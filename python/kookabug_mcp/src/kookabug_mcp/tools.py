"""MCP 도구 정의 (M5 계획 3.3). 도구 입력 JSON Schema의 단일 출처.

도구 이름·툴셋·조회/변경은 `kookabug_core.permissions.TOOLS`와 1:1이다(검사가 본다). 판정은
shim이 하지 않는다: 도구는 daemon 메서드를 부르고, daemon이 연결의 주체·툴셋으로
판정한다(꺼진 툴셋은 `toolset_disabled`). 처리기는 **그 도구 이름으로 판정되는 daemon 메서드만**
부른다(자기 연결 문서 닫기 `graph.close`만 예외) — 다른 도구로 판정되는 메서드를
돌아 쓰면 그 도구의 deny를 우회한다(`test_tool_permissions`가 본다).

처리기가 없는(None) 도구는 다음 묶음에서 붙는다 — 부르면 `isError` `not_available`.
"""

from __future__ import annotations

import contextlib
import copy
import re
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
WINDOW: Final = {"type": "string", "minLength": 1, "description": "창 제목 (정확히 같은 제목)"}
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
    permissions = _daemon(link, "permissions.get")
    installed = _daemon(link, "plugins.list")
    verdicts = {t["tool"]: t["final"] for t in permissions["tools"]}
    enabled = set(link.toolsets)
    data = {
        "workspace": {
            "root": info["root"],
            "profiles": info["profiles"],
            "plugins": info["plugins"],
            "diagnostics": info["diagnostics"],
        },
        # 설치 플러그인 (M6): ID·판·권한·환경 상태. 설치·제거·준비는 사람만 한다 (도구 없음)
        "installed_plugins": [
            {
                "id": p["id"],
                "version": p["version"],
                "title": p["manifest"].get("title"),
                "permissions": p["manifest"].get("permissions", []),
                "env": p["env"],
                "env_status": p["env_status"],
            }
            for p in installed["plugins"]
        ],
        "plugin_stale_reason": installed["stale_reason"],
        "principal": link.principal,
        "folders": FOLDERS,
        "agents_md": info.get("agents_md"),
        "toolsets": [
            {
                "name": name,
                "enabled": name in enabled,
                "tools": [d.name for d in TOOL_DEFS if d.toolset == name],
            }
            for name in TOOLSETS
        ],
        # 이 연결의 도구별 판정 요약 (인자 없는 대표 판정 — 경로 규칙은 실제 호출에서 다시 본다)
        "permissions": {d.name: verdicts.get(d.name, "deny") for d in TOOL_DEFS},
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
    listed = _daemon(link, "nodes.list")
    # 설치 플러그인의 권한·환경 상태 (M6: 환경이 준비되지 않은 플러그인 노드는 실행 전 검증 오류)
    installed = {p["id"]: p for p in listed.get("plugins", [])}
    for doc in listed["schemas"]:
        plugin = doc.get("plugin", {}).get("id")
        extra: dict[str, Any] = {}
        if plugin in installed:
            extra = {
                "plugin_permissions": installed[plugin]["permissions"],
                "plugin_env_status": installed[plugin]["env_status"],
            }
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
                **extra,
            }
            if node.get("effects"):
                item["effects"] = list(node["effects"])
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
    data = dict(status)
    summary = f"실행 {run}: {status['state']} ({verdict})"
    if status["state"] == "ended" and verdict != "pass":
        # 실패 요약: 실패 위치·오류·증거 파일·지난 성공 (비밀값은 daemon이 가린다)
        failure = _daemon(link, "run.failure", {"run_id": str(run)})
        data["failure"] = failure
        where = failure.get("failure")
        if isinstance(where, dict):
            error = where.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            summary += (
                f" · 실패 {where.get('node')} ({where.get('step')}, {code or where.get('exit')})"
            )
    return ok_result(summary, data)


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
    rect = list(args["rect"])
    # 실행 증거 출처도 target.save 하나로 (kb_target_create로만 판정, daemon이 비밀값 분류를 본다)
    crop: dict[str, Any] = (
        {"frame_id": source["frame_id"], "rect": rect}
        if "frame_id" in source
        else {"run_id": source["run"], "file": source["file"], "rect": rect}
    )
    params = {
        "path": args["path"],
        "base_revision": args.get("base_revision"),
        "spec": dict(args.get("spec") or {}),
        "crop": crop,
    }
    saved = _daemon(link, "target.save", params)
    data = {"path": args["path"], **saved}
    return ok_result(f"{args['path']}를 저장했다 (revision {saved['revision'][:12]})", data)


# ---------------------------------------------------------------- 처리기 (run·기록)


def _log_search(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"query": str(args["query"])}
    for key in ("runs", "limit"):
        if key in args:
            params[key] = args[key]
    found = _daemon(link, "run.search", params)
    note = f" · 분류 없는 기록 {len(found['skipped'])}개는 건너뜀" if found["skipped"] else ""
    return ok_result(f"일치 {len(found['matches'])}건{note}", found)


def _run_start(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"path": args["path"], "idempotency_key": args["idempotency_key"]}
    for key in ("profile", "deadline_ms", "settings", "basis"):
        if key in args:
            params[key] = args[key]
    started = _daemon(link, "run.start", params)
    data = {"run": started["run_id"], **started}
    return ok_result(
        f"실행 {started['run_id']} 시작 ({started['graph']}). kb_run_status의 wait_ms로 기다린다",
        data,
    )


def _run_cancel(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    _daemon(link, "run.cancel", {"run_id": str(args["run"])})
    return ok_result(f"실행 {args['run']} 취소를 요청했다", {"run": args["run"]})


def _run_events(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"run_id": str(args["run"])}
    for key in ("after_seq", "step", "kinds", "limit"):
        if key in args:
            params[key] = args[key]
    found = _daemon(link, "run.events", params)
    more = " (더 있음 — after_seq로 이어 받는다)" if found["truncated"] else ""
    shown = "" if found["classified"] else " · 분류 없는 옛 기록이라 안전 필드만"
    return ok_result(f"이벤트 {len(found['events'])}개{more}{shown}", found)


def _cache_file(link: DaemonLink, name: str) -> bytes:
    """daemon이 쓴 에이전트용 축소 이미지 (`.kookabug/cache/agent/<name>`) — 읽고 지운다."""
    if not re.fullmatch(r"c\d+/[0-9a-f]{16}\.png", name):
        raise ToolError("internal_error", f"daemon이 준 캐시 이름이 틀렸다: {name!r}")
    path = link.root.joinpath(".kookabug", "cache", "agent", *name.split("/"))
    try:
        return path.read_bytes()
    finally:
        with contextlib.suppress(OSError):
            path.unlink()


def _run_artifact(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    rel = str(args["path"])
    got = _daemon(link, "run.artifact", {"run_id": str(args["run"]), "path": rel})
    if got["kind"] == "image":
        data = _cache_file(link, str(got["cache"]))
        meta = {k: got[k] for k in ("path", "width", "height", "bytes")}
        return ok_result(f"{rel} ({got['width']}x{got['height']})", meta, [(data, "image/png")])
    cut = " (잘림)" if got.get("truncated") else ""
    return ok_result(f"{rel}{cut}", got)


def _run_compare(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"run_id": str(args["run"])}
    if "base" in args:
        params["baseline"] = args["base"]
    diff = _daemon(link, "run.diff", params)
    base = diff.get("baseline")
    head = f"실행 {args['run']} ↔ {base}" if base else f"실행 {args['run']}: 비교할 성공 실행 없음"
    return ok_result(head, diff)


# ---------------------------------------------------------------- 처리기 (observe)


def _window(link: DaemonLink, title: str) -> dict[str, Any]:
    """창 제목 → 창 하나 (정확히 같은 제목, 없으면 제목에 포함 — 둘 이상이면 오류)."""
    windows = _daemon(link, "windows.list")["windows"]
    exact = [w for w in windows if w["title"] == title]
    found = exact or [w for w in windows if title.casefold() in str(w["title"]).casefold()]
    if not found:
        raise ToolError("window_not_found", f"제목이 {title!r}인 창이 없다")
    if len(found) > 1:
        names = ", ".join(repr(w["title"]) for w in found[:5])
        raise ToolError("window_ambiguous", f"제목 {title!r}에 맞는 창이 여럿이다: {names}")
    return found[0]


def _screen_capture(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    title = args.get("window")
    if title is None:
        windows = _daemon(link, "windows.list")["windows"]
        listed = [
            {k: w[k] for k in ("title", "process", "pid", "client_size", "dpi")} for w in windows
        ]
        return ok_result(f"창 {len(listed)}개", {"windows": listed})
    window = _window(link, str(title))
    frame = _daemon(link, "target.capture", {"window": window["handle"]})
    data = {k: frame[k] for k in ("frame_id", "width", "height", "dpi", "client_size")}
    data["window"] = window["title"]
    protected = frame.get("protected")
    if isinstance(protected, dict):
        # 보호 중 (M7 3.5a): 이미지 없이 사유·안내만 — 탐색은 메타로 이어 간다
        data["protected"] = protected
        text = (
            f"{window['title']} 캡처 (frame_id {frame['frame_id']}) — 이미지 없음: "
            f"{protected.get('hint', '')} ({protected.get('reason', '')})"
        )
        return ok_result(text, data)
    # 이미지 축소는 daemon이 한다 (agent 연결이면 agent_image — 에이전트 캐시, 편집기 캐시와 나눔)
    shown = frame.get("agent_image")
    images = [] if shown is None else [(_cache_file(link, str(shown["cache"])), "image/png")]
    return ok_result(f"{window['title']} 캡처 (frame_id {frame['frame_id']})", data, images)


def _image_find(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    target = str(args["target"])
    opened = _daemon(link, "target.open", {"path": target})
    spec = dict(opened["spec"])
    image = spec.get("image")
    if not isinstance(image, str):
        raise ToolError("target_invalid", f"{target}에 image가 없다")
    if "threshold" in args:
        # target 사양의 임계값 자리는 match.threshold (나머지 match 설정은 그대로)
        match = spec.get("match")
        spec["match"] = {
            **(match if isinstance(match, dict) else {}),
            "threshold": args["threshold"],
        }
    result = _daemon(
        link,
        "target.preview",
        {
            "frame_id": str(args["frame_id"]),
            "spec": spec,
            "template": {"image": image},
            "base_path": target,
            "seq": 1,
        },
    )
    data = {k: result[k] for k in ("found", "match", "best", "threshold", "peaks") if k in result}
    match = result.get("match")
    if result.get("found") and isinstance(match, dict):
        head = f"{target}: 찾음 (점수 {match.get('score')}, rect {match.get('rect')})"
    else:
        best = result.get("best")
        score = best.get("score") if isinstance(best, dict) else None
        head = f"{target}: 못 찾음 (최고 점수 {score}, 임계값 {result.get('threshold')})"
    return ok_result(head, data)


def _ocr_read(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"frame_id": str(args["frame_id"])}
    if "rect" in args:
        params["rect"] = list(args["rect"])
    read = _daemon(link, "screen.read_text", params)
    return ok_result(f"글자 {len(read['lines'])}줄", read)


# ---------------------------------------------------------------- 처리기 (screens)


def _screen_list(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"under": args["under"]} if "under" in args else {}
    screens = _daemon(link, "screens.list", params)["screens"]
    return ok_result(f"화면 지도 {len(screens)}개", {"screens": screens})


def _screen_get(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    got = _daemon(link, "screens.get", {"path": str(args["path"])})
    note = f" (문제: {got['problem']})" if "problem" in got else ""
    return ok_result(f"{got['path']}{note}", got)


def _screen_identify(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    got = _daemon(link, "screens.identify", {"frame_id": str(args["frame_id"])})
    names = ", ".join(str(m.get("id") or m.get("key")) for m in got["matches"]) or "없음"
    unknown = f", 확인 못 함 {len(got['unknown'])}" if got["unknown"] else ""
    return ok_result(f"맞는 화면: {names}{unknown}", got)


def _explore_start(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {k: args[k] for k in ("title", "goal", "window", "max_steps") if k in args}
    got = _daemon(link, "explore.start", params)
    return ok_result(f"탐색 세션 {got['session']} (스텝 예산 {got['max_steps']})", got)


def _explore_end(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    got = _daemon(link, "explore.end", {})
    counts = got["counts"]
    return ok_result(
        f"탐색 세션 {got['session']} 끝: 화면 {counts['screens']} · 이동 {counts['moves']} · "
        f"미탐색 {counts['untried']}",
        got,
    )


def _screen_save(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("key", "title", "description", "kind", "frame_id", "of", "detect", "elements", "moves")
    got = _daemon(link, "screens.save", {k: args[k] for k in keys if k in args})
    note = "" if got["shot"] == "saved" else f" (스크린샷 생략: {got.get('reason', '')})"
    also = ", ".join(m["node"] for m in got["also_matches"])
    also_note = f" — 같은 화면일 수 있음: {also}" if also else ""
    return ok_result(f"{got['path']} 저장{note}{also_note}", got)


# ---------------------------------------------------------------- 처리기 (control)


def _control_done(what: str, result: Mapping[str, Any]) -> dict[str, Any]:
    data = {"run": result["run_id"], **result}
    if result["verdict"] == "pass":
        return ok_result(f"{what} 했다 (제어 실행 {result['run_id']})", data)
    error = result.get("error") or {}
    raise ToolError(
        str(error.get("code") or "control_failed"),
        f"{what} 실패 (제어 실행 {result['run_id']}, 판정 {result['verdict']}): "
        f"{error.get('message', '')}",
        run=result["run_id"],
        verdict=result["verdict"],
    )


def _input_click(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"window": args["window"]}
    for key in ("point", "target", "button", "count"):
        if key in args:
            params[key] = args[key]
    return _control_done(f"'{args['window']}' 클릭", _daemon(link, "control.click", params))


def _input_key(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"window": args["window"], "keys": args["keys"]}
    done = _daemon(link, "control.key", params)
    return _control_done(f"'{args['window']}'에 키 {args['keys']}", done)


def _input_type(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"window": args["window"]}
    for key in ("text", "secret"):
        if key in args:
            params[key] = args[key]
    what = "비밀값 입력" if "secret" in args else "글자 입력"
    return _control_done(f"'{args['window']}'에 {what}", _daemon(link, "control.type", params))


def _app_launch(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"profile": args["profile"]} if "profile" in args else {}
    launched = _daemon(link, "app.launch", params)
    return ok_result(f"게임을 띄웠다 (PID {launched['pid']})", launched)


# ---------------------------------------------------------------- 처리기 (knowledge·cases, M8)


def _knowledge_search(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {k: args[k] for k in ("query", "files", "limit") if k in args}
    found = _daemon(link, "knowledge.search", params)
    more = " (더 있음)" if found["truncated"] else ""
    return ok_result(f"지식 항목 {len(found['matches'])}개{more}", found)


def _knowledge_get(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {k: args[k] for k in ("file", "id") if k in args}
    got = _daemon(link, "knowledge.get", params)
    return ok_result(f"{got['file']} (revision {got['revision']})", got)


def _knowledge_apply(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    done = _daemon(link, "knowledge.apply", {"request_id": args["request_id"], "ops": args["ops"]})
    conflicts = len(done.get("conflicts") or [])
    note = f" · 의미 충돌 {conflicts}건 (둘 다 conflicted)" if conflicts else ""
    return ok_result(f"지식 연산 {len(args['ops'])}개를 적용했다{note}", done)


def _wiki_write(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"path": args["path"], "text": args["text"], "base_sha256": args.get("base_sha256")}
    done = _daemon(link, "wiki.write", params)
    return ok_result(f"{done['path']}를 썼다 (sha256 {done['sha256'][:12]})", done)


def _case_list(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params = {"state": args["state"]} if "state" in args else {}
    found = _daemon(link, "cases.list", params)
    return ok_result(f"사건 {len(found['cases'])}개", found)


def _case_get(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    got = _daemon(link, "cases.get", {"id": args["case"]})
    case = got["case"]
    return ok_result(f"사건 {case['id']} ({case['state']}, revision {case['revision']})", got)


def _triage_signals(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    got = _daemon(link, "cases.signals", {"id": args["case"]})
    gaps = len(got["not_comparable"])
    return ok_result(
        f"사건 {args['case']}의 판단 재료 (원인은 판정하지 않는다, 비교할 수 없는 것 {gaps}개)", got
    )


def _case_open(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"run": args["run"]}
    if "title" in args:
        params["title"] = args["title"]
    done = _daemon(link, "cases.open", params)
    what = "기존 사건에 붙였다" if done["attached"] else "새 사건을 열었다"
    return ok_result(f"{what}: {done['case']} (원래 실패 증거 {done['evidence']})", done)


def _case_update(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    done = _daemon(
        link,
        "cases.update",
        {"id": args["case"], "base_revision": args["base_revision"], "changes": args["changes"]},
    )
    return ok_result(f"사건 {done['case']}을 고쳤다 (revision {done['revision']})", done)


def _evidence_pin(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"run": args["run"], "note": args["note"]}
    if "step" in args:
        params["step"] = args["step"]
    done = _daemon(link, "evidence.pin", params)
    return ok_result(f"증거 묶음 {done['id']}를 고정했다 (파일 {len(done['files'])}개)", done)


def _adopt_request(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {"case": args["case"], "change": args["change"]}
    if args.get("negatives"):
        params["negatives"] = args["negatives"]
    done = _daemon(link, "adopt.request", params)
    if done["adopted"]:
        return ok_result(f"자동 채택했다: {done['adoption']}", done)
    failed = done.get("failed") or {}
    return ok_result(
        f"채택하지 않았다 (조건 {failed.get('condition')} {failed.get('code')}). "
        "변경은 작업 기준에 남는다",
        done,
    )


def _report_note(link: DaemonLink, args: Mapping[str, Any]) -> dict[str, Any]:
    done = _daemon(link, "job.note", {"text": args["text"]})
    return ok_result(f"작업 {done['job']} 보고 메모를 남겼다 ({done['bytes']}바이트)", done)


CASE_ID: Final = {"type": "string", "pattern": "^c-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$"}


# ---------------------------------------------------------------- 정의

TOOL_DEFS: Final[tuple[ToolDef, ...]] = (
    # core
    ToolDef(
        "kb_project_info",
        "프로젝트 정보",
        "워크스페이스 루트·프로필·플러그인(설치된 것의 권한·환경 상태)·폴더 규칙, 툴셋(켜짐 여부·"
        "도구), 이 연결의 주체. 처음에 부른다. 플러그인 설치·제거·준비는 사람만 한다",
        _schema({}),
        _project_info,
    ),
    ToolDef(
        "kb_toolset_enable",
        "툴셋 켜기",
        "툴셋을 켠다(graph_edit·run·observe·control·screens·knowledge·cases). 켠 뒤 tools/list를 "
        "다시 받는다. "
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
        "쓸 수 있는 노드 타입(제목·핀·출구·설정 이름·효과). 설치 플러그인 노드는 그 플러그인의 "
        "권한·환경 상태(ready가 아니면 실행 전 검증 오류 — 준비는 사람이 한다)",
        _schema({"query": {"type": "string"}, "category": {"type": "string"}}),
        _node_search,
    ),
    ToolDef(
        "kb_run_status",
        "실행 상태",
        "run을 주면 그 실행의 상태(wait_ms 동안 끝나기를 기다림)와, 실패했으면 실패 요약(실패 "
        "노드·오류·증거 파일·지난 성공). 없으면 최근 실행 목록. 실패 분석은 여기서 시작한다",
        _schema({"run": RUN, "wait_ms": {"type": "integer", "minimum": 0, "maximum": MAX_WAIT_MS}}),
        _run_status,
    ),
    ToolDef(
        "kb_log_search",
        "기록 찾기",
        "최근 실행 기록의 이벤트 메시지·오류·판정 사유에서 글자를 찾는다 (비밀값은 가려져 있다)",
        _schema(
            {
                "query": {"type": "string", "minLength": 1},
                "runs": {"type": "array", "items": RUN},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            ("query",),
        ),
        _log_search,
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
        "정지 화면(kb_screen_capture의 frame_id) 또는 실행 증거 이미지({run, file} — "
        "kb_run_status의 evidence)의 rect를 잘라 *.target.json을 저장한다. 새 파일이면 "
        "base_revision 없음(있으면 exists), 고치기는 base_revision 필수",
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
        "그래프를 실행한다. idempotency_key가 같으면 다시 보내도 실행 하나. basis는 실행 기준"
        "(team = 팀 파일만, working = 작업 기준 덧씌움 — 생략하면 작업 연결은 working, 그 밖은 "
        "team. qa_runner는 team만)",
        _schema(
            {
                "path": PATH,
                "idempotency_key": {"type": "string", "minLength": 1},
                "profile": {"type": "string"},
                "deadline_ms": {"type": "integer", "minimum": 1},
                "settings": {"type": "object"},
                "basis": {"enum": ["team", "working"]},
            },
            ("path", "idempotency_key"),
        ),
        _run_start,
    ),
    ToolDef(
        "kb_run_cancel",
        "실행 취소",
        "실행을 취소한다",
        _schema({"run": RUN}, ("run",)),
        _run_cancel,
    ),
    ToolDef(
        "kb_run_events",
        "실행 이벤트",
        "실행 이벤트 (seq 순). 비밀값이 든 필드는 ***, 분류 없는 옛 기록은 판정·노드·출구·"
        "오류 코드·시각만. step·kinds(예: step.end, log)로 거른다",
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
        _run_events,
    ),
    ToolDef(
        "kb_run_artifact_get",
        "실행 증거",
        "실행 폴더의 증거 파일(steps/·thumbs/ 이미지·글자, video/index.json). 이미지는 image "
        "내용으로 준다. 비밀값을 다룬 스텝의 증거와 영상 조각은 주지 않는다",
        _schema(
            {"run": RUN, "path": {**PATH, "description": "실행 폴더 기준 경로 ('/')"}},
            ("run", "path"),
        ),
        _run_artifact,
    ),
    ToolDef(
        "kb_run_compare",
        "지난 성공과 비교",
        "실행을 지난 성공(또는 base)과 비교: 그래프·환경·시간·실패 화면 차이",
        _schema({"run": RUN, "base": RUN}, ("run",)),
        _run_compare,
    ),
    # observe
    ToolDef(
        "kb_screen_capture",
        "화면 캡처",
        "window(창 제목)를 주면 그 창을 캡처(frame_id·이미지), 없으면 창 목록. 민감 대상이 "
        "보이거나 비밀값을 입력한 칸이 남은 화면은 이미지 없이 protected(사유·안내)만 준다",
        _schema({"window": WINDOW}),
        _screen_capture,
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
        _image_find,
    ),
    ToolDef(
        "kb_ocr_read",
        "글자 읽기",
        "정지 화면의 글자 (sensitive target이 보이는 화면·비밀값을 입력한 칸이 남은 화면은 거부)",
        _schema({"frame_id": {"type": "string", "minLength": 1}, "rect": RECT}, ("frame_id",)),
        _ocr_read,
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
        _input_click,
    ),
    ToolDef(
        "kb_input_key",
        "키 누르기",
        "키 조합을 한 번 누르고 뗀다 (누른 채 두기 없음)",
        _schema({"window": WINDOW, "keys": {"type": "string", "minLength": 1}}, ("window", "keys")),
        _input_key,
    ),
    ToolDef(
        "kb_input_type",
        "글자 입력",
        "글자를 입력한다. secret을 주면 그 비밀값(키 이름)을 입력하고 값은 돌려주지 않는다. "
        "비밀값 칸은 kb_input_click(point)으로 누른 뒤 10초 안에 입력한다 — 아니면 그 창이 닫힐 "
        "때까지 kb_screen_capture 이미지가 오지 않는다",
        _schema(
            {
                "window": WINDOW,
                "text": {"type": "string"},
                "secret": daemon_def("SecretKey"),
            },
            ("window",),
        ),
        _input_type,
    ),
    ToolDef(
        "kb_app_launch",
        "게임 실행",
        "프로필의 게임을 띄운다 (설정 game.executable·game.args. 실행·녹화 중이면 거부)",
        _schema({"profile": {"type": "string"}}),
        _app_launch,
    ),
    # screens
    ToolDef(
        "kb_screen_list",
        "화면 지도 목록",
        "screens/ 아래 *.screen.json 목록",
        _schema({"under": {"type": "string"}}),
        _screen_list,
    ),
    ToolDef(
        "kb_screen_get",
        "화면 지도",
        "*.screen.json 내용",
        _schema({"path": PATH}, ("path",)),
        _screen_get,
    ),
    ToolDef(
        "kb_screen_identify",
        "화면 식별",
        "정지 화면(kb_screen_capture의 frame_id)이 어느 화면인지 — 확정 화면과 이 탐색 세션의 "
        "후보. 처음 보는 화면이면 kb_screen_save로 저장한다",
        _schema({"frame_id": {"type": "string", "minLength": 1}}, ("frame_id",)),
        _screen_identify,
    ),
    ToolDef(
        "kb_explore_start",
        "탐색 시작",
        "게임 화면 탐색 세션을 연다 (결과는 screens/_explored/<세션>/, 사람이 확인해 옮긴다). "
        "순서: 캡처 → kb_screen_identify → 처음이면 kb_screen_save → 입력 → 반복 → "
        "kb_explore_end. 되돌릴 수 없는 동작(구매·삭제)은 누르지 말고 moves에 untried로 남긴다. "
        "비밀값 칸은 kb_input_click(point)으로 누른 뒤 입력한다",
        _schema(
            {
                "title": {"type": "string", "minLength": 1},
                "goal": {"type": "string"},
                "window": {"type": "string"},
                "max_steps": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            ("title",),
        ),
        _explore_start,
    ),
    ToolDef(
        "kb_explore_end",
        "탐색 끝",
        "이 연결의 탐색 세션을 끝낸다",
        _schema({}),
        _explore_end,
    ),
    ToolDef(
        "kb_screen_save",
        "화면 저장",
        "탐색 세션의 후보 화면 카드를 저장·갱신한다 (key = 새 화면 ID 후보, 좌표는 프레임 픽셀). "
        "detect는 image(영역을 잘라 조건) 또는 ocr(영역 + 글자), moves는 via(click element·point "
        "또는 key)·to(화면 키)·status(tried·untried). 보호 중인 화면은 조건·스크린샷 없이만 "
        "저장된다",
        daemon_def("ScreensSaveParams"),
        _screen_save,
    ),
    # knowledge (M8 3.3·3.14)
    ToolDef(
        "kb_knowledge_search",
        "지식 찾기",
        "주장·경험칙·치트·미지수의 ID·글자에서 찾는다 (공백·대소문자 무시)",
        daemon_def("Kb8KnowledgeSearchParams"),
        _knowledge_search,
    ),
    ToolDef(
        "kb_knowledge_get",
        "지식 읽기",
        "지식 파일(features/<기능>·lessons·cheats·unknowns) 또는 그 항목 하나와 revision. 주장 "
        "파일은 작업 기준 덧씌움(working)도 준다. 고칠 때 revision·rev를 base로 준다",
        daemon_def("Kb8KnowledgeGetParams"),
        _knowledge_get,
    ),
    ToolDef(
        "kb_knowledge_apply",
        "지식 연산",
        "제한 연산(add·revise·supersede·mark_conflicted·attach_evidence·set_status) 묶음을 "
        "원자로 적용한다. 근거 형식은 source·evidence·run뿐(human은 사람만, 위키·주장 인용 없음). "
        "expected 주장의 고치기는 작업 기준에 남고 사람이 수락한다. 같은 request_id는 지난 결과",
        daemon_def("Kb8KnowledgeApplyParams"),
        _knowledge_apply,
    ),
    ToolDef(
        "kb_wiki_write",
        "위키 쓰기",
        "산문 위키 페이지(wiki/**/*.md, index·log·reports 제외)를 쓴다. 새 파일은 base_sha256 "
        "null. 판정 근거로 쓰이지 않는다",
        daemon_def("Kb8WikiWriteParams"),
        _wiki_write,
    ),
    # cases (M8 3.2·3.8·3.14)
    ToolDef(
        "kb_case_list",
        "사건 목록",
        "조사 사건 목록 (상태·증상·실행 수)",
        daemon_def("Kb8CasesListParams"),
        _case_list,
    ),
    ToolDef(
        "kb_case_get",
        "사건 읽기",
        "사건 하나 (원래 실패·가설·필요 정보·연결). 고칠 때 revision을 base_revision으로 준다",
        _schema({"case": CASE_ID}, ("case",)),
        _case_get,
    ),
    ToolDef(
        "kb_triage_signals",
        "조사 신호",
        "사건의 판단 재료: 지난 성공과 비교·실패 화면 식별·변경 없는 재실행 결과·원본 변화·관련 "
        "주장. 원인은 판정하지 않는다 (not_comparable에 비교할 수 없는 이유)",
        _schema({"case": CASE_ID}, ("case",)),
        _triage_signals,
    ),
    ToolDef(
        "kb_case_open",
        "사건 열기",
        "실패 실행으로 사건을 연다. 원래 실패 증거는 Kookabug가 고정한다. 같은 시그니처의 열린 "
        "사건이 있으면 그 사건에 붙이고 지난 가설을 준다(같은 원인 확정은 아님)",
        daemon_def("Kb8CasesOpenParams"),
        _case_open,
    ),
    ToolDef(
        "kb_case_update",
        "사건 고치기",
        "사건의 제목·상태(open·needs_info·watching)·가설·조치·필요 정보·재확인·연결을 고친다. "
        "resolved·closed는 자동 채택이나 사람만 (case_resolution_reserved)",
        _schema(
            {
                "case": CASE_ID,
                "base_revision": {"type": "integer", "minimum": 1},
                "changes": {"type": "object"},
            },
            ("case", "base_revision", "changes"),
        ),
        _case_update,
    ),
    ToolDef(
        "kb_evidence_pin",
        "증거 고정",
        "실행 기록에서 최소 증거 묶음을 고정한다 (가린 안전 필드·보호 아닌 이미지 480px). 지우거나 "
        "고치는 도구는 없다",
        daemon_def("Kb8EvidencePinParams"),
        _evidence_pin,
    ),
    ToolDef(
        "kb_adopt_request",
        "자동 채택 요청",
        "사건의 작업 기준 변경(target 제자리 수리) 하나를 자동 채택 조건 1~8로 검사해 팀에 "
        "게시한다. 검증 실행은 Kookabug가 고르고 돌린다. 실패해도 변경은 작업 기준에 남는다",
        daemon_def("Kb8AdoptRequestParams"),
        _adopt_request,
    ),
    ToolDef(
        "kb_report_note",
        "보고 메모",
        "이 작업 보고의 요약 글 (4 KB, 작업 연결 전용). 보고 항목은 Kookabug가 기록에서 만든다",
        daemon_def("Kb8JobNoteParams"),
        _report_note,
    ),
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
