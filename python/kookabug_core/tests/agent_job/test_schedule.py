"""예약 실행 (M8 계획 3.9 "예약", E12·U5) — XML·명령 생성과 `--dry-run`까지만 (schtasks 없음)."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import TextIO

import pytest

from kb_testing.sample_game import copy_example_workspace
from kookabug_cli import agent_job_cmd
from kookabug_cli.main import build_parser
from kookabug_core.agent_job import schedule

NS = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
WID = "0b7c5a1e-2f7e-4c55-9e1a-3c2b6d8f9a10"


def test_xml_and_schtasks_command_dry_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    made = schedule.plan(
        root,
        workspace_id=WID,
        playbook="triage",
        daily="09:30",
        agent="claude",
        user=r"PC\tester",
        python=r"C:\Kookabug\python.exe",
        today=datetime(2026, 11, 10),
    )
    assert made.name == f"Kookabug\\{WID}\\triage"
    assert made.command == [
        "schtasks",
        "/Create",
        "/TN",
        made.name,
        "/XML",
        str(root / ".kookabug" / "jobs" / "schedule-triage.xml"),
        "/F",
    ]
    task = ET.fromstring(made.xml.split("\n", 1)[1])
    assert task.findtext("t:Triggers/t:CalendarTrigger/t:StartBoundary", namespaces=NS) == (
        "2026-11-10T09:30:00"
    )
    assert task.findtext("t:Principals/t:Principal/t:UserId", namespaces=NS) == r"PC\tester"
    # U5: 로그온한 경우에만, 절전 깨우기 안 함, 배터리에서 시작 안 함, 실행 중이면 새로 시작 안 함
    assert (
        task.findtext("t:Principals/t:Principal/t:LogonType", namespaces=NS) == "InteractiveToken"
    )
    settings = {
        name: task.findtext(f"t:Settings/t:{name}", namespaces=NS)
        for name in ("WakeToRun", "DisallowStartIfOnBatteries", "MultipleInstancesPolicy")
    }
    assert settings == {
        "WakeToRun": "false",
        "DisallowStartIfOnBatteries": "true",
        "MultipleInstancesPolicy": "IgnoreNew",
    }
    arguments = task.findtext("t:Actions/t:Exec/t:Arguments", namespaces=NS) or ""
    assert "agent-job run" in arguments and "--trigger schedule" in arguments
    assert "--agent claude" in arguments and "--playbook triage" in arguments
    # 토큰·비밀값은 XML에 없다 (실행 때 새 토큰을 받는다)
    for word in ("job_token", "kookabug_job_token", "kookabug_secret", "--job-token"):
        assert word not in made.xml.casefold()

    with pytest.raises(schedule.ScheduleError):
        schedule.plan(root, workspace_id=WID, playbook="triage", daily="25:00", agent=None)

    # 설치: 주입한 schtasks만 부른다 (실제 등록 없음), XML은 UTF-16
    calls: list[list[str]] = []
    assert schedule.install(root, made, runner=lambda c: calls.append(list(c)) or 0) == 0
    assert calls == [made.command]
    assert (root / made.xml_rel).read_bytes().decode("utf-16") == made.xml

    # CLI --dry-run: XML·명령만 출력하고 파일·등록·kookabug.json id를 만들지 않는다
    ws = copy_example_workspace(tmp_path / "cli")
    before = (ws / "kookabug.json").read_bytes()

    def boom(*_: object, **__: object) -> int:
        raise AssertionError("dry-run이 schtasks를 불렀다")

    monkeypatch.setattr(schedule, "_run_schtasks", boom)
    monkeypatch.delenv("KOOKABUG_AGENT", raising=False)
    args = build_parser().parse_args(
        [
            "agent-job",
            "schedule",
            "install",
            "--workspace",
            str(ws),
            "--playbook",
            "triage",
            "--daily",
            "07:05",
            "--dry-run",
            "--json",
        ]
    )
    assert agent_job_cmd.run(args, *_streams()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True and out["schtasks"][:2] == ["schtasks", "/Create"]
    assert "T07:05:00" in out["xml"]
    assert not (ws / ".kookabug" / "jobs").exists()
    assert (ws / "kookabug.json").read_bytes() == before


def _streams() -> tuple[TextIO, TextIO]:
    import sys

    return sys.stdout, sys.stderr
