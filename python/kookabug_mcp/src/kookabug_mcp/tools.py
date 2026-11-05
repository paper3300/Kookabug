"""MCP 도구 정의 (M5 계획 3.3). 도구 입력 JSON Schema의 단일 출처.

도구 이름·툴셋·조회/변경은 `kookabug_core.permissions.TOOLS`와 1:1이다(M7로 미룬 `kb_screen_save`
제외 — 검사가 본다). 판정은 shim이 하지 않는다: 도구는 daemon 메서드를 부르고, daemon이 연결의
주체·툴셋으로 판정한다(꺼진 툴셋은 `toolset_disabled`). 처리기는 **그 도구 이름으로 판정되는
daemon 메서드만** 부른다(자기 연결 문서 닫기 `graph.close`만 예외) — 다른 도구로 판정되는 메서드를
돌아 쓰면 그 도구의 deny를 우회한다(`test_tool_permissions`가 본다).

처리기가 없는(None) 도구는 다음 묶음에서 붙는다 — 부르면 `isError` `not_available`.
"""

from __future__ import annotations

import contextlib
import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from kookabug_core.permissions import TOOLS, TOOLSETS
from kookabug_core.schema import metaschema
from kookabug_daemon.client import DaemonError
from kookabug_mcp.daemon_link import DaemonLink
from kookabug_mcp.results import ToolError, from_daemon_error, ok_result

__all__ = ["FOLDERS", "TOOL_DEFS", "ToolDef", "by_name", "call_tool", "listed"]

type Handler = Callable[[DaemonLink, Mapping[str, Any]], dict[str, Any]]

FOLDERS: Final = {
    "tests/": "테스트 그래프 (*.graph.json, kind test)",
    "subgraphs/": "서브그래프 (*.graph.json, kind subgraph)",
    "targets/": "찾기 대상 (*.target.json + PNG)",
    "screens/": "화면 지도 (*.screen.json, screens 툴셋)",
    "runs/": "실행 기록 (읽기 전용, run 툴셋)",
}
WAIT_STEP_S: Final = 0.2
MAX_WAIT_MS: Final = 30_000


@dataclass(frozen=True, slots=True)
class ToolDef:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    handler: Handler | None = None

    @property
    def toolset(self) -> str:
        return TOOLS[self.name].toolset

    @property
    def read_only(self) -> bool:
        return not TOOLS[self.name].mutating

    def listing(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.input_schema,
            "annotations": {"title": self.title, "readOnlyHint": self.read_only},
        }


# ---------------------------------------------------------------- 입력 스키마 조각


def _schema(properties: Mapping[str, Any], required: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties),
        "additionalProperties": False,
    }
    if required:
        out["required"] = list(required)
    return out


def _inline(value: Any, defs: Mapping[str, Any]) -> Any:
    """`#/$defs/X` 참조를 풀어 넣는다 (MCP 클라이언트에는 참조 없는 스키마를 준다)."""
    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            return _inline(defs[ref.removeprefix("#/$defs/")], defs)
        return {k: _inline(v, defs) for k, v in value.items()}
    if isinstance(value, list):
        return [_inline(v, defs) for v in value]
    return value


def daemon_def(name: str) -> dict[str, Any]:
    """daemon 계약(`daemon-rpc.schema.json`)의 정의 하나를 참조 없이 (모양의 단일 출처는 계약)."""
    defs = metaschema("daemon-rpc")["$defs"]
    return _inline(copy.deepcopy(defs[name]), defs)


@cache
def patch_op_schema() -> dict[str, Any]:
    """`graph.patch` 연산 하나의 스키마 (daemon 계약 `GraphPatchOp`)."""
    return daemon_def("GraphPatchOp")


PATH: Final = {"type": "string", "minLength": 1, "description": "워크스페이스 루트 기준 경로 ('/')"}
REVISION: Final = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
RUN: Final = {"type": "string", "minLength": 1, "description": "실행 ID (kb_run_status의 run)"}
RECT: Final = {
    "type": "array",
    "items": {"type": "integer"},
    "minItems": 4,
    "maxItems": 4,
    "description": "[x, y, w, h] 클라이언트 영역 물리 픽셀",
}
WINDOW: Final = {"type": "string", "minLength": 1, "description": "창 제목"}
POINT: Final = {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2}


def _ops(min_items: int) -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": min_items,
        "maxItems": 1000,
        "items": patch_op_schema(),
        "description": "모두 적용하거나 하나도 안 한다. id·from·to에는 같은 묶음 add_node의 ref도 "
        "쓸 수 있다",
    }


# ---------------------------------------------------------------- 처리기 (core)


def _daemon(link: DaemonLink, method: str, params: Mapping[str, Any] | None = None) -> Any:
    return link.call(method, params)


def _project_info(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    # daemon 메서드는 kb_project_info로 판정되는 것만 부른다. 켜진 툴셋은 이 연결에서 켠 것을
    # shim이 기억한다(붙을 때·켤 때 daemon이 알려 준 값)
    info = _daemon(link, "workspace.info")
    enabled = set(link.toolsets)
    data = {
        "workspace": {
            "root": info["root"],
            "profiles": info["profiles"],
            "plugins": info["plugins"],
            "diagnostics": info["diagnostics"],
        },
        "principal": link.principal,
        "folders": FOLDERS,
        "toolsets": [
            {
                "name": name,
                "enabled": name in enabled,
                "tools": [d.name for d in TOOL_DEFS if d.toolset == name],
            }
            for name in TOOLSETS
        ],
    }
    on = ", ".join(t for t in TOOLSETS if t in enabled)
    return ok_result(f"워크스페이스 {info['root']} · 켜진 툴셋 {on}", data)


def _toolset_enable(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    result = link.enable(list(args["toolsets"]))
    names = {d.name for d in TOOL_DEFS}
    tools = [t for t in result["tools"] if t in names]
    data = {"enabled": result["enabled"], "tools": tools}
    note = "tools/list를 다시 받으면 새 도구가 보인다" if tools else "새로 켠 툴셋이 없다"
    return ok_result(f"켜진 툴셋 {', '.join(result['enabled'])} · {note}", data)


def _graph_list(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"under": args["under"]} if "under" in args else {}
    graphs = _daemon(link, "graph.list", params)["graphs"]
    return ok_result(f"그래프 {len(graphs)}개", {"graphs": graphs})


def _close(link: DaemonLink, opened: Mapping[str, Any]) -> None:
    """에이전트가 연 문서를 표에 남기지 않는다 (이미 닫혔으면 그대로)."""
    with contextlib.suppress(DaemonError):
        _daemon(link, "graph.close", {"doc_id": opened["doc_id"]})


def _opened(link: DaemonLink, path: str) -> dict[str, Any]:
    """`graph.open` 결과 (바로 닫는다)."""
    opened = _daemon(link, "graph.open", {"path": path})
    _close(link, opened)
    return opened


def _graph_get(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    opened = _opened(link, str(args["path"]))
    data = {
        "path": args["path"],
        "revision": opened["revision"],
        "value": opened["value"],
        "diagnostics": opened["diagnostics"],
        "read_only": bool(opened.get("read_only", False)),
    }
    errors = sum(1 for d in opened["diagnostics"] if d.get("severity") == "error")
    return ok_result(f"{args['path']} (revision {opened['revision'][:12]}, 오류 {errors})", data)


def _graph_validate(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"path": str(args["path"])}
    if "value" in args:
        params["value"] = args["value"]
    diagnostics = _daemon(link, "graph.check", params)["diagnostics"]
    errors = sum(1 for d in diagnostics if d.get("severity") == "error")
    return ok_result(f"진단 {len(diagnostics)}건 (오류 {errors})", {"diagnostics": diagnostics})


def _pins(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            name: (pin.get("type") if isinstance(pin, dict) else pin) for name, pin in value.items()
        }
    return value  # 인터페이스에서 정함


def _exits(value: Any) -> Any:
    if isinstance(value, list):
        return [e.get("name") if isinstance(e, dict) else e for e in value]
    return value


def _node_search(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    query = str(args.get("query", "")).casefold()
    category = args.get("category")
    found: list[dict[str, Any]] = []
    for doc in _daemon(link, "nodes.list")["schemas"]:
        plugin = doc.get("plugin", {}).get("id")
        for node in doc.get("nodes", []):
            if category is not None and node.get("category") != category:
                continue
            text = " ".join(
                str(node.get(k, "")) for k in ("type", "title", "description", "category")
            )
            if query and query not in text.casefold():
                continue
            item: dict[str, Any] = {
                "type": node["type"],
                "version": node["version"],
                "title": node.get("title"),
                "plugin": plugin,
            }
            for key in ("category", "description"):
                if key in node:
                    item[key] = node[key]
            if node.get("pure"):
                item["pure"] = True
            item["inputs"] = _pins(node.get("inputs", {}))
            item["outputs"] = _pins(node.get("outputs", {}))
            if "exits" in node:
                item["exits"] = _exits(node["exits"])
            if "config" in node:
                item["config"] = sorted(node["config"])
            found.append(item)
    return ok_result(f"노드 타입 {len(found)}개", {"nodes": found})


def _run_status(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    run = args.get("run")
    if run is None:
        runs = _daemon(link, "run.list", {"limit": 10})
        return ok_result(f"최근 실행 {len(runs['runs'])}개", runs)
    wait_ms = min(int(args.get("wait_ms", 0)), MAX_WAIT_MS)
    deadline = time.monotonic() + wait_ms / 1000
    while True:
        status = _daemon(link, "run.status", {"run_id": str(run)})
        if status["state"] == "ended" or time.monotonic() >= deadline:
            break
        time.sleep(WAIT_STEP_S)
    outcome = status.get("outcome") or {}
    verdict = outcome.get("verdict", "진행 중") if isinstance(outcome, dict) else "진행 중"
    return ok_result(f"실행 {run}: {status['state']} ({verdict})", status)


# ---------------------------------------------------------------- 처리기 (graph_edit)


def _graph_create(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    # 연산은 daemon이 쓰기 전에 틀에 적용한다 (판정은 kb_graph_create 하나, 틀리면 만들지 않음)
    path = str(args["path"])
    params: dict[str, Any] = {"path": path, "kind": args["kind"]}
    for key in ("title", "ops"):
        if args.get(key):
            params[key] = args[key]
    opened = _daemon(link, "graph.create", params)
    _close(link, opened)
    data: dict[str, Any] = {
        "path": path,
        "revision": opened["revision"],
        "created": opened.get("created", {}),
        "diagnostics": opened["diagnostics"],
    }
    return ok_result(f"{path}를 만들었다 (revision {data['revision'][:12]})", data)


def _graph_patch(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    result = _daemon(
        link,
        "graph.patch",
        {"path": args["path"], "base_revision": args["base_revision"], "ops": args["ops"]},
    )
    data = {"path": args["path"], **result}
    errors = sum(1 for d in result["diagnostics"] if d.get("severity") == "error")
    return ok_result(
        f"{args['path']}를 고쳤다 (revision {result['revision'][:12]}, 진단 오류 {errors})", data
    )


def _target_create(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    source = args["source"]
    if "frame_id" not in source:
        raise ToolError("not_available", "실행 기록 이미지 출처({run, file})는 아직 없다")
    params = {
        "path": args["path"],
        "base_revision": args.get("base_revision"),
        "spec": dict(args.get("spec") or {}),
        "crop": {"frame_id": source["frame_id"], "rect": list(args["rect"])},
    }
    saved = _daemon(link, "target.save", params)
    data = {"path": args["path"], **saved}
    return ok_result(f"{args['path']}를 저장했다 (revision {saved['revision'][:12]})", data)


# ---------------------------------------------------------------- 정의

TOOL_DEFS: Final[tuple[ToolDef, ...]] = (
    # core
    ToolDef(
        "kb_project_info",
        "프로젝트 정보",
        "워크스페이스 루트·프로필·플러그인·폴더 규칙, 툴셋(켜짐 여부·도구), 이 연결의 주체. "
        "처음에 부른다",
        _schema({}),
        _project_info,
    ),
    ToolDef(
        "kb_toolset_enable",
        "툴셋 켜기",
        "툴셋을 켠다(graph_edit·run·observe·control·screens). 켠 뒤 tools/list를 다시 받는다. "
        "켜도 도구마다의 권한은 그대로다",
        _schema(
            {
                "toolsets": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"enum": list(TOOLSETS)},
                    "uniqueItems": True,
                }
            },
            ("toolsets",),
        ),
        _toolset_enable,
    ),
    ToolDef(
        "kb_graph_list",
        "그래프 목록",
        "*.graph.json 목록(경로·종류·제목)",
        _schema({"under": {"type": "string", "description": "이 폴더 아래만 (예: tests)"}}),
        _graph_list,
    ),
    ToolDef(
        "kb_graph_get",
        "그래프 읽기",
        "그래프 값·revision·진단. 고칠 때는 이 revision을 kb_graph_patch의 base_revision으로 준다",
        _schema({"path": PATH}, ("path",)),
        _graph_get,
    ),
    ToolDef(
        "kb_graph_validate",
        "그래프 검증",
        "그래프 진단. value를 주면 디스크 대신 그 값을 검증한다(저장하지 않음)",
        _schema({"path": PATH, "value": {"type": "object"}}, ("path",)),
        _graph_validate,
    ),
    ToolDef(
        "kb_node_search",
        "노드 찾기",
        "쓸 수 있는 노드 타입(제목·핀·출구·설정 이름)",
        _schema({"query": {"type": "string"}, "category": {"type": "string"}}),
        _node_search,
    ),
    ToolDef(
        "kb_run_status",
        "실행 상태",
        "run을 주면 그 실행의 상태(wait_ms 동안 끝나기를 기다림), 없으면 최근 실행 목록",
        _schema({"run": RUN, "wait_ms": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS}}),
        _run_status,
    ),
    ToolDef(
        "kb_log_search",
        "기록 찾기",
        "최근 실행 기록의 이벤트 메시지·오류에서 글자를 찾는다",
        _schema(
            {
                "query": {"type": "string", "minLength": 1},
                "runs": {"type": "array", "items": RUN},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ("query",),
        ),
    ),
    # graph_edit
    ToolDef(
        "kb_graph_create",
        "그래프 만들기",
        "새 그래프 파일(시작 노드만 있는 틀). ops를 주면 만든 뒤 kb_graph_patch와 같이 고친다",
        _schema(
            {
                "path": PATH,
                "kind": {"enum": ["test", "subgraph"]},
                "title": {"type": "string"},
                "ops": _ops(0),
            },
            ("path", "kind"),
        ),
        _graph_create,
    ),
    ToolDef(
        "kb_graph_patch",
        "그래프 고치기",
        "연산 묶음으로 그래프를 고친다(모두 적용 또는 하나도 안 함). base_revision이 디스크와 "
        "다르면 revision_conflict — kb_graph_get으로 다시 읽는다. 노드 ID는 바꿀 수 없다",
        _schema(
            {"path": PATH, "base_revision": REVISION, "ops": _ops(1)},
            ("path", "base_revision", "ops"),
        ),
        _graph_patch,
    ),
    ToolDef(
        "kb_target_create",
        "찾기 대상 만들기",
        "정지 화면(kb_screen_capture의 frame_id)의 rect를 잘라 *.target.json을 저장한다. 새 "
        "파일이면 base_revision 없음(있으면 exists), 고치기는 base_revision 필수",
        _schema(
            {
                "path": PATH,
                "source": {
                    "type": "object",
                    "oneOf": [
                        _schema({"frame_id": {"type": "string", "minLength": 1}}, ("frame_id",)),
                        _schema({"run": RUN, "file": PATH}, ("run", "file")),
                    ],
                },
                "rect": RECT,
                "spec": {"type": "object", "description": "target 사양 (없으면 기본값)"},
                "base_revision": {
                    "anyOf": [daemon_def("TargetRevision"), {"type": "null"}],
                    "description": "고칠 때 지금 revision (exists 오류가 알려 준다)",
                },
            },
            ("path", "source", "rect"),
        ),
        _target_create,
    ),
    # run
    ToolDef(
        "kb_run_start",
        "실행 시작",
        "그래프를 실행한다. idempotency_key가 같으면 다시 보내도 실행 하나",
        _schema(
            {
                "path": PATH,
                "idempotency_key": {"type": "string", "minLength": 1},
                "profile": {"type": "string"},
                "deadline_ms": {"type": "integer", "minimum": 1},
                "settings": {"type": "object"},
            },
            ("path", "idempotency_key"),
        ),
    ),
    ToolDef("kb_run_cancel", "실행 취소", "실행을 취소한다", _schema({"run": RUN}, ("run",))),
    ToolDef(
        "kb_run_events",
        "실행 이벤트",
        "실행 이벤트 (비밀값은 가려짐)",
        _schema(
            {
                "run": RUN,
                "after_seq": {"type": "integer", "minimum": 0},
                "step": {"type": "string"},
                "kinds": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ("run",),
        ),
    ),
    ToolDef(
        "kb_run_artifact_get",
        "실행 증거",
        "실행 폴더의 이미지·글자 파일",
        _schema({"run": RUN, "path": PATH}, ("run", "path")),
    ),
    # observe
    ToolDef(
        "kb_screen_capture",
        "화면 캡처",
        "window를 주면 그 창을 캡처(frame_id·이미지), 없으면 창 목록",
        _schema({"window": WINDOW}),
    ),
    ToolDef(
        "kb_image_find",
        "이미지 찾기",
        "정지 화면에서 target을 찾는다",
        _schema(
            {
                "frame_id": {"type": "string", "minLength": 1},
                "target": PATH,
                "threshold": {"type": "number", "minimum": 0, "maximum": 1},
            },
            ("frame_id", "target"),
        ),
    ),
    ToolDef(
        "kb_ocr_read",
        "글자 읽기",
        "정지 화면의 글자 (sensitive target 영역은 거부)",
        _schema({"frame_id": {"type": "string", "minLength": 1}, "rect": RECT}, ("frame_id",)),
    ),
    # control
    ToolDef(
        "kb_input_click",
        "클릭",
        "게임 창을 클릭한다 (point 또는 target)",
        _schema(
            {
                "window": WINDOW,
                "point": POINT,
                "target": PATH,
                "button": {"enum": ["left", "right", "middle"]},
                "count": {"type": "integer", "minimum": 1, "maximum": 3},
            },
            ("window",),
        ),
    ),
    ToolDef(
        "kb_input_key",
        "키 누르기",
        "키 조합을 한 번 누르고 뗀다 (누른 채 두기 없음)",
        _schema({"window": WINDOW, "keys": {"type": "string", "minLength": 1}}, ("window", "keys")),
    ),
    ToolDef(
        "kb_input_type",
        "글자 입력",
        "글자를 입력한다. secret을 주면 그 비밀값(키 이름)을 입력하고 값은 돌려주지 않는다",
        _schema(
            {"window": WINDOW, "text": {"type": "string"}, "secret": {"type": "string"}},
            ("window",),
        ),
    ),
    ToolDef(
        "kb_app_launch",
        "게임 실행",
        "프로필의 게임을 띄운다 (실행·녹화 중이면 거부)",
        _schema({"profile": {"type": "string"}}),
    ),
    # screens
    ToolDef(
        "kb_screen_list",
        "화면 지도 목록",
        "*.screen.json 목록",
        _schema({"under": {"type": "string"}}),
    ),
    ToolDef("kb_screen_get", "화면 지도", "*.screen.json 내용", _schema({"path": PATH}, ("path",))),
)


@cache
def by_name() -> dict[str, ToolDef]:
    return {d.name: d for d in TOOL_DEFS}


def listed(toolsets: frozenset[str]) -> list[dict[str, Any]]:
    """`tools/list`: 켜진 툴셋의 도구."""
    return [d.listing() for d in TOOL_DEFS if d.toolset in toolsets]


def call_tool(link: DaemonLink, tool: ToolDef, args: Mapping[str, Any]) -> dict[str, Any]:
    """도구 하나 → MCP 결과. daemon 오류(권한·툴셋 꺼짐 포함)는 `isError` 결과다. 툴셋·권한은
    daemon이 메서드마다 판정한다 — shim은 판정하지 않는다."""
    if tool.handler is None:
        raise ToolError("not_available", f"{tool.name}은(는) 이 판에 아직 없다")
    try:
        return tool.handler(link, args)
    except DaemonError as exc:
        return from_daemon_error(exc)
