"""runner 자기 종료 감시자 (구현 계획 M0b 2.6, 4차 결정 4).

전용 스레드다. 잠금·저널·RPC·입력 액터·고장 주입을 **전혀 쓰지 않는다**. 하는 일은 OS 대기
(`WaitForMultipleObjects`: 감독자 프로세스 핸들 + 무장 이벤트, 시간 한도)와 시각 계산, 그리고
`TerminateProcess(self, 4)` 하나다. 다른 스레드는 값(무장 시각)을 쓰고 Win32 이벤트를 세우는
것으로만 알린다 — 그래서 주 스레드가 저널 잠금을 쥔 채 멈추거나 액터가 백엔드에서 멈춰도 감시자는
제때 끝낸다.

- **감독자 사망**(프로세스 핸들이 신호됨): `supervisor_lost_at`을 세운다(제어 스레드가 보고 취소
  순서를 `supervisor_lost`로 시작). 사망 시각 + `shutdown_grace_ms`에 아직 살아 있으면 자기 종료.
  감독자가 없으므로 runner가 스스로 끝내는 유일한 경로다
- **마무리 기한 초과**(감독자 생존): 종료 단계 진입 시각(`arm()`: 취소 시각 또는 정상 마무리 시작)
  + `shutdown_grace_ms` + `self_kill_margin_ms`에 아직 살아 있으면 자기 종료. 감독자가 살아 있으면
  하드 종료는 감독자가 먼저 하고(종료 단계 진입 + `shutdown_grace_ms`), 이것은 뒤 안전망이다

감시 조건은 "마무리를 시작했는가"가 아니라 "프로세스가 아직 살아 있는가"다. 제어 채널 EOF는
감독자 사망의 증거가 아니다 — 사망은 프로세스 핸들로만 판정한다.
"""

from __future__ import annotations

import threading
import time
from typing import Final

from kookabug_core.win import Process, ProcessId, WinEvent, terminate_current, wait_any

__all__ = ["SELF_KILL_EXIT_CODE", "Watchdog"]

SELF_KILL_EXIT_CODE: Final = 4
THREAD_NAME: Final = "kookabug-runner-watchdog"


class Watchdog:
    """`start()` 뒤 `arm()`(종료 단계 진입)으로 마무리 기한을 건다. 끄지 않는다 — 프로세스가
    끝나면 같이 끝난다(데몬 스레드)."""

    def __init__(
        self,
        supervisor: ProcessId,
        *,
        shutdown_grace_ms: int,
        self_kill_margin_ms: int,
    ) -> None:
        self.shutdown_grace_s = shutdown_grace_ms / 1000
        self.self_kill_margin_s = self_kill_margin_ms / 1000
        self._event = WinEvent.create()
        # 단조 시각(초). 한 번 정하면 바꾸지 않는다 (쓰는 쪽은 None일 때만 쓴다: 값 하나의 대입)
        self.armed_at: float | None = None
        self.supervisor_lost_at: float | None = None
        try:
            self._supervisor: Process | None = Process.open(supervisor)
        except ProcessLookupError:
            # 열 때 이미 없다(또는 생성 시각이 다르다): 이미 죽은 것
            self._supervisor = None
            self.supervisor_lost_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)

    @property
    def supervisor_lost(self) -> bool:
        return self.supervisor_lost_at is not None

    def start(self) -> Watchdog:
        self._thread.start()
        return self

    def arm(self, at: float | None = None) -> None:
        """종료 단계에 들어갔다 (취소 순서 1 또는 정상 마무리 시작). 처음 시각만 쓴다."""
        if self.armed_at is None:
            self.armed_at = time.monotonic() if at is None else at
        self._event.set()

    def kill_at(self) -> float | None:
        """자기 종료할 시각 (아직 정해지지 않았으면 None)."""
        times: list[float] = []
        if self.supervisor_lost_at is not None:
            times.append(self.supervisor_lost_at + self.shutdown_grace_s)
        if self.armed_at is not None:
            times.append(self.armed_at + self.shutdown_grace_s + self.self_kill_margin_s)
        return min(times) if times else None

    def _run(self) -> None:
        while True:
            now = time.monotonic()
            deadline = self.kill_at()
            if deadline is not None and now >= deadline:
                terminate_current(SELF_KILL_EXIT_CODE)
            timeout = None if deadline is None else deadline - now
            supervisor = self._supervisor if self.supervisor_lost_at is None else None
            handles: list[int] = []
            if supervisor is not None:
                handles.append(supervisor.handle)
            if self.armed_at is None:
                # 무장 이벤트는 수동 재설정이라 세운 뒤에는 계속 신호 상태다: 무장 전에만 본다
                handles.append(self._event.handle)
            if not handles:
                time.sleep(timeout or 0)
                continue
            index = wait_any(handles, timeout)
            if supervisor is not None and index == 0:
                self.supervisor_lost_at = time.monotonic()
