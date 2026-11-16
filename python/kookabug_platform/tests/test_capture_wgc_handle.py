"""windows-capture 제어 객체를 두 스레드가 겹쳐 쓸 때 (실측 2026-11-16: 시작 화면→본 창 바꾸기 중
`RuntimeError: Already mutably borrowed`로 노드 오류). 멈추는 중의 `is_finished`는 "아직 안 끝남",
겹친 `stop`은 잠깐 뒤 다시 보낸다."""

from __future__ import annotations

import pytest

from kookabug_platform.capture import _WgcHandle


class _Control:
    def __init__(self, busy_times: int) -> None:
        self.busy_times = busy_times
        self.stops = 0
        self.finished = False

    def _busy(self) -> None:
        if self.busy_times > 0:
            self.busy_times -= 1
            raise RuntimeError("Already mutably borrowed")

    def is_finished(self) -> bool:
        self._busy()
        return self.finished

    def stop(self) -> None:
        self._busy()
        self.stops += 1
        self.finished = True


def test_is_finished_while_other_thread_stops_is_not_finished() -> None:
    handle = _WgcHandle(_Control(busy_times=1))
    assert handle.is_finished() is False
    assert handle.is_finished() is False  # 다음 확인은 실제 상태


def test_stop_retries_when_control_is_borrowed() -> None:
    control = _Control(busy_times=3)
    _WgcHandle(control).stop()
    assert control.stops == 1 and control.finished


def test_other_errors_are_not_hidden() -> None:
    class Broken:
        def is_finished(self) -> bool:
            raise RuntimeError("세션이 깨졌다")

    with pytest.raises(RuntimeError, match="깨졌다"):
        _WgcHandle(Broken()).is_finished()
