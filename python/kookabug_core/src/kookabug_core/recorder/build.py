"""녹화 스텝의 노드 초안 → 커밋 조각, 조각 → 그래프 (M4 계획 2.7 "동작 → 노드"·"조각의 맨 앞·끝",
2.9 조각, C8·C9·C10, T6).

- 동작 하나 = 노드 초안 하나 이상(`NodeDraft`). 끌기는 `image.wait` + `input.drag`(시작 = 앞 노드의
  `match`)이라 초안의 `$link`는 `@prev.<출력>`으로 적고 조각을 만들 때 로컬 ID로 바꾼다
- **새 테스트**: 현재 대상 창을 정하는 노드로 시작한다 — 게임 띄워서 녹화했으면 `core.app.launch`
  (워크스페이스 `game.*` `$setting`), 떠 있는 창이면 `core.window.attach {title}`. 검증 노드가
  없으면 끝에 `core.test.pass` + 경고 `no_assertion`
- **삽입**: 맨 앞 창 노드·종료 노드 없이 **열린 끝점**(마지막 노드의 첫 ok 출구)
- 비밀값 구간 글자는 `{"$secret": 키}`로만 들어온다 (원문은 `RecorderTexts.graph_text`가 막음)

`apply_fragment`는 렌더러 `insertFragment`와 같은 규칙의 파이썬 판(검사·daemon 쪽 확인용):
로컬 ID → 새 노드 ID, `$link`·`next`를 같이 바꾸고, 고른 출구의 원래 대상을 열린 끝으로 옮긴다.
"""

from __future__ import annotations

import copy
import secrets as _random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from kookabug_core.recorder.fragment import fragment_problems

__all__ = [
    "LAUNCH_SETTINGS",
    "FragmentError",
    "NodeDraft",
    "apply_fragment",
    "attach_draft",
    "build_fragment",
    "check_text_draft",
    "check_visible_draft",
    "click_drafts",
    "delay_draft",
    "drag_drafts",
    "key_draft",
    "launch_draft",
    "new_node_id",
    "scroll_draft",
    "text_draft",
    "wait_draft",
]

LAUNCH_SETTINGS: Final = {
    "path": "game.executable",
    "args": "game.args",
    "cwd": "game.cwd",
    "window_title": "game.title",
}
"""`core.app.launch` 입력 ← 워크스페이스 설정 (예제 `enter_world`와 같다)."""
_ID_ALPHABET: Final = "abcdefghijklmnopqrstuvwxyz234567"
_PREV: Final = "@prev."


class FragmentError(Exception):
    """조각을 만들 수 없다 (규칙 위반 — 만드는 쪽의 버그)."""


@dataclass(frozen=True, slots=True)
class NodeDraft:
    type: str
    title: str
    ok_exit: str
    """다음 노드로 잇는 출구 (실행 차례)."""
    inputs: Mapping[str, Any] = field(default_factory=dict[str, Any])
    config: Mapping[str, Any] | None = None
    version: int = 1

    @property
    def is_assertion(self) -> bool:
        return self.type.startswith("core.assert.")


def click_drafts(
    target: str,
    name: str,
    *,
    button: str = "left",
    count: int = 1,
    timeout_ms: int | None = None,
) -> list[NodeDraft]:
    """클릭 → `core.image.click` (스스로 기다린다). `name`은 보호 규칙을 거친 이름이다."""
    inputs: dict[str, Any] = {"target": {"$target": target}}
    if button != "left":
        inputs["button"] = button
    if count != 1:
        inputs["count"] = count
    if timeout_ms is not None and timeout_ms != 10000:
        inputs["timeout_ms"] = timeout_ms
    return [NodeDraft("core.image.click", f'이미지 클릭 "{name}"', "done", inputs)]


def wait_draft(target: str, name: str, timeout_ms: int) -> NodeDraft:
    return NodeDraft(
        "core.image.wait",
        f'나타날 때까지 대기 "{name}"',
        "found",
        {"target": {"$target": target}, "timeout_ms": timeout_ms},
    )


def delay_draft(ms: int) -> NodeDraft:
    return NodeDraft("core.flow.delay", f"{ms} ms 기다리기", "done", {"ms": ms})


def drag_drafts(
    start_target: str, name: str, end: Sequence[int], duration_ms: int, timeout_ms: int
) -> list[NodeDraft]:
    """끌기 → 누른 자리 `image.wait` + `input.drag {start: 앞 노드 match, end: [x, y]}`.
    끝점은 픽셀 상수다 (U11)."""
    return [
        wait_draft(start_target, name, timeout_ms),
        NodeDraft(
            "core.input.drag",
            "끌기",
            "done",
            {
                "start": {"$link": f"{_PREV}match"},
                "end": [int(end[0]), int(end[1])],
                "duration_ms": duration_ms,
            },
        ),
    ]


def scroll_draft(point: Sequence[int], amount: int) -> NodeDraft:
    return NodeDraft(
        "core.input.scroll",
        "휠",
        "done",
        {"point": [int(point[0]), int(point[1])], "amount": amount},
    )


def key_draft(keys: str, hold_ms: int | None = None) -> NodeDraft:
    inputs: dict[str, Any] = {"keys": keys}
    if hold_ms:
        inputs["hold_ms"] = hold_ms
    return NodeDraft("core.input.key", f"키 입력 {keys}", "done", inputs)


def text_draft(text: str | Mapping[str, str], *, clear: bool) -> NodeDraft:
    """글자 → target 없는 `type_text` (칸 클릭은 앞 `image.click`이 기다리며 누른다, C10).
    제목에는 글자를 넣지 않는다 — 비밀값·일반 모두 `in.text`에만 있다."""
    value: Any = dict(text) if isinstance(text, Mapping) else text
    title = "비밀값 입력" if isinstance(text, Mapping) else "글자 입력"
    return NodeDraft("core.input.type_text", title, "done", {"text": value, "clear": clear})


def check_visible_draft(target: str, name: str) -> NodeDraft:
    return NodeDraft(
        "core.assert.visible", f'화면 확인 "{name}"', "ok", {"target": {"$target": target}}
    )


def check_text_draft(target: str, name: str, equals: str) -> NodeDraft:
    return NodeDraft(
        "core.assert.text",
        f'문구 확인 "{name}"',
        "ok",
        {"region": {"$target": target}, "equals": equals},
    )


def launch_draft() -> NodeDraft:
    return NodeDraft(
        "core.app.launch",
        "게임 실행",
        "attached",
        {**{pin: {"$setting": key} for pin, key in LAUNCH_SETTINGS.items()}, "timeout_ms": 30000},
    )


def attach_draft(title: str) -> NodeDraft:
    return NodeDraft("core.window.attach", "창에 붙기", "found", {"title": title})


def _replace_prev(value: Any, prev: str | None) -> Any:
    if isinstance(value, list):
        items: list[Any] = value
        return [_replace_prev(v, prev) for v in items]
    if isinstance(value, dict):
        obj: dict[str, Any] = value
        if list(obj) == ["$literal"]:
            return copy.deepcopy(obj)
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "$link" and isinstance(v, str) and v.startswith(_PREV):
                if prev is None:
                    raise FragmentError("첫 노드가 앞 노드를 가리킨다")
                out[k] = f"{prev}.{v.removeprefix(_PREV)}"
            else:
                out[k] = _replace_prev(v, prev)
        return out
    return value


def build_fragment(
    steps: Sequence[Sequence[NodeDraft]],
    *,
    mode: Literal["new_test", "insert"],
    start: NodeDraft | None = None,
    warnings: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    """스텝 차례의 노드 초안 → 조각. 새 테스트는 `start`(launch·attach 초안)가 있어야 한다."""
    drafts: list[NodeDraft] = [d for step in steps for d in step]
    out_warnings: list[dict[str, str]] = [dict(w) for w in warnings]
    if mode == "new_test":
        if start is None:
            raise FragmentError("새 테스트는 창을 정하는 노드로 시작한다")
        drafts.insert(0, start)
        if not any(d.is_assertion for d in drafts):
            drafts.append(NodeDraft("core.test.pass", "성공으로 끝냄", ""))
            out_warnings.append(
                {
                    "code": "no_assertion",
                    "message": "검증이 없어 끝까지 가면 통과예요. 화면 확인을 넣으세요",
                }
            )
        if start.type == "core.window.attach":
            out_warnings.append(
                {
                    "code": "attach_start",
                    "message": "재생 전에 게임을 녹화를 시작한 화면으로 돌려 두세요",
                }
            )
    elif not drafts:
        raise FragmentError("넣을 노드가 없다")
    nodes: list[dict[str, Any]] = []
    chain: list[str] = []
    prev: str | None = None
    for index, draft in enumerate(drafts, start=1):
        if draft.type == "core.test.pass" and mode == "insert":
            raise FragmentError("삽입 조각에는 종료 노드를 넣지 않는다")
        local = f"r{index}"
        node: dict[str, Any] = {
            "local_id": local,
            "type": draft.type,
            "version": draft.version,
            "in": _replace_prev(dict(draft.inputs), prev),
            "title": draft.title,
        }
        if draft.config is not None:
            node["config"] = copy.deepcopy(dict(draft.config))
        if nodes and drafts[index - 2].ok_exit:
            nodes[-1].setdefault("next", {})[drafts[index - 2].ok_exit] = local
        nodes.append(node)
        chain.append(local)
        prev = local
    fragment: dict[str, Any] = {
        "mode": mode,
        "nodes": nodes,
        "chain": chain,
        "warnings": out_warnings,
    }
    if mode == "new_test":
        fragment["first_window_node"] = chain[0]
    else:
        last = drafts[-1]
        if not last.ok_exit:
            raise FragmentError("삽입 조각의 마지막 노드에 이을 출구가 없다")
        fragment["open_end"] = {"node": chain[-1], "exit": last.ok_exit}
    problems = fragment_problems(fragment)
    if problems:
        raise FragmentError("; ".join(problems))
    return fragment


def new_node_id(taken: set[str], random: Callable[[int], bytes] = _random.token_bytes) -> str:
    """`n_` + 소문자 base32 8자 (렌더러 `newNodeId`와 같은 모양)."""
    for _ in range(1000):
        raw = random(8)
        node_id = "n_" + "".join(_ID_ALPHABET[b & 31] for b in raw)
        if node_id not in taken:
            taken.add(node_id)
            return node_id
    raise RuntimeError("새 노드 ID를 만들지 못했다")


def _rename_links(value: Any, ids: Mapping[str, str]) -> Any:
    if isinstance(value, list):
        items: list[Any] = value
        return [_rename_links(v, ids) for v in items]
    if isinstance(value, dict):
        obj: dict[str, Any] = value
        if list(obj) == ["$literal"]:
            return copy.deepcopy(obj)
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k == "$link" and isinstance(v, str) and "." in v:
                node, pin = v.split(".", 1)
                out[k] = f"{ids.get(node, node)}.{pin}"
            else:
                out[k] = _rename_links(v, ids)
        return out
    return value


def apply_fragment(
    graph: Mapping[str, Any],
    fragment: Mapping[str, Any],
    *,
    after: tuple[str, str] | None,
    random: Callable[[int], bytes] = _random.token_bytes,
) -> dict[str, Any]:
    """조각을 그래프에 넣은 새 값. `after` = (노드 ID, 출구): 그 출구의 원래 대상을 조각의 열린
    끝으로 옮기고 그 출구를 조각 첫 노드로 잇는다. 고른 노드가 출구 없는 종료 노드면 거부."""
    value = copy.deepcopy(dict(graph))
    nodes: dict[str, Any] = value.setdefault("nodes", {})
    taken = set(nodes) | set((value.get("layout") or {}).get("collapsed") or {})
    taken |= set((value.get("layout") or {}).get("comments") or {})
    ids = {n["local_id"]: new_node_id(taken, random) for n in fragment["nodes"]}
    for frag_node in fragment["nodes"]:
        node: dict[str, Any] = {"type": frag_node["type"], "version": frag_node["version"]}
        if frag_node.get("in"):
            node["in"] = _rename_links(frag_node["in"], ids)
        if frag_node.get("config") is not None:
            node["config"] = copy.deepcopy(frag_node["config"])
        if frag_node.get("next"):
            node["next"] = {e: ids[t] for e, t in frag_node["next"].items()}
        if frag_node.get("title"):
            node["title"] = frag_node["title"]
        nodes[ids[frag_node["local_id"]]] = node
    first = ids[fragment["chain"][0]]
    if after is not None:
        anchor_id, exit_name = after
        anchor = nodes.get(anchor_id)
        if anchor is None:
            raise FragmentError("넣을 자리의 노드가 없다")
        if anchor["type"] in (
            "core.test.pass",
            "core.test.fail",
            "core.test.skip",
            "core.graph.exit",
        ):
            raise FragmentError("끝 노드 뒤에는 넣을 수 없어요")
        old = anchor.setdefault("next", {}).get(exit_name)
        anchor["next"][exit_name] = first
        open_end = fragment.get("open_end")
        if old is not None:
            if open_end is None:
                raise FragmentError("조각에 열린 끝이 없어 원래 다음 노드를 이을 수 없다")
            nodes[ids[open_end["node"]]].setdefault("next", {})[open_end["exit"]] = old
    return value
