import json
import sys
import textwrap
from pathlib import Path

import pytest

from kookabug_core.schema import check_shape
from kookabug_sdk.build import BuildError, build, dumps
from kookabug_sdk.cli import main
from kookabug_sdk.schema import SCHEMA_FILE, load_installed

# 모든 선언 기능을 한 번씩 쓰는 플러그인. 일부러 type 역순으로 선언한다
NODES = '''
from typing import Annotated, Any, Literal

from kookabug_sdk import (
    Config, Context, DynamicExits, Exit, FromInterface, Input, Output, Result, Retry, node,
)
from kookabug_sdk.types import Match, Secret, Target


@node(
    type="{id}.image.wait_any",
    version=2,
    title="여러 대상 중 먼저 보이는 것",
    category="image",
    config={{"exits": Config(list[str], min_items=2, description="출구 순서")}},
    exits=DynamicExits(from_config="exits", kind="ok", extra=[Exit("timeout", "fail")]),
    outputs={{"match": Match}},
    effects={{"capture"}},
    retry=Retry.observation(on=["timeout"]),
)
def wait_any(ctx: Context, targets: dict[str, Target], timeout_ms: int = 10000) -> Result:
    """먼저 보이는 대상의 출구로 나간다."""
    return Result.fail("timeout")


@node(
    type="{id}.input.type_text",
    version=1,
    title="글자 입력",
    exits=[Exit("done", "ok")],
    effects={{"input"}},
)
def type_text(ctx: Context, text: str | Secret, clear: bool = False) -> Result:
    return Result.ok("done")


@node(
    type="{id}.assert.compare",
    version=1,
    title="값 비교 검증",
    exits=[Exit("ok", "ok"), Exit("fail", "fail")],
    assertion=True,
)
def assert_compare(
    ctx: Context, a: Any, op: Literal["==", "!="], b: Any, note: str | None = None
) -> Result:
    return Result.ok("ok")


@node(
    type="{id}.logic.clamp",
    version=1,
    title="범위 제한",
    pure=True,
    outputs={{"value": Output(int, description="결과"), "clamped": bool | None}},
)
def clamp(ctx: Context, value: int, low: Annotated[int, Input(minimum=0, maximum=100)] = 0):
    return {{"value": max(value, low), "clamped": value < low}}
'''

ENGINE_NODES = """
from kookabug_sdk import Config, Context, Exit, FromInterface, Result, node


@node(
    type="core.graph.call",
    version=1,
    title="서브그래프 호출",
    config={"graph": Config(str)},
    inputs=FromInterface("inputs"),
    outputs=FromInterface("outputs"),
    exits=FromInterface("exits"),
    engine="call",
)
def call(ctx: Context) -> Result:
    raise AssertionError


@node(type="core.test.pass", version=1, title="성공", exits=[], engine="test_pass")
def test_pass(ctx: Context, reason: str = "") -> Result:
    raise AssertionError
"""


def make_project(
    root: Path,
    package: str,
    plugin_id: str,
    nodes: str,
    *,
    module: str = "nodes",
    permissions: str = '["capture", "input"]',
) -> Path:
    """`root/<package>` 아래 src 레이아웃 플러그인 프로젝트를 만든다."""
    project = root / package
    *packages, leaf = [package, *module.split(".")]
    folder = project / "src"
    for part in packages:
        folder = folder / part
        folder.mkdir(parents=True)
        (folder / "__init__.py").touch()
    (folder / f"{leaf}.py").write_text(nodes, encoding="utf-8")
    (project / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "{package.replace("_", "-")}"
            version = "0.3.0"
            dependencies = ["kookabug-sdk"]

            [tool.kookabug]
            id = "{plugin_id}"
            title = "샘플"
            modules = ["{package}.{module}"]
            permissions = {permissions}
            """
        ),
        encoding="utf-8",
    )
    return project


def test_build_output_validates_against_node_schema_metaschema(tmp_path: Path) -> None:
    project = make_project(tmp_path, "kbt_valid", "sample", NODES.format(id="sample"))
    out = build(project)
    assert check_shape(out.document, "node-schema") == []
    assert check_shape(json.loads(out.path.read_text(encoding="utf-8")), "node-schema") == []
    assert out.document["plugin"] == {"id": "sample", "title": "샘플", "version": "0.3.0"}

    core = make_project(tmp_path, "kbt_core", "core", ENGINE_NODES, permissions="[]")
    assert check_shape(build(core).document, "node-schema") == []


def test_build_is_deterministic_and_sorted(tmp_path: Path) -> None:
    project = make_project(tmp_path, "kbt_det", "sample", NODES.format(id="sample"))
    first = build(project)
    second = build(project)
    assert first.text == second.text
    assert first.path.read_bytes() == first.text.encode("utf-8")
    assert b"\r\n" not in first.path.read_bytes()

    types = [n["type"] for n in first.document["nodes"]]
    assert types == sorted(types)
    assert types == [
        "sample.assert.compare",
        "sample.image.wait_any",
        "sample.input.type_text",
        "sample.logic.clamp",
    ]
    assert (
        first.text
        == json.dumps(first.document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )
    assert str(tmp_path) not in first.text  # 환경 값이 들어가지 않는다


def test_build_writes_inside_top_level_package(tmp_path: Path) -> None:
    project = make_project(
        tmp_path, "kbt_nested", "sample", NODES.format(id="sample"), module="sub.nodes"
    )
    out = build(project)
    assert out.path == (project / "src" / "kbt_nested" / SCHEMA_FILE).resolve()
    assert out.path.is_file()
    assert not (project / "kookabug").exists()
    assert not (project / "src" / "kbt_nested" / "sub" / SCHEMA_FILE).exists()


def test_build_cleans_up_imported_modules(tmp_path: Path) -> None:
    project = make_project(tmp_path, "kbt_clean", "sample", NODES.format(id="sample"))
    build(project)
    assert not [m for m in sys.modules if m.startswith("kbt_clean")]
    assert str(project / "src") not in sys.path


@pytest.mark.parametrize(
    ("nodes", "permissions", "message"),
    [
        (NODES.format(id="other"), '["capture", "input"]', "플러그인 ID 'sample.'"),
        (NODES.format(id="sample"), '["capture"]', "permissions에 선언"),
        ("x = 1\n", "[]", "@node 노드가 없다"),
        ("raise RuntimeError('boom')\n", "[]", "RuntimeError: boom"),
        (
            NODES.format(id="sample").replace(
                'effects={"input"}', 'effects={"input"}, retry=Retry.observation(on=["done"])'
            ),
            '["capture", "input"]',
            "관측 재시도",
        ),
    ],
    ids=["prefix", "permissions", "empty", "import_error", "declaration_error"],
)
def test_build_errors(tmp_path: Path, nodes: str, permissions: str, message: str) -> None:
    project = make_project(tmp_path, "kbt_err", "sample", nodes, permissions=permissions)
    with pytest.raises(BuildError, match=message):
        build(project)
    assert not (project / "src" / "kbt_err" / SCHEMA_FILE).exists()


def test_build_rejects_bad_tool_section(tmp_path: Path) -> None:
    project = make_project(tmp_path, "kbt_tool", "sample", NODES.format(id="sample"))
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('id = "sample"', 'id = "Bad-Id"'),
        encoding="utf-8",
    )
    with pytest.raises(BuildError, match="id는"):
        build(project)


def test_cli_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project = make_project(tmp_path, "kbt_cli", "sample", NODES.format(id="sample"))
    assert main(["build", str(project)]) == 0
    assert "4개 노드" in capsys.readouterr().out
    bad = make_project(tmp_path, "kbt_cli_bad", "sample", "x = 1\n", permissions="[]")
    assert main(["build", str(bad)]) == 1
    assert "오류:" in capsys.readouterr().err


def test_load_installed_reads_package_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path, "kbt_load", "sample", NODES.format(id="sample"))
    out = build(project)
    monkeypatch.syspath_prepend(str(project / "src"))
    try:
        assert load_installed("kbt_load") == out.document
    finally:
        for name in [m for m in sys.modules if m.startswith("kbt_load")]:
            del sys.modules[name]

    empty = tmp_path / "site" / "kbt_empty"
    empty.mkdir(parents=True)
    (empty / "__init__.py").touch()
    monkeypatch.syspath_prepend(str(empty.parent))
    with pytest.raises(FileNotFoundError, match="kookabug-sdk build"):
        load_installed("kbt_empty")


@pytest.mark.parametrize(
    "decl",
    [
        "Config(list[str], min_items=-1)",
        'Config(float, minimum=float("nan"))',
        "Config(int, default=2**53)",
        'outputs={"state": Literal["ready", "done"]}',
    ],
    ids=["negative_min_items", "nan_minimum", "unsafe_int_default", "literal_output"],
)
def test_build_rejects_declarations_metaschema_would_reject(tmp_path: Path, decl: str) -> None:
    # 검수 T3_1 반례: 이전에는 build가 성공하고 메타스키마에 맞지 않는(또는 NaN이 든) 파일을 썼다
    is_output = decl.startswith("outputs=")
    decorator_arg = decl if is_output else f'config={{"value": {decl}}}'
    nodes = textwrap.dedent(
        f"""\
        from typing import Literal
        from kookabug_sdk import Config, Context, node

        @node(type="sample.value.probe", version=1, title="t", pure=True, {decorator_arg})
        def probe(ctx: Context):
            return {{}}
        """
    )
    project = make_project(tmp_path, "kbt_decl", "sample", nodes, permissions="[]")
    with pytest.raises(BuildError):
        build(project)
    assert not (project / "src" / "kbt_decl" / SCHEMA_FILE).exists()
    assert main(["build", str(project)]) == 1


def test_dumps_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        dumps({"x": float("nan")})
