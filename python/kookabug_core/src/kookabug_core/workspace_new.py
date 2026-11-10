"""새 워크스페이스 만들기 (M8 계획 3.1·C15). CLI `kookabug workspace new`(daemon 없이 동작)와 앱
마법사 1단계(메인 프로세스가 CLI를 부름)가 쓴다.

만드는 것: `kookabug.json`(형식·ID·이름), `AGENTS.md`(관리 구간), `.gitignore`(`runs/`·
`.kookabug/`), `tests/`·`subgraphs/`·`targets/`·`screens/`, `knowledge/` 하위 폴더, `wiki/index.md`.
폴더가 있고 비어 있지 않으면 아무것도 쓰지 않는다(`not_empty`). `git=True`면 `git init`도 한다
(실패는 경고 — 워크스페이스는 그대로 쓸 수 있다).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unicodedata
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from kookabug_core.canonical import canonical_dumps
from kookabug_core.documents import write_atomic
from kookabug_core.knowledge.formats import LAYOUT
from kookabug_core.knowledge.render import render_index
from kookabug_core.workspace import WORKSPACE_FILE, write_agents_md

__all__ = ["GITIGNORE", "CreateError", "Created", "create_workspace"]

GITIGNORE: Final = "# 실행 기록·개인 설정 (워크스페이스 구조.md)\nruns/\n.kookabug/\n"
FOLDERS: Final = ("tests", "subgraphs", "targets", "screens", *LAYOUT)
GIT_TIMEOUT_S: Final = 30


class CreateError(Exception):
    """만들지 않았다. `code`: `not_empty`·`invalid_name`·`path_link`·`io_error`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Created:
    root: Path
    id: str
    files: list[str] = field(default_factory=list[str])
    git: bool = False
    warnings: list[str] = field(default_factory=list[str])

    def to_dict(self) -> dict[str, object]:
        return {
            "root": str(self.root),
            "id": self.id,
            "files": self.files,
            "git": self.git,
            "warnings": self.warnings,
        }


def _check_name(name: str) -> str:
    name = name.strip()
    if not 1 <= len(name) <= 100 or any(unicodedata.category(ch).startswith("C") for ch in name):
        raise CreateError("invalid_name", "프로젝트 이름은 1~100자, 제어 문자 없이 쓴다")
    return name


def _check_no_links(path: Path) -> None:
    """대상과 그 조각(있는 조상 폴더) 중 링크·정션이 있으면 거부한다 — 글자와 다른 곳(정션이
    가리키는 외부 폴더)에 워크스페이스를 만들지 않는다 (B7 검수 H1). 앱은 고른 위치의 실경로를
    넘긴다."""
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if current.is_symlink() or current.is_junction():
            raise CreateError("path_link", f"{current}이(가) 링크·정션이라 만들지 않는다")


def create_workspace(root: str | os.PathLike[str], name: str, *, git: bool = False) -> Created:
    """`root`에 새 워크스페이스를 만든다. 없으면 폴더도 만든다."""
    name = _check_name(name)
    path = Path(os.path.abspath(root))
    _check_no_links(path)
    if path.exists():
        if not path.is_dir():
            raise CreateError("not_empty", f"{path}은(는) 폴더가 아니다")
        if any(path.iterdir()):
            raise CreateError("not_empty", f"{path}이(가) 비어 있지 않아 만들지 않는다")
    try:
        path.mkdir(parents=True, exist_ok=True)
        # 쓰기 직전에 다시 본다 (검사와 만들기 사이에 바뀐 경우)
        _check_no_links(path)
        path = path.resolve()
        workspace_id = str(uuid.uuid4())
        created = Created(path, workspace_id)
        config = {"format": "kookabug.workspace/0", "id": workspace_id, "name": name}
        write_atomic(path / WORKSPACE_FILE, canonical_dumps(config).encode("utf-8"))
        write_atomic(path / ".gitignore", GITIGNORE.encode("utf-8"))
        write_agents_md(path)
        for folder in FOLDERS:
            path.joinpath(*folder.split("/")).mkdir(parents=True, exist_ok=True)
        write_atomic(path / "wiki" / "index.md", render_index([], {}, []).encode("utf-8"))
    except OSError as exc:
        raise CreateError("io_error", f"워크스페이스를 만들지 못했다: {exc.strerror}") from exc
    created.files = [WORKSPACE_FILE, ".gitignore", "AGENTS.md", "wiki/index.md"]
    if git:
        exe = shutil.which("git")
        if exe is None:
            created.warnings.append("git을 찾지 못해 git init을 하지 않았다")
        else:
            try:
                done = subprocess.run(
                    [exe, "init", "--quiet"],
                    cwd=path,
                    capture_output=True,
                    timeout=GIT_TIMEOUT_S,
                    check=False,
                )
                created.git = done.returncode == 0
                if not created.git:
                    created.warnings.append(f"git init 실패 (종료 코드 {done.returncode})")
            except (OSError, subprocess.TimeoutExpired) as exc:
                created.warnings.append(f"git init 실패: {exc}")
    return created
