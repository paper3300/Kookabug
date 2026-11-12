"""Agent 읽기 허용 폴더 (UX3) — 허용하지 않는 폴더(저장·읽기), 자동 포함, 민감한 이름, 근거 아님.

읽기 허용 폴더는 워크스페이스 **밖** 임시 폴더다(`make_ws`는 `tmp_path/ws`). 사용자 프로필·
Windows·Program Files는 가짜 환경(`env`)으로 본다(실제 PC 폴더를 건드리지 않는다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.knowledge import CHECK, add, apply, make_ws, price_claim

from kookabug_core.knowledge import read_roots, setting_change, source_read
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.knowledge.sources import verify_basis
from kookabug_core.workspace import Workspace

NO_SECRETS = lambda: []  # noqa: E731


def set_local(root: Path, **settings: Any) -> None:
    (root / ".kookabug").mkdir(exist_ok=True)
    file = root / ".kookabug" / "local.json"
    doc: dict[str, Any] = (
        json.loads(file.read_text("utf-8")) if file.exists() else {"format": "kookabug.local/0"}
    )
    doc.setdefault("settings", {}).update(settings)
    file.write_text(json.dumps(doc), "utf-8")


def fake_env(tmp_path: Path) -> dict[str, str]:
    """가짜 사용자 프로필·Windows·Program Files (실제 폴더 대신)."""
    out = {
        "USERPROFILE": tmp_path / "home",
        "SystemRoot": tmp_path / "win",
        "ProgramFiles": tmp_path / "pf",
        "ProgramFiles(x86)": tmp_path / "pf86",
    }
    for path in out.values():
        path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "home" / "AppData" / "Local" / "Game").mkdir(parents=True)
    (tmp_path / "win" / "System32").mkdir(parents=True)
    (tmp_path / "pf" / "Game").mkdir(parents=True)
    return {k: str(v) for k, v in out.items()}


def reason(fn: Any, *args: Any, **kwargs: Any) -> tuple[str, Any]:
    with pytest.raises(KnowledgeError) as info:
        fn(*args, **kwargs)
    return info.value.code, info.value.fields.get("reason")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = make_ws(tmp_path)
    tools = tmp_path / "tools"
    (tools / "env").mkdir(parents=True)
    (tools / "launch.bat").write_bytes(b"@echo off\nGame.exe -server=dev\n")
    (tools / "env" / "servers.json").write_text('{"servers": ["dev"]}', "utf-8")
    game = tmp_path / "game"
    game.mkdir()
    (game / "Game.exe").write_bytes(b"MZ\0\0")
    (game / "game.ini").write_text("[net]\nport=7777\n", "utf-8")
    set_local(root, **{"game.executable": str(game / "Game.exe"), read_roots.KEY: [str(tools)]})
    return root


def test_refused_folders_on_save(ws: Path, tmp_path: Path) -> None:
    env = fake_env(tmp_path)
    w = Workspace.open(ws)

    def why(path: Path | str) -> str | None:
        return read_roots.refusal(w, str(path), env=env)

    assert why("C:\\") == "drive_root"
    assert why(Path(ws.anchor)) == "drive_root"
    assert why("relative/dir") == "not_absolute"
    assert why(tmp_path / "home") == "user_profile"
    assert why(tmp_path / "HOME" / "appdata") == "app_data"  # 대소문자 무시
    assert why(tmp_path / "home" / "AppData" / "Local" / "Game") is None  # AppData 아래는 된다
    assert why(tmp_path / "win") == "windows"
    assert why(tmp_path / "win" / "System32") == "windows"
    assert why(tmp_path / "pf") == "program_files"
    assert why(tmp_path / "pf86") == "program_files"
    assert why(tmp_path / "pf" / "Game") is None  # Program Files 아래 게임 폴더는 된다
    assert why(ws) == "contains_workspace"
    assert why(tmp_path) == "contains_workspace"
    assert why(ws / "knowledge") == "workspace_derived"
    assert why(tmp_path / "nope") == "missing"
    (tmp_path / "x" / ".ssh").mkdir(parents=True)
    assert why(tmp_path / "x" / ".ssh") == "sensitive_name"
    assert why(tmp_path / "tools") is None
    # 저장 검사: policy_path + 이유 + 몇째 줄인지 (경로 값은 메시지에 넣지 않는다)
    with pytest.raises(KnowledgeError) as info:
        read_roots.normalize(w, [str(tmp_path / "tools"), str(tmp_path)], env=env)
    assert info.value.code == "policy_path"
    assert info.value.fields == {"reason": "contains_workspace", "index": 1}
    assert str(tmp_path) not in info.value.message
    # 빈 줄은 빼고, 같은 폴더는 하나로
    tools = str(tmp_path / "tools")
    assert read_roots.normalize(w, [tools, "  ", tools.upper()], env=env) == [tools]
    with pytest.raises(KnowledgeError):
        read_roots.normalize(w, [tools] * (read_roots.MAX_ROOTS + 1), env=env)


def test_auto_roots_from_effective_game_settings(ws: Path, tmp_path: Path) -> None:
    w = Workspace.open(ws)
    roots = {r["id"]: r for r in read_roots.read_roots(w)}
    assert roots["read:game"] == {
        "id": "read:game",
        "path": str(tmp_path / "game"),
        "title": read_roots.AUTO_TITLE,
        "auto": True,
        "state": "ok",
        "reason": None,
    }
    assert roots["read:1"]["path"] == str(tmp_path / "tools") and roots["read:1"]["auto"] is False
    assert "read:game_cwd" not in roots  # 작업 폴더 설정 없음
    # 작업 폴더가 실행 파일 폴더와 다르면 따로, 같으면 하나
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    set_local(ws, **{"game.cwd": str(runtime)})
    roots = {r["id"]: r for r in read_roots.read_roots(Workspace.open(ws))}
    assert roots["read:game_cwd"]["path"] == str(runtime)
    set_local(ws, **{"game.cwd": str(tmp_path / "game")})
    assert "read:game_cwd" not in {r["id"] for r in read_roots.read_roots(Workspace.open(ws))}
    # 설정 파일에는 쓰지 않는다 (계산 값)
    local = json.loads((ws / ".kookabug" / "local.json").read_text("utf-8"))
    assert local["settings"][read_roots.KEY] == [str(tmp_path / "tools")]


def test_auto_root_refused_is_dropped_with_reason(ws: Path, tmp_path: Path) -> None:
    """실행 파일이 워크스페이스를 품는 폴더에 있으면 자동 포함에서 빠진다(읽기도 거부)."""
    (tmp_path / "Game.exe").write_bytes(b"MZ")
    set_local(ws, **{"game.executable": str(tmp_path / "Game.exe")})
    w = Workspace.open(ws)
    auto = next(r for r in read_roots.read_roots(w) if r["id"] == "read:game")
    assert auto["state"] == "refused" and auto["reason"] == "contains_workspace"
    listed = {s["id"]: s for s in source_read.list_sources(w)}
    assert listed["read:game"]["state"] == "refused" and listed["read:game"]["type"] is None
    assert reason(source_read.read_source, w, "read:game", "Game.exe", secrets=NO_SECRETS) == (
        "policy_path",
        "contains_workspace",
    )
    assert reason(source_read.list_source, w, "read:game") == ("policy_path", "contains_workspace")


def test_refused_on_read_even_if_saved_by_hand(ws: Path, tmp_path: Path) -> None:
    """local.json을 손으로 고쳐 넣은 허용하지 않는 폴더도 읽을 때 거부한다."""
    set_local(ws, **{read_roots.KEY: [str(tmp_path), "C:\\"]})
    w = Workspace.open(ws)
    assert reason(source_read.read_source, w, "read:1", "ws/kookabug.json", secrets=NO_SECRETS) == (
        "policy_path",
        "contains_workspace",
    )
    assert reason(source_read.list_source, w, "read:2") == ("policy_path", "drive_root")
    assert reason(source_read.read_source, w, "read:9", "x", secrets=NO_SECRETS)[0] == "unknown_id"


def test_list_and_read_read_root(ws: Path, tmp_path: Path) -> None:
    w = Workspace.open(ws)
    listed = {s["id"]: s for s in source_read.list_sources(w)}
    assert listed["read:1"] == {
        "id": "read:1",
        "kind": "read_root",
        "title": str(tmp_path / "tools"),
        "state": "ok",
        "type": "dir",
    }
    assert listed["read:game"]["kind"] == "read_root"
    assert listed["plans" if "plans" in listed else "item_table"]["kind"] != "read_root"
    top = source_read.list_source(w, "read:1")
    assert [e["name"] for e in top["entries"]] == ["env", "launch.bat"]
    got = source_read.read_source(w, "read:1", "launch.bat", secrets=lambda: ["dev"])
    assert got["text"] == "@echo off\nGame.exe -server=***\n"  # 같은 가림
    assert got["ref"] == "read:1#launch.bat" and got["format"] == "text"
    ini = source_read.read_source(w, "read:game", "game.ini", secrets=NO_SECRETS)
    assert "port=7777" in ini["text"]
    # 경계는 원본과 같다
    outside = reason(
        source_read.read_source, w, "read:1", "../ws/kookabug.json", secrets=NO_SECRETS
    )
    assert outside[0] == "policy_path"


def test_sensitive_names_refused_and_hidden(ws: Path, tmp_path: Path) -> None:
    tools = tmp_path / "tools"
    for rel in (
        ".ssh/config",
        ".GIT/config",
        ".aws/credentials",
        "cert.PEM",
        "server.key",
        "a.pfx",
        "b.p12",
        "vault.kdbx",
        ".env",
        ".env.local",
        "id_rsa.pub",
        "id_ed25519",
        "Credentials.json",
        "app.keystore",
        "app.jks",
        "nested/.gnupg/x",
        "nested/.azure/x",
    ):
        (tools / rel).parent.mkdir(parents=True, exist_ok=True)
        (tools / rel).write_text("secret", "utf-8")
        got = reason(source_read.read_source, Workspace.open(ws), "read:1", rel, secrets=NO_SECRETS)
        assert got == ("policy_path", "sensitive_name"), rel
    w = Workspace.open(ws)
    names = [e["name"] for e in source_read.list_source(w, "read:1")["entries"]]
    assert names == ["env", "nested", "launch.bat"]
    assert reason(source_read.list_source, w, "read:1", ".ssh") == ("policy_path", "sensitive_name")
    # 원본(기획 근거)은 이 이름 목록을 쓰지 않는다 (UX2 그대로)
    assert read_roots.sensitive(["ok.md", "keys"]) is False


def test_proposal_add_read_root(ws: Path, tmp_path: Path) -> None:
    """`agent.read_roots.add` 제안: 허용 목록 안, 같은 검사(허용하지 않는 폴더·이미 있음), 설정은 안
    바뀐다(수락은 daemon 검사 `test_ux3_methods`)."""
    job = "j-20261112-120000-abcd"

    def propose(value: Any) -> Any:
        return setting_change.propose(
            ws, job, "agent.read_roots.add", value, "실행 bat", [], check_secrets=CHECK
        )

    before = (ws / ".kookabug" / "local.json").read_bytes()
    extra = tmp_path / "server_list"
    extra.mkdir()
    got = propose(str(extra))
    assert got["key"] == "agent.read_roots.add" and got["value"] == str(extra)
    assert got["current"] == [str(tmp_path / "tools")]
    assert (ws / ".kookabug" / "local.json").read_bytes() == before
    assert reason(propose, str(tmp_path / "tools")) == ("exists", None)
    assert reason(propose, str(tmp_path)) == ("policy_path", "contains_workspace")
    assert reason(propose, "relative")[1] == "not_absolute"
    assert reason(propose, ["x"])[0] == "format"


def test_read_root_file_is_not_source_basis(ws: Path) -> None:
    w = Workspace.open(ws)
    got = source_read.read_source(w, "read:1", "launch.bat", secrets=NO_SECRETS)
    for ref in (got["ref"], "sources:read:1#launch.bat", "sources:read#launch.bat"):
        with pytest.raises(KnowledgeError) as info:
            verify_basis(w, {"type": "source", "ref": ref, "hash": got["hash"]})
        assert info.value.code == "basis_unknown", ref
    claim = price_claim(basis=[{"type": "source", "ref": got["ref"], "hash": got["hash"]}])
    assert reason(apply, ws, [add("features/shop", claim)], rid="ux3-basis")[0] == "basis_unknown"


# ---------------------------------------------------------------- 검수 1 (H1·H2·M1) 회귀


def _short(path: Path) -> str | None:
    """8.3 짧은 경로 (볼륨이 짧은 이름을 만들지 않으면 None)."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buf = ctypes.create_unicode_buffer(32768)
    n = int(kernel32.GetShortPathNameW(str(path), buf, 32768))
    if not 0 < n < 32768 or buf.value.casefold() == str(path).casefold():
        return None
    return buf.value


DEVICE_FORMS = ("\\\\?\\{}", "//?/{}", "\\\\.\\{}", "\\??\\{}", "\\/?\\{}")


def test_h1_device_prefix_refused_on_save_read_and_auto(ws: Path, tmp_path: Path) -> None:
    """검수 재현: `\\\\?\\<ws>`·`\\\\?\\<ws>\\.kookabug`·`\\\\?\\` 실행 파일 — 저장·읽기·자동 포함
    모두 `device_path`로 거부되고 보호 경로가 읽히지 않는다."""
    (ws / ".kookabug" / "review_token.txt").write_text("protected-marker", "utf-8")
    (ws / "screens").mkdir(exist_ok=True)
    (ws / "Game.exe").write_bytes(b"MZ")
    w = Workspace.open(ws)
    for form in DEVICE_FORMS:
        for target in (ws, ws / ".kookabug", tmp_path / "tools"):
            path = form.format(target)
            assert read_roots.refusal(w, path) == "device_path", path
            # 저장
            with pytest.raises(KnowledgeError) as info:
                read_roots.normalize(w, [path])
            assert info.value.fields["reason"] == "device_path"
    # 읽기: 손으로 넣은 값
    set_local(ws, **{read_roots.KEY: [f"\\\\?\\{ws}", f"\\\\?\\{ws}\\.kookabug"]})
    w = Workspace.open(ws)
    for root_id, rel in (("read:1", ".kookabug/review_token.txt"), ("read:2", "review_token.txt")):
        got = reason(source_read.read_source, w, root_id, rel, secrets=NO_SECRETS)
        assert got == ("policy_path", "device_path"), root_id
    assert reason(source_read.list_source, w, "read:1") == ("policy_path", "device_path")
    # 자동 포함: `\\?\` 실행 파일·작업 폴더는 빼고 경고
    set_local(
        ws,
        **{
            read_roots.KEY: [],
            "game.executable": f"\\\\?\\{ws}\\Game.exe",
            "game.cwd": f"//?/{tmp_path / 'game'}",
        },
    )
    w = Workspace.open(ws)
    auto = {r["id"]: r for r in read_roots.read_roots(w)}
    assert auto["read:game"]["state"] == "refused"
    assert auto["read:game"]["reason"] == "device_path"
    assert auto["read:game_cwd"]["reason"] == "device_path"
    for rel in (".kookabug/review_token.txt", ".kookabug/local.json", "screens"):
        got = reason(source_read.read_source, w, "read:game", rel, secrets=NO_SECRETS)
        assert got == ("policy_path", "device_path"), rel


def test_h1_device_prefixed_env_dirs_still_refused(ws: Path, tmp_path: Path) -> None:
    """가짜 프로필·AppData·Windows·Program Files에 `\\\\?\\`를 붙인 환경 변수도 같은 정규화로
    비교."""
    env = {k: f"\\\\?\\{v}" for k, v in fake_env(tmp_path).items()}
    w = Workspace.open(ws)
    assert read_roots.refusal(w, str(tmp_path / "home"), env=env) == "user_profile"
    assert read_roots.refusal(w, str(tmp_path / "home" / "AppData"), env=env) == "app_data"
    assert read_roots.refusal(w, str(tmp_path / "win" / "System32"), env=env) == "windows"
    assert read_roots.refusal(w, str(tmp_path / "pf"), env=env) == "program_files"
    assert read_roots.refusal(w, str(tmp_path / "pf86"), env=env) == "program_files"
    assert read_roots.refusal(w, str(tmp_path / "pf" / "Game"), env=env) is None


def test_h1_short_name_profile_env(ws: Path, tmp_path: Path) -> None:
    """`USERPROFILE`을 8.3 짧은 경로로 줘도 긴 경로의 프로필·AppData를 거부한다 (반대도)."""
    home = tmp_path / "user profile long name"
    (home / "AppData").mkdir(parents=True)
    short = _short(home)
    if short is None:
        pytest.skip("이 볼륨은 8.3 짧은 이름을 만들지 않는다")
    w = Workspace.open(ws)
    env = {"USERPROFILE": short}
    assert read_roots.refusal(w, str(home), env=env) == "user_profile"
    assert read_roots.refusal(w, str(home / "AppData"), env=env) == "app_data"
    long_env = {"USERPROFILE": str(home)}
    assert read_roots.refusal(w, short, env=long_env) == "user_profile"
    # 워크스페이스를 짧은 경로로 줘도 품는 폴더로 본다
    ws_short = _short(ws)
    if ws_short is not None:
        assert read_roots.refusal(w, ws_short) == "contains_workspace"


def test_h1_ux2_source_root_device_prefix_refused(ws: Path) -> None:
    """원본(UX2) 루트도 확장 접두사는 입구에서 거부한다 (`.kookabug`가 원본으로 읽히지 않게)."""
    (ws / ".kookabug" / "review_token.txt").write_text("protected-marker", "utf-8")
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["sources"] = [
        *config["sources"],
        {"id": "alias", "kind": "other", "title": "별칭", "path": f"\\\\?\\{ws}"},
        {"id": "alias2", "kind": "other", "title": "별칭", "path": f"\\\\?\\{ws}\\.kookabug"},
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    w = Workspace.open(ws)
    listed = {s["id"]: s for s in source_read.list_sources(w)}
    assert listed["alias"]["state"] == "unreadable" and listed["alias2"]["state"] == "unreadable"
    got = reason(
        source_read.read_source, w, "alias", ".kookabug/review_token.txt", secrets=NO_SECRETS
    )
    assert got == ("policy_path", "device_path")
    got = reason(source_read.read_source, w, "alias2", "review_token.txt", secrets=NO_SECRETS)
    assert got == ("policy_path", "device_path")


def test_h2_trailing_dot_or_space_refused(ws: Path, tmp_path: Path) -> None:
    """검수 재현: `cert.pem.`·`.ssh./config`·`.git./config`·`cert.pem ` — Windows가 끝점·공백을 떼고
    여는 조각은 원본·읽기 허용 폴더 모두 거부 (직접 읽기·하위 목록·루트)."""
    tools = tmp_path / "tools"
    (tools / "cert.pem").write_text("pem-marker", "utf-8")
    for d in (".ssh", ".git"):
        (tools / d).mkdir()
        (tools / d / "config").write_text("config-marker", "utf-8")
    (tools / "plain").mkdir()
    (tools / "plain" / "a.txt").write_text("a", "utf-8")
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["sources"] = [
        *config["sources"],
        {"id": "tools_src", "kind": "other", "title": "도구", "path": str(tools)},
        {"id": "dotted", "kind": "other", "title": "끝점", "path": f"{tools}."},
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    w = Workspace.open(ws)
    for source in ("read:1", "tools_src"):
        for rel in ("cert.pem.", ".ssh./config", ".git./config", "cert.pem ", "plain./a.txt"):
            got = reason(source_read.read_source, w, source, rel, secrets=NO_SECRETS)
            assert got[0] == "policy_path", (source, rel)
            if source == "tools_src":
                assert got[1] == "odd_name", rel
        assert reason(source_read.list_source, w, source, "plain.")[0] == "policy_path"
        assert reason(source_read.list_source, w, source, ".ssh.")[0] == "policy_path"
    # 루트 경로: 원본·읽기 허용 폴더
    assert reason(source_read.list_source, w, "dotted") == ("policy_path", "odd_name")
    assert read_roots.refusal(w, f"{tools}.") == "odd_name"
    assert read_roots.refusal(w, f"{tools} ") == "odd_name"
    # 일반 철자는 그대로 읽힌다 (원본)
    assert source_read.read_source(w, "tools_src", "plain/a.txt", secrets=NO_SECRETS)["text"] == "a"


def test_h2_short_name_of_sensitive_file_refused(ws: Path, tmp_path: Path) -> None:
    """요청 글이 8.3 짧은 이름이어도 실제로 풀린 긴 이름으로 민감한 이름 검사를 한다."""
    tools = tmp_path / "tools"
    target = tools / "credentials_for_review.json"
    target.write_text("cred-marker", "utf-8")
    short = _short(target)
    if short is None:
        pytest.skip("이 볼륨은 8.3 짧은 이름을 만들지 않는다")
    name = Path(short).name
    assert not read_roots.sensitive([name])  # 요청 글만 보면 통과하는 이름
    w = Workspace.open(ws)
    got = reason(source_read.read_source, w, "read:1", name, secrets=NO_SECRETS)
    assert got == ("policy_path", "sensitive_name")


def test_m1_plain_source_listing_unchanged(ws: Path, tmp_path: Path) -> None:
    """일반 원본 목록은 UX2 그대로(민감한 이름도 보인다), `read:` 목록에서만 숨긴다."""
    tools = tmp_path / "tools"
    for rel in (".env", "cert.pem", "credentials.json", "normal.txt"):
        (tools / rel).write_text("x", "utf-8")
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["sources"] = [
        *config["sources"],
        {"id": "normal_source", "kind": "other", "title": "도구", "path": str(tools)},
    ]
    (ws / "kookabug.json").write_text(json.dumps(config, ensure_ascii=False), "utf-8")
    w = Workspace.open(ws)
    plain = [e["name"] for e in source_read.list_source(w, "normal_source")["entries"]]
    assert {".env", "cert.pem", "credentials.json", "normal.txt"} <= set(plain)
    hidden = [e["name"] for e in source_read.list_source(w, "read:1")["entries"]]
    assert ".env" not in hidden and "cert.pem" not in hidden and "normal.txt" in hidden
