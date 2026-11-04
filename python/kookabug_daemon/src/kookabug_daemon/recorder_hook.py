"""daemon 쪽 녹화 훅 연결 (M4 계획 2.1·2.2·2.9): 훅 프로세스 띄우기·받기·연속성·생존 감시.

- `HookStream`(순수): 훅 메시지를 받아 연속성을 보고(`kookabug_core.recorder.continuity` —
  `batch_no`·`crit_seq` 빈틈·`overflow`면 `input_overflow`, `event_id` 빈틈·표식 제외·이동
  합치기는 정상), 다른 프로그램이 보낸 입력(`injected`)을 걸러 세고(U2), 생존 보고로
  `hook_lost`를 판정한다. 실제 훅 프로세스(`HookClient`)와 가짜 원천(`FakeHookSource`, 녹화
  검사·E2E)이 같은 판정을 쓴다
- `HookClient`: 훅 프로세스를 녹화 Job(`KILL_ON_JOB_CLOSE`)에 넣어 띄우고, named pipe + 상호 HMAC
  으로 받는다(파이프 키는 stdin으로 — 명령줄에 남기지 않는다). 생존 감시 셋 중 하나면 `hook_lost`:
  ① 프로세스 종료 또는 파이프 EOF ② `hook.health`가 2초 넘게 오지 않음 ③ 세션 마지막 입력 시각
  (`GetLastInputInfo`, 합성 포함)이 앞섰는데 1초 넘게 훅 이벤트가 하나도 없음(OS가 훅을 뗌)
- 검사 전용 옵션(`HookTesting`): 검사 표식(`extra_info`)을 가진 합성 입력을 사람 입력으로 받기,
  IME 조회 대상 바꿔 끼우기. `KOOKABUG_TESTING=1`일 때만, 표식 값이 제품 표식이면 거부(2.2)
"""

from __future__ import annotations

import contextlib
import logging
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from kookabug_core.recorder.continuity import STOP_REASON, ContinuityChecker
from kookabug_core.recorder.contract import HEALTH_SILENCE_NS, HOOK_PROTOCOL, INPUT_STALL_NS
from kookabug_core.win import Job, Process, ProcessId, current, spawn
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_sdk.pipe import PipeConnection, PipeListener, new_key, new_pipe_name
from kookabug_sdk.rpc import Incoming, PeerLost, RpcPeer

__all__ = [
    "HELLO_TIMEOUT_S",
    "TESTING_ENV",
    "HookClient",
    "HookStop",
    "HookStopIncomplete",
    "HookStream",
    "HookTesting",
    "HookUpdate",
    "StopActions",
    "StopMachine",
    "testing_options",
]

log = logging.getLogger(__name__)

TESTING_ENV: Final = "KOOKABUG_TESTING"
HELLO_TIMEOUT_S: Final = 15.0
MONITOR_INTERVAL_S: Final = 0.1
STOP_WAIT_S: Final = 3.0

type StopReason = Literal["hook_lost", "input_overflow"]


@dataclass(frozen=True, slots=True)
class HookTesting:
    """검사 전용 (`KOOKABUG_TESTING=1` + daemon 옵션). 운영에서는 만들어지지 않는다."""

    accept_extra_info: int | None = None
    """이 `dwExtraInfo`를 가진 합성 입력은 사람 입력으로 받는다 (검사 표식)."""
    ime_query_window: int | None = None
    """IME 표본 조회 대상을 이 창으로 바꿔 끼운다 (지연 검사의 멈춘 응답 창)."""


def testing_options(
    environ: Mapping[str, str],
    *,
    accept_extra_info: int | None = None,
    ime_query_window: int | None = None,
) -> HookTesting | None:
    """daemon 옵션 → 검사 전용 설정. 옵션이 없으면 None. `KOOKABUG_TESTING=1`이 아니거나 검사 표식이
    제품 표식과 같으면 `ValueError` (시작하지 않는다)."""
    if accept_extra_info is None and ime_query_window is None:
        return None
    if environ.get(TESTING_ENV) != "1":
        raise ValueError(
            "--recorder-accept-extra-info·--recorder-ime-query-window는 검사 전용이다 "
            f"({TESTING_ENV}=1일 때만)"
        )
    if accept_extra_info == KOOKABUG_INPUT_MARK:
        raise ValueError(
            "검사 표식이 제품 표식(KOOKABUG_INPUT_MARK)과 같다 — 우리 입력을 녹화하게 된다"
        )
    return HookTesting(accept_extra_info, ime_query_window)


class HookStopIncomplete(RuntimeError):
    """정상 멈춤이 기한 안에 받은 메시지를 다 넘기지 못했다 (소비자 콜백이 늦음)."""


@dataclass(frozen=True, slots=True)
class HookStop:
    reason: StopReason
    detail: str
    cut_crit_seq: int | None = None
    """`input_overflow`면 이 번호 앞의 중요 이벤트까지만 쓴다."""


@dataclass(slots=True)
class HookUpdate:
    """메시지 하나에서 나온 것: 사람 입력으로 받은 이벤트·즉시 관측·IME 표본 (판정 재료)."""

    events: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    obs: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    ime: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


class HookStream:
    """훅 메시지 해석·연속성·생존 판정 (순수 — 시각은 부르는 쪽이 준다, 녹화 기준 시각 ns)."""

    def __init__(self, *, mono_base_ns: int, testing: HookTesting | None = None) -> None:
        self.mono_base_ns = mono_base_ns
        self.testing = testing
        self.checker = ContinuityChecker()
        self.hello: dict[str, Any] | None = None
        self.stop: HookStop | None = None
        self.ignored_injected = 0
        """다른 프로그램이 보낸 입력(합성)이라 녹화하지 않은 중요 이벤트 수 (U2)."""
        self.health_count = 0
        """받은 `hook.health` 수 (진단·검사)."""
        self._last_message_ns: int | None = None
        self._last_health_ns: int | None = None
        self._previous_health: dict[str, Any] | None = None
        self._stall_since: int | None = None

    def _stop(self, reason: StopReason, detail: str, cut: int | None = None) -> HookStop:
        if self.stop is None:
            self.stop = HookStop(reason, detail, cut)
        return self.stop

    def feed(self, method: str, params: Mapping[str, Any], now_ns: int) -> HookUpdate | None:
        """메시지 하나. 녹화를 멈춰야 하면 `self.stop`이 생긴다.

        연속성 위반(`input_overflow`)이면 그 묶음의 유실 앞 이벤트(`valid_prefix`)를 담은 업데이트를
        돌려주고, 멈춘 뒤에도 관측·IME 표본은 계속 돌려준다 — 유실 앞 이벤트의 판정 재료가 뒤
        메시지로 온다. 그 밖의 메시지와 `hook_lost` 뒤에는 None.
        """
        if self.stop is not None:
            if self.stop.reason == STOP_REASON and method == "hook.obs":
                return HookUpdate(obs=list(params["batch"]))
            if self.stop.reason == STOP_REASON and method == "hook.ime":
                return HookUpdate(ime=list(params["batch"]))
            return None
        self._last_message_ns = now_ns
        if method == "hook.hello":
            if params.get("protocol") != HOOK_PROTOCOL:
                self._stop("hook_lost", f"훅 프로토콜이 다르다: {params.get('protocol')}")
                return None
            if str(params.get("mono_base_ns")) != str(self.mono_base_ns):
                self._stop("hook_lost", "훅 프로세스의 녹화 기준 시각이 다르다")
                return None
            self.hello = dict(params)
            self._last_health_ns = now_ns
            return HookUpdate()
        if self.hello is None:
            self._stop("hook_lost", f"hook.hello 전에 {method}가 왔다")
            return None
        if method == "hook.events":
            violation = self.checker.feed_events(params)
            if violation is not None:
                self._stop(STOP_REASON, violation.message, violation.cut_crit_seq)
                prefix = params["events"][: violation.valid_prefix]
                return HookUpdate(events=self._human(prefix))
            return HookUpdate(events=self._human(params["events"]))
        if method == "hook.obs":
            return HookUpdate(obs=list(params["batch"]))
        if method == "hook.ime":
            return HookUpdate(ime=list(params["batch"]))
        if method == "hook.health":
            violation = self.checker.feed_health(params)
            if violation is not None:
                self._stop(STOP_REASON, violation.message, violation.cut_crit_seq)
                return None
            self._note_health(dict(params), now_ns)
            return HookUpdate()
        return HookUpdate()

    def _human(self, events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        accept = None if self.testing is None else self.testing.accept_extra_info
        kept: list[dict[str, Any]] = []
        for event in events:
            injected = bool(event.get("injected")) or bool(event.get("injected_lower_il"))
            if injected and not (accept is not None and event.get("extra_info") == accept):
                if "crit_seq" in event:
                    self.ignored_injected += 1
                continue
            kept.append(dict(event))
        return kept

    def _note_health(self, health: dict[str, Any], now_ns: int) -> None:
        self.health_count += 1
        previous = self._previous_health
        if previous is not None:
            input_moved = health["last_input_tick"] != previous["last_input_tick"]
            event_moved = health["last_event_ns"] != previous["last_event_ns"]
            if event_moved:
                self._stall_since = None
            elif input_moved and self._stall_since is None:
                # 앞 보고 뒤 어느 때 입력이 있었는데 훅 이벤트가 없다
                self._stall_since = self._last_health_ns
        self._previous_health = health
        self._last_health_ns = now_ns

    def liveness(self, now_ns: int) -> HookStop | None:
        """생존 감시 ②·③의 **후보** (①은 프로세스·파이프를 보는 `HookClient`).

        상태를 바꾸지 않는다 — 멈출지는 부르는 쪽(`HookClient`의 정지 기계)이 정한다. 그래서 후보가
        보류돼도 뒤 메시지는 그대로 받는다. 이미 멈췄으면 None."""
        if self.stop is not None or self.hello is None or self._last_health_ns is None:
            return None
        if now_ns - self._last_health_ns > HEALTH_SILENCE_NS:
            return HookStop("hook_lost", "hook.health가 2초 넘게 오지 않았다")
        if self._stall_since is not None and now_ns - self._stall_since > INPUT_STALL_NS:
            return HookStop(
                "hook_lost", "입력이 있었는데 1초 넘게 훅 이벤트가 없다 (OS가 훅을 뗐을 수 있다)"
            )
        return None


def hook_command() -> list[str]:
    return [sys.executable, "-m", "kookabug_platform.recorder.hookproc"]


type StopEvent = Literal[
    "overflow",  # 읽기: 연속성 위반을 찾음 (stop=input_overflow)
    "protocol_lost",  # 읽기: hello 불일치 등 (stop=hook_lost)
    "eof",  # 읽기: 파이프 EOF — 그 앞 메시지는 모두 넘겼다
    "process_exited",  # 감시: 훅 프로세스가 끝났다 (detail)
    "liveness_lost",  # 감시: 생존 보고 끊김·입력 앞섬 (stop=hook_lost)
    "stop_requested",  # stop(): 정상 멈춤
    "tick",  # 감시: 기한 확인 (now)
]
type MachineState = Literal["running", "draining", "exited", "stopping", "ended"]


@dataclass(frozen=True, slots=True)
class StopActions:
    """결정의 결과 — 부르는 쪽이 **잠금 밖에서** 이 차례로 한다: 훅에 `hook.stop` → `on_stop` →
    프로세스·파이프 끝내기."""

    notify_stop: bool = False
    report: HookStop | None = None
    kill: bool = False


class StopMachine:
    """`HookClient`의 정지 결정을 하는 **유일한 주체** (한 잠금 아래 상태 기계).

    읽기·감시·`stop()` 스레드는 사건(`StopEvent`)만 알리고, 최종 정지 사유와 `on_stop`(한 번)은
    여기서 정한다. 상태:

    - `running`: 녹화 중
    - `draining`: 넘침을 찾았다 — 훅을 멈추고 EOF까지 유실 앞 이벤트의 관측·표본을 받는다. EOF에서
      `input_overflow`를 알린다. 프로세스 종료·생존 감시는 무시한다(예상된 종료, 넘침이 먼저다)
    - `exited`: 녹화 중 훅 프로세스가 끝났다 — 이미 받은 메시지에 넘침이 있을 수 있으니 바로
      알리지 않고 EOF까지 읽는다. 그 사이 넘침이면 `draining`, EOF면 `hook_lost`(종료 코드)
    - `stopping`: 정상 멈춤 — 아무것도 알리지 않는다(`stop()`이 결과를 돌려준다)
    - `ended`: 끝 (알렸거나 정상으로 끝남)

    생존 감시(`liveness_lost`)는 읽기 스레드가 받은 큐가 빈 순간에만 계산해 알리고(`HookStream.
    liveness`는 상태를 바꾸지 않는 후보), 여기서도 읽기가 밀렸거나 큐가 차 있으면 버린다 — 늦은
    것이 소비자 콜백이면 생존 보고는 큐에 와 있고, 그것을 처리한 뒤 다시 잰다.
    """

    def __init__(
        self,
        *,
        pending: Callable[[], int] = lambda: 0,
        drain_wait_s: float = STOP_WAIT_S,
        exit_wait_s: float = 1.0,
    ) -> None:
        self._lock = threading.Lock()
        self._pending = pending
        self._drain_wait_s = drain_wait_s
        self._exit_wait_s = exit_wait_s
        self.state: MachineState = "running"
        self.reported: HookStop | None = None
        """`on_stop`으로 알린 것."""
        self.overflow: HookStop | None = None
        self._exit_detail = ""
        self._deadline: float | None = None
        self._reader_busy = False

    def reader_busy(self, busy: bool) -> None:
        with self._lock:
            self._reader_busy = busy

    def on(
        self,
        event: StopEvent,
        *,
        stop: HookStop | None = None,
        detail: str = "",
        now: float | None = None,
    ) -> StopActions:
        clock = time.monotonic() if now is None else now
        with self._lock:
            return self._step(event, stop, detail, clock)

    def _end(self, report: HookStop) -> StopActions:
        self.state = "ended"
        self.reported = report
        return StopActions(report=report, kill=True)

    def _step(
        self, event: StopEvent, stop: HookStop | None, detail: str, now: float
    ) -> StopActions:
        state = self.state
        if state == "ended":
            return StopActions()
        if state == "stopping":
            if event == "overflow" and self.overflow is None:
                self.overflow = stop
            if event == "eof":
                self.state = "ended"
            return StopActions()
        if event == "stop_requested":
            self.state = "stopping"
            return StopActions(notify_stop=state == "running")
        if event == "tick":
            if self._deadline is not None and now > self._deadline:
                self._deadline = None  # 한 번만: 파이프가 닫히면 EOF가 온다
                return StopActions(kill=True)
            return StopActions()
        if state == "running":
            if event == "overflow":
                self.state, self.overflow = "draining", stop
                self._deadline = now + self._drain_wait_s
                return StopActions(notify_stop=True)
            if event == "protocol_lost" and stop is not None:
                return self._end(stop)
            if event == "eof":
                return self._end(HookStop("hook_lost", f"훅 프로세스 파이프가 끊겼다: {detail}"))
            if event == "process_exited":
                self.state, self._exit_detail = "exited", detail
                self._deadline = now + self._exit_wait_s
                return StopActions()
            if event == "liveness_lost" and stop is not None:
                if self._reader_busy or self._pending() > 0:
                    return StopActions()  # 읽기가 밀렸다 — 생존 보고가 큐에 있을 수 있다
                return self._end(stop)
            return StopActions()
        if state == "draining":
            if event == "eof" and self.overflow is not None:
                return self._end(self.overflow)
            return StopActions()  # 프로세스 종료·생존 감시·프로토콜은 넘침 마무리 중 무시
        # exited
        if event == "overflow":
            self.state, self.overflow = "draining", stop
            self._deadline = now + self._drain_wait_s
            return StopActions()  # 프로세스는 이미 끝났다
        if event == "protocol_lost" and stop is not None:
            return self._end(stop)
        if event == "eof":
            return self._end(HookStop("hook_lost", self._exit_detail))
        return StopActions()


class HookClient:
    """훅 프로세스 하나. `start()` → (업데이트·멈춤 콜백) → `stop()`.

    `on_update(update)`·`on_stop(stop)`은 읽기·감시 스레드에서 불린다. `on_stop`은 한 번만, 정상
    `stop()` 중에는 부르지 않는다. 넘침(`input_overflow`)이면 유실 앞 이벤트를 먼저 `on_update`로
    넘기고, 훅을 정상으로 멈춰 그 이벤트들의 관측·표본까지 받은 뒤(EOF) `on_stop`을 부른다.
    `hook_lost`는 바로 알리고 프로세스를 끝낸다. `stop()`은 받은 메시지를 모두 넘긴 뒤 돌아온다
    (기한을 넘기면 `HookStopIncomplete` — 그 뒤 콜백은 없다). 정지 사유와 `on_stop`은
    `StopMachine` 하나가 정하고, 읽기·감시·`stop()` 스레드는 사건만 알린다.
    """

    def __init__(
        self,
        *,
        mono_base_ns: int,
        on_update: Callable[[HookUpdate], None],
        on_stop: Callable[[HookStop], None],
        testing: HookTesting | None = None,
        target_hwnd: int | None = None,
        command: Sequence[str] | None = None,
        env: Mapping[str, str] | None = None,
        logs_dir: Path | None = None,
    ) -> None:
        self.stream = HookStream(mono_base_ns=mono_base_ns, testing=testing)
        self.mono_base_ns = mono_base_ns
        self._on_update = on_update
        self._on_stop = on_stop
        self._target_hwnd = target_hwnd
        self._command = list(command) if command is not None else hook_command()
        self._env = dict(os.environ if env is None else env)
        self._logs = logs_dir or Path(tempfile.mkdtemp(prefix="kb-hook-"))
        self._job: Job | None = None
        self._process: Process | None = None
        self._launcher: Process | None = None
        self._peer: RpcPeer | None = None
        self._reader_done = threading.Event()
        self._abandoned = threading.Event()
        """`stop()`이 넘기기 기한을 넘겨 포기했다 (그 뒤 콜백 없음)."""
        self._reader: threading.Thread | None = None
        self.machine = StopMachine(pending=self._pending)
        """정지 결정의 유일한 주체 — 이 클래스의 스레드들은 사건만 알린다."""

    @property
    def result(self) -> HookStop | None:
        """`on_stop`으로 알린 멈춤."""
        return self.machine.reported

    def _pending(self) -> int:
        peer = self._peer
        return 0 if peer is None else peer.incoming.qsize()

    def _apply(self, actions: StopActions) -> None:
        """정지 기계의 결정을 잠금 밖에서 한다: `hook.stop` → `on_stop` → 끝내기."""
        if actions.notify_stop:
            self._notify_stop()
        if actions.report is not None:
            log.warning("녹화 훅 멈춤: %s (%s)", actions.report.reason, actions.report.detail)
            self._on_stop(actions.report)
        if actions.kill:
            self._kill()

    def _event(self, event: StopEvent, *, stop: HookStop | None = None, detail: str = "") -> None:
        self._apply(self.machine.on(event, stop=stop, detail=detail))

    def now_ns(self) -> int:
        return time.monotonic_ns() - self.mono_base_ns

    def _args(self) -> list[str]:
        me = current()
        args = [
            "--parent-pid",
            str(me.pid),
            "--parent-created",
            str(me.created),
            "--mono-base-ns",
            str(self.mono_base_ns),
        ]
        if self._target_hwnd is not None:
            args += ["--target-hwnd", str(self._target_hwnd)]
        testing = self.stream.testing
        if testing is not None and testing.ime_query_window is not None:
            args += ["--ime-query-window", str(testing.ime_query_window)]
        return args

    def start(self, timeout: float = HELLO_TIMEOUT_S) -> dict[str, Any]:
        """띄우고 `hook.hello`까지. 실패하면 정리하고 `RuntimeError`."""
        job = Job.create(kill_on_close=True)
        listener = PipeListener(new_pipe_name("hook"))
        key = new_key()
        accepted: queue.Queue[PipeConnection | BaseException] = queue.Queue()

        def accept() -> None:
            try:
                accepted.put(listener.accept(key, timeout=timeout))
            except BaseException as exc:
                accepted.put(exc)

        threading.Thread(target=accept, name="hook-accept", daemon=True).start()
        try:
            launcher = spawn(
                [*self._command, "--pipe", listener.name, *self._args()],
                stdout=self._logs / "hook.stdout.log",
                stderr=self._logs / "hook.stderr.log",
                env=self._env,
                stdin=subprocess.PIPE,
            )
            assert launcher.stdin is not None
            launcher.stdin.write((key.hex() + "\n").encode("ascii"))
            launcher.stdin.close()
            job.assign(launcher.pid)
            self._process = Process.open(launcher.pid, terminate=True)
            self._job = job
            got = accepted.get(timeout=timeout)
            if isinstance(got, BaseException):
                raise RuntimeError(f"훅 프로세스가 파이프에 붙지 못했다: {got}") from got
            self._peer = RpcPeer(got, name="recorder-hook").start()
            hello = self._wait_hello(timeout)
            self._adopt(hello, launcher.pid, job)
        except BaseException:
            listener.close()
            self._kill()
            raise
        self._start_threads()
        return hello

    def _start_threads(self) -> None:
        self._reader = threading.Thread(target=self._read, name="hook-read", daemon=True)
        self._reader.start()
        threading.Thread(target=self._monitor, name="hook-monitor", daemon=True).start()

    def _adopt(self, hello: Mapping[str, Any], launcher_pid: int, job: Job) -> None:
        """hello가 알린 실제 훅 프로세스를 감시·종료 대상으로 (venv `python.exe`는 실제
        인터프리터를 자식으로 띄우는 런처다 — 그 자식은 런처를 Job에 넣기 전에 생겼을 수 있다)."""
        pid = int(hello["pid"])
        if pid == launcher_pid:
            return
        try:
            real = Process.open(ProcessId(pid, int(hello["created"])), terminate=True)
        except (ProcessLookupError, ValueError) as exc:
            raise RuntimeError(f"hello가 알린 훅 프로세스({pid})를 열 수 없다: {exc}") from exc
        try:
            job.assign(pid)
        except OSError as exc:  # 이미 다른 Job 소속 등 — 부모 감시·직접 종료로 정리한다
            log.warning("훅 프로세스 %d를 녹화 Job에 넣지 못했다: %s", pid, exc)
        self._launcher, self._process = self._process, real

    def _wait_hello(self, timeout: float) -> dict[str, Any]:
        assert self._peer is not None
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                item = self._peer.incoming.get(timeout=left)
            except queue.Empty:
                break
            if isinstance(item, PeerLost):
                raise RuntimeError(f"훅 프로세스가 hello 전에 끊겼다: {item.reason}")
            self.stream.feed(item.method, item.params, self.now_ns())
            if self.stream.stop is not None:
                raise RuntimeError(self.stream.stop.detail)
            if self.stream.hello is not None:
                return self.stream.hello
        raise RuntimeError(f"훅 프로세스가 {timeout:g}초 안에 hello를 보내지 않았다")

    def _read(self) -> None:
        """파이프 EOF(`PeerLost`)까지 받은 차례대로 넘긴다. 정상 멈춤·넘침 마무리도 EOF까지 읽는다
        — 훅 프로세스가 훅을 뗀 뒤 마지막 묶음·관측을 보내고 파이프를 닫는 것이 완료 경계다."""
        assert self._peer is not None
        stream_stop_seen = False
        try:
            while True:
                try:
                    item = self._peer.incoming.get(timeout=MONITOR_INTERVAL_S)
                except queue.Empty:
                    # 생존 감시는 **여기서만** 판정한다: 읽기 스레드가 손에 든 메시지도 없고 받은
                    # 큐도 비었을 때다. 콜백이 늦는 동안 쌓인 생존 보고는 먼저 처리된 뒤에 잰다
                    lost = self.stream.liveness(self.now_ns())
                    if lost is not None:
                        self._event("liveness_lost", stop=lost)
                    continue
                self.machine.reader_busy(True)
                try:
                    if isinstance(item, PeerLost):
                        self._event("eof", detail=item.reason)
                        return
                    stream_stop_seen = self._deliver(item, stream_stop_seen)
                finally:
                    self.machine.reader_busy(False)
        finally:
            self._reader_done.set()

    def _deliver(self, item: Incoming, stream_stop_seen: bool) -> bool:
        """메시지 하나를 넘긴다. 스트림이 멈춤을 찾으면 **콜백 전에** 정지 기계에 알린다 — 넘침
        마무리 상태가 먼저 정해져야 감시 스레드의 어떤 사건도 그 앞에 알려지지 않는다."""
        if self._abandoned.is_set():
            return stream_stop_seen  # `stop()`이 기한을 넘겨 포기했다 — 그 뒤 콜백은 없다
        reported = self.machine.reported
        if reported is not None and reported.reason == "hook_lost":
            return stream_stop_seen  # 끊긴 뒤 남은 것은 믿지 않는다
        update = self.stream.feed(item.method, item.params, self.now_ns())
        stop = self.stream.stop
        if stop is not None and not stream_stop_seen:
            stream_stop_seen = True
            kind: StopEvent = "overflow" if stop.reason == STOP_REASON else "protocol_lost"
            self._event(kind, stop=stop)
        reported = self.machine.reported
        if reported is not None and reported.reason == "hook_lost":
            return stream_stop_seen
        if update is not None and (update.events or update.obs or update.ime):
            self._on_update(update)  # 넘침이면 유실 앞 이벤트가 먼저 간다
        return stream_stop_seen

    def _monitor(self) -> None:
        """사건만 알린다: 기한(`tick`), 프로세스 종료. 결정은 정지 기계가 한다. 생존 감시는 읽기
        스레드가 큐가 빌 때 판정한다 (`_read`) — 여기서 재면 읽기 스레드가 손에 든 생존 보고를 못
        본 채 시간 초과를 알릴 수 있다."""
        while not self._reader_done.wait(MONITOR_INTERVAL_S):
            if self.machine.state in ("ended", "stopping"):
                return
            self._event("tick")
            process = self._process
            if process is not None and not process.alive():
                code = process.exit_code()
                self._event("process_exited", detail=f"훅 프로세스가 끝났다 (종료 코드 {code})")

    def _notify_stop(self) -> None:
        peer = self._peer
        if peer is not None and peer.lost is None:
            with contextlib.suppress(Exception):  # 그 사이 끊겼으면 EOF가 온다
                peer.notify("hook.stop", {})

    def stop(
        self, timeout: float = STOP_WAIT_S, *, deliver_timeout: float = STOP_WAIT_S
    ) -> HookStop | None:
        """정상 멈춤: `hook.stop`을 보내고, 훅 프로세스가 끝나(`timeout`, 넘기면 끝낸다) 파이프
        EOF까지 받은 메시지를 모두 `on_update`로 넘긴 뒤 돌아온다. 마무리 묶음에서 실제 유실이
        보이면 그 멈춤(`input_overflow`)을 돌려준다 — 이때는 `on_stop`을 부르지 않는다.

        넘기기(소비자 콜백 포함)가 `deliver_timeout` 안에 끝나지 않으면 `HookStopIncomplete` — 정상
        완료와 구별된다. 그때 실행 중인 콜백 하나는 끝까지 돌 수 있고(`wait_done()`으로 기다린다),
        그 뒤 콜백은 없다. 콜백 안(읽기 스레드)에서 부르면 프로세스 종료까지만 기다리고, 남은
        메시지는 그 콜백이 돌아온 뒤 차례대로 넘어간다."""
        self._event("stop_requested")
        self._notify_stop()  # 넘침 마무리·프로세스 종료 중이어도 보낸다 (이미 끝났으면 무시됨)
        if self._process is not None and self._process.wait(timeout) is None:
            self._kill()  # 기한 안에 끝나지 않음 — 파이프가 닫혀 EOF가 온다
        off_reader = self._reader is not None and threading.current_thread() is not self._reader
        if off_reader and not self._reader_done.wait(deliver_timeout):
            self._abandoned.set()
            self._kill()
            raise HookStopIncomplete(
                f"훅 메시지 넘기기가 {deliver_timeout:g}초 안에 끝나지 않았다 "
                "(소비자 콜백이 늦다) — 녹화 끝부분이 빠졌을 수 있다"
            )
        self._kill()
        if self.machine.reported is not None:
            return None  # 이미 `on_stop`으로 알렸다
        stop = self.machine.overflow or self.stream.stop
        return stop if stop is not None and stop.reason == STOP_REASON else None

    def wait_done(self, timeout: float | None = None) -> bool:
        """읽기 스레드(와 실행 중인 콜백)가 끝났는가 — `HookStopIncomplete` 뒤 정리에 쓴다."""
        return self._reader is None or self._reader_done.wait(timeout)

    def _kill(self) -> None:
        for process in (self._process, self._launcher):
            if process is not None and process.alive():
                process.terminate()
        if self._peer is not None:
            self._peer.close()
        if self._job is not None:
            self._job.close()
            self._job = None

    @property
    def pid(self) -> int | None:
        return None if self._process is None else self._process.pid
