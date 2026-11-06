"""`kookabug agent-host` (M5 B5 검수 H1·M2): 패널 에이전트와 자손을 한 Job으로 묶어 띄우는 도우미.

에이전트가 스스로 끝나거나·죽거나, 앱이 도우미를 끝내거나, 입력이 닫히면 에이전트와 손자까지 끝난다.
에이전트 환경은 `KOOKABUG_*`가 없고, `--secret-env`는 실행 직전에 비밀값 제공자에서 찾는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kb_testing.daemon import copy_sample_workspace
from kookabug_core.workspace import secret_env_name

pytestmark = [pytest.mark.process, pytest.mark.timeout(60)]

# 가짜 에이전트: 잠자는 손자를 띄워 PID를 쓰고, 환경 일부를 쓰고, 첫 줄을 되돌려 준 뒤 각본대로
AGENT = r"""
import json, os, subprocess, sys, time
out = sys.argv[1]
mode = sys.argv[2]
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
env = {k: v for k, v in os.environ.items()
       if k.upper().startswith("KOOKABUG_") or k.startswith("KBT_")}
with open(out, "w", encoding="utf-8") as f:
    json.dump({"pid": os.getpid(), "child": child.pid, "env": env, "cwd": os.getcwd()}, f)
line = sys.stdin.readline()
sys.stdout.buffer.write(("echo:" + line.strip() + chr(10)).encode())
sys.stdout.buffer.flush()
if mode == "exit":
    sys.exit(3)
time.sleep(120)
"""


def alive(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000 | 0x00100000, False, pid)
    if not handle:
        return False
    try:
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259  # STILL_ACTIVE
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def wait_dead(*pids: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while any(alive(p) for p in pids):
        assert time.monotonic() < deadline, f"끝나지 않았다: {[p for p in pids if alive(p)]}"
        time.sleep(0.05)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


def start(
    ws: Path,
    tmp_path: Path,
    mode: str,
    extra: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> tuple[subprocess.Popen[bytes], Path]:
    script = tmp_path / "agent.py"
    script.write_text(AGENT, encoding="utf-8")
    out = tmp_path / "agent.json"
    base = {**os.environ, "KOOKABUG_SESSION_TOKEN": "t0p", **(env or {})}
    proc = subprocess.Popen(
        [sys.executable, "-m", "kookabug_cli", "agent-host", "--workspace", str(ws), *(extra or []),
         "--", sys.executable, str(script), str(out), mode],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=base,
    )  # fmt: skip
    return proc, out


def started(proc: subprocess.Popen[bytes], out: Path) -> dict[str, object]:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(b"hello\n")
    proc.stdin.flush()
    assert proc.stdout.readline() == b"echo:hello\n"
    return json.loads(out.read_text(encoding="utf-8"))


def test_natural_exit_ends_descendants_and_relays_code(ws: Path, tmp_path: Path) -> None:
    proc, out = start(ws, tmp_path, "exit")
    info = started(proc, out)
    assert proc.wait(20) == 3
    wait_dead(int(info["pid"]), int(info["child"]))  # pyright: ignore[reportArgumentType]


def test_agent_crash_ends_helper_and_descendants(ws: Path, tmp_path: Path) -> None:
    proc, out = start(ws, tmp_path, "sleep")
    info = started(proc, out)
    subprocess.run(["taskkill", "/pid", str(info["pid"]), "/F"], capture_output=True, check=False)
    proc.wait(20)
    wait_dead(int(info["child"]))  # pyright: ignore[reportArgumentType]


def test_helper_killed_ends_descendants(ws: Path, tmp_path: Path) -> None:
    """앱이 도우미 프로세스만 끝내도(TerminateProcess) Job 핸들이 닫혀 에이전트·손자가 끝난다."""
    proc, out = start(ws, tmp_path, "sleep")
    info = started(proc, out)
    proc.kill()
    proc.wait(10)
    wait_dead(int(info["pid"]), int(info["child"]))  # pyright: ignore[reportArgumentType]


def test_input_closed_ends_descendants(ws: Path, tmp_path: Path) -> None:
    """앱이 죽어 입력이 닫히면 도우미가 Job을 끝낸다."""
    proc, out = start(ws, tmp_path, "sleep")
    info = started(proc, out)
    assert proc.stdin is not None
    proc.stdin.close()
    proc.wait(20)
    wait_dead(int(info["pid"]), int(info["child"]))  # pyright: ignore[reportArgumentType]


def test_env_strips_kookabug_and_resolves_secret(ws: Path, tmp_path: Path) -> None:
    secret = {secret_env_name("agent.token"): "s3cr3t-value"}
    proc, out = start(
        ws,
        tmp_path,
        "exit",
        [
            *("--env", "KBT_PLAIN=plain"),
            *("--secret-env", "KBT_TOKEN=agent.token"),
            *("--env", "KOOKABUG_X=no"),
        ],
        secret,
    )
    info = started(proc, out)
    assert proc.wait(20) == 3
    assert info["env"] == {"KBT_PLAIN": "plain", "KBT_TOKEN": "s3cr3t-value"}
    assert Path(str(info["cwd"])).resolve() == ws.resolve()
    assert proc.stderr is not None
    assert b"s3cr3t" not in proc.stderr.read()


def test_missing_secret_fails_before_start(ws: Path, tmp_path: Path) -> None:
    proc, out = start(ws, tmp_path, "exit", ["--secret-env", "KBT_TOKEN=agent.nope"])
    _, err = proc.communicate(timeout=20)
    assert proc.returncode == 7
    text = err.decode("utf-8")
    assert "KBT_TOKEN" in text and "agent.nope" in text
    assert not out.exists()  # 에이전트를 띄우지 않았다
