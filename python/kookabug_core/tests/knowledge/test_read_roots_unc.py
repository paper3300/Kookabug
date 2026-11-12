"""UX3 검수 2 — UNC 관리 공유·루프백 별칭(`\\\\localhost\\D$\\<ws>`) 거부, 일반 NAS UNC는 허용.

SMB에는 연결하지 않는다: UNC 경로의 `os.path.realpath`·긴 이름 풀기·`Path.exists`·`is_dir`·
`is_symlink`·`is_junction`을 막아 판정만 본다(`no_smb`). 네 입구(저장·제안, 읽을 때 설정 값, 자동
포함, 원본 루트)를 모두 본다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from helpers.knowledge import CHECK, make_ws

from kookabug_core.knowledge import read_roots, setting_change, source_read
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.workspace import Workspace

NO_SECRETS = lambda: []  # noqa: E731
ENV = {"COMPUTERNAME": "REVIEWPC"}
JOB = "j-20261112-130000-abcd"


def _unc(path: Any) -> bool:
    text = os.fspath(path).replace("/", "\\")
    return text.startswith("\\\\") and not text.startswith(("\\\\?\\", "\\\\.\\"))


@pytest.fixture
def no_smb(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """UNC 경로는 연결 없이 그대로 돌려준다. 돌려준 dict에 `드라이브 경로 → UNC 실경로`를 넣으면
    네트워크 드라이브처럼 실경로를 UNC로 푼다."""
    mapped: dict[str, str] = {}
    original = os.path.realpath

    def realpath(path: Any, *args: Any, **kwargs: Any) -> str:
        text = os.fspath(path)
        for drive, unc in mapped.items():
            if text.casefold().startswith(drive.casefold()):
                return unc + text[len(drive) :]
        return text if _unc(text) else original(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "realpath", realpath)

    def wrap(name: str, value: bool) -> None:
        orig: Callable[..., bool] = getattr(Path, name)

        def fake(self: Path, *args: Any, **kwargs: Any) -> bool:
            return value if _unc(self) else orig(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, fake)

    wrap("exists", True)
    wrap("is_dir", True)
    wrap("is_symlink", False)
    wrap("is_junction", False)
    long = read_roots._long  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(read_roots, "_long", lambda p: p if _unc(p) else long(p))
    return mapped


def loopback(root: Path, host: str = "localhost") -> str:
    """`D:\\a\\ws` → `\\\\<host>\\D$\\a\\ws` (관리 공유 루프백 별칭)."""
    return f"\\\\{host}\\{root.drive[0]}$\\{str(root)[3:]}"


def set_local(root: Path, **settings: Any) -> None:
    file = root / ".kookabug" / "local.json"
    file.parent.mkdir(exist_ok=True)
    doc: dict[str, Any] = (
        json.loads(file.read_text("utf-8")) if file.exists() else {"format": "kookabug.local/0"}
    )
    doc.setdefault("settings", {}).update(settings)
    file.write_text(json.dumps(doc), "utf-8")


def reason(fn: Any, *args: Any, **kwargs: Any) -> tuple[str, Any]:
    with pytest.raises(KnowledgeError) as info:
        fn(*args, **kwargs)
    return info.value.code, info.value.fields.get("reason")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = make_ws(tmp_path)
    (root / ".kookabug").mkdir(exist_ok=True)
    (root / ".kookabug" / "review_token.txt").write_text("protected-marker", "utf-8")
    (root / "screens").mkdir(exist_ok=True)
    return root


def test_admin_share_and_loopback_hosts() -> None:
    yes = (
        "\\\\nas\\C$\\x",
        "\\\\nas\\admin$",
        "\\\\nas\\IPC$\\x",
        "\\\\nas\\docs$\\x",
        "//nas/d$/x",
        "\\\\localhost\\share\\x",
        "\\\\LOCALHOST\\share",
        "\\\\127.0.0.1\\share\\x",
        "\\\\127.5.6.7\\share",
        "\\\\::1\\share",
        "\\\\[::1]\\share",
        "\\\\0:0:0:0:0:0:0:1\\share",
        "\\\\::ffff:127.0.0.1\\share",
        "\\\\0--1.ipv6-literal.net\\share",
        "\\\\0-0-0-0-0-0-0-1.IPV6-LITERAL.NET\\share",
        "\\\\reviewpc\\share",
        "\\\\ReviewPC.corp.example\\share",
        "\\\\?\\UNC\\localhost\\share\\x",
    )
    for path in yes:
        assert read_roots.admin_share(path, env=ENV), path
    no = (
        "\\\\nas\\share\\docs",
        "\\\\nas.corp.example\\plans\\x",
        "\\\\10.0.0.5\\share",
        "\\\\fe80--1.ipv6-literal.net\\share",
        "\\\\otherpc\\share",
        "\\\\reviewpc2\\share",
        "D:\\Games\\x",
        "D:\\a$\\x",
    )
    for path in no:
        assert not read_roots.admin_share(path, env=ENV), path


def test_review_repro_loopback_refused_on_save_and_propose(
    ws: Path, no_smb: dict[str, str]
) -> None:
    """검수 재현: `\\\\localhost\\D$\\<ws>`·`…\\.kookabug`·`…\\screens`·
    `\\\\127.0.0.1\\D$\\<ws>\\.kookabug` — 같은 폴더를 로컬 경로로 넣으면 거부되던 것이 이제
    `admin_share`로 거부된다."""
    w = Workspace.open(ws)
    paths = (
        loopback(ws),
        loopback(ws) + "\\.kookabug",
        loopback(ws) + "\\screens",
        loopback(ws, "127.0.0.1") + "\\.kookabug",
    )
    for path in paths:
        assert read_roots.refusal(w, path, env=ENV) == "admin_share", path
        with pytest.raises(KnowledgeError) as info:
            read_roots.normalize(w, [path], env=ENV)
        assert info.value.fields["reason"] == "admin_share"
    # 제안 단계도 같은 검사 (수락도 같은 `check_read_root`)
    got = reason(
        setting_change.propose,
        ws,
        JOB,
        "agent.read_roots.add",
        loopback(ws) + "\\.kookabug",
        "r",
        [],
        check_secrets=CHECK,
    )
    assert got == ("policy_path", "admin_share")
    assert reason(setting_change.check_read_root, ws, loopback(ws)) == (
        "policy_path",
        "admin_share",
    )


def test_loopback_refused_on_read_auto_and_source_root(ws: Path, no_smb: dict[str, str]) -> None:
    # 읽을 때 설정 값 (손으로 넣은 값)
    set_local(ws, **{read_roots.KEY: [loopback(ws), loopback(ws) + "\\.kookabug"]})
    w = Workspace.open(ws)
    for root_id, rel in (("read:1", ".kookabug/review_token.txt"), ("read:2", "review_token.txt")):
        got = reason(source_read.read_source, w, root_id, rel, secrets=NO_SECRETS)
        assert got == ("policy_path", "admin_share"), root_id
    # 자동 포함 (game.executable·game.cwd)
    set_local(
        ws,
        **{
            read_roots.KEY: [],
            "game.executable": loopback(ws) + "\\Game.exe",
            "game.cwd": loopback(ws, "127.0.0.1") + "\\screens",
        },
    )
    w = Workspace.open(ws)
    auto = {r["id"]: r for r in read_roots.read_roots(w)}
    assert (auto["read:game"]["state"], auto["read:game"]["reason"]) == ("refused", "admin_share")
    assert auto["read:game_cwd"]["reason"] == "admin_share"
    got = reason(
        source_read.read_source, w, "read:game", ".kookabug/review_token.txt", secrets=NO_SECRETS
    )
    assert got == ("policy_path", "admin_share")
    # 원본(UX2) 루트
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["sources"] = [
        *config["sources"],
        {"id": "loop", "kind": "other", "title": "루프백", "path": loopback(ws)},
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    w = Workspace.open(ws)
    listed = {s["id"]: s for s in source_read.list_sources(w)}
    assert listed["loop"]["state"] == "unreadable"
    got = reason(
        source_read.read_source, w, "loop", ".kookabug/review_token.txt", secrets=NO_SECRETS
    )
    assert got == ("policy_path", "admin_share")


def test_network_drive_resolving_to_loopback_refused(
    ws: Path, tmp_path: Path, no_smb: dict[str, str]
) -> None:
    """네트워크 드라이브 문자(지정 경로는 로컬 모양)의 실경로가 루프백 관리 공유 UNC면 거부."""
    tools = tmp_path / "tools"
    tools.mkdir()
    no_smb[str(tools)] = loopback(ws)  # `net use`처럼 실경로가 UNC로 풀린다
    w = Workspace.open(ws)
    assert read_roots.refusal(w, str(tools), env=ENV) == "admin_share"
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["sources"] = [
        *config["sources"],
        {"id": "mapped", "kind": "other", "title": "드라이브", "path": str(tools)},
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    got = reason(source_read.list_source, Workspace.open(ws), "mapped")
    assert got == ("policy_path", "admin_share")


def test_plain_nas_unc_allowed(ws: Path, no_smb: dict[str, str]) -> None:
    """일반 UNC(회사 NAS의 기획 문서 등)는 계속 허용한다."""
    w = Workspace.open(ws)
    assert read_roots.refusal(w, "\\\\nas\\share\\docs", env=ENV) is None
    assert read_roots.normalize(w, ["\\\\nas\\share\\docs"], env=ENV) == ["\\\\nas\\share\\docs"]
    assert read_roots.refusal(w, "\\\\nas\\share", env=ENV) == "drive_root"
    assert read_roots.refusal(w, "\\\\nas\\docs$\\plans", env=ENV) == "admin_share"
