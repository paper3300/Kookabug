"""원천 받기 경계 (M6 계획 3.5a — 엄격: 승인 전 코드 실행 없음·인증 정보).

- git은 사용자 git 설정(훅·필터 드라이버)을 쓰지 않는다: 이 PC 전역 설정은 건드리지 않고, 검사용
  임시 HOME·`GIT_CONFIG_GLOBAL`에 악성 설정을 두어 확인한다
- 허용 안 된 전송·위험한 ref는 아무 명령도 돌기 전에 `source_refused`
- 인증 정보(URL 사용자 정보·비밀 쿼리)는 잠금·작업 로그·응답에 없다
- 신뢰 확인 전(미리보기·취소)에는 빌드 백엔드·플러그인 import가 돌지 않는다 (`build_marker`)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import io
import json
import shutil
import subprocess
import sys
import urllib.request
from email.message import Message
from pathlib import Path
from typing import cast
from urllib.response import addinfourl

import pytest
from helpers.plugins import YES, Rig, git_source, plugin_cli

from kb_testing.plugin_fixtures import PLUGINS, SAMPLE, git_env, git_repo, plugin_wheel
from kookabug_cli import plugin_cmd
from kookabug_core.plugins import PluginError
from kookabug_core.plugins.sources import fetch, parse_source, strip_credentials
from kookabug_core.plugins.sources import git_env as source_git_env
from kookabug_core.plugins.uv import ProcessRunner

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(600)]

SECRET = "kbsecret-token-77"


def _hostile_git_config(home: Path, marks: Path) -> dict[str, str]:
    """훅(post-checkout)·필터 드라이버(smudge)가 표식을 쓰는 전역 git 설정 (검사 전용 HOME)."""
    env = git_env(home)
    hooks = home / "hooks"
    hooks.mkdir(parents=True)
    hook_mark = (marks / "hook").as_posix()
    filter_mark = (marks / "filter").as_posix()
    (hooks / "post-checkout").write_text(f"#!/bin/sh\necho ran > '{hook_mark}'\n", newline="\n")
    Path(env["GIT_CONFIG_GLOBAL"]).write_text(
        "[core]\n"
        f"\thooksPath = {hooks.as_posix()}\n"
        '[filter "kbmark"]\n'
        f"\tsmudge = \"sh -c 'echo ran > {filter_mark}; cat'\"\n"
        "\trequired = true\n",
        encoding="utf-8",
    )
    return env


def test_git_isolation_hooks_filters_not_run(rig: Rig, tmp_path: Path) -> None:
    marks = tmp_path / "marks"
    marks.mkdir()
    repo = git_repo(
        SAMPLE, tmp_path / "repos" / "sample", extra={".gitattributes": b"*.py filter=kbmark\n"}
    )
    hostile = _hostile_git_config(tmp_path / "home", marks)
    # 대조군: 같은 설정의 평범한 git clone은 훅·필터를 돌린다 (검사가 의미 있음)
    control = subprocess.run(
        ["git", "clone", "--quiet", repo.as_uri(), str(tmp_path / "control")],
        env=hostile,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    assert control.returncode == 0, control.stderr
    assert {p.name for p in marks.iterdir()} == {"hook", "filter"}
    for p in marks.iterdir():
        p.unlink()
    # 같은 사용자 환경(HOME·GIT_CONFIG_GLOBAL)에서 플러그인 설치: 미리보기 → 취소, 그다음 승인·설치
    environ = {**rig.world.environ, **{k: hostile[k] for k in ("HOME", "USERPROFILE")}}
    environ["GIT_CONFIG_GLOBAL"] = hostile["GIT_CONFIG_GLOBAL"]
    ops = rig.ops()
    ops.environ = environ
    with pytest.raises(PluginError) as caught:
        ops.add(git_source(repo), confirm=lambda _: False)
    assert caught.value.code == "cancelled"
    assert not any(marks.iterdir())
    ops = rig.ops()
    ops.environ = environ
    result = ops.add(git_source(repo), confirm=YES)
    assert result["plugin"]["source"]["kind"] == "git"
    assert not any(marks.iterdir())  # 훅·필터 드라이버는 한 번도 돌지 않았다
    # git 명령은 전역·시스템 설정 없이 돌았다
    git_calls = [c for c in ops.calls if Path(c[0]).stem.lower() == "git"]
    assert git_calls
    for call in git_calls:
        assert "protocol.allow=never" in call
        assert any(a.startswith("core.hooksPath=") for a in call)


@pytest.mark.parametrize(
    ("source", "ref"),
    [
        ("git+ext::sh -c touch% /tmp/x", None),
        ("git+fd::17", None),
        ("git+git://example.invalid/repo.git", None),
        ("git+http://example.invalid/repo.git", None),
        ("git+ftp://example.invalid/repo.git", None),
        ("git+-oProxyCommand=calc", None),
        ("git+relative/path", None),
        ("git+https://example.invalid/repo.git", "--upload-pack=touch x"),
        ("git+https://example.invalid/repo.git", "-x"),
        ("git+https://example.invalid/repo.git", "a..b"),
        ("git+https://example.invalid/repo.git@v1 rm", None),
        ("git+ssh://git@example.invalid/repo.git", None),  # ssh는 MVP 뒤 (U14)
        ("git+git@example.invalid:team/repo.git@v1", None),
        ("git+SSH://example.invalid/repo.git", None),
        ("http://example.invalid/kbfix-0.1.0-py3-none-any.whl", None),
        ("https://example.invalid/kbfix-0.1.0-py3-none-any.whl", None),  # sha256 없음
        ("https://example.invalid/kbfix-0.1.0.tar.gz", None),
    ],
)
def test_refused_transports_and_refs(rig: Rig, source: str, ref: str | None) -> None:
    ops = rig.ops()
    with pytest.raises(PluginError) as caught:
        ops.add(source, ref=ref, confirm=YES)
    assert caught.value.code == "source_refused", caught.value.message
    assert ops.calls == []  # 어떤 자식 명령도 돌지 않았다
    assert rig.lock_bytes() is None


def test_ref_parsing_keeps_userinfo_and_paths() -> None:
    spec = parse_source(f"git+https://kb:{SECRET}@example.invalid/a/repo.git@release/1.0")
    assert (spec.location, spec.ref) == (
        f"https://kb:{SECRET}@example.invalid/a/repo.git",
        "release/1.0",
    )
    spec = parse_source("git+file:///C:/repos/a@b/repo@v2")
    assert (spec.location, spec.ref) == ("file:///C:/repos/a@b/repo", "v2")
    assert strip_credentials(f"https://kb:{SECRET}@example.invalid/r.git") == (
        "https://example.invalid/r.git"
    )
    assert strip_credentials(f"ssh://git:{SECRET}@example.invalid/r") == (
        "ssh://git@example.invalid/r"
    )
    assert SECRET not in strip_credentials(f"https://example.invalid/a.whl?token={SECRET}&x=1")


def _all_text(rig: Rig) -> str:
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in _logs(rig)]
    if rig.lock_bytes() is not None:
        texts.append(rig.lock_bytes().decode("utf-8"))  # pyright: ignore[reportOptionalMemberAccess]
    return "\n".join(texts)


def _logs(rig: Rig) -> list[Path]:
    folder = rig.root / ".kookabug" / "plugins" / "logs"
    return sorted(folder.glob("*.log")) if folder.is_dir() else []


def test_credentials_not_in_lock_or_log(rig: Rig) -> None:
    # 인덱스 URL에 사용자 정보: 받기에는 쓰고(uv가 basic auth로 보냄) 잠금·로그에는 가린 값
    index = rig.world.index.url.replace("http://", f"http://kb:{SECRET}@")
    config = json.loads((rig.root / "kookabug.json").read_text(encoding="utf-8"))
    config["plugin_index"] = {"url": index}
    (rig.root / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    result = rig.add("conflict_a")
    assert SECRET not in json.dumps(result)
    assert rig.lock()["index"] == rig.world.index.url.replace("http://", "http://***@")
    # git·https wheel 원천의 인증 정보: 받기 실패 메시지·응답·로그·잠금 어디에도 없다
    lock_before = rig.lock_bytes()
    failing = [
        (f"git+https://kb:{SECRET}@127.0.0.1:9/team/repo.git@v1", None),
        (f"https://kb:{SECRET}@127.0.0.1:9/kbfix-0.1.0-py3-none-any.whl?token={SECRET}", "0" * 64),
    ]
    for source, sha in failing:
        with pytest.raises(PluginError) as caught:
            rig.ops().add(source, sha256=sha, confirm=YES)
        assert caught.value.code == "source_unavailable", caught.value.message
        assert SECRET not in json.dumps(caught.value.to_json(), ensure_ascii=False)
    assert rig.lock_bytes() == lock_before
    # CLI 응답(--json)·오류 출력에도 없다
    proc = plugin_cli(rig, "add", failing[0][0], "--yes", "--json")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert SECRET not in proc.stdout + proc.stderr
    assert _logs(rig)
    assert SECRET not in _all_text(rig)


def test_preview_cancel_runs_no_code(rig: Rig, tmp_path: Path) -> None:
    marks = tmp_path / "marks"
    marks.mkdir()
    repo = git_repo(PLUGINS / "build_marker", tmp_path / "repos" / "build_marker")
    environ = {**rig.world.environ, "KBFIX_MARKER_DIR": str(marks)}
    for source in (git_source(repo), str(repo)):  # git·폴더 원천
        ops = rig.ops()
        ops.environ = environ
        previews: list[dict[str, object]] = []

        def cancel(preview: object, previews: list[dict[str, object]] = previews) -> bool:
            previews.append(preview.to_json())  # pyright: ignore[reportAttributeAccessIssue]
            return False

        with pytest.raises(PluginError) as caught:
            ops.add(source, confirm=cancel)
        assert caught.value.code == "cancelled"
        assert [p["id"] for p in previews] == ["build_marker"]
        assert not any(marks.iterdir())
        # 미리보기까지는 git(받기)만 돌았다 — uv·빌드·인터프리터 없음
        assert all(Path(c[0]).stem.lower() == "git" for c in ops.calls), ops.calls
    assert rig.lock_bytes() is None
    # 승인한 뒤에만 빌드 백엔드·import가 돈다
    ops = rig.ops()
    ops.environ = environ
    ops.add(git_source(repo), confirm=YES)
    assert {p.name for p in marks.iterdir()} == {"backend", "import"}
    assert [p["id"] for p in rig.lock()["plugins"]] == ["build_marker"]


# ------------------------------------------------------------------ 2라운드 회귀 (review_B2_1)


def test_ssh_command_in_environment_never_runs(rig: Rig, tmp_path: Path) -> None:
    """`GIT_SSH_COMMAND`가 있어도 ssh 원천은 아무 명령 전에 거부 (신뢰 확인 콜백도 안 부름)."""
    marker = tmp_path / "ssh-ran.txt"
    script = tmp_path / "ssh_probe.py"
    script.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\nraise SystemExit(1)\n",
        encoding="utf-8",
    )
    ops = rig.ops()
    command = f'"{sys.executable}" -X utf8 "{script}"'
    ops.environ = {**ops.environ, "GIT_SSH_COMMAND": command, "GIT_SSH": str(script)}
    asked: list[object] = []
    for source in ("git+ssh://git@example.invalid/repo", "git+git@example.invalid:repo.git"):
        with pytest.raises(PluginError) as caught:
            ops.add(source, confirm=lambda p: asked.append(p) or False)
        assert caught.value.code == "source_refused"
        assert "https" in caught.value.message
    assert asked == [] and ops.calls == []
    assert not marker.exists()


def test_git_env_is_allowlist(tmp_path: Path) -> None:
    environ = {
        "PATH": "C:\\bin",
        "SystemRoot": "C:\\Windows",
        "HTTPS_PROXY": "http://proxy.invalid:8080",
        "GIT_SSL_CAINFO": "C:\\ca.pem",
        "GIT_SSH_COMMAND": "evil",
        "GIT_SSH": "evil",
        "GIT_SSH_VARIANT": "ssh",
        "GIT_PROXY_COMMAND": "evil",
        "GIT_ASKPASS": "evil",
        "SSH_ASKPASS": "evil",
        "GIT_EXEC_PATH": "C:\\evil",
        "GIT_CONFIG_PARAMETERS": "'core.sshCommand=evil'",
        "XDG_CONFIG_HOME": "C:\\evil",
        "HOME": "C:\\Users\\someone",
        "PYTHONPATH": "C:\\evil",
    }
    env = source_git_env(environ, tmp_path)
    assert set(env) == {
        "PATH",
        "SystemRoot",
        "HTTPS_PROXY",
        "GIT_SSL_CAINFO",
        "HOME",
        "USERPROFILE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_CONFIG_GLOBAL",
        "GIT_TERMINAL_PROMPT",
        "GCM_INTERACTIVE",
    }
    assert env["HOME"] == env["USERPROFILE"] == str(tmp_path)


class _FakeTransport(urllib.request.BaseHandler):
    """네트워크 없는 https·http 전송 (요청 기록). 첫 https 응답은 `location`으로 넘긴다."""

    handler_order = 100

    def __init__(self, location: str, body: bytes) -> None:
        self.location = location
        self.body = body
        self.seen: list[tuple[str, str | None]] = []

    def _answer(self, req: urllib.request.Request) -> addinfourl:
        self.seen.append((req.full_url, req.get_header("Authorization")))
        headers = Message()
        if len(self.seen) == 1:
            headers["Location"] = self.location
            response = addinfourl(io.BytesIO(b""), headers, req.full_url, 302)
            msg = "Found"
        else:
            response = addinfourl(io.BytesIO(self.body), headers, req.full_url, 200)
            msg = "OK"
        setattr(response, "msg", msg)  # noqa: B010  # 오류 처리기가 읽는 상태 문구
        return response

    def https_open(self, req: urllib.request.Request) -> addinfourl:
        return self._answer(req)

    def http_open(self, req: urllib.request.Request) -> addinfourl:
        return self._answer(req)


def _fake_urlopen(monkeypatch: pytest.MonkeyPatch, transport: _FakeTransport) -> None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), transport)
    monkeypatch.setattr(urllib.request, "urlopen", opener.open)


def test_wheel_redirect_to_http_refused_before_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = _FakeTransport(f"http://example.invalid/p.whl?token={SECRET}", b"wheel")
    _fake_urlopen(monkeypatch, transport)
    spec = parse_source(f"https://example.invalid/p.whl?token={SECRET}", sha256="0" * 64)
    with pytest.raises(PluginError) as caught:
        fetch(spec, tmp_path / "a", _no_runner(), root=tmp_path)
    assert caught.value.code == "source_refused"
    assert SECRET not in caught.value.message
    assert [url for url, _ in transport.seen] == [f"https://example.invalid/p.whl?token={SECRET}"]


def test_wheel_https_redirect_drops_basic_auth_and_checks_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"fake-wheel-bytes"
    transport = _FakeTransport("https://second.invalid/p.whl", body)
    _fake_urlopen(monkeypatch, transport)
    spec = parse_source(
        f"https://kb:{SECRET}@first.invalid/p.whl", sha256=hashlib.sha256(body).hexdigest()
    )
    result = fetch(spec, tmp_path / "a", _no_runner(), root=tmp_path)
    assert result.wheel is not None and result.wheel.read_bytes() == body
    token = base64.b64encode(f"kb:{SECRET}".encode()).decode()
    assert transport.seen == [
        ("https://first.invalid/p.whl", f"Basic {token}"),
        ("https://second.invalid/p.whl", None),  # 넘겨주기에는 인증 헤더 없음
    ]
    assert result.source == {
        "kind": "wheel",
        "url": "https://first.invalid/p.whl",
        "sha256": spec.sha256,
    }
    transport = _FakeTransport("https://second.invalid/p.whl", body + b"x")
    _fake_urlopen(monkeypatch, transport)
    with pytest.raises(PluginError) as caught:
        fetch(spec, tmp_path / "b", _no_runner(), root=tmp_path)
    assert caught.value.code == "source_unavailable"


def _no_runner() -> ProcessRunner:
    """wheel URL 받기는 자식 명령을 쓰지 않는다 (부르면 실패하는 실행기)."""
    return cast(ProcessRunner, object())


# ------------------------------------------------------------------ 3라운드 회귀 (review_B2_2)

_SECRET_DEP = (
    f"kbfix-secret-dep @ https://kb:{SECRET}@example.invalid/"
    f"kbfix_secret_dep-1-py3-none-any.whl?token={SECRET}"
)


def _with_dependency(kind: str, requirement: str, tmp_path: Path) -> Path:
    if kind == "wheel":
        return plugin_wheel(
            SAMPLE,
            tmp_path / "wheel",
            pyproject_edit=lambda d: d["project"]["dependencies"].append(requirement),
        )
    project = tmp_path / "project"
    shutil.copytree(SAMPLE, project)
    config = project / "pyproject.toml"
    text = config.read_text(encoding="utf-8")
    config.write_text(
        text.replace("dependencies = [", f"dependencies = [{json.dumps(requirement)}, "),
        encoding="utf-8",
    )
    return project


@pytest.mark.parametrize(
    ("kind", "requirement"),
    [
        ("path", _SECRET_DEP),
        ("wheel", _SECRET_DEP),
        ("path", _SECRET_DEP.replace(" @ ", " @@ ")),  # 읽을 수 없는 요구 (파서 예외 경로)
    ],
)
def test_dependency_refusal_hides_credentials(
    rig: Rig, tmp_path: Path, kind: str, requirement: str
) -> None:
    source = _with_dependency(kind, requirement, tmp_path)
    ops = rig.ops()
    asked: list[object] = []
    with pytest.raises(PluginError) as caught:
        ops.add(str(source), confirm=lambda p: asked.append(p) or True)
    error = caught.value
    assert error.code == "manifest_invalid"
    assert asked == [] and ops.calls == []  # 승인 전 미실행 그대로
    assert "kbfix-secret-dep" in error.message  # 이름과 이유는 보인다
    texts = [str(error), error.message, json.dumps(error.to_json(), ensure_ascii=False)]
    # CLI JSON과 일반 오류 출력
    as_json = plugin_cli(rig, "add", source, "--yes", "--json")
    plain = plugin_cli(rig, "add", source, "--yes")
    for proc in (as_json, plain):
        assert proc.returncode == 2, proc.stdout + proc.stderr
        texts += [proc.stdout, proc.stderr]
    assert json.loads(as_json.stdout)["error"]["code"] == "manifest_invalid"
    assert "manifest_invalid" in plain.stderr
    for text in texts:
        assert SECRET not in text
    assert rig.lock_bytes() is None


def test_plugin_error_masks_message_and_fields() -> None:
    """경계 하나: 메시지·필드에 넣은 URL 인증 정보·비밀 쿼리는 만들 때 가려진다."""
    url = f"https://kb:{SECRET}@example.invalid/a.whl?token={SECRET}&x=1"
    error = PluginError(
        "source_unavailable", f"{url} 실패", stage="fetch", detail={"urls": [url]}, raw=url
    )
    assert SECRET not in str(error) + error.message + json.dumps(error.to_json())
    assert error.to_json()["detail"] == {
        "urls": ["https://***@example.invalid/a.whl?token=***&x=1"]
    }


# ------------------------------------------------------------ 4라운드 회귀 (review_B2_3 별도 발견)

_BAD_URLS = [
    f"https://example.invalid/bad name.whl?token={SECRET}",  # 공백
    f"https://example.invalid/bad\x01.whl?token={SECRET}",  # 제어 문자
    f"https://example.invalid/bad%zz.whl?token={SECRET}",  # 잘못된 퍼센트 인코딩
    f"https://example.invalid/한글.whl?token={SECRET}",  # 인코딩 안 한 비ASCII
    f"https://kb:{SECRET}@example.invalid:99999/p.whl",  # 포트
    f"https://kb:{SECRET}@/p.whl",  # 호스트 없음
]


@pytest.mark.parametrize("url", _BAD_URLS)
def test_malformed_https_wheel_url_refused_before_request(url: str) -> None:
    with pytest.raises(PluginError) as caught:
        parse_source(url, sha256="0" * 64)
    assert caught.value.code == "source_refused"
    assert SECRET not in str(caught.value) + json.dumps(caught.value.to_json())


@pytest.mark.parametrize(
    "error",
    [
        http.client.InvalidURL(f"URL can't contain control characters. '/p.whl?token={SECRET}'"),
        http.client.RemoteDisconnected(f"closed https://kb:{SECRET}@example.invalid/p.whl"),
        RuntimeError(f"https://example.invalid/p.whl?token={SECRET}"),
    ],
)
def test_wheel_fetch_wraps_any_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def broken(*args: object, **kwargs: object) -> object:
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", broken)
    spec = parse_source(f"https://example.invalid/p.whl?token={SECRET}", sha256="0" * 64)
    with pytest.raises(PluginError) as caught:
        fetch(spec, tmp_path / "a", _no_runner(), root=tmp_path)
    assert caught.value.code == "source_unavailable"
    assert type(error).__name__ in caught.value.message
    assert caught.value.__cause__ is None and caught.value.__suppress_context__
    assert SECRET not in str(caught.value) + json.dumps(caught.value.to_json())


def _run_cli(rig: Rig, **overrides: object) -> tuple[int, str, str]:
    args = argparse.Namespace(
        action="add",
        source=f"https://example.invalid/bad name.whl?token={SECRET}",
        workspace=str(rig.root),
        json=True,
        yes=True,
        isolation=None,
        sha256="0" * 64,
        ref=None,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    out, err = io.StringIO(), io.StringIO()
    code = plugin_cmd.run(args, out=out, err=err, stdin=io.StringIO())
    return code, out.getvalue(), err.getvalue()


def test_cli_invalid_url_refused_without_secret(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """검수자 관찰(`InvalidURL`이 CLI 밖으로 원문 그대로 나감)의 역단언: 연결 없이 거부, 비밀
    없음."""
    connections: list[bool] = []

    def blocked(*args: object, **kwargs: object) -> None:
        connections.append(True)
        pytest.fail("네트워크에 연결하면 안 된다")

    monkeypatch.setattr(http.client.HTTPSConnection, "connect", blocked)
    monkeypatch.setattr(http.client.HTTPConnection, "connect", blocked)
    code, out, err = _run_cli(rig)
    assert code == 2 and not connections
    assert json.loads(out)["error"]["code"] in ("source_refused", "source_unavailable")
    assert SECRET not in out + err
    # 하위 프로세스 CLI: --json·일반 출력의 stdout·stderr 모두
    for extra in (("--json",), ()):
        proc = plugin_cli(rig, "add", _BAD_URLS[0], "--sha256", "0" * 64, "--yes", *extra)
        assert proc.returncode == 2, proc.stdout + proc.stderr
        assert SECRET not in proc.stdout + proc.stderr
        assert "Traceback" not in proc.stderr


def test_cli_unexpected_exception_is_masked(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """`PluginError`가 아닌 예외(하위 프로세스·예상 밖)도 최상위 경계에서 가린 문구로 종료 2."""
    from kookabug_core.plugins import PluginOps

    def boom(self: object, *args: object, **kwargs: object) -> object:
        raise OSError(f"git 실패: https://kb:{SECRET}@example.invalid/r.git?token={SECRET}")

    monkeypatch.setattr(PluginOps, "add", boom)
    code, out, err = _run_cli(rig, source="git+https://example.invalid/r.git")
    body = json.loads(out)
    assert code == 2 and body["error"]["code"] == "unexpected_error"
    assert "OSError" in body["error"]["message"]
    assert SECRET not in out + err and "Traceback" not in err
    monkeypatch.setenv(plugin_cmd.DEBUG_ENV, "1")
    code, out, err = _run_cli(rig, source="git+https://example.invalid/r.git", json=False)
    assert code == 2 and "Traceback" in err  # 디버그: 가린 traceback
    assert SECRET not in out + err
