"""관측 세대와 값의 출처 (구현 계획 M3 2.4, 스키마 v0 6장 "관측값 무효화").

- **세대** (`Epochs`): 실행마다 0에서 시작해 디버거로 멈췄다 **재개할 때마다**(Step 포함) 1 오른다.
  runner 멈춤 게이트가 올리고 실행기가 읽는다. 멈추지 않은 실행은 끝까지 0이라 M1 동작과 같다
- **캡처 세대** (`CaptureEpochs`): 캡처 번호(`Image.capture_id`, 실행 안에서 1부터 늘어남) → 그
  캡처의 세대. 입력 서비스가 `Match.frame_info.capture_id`로 찾는다. 워커는 이 표를 보지 못한다
- **출처** (`Origin`): 값 옆에 붙이는 "이 값이 기댄 가장 오래된 관측"(세대 + 어디서). 값 자체는
  바꾸지 않는다(노드·워커 계약 그대로). 관측과 무관한 값(설정·비밀값·상수·`index`)은 출처가 없다
- **스텝 관측 바닥** (`StepTrace.floor`): 시작 값 = 입력 출처 중 가장 오래된 것. 그 스텝의 캡처,
  변수 읽기와 합친다(가장 오래된 쪽). 출력 출처 = 바닥 — 끝난 시각의 세대로 덮어쓰지 않는다
  (옛 관측에서 나온 값이 새 값으로 세탁되지 않게). 폴링 재개 뒤 노드가 들고 있던 관측을 버렸다고
  알리면(`reset`) 바닥을 입력 출처로 되돌린다(뒤 캡처는 지금 세대)
- **스텝 입력 검사** (`stale_input`): 입력에 지금 세대보다 오래된 출처가 있으면 노드를 부르지 않고
  처리되지 않은 fail `stale_observation`. 예외 둘: 옮기기·기록용 코어 노드(`STALE_EXEMPT`), `input`
  효과 노드가 받은 `Match`(입력 서비스가 target으로 다시 찾는다)
- 한계: 워커가 자기 파이썬 상태에 따로 보관한 값은 추적하지 못한다 (워커 노드는 경계에서만 멈추므로
  한 스텝 안에서는 세대가 바뀌지 않고, 스텝을 넘어 몰래 보관하는 것은 노드 계약 위반)
"""

from __future__ import annotations

import bisect
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from kookabug_sdk.types import Match

__all__ = [
    "STALE_EXEMPT",
    "CaptureEpochs",
    "Epochs",
    "Origin",
    "StepTrace",
    "oldest",
    "stale_input",
]

STALE_EXEMPT: Final[frozenset[str]] = frozenset(
    {
        "core.log.message",
        "core.var.set",
        "core.graph.call",
        "core.graph.exit",
        "core.test.pass",
        "core.test.skip",
        "core.test.fail",
    }
)
"""오래된 관측값을 그대로 옮기거나 기록만 하는 코어 노드 (조율자 결정 Q6). 받은 값의 출처는 같이
넘긴다(`var.set`은 변수에, `graph.call`·`graph.exit`은 서브그래프 입력·호출 출력에). 플러그인
선언은 보류 H3."""


@dataclass(frozen=True, slots=True)
class Origin:
    """값이 기댄 가장 오래된 관측: 그 세대와 그 관측을 낸 곳(노드 경로)."""

    epoch: int
    source: str

    def stale(self, current: int) -> bool:
        return self.epoch < current


def oldest(a: Origin | None, b: Origin | None) -> Origin | None:
    """둘 중 더 오래된 출처 (없는 쪽은 무시)."""
    if a is None:
        return b
    if b is None:
        return a
    return b if b.epoch < a.epoch else a


class Epochs:
    """한 실행의 관측 세대. runner 주 스레드가 재개할 때 올리고 같은 스레드의 실행기가 읽는다."""

    def __init__(self) -> None:
        self._current = 0

    @property
    def current(self) -> int:
        return self._current

    def advance(self) -> int:
        """재개: 세대를 하나 올리고 새 세대를 돌려준다 (`debug.resume.epoch`)."""
        self._current += 1
        return self._current


class CaptureEpochs:
    """캡처 번호 → 세대. 번호와 세대가 둘 다 늘기만 하므로 세대가 바뀐 첫 번호만 적는다(재개 횟수에
    비례하는 메모리 — 캡처 수와 무관)."""

    def __init__(self) -> None:
        self._starts: list[int] = []
        """세대가 바뀐 첫 캡처 번호 (오름차순)."""
        self._epochs: list[int] = []
        self._last = 0

    def note(self, capture_id: int, epoch: int) -> None:
        if not self._epochs or self._epochs[-1] != epoch:
            self._starts.append(capture_id)
            self._epochs.append(epoch)
        self._last = max(self._last, capture_id)

    def epoch_of(self, capture_id: int | None) -> int | None:
        """그 캡처의 세대. 이 실행이 준 번호가 아니면(출처 없음) None."""
        if capture_id is None or not self._starts or capture_id > self._last:
            return None
        at = bisect.bisect_right(self._starts, capture_id) - 1
        return None if at < 0 else self._epochs[at]


def stale_input(
    node_type: str,
    input_effect: bool,
    values: Mapping[str, Any],
    origins: Mapping[str, Origin | None],
    current: int,
) -> str | None:
    """스텝 입력 검사: 지금 세대보다 오래된 관측에서 온 입력이 있으면 그 설명, 없으면 None.

    예외 목록 노드는 받는다. `input` 효과 노드의 `Match` 값은 받는다(입력 서비스가 다시 찾는다)."""
    if current == 0 or node_type in STALE_EXEMPT:
        return None
    for pin in sorted(origins):
        origin = origins[pin]
        if origin is None or not origin.stale(current):
            continue
        if input_effect and isinstance(values.get(pin), Match):
            continue
        return (
            f"입력 '{pin}'이(가) 디버거 재개 전 관측('{origin.source}', 세대 {origin.epoch} < "
            f"지금 {current})에서 왔다 — 멈춘 동안 화면이 바뀌었을 수 있어 쓰지 않는다"
        )
    return None


@dataclass(eq=False)
class StepTrace:
    """스텝 하나의 관측 출처 (스텝 관측 바닥). 순수 노드 계산 한 번도 이것을 하나 쓴다.

    `inputs`는 핀별 입력 출처, `values`는 계산한 입력 값(입력 재검사의 `Match` 예외용).
    `outputs`를 정하면 출력 출처는 바닥이 아니라 그 표다(`graph.entry`·`graph.call`이 핀별로 옮김,
    반복 노드의 `index`는 출처 없음)."""

    node_type: str
    input_effect: bool = False
    inputs: Mapping[str, Origin | None] = field(default_factory=dict[str, Origin | None])
    values: Mapping[str, Any] = field(default_factory=dict[str, Any])
    floor: Origin | None = None
    reset_pending: bool = False
    """폴링 재개로 노드 안 관측이 무효가 됐다 (노드가 `reset`으로 거둘 때까지)."""
    outputs: Mapping[str, Origin | None] | None = None

    def __post_init__(self) -> None:
        self.floor = self.input_floor

    @property
    def input_floor(self) -> Origin | None:
        floor: Origin | None = None
        for origin in self.inputs.values():
            floor = oldest(floor, origin)
        return floor

    @property
    def exempt(self) -> bool:
        """오래된 관측값을 받아도 되는 노드 (변수 읽기 거부도 하지 않는다)."""
        return self.node_type in STALE_EXEMPT

    def begin_attempt(self) -> None:
        """새 시도: 노드가 처음부터 다시 관측한다 (앞 시도의 캡처는 이 시도의 출력에 없다)."""
        self.floor = self.input_floor
        self.reset_pending = False

    def note(self, origin: Origin | None) -> None:
        """캡처·변수 읽기의 출처를 바닥에 합친다."""
        self.floor = oldest(self.floor, origin)

    def stale_inputs(self, current: int) -> str | None:
        return stale_input(self.node_type, self.input_effect, self.values, self.inputs, current)

    def poll_resumed(self) -> None:
        self.reset_pending = True

    def reset(self) -> None:
        """노드가 들고 있던 관측(이전 프레임·후보·안정 시간)을 버렸다: 바닥을 입력 출처로 되돌린다
        (다음 캡처가 지금 세대로 합쳐진다)."""
        self.reset_pending = False
        self.floor = self.input_floor

    def output_origins(self, names: Mapping[str, Any]) -> dict[str, Origin | None]:
        """출력 핀별 출처."""
        if self.outputs is not None:
            return {name: self.outputs.get(name) for name in names}
        return dict.fromkeys(names, self.floor)
