"""UX11 Kookabug 자체 자격 증명 가림 (검수 2 반영 — 정의 단순화).

공용 출구(원본 읽기·대화 저장·작업 활동·글자 검사)가 가리는 값 = 실행 중인 작업들이 daemon 메모리에
가진 작업 토큰 + runner가 그 에이전트 프로세스에 넣은 인증·환경 값(`job.heartbeat` `masks`). 파일을
훑지 않는다. 워크스페이스 비밀값 저장소의 값은 용도와 무관하게(게임 계정이든 판단 노드 `api_key`로
쓰인 값이든) 가리지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core.workspace import secret_env_name

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

API_KEY = "sk-test-UX11-key-0123456789"
"""검사 전용 가짜 모델 API 키 (워크스페이스 비밀값 — 판단 노드 `api_key`로 쓰인다)."""
PASSED = "agent-env-UX11-tok-55"
"""검사 전용 가짜 값: runner가 에이전트 프로세스에 넣은 인증 환경 값."""
GAME_PW = "game-pass-UX11-77"
"""검사 전용 가짜 게임 계정 비밀번호 (워크스페이스 비밀값)."""


def judge_graph() -> dict[str, object]:
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_judge": {
                "type": "core.agent.api_judge",
                "version": 1,
                "in": {"api_key": {"$secret": "model.key"}, "prompt": "?"},
            },
        },
    }


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = copy_example_workspace(tmp_path)
    (root / "tests" / "judge.graph.json").write_text(json.dumps(judge_graph()), encoding="utf-8")
    monkeypatch.setenv(secret_env_name("model.key"), API_KEY)
    monkeypatch.setenv(secret_env_name("acc.pw"), GAME_PW)
    source = tmp_path / "notes.txt"
    source.write_text(f"API_KEY={API_KEY}\nPASSED={PASSED}\nPW={GAME_PW}\n", encoding="utf-8")
    config_path = root / "kookabug.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    config["sources"] = [{"id": "notes", "kind": "other", "title": "메모", "path": str(source)}]
    config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return root


@pytest.fixture
def daemon(ws: Path) -> Iterator[ThreadDaemon]:
    with ThreadDaemon(ws) as d:
        yield d


def running_job(d: ThreadDaemon) -> dict[str, Any]:
    """실행 중인 작업 하나 + runner가 넣은 값 알림 (`job.heartbeat` `masks` — 소유 연결)."""
    job = d.begin_job({"playbook": "repair"})
    job["owner"].call("job.heartbeat", {"job": job["job"], "masks": [PASSED]}, timeout=10)
    return job


def test_heartbeat_masks_owner_only_and_lifetime(daemon: ThreadDaemon) -> None:
    job = running_job(daemon)
    values = daemon.daemon.jobs.secret_values()
    assert job["token"] in values and PASSED in values
    assert API_KEY not in values and GAME_PW not in values  # 워크스페이스 비밀값은 들지 않는다
    with daemon.client() as other, pytest.raises(Exception) as caught:
        other.call("job.heartbeat", {"job": job["job"], "masks": ["x"]}, timeout=10)
    assert getattr(caught.value, "kind", None) == "permission_denied"
    daemon.daemon.jobs.forget_token(job["job"])
    assert PASSED not in daemon.daemon.jobs.secret_values()


def test_source_read_masks_passed_values_keeps_workspace_secrets(
    ws: Path, daemon: ThreadDaemon
) -> None:
    from kookabug_daemon.methods.sources import _read_sync  # pyright: ignore[reportPrivateUsage]

    job = running_job(daemon)
    (ws.parent / "notes.txt").write_text(
        f"TOKEN={job['token']}\nAPI_KEY={API_KEY}\nPASSED={PASSED}\nPW={GAME_PW}\n",
        encoding="utf-8",
    )
    call = SimpleNamespace(daemon=daemon.daemon, params={"source": "notes"})
    text = _read_sync(call)["text"]  # type: ignore[arg-type]
    assert job["token"] not in text and PASSED not in text
    assert API_KEY in text and GAME_PW in text  # 판단 노드 api_key로 쓰인 값도 그대로


def test_conversation_save_masks_passed_values(ws: Path, daemon: ThreadDaemon) -> None:
    running_job(daemon)
    item = {"kind": "user", "text": f"넣은 값 {PASSED} 키 {API_KEY} 비번 {GAME_PW}", "chips": []}
    conversation = {
        "id": "c-20261116-120000-beef",
        "agent_id": "fake",
        "agent_name": "가짜",
        "acp_session": None,
        "items": [item],
    }
    with daemon.client() as ui:
        ui.call("conversations.save", {"conversation": conversation})
    raw = (ws / ".kookabug" / "conversations" / "c-20261116-120000-beef.json").read_text("utf-8")
    assert PASSED not in raw
    assert API_KEY in raw and GAME_PW in raw


def test_text_check_refuses_passed_values_only(daemon: ThreadDaemon) -> None:
    from kookabug_daemon.methods.adopt import text_checker

    job = running_job(daemon)
    check = text_checker(daemon.daemon)
    check([("note", f"키 {API_KEY} 비번 {GAME_PW}")])  # 워크스페이스 비밀값은 그대로 저장된다
    for value in (PASSED, job["token"]):
        with pytest.raises(Exception) as caught:
            check([("note", f"값 {value}")])
        assert getattr(caught.value, "code", None) == "secret_in_text"


def test_activity_target_masks_passed_values(ws: Path, daemon: ThreadDaemon) -> None:
    from kookabug_core.agent_job import activity, jobdir

    job = running_job(daemon)
    jobdir.job_path(ws, job["job"]).mkdir(parents=True, exist_ok=True)  # agent-job이 만드는 폴더
    daemon.daemon.jobs.record_activity(job["job"], "kb_source_read", "ok", f"notes:{PASSED}")
    daemon.daemon.jobs.record_activity(job["job"], "kb_source_read", "ok", f"notes:{GAME_PW}")
    targets = [row.get("target", "") for row in activity.read(ws, job["job"])]
    assert all(PASSED not in t for t in targets)
    assert any(GAME_PW in t for t in targets)
