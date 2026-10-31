"""daemon의 실행 관리 (M2 계획 2.3·2.8). daemon이 감독자다.

**시작 순서** (`run.start`). ①~⑥은 워크스페이스 **시작 잠금** 하나 안에서 직렬로 한다. 그래서 동시에
온 두 요청 중 하나만 실행 폴더·runner를 만든다

1. 중복 방지 키: 범위는 (주체 종류·주체 id, 키), 기한 10분. 같은 인자(경로·profile·settings·
   deadline_ms의 canonical 비교)면 앞 실행을 그대로 돌려준다 — 단 ②는 다시 한다. 다른 인자면
   `idempotency_conflict`
2. 권한 판정 (`Authorizer` → `WorkspaceService.require`). 이 메서드만 전송이 미리 판정하지 않는다
3. **시작 예약**: 진행 중이거나 예약된 실행이 있으면 `run_busy`, 종료가 정해졌으면
   `shutting_down`. 아니면 실행 ID를 미리 뽑아 예약한다
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
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Protocol

from kookabug_core.canonical import canonical_dumps
from kookabug_core.permissions import Decision, Principal
from kookabug_core.record import follow, read_run, read_run_json
from kookabug_core.record.runfolder import RUN_JSON_FILE, new_run_id, run_id_of_folder
from kookabug_core.registry import Registry
from kookabug_core.runner.run import unix_micros
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.schema import check_shape
from kookabug_core.service import WorkspaceService, start_options
from kookabug_core.supervisor import RunHandle, RunOutcome, run_exit_code
from kookabug_core.validate import check_graph
from kookabug_core.win import identify, is_alive
from kookabug_core.workspace import RunOptions, Workspace, WorkspaceError
from kookabug_daemon.documents import WsPath, recheck_path, resolve_path
from kookabug_daemon.methods.tools import Authorizer
from kookabug_daemon.protocol import RequestFailed

__all__ = [
    "IDEMPOTENCY_TTL_S",
    "TAIL_SIZE",
    "LagRecord",
    "RunManager",
    "RunSink",
    "StartRequest",
]

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
_VERDICTS: Final = frozenset({"error", "fail", "pass", "skipped"})


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


@dataclass(frozen=True, slots=True)
class StartRequest:
    principal: Principal
    path: str
    profile: str | None = None
    settings: Mapping[str, Any] = field(default_factory=dict[str, Any])
    deadline_ms: int | None = None
    idempotency_key: str | None = None


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

    @property
    def managed(self) -> bool:
        return self.handle is not None


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
    ) -> None:
        self.root = root
        self.service = service
        self.authorizer = authorizer
        self._registry = registry
        self.platform = platform or PlatformSpec("windows")
        self.plugin_modules = tuple(plugin_modules)
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
        self._closing = False
        """종료가 정해졌다: 새 시작 예약을 받지 않는다."""
        self._keys: dict[tuple[str, str, str], _Key] = {}
        self._current: dict[tuple[int, str], _Sub] = {}
        """(연결, 실행) → 지금 구독 (이벤트 루프만 바꾼다)."""
        self._lag_listening: set[int] = set()
        self._order = itertools.count()
        self._closed = threading.Event()

    # ---------------------------------------------------------------- 수명 (RunsLike)

    def active_run(self) -> str | None:
        with self._lock:
            return self._active or self._reserved

    def reserve_shutdown(self, *, force: bool) -> str | None:
        with self._lock:
            busy = self._active or self._reserved
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

    def _reserve(self) -> str:
        """③ 시작 예약 (시작 잠금 안). 겹치지 않는 실행 ID를 미리 뽑는다."""
        with self._lock:
            if self._closing:
                text = "daemon이 끝나는 중이다"
                raise RequestFailed("shutting_down", text, message=text)
            busy = self._active or self._reserved
            if busy is not None:
                raise RequestFailed("run_busy", f"진행 중인 실행 {busy}이(가) 있다", run_id=busy)
            run_id = new_run_id()
            while run_id in self._runs or self._find_folder(run_id) is not None:
                run_id = new_run_id()
            self._reserved = run_id
            return run_id

    def _unreserve(self, run_id: str) -> None:
        with self._lock:
            if self._reserved == run_id:
                self._reserved = None

    def _active_run(self) -> _Run | None:
        with self._lock:
            return None if self._active is None else self._runs.get(self._active)

    # ---------------------------------------------------------------- 시작

    def start(self, request: StartRequest) -> dict[str, Any]:
        """시작 순서 ①~⑥ (막히는 호출: 스레드에서 부른다)."""
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
            decision = self.authorizer.require(principal, "run.start", where.rel)
            assert decision is not None  # run.start는 ui_only가 아니다
            if previous is not None:
                return dict(previous.result)
            # ③ 시작 예약 (실행 중·종료 결정과 같은 잠금)
            reserved = self._reserve()
            try:
                handle, current = self._prepare_and_launch(request, where, decision, reserved)
            except BaseException:
                self._unreserve(reserved)
                raise
            # ⑥ 등록 (예약 → 진행 중)
            run = _Run(handle.run_id, handle.run_dir, current, handle, order=next(self._order))
            result = {"run_id": run.run_id, "run_dir": str(run.folder), "graph": run.graph}
            with self._lock:
                self._runs[run.run_id] = run
                self._active = run.run_id
                self._reserved = None
                if scope is not None:
                    self._keys[scope] = _Key(
                        args, run.run_id, dict(result), time.monotonic() + IDEMPOTENCY_TTL_S
                    )
            log.info("실행 %s 시작: %s (%s)", run.run_id, run.graph, principal.id)
            _thread(self._wait, run, name=f"kb-run-wait-{run.run_id}")
            _thread(self._follow, run, self._managed_stop(run), name=f"kb-run-follow-{run.run_id}")
            self._prune()
            return result

    def _prepare_and_launch(
        self, request: StartRequest, where: WsPath, decision: Decision, run_id: str
    ) -> tuple[RunHandle, str]:
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
        # ⑤ 시작 (②의 판정과 예약한 ID를 넘긴다)
        start = start_options(
            workspace.run_conditions(),
            deadline_ms=request.deadline_ms,
            profile=request.profile,
            settings=settings,
            plugin_modules=self.plugin_modules,
            platform=self.platform,
        )
        try:
            handle = self.service.start_decided(
                decision, current.rel, replace(start, run_id=run_id)
            )
        except (OSError, RuntimeError) as exc:  # 실행 폴더·Job·파이프를 만들지 못함
            text = f"실행을 시작할 수 없다: {exc}"
            raise RequestFailed("io_error", text, message=text) from exc
        return handle, current.rel

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

    def status(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._runs.get(run_id)
        folder = run.folder if run is not None else self._find_folder(run_id)
        summary = None if folder is None else self._summary(folder, run)
        if summary is None:
            raise RequestFailed("run_not_found", f"실행 {run_id}이(가) 없다", run_id=run_id)
        return summary

    def recent(self, limit: int | None) -> list[dict[str, Any]]:
        count = DEFAULT_LIST_LIMIT if limit is None else limit
        runs = self.root / RUNS_DIR
        try:
            folders = sorted((p for p in runs.iterdir() if p.is_dir()), key=lambda p: p.name)
        except OSError:
            return []
        found: list[dict[str, Any]] = []
        # 폴더 이름은 시작 시각(초)으로 시작한다: 최근 초부터 묶어서 보고, 같은 초 안에서는
        # `started_at`(밀리초)으로 정렬한다
        for _, group in itertools.groupby(reversed(folders), key=lambda p: p.name.split("_")[0]):
            if len(found) >= count:
                break
            summaries: list[dict[str, Any]] = []
            for folder in group:
                run_id = run_id_of_folder(folder)
                if run_id is None:
                    continue
                with self._lock:
                    run = self._runs.get(run_id)
                summary = self._summary(folder, run)
                if summary is not None:
                    summaries.append(summary)
            summaries.sort(key=lambda s: s["started_at"] or "", reverse=True)
            found.extend(summaries)
        return found[:count]

    def _summary(self, folder: Path, run: _Run | None) -> dict[str, Any] | None:
        run_id = run_id_of_folder(folder)
        if run_id is None:
            return None
        view = read_run(folder)
        data = read_run_json(folder / RUN_JSON_FILE) or {}
        graph = run.graph if run is not None else _graph_of(folder, data, view.run_start)
        started = data.get("started_at") or (view.run_start or {}).get("t")
        if started is None and run is not None and run.handle is not None:
            started = run.handle.started_at
        outcome: dict[str, Any] | None = None
        if run is not None and run.managed:
            running = not run.done.is_set()
            if not running:
                recover_error = None if run.outcome is None else run.outcome.recover_error
                run_end = view.run_end if run.outcome is None else run.outcome.run_end
                outcome = _outcome(run_end, recover_error)
        else:
            running = view.run_end is None and _runner_alive(view.run_start)
            if view.run_end is not None:
                outcome = _outcome(view.run_end, None)
        summary = {
            "run_id": run_id,
            "run_dir": str(folder),
            "graph": graph,
            "state": "running" if running else "ended",
            "started_at": started,
            "last_seq": view.last_seq,
            "outcome": outcome,
        }
        if check_shape(summary, "daemon-rpc", ref="#/$defs/RunSummary"):
            log.warning("실행 폴더 %s를 요약할 수 없다 (형식이 틀린 기록)", folder)
            return None
        return summary


# ---------------------------------------------------------------- 도움 함수


def _thread(target: Callable[..., None], *args: Any, name: str) -> None:
    threading.Thread(target=target, args=args, name=name, daemon=True).start()


def _open_workspace(root: Path) -> Workspace:
    try:
        return Workspace.open(root)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


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
