import copy
from typing import Any

import pytest

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.schema import KINDS, check_shape, metaschema
from kookabug_core.schema.models.node_schema import DynamicExits, FromInterface, NodeSchemaFile
from kookabug_core.schema.models.user_settings import UserSettings
from kookabug_core.schema.shape import ecma_regex


def codes(diags: list[Diagnostic]) -> list[tuple[str, str | None]]:
    return [(d.code, d.pointer) for d in diags]


TARGET = {
    "click": {"anchor": "center", "offset": [0, 0]},
    "format": "kookabug.target/0",
    "image": "start_button.png",
    "match": {"methods": ["template_multiscale", "template"], "rgb": True, "threshold": 0.85},
    "recorded": {"client_size": [1920, 1080], "dpi": 96},
    "search": {"region": [0.35, 0.6, 0.3, 0.25]},
}


def test_target_example_shape() -> None:
    assert check_shape(TARGET) == []
    assert check_shape({"format": "kookabug.target/0", "image": "a.png", "sensitive": True}) == []

    bad = copy.deepcopy(TARGET)
    del bad["image"]
    bad["click"]["anchor"] = "middle"
    bad["match"]["threshold"] = 1.5
    bad["match"]["methods"] = ["sift"]
    bad["search"]["region"] = [0.1, 0.2, 0.3]
    bad["recorded"]["dpi"] = 0
    assert codes(check_shape(bad)) == [
        ("missing_field", ""),
        ("invalid_value", "/click/anchor"),
        ("invalid_value", "/match/methods/0"),
        ("out_of_range", "/match/threshold"),
        ("out_of_range", "/recorded/dpi"),
        ("out_of_range", "/search/region"),
    ]


def test_target_image_uses_forward_slashes() -> None:
    assert codes(check_shape(TARGET | {"image": "sub\\a.png"})) == [("pattern_mismatch", "/image")]


def test_workspace_settings_null_allowed() -> None:
    workspace = {
        "format": "kookabug.workspace/0",
        "profiles": {"dev": {"settings": {"game.server": "Server 1", "game.executable": None}}},
        "settings": {"game.executable": None, "game.server": "Server 1", "n": 3, "l": [1]},
    }
    assert check_shape(workspace) == []

    workspace["settings"]["bad..key"] = 1
    workspace["profiles"]["q a"] = {}
    workspace["retention"] = {"keep_last": -1}
    workspace["record"] = {"video": "failed_only", "screenshots": "never"}
    assert codes(check_shape(workspace)) == [
        ("invalid_key", "/profiles/q a"),
        ("invalid_value", "/record/screenshots"),
        ("out_of_range", "/retention/keep_last"),
        ("invalid_key", "/settings/bad..key"),
    ]


def test_local_schema() -> None:
    local = {
        "format": "kookabug.local/0",
        "settings": {"game.executable": "C:/Games/SampleRPG/SampleRPG.exe", "x": None},
    }
    assert check_shape(local) == []
    assert check_shape({"format": "kookabug.local/0"}) == []
    assert codes(check_shape({"settings": {}}, "local")) == [("missing_field", "")]
    assert codes(check_shape(local | {"profile": "qa"})) == [("unknown_field", "/profile")]


PERMISSIONS = {
    "preset": "graph_author",
    "rules": [
        {"rule": "kb_run_start(tests/smoke/*)", "verdict": "allow"},
        {"rule": "kb_input_*", "verdict": "deny"},
        {"rule": "kb_run_start()", "verdict": "ask"},
    ],
    "toolsets": {"control": "deny", "run": "ask"},
}


def test_workspace_permissions_shape() -> None:
    for fmt in ("kookabug.workspace/0", "kookabug.local/0"):
        assert check_shape({"format": fmt, "permissions": PERMISSIONS}) == []
        assert check_shape({"format": fmt, "permissions": {}}) == []
        bad = copy.deepcopy(PERMISSIONS)
        bad["preset"] = "admin"
        bad["toolsets"] = {"shell": "allow", "run": "maybe"}
        bad["rules"] = [{"rule": "KB_RUN"}, {"rule": "kb_x(", "verdict": "deny", "why": 1}]
        bad["extra"] = True
        assert codes(check_shape({"format": fmt, "permissions": bad})) == [
            ("unknown_field", "/permissions/extra"),
            ("invalid_value", "/permissions/preset"),
            ("missing_field", "/permissions/rules/0"),
            ("pattern_mismatch", "/permissions/rules/0/rule"),
            ("pattern_mismatch", "/permissions/rules/1/rule"),
            ("unknown_field", "/permissions/rules/1/why"),
            ("invalid_value", "/permissions/toolsets/run"),
            ("invalid_key", "/permissions/toolsets/shell"),
        ]


def test_user_settings_schema() -> None:
    data = {"format": "kookabug.user-settings/0", "permissions": PERMISSIONS}
    assert check_shape(data) == []
    assert check_shape({"format": "kookabug.user-settings/0"}) == []
    assert codes(check_shape({"permissions": {}}, "user-settings")) == [("missing_field", "")]
    # 사용자 설정에는 워크스페이스 값(settings·profiles)을 두지 않는다
    assert codes(check_shape(data | {"settings": {}})) == [("unknown_field", "/settings")]
    model = UserSettings.model_validate(data)
    assert model.permissions is not None and model.permissions.preset == "graph_author"


def node_file(*nodes: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": "kookabug.nodes/0",
        "nodes": list(nodes),
        "plugin": {"id": "core", "title": "코어", "version": "0.1.0"},
    }


WAIT_ANY = {
    "category": "image",
    "config": {"exits": {"min_items": 2, "type": "list[string]"}},
    "description": "여러 대상 중 먼저 보이는 것",
    "effects": ["capture"],
    "exits": {
        "extra": [{"kind": "fail", "name": "timeout", "outputs": []}],
        "from_config": "exits",
        "kind": "ok",
        "outputs": ["match"],
    },
    "inputs": {
        "targets": {"type": "dict[str,target]"},
        "timeout_ms": {"default": 10000, "minimum": 1, "type": "int"},
    },
    "outputs": {"match": {"type": "match"}},
    "retry": {"mode": "observation", "on": ["timeout"]},
    "title": "여러 대상 중 먼저 보이는 것",
    "type": "core.image.wait_any",
    "version": 1,
}


def test_node_schema_dynamic_exits_shape() -> None:
    assert check_shape(node_file(WAIT_ANY)) == []
    model = NodeSchemaFile.model_validate(node_file(WAIT_ANY))
    assert isinstance(model.nodes[0].exits, DynamicExits)
    assert model.nodes[0].exits.from_config.root == "exits"

    bad = copy.deepcopy(WAIT_ANY)
    del bad["exits"]["outputs"]
    bad["exits"]["from_config"] = "Exits"
    bad["exits"]["extra"][0]["kind"] = "error"
    assert codes(check_shape(node_file(bad))) == [
        ("missing_field", "/nodes/0/exits"),
        ("invalid_value", "/nodes/0/exits/extra/0/kind"),
        ("pattern_mismatch", "/nodes/0/exits/from_config"),
    ]


def test_node_schema_static_exits_and_retry_decl() -> None:
    wait = {
        "effects": ["capture"],
        "exits": [
            {"kind": "ok", "name": "found", "outputs": ["match"]},
            {"kind": "fail", "name": "timeout", "outputs": []},
        ],
        "inputs": {"target": {"type": "target"}},
        "outputs": {"match": {"type": "match"}},
        "retry": {"mode": "observation", "on": ["timeout"]},
        "title": "이미지 대기",
        "type": "core.image.wait",
        "version": 1,
    }
    assert check_shape(node_file(wait)) == []

    bad = copy.deepcopy(wait)
    bad["retry"] = {"mode": "observation"}
    bad["exits"][0]["outputs"] = ["match", "match"]
    del bad["exits"][1]["outputs"]
    bad["effects"] = ["network"]
    assert codes(check_shape(node_file(bad))) == [
        ("invalid_value", "/nodes/0/effects/0"),
        ("duplicate_item", "/nodes/0/exits/0/outputs"),
        ("missing_field", "/nodes/0/exits/1"),
        ("missing_field", "/nodes/0/retry"),
    ]
    bad = copy.deepcopy(wait) | {"retry": {"mode": "never", "on": ["timeout"]}}
    assert codes(check_shape(node_file(bad))) == [("not_allowed", "/nodes/0/retry")]


GRAPH_CALL = {
    "config": {"graph": {"description": "워크스페이스 기준 서브그래프 경로", "type": "string"}},
    "engine": "graph_call",
    "exits": {"from_interface": "exits"},
    "inputs": {"from_interface": "inputs"},
    "outputs": {"from_interface": "outputs"},
    "title": "서브그래프 호출",
    "type": "core.graph.call",
    "version": 1,
}
VAR_GET = {
    "inputs": {"default": {"default": None, "type": "any"}, "name": {"type": "string"}},
    "outputs": {"value": {"type": "any"}},
    "pure": True,
    "title": "변수 읽기",
    "type": "core.var.get",
    "version": 1,
}
TEST_PASS = {
    "assertion": False,
    "engine": "test_pass",
    "exits": [],
    "inputs": {"reason": {"default": "", "type": "string"}},
    "title": "테스트 성공",
    "type": "core.test.pass",
    "version": 1,
}


def test_node_schema_from_interface_and_engine_shape() -> None:
    assert check_shape(node_file(GRAPH_CALL, TEST_PASS, VAR_GET)) == []
    model = NodeSchemaFile.model_validate(node_file(GRAPH_CALL))
    assert isinstance(model.nodes[0].inputs, FromInterface)
    assert model.nodes[0].engine == "graph_call"

    bad = copy.deepcopy(GRAPH_CALL)
    bad["inputs"] = {"from_interface": "settings"}
    bad["engine"] = "Graph.Call"
    assert codes(check_shape(node_file(bad))) == [
        ("pattern_mismatch", "/nodes/0/engine"),
        ("invalid_value", "/nodes/0/inputs/from_interface"),
    ]


def test_node_schema_pure_and_exec_rules() -> None:
    # 순수 노드는 출구·효과·재시도를 가질 수 없다
    pure_bad = VAR_GET | {"exits": [], "effects": ["capture"]}
    diags = check_shape(node_file(pure_bad))
    assert codes(diags) == [("not_allowed", "/nodes/0")]
    assert "'effects'" in diags[0].message and "'exits'" in diags[0].message
    # exec 노드는 출구 목록이 있어야 한다 (종료 노드는 빈 배열)
    no_exits = {k: v for k, v in TEST_PASS.items() if k != "exits"}
    assert codes(check_shape(node_file(no_exits))) == [("missing_field", "/nodes/0")]


def test_node_schema_optional_input_pin() -> None:
    # optional = default 없이 생략할 수 있는 입력 (생략과 null을 구분). default와 같이 쓰지 않는다
    optional = {"nullable": True, "optional": True, "type": "any"}
    assert check_shape(node_file(VAR_GET | {"inputs": {"default": optional}})) == []
    both = optional | {"default": None}
    diags = check_shape(node_file(VAR_GET | {"inputs": {"default": both}}))
    assert codes(diags) == [("not_allowed", "/nodes/0/inputs/default")]
    not_true = {"optional": False, "type": "any"}
    assert codes(check_shape(node_file(VAR_GET | {"inputs": {"default": not_true}}))) == [
        ("invalid_value", "/nodes/0/inputs/default/optional")
    ]


def test_node_schema_file_fields() -> None:
    data = node_file(TEST_PASS)
    data["plugin"]["id"] = "Core"
    data["extra"] = 1
    data["nodes"][0] = TEST_PASS | {"type": "core", "inputs": {"Reason": {"type": "str"}}}
    assert codes(check_shape(data)) == [
        ("unknown_field", "/extra"),
        ("invalid_key", "/nodes/0/inputs/Reason"),
        ("invalid_pin_type", "/nodes/0/inputs/Reason/type"),
        ("pattern_mismatch", "/nodes/0/type"),
        ("pattern_mismatch", "/plugin/id"),
    ]


def test_shared_defs_identical_across_files() -> None:
    # 생성기가 파일 간 $ref를 풀지 못해 공용 정의를 파일마다 복사했다. 어긋나면 실패
    # (설명 문구는 파일마다 다를 수 있다)
    seen: dict[str, tuple[str, Any]] = {}
    shared = 0
    for kind in KINDS:
        for name, full in metaschema(kind)["$defs"].items():
            schema = {k: v for k, v in full.items() if k != "description"}
            if name in seen:
                first_kind, first = seen[name]
                assert schema == first, f"$defs/{name}: {first_kind}와 {kind}가 다르다"
                shared += 1
            else:
                seen[name] = (kind, schema)
    assert shared >= 9


def test_ecma_pattern_translation() -> None:
    assert ecma_regex(r"^a$").pattern == r"^a\Z"
    assert ecma_regex(r"^\$[$]x$").pattern == r"^\$[$]x\Z"
    assert ecma_regex(r"^[^\\]+\.json$").search("a.json\n") is None


@pytest.mark.parametrize(
    "kind", ["graph", "target", "workspace", "local", "node-schema", "run", "user-settings"]
)
def test_empty_object_reports_required_fields(kind: Any) -> None:
    diags = check_shape({}, kind)
    assert diags
    assert {d.code for d in diags} == {"missing_field"}
