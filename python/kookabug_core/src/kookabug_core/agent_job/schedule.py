"""예약 실행 — Windows 작업 스케줄러 한 종류 (M8 계획 3.9 "예약", E12, U5).

`schedule install`이 `.kookabug/jobs/schedule-<playbook>.xml`을 쓰고
`schtasks /Create /TN "Kookabug\\<워크스페이스 ID>\\<playbook>" /XML <파일> /F`로 등록한다.
`--dry-run`은 XML·명령만 돌려주고 파일·등록을 하지 않는다. 실제 `schtasks` 호출은 주입 가능하다
(검사는 실제로 부르지 않는다).

작업 조건(U5): 실행 계정 = 현재 사용자, 로그온한 경우에만(`InteractiveToken`), 절전 깨우기 안 함,
배터리에서 시작 안 함, 이미 실행 중이면 새로 시작 안 함(`IgnoreNew`). XML에는 토큰·비밀값이 없다
(실행 때 `agent-job run`이 새 토큰을 받는다).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final
from xml.sax.saxutils import escape

from kookabug_core.agent_job.jobdir import JOBS_DIR, write_bytes

__all__ = [
    "Plan",
    "ScheduleError",
    "SchtasksRunner",
    "create_command",
    "delete_command",
    "install",
    "plan",
    "query_command",
    "remove",
    "task_name",
    "task_xml",
]

_TIME: Final = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
_SAFE: Final = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
type SchtasksRunner = Callable[[Sequence[str]], int]


class ScheduleError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class Plan:
    name: str
    xml: str
    xml_rel: str
    command: list[str]
    """`schtasks /Create …` (XML 경로 포함)."""


def task_name(workspace_id: str, playbook: str) -> str:
    if not _SAFE.fullmatch(workspace_id) or not _SAFE.fullmatch(playbook):
        raise ScheduleError("schedule_invalid", "작업 이름에 쓸 수 없는 글자가 있다")
    return f"Kookabug\\{workspace_id}\\{playbook}"


def _argument(value: str) -> str:
    """작업 스케줄러 Arguments 안 인자 하나 (공백·따옴표가 있으면 따옴표로)."""
    if value and not any(c in value for c in ' \t"'):
        return value
    return '"' + value.replace('"', '\\"') + '"'


def task_xml(
    *,
    root: Path,
    playbook: str,
    daily: str,
    agent: str | None,
    user: str,
    python: str | None = None,
    today: datetime | None = None,
) -> str:
    """작업 스케줄러 XML (UTF-16으로 저장한다 — schtasks가 읽는 인코딩)."""
    match = _TIME.fullmatch(daily)
    if match is None:
        raise ScheduleError("schedule_invalid", f"--daily는 HH:MM이어야 한다: {daily!r}")
    day = (today or datetime.now()).strftime("%Y-%m-%d")
    args = ["-m", "kookabug_cli", "agent-job", "run", "--workspace", str(root)]
    args += ["--playbook", playbook, "--trigger", "schedule"]
    if agent:
        args += ["--agent", agent]
    arguments = " ".join(_argument(a) for a in args)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Kookabug agent-job {escape(playbook)}</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{day}T{daily}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{escape(user)}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>true</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>true</StopIfGoingOnBatteries>
    <WakeToRun>false</WakeToRun>
    <StartWhenAvailable>false</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT4H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python or sys.executable)}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def create_command(name: str, xml_path: Path) -> list[str]:
    return ["schtasks", "/Create", "/TN", name, "/XML", str(xml_path), "/F"]


def delete_command(name: str) -> list[str]:
    return ["schtasks", "/Delete", "/TN", name, "/F"]


def query_command(name: str) -> list[str]:
    return ["schtasks", "/Query", "/TN", name, "/XML"]


def current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "")
    user = os.environ.get("USERNAME", "")
    return f"{domain}\\{user}" if domain else user


def plan(
    root: Path,
    *,
    workspace_id: str,
    playbook: str,
    daily: str,
    agent: str | None,
    user: str | None = None,
    python: str | None = None,
    today: datetime | None = None,
) -> Plan:
    """XML·명령을 만든다 (쓰지도 등록하지도 않는다 — `--dry-run`이 이것만 출력)."""
    name = task_name(workspace_id, playbook)
    xml = task_xml(
        root=root,
        playbook=playbook,
        daily=daily,
        agent=agent,
        user=user or current_user(),
        python=python,
        today=today,
    )
    rel = f"{JOBS_DIR}/schedule-{playbook}.xml"
    return Plan(name, xml, rel, create_command(name, root.joinpath(*rel.split("/"))))


def _run_schtasks(command: Sequence[str]) -> int:
    done = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return done.returncode


def install(root: Path, made: Plan, *, runner: SchtasksRunner | None = None) -> int:
    """XML을 쓰고(링크·정션·밖이면 거부) `schtasks /Create`를 부른다. 종료 코드를 돌려준다."""
    write_bytes(root, made.xml_rel, made.xml.encode("utf-16"))
    return (runner or _run_schtasks)(made.command)


def remove(name: str, *, runner: SchtasksRunner | None = None) -> int:
    return (runner or _run_schtasks)(delete_command(name))
