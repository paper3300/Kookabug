"""앱 노드: 게임 띄우기·닫기.

`core.app.launch`가 띄운 게임은 실행 Job 안이라 실행이 끝나면 같이 정리된다 (구현 계획 3장).
"""

from typing import Annotated, Any, Final

from kookabug_sdk import Context, Exit, Input, ObservationTimeout, Result, node
from kookabug_sdk.errors import RunnerError
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
    path: str | None = None,
    args: list[str] | None = None,
    window_title: str | None = None,
    cwd: str | None = None,
    timeout_ms: Annotated[int, Input(minimum=0)] = 30000,
) -> Result:
    """실행 파일을 띄우고 그 창(`window_title`을 주면 제목이 맞는 창)이 뜨기를 기다려 현재 대상
    창으로 정한다. 런처가 띄운 아래 프로세스의 창도 찾는다. `timeout_ms` 안에 창이 안 뜨면
    `timeout`.

    `path`를 비우면 워크스페이스 게임 설정(`game.executable`, 생략한 `args`·`cwd`는 `game.args`·
    `game.cwd`)으로 띄운다 — 그래프에 이 PC 경로가 남지 않는다."""
    if not path:
        path, args, cwd = _game_setting(ctx, args, cwd)
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


_NO_GAME: Final = "게임 설정이 없다 — 설정 도우미에서 게임을 연결한다 (game.executable)"


def _optional(ctx: Context, key: str) -> Any:
    try:
        return ctx.setting(key)
    except KeyError:
        return None


def _game_setting(
    ctx: Context, args: list[str] | None, cwd: str | None
) -> tuple[str, list[str] | None, str | None]:
    """(실행 파일, 인자, 작업 폴더) ← 워크스페이스 게임 설정 (UX10 B). 노드에 준 `args`·`cwd`가
    설정보다 우선한다."""
    path = _optional(ctx, "game.executable")
    if not isinstance(path, str) or not path:
        raise RunnerError("setting_missing", _NO_GAME)
    if args is None:
        found = _optional(ctx, "game.args")
        if found is not None and (
            not isinstance(found, list) or not all(isinstance(a, str) for a in found)
        ):
            raise RunnerError("setting_invalid", "설정 game.args는 글자 목록이어야 한다")
        args = found
    if not cwd:  # 빈 글자도 비운 것 (편집기에서 지운 칸 — path와 같은 규칙)
        found = _optional(ctx, "game.cwd")
        if found is not None and not isinstance(found, str):
            raise RunnerError("setting_invalid", "설정 game.cwd는 글자여야 한다")
        cwd = found or None
    return path, args, cwd


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
