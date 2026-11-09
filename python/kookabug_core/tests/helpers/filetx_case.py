"""`filetx` 실패 주입 검사의 거래 하나 (같은 프로세스·자식 프로세스 공용, M8 B1)."""

from __future__ import annotations

from pathlib import Path

from kookabug_core import filetx

A_NEW = b"a after\n"
B_NEW = b"b created\n"
C_NEW = b"c created\n"


def run_tx(root: Path) -> dict[str, object]:
    """바꾸기 1·만들기 2(새 폴더 포함)·지우기 1."""
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.replace("a.txt", A_NEW, expect_sha=filetx.sha256_of((root / "a.txt").read_bytes()))
        tx.create("new/sub/b.txt", B_NEW)
        tx.create("c.txt", C_NEW)
        tx.delete("d.txt", expect_sha=filetx.sha256_of((root / "d.txt").read_bytes()))
        return tx.commit()
