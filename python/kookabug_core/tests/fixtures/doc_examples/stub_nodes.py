"""문서 예시가 쓰는 M1 노드의 선언만 한 스텁 (테스트 전용, 실행하지 않는다).

핀·출구는 `MVP 노드 목록.md` 표를 따른다. 실제 구현(M1)에서 기본값·제약이 바뀔 수 있으므로
이 파일은 문서 예시의 **의미 검증**(핀 이름·타입·출구·지배)에만 쓴다.

`registry_with_stubs()`는 설치된 코어 플러그인 스키마에 스텁 선언을 합쳐 `core` 플러그인 하나로
등록한다 (같은 플러그인을 두 번 등록할 수 없다).
"""

import importlib
from typing import Literal

import kookabug_nodes
from kookabug_core.registry import CORE_PACKAGE, Registry
from kookabug_sdk import (
    Config,
    Context,
    DynamicExits,
    Exit,
    NodeFunction,
    Output,
    Result,
    Retry,
    Secret,
    node,
)
from kookabug_sdk.schema import load_installed
from kookabug_sdk.types import Match, Point, ProcessRef, Rect, Target, WindowRef


@node(
    type="core.app.launch",
    version=1,
    title="게임 실행",
    exits=[Exit("attached", "ok"), Exit("timeout", "fail")],
    outputs={"window": WindowRef, "process": ProcessRef},
    effects={"process"},
)
def app_launch(ctx: Context, path: str, window_title: str, timeout_ms: int = 30000) -> Result:
    """실행 파일을 띄우고 창을 잡는다."""
    raise NotImplementedError


@node(
    type="core.image.wait",
    version=1,
    title="이미지 대기",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def image_wait(ctx: Context, target: Target, timeout_ms: int = 10000) -> Result:
    """대상이 나타날 때까지 기다린다."""
    raise NotImplementedError


@node(
    type="core.image.wait_any",
    version=1,
    title="여러 이미지 중 먼저 보이는 것",
    config={"exits": Config(list[str])},
    exits=DynamicExits(from_config="exits", extra=[Exit("timeout", "fail")]),
    outputs={"match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def image_wait_any(ctx: Context, targets: dict[str, Target], timeout_ms: int = 10000) -> Result:
    """`targets` 중 먼저 보이는 출구로 나간다. 동시에 보이면 `config.exits` 앞쪽."""
    raise NotImplementedError


@node(
    type="core.image.click",
    version=1,
    title="이미지 클릭",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def image_click(
    ctx: Context,
    target: Target,
    button: Literal["left", "right", "middle"] = "left",
    count: int = 1,
    timeout_ms: int = 10000,
) -> Result:
    """대상을 기다렸다가 클릭한다."""
    raise NotImplementedError


@node(
    type="core.input.click",
    version=1,
    title="클릭",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def input_click(ctx: Context, match: Match | None = None, point: Point | None = None) -> Result:
    """매칭 결과나 좌표를 클릭한다."""
    raise NotImplementedError


@node(
    type="core.input.type_text",
    version=1,
    title="글자 입력",
    exits=[Exit("done", "ok")],
    effects={"capture", "input"},
)
def input_type_text(
    ctx: Context, target: Target, text: str | Secret, clear: bool = False
) -> Result:
    """대상 칸에 글자를 입력한다. `text`는 평문과 비밀값을 다 받는다 (G9)."""
    raise NotImplementedError


@node(
    type="core.input.key",
    version=1,
    title="키 입력",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def input_key(ctx: Context, keys: str, hold_ms: int = 0) -> Result:
    """키·조합을 누른다."""
    raise NotImplementedError


@node(
    type="core.ocr.read",
    version=1,
    title="글자 읽기",
    exits=[Exit("done", "ok"), Exit("unreadable", "fail")],
    outputs={
        "text": str,
        "number": Output(float, nullable=True),
        "confidence": Output(float, nullable=True),
    },
    effects={"capture"},
    retry=Retry.observation(on=["unreadable"]),
)
def ocr_read(
    ctx: Context, region: Target | Rect, parse: Literal["text", "number"] = "text"
) -> Result:
    """영역의 글자를 읽는다."""
    raise NotImplementedError


@node(
    type="core.ocr.click_text",
    version=1,
    title="문구 클릭",
    exits=[Exit("done", "ok"), Exit("not_found", "fail")],
    outputs={"match": Match},
    effects={"capture", "input"},
)
def ocr_click_text(ctx: Context, region: Target | Rect, text: str) -> Result:
    """영역에서 문구를 찾아 클릭한다."""
    raise NotImplementedError


@node(
    type="core.assert.visible",
    version=1,
    title="보이는지 검증",
    exits=[Exit("ok", "ok"), Exit("fail", "fail")],
    outputs={"match": Match},
    effects={"capture"},
    assertion=True,
    retry=Retry.observation(on=["fail"]),
)
def assert_visible(ctx: Context, target: Target, timeout_ms: int = 5000) -> Result:
    """대상이 보이는지 검증한다."""
    raise NotImplementedError


STUBS: tuple[NodeFunction, ...] = (
    app_launch,
    image_wait,
    image_wait_any,
    image_click,
    input_click,
    input_type_text,
    input_key,
    ocr_read,
    ocr_click_text,
    assert_visible,
)


def registry_with_stubs() -> Registry:
    """설치된 코어 노드 + 스텁을 `core` 플러그인 하나로."""
    schema = load_installed(CORE_PACKAGE)
    nodes = [*schema["nodes"], *(stub.schema() for stub in STUBS)]
    merged = {**schema, "nodes": sorted(nodes, key=lambda n: n["type"])}
    functions = [
        value
        for name in kookabug_nodes.MODULES
        for value in vars(importlib.import_module(name)).values()
        if isinstance(value, NodeFunction)
    ]
    registry = Registry()
    registry.add_plugin(merged, [*functions, *STUBS])
    return registry
