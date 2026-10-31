"""`kookabug daemon` (M2 계획 2.3)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from kb_testing.daemon import DaemonProcess, daemon_env, make_workspace
from kb_testing.proc import Spawned
from kookabug_cli.main import build_parser, main
from kookabug_daemon import session as sess
from kookabug_daemon.client import DaemonClient


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return make_workspace(tmp_path / "ws")


def shutdown(root: Path) -> None:
    info = sess.read_session(root)
    assert info is not None
    with DaemonClient.from_session(info) as client:
        client.call("daemon.shutdown", {})


def test_parser_has_daemon_command() -> None:
    args = build_parser().parse_args(["daemon", "--workspace", "w", "--idle-timeout-s", "30"])
    assert (args.command, args.workspace, args.idle_timeout_s, args.json) == (
        "daemon",
        "w",
        30.0,
        False,
    )
    assert args.platform_fake is None and args.session_wait_s == 15.0
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(["daemon", "--idle-timeout-s", "0"])
    assert caught.value.code == 6


@pytest.mark.process
def test_daemon_json_output_session(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    proc = DaemonProcess.start(spawned, root, tmp_path / "d", env=daemon_env(tmp_path))
    line = proc.first_line()
    assert line["status"] == "started", proc.output()
    info = sess.read_session(root)
    assert info is not None and line["session"] == info.public()
    assert "token" not in line["session"] and info.token not in proc.stdout()
    assert Path(line["log"]).is_file()
    shutdown(root)
    assert proc.wait() == 0
    assert proc.stdout().count("\n") == 1  # 출력은 시작 한 줄뿐


@pytest.mark.process
def test_already_running_exit_0(root: Path, tmp_path: Path, spawned: Spawned) -> None:
    env = daemon_env(tmp_path)
    first = DaemonProcess.start(spawned, root, tmp_path / "d1", env=env)
    started = first.first_line()
    assert started["status"] == "started", first.output()

    again = DaemonProcess.start(spawned, root, tmp_path / "d2", env=env)
    assert again.wait() == 0, again.output()
    line = again.first_line()
    assert line == {"status": "already_running", "session": started["session"]}

    text = DaemonProcess.start(spawned, root, tmp_path / "d3", env=env, json_output=False)
    assert text.wait() == 0, text.output()
    assert f"이미 실행 중이다: PID {first.pid}" in text.stdout()

    shutdown(root)
    assert first.wait() == 0


def test_not_a_workspace_exit_6(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["daemon", "--workspace", str(tmp_path), "--json"]) == 6
    assert "kookabug.json" in capsys.readouterr().err


def test_platform_fake_must_be_json_object(root: Path, tmp_path: Path) -> None:
    from kookabug_daemon import app

    bad = tmp_path / "fake.json"
    bad.write_text("[]", encoding="utf-8")
    args = build_parser().parse_args(
        ["daemon", "--workspace", str(root), "--platform-fake", str(bad)]
    )
    with pytest.raises(app.UsageError):
        app.config_from_args(args)
    bad.write_text(json.dumps({"frames": []}), encoding="utf-8")
    assert app.config_from_args(args).platform_fake == bad.resolve()


def test_cli_parser_does_not_import_daemon_runtime() -> None:
    # 파서만 만들 때는 websockets·asyncio daemon을 불러오지 않는다 (`kookabug run` 시작을 가볍게)
    code = (
        "import sys\n"
        "from kookabug_cli.main import build_parser\n"
        "build_parser()\n"
        "heavy = ('websockets', 'kookabug_daemon.app')\n"
        "print(sorted(m for m in sys.modules if m.startswith(heavy)))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, timeout=60
    )
    assert out.stdout.strip() == "[]"
