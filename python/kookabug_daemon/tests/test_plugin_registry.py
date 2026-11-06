"""daemon 팔레트·사전 검증 레지스트리의 설치 플러그인 (M6 계획 B3, D9): 커밋된 wheel 안 스키마
파일을 읽고 플러그인 코드를 import하지 않는다."""

from __future__ import annotations

import json
import subprocess

import pytest
from helpers.plugins import Rig, plugin_world, rig

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import direct_env, python_cmd
from kookabug_core.schema import check_shape
from kookabug_sdk.schema import schema_digest

__all__ = ["plugin_world", "rig"]

pytestmark = [pytest.mark.packaging, pytest.mark.process, pytest.mark.timeout(600)]

_PROBE = """
import importlib.util, json, sys
from pathlib import Path
from kookabug_daemon.app import plugin_registry

registry = plugin_registry((), Path(sys.argv[1]))()
print(json.dumps({
    "findable": importlib.util.find_spec("kookabug_plugin_sample") is not None,
    "imported": sorted(m for m in sys.modules if m.startswith("kookabug_plugin_sample")),
    "types": sorted(t for t in registry.types() if t.startswith("sample.")),
    "remote": all(registry.get(t).remote for t in registry.types() if t.startswith("sample.")),
    "plugins": dict(registry.plugins),
}))
"""


def test_palette_from_schema_file_no_import(rig: Rig) -> None:
    rig.add("sample")
    entry = rig.lock()["plugins"][0]
    # 별도 daemon 인터프리터: 플러그인 패키지는 import 경로에 없다 → import 없이 등록돼야 한다
    proc = subprocess.run(
        python_cmd("-c", _PROBE, rig.root),
        env=direct_env(rig.world.environ),
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    found = json.loads(proc.stdout.strip().splitlines()[-1])
    assert found["findable"] is False and found["imported"] == []
    assert found["types"] == ["sample.color.pick", "sample.text.reverse", "sample.window.title"]
    assert found["remote"] is True
    assert found["plugins"]["sample"] == "0.1.0"
    # 실제 daemon의 팔레트(`nodes.list`)에 그 스키마 그대로 (잠금의 schema_sha256과 같은 문서)
    with ThreadDaemon(rig.root) as d, d.client() as client:
        result = client.call("nodes.list")
    schemas = {s["plugin"]["id"]: s for s in result["schemas"]}
    assert set(schemas) == {"core", "sample"}
    assert schema_digest(schemas["sample"]) == entry["schema_sha256"]
    assert check_shape(schemas["sample"], "node-schema") == []


def test_tampered_committed_wheel_not_in_palette(rig: Rig) -> None:
    """커밋된 wheel 바이트가 잠금과 다르면 그 플러그인은 팔레트에 없다 (그 그래프는 사전 검증에서
    `unknown_node_type`)."""
    rig.add("sample")
    entry = rig.lock()["plugins"][0]
    wheel = rig.root.joinpath(*str(entry["wheel"]).split("/"))
    wheel.write_bytes(wheel.read_bytes() + b"x")
    with ThreadDaemon(rig.root) as d, d.client() as client:
        result = client.call("nodes.list")
    assert [s["plugin"]["id"] for s in result["schemas"]] == ["core"]
