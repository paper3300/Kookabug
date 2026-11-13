"""작업 토큰 연결 (M8 계획 3.9·3.14, 9장 R0·R7) — 엄격: Agent 권한.

토큰 = {워크스페이스, 작업 ID, 주체 Agent, 허용 범위, 만료}. 틀린·만료·폐기된·다른 작업의 토큰은
연결을 거부하고, 살아 있는 토큰은 주체에 작업을 붙인다(자기 신고가 아니다).
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_daemon.client import DaemonClient, DaemonError

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

PERMISSION_CODES = {"permission_denied", "approval_required", "toolset_disabled"}


def agent(agent_id: str, *, token: str | None = None, attended: bool = False) -> dict[str, Any]:
    info: dict[str, Any] = {
        "kind": "agent",
        "name": "mcp",
        "version": "0",
        "id": agent_id,
        "attended": attended,
    }
    if token is not None:
        info["job_token"] = token
    return info


def set_permissions(ws: Path, permissions: dict[str, Any]) -> None:
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))  # 게임 실행 설정은 그대로 두고 권한만 바꾼다
    body["permissions"] = permissions
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    root = copy_example_workspace(tmp_path)
    set_permissions(root, {"preset": "curator"})
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def begin(d: ThreadDaemon, **params: Any) -> dict[str, Any]:
    # 소유 연결은 열어 둔다 (R8: 끊기면 작업이 끝나 토큰이 폐기된다)
    return d.begin_job({"playbook": "triage", **params})


def refused_hello(d: ThreadDaemon, info: dict[str, Any]) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        DaemonClient.connect(d.port, d.session.token, client=info)
    return caught.value


def test_invalid_token_refused(daemon: ThreadDaemon) -> None:
    # 워크스페이스당 끝나지 않은 작업은 하나다 (R8) — 작업 A를 끝낸 뒤 B를 만든다
    old = begin(daemon)
    with daemon.client() as ui:
        ui.call("job.end", {"job": old["job"], "reason": "cancelled"}, timeout=300)
    job = begin(daemon)
    # 모르는 토큰, 다른 작업의 주체 ID(살아 있는 작업 B의 토큰을 작업 A 주체로), 형식이 틀린 토큰
    assert refused_hello(daemon, agent(job["agent_id"], token="x" * 43)).kind == "job_token_invalid"
    assert refused_hello(daemon, agent(old["agent_id"], token=job["token"])).kind == (
        "job_token_invalid"
    )
    assert refused_hello(daemon, agent("mcp:1", token=job["token"])).kind == "job_token_invalid"
    # 형식이 틀린 토큰·ui 연결의 토큰은 계약 형식 오류 (클라이언트도 같은 스키마로 막는다)
    with pytest.raises((DaemonError, ValueError)):
        DaemonClient.connect(daemon.port, daemon.session.token, client=agent("a", token="short"))
    with pytest.raises((DaemonError, ValueError)):
        DaemonClient.connect(
            daemon.port,
            daemon.session.token,
            client={"kind": "ui", "name": "app", "version": "0", "job_token": job["token"]},
        )


def test_expired_token_refused(daemon: ThreadDaemon) -> None:
    job = begin(daemon, ttl_s=1)
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        assert conn.call("workspace.info")["root"]
        time.sleep(1.5)
        # 연결 뒤 만료: 그 뒤 모든 요청 거부
        with pytest.raises(DaemonError) as caught:
            conn.call("workspace.info")
        assert caught.value.kind == "job_token_invalid"
    assert refused_hello(daemon, agent(job["agent_id"], token=job["token"])).kind == (
        "job_token_invalid"
    )
    # 토큰이 만료돼도 작업은 감독이 끝낼 때까지 슬롯을 쥔다 — 끝내고 다음 작업
    with daemon.client() as ui:
        ui.call("job.end", {"job": job["job"], "reason": "cancelled"}, timeout=300)
    # 폐기(job.end): 토큰 먼저 폐기 → 붙은 연결도 그 뒤 거부
    live = begin(daemon)
    with daemon.client(agent(live["agent_id"], token=live["token"])) as conn:
        assert conn.call("workspace.info")["root"]
        with daemon.client() as ui:
            ended = ui.call("job.end", {"job": live["job"], "reason": "cancelled"})
            assert (ended["job"], ended["cancelled"], ended["state"]) == (
                live["job"],
                [],
                "cancelled",
            )
            # 멱등
            assert ui.call("job.end", {"job": live["job"], "reason": "cancelled"})["job"]
        with pytest.raises(DaemonError) as caught:
            conn.call("workspace.info")
        assert caught.value.kind == "job_token_invalid"


def test_token_binds_job(ws: Path, daemon: ThreadDaemon) -> None:
    job = begin(daemon, toolsets=["knowledge", "cases"])
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        assert conn.hello_result is not None
        assert conn.hello_result["principal"] == {
            "kind": "agent",
            "id": job["agent_id"],
            "attended": False,
            "job": job["job"],
        }
        # 허용 범위 밖 툴셋은 켜도 쓰지 못한다 (run은 이 작업의 범위 밖)
        conn.call("agent.toolsets.enable", {"toolsets": ["run", "cases"]})
        with pytest.raises(DaemonError) as caught:
            conn.call("run.start", {"path": "tests/inventory_open.graph.json"})
        assert (caught.value.kind, caught.value.data.get("reason")) == (
            "permission_denied",
            "job_scope",
        )
        # 보고 메모는 작업 연결 전용 (글자 검사 거침)
        noted = conn.call("job.note", {"text": "구매 단추가 옮겨졌다"})
        assert noted == {"job": job["job"], "bytes": len("구매 단추가 옮겨졌다".encode())}
        # 작업 연결은 작업을 만들거나 끝내지 못한다 (재귀 금지)
        with pytest.raises(DaemonError) as caught:
            conn.call("job.begin", {"playbook": "triage"})
        assert caught.value.kind == "permission_denied"
    with daemon.client(agent("panel", attended=True)) as plain:
        plain.call("agent.toolsets.enable", {"toolsets": ["cases"]})
        with pytest.raises(DaemonError) as caught:
            plain.call("job.note", {"text": "x"})
        assert caught.value.kind == "job_only"
        # 자기 신고 ID만으로는 작업에 묶이지 않는다
        assert plain.hello_result is not None and "job" not in plain.hello_result["principal"]
    # 토큰 없이 같은 ID: 끝나지 않은 작업에 예약된 ID는 토큰으로만 붙는다 (UX5 검수 1 — 예전에는
    # 작업 밖 연결로 붙어 작업 규칙을 피할 수 있었다)
    impostor = agent(job["agent_id"])
    assert refused_hello(daemon, impostor).kind == "job_token_invalid"


def control_kind(conn: DaemonClient) -> str:
    """control.key를 보내 본 결과의 종류 (창이 없어 입력은 가지 않는다)."""
    conn.call("agent.toolsets.enable", {"toolsets": ["control"]})
    try:
        conn.call("control.key", {"window": "창 없음 B4", "keys": "a"}, timeout=120)
    except DaemonError as exc:
        return str(exc.kind)
    return "ok"


def test_job_token_curator_control_allowed(daemon: ThreadDaemon) -> None:
    job = begin(daemon)
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        # 판정은 통과했다 (창이 없어 제어 실행이 입력 없이 끝난다 — 권한 오류가 아니다)
        assert control_kind(conn) not in PERMISSION_CODES


def test_job_control_refused_during_verification(daemon: ThreadDaemon) -> None:
    """작업 안 control allow(R0)여도 자동 채택 검증 세션 중의 작업 연결 입력은 거부한다 (R7)."""
    job = begin(daemon)
    manager = daemon.daemon.run_manager
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        epoch = manager.begin_verification()
        try:
            assert control_kind(conn) == "verification_active"
            assert manager.input_epoch() == epoch  # 거부된 시도는 세대를 올리지 않는다
        finally:
            manager.end_verification()
        assert control_kind(conn) not in PERMISSION_CODES | {"verification_active"}  # 양성


def test_outside_job_ask(daemon: ThreadDaemon) -> None:
    with daemon.client(agent("night", attended=False)) as conn:
        assert control_kind(conn) == "permission_denied"  # 무인 ask = deny
    with daemon.client(agent("panel", attended=True)) as conn:
        assert control_kind(conn) == "approval_required"  # 확인할 사람 연결 없음


def test_job_explicit_deny_kept(ws: Path, daemon: ThreadDaemon) -> None:
    set_permissions(
        ws, {"preset": "curator", "rules": [{"rule": "kb_input_key", "verdict": "deny"}]}
    )
    job = begin(daemon)
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        assert control_kind(conn) == "permission_denied"
    team = json.loads((ws / "kookabug.json").read_text("utf-8"))
    team["permissions"] = {"toolsets": {"control": "deny"}}
    (ws / "kookabug.json").write_text(json.dumps(team), encoding="utf-8")
    set_permissions(ws, {"preset": "curator"})
    with daemon.client(agent(job["agent_id"], token=job["token"])) as conn:
        assert control_kind(conn) == "permission_denied"
