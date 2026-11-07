"""daemon의 실행 관리 (M2 계획 2.3·2.8). daemon이 감독자다.

**시작 순서** (`run.start`). ①~⑥은 워크스페이스 **시작 잠금** 하나 안에서 직렬로 한다. 그래서 동시에
온 두 요청 중 하나만 실행 폴더·runner를 만든다

1. 중복 방지 키: 범위는 (주체 종류·주체 id, 키), 기한 10분. 같은 인자(경로·profile·settings·
   deadline_ms의 canonical 비교)면 앞 실행을 그대로 돌려준다 — 단 ②는 다시 한다. 다른 인자면
   `idempotency_conflict`
2. 권한 판정 (`Authorizer` → `WorkspaceService.require`). 이 메서드만 전송이 미리 판정하지 않는다
3. **시작 예약**: 진행 중이거나 예약된 실행이 있으면 `run_busy`, 종료가 정해졌으면
   `shutting_down`, 이 daemon의 녹화가 `starting`·`recording`·`paused`면 `recording_active`(M4 —
   실행 폴더·runner를 만들기 전). 아니면 실행 ID를 미리 뽑아 예약한다. 녹화 시작 예약
   (`reserve_recording`)도 같은 시작 잠금 안에서 "진행 중 실행 없음"을 보고 잡으므로 둘이 동시에
   와도 하나만 이긴다
4. 사전 검증: 경로를 다시 해석한 뒤(잠금 뒤·연산 직전) 디스크 파일로 `check_graph`. 오류면
   `validation_failed`이고 실행 폴더를 만들지 않는다(예약을 푼다)
5. `WorkspaceService.start_decided`(②의 판정과 예약한 ID를 넘긴다. 다시 판정하지 않는다)
6. 핸들 등록(예약 → 진행 중)·키 기록

**수명과 같은 잠금**: 예약·진행 중 상태(`active_run`)와 종료 결정(`reserve_shutdown`, 일반
`daemon.shutdown`·유휴 종료)은 상태 잠금 하나 안에서 판단한다. 그래서 시작 중인 실행이 있으면
일반 종료가 `run_active`로 거부되고, 종료가 정해진 뒤에는 이미 기다리던 시작 요청도 runner를 만들지
못한다. daemon이 끝날 때(`close`)는 종료를 정한 뒤 진행 중인 시작이 끝나기를 기다려 그 실행까지
취소한다.

사전 검증과 runner 스냅샷 사이에 파일이 바뀌면 runner의 최종 검증이 실패한다. 실행 폴더가 있는 정상
실행 결과다(`run.ended`의 판정 error, `run.end` 코드 `graph_invalid`).

**구독** (`run.subscribe`)

- 실행마다 따라 읽기 스레드 하나(`record.reader.follow`)가 이벤트를 메모리 꼬리(최근 2,000개)에
  넣고 구독에 나눠 준다. 감독자 마무리(`RunHandle.wait`)가 끝날 때까지 읽으므로 `run.end` 뒤
  감독자가 쓴 `input.recovered`까지 보낸 뒤에 `run.ended`를 보낸다
- 구독마다 hwm(그 연결에 보낸 마지막 seq). 구독은 "따라잡기"로 시작한다: 그동안 들어온 실시간
  이벤트는 보류하고, `after_seq + 1`부터 꼬리(덮지 못하면 파일)에서 보낸 뒤 보류분 중
  `seq > hwm`인 것을 보내고 실시간으로 바꾼다. 전환은 실행 잠금 안에서 한다. 실시간에서도
  `seq <= hwm`은 보내지 않는다
- 송신은 이벤트 루프로 넘긴다(`RunSink.post`). 구독마다 보내는 차례를 구독 잠금 안에서 정하므로
  순서가 바뀌지 않는다
- 연결·실행마다 **지금 구독**을 따로 든다. 이벤트 생산이 끝난 구독(`run.ended`를 넘김)도 해제·
  교체·`run.lagged`·끊김 전까지 여기 남는다. 이것들이 그 구독을 닫으면 아직 루프에서 실행되지 않은
  송신까지 버려진다(넘긴 송신은 루프에서 그 구독이 닫혔는지 본다)
- 송신 큐가 넘쳐 `run.lagged`가 나가면 그 구독을 닫는다. 클라이언트는 **자기가 적용한 마지막 seq**로
  다시 구독한다(daemon의 hwm이 아니다: 큐에 넣었지만 보내지 못한 이벤트가 있을 수 있다)
- 이 daemon이 띄우지 않은 실행(CLI `run`)도 구독할 수 있다: `run.json`이 끝날 때까지 파일을 따라
  읽는다. runner가 죽고 아무도 마무리하지 않으면 잠시 뒤 읽기를 멈춘다(그 실행에는 `run.ended`가
  없다)

**디버거** (M3 계획 2.1·2.3)

- 실행마다 시작한 연결 종류(`client.kind == "ui"`)와 원래 `StartRequest`를 `_Run`에 둔다. 주체
  `kind`로 가리지 않는다(UI 주체는 `user`). 브레이크포인트(`.kookabug/breakpoints.json`)는 UI
  실행에만 넣는다: 시작 순간의 파일 값을 사양에 넣고, 실행 중 바뀌면 runner에 밀어 넣는다(항상
  지금 파일 값을 보내므로 엇갈려도 마지막 값이 남는다). 에이전트·CLI 실행은 빈 목록이다
- 일시정지·재개는 이 daemon이 띄운 UI 실행에만 (`run_not_debuggable`). 멈춤 상태는 따라 읽는
  이벤트(`debug.pause`·`debug.resume`)로 안다
- **다시 시작** (`restart`): ① 시작 잠금 안에서 그 실행이 UI 실행인지 보고 **재시작 예약**을 건다
  (시작 예약과 같은 자리라 그동안 `run.start`·`run.restart`는 `run_busy`, 일반 종료는 `run_active`)
  ② 잠금 밖에서 취소하고 마무리를 기다린다 ③ 잠금 안에서 그 예약으로 시작 경로(②④⑤⑥, 중복
  방지 키 없음)를 원래 인자로 부른다. 실패하면 예약을 푼다
- **UI 없이 멈춘 실행**: 멈춘 UI 실행에 UI 연결이 하나도 없는 상태가 `unattended_pause_s`(10분)
  이어지면 취소한다. 기한에서 멈춘 시간을 빼므로 이것이 없으면 앱을 끈 채 멈춘 실행이 입력 임대권을
  영영 쥔다. 취소 뒤 마무리는 실제 시간 M0b 경로 그대로다

**목록·기록 읽기** (M3 계획 2.7)

- `run.list`는 최신순(폴더 이름의 시작 초, 같은 초 안은 `started_at`)이고 `before` 커서로 다음 쪽을
  준다. 요약의 배지·결과 필드는 `run.json`에서 읽는다(없으면 뺀다). 끝난 실행은 `events.jsonl`을
  다 읽지 않고 끝부분만 읽는다(마지막 seq·`run.end` 경과)
- 기록 읽기 메서드는 `run_index.RunRecords`가 하고, 실행이 끝났는지는 `locate`가 정한다
"""

from __future__ import annotations

import itertools
import json
import logging
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

from kookabug_core.canonical import canonical_dumps, loads_strict
from kookabug_core.engine.debug import ResumeMode
from kookabug_core.permissions import Decision, Principal
from kookabug_core.record import follow, read_run, read_run_json
from kookabug_core.record.index import node_titles
from kookabug_core.record.policy import AGENT_CONTROL_RECORD
from kookabug_core.record.runfolder import (
    EVENTS_FILE,
    RUN_JSON_FILE,
    SNAPSHOT_DIR,
    new_run_id,
    run_id_of_folder,
)
from kookabug_core.registry import Registry
from kookabug_core.runner.control import ControlState
from kookabug_core.runner.run import unix_micros
from kookabug_core.runner.spec import BoundWindow, PlatformSpec
from kookabug_core.schema import check_shape
from kookabug_core.service import (
    DevModulesRefused,
    WorkspaceService,
    refuse_dev_modules,
    start_options,
)
from kookabug_core.supervisor import (
    ControlError,
    ResumeRefused,
    RunHandle,
    RunOutcome,
    run_exit_code,
)
from kookabug_core.validate import check_graph, check_graph_value
from kookabug_core.win import identify, is_alive
from kookabug_core.workspace import RunOptions, Workspace, WorkspaceError
from kookabug_daemon.breakpoints import BreakpointStore
from kookabug_daemon.documents import WsPath, recheck_path, resolve_path
from kookabug_daemon.methods.tools import Authorizer
from kookabug_daemon.protocol import InvalidParams, RequestFailed
from kookabug_daemon.run_index import Located, RunRecords

__all__ = [
    "IDEMPOTENCY_TTL_S",
    "TAIL_SIZE",
    "LagRecord",
    "RecordingReservation",
    "RecordingState",
    "RunManager",
    "RunSink",
    "StartRequest",
    "snapshot_calls",
]

type RecordingState = Literal["starting", "recording", "paused"]
"""실행을 막는 녹화 세션 상태 (M4 계획 2.3). stopped 뒤에는 예약을 푼다."""

log = logging.getLogger(__name__)

TAIL_SIZE: Final = 2000
IDEMPOTENCY_TTL_S: Final = 600.0
FOLLOW_INTERVAL_S: Final = 0.02
DEFAULT_LIST_LIMIT: Final = 50
RUNS_DIR: Final = "runs"
UNMANAGED_CHECK_S: Final = 0.5
"""daemon이 띄우지 않은 실행의 끝 판정(`run.json`·runner 생존)을 다시 보는 간격."""
UNMANAGED_DEAD_GRACE_S: Final = 10.0
"""그 실행의 runner가 죽은 뒤 감독자 마무리를 기다리는 시간. 지나면 따라 읽기를 멈춘다."""
CLOSE_WAIT_S: Final = 30.0
KEEP_FINISHED: Final = 16
"""구독이 없는 끝난 실행을 메모리에 남기는 수 (나머지는 다시 구독할 때 파일에서 읽는다)."""
UNATTENDED_PAUSE_S: Final = 600.0
"""멈춘 UI 실행에 UI 연결이 하나도 없는 채 이만큼 지나면 취소한다 (사용자 결정 U13, 실제 시간)."""
UNATTENDED_CHECK_S: Final = 0.5
RUNS_BYTES_TTL_S: Final = 60.0
"""`run.list`의 `runs/` 합계 크기를 다시 재는 간격."""
TAIL_READ: Final = 64 * 1024
"""끝난 실행 요약이 읽는 `events.jsonl` 끝부분 바이트."""
_VERDICTS: Final = frozenset({"error", "fail", "pass", "skipped"})
CONTROL_GRAPH: Final = "agent_control.graph.json"
"""에이전트 제어 실행의 그래프 자리 (스냅샷 안에만 쓴다 — 워크스페이스 파일이 아니다)."""
CONTROL_DEADLINE_MS: Final = 30_000
"""제어 실행 하나의 기한 (M5 3.9)."""
_DETACHED_FLAGS: Final = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
    subprocess, "DETACHED_PROCESS", 0
)
_BREAKAWAY: Final = 0x01000000
"""CREATE_BREAKAWAY_FROM_JOB: daemon을 띄운 쪽(앱 등)의 Job에 묶이지 않게."""


class RunSink(Protocol):
    """실행 관리가 보는 전송 (daemon이 구현한다). `post` 말고는 이벤트 루프 안에서만 부른다."""

    def post(self, fn: Callable[[], None]) -> None:
        """`fn`을 이벤트 루프에서 부른다 (어느 스레드에서나). 부른 차례대로 돈다."""
        ...

    def notify(
        self, connection: int, method: str, params: Mapping[str, Any], run_id: str
    ) -> None: ...

    def resume(self, connection: int, run_id: str) -> None:
        """그 연결의 송신 큐가 그 실행 알림을 다시 받게 한다 (`run.lagged` 뒤 다시 구독)."""
        ...

    def on_lag(self, connection: int, listener: Callable[[str], None]) -> bool:
        """송신 큐가 넘쳐 실행 구독이 끊길 때 부를 함수를 그 연결에 단다. 연결이 없으면 False."""
        ...

    def ui_attached(self) -> bool:
        """인증된 UI 연결이 하나라도 있다 (어느 스레드에서나)."""
        ...


@dataclass(frozen=True, slots=True)
class StartRequest:
    principal: Principal
    path: str
    profile: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    deadline_ms: int | None = None
    idempotency_key: str | None = None
    ui: bool = False
    """사람이 UI 연결(`client.kind: ui`)에서 시작했다. 이 실행만 브레이크포인트·디버그 메서드를
    받는다 (M3 2.1)."""
    approved: bool = False
    """ask 판정을 사람이 확인했다 (M5 3.6, `approvals.ApprovalBroker.approve`). ② 단계의 판정에
    넘긴다 — 그 사이 정책이 deny로 바뀌었으면 그대로 거부된다."""


@dataclass(frozen=True, slots=True)
class _LaunchCommand:
    argv: list[str]
    cwd: str | None


def _launch_command(workspace: Workspace, options: RunOptions) -> _LaunchCommand:
    """`game.executable`·`game.args`·`game.cwd` 설정 (`$setting` 탐색 순서 그대로)."""

    def value(key: str) -> Any:
        found = workspace.lookup_setting(key, options)
        return found.value if found.found else None

    executable = value("game.executable")
    if not isinstance(executable, str) or not executable:
        raise RequestFailed(
            "launch_failed",
            "설정 game.executable이 없다 (.kookabug/local.json이나 프로필에 실행 파일 경로를 쓴다)",
        )
    args = value("game.args")
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
        raise RequestFailed("launch_failed", "설정 game.args는 글자 목록이어야 한다")
    cwd = value("game.cwd")
    if cwd is not None and not isinstance(cwd, str):
        raise RequestFailed("launch_failed", "설정 game.cwd는 글자여야 한다")
    return _LaunchCommand([executable, *cast(list[str], args)], cwd)


@dataclass(frozen=True, slots=True)
class LagRecord:
    """송신 큐가 넘쳐 닫은 구독 (진단용). `hwm`은 그때까지 큐에 넣은 마지막 seq다."""

    connection: int
    run_id: str
    hwm: int


@dataclass(slots=True)
class _Key:
    args: str
    run_id: str
    result: dict[str, Any]
    expires: float


@dataclass(eq=False, slots=True)
class _Sub:
    """연결 하나의 실행 구독. `closed`는 이벤트 루프가 정한다(다시 구독·해제·끊김·`run.lagged`):
    이미 넘긴 송신도 루프에서 버린다. `done`은 `run.ended`를 넘긴 뒤 더 넘기지 않는다는 뜻이다."""

    connection: int
    run_id: str
    hwm: int
    live: bool = False
    closed: bool = False
    done: bool = False
    pending: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    lock: threading.Lock = field(default_factory=threading.Lock)


@dataclass(eq=False, slots=True)
class _Run:
    run_id: str
    folder: Path
    graph: str
    handle: RunHandle | None = None
    """이 daemon이 띄운 실행이면 그 핸들."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    tail: deque[dict[str, Any]] = field(
        default_factory=lambda: deque[dict[str, Any]](maxlen=TAIL_SIZE)
    )
    subs: list[_Sub] = field(default_factory=list[_Sub])
    last_seq: int = 0
    ended: dict[str, Any] | None = None
    """`run.ended` params (따라 읽기가 끝나고 판정이 있을 때)."""
    done: threading.Event = field(default_factory=threading.Event)
    """감독자 마무리가 끝났다 (이 daemon이 띄운 실행)."""
    finished: threading.Event = field(default_factory=threading.Event)
    """따라 읽기가 끝났다."""
    outcome: RunOutcome | None = None
    order: int = 0
    request: StartRequest | None = None
    """이 daemon이 띄운 실행의 원래 시작 인자 (다시 시작에 쓴다)."""
    breakpoints_version: int = -1
    """시작 때 사양에 넣은 브레이크포인트 판 (UI 실행만)."""
    push_lock: threading.Lock = field(default_factory=threading.Lock)
    """브레이크포인트 밀어 넣기를 한 번에 하나씩 (늘 지금 파일 값을 보낸다)."""
    paused: bool = False
    """따라 읽은 이벤트로 본 멈춤 (`debug.pause` 뒤 `debug.resume`·`run.end` 전)."""

    @property
    def managed(self) -> bool:
        return self.handle is not None

    @property
    def ui(self) -> bool:
        """이 daemon이 사람의 UI 연결에서 띄운 실행 (디버그 대상)."""
        return self.handle is not None and self.request is not None and self.request.ui


class RunManager:
    """워크스페이스의 실행: 시작 순서·핸들·따라 읽기·구독. daemon 수명 판단(`RunsLike`)도 한다."""

    def __init__(
        self,
        root: Path,
        service: WorkspaceService,
        authorizer: Authorizer,
        registry: Callable[[], Registry],
        *,
        platform: PlatformSpec | None = None,
        plugin_modules: tuple[str, ...] = (),
        breakpoints: BreakpointStore | None = None,
    ) -> None:
        self.root = root
        self.service = service
        self.authorizer = authorizer
        self._registry = registry
        self.platform = platform or PlatformSpec("windows")
        self.plugin_modules = tuple(plugin_modules)
        self.breakpoints = breakpoints or BreakpointStore(root)
        self.unattended_pause_s = UNATTENDED_PAUSE_S
        """멈춘 UI 실행을 UI 연결 없이 두는 한도 (검사가 줄인다)."""
        self.unattended_check_s = UNATTENDED_CHECK_S
        self.sink: RunSink | None = None
        self.catchup_hook: Callable[[str, int], None] | None = None
        """검사용: 따라잡기 스레드가 과거분을 다 보낸 뒤, 보류분을 합치기 전에 부른다
        (인자: run_id, 그때의 hwm)."""
        self.lags: deque[LagRecord] = deque(maxlen=100)
        self._start_lock = threading.Lock()
        self._lock = threading.Lock()
        """상태 잠금: `_runs`·`_active`·`_reserved`·`_closing`·`_keys`·`_current`·
        `_lag_listening`. 시작 예약과 종료 결정은 이 잠금 안에서만 한다."""
        self._runs: dict[str, _Run] = {}
        self._active: str | None = None
        self._reserved: str | None = None
        """시작 예약(③~⑥ 사이)의 실행 ID."""
        self._restarting: str | None = None
        """재시작 예약: 다시 시작하는 실행의 ID (취소·마무리 기다림부터 새 시작 예약까지)."""
        self._closing = False
        """종료가 정해졌다: 새 시작 예약을 받지 않는다."""
        self._recording: RecordingReservation | None = None
        """녹화 예약 (M4 계획 2.3): 있는 동안 `run.start`·`run.restart`는 `recording_active`."""
        self._recording_state: RecordingState = "starting"
        self._keys: dict[tuple[str, str, str], _Key] = {}
        self._current: dict[tuple[int, str], _Sub] = {}
        """(연결, 실행) → 지금 구독 (이벤트 루프만 바꾼다)."""
        self._lag_listening: set[int] = set()
        self._order = itertools.count()
        self._closed = threading.Event()
        self.records = RunRecords(root, self.locate)
        """기록 읽기 (`run.index`·`run.children`·`run.step`·`run.file`·`run.export`)."""
        self._runs_bytes: tuple[float, int] | None = None
        """(잰 시각, `runs/` 합계 크기)."""
        self._runs_bytes_lock = threading.Lock()

    # ---------------------------------------------------------------- 수명 (RunsLike)

    def active_run(self) -> str | None:
        with self._lock:
            return self._busy()

    def _busy(self) -> str | None:
        """진행 중·시작 예약·재시작 예약 중인 실행 ID (상태 잠금 안)."""
        return self._active or self._reserved or self._restarting

    def reserve_shutdown(self, *, force: bool) -> str | None:
        with self._lock:
            busy = self._busy()
            if busy is not None and not force:
                return busy
            self._closing = True
            return None

    def cancel_all_and_wait(self) -> None:
        """종료를 정하고, 시작 중이면 시작이 끝나기를 기다린 뒤 진행 중인 실행을 취소하고 마무리를
        기다린다."""
        with self._lock:
            self._closing = True
        with self._start_lock:
            run = self._active_run()
        if run is not None and run.handle is not None:
            run.handle.cancel()
            run.done.wait()

    def close(self) -> None:
        """daemon이 끝난다: 종료를 정하고(새 시작 거부), 진행 중인 시작이 끝나기를 기다린 뒤 따라
        읽기를 멈춘다. 이 프로세스가 계속 살아 있는 경우(검사)를 위해 진행 중인 실행은 취소하고
        잠시 기다린다 — 감독자 프로세스가 죽으면 runner가 스스로 취소하는 것과 같은 결과다."""
        with self._lock:
            self._closing = True
        with self._start_lock:
            run = self._active_run()
        if run is not None and run.handle is not None and not run.done.is_set():
            run.handle.cancel()
            run.done.wait(CLOSE_WAIT_S)
        self._closed.set()

    def _reserve(self, *, restarting: str | None = None) -> str:
        """③ 시작 예약 (시작 잠금 안). 겹치지 않는 실행 ID를 미리 뽑는다. `restarting`이면 그
        재시작 예약을 이 시작 예약으로 바꾼다(그 사이 빈틈 없이)."""
        with self._lock:
            if self._closing:
                if restarting is not None and self._restarting == restarting:
                    self._restarting = None
                text = "daemon이 끝나는 중이다"
                raise RequestFailed("shutting_down", text, message=text)
            if self._recording is not None:
                if restarting is not None and self._restarting == restarting:
                    self._restarting = None
                raise _recording_active(self._recording_state)
            busy = self._active or self._reserved
            if restarting is None or self._restarting != restarting:
                busy = busy or self._restarting
            if busy is not None:
                raise RequestFailed("run_busy", f"진행 중인 실행 {busy}이(가) 있다", run_id=busy)
            run_id = new_run_id()
            while run_id in self._runs or self._find_folder(run_id) is not None:
                run_id = new_run_id()
            self._reserved = run_id
            if restarting is not None:
                self._restarting = None
            return run_id

    # ---------------------------------------------------------------- 녹화 예약 (M4 계획 2.3)

    def reserve_recording(self) -> RecordingReservation:
        """녹화 시작 예약 (막히는 호출: 스레드에서 부른다). 실행 시작과 **같은 시작 잠금** 안에서
        "진행 중 실행 없음"을 확인하고 `starting`으로 예약한다 — 동시에 온 `run.start`와 둘 중
        하나만 이긴다. 진행 중·예약된 실행이 있으면 `run_active`, 이미 녹화 예약이 있으면
        `recording_active`, 종료가 정해졌으면 `shutting_down`. 나머지 시작 단계(임대권·훅·캡처)는
        예약을 쥔 채 잠금 밖에서 하고, 실패하거나 녹화가 멈추면 `release()`로 푼다."""
        with self._start_lock, self._lock:
            if self._closing:
                text = "daemon이 끝나는 중이다"
                raise RequestFailed("shutting_down", text, message=text)
            if self._recording is not None:
                raise _recording_active(self._recording_state)
            busy = self._busy()
            if busy is not None:
                raise RequestFailed("run_active", f"진행 중인 실행 {busy}이(가) 있다", run_id=busy)
            reservation = RecordingReservation(self)
            self._recording = reservation
            self._recording_state = "starting"
            return reservation

    def recording_state(self) -> RecordingState | None:
        """지금 녹화 예약의 상태 (없으면 None)."""
        with self._lock:
            return None if self._recording is None else self._recording_state

    def holds_recording(self, reservation: RecordingReservation) -> bool:
        with self._lock:
            return self._recording is reservation

    def reservation_state(self, reservation: RecordingReservation) -> RecordingState | None:
        """그 예약의 상태 (풀렸으면 None)."""
        with self._lock:
            return self._recording_state if self._recording is reservation else None

    def set_recording_state(self, reservation: RecordingReservation, state: RecordingState) -> None:
        """그 예약의 상태를 바꾼다 (`RecordingReservation.set_state`). 풀렸으면 `RuntimeError`."""
        with self._lock:
            if self._recording is not reservation:
                raise RuntimeError("풀린 녹화 예약이다")
            self._recording_state = state

    def release_recording(self, reservation: RecordingReservation) -> None:
        """그 예약을 푼다 (`RecordingReservation.release`, 여러 번 불러도 된다)."""
        with self._lock:
            if self._recording is reservation:
                self._recording = None

    def _unreserve(self, run_id: str) -> None:
        with self._lock:
            if self._reserved == run_id:
                self._reserved = None

    def _active_run(self) -> _Run | None:
        with self._lock:
            return None if self._active is None else self._runs.get(self._active)

    # ---------------------------------------------------------------- 시작

    def refuse_dev_modules(self, principal: Principal) -> None:
        """이 daemon이 개발 모듈(`--plugin-module`)로 떠 있으면 에이전트 주체의 실행은
        `permission_denied`(이유 `dev_modules_agent`) — runner를 띄우기 전, 사람 확인도 묻기 전에
        (M6 3.7). 사람(ui) 연결만 개발 모듈 실행을 쓴다."""
        try:
            refuse_dev_modules(principal, self.plugin_modules)
        except DevModulesRefused as exc:
            raise RequestFailed(exc.code, str(exc), reason=exc.reason) from exc

    def start(self, request: StartRequest) -> dict[str, Any]:
        """시작 순서 ①~⑥ (막히는 호출: 스레드에서 부른다)."""
        self.refuse_dev_modules(request.principal)
        where = resolve_path(self.root, request.path, graph=True)
        settings = dict(request.settings)
        args = canonical_dumps(
            {
                "path": where.rel,
                "profile": request.profile,
                "settings": settings,
                "deadline_ms": request.deadline_ms,
            }
        )
        principal = request.principal
        with self._start_lock:
            # ① 중복 방지 키
            scope: tuple[str, str, str] | None = None
            previous: _Key | None = None
            if request.idempotency_key is not None:
                scope = (principal.kind, principal.id, request.idempotency_key)
                previous = self._key(scope, time.monotonic())
                if previous is not None and previous.args != args:
                    raise RequestFailed(
                        "idempotency_conflict",
                        "같은 중복 방지 키를 다른 인자로 보냈다",
                        run_id=previous.run_id,
                    )
            # ② 권한 (키가 같아도 다시 판정한다: 그 사이 정책이 바뀌었을 수 있다)
            decision = self.authorizer.require(
                principal, "run.start", where.rel, approved=request.approved
            )
            assert decision is not None  # run.start는 ui_only가 아니다
            if previous is not None:
                return dict(previous.result)
            # ③ 시작 예약 (실행 중·종료 결정과 같은 잠금)
            reserved = self._reserve()
            key = None if scope is None else (scope, args)
            return self._launch_reserved(request, where, decision, reserved, key)

    def _launch_reserved(
        self,
        request: StartRequest,
        where: WsPath,
        decision: Decision,
        reserved: str,
        key: tuple[tuple[str, str, str], str] | None,
    ) -> dict[str, Any]:
        """④~⑥ (시작 잠금 안, 예약을 쥔 채). 실패하면 예약을 푼다."""
        try:
            handle, current, version = self._prepare_and_launch(request, where, decision, reserved)
        except BaseException:
            self._unreserve(reserved)
            raise
        return self._register(request, handle, current, version, key)

    # ---------------------------------------------------------------- 내부 진입점 (M5 3.9)

    def start_internal(
        self,
        principal: Principal,
        graph_value: Mapping[str, Any],
        decision: Decision,
        *,
        approved: bool = False,
        source: Literal["agent_control"] = "agent_control",
        deadline_ms: int = CONTROL_DEADLINE_MS,
        bound_window: BoundWindow | None = None,
    ) -> str:
        """daemon이 메모리에서 만든 그래프 값으로 실행한다 (에이전트 제어 실행). **공개 RPC가
        아니다** — `control.*` 처리기만 부르고, 이미 집행한 그 도구의 판정(`decision`)을 받는다
        (`kb_run_start`를 다시 판정하지 않음). 나머지는 `run.start`와 같다: 시작 잠금 → 시작 예약
        (`run_busy`·`recording_active`·`shutting_down`) → 사전 검증(값) → 감독자 시작(그래프 값을
        스냅샷에 직접 쓴다 — 워크스페이스·`.kookabug/`에 그래프 파일을 쓰지 않음) → 임대권·감독자
        복구·기록은 runner·감독자 그대로. 실행 ID를 돌려준다 (막히는 호출).

        받는 판정은 allow이거나 사람이 승인한 ask(`approved`)다. 승인 없는 ask·deny면 아무것도
        만들지 않고 `ValueError`(호출자의 버그)."""
        if not (decision.final == "allow" or (decision.final == "ask" and approved)):
            raise ValueError(f"허용되지 않은 판정으로는 시작할 수 없다: {decision.final}")
        self.refuse_dev_modules(principal)
        request = StartRequest(principal=principal, path=CONTROL_GRAPH)
        with self._start_lock:
            reserved = self._reserve()
            try:
                workspace = _open_workspace(self.root)
                _, diagnostics = check_graph_value(
                    workspace, CONTROL_GRAPH, dict(graph_value), registry=self._registry()
                )
                errors = [d for d in diagnostics if d.severity == "error"]
                if errors:
                    raise RequestFailed(
                        "validation_failed",
                        f"제어 실행 검증 오류 {len(errors)}개: {errors[0].message}",
                        diagnostics=[d.to_dict() for d in diagnostics],
                    )
                start = start_options(
                    workspace.run_conditions(),
                    deadline_ms=deadline_ms,
                    plugin_modules=self.plugin_modules,
                    platform=self.platform,
                )
                options = replace(
                    start,
                    run_id=reserved,
                    graph_value=dict(graph_value),
                    source=source,
                    agent={"id": principal.id},
                    # 에이전트 제어 실행은 이미지 기록을 모두 끄고 비밀값을 가린다 (M7 R2) —
                    # 워크스페이스·사용자 설정 파일은 바꾸지 않고 실행 사양으로만
                    record_override=dict(AGENT_CONTROL_RECORD),
                    # daemon이 정한 창에만 붙는다 (M7 R1 — 보호 기록을 쓴 창 = 입력하는 창)
                    bound_window=bound_window,
                )
                try:
                    handle = self.service.start_decided(
                        decision, CONTROL_GRAPH, options, approved=approved
                    )
                except (OSError, RuntimeError) as exc:
                    text = f"실행을 시작할 수 없다: {exc}"
                    raise RequestFailed("io_error", text, message=text) from exc
            except BaseException:
                self._unreserve(reserved)
                raise
            return self._register(request, handle, CONTROL_GRAPH, -1, None)["run_id"]

    def wait_outcome(self, run_id: str, timeout: float) -> RunOutcome | None:
        """이 daemon이 띄운 실행의 마무리를 기다린다 (감독자 복구까지). 기한 안에 안 끝나면 None."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or not run.done.wait(timeout):
            return None
        return run.outcome

    def launch_app(self, profile: str | None) -> int:
        """`app.launch` (M5 C5): 프로필 계층까지 본 설정 `game.executable`·`game.args`·`game.cwd`로
        게임을 띄운다. 실행 Job 밖이다(실행이 끝나도 게임은 남는다). 시작 예약과 같은 잠금 안에서
        실행 중·예약·녹화 중이면 거부한다 (막히는 호출). PID를 돌려준다."""
        with self._start_lock, self._lock:
            if self._closing:
                text = "daemon이 끝나는 중이다"
                raise RequestFailed("shutting_down", text, message=text)
            if self._recording is not None:
                raise _recording_active(self._recording_state)
            busy = self._busy()
            if busy is not None:
                raise RequestFailed("run_busy", f"진행 중인 실행 {busy}이(가) 있다", run_id=busy)
            workspace = _open_workspace(self.root)
            options = RunOptions(profile=profile)
            problems = [d for d in workspace.check_options(options) if d.severity == "error"]
            if problems:
                raise RequestFailed("launch_failed", problems[0].message)
            command = _launch_command(workspace, options)

            def spawn(flags: int) -> subprocess.Popen[bytes]:
                return subprocess.Popen(
                    command.argv,
                    cwd=command.cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=flags,
                    close_fds=True,
                )

            try:
                try:
                    proc = spawn(_DETACHED_FLAGS | _BREAKAWAY)
                except PermissionError:
                    # daemon을 띄운 쪽의 Job이 빠져나가기를 허용하지 않는다: 그 Job 안에서 띄운다
                    # (실행 Job은 아니다 — 실행이 끝나도 게임은 남는다)
                    proc = spawn(_DETACHED_FLAGS)
            except OSError as exc:
                raise RequestFailed("launch_failed", f"게임을 띄우지 못했다: {exc}") from exc
            log.info("게임을 띄웠다: PID %d (%s)", proc.pid, command.argv[0])
            return proc.pid

    def _register(
        self,
        request: StartRequest,
        handle: RunHandle,
        current: str,
        version: int,
        key: tuple[tuple[str, str, str], str] | None,
    ) -> dict[str, Any]:
        # ⑥ 등록 (예약 → 진행 중)
        run = _Run(
            handle.run_id,
            handle.run_dir,
            current,
            handle,
            order=next(self._order),
            request=request,
            breakpoints_version=version,
        )
        result = {"run_id": run.run_id, "run_dir": str(run.folder), "graph": run.graph}
        with self._lock:
            self._runs[run.run_id] = run
            self._active = run.run_id
            self._reserved = None
            if key is not None:
                scope, args = key
                self._keys[scope] = _Key(
                    args, run.run_id, dict(result), time.monotonic() + IDEMPOTENCY_TTL_S
                )
        log.info(
            "실행 %s 시작: %s (%s%s)",
            run.run_id,
            run.graph,
            request.principal.id,
            ", UI" if request.ui else "",
        )
        _thread(self._wait, run, name=f"kb-run-wait-{run.run_id}")
        _thread(self._follow, run, self._managed_stop(run), name=f"kb-run-follow-{run.run_id}")
        if run.ui:
            # 시작 때 넣은 목록이 그 사이 바뀌었으면 지금 값을 밀어 넣는다
            if self.breakpoints.version != version:
                _thread(self._push_breakpoints, run, name=f"kb-run-bp-{run.run_id}")
            _thread(self._watch_unattended, run, name=f"kb-run-unattended-{run.run_id}")
        self._prune()
        return result

    def _prepare_and_launch(
        self, request: StartRequest, where: WsPath, decision: Decision, run_id: str
    ) -> tuple[RunHandle, str, int]:
        """④ 사전 검증 → ⑤ 시작. (핸들, 실행한 그래프 경로)."""
        # ④ 사전 검증 (경로는 잠금 뒤·연산 직전에 다시 해석한다)
        current = recheck_path(self.root, where)
        if not current.path.is_file():
            raise RequestFailed(
                "not_found", f"그래프 파일이 없다: {request.path}", path=request.path
            )
        workspace = _open_workspace(self.root)
        settings = dict(request.settings)
        options = RunOptions(settings=settings, profile=request.profile)
        _, diagnostics = check_graph(
            workspace, current.rel, registry=self._registry(), options=options
        )
        errors = [d for d in diagnostics if d.severity == "error"]
        if errors:
            raise RequestFailed(
                "validation_failed",
                f"실행 전 검증 오류 {len(errors)}개",
                diagnostics=[d.to_dict() for d in diagnostics],
            )
        # ⑤ 시작 (②의 판정과 예약한 ID를 넘긴다). 브레이크포인트는 UI 실행에만, 시작 순간의 파일 값
        start = start_options(
            workspace.run_conditions(),
            deadline_ms=request.deadline_ms,
            profile=request.profile,
            settings=settings,
            plugin_modules=self.plugin_modules,
            platform=self.platform,
        )
        breakpoints, version = self.breakpoints.snapshot() if request.ui else ((), -1)
        try:
            # 사람이 승인한 ask면 그 사실을 감독자 시작까지 넘긴다 (M5 3.6, 공개 인자 아님)
            handle = self.service.start_decided(
                decision,
                current.rel,
                replace(start, run_id=run_id, breakpoints=breakpoints),
                approved=request.approved,
            )
        except (OSError, RuntimeError) as exc:  # 실행 폴더·Job·파이프를 만들지 못함
            text = f"실행을 시작할 수 없다: {exc}"
            raise RequestFailed("io_error", text, message=text) from exc
        return handle, current.rel, version

    def _key(self, scope: tuple[str, str, str], now: float) -> _Key | None:
        with self._lock:
            for item in [k for k, v in self._keys.items() if v.expires <= now]:
                del self._keys[item]
            return self._keys.get(scope)

    def _wait(self, run: _Run) -> None:
        assert run.handle is not None
        try:
            run.outcome = run.handle.wait()
        except Exception:
            log.exception("실행 %s 마무리를 기다리다 실패했다", run.run_id)
        with self._lock:
            if self._active == run.run_id:
                self._active = None
        run.done.set()
        log.info("실행 %s 끝", run.run_id)

    # ---------------------------------------------------------------- 따라 읽기

    def _managed_stop(self, run: _Run) -> Callable[[], bool]:
        return lambda: run.done.is_set() or self._closed.is_set()

    def _unmanaged_stop(self, run: _Run) -> Callable[[], bool]:
        state: dict[str, Any] = {"next": 0.0, "dead_since": None, "start": None}

        def stop() -> bool:
            if self._closed.is_set():
                return True
            now = time.monotonic()
            if now < state["next"]:
                return False
            state["next"] = now + UNMANAGED_CHECK_S
            data = read_run_json(run.folder / RUN_JSON_FILE)
            if data is not None and data.get("status") == "finished":
                return True
            if state["start"] is None:
                state["start"] = read_run(run.folder).run_start
            if _runner_alive(state["start"]):
                state["dead_since"] = None
                return False
            if state["dead_since"] is None:
                state["dead_since"] = now
            return now - state["dead_since"] >= UNMANAGED_DEAD_GRACE_S

        return stop

    def _follow(self, run: _Run, stop: Callable[[], bool]) -> None:
        try:
            for event in follow(run.folder, 0, stop=stop, interval=FOLLOW_INTERVAL_S):
                seq = event.get("seq")
                if not isinstance(seq, int) or isinstance(seq, bool):
                    continue
                with run.lock:
                    run.last_seq = seq
                    run.tail.append(event)
                    kind = event.get("event")
                    if kind == "debug.pause":
                        run.paused = True
                    elif kind in ("debug.resume", "run.end"):
                        run.paused = False
                    for sub in list(run.subs):
                        with sub.lock:
                            if sub.done:
                                continue
                            if not sub.live:
                                sub.pending.append(event)
                            elif seq > sub.hwm:
                                self._send_event(sub, event)
            ended = None if self._closed.is_set() else self._ended_params(run)
        except Exception:
            log.exception("실행 %s 따라 읽기 실패", run.run_id)
            ended = None
        with run.lock:
            run.ended = ended
            if ended is not None:
                for sub in list(run.subs):
                    with sub.lock:
                        if sub.live and not sub.done:
                            self._send_ended(sub, ended)
                            run.subs.remove(sub)
        run.finished.set()
        if run.done.is_set():
            # 진행 중에 읽힌 메모리 색인을 캐시로 옮긴다 (다시 읽히지 않아도 남지 않게)
            try:
                self.records.finish(run.run_id)
            except Exception:
                log.exception("실행 %s 색인 정리 실패", run.run_id)

    def _ended_params(self, run: _Run) -> dict[str, Any] | None:
        recover_error: str | None = None
        if run.outcome is not None:
            run_end = run.outcome.run_end
            recover_error = run.outcome.recover_error
        else:
            run_end = read_run(run.folder).run_end
            if run_end is None and not run.managed:
                return None  # 아무도 마무리하지 못한 실행 (중단)
        return {
            "run_id": run.run_id,
            "outcome": _outcome(run_end, recover_error),
            "last_seq": run.last_seq,
        }

    # ---------------------------------------------------------------- 송신

    def _send_event(self, sub: _Sub, event: dict[str, Any]) -> None:
        """구독 잠금 안에서 부른다: hwm을 올리고 루프로 넘긴다 (넘긴 차례 = 보내는 차례)."""
        seq: int = event["seq"]
        sub.hwm = seq
        self._post(sub, "run.event", {"run_id": sub.run_id, "seq": seq, "event": event})

    def _send_ended(self, sub: _Sub, ended: dict[str, Any]) -> None:
        sub.done = True
        self._post(sub, "run.ended", ended)

    def _post(self, sub: _Sub, method: str, params: dict[str, Any]) -> None:
        sink = self.sink
        if sink is None:
            return

        def deliver() -> None:
            if not sub.closed:
                sink.notify(sub.connection, method, params, sub.run_id)

        sink.post(deliver)

    # ---------------------------------------------------------------- 구독 (이벤트 루프 안)

    def subscribe(self, connection: int, run_id: str, after_seq: int) -> None:
        run = self._tracked(run_id)
        sink = self.sink
        assert sink is not None
        with self._lock:
            listen = connection not in self._lag_listening
            if listen:
                self._lag_listening.add(connection)
        if listen:
            sink.on_lag(connection, lambda lagged: self._lagged(connection, lagged))
        # 옛 구독(이벤트 생산이 끝났어도)을 닫는다: 루프에 남은 그 송신은 버려진다. 새 구독의
        # 송신은 이 뒤에만 넘어간다
        self._close_subs(lambda key: key == (connection, run_id))
        sink.resume(connection, run_id)
        sub = _Sub(connection, run_id, after_seq)
        with self._lock:
            self._current[(connection, run_id)] = sub
        with run.lock:
            run.subs.append(sub)
            snapshot = _covering(run.tail, after_seq)
        _thread(self._catch_up, run, sub, snapshot, name=f"kb-run-catchup-{run_id}")

    def unsubscribe(self, connection: int, run_id: str) -> None:
        self._close_subs(lambda key: key == (connection, run_id))

    def connection_closed(self, connection: int) -> None:
        self._close_subs(lambda key: key[0] == connection)
        with self._lock:
            self._lag_listening.discard(connection)

    def _lagged(self, connection: int, run_id: str) -> None:
        """송신 큐가 넘쳤다 (루프 안, `run.lagged`를 넣기 전). 그 구독을 닫는다."""
        for sub in self._close_subs(lambda key: key == (connection, run_id)):
            self.lags.append(LagRecord(connection, run_id, sub.hwm))

    def _close_subs(self, match: Callable[[tuple[int, str]], bool]) -> list[_Sub]:
        """지금 구독 중 `match`인 것을 닫는다 (루프 안). 이벤트 생산이 끝나 실행의 구독 목록에서
        빠진 구독도 닫으므로, 아직 루프에서 실행되지 않은 그 송신(`run.ended` 포함)도 버려진다."""
        with self._lock:
            closed = [self._current.pop(key) for key in list(self._current) if match(key)]
            runs = {sub.run_id: self._runs.get(sub.run_id) for sub in closed}
        for sub in closed:
            with sub.lock:
                sub.closed = True
                sub.done = True
            run = runs[sub.run_id]
            if run is not None:
                with run.lock:
                    if sub in run.subs:
                        run.subs.remove(sub)
        return closed

    def _catch_up(self, run: _Run, sub: _Sub, snapshot: list[dict[str, Any]] | None) -> None:
        try:
            events = snapshot if snapshot is not None else _read_after(run.folder, sub.hwm)
            for event in events:
                with sub.lock:
                    if sub.done:
                        return
                    if event["seq"] > sub.hwm:
                        self._send_event(sub, event)
            hook = self.catchup_hook
            if hook is not None:
                hook(run.run_id, sub.hwm)
            with run.lock, sub.lock:
                if sub.done:
                    return
                for event in sorted(sub.pending, key=lambda e: e["seq"]):
                    if event["seq"] > sub.hwm:
                        self._send_event(sub, event)
                sub.pending.clear()
                sub.live = True
                if run.ended is not None:
                    self._send_ended(sub, run.ended)
                    if sub in run.subs:
                        run.subs.remove(sub)
        except Exception:
            log.exception("실행 %s 따라잡기 실패", run.run_id)

    def _tracked(self, run_id: str) -> _Run:
        """구독할 실행: 이 daemon이 따라 읽는 실행, 아니면 디스크의 실행을 새로 따라 읽는다."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                return run
        folder = self._find_folder(run_id)
        graph = None if folder is None else _graph_of(folder)
        if folder is None or graph is None:
            raise RequestFailed("run_not_found", f"실행 {run_id}이(가) 없다", run_id=run_id)
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                return run
            run = _Run(run_id, folder, graph, order=next(self._order))
            self._runs[run_id] = run
        _thread(self._follow, run, self._unmanaged_stop(run), name=f"kb-run-follow-{run_id}")
        self._prune()
        return run

    def _prune(self) -> None:
        with self._lock:
            idle = sorted(
                (r for r in self._runs.values() if r.finished.is_set() and not r.subs),
                key=lambda r: r.order,
            )
            for run in idle[: max(0, len(idle) - KEEP_FINISHED)]:
                del self._runs[run.run_id]

    # ---------------------------------------------------------------- 상태·목록·취소

    def _find_folder(self, run_id: str) -> Path | None:
        runs = self.root / RUNS_DIR
        try:
            return next((p for p in runs.glob(f"*_{run_id}") if p.is_dir()), None)
        except OSError:
            return None

    def graph_of(self, run_id: str) -> str:
        """권한 판정의 대표 인자(`run.cancel`): 그 실행의 그래프 경로."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is not None:
            return run.graph
        folder = self._find_folder(run_id)
        graph = None if folder is None else _graph_of(folder)
        if graph is None:
            raise RequestFailed("run_not_found", f"실행 {run_id}이(가) 없다", run_id=run_id)
        return graph

    def cancel(self, run_id: str) -> None:
        """이 daemon이 띄운 실행만 취소한다 (막히는 호출: runner의 답을 기다린다)."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or run.handle is None:
            raise RequestFailed(
                "run_not_found", f"이 daemon이 감독하는 실행이 아니다: {run_id}", run_id=run_id
            )
        if not run.done.is_set():
            run.handle.cancel()

    # ---------------------------------------------------------------- 디버거 (M3 2.1·2.3)

    def _debuggable(self, run_id: str) -> _Run:
        """이 daemon이 UI 연결에서 띄운 실행. 이 daemon이 기억하지 않는 실행(다른 daemon·끝나 잊은
        실행·없는 ID)이면 `run_not_found`, 기억하지만 UI 실행이 아니면 `run_not_debuggable`."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None:
            raise RequestFailed(
                "run_not_found", f"이 daemon이 기억하는 실행이 아니다: {run_id}", run_id=run_id
            )
        if not run.ui:
            raise RequestFailed(
                "run_not_debuggable",
                f"이 daemon이 UI에서 시작한 실행이 아니다: {run_id}",
                run_id=run_id,
            )
        return run

    def pause(self, run_id: str) -> ControlState:
        """일시정지 요청 (막히는 호출). 끝난 실행이면 `run_not_found`."""
        run = self._debuggable(run_id)
        assert run.handle is not None
        if run.done.is_set():
            raise _ended(run_id)
        try:
            return run.handle.pause()
        except ControlError as exc:
            raise _ended(run_id) from exc

    def resume(self, run_id: str, mode: ResumeMode = "continue") -> ControlState:
        """재개 (막히는 호출). Step을 멈추지 않은 실행에 보내면 `not_paused`."""
        run = self._debuggable(run_id)
        assert run.handle is not None
        if run.done.is_set():
            raise _not_paused(run_id, "실행이 이미 끝났다")
        try:
            return run.handle.resume(mode)
        except ResumeRefused as exc:
            raise _not_paused(run_id, f"멈춰 있지 않다 ({exc.state})") from exc
        except ControlError as exc:
            raise _not_paused(run_id, "실행이 끝나는 중이다") from exc

    def set_breakpoints(self, items: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
        """브레이크포인트 목록 전체를 바꾸고(파일), 진행 중인 UI 실행에 밀어 넣는다(막히는
        호출)."""
        written = self.breakpoints.replace(items)
        with self._lock:
            run = None if self._active is None else self._runs.get(self._active)
        if run is not None and run.ui and not run.done.is_set():
            self._push_breakpoints(run)
        return [bp.to_json() for bp in written]

    def _push_breakpoints(self, run: _Run) -> None:
        """그 실행에 **지금 파일 값**을 보낸다. 한 실행에는 한 번에 하나씩 보내므로, 시작과 변경이
        엇갈려도 마지막에 받은 값이 마지막 파일 값이다. 실행이 끝나는 중이면 버린다."""
        assert run.handle is not None
        with run.push_lock:
            if run.done.is_set():
                return
            try:
                run.handle.set_breakpoints(self.breakpoints.current())
            except ControlError as exc:
                log.info("실행 %s에 브레이크포인트를 넣지 못했다 (끝나는 중): %s", run.run_id, exc)

    def _watch_unattended(self, run: _Run) -> None:
        """멈춘 UI 실행에 UI 연결이 `unattended_pause_s` 동안 하나도 없으면 취소한다."""
        assert run.handle is not None
        since: float | None = None
        while not run.done.wait(self.unattended_check_s):
            sink = self.sink
            alone = run.paused and (sink is None or not sink.ui_attached())
            if not alone:
                since = None
                continue
            now = time.monotonic()
            if since is None:
                since = now
            elif now - since >= self.unattended_pause_s:
                minutes = self.unattended_pause_s / 60
                log.warning("실행 %s: 디버거 연결 없이 %g분 멈춰 있어 취소", run.run_id, minutes)
                run.handle.cancel()
                return

    def restart(self, run_id: str) -> dict[str, Any]:
        """다시 시작 (막히는 호출, M3 2.3 원자적 재시작). 새 실행의 `run.start` 결과를 돌려준다."""
        # ① 재시작 예약 (시작 잠금 안): UI 실행인지 보고 시작 예약과 같은 자리를 차지한다
        with self._start_lock:
            run = self._debuggable(run_id)
            request = run.request
            assert request is not None and run.handle is not None
            with self._lock:
                if self._closing:
                    text = "daemon이 끝나는 중이다"
                    raise RequestFailed("shutting_down", text, message=text)
                if self._recording is not None:
                    raise _recording_active(self._recording_state)
                busy = self._reserved or self._restarting
                if busy is None and self._active not in (None, run_id):
                    busy = self._active
                if busy is not None:
                    raise RequestFailed(
                        "run_busy", f"진행 중인 실행 {busy}이(가) 있다", run_id=busy
                    )
                self._restarting = run_id
        try:
            # ② 잠금 밖: 진행 중이면 취소하고 감독자 마무리를 기다린다
            if not run.done.is_set():
                run.handle.cancel()
                run.done.wait()
            # ③ 잠금 안: 그 예약으로 시작 경로(②④⑤⑥). 중복 방지 키는 넘기지 않는다
            with self._start_lock:
                where = resolve_path(self.root, request.path, graph=True)
                decision = self.authorizer.require(request.principal, "run.start", where.rel)
                assert decision is not None
                reserved = self._reserve(restarting=run_id)
                fresh = replace(request, idempotency_key=None)
                return self._launch_reserved(fresh, where, decision, reserved, None)
        finally:
            with self._lock:
                if self._restarting == run_id:
                    self._restarting = None

    def status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
        folder = run.folder if run is not None else self._find_folder(run_id)
        summary = None if folder is None else self._summary(folder, run)
        if summary is None or folder is None:
            raise RequestFailed("run_not_found", f"실행 {run_id}이(가) 없다", run_id=run_id)
        return {**summary, "calls": snapshot_calls(folder)}

    def list_runs(
        self,
        limit: int | None = None,
        *,
        before: str | None = None,
        graph: str | None = None,
        verdict: str | None = None,
    ) -> dict[str, Any]:
        """`run.list` (막히는 호출). 최신순 쪽 하나와 다음 쪽 커서(`next`, 마지막 쪽이면 None).

        순서 열쇠는 (폴더 이름의 시작 초, `started_at`, 폴더 이름)이고 커서는 그 열쇠다. 폴더 이름은
        시작 시각(초)으로 시작하므로 커서보다 뒤 초의 폴더는 읽지 않고 건너뛴다."""
        count = DEFAULT_LIST_LIMIT if limit is None else limit
        cursor = None if before is None else _parse_cursor(before)
        runs = self.root / RUNS_DIR
        try:
            folders = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name)
        except OSError:
            folders = []
        found: list[tuple[tuple[str, str, str], dict[str, Any]]] = []
        more = False
        for second, group in itertools.groupby(
            reversed(folders), key=lambda p: p.name.split("_")[0]
        ):
            if len(found) > count:
                break
            if cursor is not None and second > cursor[0]:
                continue
            keyed: list[tuple[tuple[str, str, str], dict[str, Any]]] = []
            for folder in group:
                run_id = run_id_of_folder(folder)
                if run_id is None:
                    continue
                with self._lock:
                    run = self._runs.get(run_id)
                summary = self._summary(folder, run, extended=True)
                if summary is None or not _listed(summary, graph, verdict):
                    continue
                key = (second, summary["started_at"] or "", folder.name)
                if cursor is None or key < cursor:
                    keyed.append((key, summary))
            keyed.sort(key=lambda item: item[0], reverse=True)
            found.extend(keyed)
        if len(found) > count:
            more = True
            found = found[:count]
        result: dict[str, Any] = {
            "runs": [summary for _, summary in found],
            "next": _cursor(found[-1][0]) if more and found else None,
        }
        size = self.runs_bytes()
        if size is not None:
            result["runs_bytes"] = size
        return result

    def runs_bytes(self) -> int | None:
        """`runs/` 합계 크기 (`RUNS_BYTES_TTL_S`마다 다시 잰다). 잴 수 없으면 None."""
        with self._runs_bytes_lock:
            now = time.monotonic()
            if self._runs_bytes is not None and now - self._runs_bytes[0] < RUNS_BYTES_TTL_S:
                return self._runs_bytes[1]
            size = _tree_size(self.root / RUNS_DIR)
            self._runs_bytes = None if size is None else (now, size)
            return size

    def locate(self, run_id: str) -> Located:
        """실행 폴더와 상태 (기록 읽기). 이 daemon이 띄운 실행은 감독자 마무리가 끝나야 `ended`,
        아니면 `run.json`이 `finished`이거나 runner가 없으면 `ended`."""
        with self._lock:
            run = self._runs.get(run_id)
        folder = run.folder if run is not None else self._find_folder(run_id)
        if folder is None:
            raise RequestFailed("run_not_found", f"실행 {run_id}이(가) 없다", run_id=run_id)
        if run is not None and run.managed:
            running = not run.done.is_set()
        else:
            data = read_run_json(folder / RUN_JSON_FILE) or {}
            running = data.get("status") != "finished" and _runner_alive(_first_event(folder))
        return Located(run_id, folder, "running" if running else "ended")

    def _summary(
        self, folder: Path, run: _Run | None, *, extended: bool = False
    ) -> dict[str, Any] | None:
        run_id = run_id_of_folder(folder)
        if run_id is None:
            return None
        data = read_run_json(folder / RUN_JSON_FILE) or {}
        managed_running = run is not None and run.managed and not run.done.is_set()
        if data.get("status") == "finished" and not managed_running:
            # 끝난 실행: 이벤트 파일을 다 읽지 않는다 (마지막 seq·run.end만 끝부분에서)
            last_seq, tail_end = _tail(folder)
            run_start = None
            run_end = tail_end or data
        else:
            view = read_run(folder)
            last_seq, run_start, run_end = view.last_seq, view.run_start, view.run_end
        graph = run.graph if run is not None else _graph_of(folder, data, run_start)
        started = data.get("started_at") or (run_start or {}).get("t")
        if started is None and run is not None and run.handle is not None:
            started = run.handle.started_at
        outcome: dict[str, Any] | None = None
        if run is not None and run.managed:
            running = managed_running
            if not running:
                recover_error = None if run.outcome is None else run.outcome.recover_error
                ended = run_end if run.outcome is None else run.outcome.run_end
                outcome = _outcome(ended, recover_error)
        else:
            running = run_end is None and _runner_alive(run_start)
            if run_end is not None:
                outcome = _outcome(run_end, None)
        summary: dict[str, Any] = {
            "run_id": run_id,
            "run_dir": str(folder),
            "graph": graph,
            "state": "running" if running else "ended",
            "started_at": started,
            "last_seq": last_seq,
            "outcome": outcome,
        }
        if extended:
            summary.update(_badges(folder, data, run_end if not running else None))
        if check_shape(summary, "daemon-rpc", ref="#/$defs/RunSummary"):
            log.warning("실행 폴더 %s를 요약할 수 없다 (형식이 틀린 기록)", folder)
            return None
        return summary


# ---------------------------------------------------------------- 도움 함수


class RecordingReservation:
    """녹화 세션의 실행 거부 예약 (`RunManager.reserve_recording`). 녹화 세션 서비스가 쥐고
    상태를 `starting → recording ⇄ paused`로 바꾸고, 정지(stopped)·버리기·시작 실패 때 푼다.
    상태는 실행 관리자의 상태 잠금 안에서만 바뀐다."""

    def __init__(self, manager: RunManager) -> None:
        self._manager = manager

    @property
    def state(self) -> RecordingState | None:
        """지금 상태 (풀렸으면 None)."""
        return self._manager.reservation_state(self)

    @property
    def active(self) -> bool:
        return self._manager.holds_recording(self)

    def set_state(self, state: RecordingState) -> None:
        """풀린 예약이면 `RuntimeError`."""
        self._manager.set_recording_state(self, state)

    def release(self) -> None:
        """예약을 푼다 (여러 번 불러도 된다). 이 뒤로 `run.start`를 받는다."""
        self._manager.release_recording(self)


def _recording_active(state: RecordingState) -> RequestFailed:
    return RequestFailed(
        "recording_active", f"녹화 중이라 실행할 수 없다 (녹화 {state})", state=state
    )


def _thread(target: Callable[..., None], *args: Any, name: str) -> None:
    threading.Thread(target=target, args=args, name=name, daemon=True).start()


def _ended(run_id: str) -> RequestFailed:
    return RequestFailed("run_not_found", f"진행 중인 실행이 아니다: {run_id}", run_id=run_id)


def _not_paused(run_id: str, why: str) -> RequestFailed:
    return RequestFailed("not_paused", f"실행 {run_id}을(를) Step할 수 없다: {why}", run_id=run_id)


def _open_workspace(root: Path) -> Workspace:
    try:
        return Workspace.open(root)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


def _cursor(key: tuple[str, str, str]) -> str:
    """목록 커서: `started_at|폴더 이름` (시작 초는 폴더 이름 앞부분)."""
    return f"{key[1]}|{key[2]}"


def _parse_cursor(text: str) -> tuple[str, str, str]:
    started, sep, name = text.partition("|")
    if not sep or not name:
        raise InvalidParams(f"before 커서를 읽을 수 없다: {text!r}")
    return (name.split("_")[0], started, name)


def _listed(summary: Mapping[str, Any], graph: str | None, verdict: str | None) -> bool:
    if graph is not None and summary.get("graph") != graph:
        return False
    if verdict is not None:
        outcome = summary.get("outcome")
        if summary.get("state") != "ended" or not isinstance(outcome, dict):
            return False
        return outcome.get("verdict") == verdict
    return True


def _badges(
    folder: Path, data: Mapping[str, Any], run_end: Mapping[str, Any] | None
) -> dict[str, Any]:
    """`run.list` 요약에 더하는 결과·배지 필드 (`run.json`에서. 없는 필드는 뺀다)."""
    out: dict[str, Any] = {}
    for key in ("code", "reason"):
        if isinstance(data.get(key), str):
            out[key] = data[key]
    if isinstance(data.get("debug_intervened"), bool):
        out["debug_intervened"] = data["debug_intervened"]
    duration = None if run_end is None else run_end.get("duration_ms")
    if isinstance(duration, int) and not isinstance(duration, bool) and duration >= 0:
        out["duration_ms"] = duration
    elif isinstance(data.get("started_at"), str) and isinstance(data.get("ended_at"), str):
        try:
            span = _iso_ms(data["ended_at"]) - _iso_ms(data["started_at"])
        except ValueError:
            span = -1
        if span >= 0:
            out["duration_ms"] = span
    if "failure_path" in data:
        path = data["failure_path"]
        if isinstance(path, list) and path and all(isinstance(p, str) for p in path):
            nodes = [str(p) for p in path]
            out["failure_path"] = nodes
            graph = data.get("graph")
            if isinstance(graph, str):
                out["failure_title"] = " > ".join(node_titles(folder, graph, nodes))
        elif path is None:
            out["failure_path"] = None
    retried = data.get("retried_steps")
    if isinstance(retried, int) and not isinstance(retried, bool):
        out["flaky"] = data.get("verdict") == "pass" and retried > 0
    if "game_build" in data and (data["game_build"] is None or isinstance(data["game_build"], str)):
        out["game_build"] = data["game_build"]
    conditions: Any = data.get("conditions")
    if isinstance(conditions, dict) and "profile" in conditions:
        profile: Any = conditions["profile"]
        if profile is None or isinstance(profile, str):
            out["profile"] = profile
    if data.get("source") == "agent_control":
        out["source"] = "agent_control"  # 배지 "에이전트 제어" (M5 U4)
    return out


def _iso_ms(t: str) -> int:
    return int(datetime.fromisoformat(t).timestamp() * 1000 + 0.5)


def _tail(folder: Path) -> tuple[int, dict[str, Any] | None]:
    """(마지막 seq, `run.end`) — `events.jsonl` 끝부분의 완전한 줄만 본다. 끝부분에 seq가 없으면
    파일 전체를 읽는다."""
    path = folder / EVENTS_FILE
    try:
        with path.open("rb") as f:
            size = os.fstat(f.fileno()).st_size
            start = max(0, size - TAIL_READ)
            f.seek(start)
            data = f.read()
    except OSError:
        return 0, None
    lines = data.split(b"\n")[:-1]  # 마지막 \n 뒤는 잘린 줄이거나 빈 바이트
    if start > 0 and lines:
        lines = lines[1:]  # 앞이 잘린 줄
    last_seq: int | None = None
    run_end: dict[str, Any] | None = None
    for raw in reversed(lines):
        event = _json_object(raw)
        if event is None:
            continue
        seq = event.get("seq")
        if last_seq is None and isinstance(seq, int) and not isinstance(seq, bool):
            last_seq = seq
        if event.get("event") == "run.end":
            run_end = event
            break
    if last_seq is None:
        view = read_run(folder)
        return view.last_seq, view.run_end
    return last_seq, run_end


def _first_event(folder: Path) -> dict[str, Any] | None:
    """`events.jsonl` 첫 줄의 `run.start` (없으면 None)."""
    try:
        with (folder / EVENTS_FILE).open("rb") as f:
            line = f.readline(TAIL_READ)
    except OSError:
        return None
    event = _json_object(line)
    return event if event is not None and event.get("event") == "run.start" else None


def _json_object(raw: bytes) -> dict[str, Any] | None:
    try:
        value: Any = json.loads(raw)
    except ValueError:
        return None
    return cast(dict[str, Any], value) if isinstance(value, dict) else None


def _tree_size(folder: Path) -> int | None:
    if not folder.is_dir():
        return 0
    total = 0
    try:
        for current, _, files in os.walk(folder):
            for name in files:
                try:
                    total += os.stat(os.path.join(current, name)).st_size
                except OSError:
                    continue
    except OSError:
        return None
    return total


def _covering(tail: deque[dict[str, Any]], after_seq: int) -> list[dict[str, Any]] | None:
    """꼬리가 `after_seq + 1`부터 덮으면 그 뒤 이벤트, 아니면 None (파일에서 읽는다)."""
    if tail and tail[0]["seq"] <= after_seq + 1:
        return [e for e in tail if e["seq"] > after_seq]
    return None


def _read_after(folder: Path, after_seq: int) -> list[dict[str, Any]]:
    """파일에 지금 있는 완전한 줄 중 `seq > after_seq`인 이벤트 (기다리지 않는다)."""
    return [
        e
        for e in follow(folder, after_seq, stop=lambda: True)
        if isinstance(e.get("seq"), int) and not isinstance(e.get("seq"), bool)
    ]


def _graph_of(
    folder: Path,
    data: Mapping[str, Any] | None = None,
    run_start: Mapping[str, Any] | None = None,
) -> str | None:
    if data is None:
        data = read_run_json(folder / RUN_JSON_FILE) or {}
    graph = data.get("graph")
    if not isinstance(graph, str):
        if run_start is None:
            run_start = read_run(folder).run_start
        graph = (run_start or {}).get("graph")
    return graph if isinstance(graph, str) else None


def snapshot_calls(folder: Path) -> dict[str, dict[str, str]]:
    """실행 스냅샷(`snapshot/`)의 호출 관계: 그래프 파일 → 호출 노드 → `config.graph`.

    화면이 실행 중 강조를 편집 버퍼가 아니라 실행한 그래프 파일에 붙이는 데 쓴다 (M2 T11). 스냅샷을
    아직 만들지 않았거나 읽을 수 없는 파일은 빠진다 (읽기만 하고 판정하지 않는다).
    """
    root = folder / SNAPSHOT_DIR
    calls: dict[str, dict[str, str]] = {}
    try:
        files = sorted(root.rglob("*.graph.json"))
    except OSError:
        return calls
    for file in files:
        try:
            data = loads_strict(file.read_bytes().decode("utf-8"))
        except OSError, UnicodeDecodeError, ValueError:
            continue
        nodes = data.get("nodes") if isinstance(data, dict) else None
        if not isinstance(nodes, dict):
            continue
        found: dict[str, str] = {}
        for node_id, node in nodes.items():
            config = node.get("config") if isinstance(node, dict) else None
            target = config.get("graph") if isinstance(config, dict) else None
            if isinstance(node_id, str) and isinstance(target, str) and target != "":
                found[node_id] = target
        if found:
            calls[file.relative_to(root).as_posix()] = found
    return calls


def _runner_alive(run_start: Mapping[str, Any] | None) -> bool:
    """`run.start`의 runner(PID + 생성 시각 마이크로초)가 아직 살아 있는가."""
    runner = (run_start or {}).get("runner")
    if not isinstance(runner, dict):
        return False
    pid, created = runner.get("pid"), runner.get("created")
    if not isinstance(pid, int) or not isinstance(created, int):
        return False
    ident = identify(pid)
    return ident is not None and unix_micros(ident) == created and is_alive(ident)


def _outcome(run_end: Mapping[str, Any] | None, recover_error: str | None) -> dict[str, Any]:
    """`run.end` → `RunOutcome` (판정·CLI 종료 코드 규칙의 값·마무리한 쪽). `run.end`가 없으면
    감독자가 마무리하지 못한 오류다."""
    end = run_end or {}
    verdict = end.get("verdict")
    finalized_by = end.get("finalized_by")
    return {
        "verdict": verdict if verdict in _VERDICTS else "error",
        "exit_code": run_exit_code(run_end, recover_error=recover_error),
        "finalized_by": finalized_by if finalized_by in ("runner", "supervisor") else "supervisor",
    }
