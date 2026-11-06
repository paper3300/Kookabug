"""설치 정적 검사의 위젯 규칙 (M6 3.10): 자기 플러그인 위젯만, 머리에 ui 폴더,
비밀값 항목에는 위젯 없음."""

from __future__ import annotations

from pathlib import Path

import pytest

from kb_testing.plugin_fixtures import SAMPLE, plugin_wheel
from kookabug_core.plugins import PluginError
from kookabug_core.plugins.manifest import read_wheel, widget_problems


def _node(**config: dict[str, object]) -> dict[str, object]:
    return {"type": "sample.color.pick", "config": config}


def test_widget_problems() -> None:
    ok = _node(color={"type": "string", "ui": {"widget": "sample.color"}}, plain={"type": "int"})
    assert widget_problems("sample", ok, has_ui=True) == []
    assert widget_problems(
        "sample", _node(c={"type": "string", "ui": {"widget": "other.color"}}), has_ui=True
    )
    assert widget_problems("sample", ok, has_ui=False)
    for secret in ("secret", "string|secret", "list[secret]"):
        node = _node(c={"type": secret, "ui": {"widget": "sample.color"}})
        assert any("비밀값" in p for p in widget_problems("sample", node, has_ui=True)), secret


def test_wheel_with_foreign_or_secret_widget_refused(tmp_path: Path) -> None:
    good = read_wheel(plugin_wheel(SAMPLE, tmp_path / "good"))
    assert good.lock_manifest()["ui"] == "ui"

    def foreign(doc: dict[str, object]) -> None:
        for node in doc["nodes"]:  # type: ignore[union-attr]
            for decl in (node.get("config") or {}).values():  # type: ignore[union-attr]
                if "ui" in decl:
                    decl["ui"] = {"widget": "other.color"}

    def secret(doc: dict[str, object]) -> None:
        for node in doc["nodes"]:  # type: ignore[union-attr]
            for decl in (node.get("config") or {}).values():  # type: ignore[union-attr]
                if "ui" in decl:
                    decl["type"] = "secret"

    for edit in (foreign, secret):
        wheel = plugin_wheel(SAMPLE, tmp_path / edit.__name__, schema_edit=edit)
        with pytest.raises(PluginError) as info:
            read_wheel(wheel)
        assert info.value.code == "manifest_invalid"
