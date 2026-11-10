"""UI ↔ daemon 계약 (M2 계획 2.4·2.5): daemon-rpc·session 메타스키마."""

from __future__ import annotations

from typing import Any

import pytest

from kookabug_core.schema import check_shape, kind_of, metaschema
from kookabug_core.schema.shape import validator
from kookabug_platform.errors import CODES as PLATFORM_CODES

DEFS: dict[str, Any] = metaschema("daemon-rpc")["$defs"]

# M2 계획 2.5 권한 표 (메서드 → 도구, 구현 계획 7장)
TOOLS = {
    "workspace.info": "kb_project_info",
    "workspace.tree": "kb_project_info",
    "workspace.read": "kb_project_info",
    "nodes.list": "kb_node_search",
    "graph.open": "kb_graph_get",
    "graph.validate": "kb_graph_validate",
    "graph.save": "kb_graph_patch",
    "graph.create": "kb_graph_create",
    "run.start": "kb_run_start",
    "run.cancel": "kb_run_cancel",
    "run.status": "kb_run_status",
    "run.list": "kb_run_status",
    "run.subscribe": "kb_run_events",
    "windows.list": "kb_screen_capture",
    "target.capture": "kb_screen_capture",
    "target.preview": "kb_image_find",
    "target.load_image": "kb_image_find",
    "target.open": "kb_image_find",
    "target.save": "kb_target_create",
    "session.hello": "ui_only",
    "daemon.shutdown": "ui_only",
    "graph.close": "ui_only",
    "run.unsubscribe": "ui_only",
    # M3 계획 2.7 기록 읽기
    "run.index": "kb_run_events",
    "run.children": "kb_run_events",
    "run.step": "kb_run_events",
    "run.file": "kb_run_events",
    "run.compare": "kb_run_events",
    # M3 계획 2.1·2.3 디버거·내보내기
    "debug.breakpoints.get": "ui_only",
    "debug.breakpoints.set": "ui_only",
    "run.pause": "ui_only",
    "run.resume": "ui_only",
    "run.restart": "ui_only",
    "run.export": "ui_only",
    # M4 계획 2.9 녹화·비밀값 (사람만)
    "recorder.start": "ui_only",
    "recorder.pause": "ui_only",
    "recorder.resume": "ui_only",
    "recorder.stop": "ui_only",
    "recorder.discard": "ui_only",
    "recorder.state": "ui_only",
    "recorder.steps": "ui_only",
    "recorder.step.update": "ui_only",
    "recorder.frame": "ui_only",
    "recorder.insert_check": "ui_only",
    "recorder.commit_prepare": "ui_only",
    "recorder.commit_finish": "ui_only",
    "recorder.commit_abort": "ui_only",
    "recorder.target.materialize": "ui_only",
    "secrets.list": "ui_only",
    "secrets.create": "ui_only",
    "target.read_text": "ui_only",
    # M5 계획 3.5 (B1): 연결별 툴셋·경로로 고치기
    "agent.toolsets.get": "kb_toolset_enable",
    "agent.toolsets.enable": "kb_toolset_enable",
    "graph.patch": "kb_graph_patch",
    # B1 검수: MCP 도구 이름 그대로 판정하는 진입점
    "graph.list": "kb_graph_list",
    "graph.check": "kb_graph_validate",
    # M5 계획 3.5 (B2): 에이전트용 기록 읽기(가린 결과)·관측·화면 지도
    "run.failure": "kb_run_status",
    "run.events": "kb_run_events",
    "run.search": "kb_log_search",
    "run.artifact": "kb_run_artifact_get",
    "run.diff": "kb_run_compare",
    "screen.read_text": "kb_ocr_read",
    "screens.list": "kb_screen_list",
    "screens.get": "kb_screen_get",
    # M5 B3: 사람 확인·권한 설정·게임 조작
    "approval.list": "ui_only",
    "approval.respond": "ui_only",
    "approval.preview": "ui_only",
    "permissions.get": "kb_project_info",
    "permissions.set": "ui_only",
    "control.click": "kb_input_click",
    "control.key": "kb_input_key",
    "control.type": "kb_input_type",
    "app.launch": "kb_app_launch",
    # M5 B5: 에이전트 패널·설정 (사람만)
    "agent.connections": "ui_only",
    "agents.get": "ui_only",
    "agents.detect": "ui_only",
    "agents.set": "ui_only",
    # M6 B4: 플러그인 — 목록은 조회, 변경은 사람만
    "plugins.list": "kb_project_info",
    "plugins.preview": "ui_only",
    "plugins.install": "ui_only",
    "plugins.upgrade": "ui_only",
    "plugins.remove": "ui_only",
    "plugins.sync": "ui_only",
    "plugins.relock": "ui_only",
    "plugins.gc": "ui_only",
    "plugins.cancel": "ui_only",
    # M7 탐색 세션·화면 지도 저장·식별 (목록은 사람 화면용)
    "screens.identify": "kb_screen_identify",
    "screens.save": "kb_screen_save",
    "explore.start": "kb_explore_start",
    "explore.end": "kb_explore_end",
    "explore.list": "ui_only",
    # M7 B3 화면 지도 사람 전용 (승격·버리기·확인·카드 배치)
    "screens.check": "ui_only",
    "screens.promote": "ui_only",
    "screens.discard": "ui_only",
    "screens.layout_get": "ui_only",
    "screens.layout_set": "ui_only",
    # M7 B4 이동 그래프 (조회, 렌더러 화면 지도 탭)
    "screens.map": "kb_screen_list",
    # M8 B2 치트 채택·분류 사람 전용
    "cheats.list": "ui_only",
    "cheats.adopt": "ui_only",
    "cheats.unadopt": "ui_only",
    "cheats.categories.set": "ui_only",
    # M8 B3 되돌리기·묶음 수락 (사람 전용). 채택 요청·증거 고정은 B4부터 cases 도구
    **dict.fromkeys(
        ("adopt.revert", "adoptions.list", "working.accept", "working.list", "working.reject"),
        "ui_only",
    ),
    "adopt.request": "kb_adopt_request",
    "evidence.pin": "kb_evidence_pin",
    # M8 B4 지식·사건 도구 (3.13·3.14)
    "knowledge.search": "kb_knowledge_search",
    "knowledge.get": "kb_knowledge_get",
    "knowledge.apply": "kb_knowledge_apply",
    "wiki.write": "kb_wiki_write",
    "cases.list": "kb_case_list",
    "cases.get": "kb_case_get",
    "cases.signals": "kb_triage_signals",
    "cases.open": "kb_case_open",
    "cases.update": "kb_case_update",
    "job.note": "kb_report_note",
    # M8 B4 사람 전용 (사건 닫기·미지수 답·정책·원본·작업·보고함·마법사)
    **dict.fromkeys(
        (
            "cases.close",
            "unknowns.answer",
            "project.automation.set",
            "project.sources.set",
            "sources.check",
            "job.begin",
            "job.end",
            "job.finish",
            "jobs.list",
            "reports.list",
            "reports.get",
            "report.decide",
            "wizard.get",
            "wizard.set",
            # M8 B5 작업 소유 연결 heartbeat (R8)
            "job.heartbeat",
        ),
        "ui_only",
    ),
    # M8 B5 플레이북 판·원본 상태 (kb_project_info가 함께 준다)
    "project.qa_info": "kb_project_info",
}
M8_B3 = {
    "adopt.request",
    "adopt.revert",
    "adoptions.list",
    "evidence.pin",
    "working.accept",
    "working.list",
    "working.reject",
}
M8_B4 = {name for name, tool in TOOLS.items() if name.split(".")[0] in {
    "knowledge", "wiki", "cases", "job", "jobs", "reports", "report", "unknowns", "project",
    "sources", "wizard",
}}  # fmt: skip
"""M8 B4 메서드: 렌더러 다리는 B7(마법사·보고함)이 연다 — 지금은 모두 렌더러 밖."""
AGENT_ONLY_B3 = {"control.click", "control.key", "control.type", "app.launch"}
AGENT_ONLY_M7 = {"screens.identify", "screens.save", "explore.start", "explore.end"}
AGENT_ONLY_B2 = {
    "run.failure",
    "run.events",
    "run.search",
    "run.artifact",
    "run.diff",
    "screen.read_text",
    "screens.list",
    "screens.get",
}


def methods() -> dict[str, dict[str, Any]]:
    return DEFS["Methods"]["properties"]


def check(name: str, value: Any) -> list[str]:
    return [e.message for e in validator("daemon-rpc", f"#/$defs/{name}").iter_errors(value)]


def test_method_table_matches_permission_table() -> None:
    table = methods()
    assert {name: row["properties"]["tool"]["const"] for name, row in table.items()} == TOOLS
    internal = {n for n, row in table.items() if not row["properties"]["renderer"]["const"]}
    # run.export의 dest는 주 프로세스 저장 대화 상자가 정한다 (M3 계획 2.7)
    # M5: 에이전트(MCP)만 쓰는 메서드도 렌더러 표면에 내놓지 않는다
    assert internal == {
        "session.hello",
        "daemon.shutdown",
        "run.export",
        "agent.toolsets.get",
        "agent.toolsets.enable",
        "graph.patch",
        "graph.list",
        "graph.check",
        *AGENT_ONLY_B2,
        *AGENT_ONLY_B3,
        *AGENT_ONLY_M7,
        # M8 B2: 치트 채택은 CLI·daemon 사람 연결만 (렌더러 다리는 B7 보고함·마법사와 같이 연다)
        "cheats.list",
        "cheats.adopt",
        "cheats.unadopt",
        "cheats.categories.set",
        # M8 B3: 렌더러 다리는 B7 보고함과 같이 연다
        *M8_B3,
        *M8_B4,
    }
    for row in table.values():
        for part in ("params", "result"):
            ref = row["properties"][part]["$ref"]
            assert ref.removeprefix("#/$defs/") in DEFS, ref
    assert set(DEFS["ToolName"]["enum"]) == set(TOOLS.values())


def test_notification_table() -> None:
    table = DEFS["Notifications"]["properties"]
    assert sorted(table) == [
        "agent.connections.changed",
        "agent.protect_corrupt",  # M7 에이전트 보호 기록 손상 (ui 연결에만)
        "approval.requested",
        "approval.resolved",
        "debug.breakpoints.changed",
        "explore.changed",  # M7 탐색 세션·후보 (ui 연결에만)
        "graph.changed",
        "job.budget",  # M8 작업 예산 상한 (ui 연결에만, B5가 보낸다)
        "job.changed",  # M8 작업 상태 (ui 연결에만, B5가 보낸다)
        "knowledge.changed",  # M8 B4 지식·위키·사건 변경 (ui 연결에만)
        "lease.changed",
        "plugins.changed",
        "plugins.done",
        "plugins.progress",
        "recorder.changed",
        "reports.changed",  # M8 보고함 (ui 연결에만, B5가 보낸다)
        "run.ended",
        "run.event",
        "run.lagged",
        "screens.changed",  # M7 B4 화면 지도 파일 변경 (ui 연결에만)
        "workspace.changed",
    ]


def test_request_failed_codes_cover_plan_and_platform() -> None:
    codes = set(DEFS["RequestFailedCode"]["enum"])
    plan = {
        "unauthenticated", "protocol_mismatch", "not_found", "path_outside_workspace",
        "private_path", "invalid_json", "doc_not_open", "revision_conflict", "exists",
        "idempotency_conflict", "validation_failed", "run_busy", "run_active", "run_not_found",
        "permission_denied", "approval_required", "platform_unavailable", "window_not_found",
        "frame_expired", "target_invalid", "io_error", "shutting_down",
        # M3 계획 2.11
        "read_only", "not_paused", "run_not_debuggable",
        # M4 계획 2.12
        "recording_active", "input_lease_busy", "not_owner", "classification_pending",
        "text_review_required", "secret_unresolved", "target_missing", "secret_region_overlap",
        "hook_failed", "hook_lost", "input_overflow", "no_frame",
    }  # fmt: skip
    assert plan <= codes
    assert set(PLATFORM_CODES) <= codes
    assert DEFS["DaemonErrorCode"]["enum"] == [-32700, -32600, -32601, -32602, -32603, -32100]


def test_envelope_and_params_validate() -> None:
    request = {"jsonrpc": "2.0", "id": 1, "method": "graph.open", "params": {"path": "a"}}
    assert check_shape(request, "daemon-rpc") == []
    error = {
        "jsonrpc": "2.0",
        "id": 3,
        "error": {
            "code": -32100,
            "message": "충돌",
            "data": {"code": "revision_conflict", "revision": None},
        },
    }
    assert check_shape(error, "daemon-rpc") == []
    assert check_shape({**error, "error": {"code": -32001, "message": "x"}}, "daemon-rpc")
    assert check("RequestFailedData", error["error"]["data"]) == []
    assert check("RequestFailedData", {"code": "nope"})
    # 저장 params: base_revision 필수, value는 객체
    save = {"doc_id": "d1", "value": {}, "base_revision": "0" * 64}
    assert check("GraphSaveParams", save) == []
    assert check("GraphSaveParams", {**save, "value": []})
    assert check("GraphSaveParams", {k: v for k, v in save.items() if k != "base_revision"})
    # target.save: base_revision은 null(새 파일) 또는 합친 revision
    crop = {"frame_id": "f", "rect": [0, 0, 4, 4]}
    target = {"path": "targets/a.target.json", "spec": {}, "crop": crop}
    assert check("TargetSaveParams", {**target, "base_revision": None}) == []
    assert check("TargetSaveParams", {**target, "base_revision": "a" * 64 + ":" + "b" * 64}) == []
    assert check("TargetSaveParams", target)
    # crop은 선택 (없으면 지금 이미지 그대로 JSON만 저장), 저장 결과의 preview는 그때 null
    no_crop = {k: v for k, v in target.items() if k != "crop"}
    assert check("TargetSaveParams", {**no_crop, "base_revision": "a" * 64 + ":" + "b" * 64}) == []
    result = {"image": "targets/a.png", "revision": "a" * 64 + ":missing", "warnings": []}
    assert check("TargetSaveResult", {**result, "preview": None}) == []
    assert check("TargetSaveResult", result)
    # preview 템플릿은 crop 또는 image 하나
    preview = {"frame_id": "f", "seq": 1, "spec": {}}
    assert check("TargetPreviewParams", {**preview, "template": {"crop": crop}}) == []
    assert check("TargetPreviewParams", {**preview, "template": {"image": "a.png"}}) == []
    assert check("TargetPreviewParams", {**preview, "template": {"crop": crop, "image": "a.png"}})
    # 큰 실수는 봉투 값 규칙과 별개로 형식상 그냥 수다
    assert check("GraphValidateParams", {"doc_id": "d", "seq": 0, "value": {"x": 1e20}}) == []


STEP_END = {
    "event": "step.end",
    "run": "abcd1234",
    "seq": 7,
    "t": "2026-10-29T06:02:11.104Z",
    "attempt": 1,
    "duration_ms": 12,
    "exit": "done",
    "outputs": {"text": "x"},
    "status": "success",
    "step": "s2",
}


def run_event(event: Any) -> list[Any]:
    params = {"run_id": "abcd1234", "seq": 7, "event": event}
    return check_shape(params, "daemon-rpc", ref="#/$defs/RunEventParams")


def test_run_event_body_checked_by_events_schema() -> None:
    # run.event의 event는 events.schema.json으로 검사한다 (T2 검수 2)
    assert check_shape(STEP_END, "events") == []
    assert run_event(STEP_END) == []
    for bad in (
        {**STEP_END, "outputs": "not-an-object"},
        {},
        {**STEP_END, "event": "step.nope"},
        {k: v for k, v in STEP_END.items() if k != "step"},
    ):
        assert check_shape(bad, "events"), bad
        assert run_event(bad), bad


@pytest.mark.parametrize(
    "error",
    [
        {"code": -32100, "message": "failed"},
        {"code": -32100, "message": "failed", "data": {"code": "unknown_failure"}},
        {"code": -32100, "message": "failed", "data": {"code": "exists", "diagnostics": "bad"}},
        {"code": -32100, "message": "failed", "data": 123},
        {"code": -32001, "message": "내부 rpc 코드"},
    ],
    ids=["no-data", "unknown-code", "bad-field", "data-not-object", "internal-code"],
)
def test_request_failed_error_requires_data(error: dict[str, Any]) -> None:
    # -32100 봉투는 data(RequestFailedData)를 필수로 검사한다 (T2 검수 3)
    assert check_shape({"jsonrpc": "2.0", "id": 1, "error": error}, "daemon-rpc")


def test_standard_error_without_data_allowed() -> None:
    error = {"code": -32601, "message": "모르는 메서드"}
    assert check_shape({"jsonrpc": "2.0", "id": 1, "error": error}, "daemon-rpc") == []
    assert (
        check_shape({"jsonrpc": "2.0", "id": None, "error": {**error, "data": "x"}}, "daemon-rpc")
        == []
    )


def test_agent_hello_requires_id() -> None:
    # agent 연결은 비어 있지 않은 id 필수, ui는 id 없이 (T2 검수 5)
    def hello(client: dict[str, Any]) -> list[str]:
        return check("SessionHelloParams", {"token": "a" * 64, "protocol": 1, "client": client})

    agent = {"kind": "agent", "name": "probe", "version": "1"}
    assert hello(agent)
    assert hello({**agent, "id": ""})
    assert hello({**agent, "id": "codex-1"}) == []
    assert hello({**agent, "id": "codex-1", "attended": True}) == []
    ui = {"kind": "ui", "name": "desktop", "version": "0.1.0"}
    assert hello(ui) == []
    assert hello({**ui, "id": "x"})
    # 생성 모델도 같은 갈래다
    from kookabug_core.schema.models.daemon_rpc import AgentClientInfo, ClientInfo

    assert isinstance(ClientInfo.model_validate({**agent, "id": "a"}).root, AgentClientInfo)
    with pytest.raises(ValueError):
        ClientInfo.model_validate(agent)


SESSION = {
    "format": "kookabug.session/0",
    "pid": 4242,
    "process_created": "133745678901234567",
    "start_id": "0123456789abcdef0123456789abcdef",
    "protocol": 1,
    "daemon_version": "0.1.0",
    "port": 51234,
    "token": "ab" * 32,
    "workspace": "D:/work/game",
    "started_at": "2026-10-31T04:05:06.789Z",
}


def test_session_file_shape() -> None:
    assert kind_of(SESSION) == "session"
    assert check_shape(SESSION) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("token", "short"),
        ("token", "AB" * 32),
        ("port", 0),
        ("port", 70000),
        ("start_id", "x"),
        ("process_created", "-1"),
        ("started_at", "2026-10-31 04:05:06"),
    ],
)
def test_session_file_rejects_bad_fields(field: str, value: Any) -> None:
    assert check_shape({**SESSION, field: value}) != []
    missing = {k: v for k, v in SESSION.items() if k != field}
    assert [d.code for d in check_shape(missing)] == ["missing_field"]
