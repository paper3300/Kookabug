"""`kookabug agent-host` 경계 (M5 B5 검수 2라운드 반례를 옮김, 이름 유지).

- Job을 만들거나 도우미를 그 Job에 넣지 못하면 에이전트를 띄우지 않는다(종료 코드 8)
- 비밀값은 `--workspace`의 워크스페이스로 찾는다
- `.cmd` 런처도 띄운다
- 에이전트가 받은 비밀값을 되돌려도(JSON 이스케이프·조각 경계 포함) 앱으로는 `***`만 간다
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from kb_testing.daemon import copy_sample_workspace
from kookabug_core.agents import host
from kookabug_core.win import Job
from kookabug_core.win.credentials import CredentialStore
from kookabug_core.workspace import secret_env_name

from .test_agent_host import wait_dead

pytestmark = [pytest.mark.process, pytest.mark.timeout(60)]

CREATE_NO_WINDOW = 0x08000000
REPO = Path(__file__).resolve().parents[3]

# Job 경계 한 곳만 실패시키는 독립 도우미 (실제 생성·연결·종료는 제품 경로)
HOST_WORKER = r"""
import argparse, subprocess, sys, time
from pathlib import Path
from kookabug_core.agents import host
from kookabug_core.win import Job

mode, workspace, infofile, gate, agent = sys.argv[1:]
while not Path(gate).exists():
    time.sleep(0.02)
if mode == "create_failure":
    def fail_create(cls, *args, **kwargs):
        raise OSError("검사: Job 생성 실패")
    Job.create = classmethod(fail_create)
elif mode == "assign_current_failure":
    def fail_current(self):
        raise OSError("검사: 현재 프로세스 Job 연결 실패")
    Job.assign_current = fail_current
    original_popen = subprocess.Popen
    def early_child(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        deadline = time.monotonic() + 10
        while not Path(infofile).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        return proc
    subprocess.Popen = early_child
args = argparse.Namespace(workspace=workspace, env=[], secret_env=[],
                          agent=[sys.executable, "-X", "utf8", agent, infofile])
raise SystemExit(host.run(args))
"""

# 자손을 바로 띄우고 기다리는 가짜 에이전트
TREE_AGENT = r"""
import json, os, subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
Path(sys.argv[1]).write_text(json.dumps({"agent": os.getpid(), "child": child.pid}),
                             encoding="utf-8")
sys.stdin.buffer.readline()
time.sleep(120)
"""

# 받은 비밀값을 그대로·JSON 이스케이프로·조각을 나눠·오류 글로 되돌리는 가짜 에이전트
ECHO_AGENT = r"""
import json, os, sys, time
value = os.environ["KBT_TOKEN"]
sys.stdin.buffer.readline()
out = sys.stdout.buffer
out.write((json.dumps({"text": value}) + "\n").encode())
line = json.dumps({"text": "앞 " + value + " 뒤"}, ensure_ascii=False).encode()
half = len(line) // 2
out.write(line[:half]); out.flush(); time.sleep(0.3)
out.write(line[half:] + b"\n")
out.write(("error: bad token " + value + "\n").encode())
out.flush()
"""


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_sample_workspace(tmp_path / "ws")


@pytest.mark.parametrize("mode", ["normal", "assign_current_failure", "create_failure"])
@pytest.mark.parametrize("end", ["agent", "helper"])
def test_job_failure_never_leaves_descendants(tmp_path: Path, mode: str, end: str) -> None:
    root = copy_sample_workspace(tmp_path / "ws")
    worker, agent = tmp_path / "worker.py", tmp_path / "tree_agent.py"
    worker.write_text(HOST_WORKER, encoding="utf-8")
    agent.write_text(TREE_AGENT, encoding="utf-8")
    infofile, gate = tmp_path / "pids.json", tmp_path / "go"
    safety = Job.create()  # 검사가 실패해도 남은 프로세스를 끝낸다
    argv = [sys.executable, "-X", "utf8", str(worker), mode, str(root)]
    proc = subprocess.Popen(
        [*argv, str(infofile), str(gate), str(agent)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        safety.assign(proc.pid)
        gate.touch()
        deadline = time.monotonic() + 15
        while not infofile.exists() and proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if mode != "normal":
            # 자손 정리를 보장하지 못하면 띄우지 않는다
            assert proc.wait(15) == host.EXIT_JOB
            assert proc.stderr is not None
            assert "Job" in proc.stderr.read().decode("utf-8")
            assert not infofile.exists()
            return
        info = json.loads(infofile.read_text(encoding="utf-8"))
        time.sleep(0.3)
        if end == "helper":
            proc.kill()
        else:
            kill = ["taskkill", "/pid", str(info["agent"]), "/F"]
            subprocess.run(kill, capture_output=True, check=False)
        proc.wait(15)
        wait_dead(info["agent"], info["child"])
    finally:
        safety.terminate()
        safety.close()
        proc.wait(10)


def test_secret_lookup_uses_requested_workspace_not_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = copy_sample_workspace(tmp_path / "a")
    b = copy_sample_workspace(tmp_path / "b")
    ids = ["11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"]
    for root, wid in zip([a, b], ids, strict=True):
        config = root / "kookabug.json"
        data = json.loads(config.read_text(encoding="utf-8-sig"))
        data["id"] = wid
        config.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.chdir(b)
    queried: list[tuple[str, str]] = []

    def fake_read(self: object, wid: str, key: str) -> str:
        queried.append((wid, key))
        return "FAKE-A-SECRET" if wid == ids[0] else "FAKE-B-SECRET"

    monkeypatch.setattr(CredentialStore, "read", fake_read)
    monkeypatch.delenv("KOOKABUG_SECRET_REVIEW_TOKEN", raising=False)

    class FakeJob:
        def assign_current(self) -> None:
            pass

        def close(self) -> None:
            pass

    def fake_create(*args: object, **kwargs: object) -> FakeJob:
        return FakeJob()

    monkeypatch.setattr(Job, "create", fake_create)
    captured: dict[str, object] = {}

    def spawn(*args: object, **kwargs: object) -> object:
        captured.update(kwargs)
        raise OSError("검사용 생성 중단")

    monkeypatch.setattr(subprocess, "Popen", spawn)
    err = io.StringIO()
    args = argparse.Namespace(
        workspace=str(a), env=[], secret_env=["REVIEW_TOKEN=review.token"], agent=[sys.executable]
    )
    assert host.run(args, stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=err) == host.EXIT_SETUP
    assert queried == [(ids[0], "review.token")]
    env = captured["env"]
    assert isinstance(env, dict) and env["REVIEW_TOKEN"] == "FAKE-A-SECRET"
    assert "FAKE-A-SECRET" not in err.getvalue()
    assert "FAKE-B-SECRET" not in str(captured)


@pytest.mark.timeout(30)
def test_fake_cmd_wrapper_still_accepts_acp(ws: Path, tmp_path: Path) -> None:
    wrapper = tmp_path / "fake-agent.cmd"
    fake = REPO / "tools" / "kb_testing" / "fake_acp_agent.py"
    wrapper.write_bytes(f'@echo off\r\n"{sys.executable}" -X utf8 "{fake}" %*\r\n'.encode())
    cli = [sys.executable, "-X", "utf8", "-m", "kookabug_cli", "agent-host"]
    proc = subprocess.Popen(
        [*cli, "--workspace", str(ws), "--", str(wrapper)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=CREATE_NO_WINDOW,
    )
    try:
        assert proc.stdin is not None and proc.stdout is not None
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": 1}}
        proc.stdin.write((json.dumps(init) + "\n").encode())
        proc.stdin.flush()
        response = proc.stdout.readline()
        assert response and json.loads(response)["result"]["protocolVersion"] == 1
    finally:
        proc.kill()
        proc.communicate(timeout=10)


def test_reflected_secret_is_scrubbed_before_app(ws: Path, tmp_path: Path) -> None:
    value = 'pa"ss\\wörd-0123'
    script = tmp_path / "echo.py"
    script.write_text(ECHO_AGENT, encoding="utf-8")
    cli = [sys.executable, "-m", "kookabug_cli", "agent-host", "--workspace", str(ws)]
    proc = subprocess.Popen(
        [*cli, "--secret-env", "KBT_TOKEN=agent.token", "--", sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, secret_env_name("agent.token"): value},
    )
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(b"go\n")
    proc.stdin.flush()
    lines = [proc.stdout.readline() for _ in range(3)]
    proc.kill()
    _, err = proc.communicate(timeout=10)
    text = b"".join(lines).decode("utf-8")
    for form in (value, json.dumps(value)[1:-1], json.dumps(value, ensure_ascii=False)[1:-1]):
        assert form not in text
    assert json.loads(lines[0]) == {"text": "***"}
    assert json.loads(lines[1]) == {"text": "앞 *** 뒤"}
    assert lines[2] == b"error: bad token ***\n"
    assert value.encode() not in err
