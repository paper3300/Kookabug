"""`kookabug-sdk new` (M6 D13): 틀이 build를 통과하고, 폴더 원천으로 실제 설치·실행된다.
위젯 틀·ui-sdk 사본."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from helpers.plugins import Rig, plugin_world, rig, run_node  # noqa: F401  (픽스처)

from kookabug_sdk.build import BuildError, build
from kookabug_sdk.cli import main
from kookabug_sdk.new import NewProjectError, create_project, sdk_range

REPO = Path(__file__).resolve().parents[3]
UI_SDK = REPO / "packages" / "ui-sdk" / "index.js"


def test_sdk_range_follows_minor() -> None:
    assert sdk_range("0.1.0.dev0") == ">=0.1.0.dev0,<0.2"
    assert sdk_range("0.3.2") == ">=0.3,<0.4"
    assert sdk_range("0.4.0rc1") == ">=0.4.0rc1,<0.5"
    assert sdk_range("1.2.0") == ">=1.2,<2"


def test_new_refuses_bad_id_and_non_empty_folder(tmp_path: Path) -> None:
    for bad in ("Acme", "1x", "core", "testkit", "a-b"):
        with pytest.raises(NewProjectError):
            create_project(tmp_path / bad, bad)
    (tmp_path / "full").mkdir()
    (tmp_path / "full" / "x.txt").write_text("x", encoding="utf-8")
    with pytest.raises(NewProjectError):
        create_project(tmp_path / "full", "acme")
    assert main(["new", str(tmp_path / "full"), "--id", "acme"]) == 1


def test_new_template_builds_with_widget(tmp_path: Path) -> None:
    project = tmp_path / "acme-tools"
    assert main(["new", str(project), "--id", "acme_tools", "--title", "Acme Tools", "--ui"]) == 0
    out = build(project)
    header = out.document["plugin"]
    assert header["id"] == "acme_tools"
    assert header["title"] == "Acme Tools"
    assert header["modules"] == ["kookabug_plugin_acme_tools.nodes"]
    assert header["ui"] == "ui"
    nodes = {n["type"]: n for n in out.document["nodes"]}
    assert set(nodes) == {"acme_tools.text.upper", "acme_tools.value.pick"}
    assert nodes["acme_tools.value.pick"]["config"]["value"]["ui"] == {
        "widget": "acme_tools.choice"
    }
    text = (project / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "kookabug-plugin-acme-tools"' in text
    assert "kookabug-sdk>=0.1.0.dev0,<0.2" in text
    # ui-sdk 사본은 패키지 원본과 같다
    copied = project / "src" / "kookabug_plugin_acme_tools" / "ui" / "kookabug-ui.js"
    assert copied.read_bytes() == UI_SDK.read_bytes()

    # --ui 없이: 위젯·ui 폴더 없음
    plain = tmp_path / "plain"
    create_project(plain, "plain")
    doc = build(plain).document
    assert "ui" not in doc["plugin"]
    assert not (plain / "src" / "kookabug_plugin_plain" / "ui").exists()


def test_ui_sdk_copies_match_package() -> None:
    """위젯은 자기 ui 폴더 파일만 읽으므로 ui-sdk를 사본으로 둔다 — 사본은 원본과 같아야
    한다 (RELEASING.md)."""
    copies = [
        REPO / "python/kookabug_sdk/src/kookabug_sdk/templates/plugin/ui/kookabug-ui.js",
        *REPO.glob("examples/plugins/*/src/*/ui/kookabug-ui.js"),
        *REPO.glob("fixtures/plugins/*/src/*/ui/kookabug-ui.js"),
    ]
    assert len(copies) >= 3
    for copy in copies:
        assert copy.read_bytes() == UI_SDK.read_bytes(), copy


def test_widget_without_ui_folder_or_on_secret_fails(tmp_path: Path) -> None:
    project = tmp_path / "w"
    create_project(project, "wid", ui=True)
    pyproject = project / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('ui = "ui"\n', ""), encoding="utf-8"
    )
    with pytest.raises(BuildError, match="ui 폴더"):
        build(project)
    nodes = project / "src" / "kookabug_plugin_wid" / "nodes.py"
    nodes.write_text(
        nodes.read_text(encoding="utf-8")
        .replace("Config(str,", "Config(Secret,")
        .replace("from kookabug_sdk import", "from kookabug_sdk import Secret,"),
        encoding="utf-8",
    )
    with pytest.raises(BuildError, match="비밀값"):
        build(project, write=False)


@pytest.mark.packaging
@pytest.mark.process
@pytest.mark.timeout(600)
def test_new_template_builds_and_installs(rig: Rig, tmp_path: Path) -> None:  # noqa: F811
    project = tmp_path / "outside" / "acme"
    create_project(project, "acme", ui=True)
    # 폴더 원천: 승인 뒤 staging에서 스키마 생성·wheel 빌드 → 잠금·커밋 wheel·환경
    rig.ops().add(str(project), confirm=lambda _: True)
    lock = rig.lock()
    entry = next(p for p in lock["plugins"] if p["id"] == "acme")
    assert entry["manifest"]["ui"] == "ui"
    assert entry["manifest"]["modules"] == ["kookabug_plugin_acme.nodes"]
    assert (rig.root / entry["wheel"]).is_file()
    env = rig.env_dir(entry["env"])
    site = env / "Lib" / "site-packages" / "kookabug_plugin_acme"
    assert (site / "ui" / "index.js").is_file()
    schema = json.loads((site / "kookabug.schema.json").read_text(encoding="utf-8"))
    assert {n["type"] for n in schema["nodes"]} == {"acme.text.upper", "acme.value.pick"}
    out = run_node(env, ["kookabug_plugin_acme.nodes"], "acme.text.upper", {"text": "ab"})
    assert out["outputs"] == {"text": "AB"}
    # 원본 폴더에는 아무것도 쓰지 않는다 (스키마 파일은 staging 사본에서 만든다)
    assert not (project / "src" / "kookabug_plugin_acme" / "kookabug.schema.json").exists()
