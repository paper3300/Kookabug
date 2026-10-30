"""창 노드: 붙기·현재 대상 창 바꾸기·크기 맞춤.

창을 정한 노드(`attach`·`set_current`, `core.app.launch`)는 정한 직후 한 번 앞으로 가져온다(최선
노력). 입력 노드는 가져오지 않는다 — 실행 중 포커스를 잃으면 입력하지 않고 오류다 (구현 계획 M1
2.2, U1).
"""

from typing import Annotated

from kookabug_sdk import Context, Exit, Input, Result, node
from kookabug_sdk.types import WindowRef


@node(
    type="core.window.attach",
    version=1,
    title="창에 붙기",
    category="window",
    exits=[Exit("found", "ok"), Exit("not_found", "fail")],
    outputs={"window": WindowRef},
    effects={"process"},
)
def attach(
    ctx: Context,
    title: str | None = None,
    process_name: str | None = None,
    owned: bool = False,
) -> Result:
    """이미 떠 있는 창을 찾아 현재 대상 창으로 정한다. `title`은 부분 일치(대소문자 무시) 또는
    `/정규식/`, `process_name`은 실행 파일 이름. 기본은 소유자 없는 창만 찾고, 소유 팝업(대화
    상자 등)은 `owned`를 켜야 찾는다."""
    if title is None and process_name is None:
        raise ValueError("title과 process_name 중 하나는 준다")
    found = ctx.windows.find(title, process_name, owned=owned)
    if found is None:
        return Result.fail("not_found", f"창이 없다 (title={title!r}, process={process_name!r})")
    ctx.set_window(found)
    ctx.windows.activate(found)
    return Result.ok("found", window=found)


@node(
    type="core.window.set_current",
    version=1,
    title="현재 창 바꾸기",
    category="window",
    exits=[Exit("done", "ok")],
    effects={"process"},
)
def set_current(ctx: Context, window: WindowRef) -> Result:
    """호출 프레임의 현재 대상 창을 다음 노드부터 바꾼다. 서브그래프 안에서 바꾼 것은 부른 쪽에
    나오지 않는다."""
    ctx.set_window(window)
    ctx.windows.activate(window)
    return Result.ok("done")


@node(
    type="core.window.set_size",
    version=1,
    title="창 크기 맞춤",
    category="window",
    exits=[Exit("done", "ok"), Exit("fail", "fail")],
    effects={"process"},
)
def set_size(ctx: Context, client_size: Annotated[list[int], Input(min_items=2)]) -> Result:
    """대상 창의 클라이언트 영역을 `[너비, 높이]`(물리 픽셀)로 맞춘다. 녹화 해상도와 맞출 때 쓴다.
    다시 읽은 크기가 다르면 `fail`."""
    if len(client_size) != 2 or any(isinstance(v, bool) or v < 1 for v in client_size):
        raise ValueError(f"client_size는 1 이상인 [너비, 높이]다: {client_size!r}")
    window = ctx.window
    if window is None:
        raise ValueError("대상 창이 없다 (core.app.launch·core.window.attach로 먼저 정한다)")
    width, height = client_size
    if ctx.windows.set_client_size(window, width, height):
        return Result.ok("done")
    return Result.fail("fail", f"클라이언트 영역을 {width}x{height}로 맞추지 못했다")
