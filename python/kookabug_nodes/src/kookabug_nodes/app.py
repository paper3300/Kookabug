"""앱 노드: 게임 띄우기·닫기.

`core.app.launch`가 띄운 게임은 실행 Job 안이라 실행이 끝나면 같이 정리된다 (구현 계획 3장).
"""

from typing import Annotated

from kookabug_sdk import Context, Exit, Input, ObservationTimeout, Result, node
from kookabug_sdk.types import ProcessRef, WindowRef


# 띄운 프로세스는 timeout 출구에도 내보낸다 (그래프가 닫을 수 있게)
@node(
    type="core.app.launch",
    version=1,
    title="게임 실행",
    category="app",
    exits=[Exit("attached", "ok"), Exit("timeout", "fail", outputs=["process"])],
    outputs={"window": WindowRef, "process": ProcessRef},
    effects={"process"},
)
def launch(
    ctx: Context,
    path: str,
    args: list[str] | None = None,
    window_title: str | None = None,
    cwd: str | None = None,
    timeout_ms: Annotated[int, Input(minimum=0)] = 30000,
) -> Result:
    """실행 파일을 띄우고 그 창(`window_title`을 주면 제목이 맞는 창)이 뜨기를 기다려 현재 대상
    창으로 정한다. 런처가 띄운 아래 프로세스의 창도 찾는다. `timeout_ms` 안에 창이 안 뜨면
    `timeout`."""
    process = ctx.process.launch(path, args or [], cwd)
    try:
        found = ctx.process.find_window(process, window_title, deadline=ctx.deadline(timeout_ms))
    except ObservationTimeout:
        found = None
    if found is None:
        return Result.fail("timeout", f"{timeout_ms} ms 안에 창이 뜨지 않았다", process=process)
    ctx.set_window(found)
    ctx.windows.activate(found)
    return Result.ok("attached", window=found, process=process)


@node(
    type="core.app.close",
    version=1,
    title="게임 종료",
    category="app",
    exits=[Exit("closed", "ok"), Exit("timeout", "fail")],
    effects={"process"},
)
def close(
    ctx: Context, process: ProcessRef, force_after_ms: Annotated[int, Input(minimum=0)] = 5000
) -> Result:
    """창에 닫기를 보내고 기다린다. `force_after_ms` 안에 끝나지 않으면 강제로 끝내고 `timeout`."""
    if ctx.process.close(process, force_after_ms):
        return Result.ok("closed")
    return Result.fail("timeout", f"{force_after_ms} ms 안에 끝나지 않아 강제로 끝냈다")
