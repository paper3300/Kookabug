"""스키마 머리·정규 해시 (M6 계획 3.1·D9): 설치 때(wheel 안 파일)와 실행 때(워커 hello) 같은 값."""

from __future__ import annotations

import zipfile

import pytest
from helpers.plugins import Rig, hello

from kookabug_core.plugins import PluginError
from kookabug_core.plugins.manifest import read_wheel
from kookabug_sdk.schema import schema_digest

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(600)]


def test_file_and_hello_digest_equal(rig: Rig) -> None:
    wheel = rig.world.wheel("sample")
    manifest = read_wheel(wheel)
    header = manifest.header
    # 머리에 title·permissions·ui, 진입 모듈은 최상위 패키지(kookabug_plugin_sample)와 다르다
    assert header["title"] == "Sample"
    assert header["permissions"] == ["capture"]
    assert header["ui"] == "ui"
    assert header["modules"] == [
        "kookabug_plugin_sample.nodes.text",
        "kookabug_plugin_sample.nodes.widgets",
    ]
    with zipfile.ZipFile(wheel) as zf:
        assert "kookabug_plugin_sample/kookabug.schema.json" in zf.namelist()
        assert "kookabug_plugin_sample/ui/index.js" in zf.namelist()
    rig.add("sample")
    entry = rig.lock()["plugins"][0]
    assert entry["schema_sha256"] == manifest.schema_sha256
    assert entry["manifest"]["modules"] == header["modules"]
    plugins = hello(rig.env_dir("shared"), header["modules"])
    assert [p["id"] for p in plugins] == ["sample"]
    got = plugins[0]
    # hello 머리 = 설치된 스키마 파일 머리 전체, 노드 = 코드 선언 → 같은 digest
    assert got["schema"]["plugin"] == header
    assert got["digest"] == schema_digest(got["schema"]) == manifest.schema_sha256


def test_schema_drift_detected(rig: Rig) -> None:
    with pytest.raises(PluginError) as caught:
        rig.add("schema_drift")
    assert caught.value.code == "verify_failed"
    assert "schema digest" in caught.value.message
    assert rig.lock_bytes() is None
