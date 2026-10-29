from importlib import resources
from typing import Any

import pytest

import gen_schema
from kb_testing.doc_examples import json_blocks
from kb_testing.packaging import REPO_ROOT
from kookabug_core.schema import KINDS, check_shape, kind_of
from kookabug_core.schema.models.graph import Graph
from kookabug_core.schema.models.target import Target
from kookabug_core.schema.models.workspace import Workspace

PACKAGE_JSON = REPO_ROOT / "packages" / "schema"


def test_generated_python_up_to_date() -> None:
    assert gen_schema.check_sources() == []
    stale = gen_schema.stale_outputs(gen_schema.expected_outputs())
    assert stale == [], "uv run python tools/gen_schema.py 로 다시 만든다"


def test_stale_outputs_detects_changed_missing_and_extra(tmp_path: Any, monkeypatch: Any) -> None:
    # 드리프트 검사 자체가 차이를 잡는지 (임시 폴더에서)
    monkeypatch.setattr(gen_schema, "CORE_SCHEMA", tmp_path)
    (tmp_path / "json").mkdir()
    (tmp_path / "models").mkdir()
    same, changed, missing = (tmp_path / "models" / n for n in ("a.py", "b.py", "c.py"))
    extra = tmp_path / "json" / "old.schema.json"
    same.write_bytes(b"x")
    changed.write_bytes(b"old")
    extra.write_bytes(b"{}")
    expected = {same: b"x", changed: b"new", missing: b"y"}
    assert gen_schema.stale_outputs(expected) == sorted([changed, missing, extra])


def test_metaschema_source_must_be_canonical(tmp_path: Any, monkeypatch: Any) -> None:
    for kind in KINDS:
        (tmp_path / f"{kind}.schema.json").write_bytes(
            (PACKAGE_JSON / f"{kind}.schema.json").read_bytes()
        )
    monkeypatch.setattr(gen_schema, "SCHEMA_DIR", tmp_path)
    monkeypatch.setattr(gen_schema, "REPO_ROOT", tmp_path)
    assert gen_schema.check_sources() == []
    (tmp_path / "local.schema.json").write_text('{"type": "object"}\n', encoding="utf-8")
    assert gen_schema.check_sources() == ["local.schema.json: canonical 형식이 아니다"]


def test_copied_json_matches_packages_schema() -> None:
    copied = resources.files("kookabug_core.schema").joinpath("json")
    names = sorted(p.name for p in copied.iterdir() if p.name.endswith(".json"))
    assert names == sorted(f"{k}.schema.json" for k in KINDS)
    for kind in KINDS:
        source = (PACKAGE_JSON / f"{kind}.schema.json").read_bytes()
        assert copied.joinpath(f"{kind}.schema.json").read_bytes() == source


def test_ts_generated_for_every_schema() -> None:
    generated = PACKAGE_JSON / "src" / "generated"
    assert sorted(p.name for p in generated.glob("*.ts")) == sorted(f"{k}.ts" for k in KINDS)


MODELS: dict[str, Any] = {"graph": Graph, "target": Target, "workspace": Workspace}


@pytest.mark.parametrize(
    "block", [b for b in json_blocks() if "format" in b.data], ids=lambda b: b.id
)
def test_pydantic_parses_doc_examples(block: Any) -> None:
    data = block.data
    kind = kind_of(data)
    assert kind in MODELS and check_shape(data) == []
    model = MODELS[kind].model_validate(data)
    # 모델이 값을 빠뜨리지 않는다 (숫자는 float가 될 수 있지만 같은 값이다)
    assert model.model_dump(mode="json", by_alias=True, exclude_unset=True) == data


def test_pydantic_typed_access() -> None:
    blocks = {b.id: b.data for b in json_blocks()}
    enter_world = Graph.model_validate(blocks["schema#0"])
    assert enter_world.interface is not None
    assert enter_world.interface.exits["login_failed"].kind == "fail"
    assert enter_world.interface.inputs is not None
    assert enter_world.interface.inputs["password"].type.root == "secret"
    launch = enter_world.nodes["n_launch"]
    assert launch.in_ is not None
    assert launch.in_["path"] == {"$setting": "game.executable"}
    wait_lobby = enter_world.nodes["n_wait_lobby"]
    # config는 노드마다 다른 키를 그대로 갖고 있다
    assert wait_lobby.config is not None
    assert wait_lobby.config.model_extra == {"exits": ["error", "lobby"]}
