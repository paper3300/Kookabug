"""target 편집 메서드의 에이전트 권한 (M2 계획 2.5, T6).

메서드 → 도구: `target.save` → `kb_target_create`(대표 인자 = target 경로), `target.open`·
`target.load_image`·`target.preview` → `kb_image_find`(경로), `windows.list`·`target.capture` →
`kb_screen_capture`. daemon 판정은 서비스 판정과 같고, 거부·승인 필요면 아무것도 쓰지 않는다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.daemon_targets import CAPTURES, START_BUTTON, Editor, snapshot, target_workspace

from kb_testing.daemon import ThreadDaemon
from kookabug_core.permissions import Principal
from kookabug_core.service import WorkspaceService
from kookabug_daemon.client import DaemonError

pytestmark = pytest.mark.process

AGENT_ID: Final = "agent-7"
NEW: Final = "targets/agent/new.target.json"
SAMPLE: Final = "targets/title/start_button.target.json"


def agent(*, attended: bool = False) -> dict[str, Any]:
    return {"kind": "agent", "name": "mcp", "version": "0", "id": AGENT_ID, "attended": attended}


def write_local(root: Path, permissions: dict[str, Any]) -> None:
    path = root / ".kookabug" / "local.json"
    data: dict[str, Any] = (
        json.loads(path.read_text("utf-8")) if path.exists() else {"format": "kookabug.local/0"}
    )
    data["permissions"] = permissions
    path.write_text(json.dumps(data), encoding="utf-8")


def write_team(root: Path, permissions: dict[str, Any]) -> None:
    path = root / "kookabug.json"
    data = json.loads(path.read_text("utf-8"))
    data["permissions"] = permissions
    path.write_text(json.dumps(data), encoding="utf-8")


POLICIES: Final = {
    "read_only": lambda root: write_team(root, {"preset": "read_only"}),
    "graph_edit_ask": lambda root: write_local(root, {"toolsets": {"graph_edit": "ask"}}),
    "observe_deny": lambda root: write_local(root, {"toolsets": {"observe": "deny"}}),
}


@pytest.mark.parametrize("attended", [False, True], ids=["unattended", "attended"])
@pytest.mark.parametrize("policy", list(POLICIES))
def test_agent_target_save_maps_kb_target_create(
    tmp_path: Path, policy: str, attended: bool
) -> None:
    root = target_workspace(tmp_path)
    POLICIES[policy](root)
    principal = Principal("agent", AGENT_ID, attended=attended)
    service = WorkspaceService(root, environ={"KOOKABUG_USER_CONFIG_DIR": str(tmp_path / "u")})
    expected = {
        "target.save": service.authorize(principal, "kb_target_create", NEW),
        "target.load_image": service.authorize(principal, "kb_image_find", f"{CAPTURES}/title.png"),
        "target.open": service.authorize(principal, "kb_image_find", SAMPLE),
    }
    with ThreadDaemon(root, service=service) as d:
        with d.client() as ui:  # UI 연결은 판정받지 않는다: 정지 화면을 만들어 둔다
            frame = Editor(ui).load(f"{CAPTURES}/title.png")
        before = snapshot(root)
        with d.client(agent(attended=attended)) as client:
            ed = Editor(client)
            calls = {
                "target.load_image": lambda: ed.load(f"{CAPTURES}/title.png"),
                "target.open": lambda: ed.open(SAMPLE),
                "target.save": lambda: ed.save(NEW, frame, START_BUTTON),
            }
            for method, call in calls.items():
                decision = expected[method]
                if decision.final == "allow":
                    call()
                    continue
                with pytest.raises(DaemonError) as caught:
                    call()
                kind = (
                    "approval_required"
                    if decision.final == "ask" and attended
                    else ("permission_denied")
                )
                assert caught.value.kind == kind, (method, caught.value)
                assert caught.value.data["decision"] == decision.to_dict()
    if expected["target.save"].final != "allow":
        assert snapshot(root) == before  # 거부·승인 필요: 파일을 쓰지 않았다
        assert not (root / NEW).exists() and not (root / "targets/agent").exists()
    else:
        assert (root / NEW).exists()
    # 정책별 기대: 편집 도구만 막는 정책은 읽기 도구를 막지 않는다
    if policy != "observe_deny":
        assert expected["target.open"].final == "allow"
        assert expected["target.save"].final != "allow"
    else:
        assert expected["target.open"].final == "deny"
