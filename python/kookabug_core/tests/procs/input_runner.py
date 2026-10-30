"""실제 입력을 누른 채 멈추는 runner (테스트 보조, M1 T5 실제 키 해제 검사).

    python input_runner.py        (감독자가 runner처럼 띄운다: 실행 사양은 stdin)

제품 runner(`kookabug_core.runner.__main__`) 그대로에 이 프로세스 안 노드 하나를 더한다 — 앱·창·입력
노드(T10)와 공용 입력 서비스(T9) 전 단계라 그래프가 창을 정하고 원시 누르기를 할 길이 없어서다.

`testkit.input.press_window`(입력 `title`, `inputs`, `x`, `y`): 제목이 정확히 `title`인 창을 찾아
이 실행의 창 바인딩을 만들고, `inputs`를 차례로 **누르기만** 한다(키 이름 또는 `mouse:<버튼>`,
마우스는 클라이언트 `(x, y)`). runner의 입력 액터로 넣으므로 입력 직전 확인·기록·임대권·복구가 제품
경로 그대로다. 마지막 누르기의 `after_down` 훅(`wait:` 장벽)에서 멈추게 하는 것은 실행 사양의
`platform.hooks`다. 장벽 없이 끝나면 실행 마무리(액터 `STOP`)가 뗀다.
"""

from __future__ import annotations

from typing import Any

import kookabug_core.runner.run as run_module
from kookabug_core.engine import NodeInvoker, RoutingInvoker
from kookabug_core.inputs import ClientPoint
from kookabug_core.registry import Registry, default_registry
from kookabug_core.runner.__main__ import _exit, main  # pyright: ignore[reportPrivateUsage]
from kookabug_sdk import Context, Exit, Result, node
from kookabug_sdk.decorators import CORE_PLUGIN

_runner: list[run_module.Runner] = []


@node(
    type="testkit.input.press_window",
    version=1,
    title="창에 원시 누르기",
    exits=[Exit("done", "ok")],
    effects={"input"},
)
def press_window(ctx: Context, title: str, inputs: list[str], x: int = 0, y: int = 0) -> Result:
    """`title` 창에 `inputs`를 차례로 누른다 (떼지 않음)."""
    # 창 API는 runner 진입점이 DPI를 정한 뒤에만 부른다
    from kookabug_platform.windows import find_window

    (runner,) = _runner
    assert runner.actor is not None and runner.window_tracker is not None
    hwnd = find_window(title=f"/^{title}$/")
    assert hwnd is not None, f"창 {title!r}이 없다"
    target = runner.window_tracker.bind(hwnd)
    for name in inputs:
        if name.startswith("mouse:"):
            button = name.removeprefix("mouse:")
            runner.actor.press_button(ClientPoint(x, y), button=button, target=target)
        else:
            runner.actor.press(name, target=target)
    return Result.ok("done")


def _registry() -> Registry:
    registry = default_registry()
    registry.add_functions("testkit", "0", [press_window])
    return registry


def _routing(remote: NodeInvoker | None) -> RoutingInvoker:
    # testkit 노드도 이 프로세스에서 돈다 (워커 없음)
    return RoutingInvoker(remote, local_plugins=(CORE_PLUGIN, "testkit"))


_start_input = run_module.Runner._start_input  # pyright: ignore[reportPrivateUsage]


def _capture_runner(self: run_module.Runner) -> Any:
    _runner.append(self)
    return _start_input(self)


run_module.default_registry = _registry
run_module.RoutingInvoker = _routing  # pyright: ignore[reportAttributeAccessIssue]
run_module.Runner._start_input = _capture_runner  # pyright: ignore[reportPrivateUsage]

if __name__ == "__main__":
    _exit(main())
