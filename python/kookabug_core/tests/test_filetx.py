"""일반 파일 거래 `filetx` (M8 계획 3.8 끝) — 엄격: 사용자 파일 손상.

모든 실패 지점마다 (예외, 자식 프로세스 kill)에서 복구 뒤 파일 집합이 "원래 그대로" 또는 "거래 전부"
둘 중 하나이고, 복구는 멱등이다. 사용자가 그사이 고친 파일은 손대지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from helpers.filetx_case import run_tx

from kookabug_core import filetx
from kookabug_sdk import _faults

CHILD = Path(__file__).parent / "procs" / "filetx_child.py"

FAULTS = [
    ("journal_write", 1, "original"),
    ("publish_fsync", 1, "original"),
    ("created", 1, "original"),
    ("publish_fsync", 2, "original"),
    ("created", 2, "original"),
    ("publish_fsync", 3, "original"),
    ("taken", 1, "original"),
    ("replaced", 1, "original"),
    ("before_commit", 1, "original"),
    ("commit_fsync", 1, "original"),
    ("after_commit", 1, "done"),
    ("deleted", 1, "done"),
    ("before_journal_remove", 1, "done"),
]


def make(root: Path) -> Path:
    root.mkdir(parents=True)
    (root / "a.txt").write_bytes(b"a before\n")
    (root / "d.txt").write_bytes(b"d to delete\n")
    (root / "keep.txt").write_bytes(b"keep\n")
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.relative_to(root).as_posix().startswith(".kookabug/")
    }


def rule(stage: str, nth: int, action: str) -> str:
    return json.dumps(
        [
            {
                "point": "filetx.stage",
                "role": "supervisor",
                "when": {"event": stage, "nth": nth},
                "action": action,
            }
        ]
    )


def recover(root: Path) -> list[str]:
    with filetx.file_lock(root):
        return filetx.recover(root)


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, bytes]]:
    base = tmp_path_factory.mktemp("expected")
    original = make(base / "original")
    done = make(base / "done")
    assert run_tx(done)["cleanup_pending"] is False
    return {"original": tree(original), "done": tree(done)}


def test_outcomes_differ(outcomes: dict[str, dict[str, bytes]]) -> None:
    assert outcomes["done"]["a.txt"] == b"a after\n" and "d.txt" not in outcomes["done"]
    assert outcomes["original"] != outcomes["done"]


@pytest.mark.parametrize("how", ["raise", "kill"])
@pytest.mark.parametrize(
    ("stage", "nth", "expected"), FAULTS, ids=[f"{s}{n}" for s, n, _ in FAULTS]
)
def test_fault_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[str, dict[str, bytes]],
    stage: str,
    nth: int,
    expected: str,
    how: str,
) -> None:
    root = make(tmp_path / "ws")
    if how == "kill":
        env = {**os.environ, "KOOKABUG_FAULTS": rule(stage, nth, "exit:9")}
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(CHILD), str(root)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 9, done.stdout + done.stderr
    else:
        monkeypatch.setenv("KOOKABUG_FAULTS", rule(stage, nth, "raise"))
        _faults.set_role("supervisor")
        try:
            if expected == "original":
                with pytest.raises((RuntimeError, filetx.TxError)):
                    run_tx(root)
            else:
                assert run_tx(root)["cleanup_pending"] is True
        finally:
            _faults.reset()
            monkeypatch.delenv("KOOKABUG_FAULTS")
    recover(root)
    assert tree(root) == outcomes[expected]
    assert filetx.journals(root) == []
    assert not (root / "new").exists() or expected == "done"  # 거래가 만든 폴더도 되돌린다
    assert recover(root) == []
    assert tree(root) == outcomes[expected]


def test_stage_names_match_fault_table() -> None:
    # 게시·커밋 단계는 위 표, 복구 단계는 아래 복구 중단 검사가 덮는다
    assert {s for s, _, _ in FAULTS} | set(filetx.RECOVERY_STAGES) == set(filetx.STAGES)


def kill_before_commit(root: Path) -> None:
    env = {**os.environ, "KOOKABUG_FAULTS": rule("before_commit", 1, "exit:9")}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root)],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9, done.stderr


def kill_recovery_at(root: Path, stage: str) -> None:
    """자식 프로세스의 복구가 `stage`(보존 영역으로 옮긴 직후)에서 죽는다."""
    env = {**os.environ, "KOOKABUG_FAULTS": rule(stage, 1, "exit:9")}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), "recover"],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9, done.stderr


def test_recovery_interrupted_after_rb_take_restores_original(
    tmp_path: Path, outcomes: dict[str, dict[str, bytes]]
) -> None:
    """롤백이 바꾼 파일을 보존 영역으로 옮긴 직후 죽어도 다음 복구가 이어서 원래 바이트를 놓는다."""
    root = make(tmp_path / "ws")
    kill_before_commit(root)
    kill_recovery_at(root, "rollback_rb")
    assert not (root / "a.txt").exists()  # 옮긴 뒤 멈춘 상태
    assert filetx.journals(root)  # 저널 항목은 아직 끝나지 않았다
    recover(root)
    assert tree(root) == outcomes["original"]
    assert filetx.journals(root) == [] and recover(root) == []


def test_recovery_interrupted_after_rm_take_cleans_aside(
    tmp_path: Path, outcomes: dict[str, dict[str, bytes]]
) -> None:
    """롤백이 만든 파일을 보존 영역으로 옮긴 직후 죽어도 다음 복구가 끝내고, 워크스페이스에 옆
    파일이 남지 않는다."""
    root = make(tmp_path / "ws")
    kill_before_commit(root)
    kill_recovery_at(root, "rollback_rm")
    recover(root)
    assert tree(root) == outcomes["original"]
    assert filetx.journals(root) == [] and recover(root) == []
    leftovers = [p for p in root.rglob(".*") if not p.relative_to(root).as_posix().startswith(".k")]
    assert leftovers == []


def test_recovery_preserves_user_edit(tmp_path: Path) -> None:
    root = make(tmp_path / "ws")
    kill_before_commit(root)
    (root / "a.txt").write_bytes(b"user edit\n")  # 사람이 그사이 고쳤다
    warnings = recover(root)
    assert any("a.txt" in w for w in warnings)
    assert (root / "a.txt").read_bytes() == b"user edit\n"  # 사용자 바이트 보존
    assert (
        not (root / "c.txt").exists() and not (root / "new").exists()
    )  # 이 거래가 만든 것은 되돌림
    assert (root / "d.txt").exists()
    left = filetx.pending(root)
    assert len(left) == 1 and left[0]["paths"] == ["a.txt"]
    backup = root / left[0]["backups"]["a.txt"]
    assert backup.read_bytes() == b"a before\n"  # 원래 바이트를 찾을 수 있다
    # 저널이 남은 동안 새 거래는 거부
    with pytest.raises(filetx.TxError) as info, filetx.locked(root):
        pass
    assert info.value.code == "recovery_pending"
    # 사람이 원래 바이트로 되돌리면 풀린다
    (root / "a.txt").write_bytes(b"a before\n")
    assert recover(root) == []
    assert filetx.journals(root) == []
    with filetx.locked(root) as warnings2:
        assert warnings2 == []


def test_deleted_replaced_file_keeps_backup(tmp_path: Path) -> None:
    root = make(tmp_path / "ws")
    kill_before_commit(root)
    (root / "a.txt").unlink()
    warnings = recover(root)
    kept = root / ".kookabug/knowledge-tx-kept"
    assert any("a.txt" in w for w in warnings)
    assert [p.read_bytes() for p in kept.rglob("a.txt")] == [b"a before\n"]
    assert filetx.journals(root) == []


def stage_hook(
    monkeypatch: pytest.MonkeyPatch, actions: dict[str, Callable[[], object]]
) -> list[str]:
    """`filetx._stage`를 바꿔 단계마다 동작을 끼운다 (사용자 수정 경합 재현). 지난 단계 이름들."""
    seen: list[str] = []

    def hook(name: str) -> None:
        seen.append(name)
        action = actions.pop(f"{name}#{seen.count(name)}", None)
        if action is not None:
            action()

    monkeypatch.setattr(filetx, "_stage", hook)
    return seen


def boom() -> None:
    raise RuntimeError("주입")


def one_replace(root: Path) -> dict[str, object]:
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        return tx.commit()


@pytest.mark.parametrize("fail_after", [False, True])
def test_user_edit_during_publish_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_after: bool
) -> None:
    """확인 뒤·교체 전(새 바이트 fsync 자리)에 사람이 고친 바이트는 커밋·롤백 어느 쪽에서도
    남는다."""
    root = make(tmp_path / "ws")

    def edit() -> None:
        (root / "a.txt").write_bytes(b"user edit\n")

    actions: dict[str, Callable[[], object]] = {"publish_fsync#1": edit}
    if fail_after:
        actions["replaced#1"] = boom
    stage_hook(monkeypatch, actions)
    with pytest.raises(filetx.TxError) as info:
        one_replace(root)
    assert info.value.code == "revision_conflict"
    assert (root / "a.txt").read_bytes() == b"user edit\n"
    monkeypatch.undo()
    assert recover(root) == [] and filetx.journals(root) == []
    assert tree(root) == {"a.txt": b"user edit\n", "d.txt": b"d to delete\n", "keep.txt": b"keep\n"}


def test_user_edit_after_publish_survives_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 바이트를 놓은 뒤 사람이 고치고 거래가 실패하면 롤백은 사람 바이트를 덮지 않는다."""
    root = make(tmp_path / "ws")

    def edit() -> None:
        (root / "a.txt").write_bytes(b"user edit\n")

    stage_hook(monkeypatch, {"replaced#1": edit, "before_commit#1": boom})
    with pytest.raises(RuntimeError):
        one_replace(root)
    assert (root / "a.txt").read_bytes() == b"user edit\n"
    left = filetx.pending(root)
    assert len(left) == 1 and (root / left[0]["backups"]["a.txt"]).read_bytes() == b"a before\n"
    assert not any(p.name.startswith(".a.txt.") for p in root.iterdir())  # 옆 이름 정리


def test_user_edit_before_delete_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """커밋 뒤 지울 파일을 사람이 고쳤으면 지우지 않는다."""
    root = make(tmp_path / "ws")

    def edit() -> None:
        (root / "d.txt").write_bytes(b"user keeps\n")

    stage_hook(monkeypatch, {"after_commit#1": edit})
    result = run_tx(root)
    assert any("d.txt" in w for w in result["warnings"])  # type: ignore[union-attr]
    assert (root / "d.txt").read_bytes() == b"user keeps\n"
    assert (root / "a.txt").read_bytes() == b"a after\n"
    assert not any(p.name.startswith((".a.txt.", ".d.txt.")) for p in root.iterdir())


class Crash(BaseException):
    """프로세스 종료 흉내 (같은 프로세스 롤백 없이 디스크 상태만 남긴다)."""


def publish_until_crash(root: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """바꾸기 하나를 `_publish`까지만 하고 `stage`에서 사람이 `a.txt`를 지운 뒤 죽는다."""

    def delete_and_die() -> None:
        (root / "a.txt").unlink()
        raise Crash

    with filetx.file_lock(root):
        tx = filetx.Tx(root)
        tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        tx._check()  # pyright: ignore[reportPrivateUsage]
        tx._prepare()  # pyright: ignore[reportPrivateUsage]
        stage_hook(monkeypatch, {f"{stage}#1": delete_and_die})
        with pytest.raises(Crash):
            tx._publish()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.undo()


def test_deleted_after_place_before_old_cleanup_stays_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """새 바이트를 놓은 뒤 사람이 지우고 죽으면 복구는 지운 것을 되살리지 않는다(놓음 표시로 가름).
    표시가 없어 가를 수 없을 때도 되살리지 않고 원래 바이트를 kept에 남기고 알린다."""
    root = make(tmp_path / "ws")
    publish_until_crash(root, monkeypatch, "replaced")
    warnings = recover(root)
    assert not (root / "a.txt").exists()
    assert any("a.txt" in w for w in warnings)
    kept = root / ".kookabug/knowledge-tx-kept"
    assert [p.read_bytes() for p in kept.rglob("a.txt")] == [b"a before\n"]
    assert filetx.journals(root) == []

    # 놓음 표시를 못 남긴 채(놓은 직후) 지워진 경우: 가를 수 없음 → 되살리지 않는다
    root2 = make(tmp_path / "ws2")
    publish_until_crash(root2, monkeypatch, "replaced")
    [folder] = (root2 / ".kookabug/knowledge-tx").iterdir()
    journal = json.loads((folder / "journal.json").read_text("utf-8"))
    journal["replaces"][0]["placed"] = False
    (folder / "journal.json").write_text(json.dumps(journal), "utf-8")
    warnings = recover(root2)
    assert not (root2 / "a.txt").exists() and any("a.txt" in w for w in warnings)
    assert [p.read_bytes() for p in (root2 / ".kookabug/knowledge-tx-kept").rglob("a.txt")] == [
        b"a before\n"
    ]

    # 옮긴 뒤 놓기 전에 멈췄으면(새 바이트 임시 파일이 남음) 원래 자리로 되돌린다
    root3 = make(tmp_path / "ws3")

    def die() -> None:
        raise Crash

    with filetx.file_lock(root3):
        tx = filetx.Tx(root3)
        tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        tx._check()  # pyright: ignore[reportPrivateUsage]
        tx._prepare()  # pyright: ignore[reportPrivateUsage]
        stage_hook(monkeypatch, {"taken#1": die})
        with pytest.raises(Crash):
            tx._publish()  # pyright: ignore[reportPrivateUsage]
    monkeypatch.undo()
    assert not (root3 / "a.txt").exists()
    recover(root3)
    assert (root3 / "a.txt").read_bytes() == b"a before\n" and filetx.journals(root3) == []


def test_share_delete_handle_bytes_survive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """사람이 FILE_SHARE_DELETE 핸들로 연 채 거래가 원래 파일을 옮기고 확인한 뒤 그 핸들로 써도,
    쓴 바이트는 지워지지 않고 남는다(확인 뒤 지우기 없음)."""
    import _winapi

    root = make(tmp_path / "ws")
    handle = _winapi.CreateFile(
        str(root / "a.txt"),
        0x40000000,  # GENERIC_WRITE
        0x1 | 0x2 | 0x4,  # FILE_SHARE_READ | WRITE | DELETE
        0,
        3,  # OPEN_EXISTING
        0x80,  # FILE_ATTRIBUTE_NORMAL
        0,
    )
    try:

        def write_through_handle() -> None:
            _winapi.WriteFile(handle, b"USER-EDIT")

        stage_hook(monkeypatch, {"taken#1": write_through_handle})
        result = one_replace(root)
    finally:
        _winapi.CloseHandle(handle)
    monkeypatch.undo()
    assert (root / "a.txt").read_bytes() == b"a after\n"
    found = [p for p in root.rglob("*") if p.is_file() and b"USER-EDIT" in p.read_bytes()]
    assert found, "핸들로 쓴 사용자 바이트가 사라졌다"
    assert any("a.txt" in w for w in result["warnings"])  # type: ignore[union-attr]
    assert recover(root) == [] and filetx.journals(root) == []


def test_trash_pruned_by_age_and_count(tmp_path: Path) -> None:
    root = make(tmp_path / "ws")
    base = root.joinpath(*filetx.TRASH_DIR)
    old = time.time() - (filetx.TRASH_KEEP_DAYS + 1) * 86400
    names = [f"20260101{n:06d}-0000" for n in range(filetx.TRASH_KEEP_MIN + 3)]
    for name in names:
        (base / name).mkdir(parents=True)
        (base / name / "old-0").write_bytes(b"x")
        os.utime(base / name, (old, old))
    (base / "20991231000000-new").mkdir()
    recover(root)
    left = sorted(p.name for p in base.iterdir())
    # 새 것 + 최근 KEEP_MIN-1개가 남고, 오래되고 개수 밖인 것만 지운다
    assert "20991231000000-new" in left and len(left) == filetx.TRASH_KEEP_MIN


def test_conflicts_and_links_write_nothing(tmp_path: Path) -> None:
    root = make(tmp_path / "ws")
    before = tree(root)
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.replace("a.txt", b"x", expect_sha="0" * 64)
        with pytest.raises(filetx.TxError) as info:
            tx.commit()
    assert info.value.code == "revision_conflict" and tree(root) == before
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.create("a.txt", b"x")
        with pytest.raises(filetx.TxError) as info:
            tx.commit()
    assert info.value.code == "exists"
    import _winapi

    outside = tmp_path / "outside"
    outside.mkdir()
    _winapi.CreateJunction(str(outside), str(root / "link"))
    with filetx.locked(root):
        tx = filetx.Tx(root)
        for bad in ("link/x.txt", "../x.txt", "C:/x.txt"):
            with pytest.raises(filetx.TxError) as info:
                tx.create(bad, b"x")
            assert info.value.code == "path_outside_workspace"
    assert list(outside.iterdir()) == []
