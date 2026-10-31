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
}


def methods() -> dict[str, dict[str, Any]]:
    return DEFS["Methods"]["properties"]


def check(name: str, value: Any) -> list[str]:
    return [e.message for e in validator("daemon-rpc", f"#/$defs/{name}").iter_errors(value)]


def test_method_table_matches_permission_table() -> None:
    table = methods()
    assert {name: row["properties"]["tool"]["const"] for name, row in table.items()} == TOOLS
    internal = {n for n, row in table.items() if not row["properties"]["renderer"]["const"]}
    assert internal == {"session.hello", "daemon.shutdown"}
    for row in table.values():
        for part in ("params", "result"):
            ref = row["properties"][part]["$ref"]
            assert ref.removeprefix("#/$defs/") in DEFS, ref
    assert set(DEFS["ToolName"]["enum"]) == set(TOOLS.values())


def test_notification_table() -> None:
    table = DEFS["Notifications"]["properties"]
    assert sorted(table) == [
        "graph.changed",
        "lease.changed",
        "run.ended",
        "run.event",
        "run.lagged",
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
