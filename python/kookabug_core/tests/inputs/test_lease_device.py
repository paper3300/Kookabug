"""얻기 복구는 앞 실행의 **입력 장치**로 뗀다 (구현 계획 v0 3장 "입력 임대권", M1 T5 검수 1).

실제 장치는 SendInput 백엔드의 전송 함수를 바꿔 끼운 대역(`Device`)이다 — OS 입력을 보내지 않는다.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from kb_testing.proc import read_fake_input_log
from kookabug_core.inputs import (
    FakeBackend,
    InputActor,
    InputBackend,
    InputDevice,
    InputLease,
    LeaseOwner,
    read_lease_file,
    recover_run,
)
from kookabug_core.record import Journal
from kookabug_core.record.runfolder import EVENTS_FILE, INPUT_RECOVERY_FILE
from kookabug_platform.sendinput import SendInputBackend
from kookabug_platform.win32 import user32


@dataclass
class Device:
    """SendInput 전송 대역: 키 상태와 보낸 것."""

    held: set[int] = field(default_factory=set[int])
    calls: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])

    def send(self, inputs: Sequence[user32.INPUT]) -> int:
        for item in inputs:
            vk = int(item.ki.wVk)
            up = bool(item.ki.dwFlags & user32.KEYEVENTF_KEYUP)
            self.calls.append(("up" if up else "down", vk))
            (self.held.discard if up else self.held.add)(vk)
        return len(inputs)

    def backend(self) -> SendInputBackend:
        return SendInputBackend(send=self.send)


@dataclass
class Env:
    tmp_path: Path
    name: str
    state: Path
    journals: list[Journal] = field(default_factory=list[Journal])
    actors: list[InputActor] = field(default_factory=list[InputActor])
    leases: list[InputLease] = field(default_factory=list[InputLease])

    def lease(
        self,
        run_id: str,
        backend: InputBackend,
        device_backend: Callable[[InputDevice], InputBackend] | None = None,
    ) -> InputLease:
        folder = self.tmp_path / "runs" / run_id
        folder.mkdir(parents=True, exist_ok=True)
        owner = LeaseOwner.current("runner", run_id=run_id, run_dir=folder)
        lease = InputLease(
            owner, backend, name=self.name, directory=self.state, device_backend=device_backend
        )
        self.leases.append(lease)
        return lease

    def die_holding(self, run_id: str, backend: InputBackend, key: str) -> Path:
        """실행 하나가 임대권을 얻고 `key`를 누른 채 (놓지 않고) 죽는다."""
        lease = self.lease(run_id, backend)
        lease.acquire()
        folder = self.tmp_path / "runs" / run_id
        journal = Journal(folder / EVENTS_FILE, run_id)
        self.journals.append(journal)
        actor = InputActor(backend, emit=journal.emit).start()
        self.actors.append(actor)
        actor.press(key)
        lease.abandon()
        return folder


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    made = Env(tmp_path, f"Local\\Kookabug.Test.T5.{uuid.uuid4().hex}", tmp_path / "state")
    yield made
    for lease in made.leases:
        if lease.held:
            lease.abandon()
    for actor in made.actors:
        actor.stop(5)
    for journal in made.journals:
        journal.close()


def test_lease_file_records_owner_device(env: Env) -> None:
    device = Device()
    lease = env.lease("aaaaaaaa", device.backend())
    lease.acquire()
    data = read_lease_file(env.state)
    assert data is not None and data["owner"]["device"] == {"kind": "windows"}
    assert lease.release(None)
    data = read_lease_file(env.state)
    assert data is not None and data["last_owner"]["device"] == {"kind": "windows"}
    log = env.tmp_path / "x.jsonl"
    assert InputDevice.from_json(FakeBackend(log).device.to_json()) == InputDevice.fake(log)


def test_windows_run_keys_released_on_real_device_by_next_fake_owner(env: Env) -> None:
    device = Device()
    a_dir = env.die_holding("aaaaaaaa", device.backend(), "a")
    assert device.held == {0x41}
    made: list[InputDevice] = []

    def windows_device(found: InputDevice) -> InputBackend:
        made.append(found)
        return device.backend()

    fake_log = env.tmp_path / "b.jsonl"
    b = env.lease("bbbbbbbb", FakeBackend(fake_log), device_backend=windows_device)
    acquired = b.acquire()
    # 가짜 실행 B는 A의 실제 키를 A의 장치(SendInput)로 뗐다. 자기 가짜 기록에는 쓰지 않았다
    assert made == [InputDevice("windows")]
    assert device.held == set() and device.calls[-1] == ("up", 0x41)
    assert not fake_log.exists()
    (recovery,) = acquired.recovered
    assert [k.name for k in recovery.inputs] == ["a"]
    assert (a_dir / INPUT_RECOVERY_FILE).exists()
    assert b.release(None)
    # 늦게 온 A의 감독자는 이미 복구됨으로 건너뛴다 — 실제로 뗐으므로 맞다
    calls = len(device.calls)
    late = recover_run(a_dir, backend=device.backend(), name=env.name, directory=env.state)
    assert late.status == "already_recovered" and len(device.calls) == calls


def test_fake_run_keys_released_on_its_log_not_sent_to_real_device(env: Env) -> None:
    a_log = env.tmp_path / "a.jsonl"
    env.die_holding("aaaaaaaa", FakeBackend(a_log, by="a"), "a")
    device = Device()
    b = env.lease("bbbbbbbb", device.backend())
    b.acquire()
    # 실제 실행 B는 A의 가짜 키를 A의 가짜 기록으로 뗐다 — 실제 SendInput은 보내지 않았다
    assert device.calls == []
    ops = [(line["op"], line["key"]) for line in read_fake_input_log(a_log)]
    assert ops == [("down", "a"), ("up", "a")]
    assert b.release(None)


def test_release_failure_leaves_no_marker_and_next_owner_retries(env: Env) -> None:
    device = Device()
    a_dir = env.die_holding("aaaaaaaa", device.backend(), "a")

    def broken(found: InputDevice) -> InputBackend:
        return SendInputBackend(send=lambda inputs: 0)  # 장치에 보낼 수 없다

    b = env.lease("bbbbbbbb", FakeBackend(env.tmp_path / "b.jsonl"), device_backend=broken)
    with pytest.raises(OSError):
        b.acquire()
    assert not (a_dir / INPUT_RECOVERY_FILE).exists()  # 떼지 못했으면 표시하지 않는다
    assert device.held == {0x41}
    data = read_lease_file(env.state)
    assert data is not None and data["owner"]["run_id"] == "aaaaaaaa"  # 옆 파일 그대로
    c = env.lease("cccccccc", device.backend())
    c.acquire()
    assert device.held == set()
    marker = json.loads((a_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
    assert marker["recovered_by"]["run_id"] == "cccccccc"
    assert c.release(None)


def unavailable(found: InputDevice) -> InputBackend:
    raise ModuleNotFoundError(f"이 실행 환경에는 {found.kind} 장치의 플랫폼이 없다")


def test_already_recovered_run_needs_no_previous_device_backend(env: Env) -> None:
    # windows 실행 A를 누군가 복구해 표시까지 썼지만 옆 파일을 고치기 전에 죽은 경계. 다음 가짜
    # 실행은 표시를 먼저 보므로 windows 백엔드를 만들지 않는다 (플랫폼이 없어도 얻는다)
    device = Device()
    a_dir = env.die_holding("aaaaaaaa", device.backend(), "a")
    fixer = env.lease("ffffffff", device.backend())
    fixer.acquire()  # A의 a를 떼고 표시
    assert (a_dir / INPUT_RECOVERY_FILE).exists() and device.held == set()
    data = read_lease_file(env.state)
    assert data is not None
    fixer.abandon()
    # 옆 파일을 A(dirty)로 되돌린다 = 표시를 쓴 뒤 자기 정보를 쓰기 전에 죽음
    a_owner = {**data["owner"], "run_id": "aaaaaaaa", "run_dir": str(a_dir)}
    (env.state / "input-lease.json").write_text(
        json.dumps({"owner": a_owner, "clean": False}), encoding="utf-8"
    )
    b = env.lease("bbbbbbbb", FakeBackend(env.tmp_path / "b.jsonl"), device_backend=unavailable)
    assert b.acquire().recovered == ()
    assert b.release(None)


def test_no_held_keys_needs_no_previous_device_backend(env: Env) -> None:
    # 뗄 키가 없는 windows 실행(누르기 전에 죽음): 표시는 남기되 장치 백엔드는 만들지 않는다
    device = Device()
    a = env.lease("aaaaaaaa", device.backend())
    a.acquire()
    a.abandon()
    b = env.lease("bbbbbbbb", FakeBackend(env.tmp_path / "b.jsonl"), device_backend=unavailable)
    (recovery,) = b.acquire().recovered
    assert recovery.inputs == ()
    assert (env.tmp_path / "runs" / "aaaaaaaa" / INPUT_RECOVERY_FILE).exists()
    assert b.release(None)
