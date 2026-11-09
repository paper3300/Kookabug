"""`filetx` 복구 자체가 중단될 때의 사용자 파일 보존 (M8 B1 4라운드 — 스스로 반대 검수).

복구(`recover`)가 하는 변경 연산(이름 바꾸기·교체·폴더 만들기·지우기 — 저널 쓰기는 교체로 센다)마다
"그 직후 프로세스가 죽음 → 사람이 대상·kept·보존 영역을 고치거나 지움 → 다시 복구"를 돌려,
사람이 쓴 바이트가 사라지거나 사람의 삭제가 취소되는 칸이 없는지 본다. 사람 개입이 없으면 결과는
"원래 그대로" 또는 "거래 전부"(지워진 대상은 지운 그대로)다.

`KB_FILETX_TABLE=<경로>`를 주면 칸별 결과 표(마크다운)를 그 파일에 쓴다.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from kookabug_core import filetx

CHILD = Path(__file__).parent / "procs" / "filetx_child.py"
ORIGINAL = {"a.txt": b"a before\n", "d.txt": b"d to delete\n", "keep.txt": b"keep\n"}
DONE = {
    "a.txt": b"a after\n",
    "c.txt": b"c created\n",
    "keep.txt": b"keep\n",
    "new/sub/b.txt": b"b created\n",
}


class Crash(BaseException):
    """프로세스 종료 흉내 (복구가 더 진행하지 못하게)."""


def make(root: Path) -> Path:
    root.mkdir(parents=True)
    for rel, data in ORIGINAL.items():
        (root / rel).write_bytes(data)
    return root


def tree(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.relative_to(root).as_posix().startswith(".kookabug/")
    }


def everything(root: Path) -> bytes:
    return b"\0".join(p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file())


def child(root: Path, stage: str, *extra: str) -> None:
    rules = [
        {
            "point": "filetx.stage",
            "role": "supervisor",
            "when": {"event": stage, "nth": 1},
            "action": "exit:9",
        }
    ]
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), *extra],
        env={**os.environ, "KOOKABUG_FAULTS": json.dumps(rules)},
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9, done.stderr


def recover(root: Path) -> list[str]:
    with filetx.file_lock(root):
        return filetx.recover(root)


@contextlib.contextmanager
def crash_after(k: int | None) -> Iterator[list[str]]:
    """변경 연산을 세고 `k`번째 연산을 마친 직후 `Crash`. 연산 이름 목록을 준다."""
    ops: list[str] = []
    real_rename, real_replace = os.rename, os.replace
    real_mkdir, real_unlink, real_rmtree = Path.mkdir, Path.unlink, shutil.rmtree

    def done(label: str) -> None:
        ops.append(label)
        if k is not None and len(ops) == k:
            raise Crash

    def rename(src: Any, dst: Any) -> None:
        real_rename(src, dst)
        done(f"rename {Path(src).name} → {Path(dst).name}")

    def replace(src: Any, dst: Any) -> None:
        real_replace(src, dst)
        done(f"replace → {Path(dst).name}")

    def mkdir(self: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        existed = self.is_dir()
        real_mkdir(self, mode, parents, exist_ok)
        if not existed:
            done(f"mkdir {self.name}")

    def unlink(self: Path, missing_ok: bool = False) -> None:
        real_unlink(self, missing_ok)
        done(f"unlink {self.name}")

    def rmtree(path: Any, *args: Any, **kwargs: Any) -> None:
        real_rmtree(path, *args, **kwargs)
        done(f"rmtree {Path(path).name}")

    def rmdir(self: Path) -> None:
        real_rmdir(self)
        done(f"rmdir {self.name}")

    real_rmdir = Path.rmdir
    with (
        mock.patch.object(os, "rename", rename),
        mock.patch.object(os, "replace", replace),
        mock.patch.object(Path, "mkdir", mkdir),
        mock.patch.object(Path, "unlink", unlink),
        mock.patch.object(Path, "rmdir", rmdir),
        mock.patch.object(shutil, "rmtree", rmtree),
    ):
        yield ops


def recover_crashing(root: Path, k: int | None) -> list[str]:
    with filetx.file_lock(root), crash_after(k) as ops, contextlib.suppress(Crash):
        filetx.recover(root)
    return ops


# ---------------------------------------------------------------- 시작 상태


@pytest.fixture(scope="module")
def templates(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """복구 전 상태들: 놓은 뒤(prepare), 놓은 뒤 사람이 대상 삭제, 옮긴 뒤 놓기 전, 커밋 뒤."""
    base = tmp_path_factory.mktemp("filetx-templates")
    out: dict[str, Path] = {}
    out["placed"] = make(base / "placed")
    child(out["placed"], "before_commit")
    out["placed_deleted"] = base / "placed_deleted"
    shutil.copytree(out["placed"], out["placed_deleted"])
    (out["placed_deleted"] / "a.txt").unlink()
    out["unplaced"] = make(base / "unplaced")
    child(out["unplaced"], "taken")
    out["committed"] = make(base / "committed")
    child(out["committed"], "after_commit")
    return out


def expected_clean(scenario: str) -> dict[str, bytes]:
    if scenario == "committed":
        return DONE
    if scenario == "placed_deleted":
        return {k: v for k, v in ORIGINAL.items() if k != "a.txt"}
    return ORIGINAL


ACTIONS = (
    "none",
    "delete_target",
    "edit_target",
    "delete_others",
    "edit_others",
    "edit_kept",
    "edit_trash",
)
SCENARIOS = ("placed", "placed_deleted", "unplaced", "committed")
ROWS: list[dict[str, Any]] = []


def act(root: Path, action: str) -> tuple[list[bytes], list[str]]:
    """사람 개입. (사람이 쓴 바이트들, 사람이 지운 파일들)."""
    target = root / "a.txt"
    written: list[bytes] = []
    if action == "delete_target" and target.exists():
        target.unlink()
        return written, ["a.txt"]
    if action == "edit_target" and target.exists():
        target.write_bytes(b"USER-TARGET\n")
        written.append(b"USER-TARGET\n")
    if action == "delete_others":  # 지울 파일·만든 파일을 사람이 지움
        gone = [rel for rel in ("d.txt", "new/sub/b.txt") if (root / rel).exists()]
        for rel in gone:
            (root / rel).unlink()
        return written, gone
    if (
        action == "edit_others"
    ):  # 지울 파일 자리에 사람 바이트(없으면 새로), 만든 파일이 있으면 고침
        (root / "d.txt").write_bytes(b"USER-DELETE-TARGET\n")
        written.append(b"USER-DELETE-TARGET\n")
        if (root / "new/sub/b.txt").exists():
            (root / "new/sub/b.txt").write_bytes(b"USER-CREATE-TARGET\n")
            written.append(b"USER-CREATE-TARGET\n")
    folder = {"edit_kept": filetx.KEPT_DIR, "edit_trash": filetx.TRASH_DIR}.get(action)
    if folder is not None:
        base = root.joinpath(*folder)
        for n, path in enumerate(sorted(p for p in base.rglob("*") if p.is_file())):
            data = f"USER-{action}-{n}\n".encode()
            path.write_bytes(data)
            written.append(data)
    return written, []


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_crash_after_each_recovery_mutation(
    tmp_path: Path, templates: dict[str, Path], scenario: str
) -> None:
    probe = tmp_path / "probe"
    shutil.copytree(templates[scenario], probe)
    labels = recover_crashing(probe, None)  # 끝까지: 변경 연산 목록
    assert labels, "복구가 아무것도 하지 않았다"
    assert tree(probe) == expected_clean(scenario)
    for k, label in enumerate(labels, start=1):
        for action in ACTIONS:
            root = tmp_path / f"k{k}-{action}"
            shutil.copytree(templates[scenario], root)
            recover_crashing(root, k)
            had_target = (root / "a.txt").exists()
            written, deleted = act(root, action)
            recover(root)
            recover(root)
            blob = everything(root)
            lost = [w for w in written if w not in blob]
            assert lost == [], (scenario, k, label, action)
            for rel in deleted:
                assert not (root / rel).exists(), (scenario, k, label, action, rel, "삭제 취소")
            if action == "none" or (action == "edit_kept" and not written):
                assert tree(root) == expected_clean(scenario), (scenario, k, label, action)
                assert filetx.journals(root) == []
            final = (root / "a.txt").read_bytes() if (root / "a.txt").exists() else None
            ROWS.append(
                {
                    "scenario": scenario,
                    "k": k,
                    "op": label,
                    "action": action,
                    "target_at_crash": had_target,
                    "a.txt": "없음" if final is None else final.decode().strip(),
                    "user_bytes": f"{len(written)}/{len(written)} 보존" if written else "-",
                    "pending": bool(filetx.journals(root)),
                }
            )


def test_zz_write_table() -> None:
    """칸별 결과 표 (KB_FILETX_TABLE이 있을 때만)."""
    out = os.environ.get("KB_FILETX_TABLE")
    if not out or not ROWS:
        return
    head = ("시작 상태", "k", "중단 직후 연산", "사람 개입", "중단 때 a.txt", "최종 a.txt")
    head += ("사람 바이트", "저널 남음")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in ROWS:
        lines.append(
            f"| {r['scenario']} | {r['k']} | {r['op']} | {r['action']} | "
            f"{'있음' if r['target_at_crash'] else '없음'} | {r['a.txt']} | {r['user_bytes']} | "
            f"{'예' if r['pending'] else '-'} |"
        )
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 검수 재현 (B1 3라운드 High 3·4)


def test_kept_edit_survives_recovery_retry(tmp_path: Path, templates: dict[str, Path]) -> None:
    """kept 사본을 만든 직후 죽고 사람이 그 kept를 고친 뒤 다시 복구해도 고친 바이트는 남는다."""
    root = tmp_path / "ws"
    shutil.copytree(templates["placed_deleted"], root)
    real = filetx._keep_backup  # pyright: ignore[reportPrivateUsage]

    def keep_then_die(*args: Any, **kwargs: Any) -> str:
        real(*args, **kwargs)
        raise Crash

    with (
        mock.patch.object(filetx, "_keep_backup", keep_then_die),
        filetx.file_lock(root),
        pytest.raises(Crash),
    ):
        filetx.recover(root)
    [kept] = [p for p in root.joinpath(*filetx.KEPT_DIR).rglob("*") if p.is_file()]
    assert kept.read_bytes() == b"a before\n"
    kept.write_bytes(b"USER-KEPT-EDIT\n")
    recover(root)

    def kept_files() -> dict[str, bytes]:
        base = root.joinpath(*filetx.KEPT_DIR)
        return {p.name: p.read_bytes() for p in base.rglob("*") if p.is_file()}

    files = kept_files()
    assert files["a.txt"] == b"USER-KEPT-EDIT\n"  # 사람 바이트 그대로
    assert files["a.txt-2"] == b"a before\n"  # 원래 바이트는 새 이름에
    assert not (root / "a.txt").exists() and filetx.journals(root) == []
    recover(root)
    assert kept_files() == files


def test_restored_then_deleted_not_resurrected(tmp_path: Path, templates: dict[str, Path]) -> None:
    """롤백이 원래 바이트를 놓은 직후(복원함 표시 전) 죽고 사람이 지우면 다시 살리지 않는다."""
    root = tmp_path / "ws"
    shutil.copytree(templates["placed"], root)
    child(root, "rollback_restored", "recover")
    assert (root / "a.txt").read_bytes() == b"a before\n"
    (root / "a.txt").unlink()
    warnings = recover(root)
    assert not (root / "a.txt").exists()
    assert any("a.txt" in w for w in warnings)
    kept = [p.read_bytes() for p in root.joinpath(*filetx.KEPT_DIR).rglob("a.txt*")]
    assert kept == [b"a before\n"]
    assert filetx.journals(root) == []
    # 복원함 표시를 남긴 뒤 죽은 경우도 같다 (표시가 있으면 그 뒤 삭제는 그대로)
    root2 = tmp_path / "ws2"
    shutil.copytree(templates["placed"], root2)
    real = filetx._write_journal  # pyright: ignore[reportPrivateUsage]

    def write_then_die(folder: Path, journal: Any) -> None:
        real(folder, journal)
        if any(i.get("restored") for i in journal.get("replaces", [])):
            raise Crash

    with (
        mock.patch.object(filetx, "_write_journal", write_then_die),
        filetx.file_lock(root2),
        pytest.raises(Crash),
    ):
        filetx.recover(root2)
    (root2 / "a.txt").unlink()
    recover(root2)
    assert not (root2 / "a.txt").exists() and filetx.journals(root2) == []
    # 사람 개입이 없으면 rb로 옮긴 직후 죽어도 원래대로 (정상 원복 유지)
    root3 = tmp_path / "ws3"
    shutil.copytree(templates["placed"], root3)
    child(root3, "rollback_rb", "recover")
    recover(root3)
    assert tree(root3) == ORIGINAL


# ---------------------------------------------------------------- 쓰기 경계 (B1 4라운드 High 1)


def single_tx(root: Path, kind: str, *, commit: bool) -> None:
    """바꾸기·만들기·지우기 하나짜리 거래를 게시까지(`commit`이면 커밋 표시까지) — 마무리 없이."""
    with filetx.file_lock(root):
        tx = filetx.Tx(root)
        if kind == "replace":
            tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        elif kind == "create":
            tx.create("c.txt", b"c created\n")
        else:
            tx.delete("d.txt", expect_sha=filetx.sha256_of(b"d to delete\n"))
        tx._check()  # pyright: ignore[reportPrivateUsage]
        tx._prepare()  # pyright: ignore[reportPrivateUsage]
        tx._publish()  # pyright: ignore[reportPrivateUsage]
        if commit:
            tx._commit_mark()  # pyright: ignore[reportPrivateUsage]


def files_of(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


@pytest.mark.parametrize("case", ["rollback_rb", "committed", "committed_del", "rollback_rm"])
def test_recovery_trash_junction_does_not_move_external_files(tmp_path: Path, case: str) -> None:
    """보존 영역의 거래 폴더가 바깥을 가리키는 정션이면, 복구는 그 원본(old·rb·rm·del)을 읽거나
    옮기지 않고 거래를 남긴다(`recovery_pending`). 바깥 파일은 이름·바이트 그대로."""
    import _winapi

    root = make(tmp_path / "ws")
    if case == "rollback_rb":  # 롤백이 rb로 옮긴 직후 죽음 → rb 재개 경로
        single_tx(root, "replace", commit=False)
        child(root, "rollback_rb", "recover")
    elif case == "committed":  # 커밋 뒤 마무리 전 → old 확인 경로
        single_tx(root, "replace", commit=True)
    elif case == "committed_del":  # 마무리가 del로 옮긴 직후 죽음 → del 재개 경로
        single_tx(root, "delete", commit=True)
        child(root, "deleted", "recover")
    else:  # 롤백이 rm으로 옮긴 직후 죽음 → rm 재개 경로
        single_tx(root, "create", commit=False)
        child(root, "rollback_rm", "recover")
    [trash] = list(root.joinpath(*filetx.TRASH_DIR).iterdir())
    outside = tmp_path / "outside"
    shutil.move(str(trash), str(outside))
    _winapi.CreateJunction(str(outside), str(trash))
    for path in outside.iterdir():  # 바깥 파일을 사람 바이트로 (옮기면 안 되는 대상)
        path.write_bytes(b"USER-EXTERNAL-" + path.name.encode() + b"\n")
    before = files_of(outside)
    assert before
    warnings = recover(root)
    assert files_of(outside) == before
    assert any("링크" in w or "정션" in w for w in warnings)
    assert filetx.pending(root)
    with pytest.raises(filetx.TxError) as info, filetx.locked(root):
        pass
    assert info.value.code == "recovery_pending"


def test_tx_folder_junction_is_not_read(tmp_path: Path) -> None:
    """거래 저널 폴더 자체가 바깥 정션이면 거래로 읽지 않고 recovery_pending."""
    import _winapi

    root = make(tmp_path / "ws")
    single_tx(root, "replace", commit=False)
    tx_dir = root.joinpath(*filetx.TX_DIR)
    outside = tmp_path / "outside"
    shutil.move(str(tx_dir), str(outside))
    _winapi.CreateJunction(str(outside), str(tx_dir))
    before = files_of(outside)
    warnings = recover(root)
    assert files_of(outside) == before and warnings
    assert filetx.pending(root)[0]["phase"] == "unsafe"


# ---------------------------------------------------------- 검수 4라운드 추가 경계 (회귀로 옮김)


def test_kept_destination_race_is_exclusive(tmp_path: Path, templates: dict[str, Path]) -> None:
    """kept 이름이 비어 있다고 본 직후 사람이 같은 이름을 만들어도 덮지 않고 `-2`에 놓는다."""
    root = tmp_path / "ws"
    shutil.copytree(templates["placed_deleted"], root)
    real = filetx._move  # pyright: ignore[reportPrivateUsage]
    raced: list[Path] = []

    def racing_move(src: Path, dst: Path) -> bool:
        if not raced and filetx.KEPT_DIR[1] in dst.as_posix() and dst.name == "a.txt":
            dst.write_bytes(b"USER-RACE\n")
            raced.append(dst)
        return real(src, dst)

    with mock.patch.object(filetx, "_move", racing_move):
        recover(root)
    assert raced
    kept = {
        p.name: p.read_bytes() for p in root.joinpath(*filetx.KEPT_DIR).rglob("*") if p.is_file()
    }
    assert kept == {"a.txt": b"USER-RACE\n", "a.txt-2": b"a before\n"}


def single_replace_until(root: Path, die: str) -> None:
    """바꾸기 하나를 게시하다 `die`(`_mark_placed` 진입)에서 죽는다 (롤백 없이 디스크만 남음)."""

    def boom(*_: Any, **__: Any) -> None:
        raise Crash

    with filetx.file_lock(root), mock.patch.object(filetx.Tx, die, boom):
        tx = filetx.Tx(root)
        tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        tx._check()  # pyright: ignore[reportPrivateUsage]
        tx._prepare()  # pyright: ignore[reportPrivateUsage]
        with pytest.raises(Crash):
            tx._publish()  # pyright: ignore[reportPrivateUsage]


def intervene(root: Path, how: str) -> None:
    if how == "delete":
        (root / "a.txt").unlink()
    elif how == "edit":
        (root / "a.txt").write_bytes(b"USER-TARGET\n")


def check_outcome(root: Path, how: str) -> None:
    if how == "none":
        assert (root / "a.txt").read_bytes() == b"a before\n" and filetx.journals(root) == []
    elif how == "delete":
        assert not (root / "a.txt").exists() and filetx.journals(root) == []
        kept = [p.read_bytes() for p in root.joinpath(*filetx.KEPT_DIR).rglob("a.txt*")]
        assert kept == [b"a before\n"]
    else:
        assert (root / "a.txt").read_bytes() == b"USER-TARGET\n"


@pytest.mark.parametrize("how", ["none", "delete", "edit"])
def test_publish_unmarked_recovery(tmp_path: Path, how: str) -> None:
    """새 바이트를 놓은 뒤 놓음 표시 전에 죽음 → 개입 없음은 원래대로, 삭제는 유지, 수정은 보존."""
    root = make(tmp_path / "ws")
    single_replace_until(root, "_mark_placed")
    assert (root / "a.txt").read_bytes() == b"a after\n"
    intervene(root, how)
    recover(root)
    check_outcome(root, how)


@pytest.mark.parametrize("how", ["none", "delete", "edit"])
def test_restored_journal_fsync_before_replace(
    tmp_path: Path, templates: dict[str, Path], how: str
) -> None:
    """복원함 표시 저널을 임시 파일에 쓰고 fsync한 뒤 교체 전에 죽음 (디스크 저널엔 표시 없음)."""
    root = tmp_path / "ws"
    shutil.copytree(templates["placed"], root)
    real = filetx._write_journal  # pyright: ignore[reportPrivateUsage]

    def fsync_then_die(folder: Path, journal: Any) -> None:
        if not any(i.get("restored") for i in journal.get("replaces", [])):
            real(folder, journal)
            return
        with open(folder / f"{filetx.JOURNAL}.tmp", "wb") as f:
            f.write(json.dumps(journal).encode())
            f.flush()
            os.fsync(f.fileno())
        raise Crash

    with (
        mock.patch.object(filetx, "_write_journal", fsync_then_die),
        filetx.file_lock(root),
        pytest.raises(Crash),
    ):
        filetx.recover(root)
    [folder] = list(root.joinpath(*filetx.TX_DIR).iterdir())
    on_disk = json.loads((folder / filetx.JOURNAL).read_text("utf-8"))
    assert not any(i.get("restored") for i in on_disk["replaces"])
    assert (root / "a.txt").read_bytes() == b"a before\n"
    intervene(root, how)
    recover(root)
    check_outcome(root, how)


def test_prepare_delete_rollback_preserves_user_edit(
    tmp_path: Path, templates: dict[str, Path]
) -> None:
    """커밋 전 거래의 지울 파일을 사람이 고치면 롤백은 그 파일에 손대지 않는다."""
    root = tmp_path / "ws"
    shutil.copytree(templates["placed"], root)
    (root / "d.txt").write_bytes(b"USER-DELETE-EDIT\n")
    recover(root)
    assert (root / "d.txt").read_bytes() == b"USER-DELETE-EDIT\n"
    assert filetx.journals(root) == []


@pytest.mark.parametrize("how", ["none", "delete", "edit"])
def test_committed_delete_target_intervention(
    tmp_path: Path, templates: dict[str, Path], how: str
) -> None:
    """마무리가 지울 파일을 del로 옮긴 직후 죽음 → 개입 없음·del 칸 삭제는 지운 그대로, 빈 자리에
    사람이 새로 쓴 바이트는 보존."""
    root = tmp_path / "ws"
    shutil.copytree(templates["committed"], root)
    labels = recover_crashing(root, 1)
    assert labels == ["rename d.txt → del-0"]
    if how == "delete":
        next(root.joinpath(*filetx.TRASH_DIR).rglob("del-0")).unlink()
    elif how == "edit":
        (root / "d.txt").write_bytes(b"USER-DELETE-NEW\n")
    recover(root)
    if how == "edit":
        assert (root / "d.txt").read_bytes() == b"USER-DELETE-NEW\n"
    else:
        assert not (root / "d.txt").exists()
    assert filetx.journals(root) == []


# ---------------------------------------------------------- 개별 거래 저널 자리 (B1 5라운드 High)


def assert_blocked(root: Path) -> None:
    with pytest.raises(filetx.TxError) as info, filetx.locked(root):
        pass
    assert info.value.code == "recovery_pending"


@pytest.mark.parametrize("junction", [True, False])
def test_pending_tx_trash_keeps_user_bytes(tmp_path: Path, junction: bool) -> None:
    """살아 있는 거래의 저널 폴더가 바깥 정션이어도 그 거래는 "있는 안전하지 않은 거래"다 —
    경고·pending·새 거래 차단, 가지치기 보류로 보존 영역의 사람 바이트가 남는다. 정션이 없으면
    정상 롤백이 그 바이트를 kept로 옮긴다(양성 대조)."""
    import _winapi

    root = make(tmp_path / "ws")
    txid = "20261101000000-00000000"
    with filetx.file_lock(root):
        tx = filetx.Tx(root)
        tx.txid = txid
        tx.folder = root.joinpath(*filetx.TX_DIR, txid)
        tx.replace("a.txt", b"a after\n", expect_sha=filetx.sha256_of(b"a before\n"))
        tx._check()  # pyright: ignore[reportPrivateUsage]
        tx._prepare()  # pyright: ignore[reportPrivateUsage]
        tx._publish()  # pyright: ignore[reportPrivateUsage]
    trash = root.joinpath(*filetx.TRASH_DIR)
    marker = b"USER-ONLY-OLD-HANDLE-EDIT"
    (trash / txid / "old-0").write_bytes(marker)  # 열린 핸들로 고친 사람 바이트 (사본 없음)
    for n in range(filetx.TRASH_KEEP_MIN):  # 더 최근 거래 20개 → 이 거래는 개수 밖
        (trash / f"20261102000000-{n:08x}").mkdir()
    old = time.time() - (filetx.TRASH_KEEP_DAYS + 1) * 86400
    os.utime(trash / txid, (old, old))
    outside = tmp_path / "outside"
    before: dict[str, bytes] = {}
    if junction:
        shutil.move(str(root.joinpath(*filetx.TX_DIR, txid)), str(outside))
        _winapi.CreateJunction(str(outside), str(root.joinpath(*filetx.TX_DIR, txid)))
        before = files_of(outside)
    warnings = recover(root)
    assert marker in everything(root)
    if junction:
        assert warnings and files_of(outside) == before
        assert [e["phase"] for e in filetx.pending(root)] == ["unsafe"]
        assert filetx.journals(root) == [txid]
        assert (trash / txid / "old-0").read_bytes() == marker  # 가지치기 보류
        assert_blocked(root)
    else:
        kept = [p.read_bytes() for p in root.joinpath(*filetx.KEPT_DIR).rglob("*") if p.is_file()]
        assert marker in kept and (root / "a.txt").read_bytes() == b"a before\n"


@pytest.mark.parametrize("entry", ["tx_child", "tx_file"])
def test_directory_boundary_pending(tmp_path: Path, entry: str) -> None:
    """거래 저널 자리의 링크·정션(또는 폴더가 아닌 항목)은 읽지 않고 이름만으로 pending·경고·
    차단."""
    import _winapi

    root = make(tmp_path / "ws")
    tx_dir = root.joinpath(*filetx.TX_DIR)
    if entry == "tx_child":
        single_tx(root, "replace", commit=False)
        [folder] = list(tx_dir.iterdir())
        outside = tmp_path / "outside"
        shutil.move(str(folder), str(outside))
        _winapi.CreateJunction(str(outside), str(folder))
        before = files_of(outside)
    else:
        tx_dir.mkdir(parents=True)
        (tx_dir / "stray").write_bytes(b"not a journal folder\n")
        outside, before = None, {}
    warnings = recover(root)
    pend = filetx.pending(root)
    assert warnings and [e["phase"] for e in pend] == ["unsafe"]
    assert_blocked(root)
    if outside is not None:
        assert files_of(outside) == before
