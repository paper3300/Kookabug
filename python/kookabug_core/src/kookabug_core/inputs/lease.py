"""입력 임대권 (구현 계획 M0b 2.4 "입력 임대권", 구현 계획 v0 3장).

하나의 Windows 사용자 세션에서 입력을 보낼 수 있는 주체는 하나다. 이름 있는 뮤텍스
(`Local\\Kookabug.InputLease`, `KOOKABUG_INPUT_LEASE_NAME`)로 구현한다.

- Windows 뮤텍스는 스레드 소유이므로 **전용 스레드**가 얻고, 놓기 신호를 기다렸다 같은 스레드에서
  놓는다. 프로세스가 놓지 않고 끝나면 다음 획득자는 `ABANDONED`로 얻는다 — 단 그때 다른 핸들이
  열려 있을 때만이다(마지막 핸들이 닫히면 뮤텍스가 없어져 새로 얻는다). 그래서 복구할지는
  `ABANDONED`가 아니라 옆 파일의 `clean`으로 정한다
- 옆 파일 `<상태 폴더>/input-lease.json`(`KOOKABUG_STATE_DIR`, 기본 `%LOCALAPPDATA%\\Kookabug`):
  `{owner: {kind, workspace, run_id, run_dir, pid, created} | null, clean, last_owner?}`. 임대권을
  쥔 소유자만 쓴다(임시 파일 + `os.replace`)
- **얻기**: 얻은 직후 옆 파일을 읽어 앞 소유자가 깨끗하게 놓지 않았으면(`clean: false`) 복구를
  먼저 한다 — 앞 실행 기록의 `held_inputs()`를 자기 백엔드로 떼고, 앞 실행 폴더에
  `input-recovery.json`을 배타적 생성으로 남긴다(이미 있으면 복구는 끝난 것). 그 뒤 자기 정보를
  `clean: false`로 쓴다. 복구는 액터를 띄우기 전, 얻는 스레드에서 하므로 단일 생산자가 깨지지 않는다
- **깨끗한 놓기 = 액터가 멈춘 뒤**: `release(actor)`는 액터가 quiesced일 때만 옆 파일을
  `clean: true`로 쓰고 놓는다. 아니면 놓지 않는다 — 프로세스가 끝날 때 버려지고, 다음 획득자가
  복구한다
- 감독자 복구 경로의 키 복구도 임대권 안에서만 한다 (`recover_run`)
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

from kookabug_core.inputs.actor import Emit
from kookabug_core.inputs.backends import InputBackend
from kookabug_core.record.finalize import InputRecoveryOutcome
from kookabug_core.record.reader import InputKey, held_inputs, read_run
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE, run_id_of_folder
from kookabug_core.win import NamedMutex, ProcessId, WaitResult, current, is_alive
from kookabug_sdk import _faults

if TYPE_CHECKING:
    from kookabug_core.inputs.actor import InputActor

__all__ = [
    "DEFAULT_LEASE_NAME",
    "LEASE_FILE",
    "LEASE_NAME_ENV",
    "STATE_DIR_ENV",
    "Acquired",
    "InputLease",
    "InputLeaseBusy",
    "LeaseOwner",
    "Recovery",
    "lease_file",
    "lease_name",
    "read_lease_file",
    "recover_run",
    "state_dir",
]

LEASE_NAME_ENV: Final = "KOOKABUG_INPUT_LEASE_NAME"
STATE_DIR_ENV: Final = "KOOKABUG_STATE_DIR"
DEFAULT_LEASE_NAME: Final = "Local\\Kookabug.InputLease"
LEASE_FILE: Final = "input-lease.json"
LEASE_THREAD_NAME: Final = "kookabug-input-lease"

# 감독자 복구 경로가 임대권을 기다리는 시간 (2.4 recover_run ③)
RECOVER_TIMEOUT_S: Final = 10.0
_REPLACE_RETRY_S: Final = 5.0

type OwnerKind = Literal["runner", "supervisor"]


def lease_name() -> str:
    return os.environ.get(LEASE_NAME_ENV) or DEFAULT_LEASE_NAME


def state_dir() -> Path:
    override = os.environ.get(STATE_DIR_ENV)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "Kookabug"


def lease_file(directory: str | os.PathLike[str] | None = None) -> Path:
    return Path(directory if directory is not None else state_dir()) / LEASE_FILE


@dataclass(frozen=True, slots=True)
class LeaseOwner:
    """임대권 소유자. `run_dir`은 복구할 때 읽을 실행 폴더(이 주체가 입력을 기록하는 곳)."""

    kind: OwnerKind
    process: ProcessId
    run_id: str | None = None
    run_dir: str | None = None
    workspace: str | None = None

    @classmethod
    def current(
        cls,
        kind: OwnerKind,
        *,
        run_id: str | None = None,
        run_dir: str | os.PathLike[str] | None = None,
        workspace: str | os.PathLike[str] | None = None,
    ) -> LeaseOwner:
        return cls(
            kind=kind,
            process=current(),
            run_id=run_id,
            run_dir=None if run_dir is None else str(run_dir),
            workspace=None if workspace is None else str(workspace),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "workspace": self.workspace,
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            **self.process.to_json(),
        }


@dataclass(frozen=True, slots=True)
class Recovery:
    """앞 소유자가 남긴 키를 뗀 결과. `inputs`가 비어도 복구 표시 파일은 남긴다."""

    from_run: str | None
    run_dir: Path
    inputs: tuple[InputKey, ...]


@dataclass(frozen=True, slots=True)
class Acquired:
    abandoned: bool
    """앞 소유자가 놓지 않고 끝났다 (`WAIT_ABANDONED`)."""
    previous: Mapping[str, Any] | None
    """얻을 때 읽은 옆 파일."""
    recovered: tuple[Recovery, ...]


class InputLeaseBusy(Exception):
    """다른 주체가 임대권을 쥐고 있다. `owner`는 살아 있음이 확인된 소유자 정보, 모르면 None."""

    code: Final = "input_lease_busy"

    def __init__(
        self, owner: Mapping[str, Any] | None, *, stale_owner: Mapping[str, Any] | None = None
    ) -> None:
        self.owner = None if owner is None else dict(owner)
        self.stale_owner = None if stale_owner is None else dict(stale_owner)
        if owner is None:
            who = "알 수 없는 주체"
        else:
            run = f" 실행 {owner.get('run_id')}" if owner.get("run_id") else ""
            who = f"{owner.get('kind')}{run} (PID {owner.get('pid')})"
        super().__init__(f"입력 임대권을 다른 주체가 쥐고 있다: {who}")

    def to_json(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "owner": self.owner}


class InputLease:
    """입력 임대권 하나. `acquire()` → (입력) → `release(actor)`.

    `emit`을 주면 앞 소유자를 복구했을 때 자기 실행 기록에 `input.recovered`를 남긴다.
    """

    def __init__(
        self,
        owner: LeaseOwner,
        backend: InputBackend,
        *,
        name: str | None = None,
        directory: str | os.PathLike[str] | None = None,
        emit: Emit | None = None,
    ) -> None:
        self.owner = owner
        self.backend = backend
        self.name = name or lease_name()
        self.file = lease_file(directory)
        self._emit = emit
        self._thread: threading.Thread | None = None
        self._release_signal = threading.Event()
        self._held = False

    @property
    def held(self) -> bool:
        return self._held

    def acquire(self, timeout: float = 0) -> Acquired:
        """얻고, 앞 소유자가 깨끗하게 놓지 않았으면 복구를 먼저 한다.

        다른 주체가 쥐고 있으면 `InputLeaseBusy`. 복구 중 실패하면 놓고(옆 파일은 그대로) 다시
        던진다.
        """
        if self._thread is not None:
            raise RuntimeError("임대권은 한 번만 얻는다")
        ready = threading.Event()
        outcome: list[WaitResult | BaseException] = []
        self._release_signal.clear()
        thread = threading.Thread(
            target=self._hold,
            args=(timeout, ready, outcome),
            name=LEASE_THREAD_NAME,
            daemon=True,
        )
        thread.start()
        ready.wait()
        result = outcome[0]
        if isinstance(result, BaseException):
            thread.join()
            raise result
        if result is WaitResult.TIMEOUT:
            thread.join()
            raise _busy(read_lease_file(self.file.parent))
        self._thread = thread
        self._held = True
        try:
            _faults.fault_point("lease.before_recovery")
            previous = read_lease_file(self.file.parent)
            recovered = self._recover_previous(previous)
            _write_json(self.file, {"owner": self.owner.to_json(), "clean": False})
        except BaseException:
            self.abandon()
            raise
        return Acquired(
            abandoned=result is WaitResult.ABANDONED,
            previous=previous,
            recovered=recovered,
        )

    def release(self, actor: InputActor | None) -> bool:
        """깨끗하게 놓는다. 액터가 quiesced가 아니면 놓지 않고 False (옆 파일은 `clean: false`).

        `actor`가 None이면 이 소유자가 입력을 보낸 적이 없다는 뜻이다 (감독자 복구 경로).
        """
        if not self._held:
            raise RuntimeError("쥐고 있지 않은 임대권이다")
        if actor is not None and not actor.quiesced:
            return False
        _write_json(self.file, {"owner": None, "clean": True, "last_owner": self.owner.to_json()})
        self._let_go()
        return True

    def abandon(self) -> None:
        """깨끗하지 않게 놓는다 (옆 파일을 고치지 않음 → 다음 획득자가 복구한다).

        프로세스가 놓지 않고 끝난 것과 같다. 이 프로세스가 더 입력하지 않는 것이 확실할 때만 쓴다.
        """
        if self._held:
            self._let_go()

    def _let_go(self) -> None:
        self._release_signal.set()
        if self._thread is not None:
            self._thread.join()
        self._thread = None
        self._held = False

    def _hold(
        self, timeout: float, ready: threading.Event, outcome: list[WaitResult | BaseException]
    ) -> None:
        try:
            mutex = NamedMutex.open(self.name)
        except BaseException as exc:
            outcome.append(exc)
            ready.set()
            return
        with mutex:
            try:
                result = mutex.wait(timeout)
            except BaseException as exc:
                outcome.append(exc)
                ready.set()
                return
            outcome.append(result)
            ready.set()
            if result is WaitResult.TIMEOUT:
                return
            self._release_signal.wait()
            mutex.release()

    def _recover_previous(self, previous: Mapping[str, Any] | None) -> tuple[Recovery, ...]:
        if previous is None or previous.get("clean") is True:
            return ()
        owner = previous.get("owner")
        if not isinstance(owner, Mapping):
            return ()
        owner_map: Mapping[str, Any] = owner
        run_dir = owner_map.get("run_dir")
        if not isinstance(run_dir, str) or not run_dir:
            return ()
        run_id = owner_map.get("run_id")
        recovery = self.recover_run_dir(Path(run_dir), run_id if isinstance(run_id, str) else None)
        return () if recovery is None else (recovery,)

    def recover_run_dir(
        self, run_dir: Path, run_id: str | None, held: Sequence[InputKey] | None = None
    ) -> Recovery | None:
        """그 실행의 눌렸을 수 있는 키를 뗀다 (임대권을 쥔 동안만). 복구 표시 파일이 있으면 None."""
        if not self._held:
            raise RuntimeError("키 복구는 임대권 안에서만 한다")
        marker = run_dir / INPUT_RECOVERY_FILE
        if marker.exists() or not run_dir.is_dir():
            return None
        view = read_run(run_dir)
        keys = tuple(held if held is not None else held_inputs(view))
        from_run = run_id or view.run_id or run_id_of_folder(run_dir)
        for key in keys:
            if key.device == "keyboard":
                self.backend.up(key.name)
            else:
                self.backend.mouse_up(key.name)
        # 떼기를 다 한 뒤에 표시한다: 그 사이에 죽으면 다음 획득자가 다시 뗀다(떼기는 해가 없다)
        record = {
            "recovered_by": {"kind": self.owner.kind, "run_id": self.owner.run_id},
            "keys": [k.to_event() for k in keys],
            "at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
        try:
            with marker.open("x", encoding="utf-8") as f:
                json.dump(record, f, ensure_ascii=False, sort_keys=True)
        except FileExistsError:
            pass
        if keys and self._emit is not None and from_run is not None:
            by: dict[str, Any] = {"kind": self.owner.kind}
            if self.owner.run_id is not None:
                by["run"] = self.owner.run_id
            self._emit(
                {
                    "event": "input.recovered",
                    "from_run": from_run,
                    "inputs": [k.to_event() for k in keys],
                    "by": by,
                }
            )
        return Recovery(from_run, run_dir, keys)


def recover_run(
    run_dir: str | os.PathLike[str],
    *,
    backend: InputBackend,
    held: Sequence[InputKey] | None = None,
    timeout: float = RECOVER_TIMEOUT_S,
    name: str | None = None,
    directory: str | os.PathLike[str] | None = None,
) -> InputRecoveryOutcome:
    """감독자 복구 경로의 키 복구 (2.4). runner 종료를 확인한 뒤에만 부른다.

    1. 그 실행 폴더에 복구 표시 파일이 있으면(다음 소유자가 이미 뗌) 건너뛴다
    2. 옆 파일이 그 실행이 깨끗하게 놓았다고 하면 뗄 키가 없다
    3. 임대권을 `timeout` 안에 얻어 얻기 복구를 돌리고, 그래도 남았으면 그 실행을 직접 복구한다.
       입력은 하지 않았으므로 곧바로 깨끗하게 놓는다
    4. 못 얻으면 표시 파일을 한 번 더 보고, 없으면 `lease_busy`

    결과의 `input.recovered`는 부르는 쪽(`finalize_run`)이 그 실행 기록에 남긴다.
    """
    folder = Path(run_dir)
    marker = folder / INPUT_RECOVERY_FILE
    if marker.exists():
        return InputRecoveryOutcome("already_recovered")
    view = read_run(folder)
    keys = tuple(held if held is not None else held_inputs(view))
    if not keys:
        return InputRecoveryOutcome("not_needed")
    run_id = view.run_id or run_id_of_folder(folder)
    if _released_clean_by(read_lease_file(directory), run_id, folder):
        return InputRecoveryOutcome("not_needed")

    owner = LeaseOwner.current("supervisor", run_id=run_id, run_dir=folder)
    lease = InputLease(owner, backend, name=name, directory=directory)
    try:
        acquired = lease.acquire(timeout)
    except InputLeaseBusy:
        if marker.exists():
            return InputRecoveryOutcome("already_recovered")
        return InputRecoveryOutcome("lease_busy")
    try:
        outcome = _recover_target(lease, acquired, folder, run_id, keys)
    except BaseException:
        # 옆 파일에는 이 감독자(run_dir = 그 실행)가 dirty로 남는다 → 다음 획득자가 그 실행을 복구
        lease.abandon()
        raise
    lease.release(None)
    return outcome


def _recover_target(
    lease: InputLease,
    acquired: Acquired,
    folder: Path,
    run_id: str | None,
    keys: Sequence[InputKey],
) -> InputRecoveryOutcome:
    for recovery in acquired.recovered:
        if _same_dir(recovery.run_dir, folder):
            return InputRecoveryOutcome("recovered", recovery.inputs)
    recovery = lease.recover_run_dir(folder, run_id, keys)
    if recovery is None:
        return InputRecoveryOutcome("already_recovered")
    return InputRecoveryOutcome("recovered", recovery.inputs)


def read_lease_file(directory: str | os.PathLike[str] | None = None) -> dict[str, Any] | None:
    """옆 파일 (없거나 JSON 객체가 아니면 None)."""
    path = lease_file(directory)
    deadline = time.monotonic() + _REPLACE_RETRY_S
    while True:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError, ValueError:
            return None
        except PermissionError:
            # 다른 프로세스가 os.replace로 바꾸는 중
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)
            continue
        return value if isinstance(value, dict) else None


def _released_clean_by(data: Mapping[str, Any] | None, run_id: str | None, folder: Path) -> bool:
    if data is None or data.get("clean") is not True:
        return False
    last = data.get("last_owner")
    if not isinstance(last, Mapping):
        return False
    last_map: Mapping[str, Any] = last
    if run_id is not None and last_map.get("run_id") == run_id:
        return True
    run_dir = last_map.get("run_dir")
    return isinstance(run_dir, str) and _same_dir(Path(run_dir), folder)


def _same_dir(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _busy(data: Mapping[str, Any] | None) -> InputLeaseBusy:
    owner = None if data is None else data.get("owner")
    if not isinstance(owner, Mapping):
        return InputLeaseBusy(None)
    owner_map: Mapping[str, Any] = owner
    try:
        ident = ProcessId.from_json(owner_map)
    except KeyError, TypeError, ValueError:
        return InputLeaseBusy(None, stale_owner=owner_map)
    if is_alive(ident):
        return InputLeaseBusy(owner_map)
    # 옆 파일의 소유자는 이미 끝났다: 지금 쥔 주체는 아직 자기 정보를 쓰기 전이다
    return InputLeaseBusy(None, stale_owner=owner_map)


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    """임시 파일 → `fsync` → `os.replace`. 읽는 쪽이 파일을 열고 있으면 잠시 다시 해 본다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(dict(data), ensure_ascii=False, sort_keys=True).encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=".input-lease.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        deadline = time.monotonic() + _REPLACE_RETRY_S
        while True:
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.005)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
