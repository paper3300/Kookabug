"""M7 검사 전용 가짜 예제 게임 배치 (M7 계획 3.12).

예제 게임 장면 표(`fixtures/sample-game/frames/scenario.json`, 이미 떠 있는 창 `running: true`)를
숨은 `--platform-fake` 사양으로 쓴다:

- `state_file`: 제어 실행(runner 프로세스)과 daemon 가짜 캡처가 같은 게임 상태(장면·지연 전이·칸
  값·포커스·선택·창)를 잇는다
- `draw_fields`: daemon 가짜 캡처가 로그인 칸의 지금 값을 픽셀에 평문으로 그린다 — 비밀값 보호
  검사의 양성 대조군(값이 원본 프레임에 실제로 보인다)
- `input_log`: 가짜 입력 백엔드 기록 (게임 쪽 — 비밀값이 실제로 갔는지)

여기 값은 모두 검사 전용 가짜 값이다. 제품 경로(`kookabug.json`·사용자 설정·실행 기록 조건)에는 이
키들이 없다.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kb_testing.daemon import ThreadDaemon, copy_sample_workspace
from kb_testing.packaging import REPO_ROOT
from kb_testing.proc import python_cmd, read_fake_input_log

__all__ = [
    "ACCOUNT_FIELD",
    "LOGIN_BUTTON",
    "PASSWORD_FIELD",
    "START_BUTTON",
    "WINDOW",
    "FakeGame",
    "make_fake_game",
]

WINDOW = "SampleRPG"
START_BUTTON = (512, 412)
"""타이틀 시작 단추 (→ 로그인)."""
ACCOUNT_FIELD = (560, 230)
PASSWORD_FIELD = (560, 310)
"""로그인 칸 가운데 (클라이언트 좌표)."""
LOGIN_BUTTON = (512, 408)


@dataclass
class FakeGame:
    root: Path
    platform: Path
    input_log: Path
    state_file: Path
    frames: Path

    def inputs(self) -> list[dict[str, Any]]:
        return read_fake_input_log(self.input_log)

    def state(self) -> dict[str, Any]:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def set_window(
        self, *, open: bool | None = None, pid: int | None = None, created: str | None = None
    ) -> None:
        """검사가 창을 닫거나(같은 HWND를 다른 프로세스가 쓰게) 바꾼다. `pid`만 바꾸면 생성 시각도
        그 PID 기본값으로 바뀐다(다른 프로세스). `created`는 프로세스 생성 시각(FILETIME 10진)."""
        state = self.state()
        window = dict(state.get("window", {}))
        if open is not None:
            window["open"] = open
        if pid is not None:
            window["pid"] = pid
            window.pop("created", None)
        if created is not None:
            window["created"] = created
        state["window"] = window
        self.state_file.write_text(json.dumps(state), encoding="utf-8")

    def run_folders(self) -> list[Path]:
        runs = self.root / "runs"
        return sorted(p for p in runs.iterdir() if p.is_dir()) if runs.exists() else []

    def daemon(self, env: Mapping[str, str]) -> ThreadDaemon:
        """같은 프로세스 daemon (실제 runner·감독자로 제어 실행, 창·캡처는 이 가짜 게임)."""
        from kookabug_core.service import WorkspaceService
        from kookabug_core.supervisor import Supervisor

        supervisor = Supervisor(runner_cmd=python_cmd("-m", "kookabug_core.runner"), env=env)
        service = WorkspaceService(self.root, environ=env, supervisor=supervisor)
        return ThreadDaemon(self.root, service=service, platform_fake=self.platform)


def make_fake_game(
    tmp_path: Path,
    *,
    permissions: dict[str, Any] | None = None,
    draw: bool = True,
    scenario_patch: Any = None,
    screens: bool = True,
) -> FakeGame:
    """예제 워크스페이스 사본 + 가짜 게임 사양. `scenario_patch(dict)`로 장면 표를 고칠 수 있다.
    `screens=False`면 확정 화면 지도(`screens/`)를 지운다 — 처음부터 탐색하는 검사용."""
    root = copy_sample_workspace(tmp_path / "ws")
    if not screens:
        shutil.rmtree(root / "screens", ignore_errors=True)
    frames = tmp_path / "frames"
    shutil.copytree(REPO_ROOT / "fixtures" / "sample-game" / "frames", frames)
    scenario = json.loads((frames / "scenario.json").read_text(encoding="utf-8"))
    scenario["running"] = True
    if scenario_patch is not None:
        scenario_patch(scenario)
    (frames / "scenario.json").write_text(json.dumps(scenario), encoding="utf-8")
    log = tmp_path / "input.jsonl"
    state = tmp_path / "game-state.json"
    spec = tmp_path / "platform.json"
    body: dict[str, Any] = {
        "scenario": str(frames / "scenario.json"),
        "input_log": str(log),
        "state_file": str(state),
    }
    if draw:
        body["draw_fields"] = {"login": ["account", "password"]}
    spec.write_text(json.dumps(body), encoding="utf-8")
    local = root / ".kookabug" / "local.json"
    local.parent.mkdir(exist_ok=True)
    perms = permissions or {"preset": "full"}
    local.write_text(
        json.dumps({"format": "kookabug.local/0", "permissions": perms}), encoding="utf-8"
    )
    return FakeGame(root, spec, log, state, frames)
