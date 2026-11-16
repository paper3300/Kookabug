"""UX9 2·3 (검수1 High 1·2, 재검수2 High): runner 창 따라가기의 소유 범위와 후보 바인딩 검증.

- 소유 범위는 그 게임의 **기록해 둔 가족**(처음 정체 + 확인된 자손, 각각 PID+생성 시각)뿐이다 —
  실행 Job 전체가 아니고, 사후 추정도 없다. 새 자손은 살아 있는 가족(스냅샷 전·후 같은 정체) 밑에서
  생성 시각을 두 번 읽어 같고 부모보다 늦으며, 연속 두 확인에서 같은 정체로 볼 때만 더한다
- 끝난 부모·정체를 모르는 부모 밑으로는 더하지 않는다(재검수2 네 경우). 기록한 가족은 각자 정체가
  맞으면 원래 게임이 끝나도 유효하다(런처형)
- 새 후보는 열거 때의 HWND 주인(PID·생성 시각)과 `_ref` 바인딩이 같고 가족 안일 때만 — 열거와
  바인딩 사이 HWND 재사용(외부 프로세스)은 버리고 다시 찾는다. 식별 불능도 버린다
- 실제 프로세스: 자식 프로세스는 기록되고, 끝나면 빠진다

OS 조회(부모 표·생성 시각·창 주인)는 대역이다. 입력은 보내지 않는다.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest

from kb_testing.proc import wait_until
from kookabug_core.engine import FakeClock
from kookabug_core.engine.context import Runtime, window_key
from kookabug_core.win import ProcessId, current
from kookabug_platform import process as processes
from kookabug_platform import windows as wins
from kookabug_platform.platform import WindowsPlatform
from kookabug_platform.win32 import api as win_api
from kookabug_sdk.types import ProcessRef, WindowRef

# 가짜 프로세스 표: PID → (부모 PID, 생성 시각)
TABLE = {
    101: (1, 10),  # 게임 A
    111: (101, 11),  # A가 띄운 본 게임 (자손)
    112: (111, 12),  # 그 자손
    202: (1, 20),  # 같은 실행에서 따로 띄운 게임 B
    999: (1, 5),  # 실행기
}

ORIGINAL_FAMILY = processes.family


class Os:
    """프로세스 대역: PID → (부모 PID, 생성 시각). 표에서 빼면 끝난 프로세스다."""

    def __init__(self, table: dict[int, tuple[int, int]]) -> None:
        self.table = dict(table)

    def parents(self) -> dict[int, int]:
        return {p: v[0] for p, v in self.table.items()}

    def created(self, pid: int) -> int | None:
        entry = self.table.get(pid)
        return None if entry is None else entry[1]

    def family(self, root: Any, alive: bool, **_: Any) -> list[ProcessId]:
        return ORIGINAL_FAMILY(root, alive, parents=self.parents, created=self.created)


def fake_family(monkeypatch: pytest.MonkeyPatch, table: dict[int, tuple[int, int]]) -> Os:
    os_ = Os(table)
    monkeypatch.setattr(processes, "family", os_.family)
    return os_


def pids(found: list[ProcessId]) -> list[int]:
    return [p.pid for p in found]


# ---------------------------------------------------------------- 가족 기록 (순수)


def test_descendants_recorded_only_after_two_checks() -> None:
    """살아 있는 게임 밑 자손은 연속 두 확인에서 같은 정체로 볼 때 기록된다. 다른 게임·실행기는
    끝내 들지 않는다."""
    os_ = Os(TABLE)
    record = processes.GameFamily(ProcessId(101, 10))
    seen = [pids(os_.family(record, True)) for _ in range(4)]
    assert seen == [[101], [101, 111], [101, 111], [101, 111, 112]]
    assert {202, 999}.isdisjoint(record.members)


def test_recorded_family_outlives_root_but_never_grows_under_dead_parent() -> None:
    """런처형: 기록한 자손은 원래 게임이 끝나도 유효하다. 끝난 부모 밑 새 자식은 더하지 않는다."""
    os_ = Os(TABLE)
    record = processes.GameFamily(ProcessId(101, 10))
    for _ in range(2):
        os_.family(record, True)
    del os_.table[101]  # 런처가 끝났다
    os_.table[150] = (101, 15)  # 그 PID 밑으로 보이는 새 프로세스 (증명할 수 없다)
    found: list[ProcessId] = []
    for _ in range(3):
        found = os_.family(record, False)
    assert 150 not in pids(found) and 111 in pids(found)


def test_no_descendant_without_live_root() -> None:
    """처음부터 끝났거나 PID를 다른 프로세스가 쓰는 게임 밑으로는 아무것도 더하지 않는다."""
    for table in ({111: (101, 11)}, {101: (1, 40), 150: (101, 41), 111: (101, 11)}):
        os_ = Os(table)
        record = processes.GameFamily(ProcessId(101, 10))
        for _ in range(3):
            assert os_.family(record, False) == []
            assert os_.family(record, True) == []  # 살아 있다고 해도 생성 시각이 다르다
        assert record.members == {}


@pytest.mark.parametrize("case", ["unstable", "older", "parent_flips"])
def test_child_not_added_when_identity_unproven(case: str) -> None:
    """생성 시각 두 번 읽기가 다르거나, 부모보다 먼저 생겼거나, 스냅샷 뒤 부모 정체가 달라지면
    더하지 않는다."""
    os_ = Os({101: (1, 10), 111: (101, 5 if case == "older" else 11)})
    reads = [0]

    def created(pid: int) -> int | None:
        if pid == 111 and case == "unstable":
            reads[0] += 1
            return 11 + reads[0] % 2  # 읽을 때마다 다르다
        return os_.created(pid)

    def parents() -> dict[int, int]:
        table = os_.parents()
        if case == "parent_flips":
            os_.table[101] = (1, 99)  # 스냅샷 직후 101을 다른 프로세스가 쓴다
        return table

    record = processes.GameFamily(ProcessId(101, 10))
    for _ in range(3):
        if case == "parent_flips":
            os_.table[101] = (1, 10)
        ORIGINAL_FAMILY(record, True, parents=parents, created=created)
    assert record.members == {}


# ---------------------------------------------------------------- 플랫폼·엔진 따라가기


def runtime(platform: Any, old: WindowRef, owner: ProcessRef) -> Runtime:
    rt = object.__new__(Runtime)
    rt.run = "ux9scope"
    rt.platform = platform
    rt.owners = {window_key(old): owner}
    rt.follows = {}
    rt.clock = FakeClock()
    rt.deadline = SimpleNamespace(remaining_ms=20000)  # pyright: ignore[reportAttributeAccessIssue]
    rt.check = lambda: None  # pyright: ignore[reportAttributeAccessIssue]
    rt.emit_to = lambda event: None
    rt.on_window_changed = None
    return rt


class OsWindows:
    """창 주인 대역: HWND → (PID, 생성 시각). `swap`이면 처음 바인딩 때 다른 프로세스가 HWND를
    쓴다."""

    def __init__(self, owners: dict[int, tuple[int, int]]) -> None:
        self.owners = owners
        self.swap: dict[int, tuple[int, int]] = {}
        self.binds = 0

    def install(self, monkeypatch: pytest.MonkeyPatch, platform: WindowsPlatform) -> None:
        api = win_api.DEFAULT_API
        monkeypatch.setattr(api, "window_pid", lambda hwnd: self.owners.get(hwnd, (0, 0))[0])
        created = {pid: made for pid, made in self.owners.values()}
        monkeypatch.setattr(api, "process_created", lambda pid: created.get(pid))
        monkeypatch.setattr(platform, "_ref", self.ref)
        monkeypatch.setattr(platform, "window_alive", lambda window: True)
        monkeypatch.setattr(platform, "activate", lambda window: True)

    def ref(self, hwnd: int) -> WindowRef:
        self.binds += 1
        pid, made = self.swap.pop(hwnd, None) or self.owners[hwnd]
        return WindowRef(hwnd, pid=pid, process_created=str(made), binding=f"b{self.binds}")


def launched(alive: bool, created: int = 10) -> Any:
    return SimpleNamespace(alive=lambda: alive, created=created)


def test_finished_game_does_not_follow_other_game_of_same_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """검수1 재현 1: A(101)가 끝나고 Job에는 실행기·B만 — B 창으로 넘어가지 않는다."""
    fake_family(monkeypatch, {k: v for k, v in TABLE.items() if k in (202, 999)})
    job: Any = SimpleNamespace(process_ids=lambda: [999, 202])
    platform = WindowsPlatform(job=job)
    platform._processes[101] = launched(False)  # pyright: ignore[reportPrivateUsage]
    os_windows = OsWindows({0x7D2: (202, 20)})
    os_windows.install(monkeypatch, platform)
    monkeypatch.setattr(wins, "main_window", lambda *, title, pids: 0x7D2 if 202 in pids else None)
    old = WindowRef(1001, pid=101, process_created="10", binding="old")
    assert not platform.process_running(ProcessRef(101), "10")
    found, _ = runtime(platform, old, ProcessRef(101)).follow(old, None, "s", "n")
    assert found is None


def test_launcher_child_recorded_then_followed(monkeypatch: pytest.MonkeyPatch) -> None:
    """정상 경우(런처형): 살아 있는 게임(101) 밑 새 자손(111)이 기록되고 그 창으로 따라간다. 그 뒤
    런처가 끝나도 기록한 자손의 창은 계속 따라갈 수 있다. 다른 게임(202)은 후보가 아니다."""
    os_ = fake_family(monkeypatch, TABLE)
    platform = WindowsPlatform()
    platform._processes[101] = launched(True)  # pyright: ignore[reportPrivateUsage]
    os_windows = OsWindows({0xAAA: (111, 11), 0x7D2: (202, 20)})
    os_windows.install(monkeypatch, platform)
    seen: list[list[int]] = []

    def main_window(*, title: str | None, pids: list[int]) -> int | None:
        seen.append(list(pids))
        return 0xAAA if 111 in pids else None

    monkeypatch.setattr(wins, "main_window", main_window)
    old = WindowRef(1001, pid=101, process_created="10", binding="old")
    found, _ = runtime(platform, old, ProcessRef(101)).follow(old, None, "s", "n")
    assert found is not None and (found.handle, found.pid) == (0xAAA, 111)
    assert all(202 not in p and 999 not in p for p in seen)
    # 런처가 끝났다: 기록한 자손은 그대로 소유 범위
    platform._processes[101] = launched(False)  # pyright: ignore[reportPrivateUsage]
    del os_.table[101]
    assert platform.process_running(ProcessRef(101), "")
    assert platform.follow_window(ProcessRef(101), "") is not None


@pytest.mark.parametrize(
    "case", ["parent_gone", "parent_reused_again", "parent_unknown", "child_reused_after_snapshot"]
)
def test_unproven_descendant_never_becomes_follow_target(
    monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """재검수2 재현: 원래 게임 (101, 10). 외부 (303, 35)는 이 게임의 자손이 아니다. 앞의 셋은 원래
    101이 끝난 뒤 외부 (101, 30)가 303을 만든 경우(외부 부모도 끝남 / 101을 세 번째 프로세스가 씀
    / 외부 부모의 생성 시각 조회 실패), 마지막은 원래 게임이 살아 있고 스냅샷의 진짜 자식
    (303, 11)이 조회 전에 끝나 외부 (303, 35)가 PID를 다시 쓴 경우 — 어느 쪽도 따라가지 않는다."""
    parents = {303: 101}
    made: dict[int, int | None] = {303: 35}
    root_alive = case == "child_reused_after_snapshot"
    if case == "parent_reused_again":
        parents[101], made[101] = 1, 50
    elif case == "parent_unknown":
        parents[101], made[101] = 1, None
    elif root_alive:
        parents[101], made[101], made[303] = 1, 10, 11
    snapshots = [0]

    def snapshot() -> dict[int, int]:
        snapshots[0] += 1
        saved = dict(parents)
        if root_alive and snapshots[0] == 2:
            made[303] = 35  # 두 번째 스냅샷 직후 자식 PID 재사용
        return saved

    def family(root: Any, alive: bool, **_: Any) -> list[ProcessId]:
        return ORIGINAL_FAMILY(root, alive, parents=snapshot, created=made.get)

    monkeypatch.setattr(processes, "family", family)
    monkeypatch.setattr("kookabug_platform.platform.is_alive", lambda _ident: root_alive)  # pyright: ignore[reportUnknownLambdaType]
    monkeypatch.setattr(win_api.DEFAULT_API, "window_pid", lambda hwnd: 303)
    monkeypatch.setattr(win_api.DEFAULT_API, "process_created", made.get)
    monkeypatch.setattr(wins, "main_window", lambda *, title, pids: 0x303 if 303 in pids else None)
    platform = WindowsPlatform()  # 붙여 실행처럼 원래 게임 핸들이 없다
    foreign = WindowRef(0x303, pid=303, process_created="35", binding="foreign")
    monkeypatch.setattr(platform, "_ref", lambda hwnd: foreign)
    monkeypatch.setattr(platform, "window_alive", lambda window: True)
    monkeypatch.setattr(platform, "activate", lambda window: True)
    old = WindowRef(0x101, pid=101, process_created="10", binding="original")
    rt = runtime(platform, old, ProcessRef(101))
    found, _ = rt.follow(old, None, "s", "n")
    assert found is None and rt.follows == {}


def test_binding_race_discarded_then_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    """검수1 재현 2: 열거 때는 게임(101)의 HWND인데 바인딩 때 외부(303)가 그 HWND를 쓰면 버리고,
    남은 기한 안에서 다시 찾아 게임의 창을 받는다. 외부 창은 owners·follows에 들지 않는다."""
    fake_family(monkeypatch, {101: (1, 10)})
    platform = WindowsPlatform()
    platform._processes[101] = launched(True)  # pyright: ignore[reportPrivateUsage]
    os_windows = OsWindows({0xBBB: (101, 10)})
    os_windows.swap[0xBBB] = (303, 30)
    os_windows.install(monkeypatch, platform)
    monkeypatch.setattr(wins, "main_window", lambda *, title, pids: 0xBBB)
    old = WindowRef(1001, pid=101, process_created="10", binding="old")
    rt = runtime(platform, old, ProcessRef(101))
    found, _ = rt.follow(old, None, "s", "n")
    assert found is not None and (found.pid, found.process_created) == (101, "10")
    assert os_windows.binds == 2
    assert all(w.pid != 303 for w in rt.follows.values())
    assert all(key[1] != 303 for key in rt.owners)


def test_unidentified_candidate_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """HWND 주인을 열거 때 알 수 없거나 가족 밖이면 버린다 (계속 그러면 기한 끝에 None)."""
    fake_family(monkeypatch, {101: (1, 10)})
    platform = WindowsPlatform()
    platform._processes[101] = launched(True)  # pyright: ignore[reportPrivateUsage]
    os_windows = OsWindows({0xCCC: (404, 40)})  # 남의 창
    os_windows.install(monkeypatch, platform)
    monkeypatch.setattr(wins, "main_window", lambda *, title, pids: 0xCCC)
    assert platform.follow_window(ProcessRef(101), "10") is None
    monkeypatch.setattr(wins, "main_window", lambda *, title, pids: 0xDDD)  # 주인 모름
    assert platform.follow_window(ProcessRef(101), "10") is None
    assert os_windows.binds == 0  # 바인딩도 만들지 않았다
    # 정체(생성 시각)를 모르는 게임은 따라가지 않는다
    other = WindowsPlatform()
    unknown: Any = SimpleNamespace(alive=lambda: True)
    other._processes[101] = unknown  # pyright: ignore[reportPrivateUsage]
    assert not other.process_running(ProcessRef(101), "")


def test_attached_game_identity_from_first_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """붙여 실행(띄우지 않은 게임): 처음 붙은 창의 생성 시각이 정체 — PID가 다른 프로세스로
    재사용됐으면 끝난 것으로 본다."""
    monkeypatch.setattr("kookabug_platform.platform.is_alive", lambda ident: ident.created == 10)  # pyright: ignore[reportUnknownLambdaType, reportUnknownMemberType]
    fake_family(monkeypatch, {101: (1, 10)})
    platform = WindowsPlatform()
    assert platform.process_running(ProcessRef(101), "10")
    assert platform.process_running(ProcessRef(101), "")  # 정체는 기록에 남는다
    other = WindowsPlatform()
    assert not other.process_running(ProcessRef(101), "99")
    assert not WindowsPlatform().process_running(ProcessRef(101), "")  # 정체 모름


# ---------------------------------------------------------------- 실제 프로세스


@pytest.fixture
def child() -> Iterator[subprocess.Popen[bytes]]:
    proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        yield proc
    finally:
        proc.kill()
        proc.wait(10)


def test_real_child_is_recorded(child: subprocess.Popen[bytes]) -> None:
    record = processes.GameFamily(current())

    def has_child() -> bool:
        return child.pid in pids(processes.family(record, True))

    wait_until(has_child, timeout=10)
    child.kill()
    child.wait(10)
    assert child.pid not in pids(processes.family(record, True))
    assert child.pid in record.refused  # 끝난 자손의 PID는 다시 받지 않는다
