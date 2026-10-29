"""입력 제어: 입력 액터(백엔드를 부르는 유일한 스레드), 입력 임대권과 임대권 안의 복구, 백엔드
(`none`·`fake`) (구현 계획 M0b 2.4)."""

from kookabug_core.inputs.actor import ACTOR_THREAD_NAME, Emit, InputActor
from kookabug_core.inputs.backends import (
    BackendKind,
    FakeBackend,
    HookAction,
    InputBackend,
    NoneBackend,
    PlatformUnavailable,
    create_backend,
)
from kookabug_core.inputs.lease import (
    Acquired,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    Recovery,
    lease_file,
    lease_name,
    read_lease_file,
    recover_run,
    state_dir,
)

__all__ = [
    "ACTOR_THREAD_NAME",
    "Acquired",
    "BackendKind",
    "Emit",
    "FakeBackend",
    "HookAction",
    "InputActor",
    "InputBackend",
    "InputLease",
    "InputLeaseBusy",
    "LeaseOwner",
    "NoneBackend",
    "PlatformUnavailable",
    "Recovery",
    "create_backend",
    "lease_file",
    "lease_name",
    "read_lease_file",
    "recover_run",
    "state_dir",
]
