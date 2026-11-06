"""환경 digest는 실제 파일 바이트를 본다 (M6 계획 3.3, rev1 M7): RECORD를 믿지 않는다."""

from __future__ import annotations

import json
import os

import pytest
from helpers.plugins import Rig

from kookabug_core.plugins.envs import MARKER, env_digest, find_env, read_marker, verify_env

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(600)]


def test_digest_catches_file_edit_with_record_unchanged(rig: Rig) -> None:
    rig.add("conflict_a")
    env = rig.env_dir("shared")
    lock_env = rig.lock()["environments"]["shared"]
    assert env_digest(env) == lock_env["digest"]
    site = env / "Lib" / "site-packages"
    target = site / "kbfix_dep" / "__init__.py"
    record = next(site.glob("kbfix_dep-*.dist-info")) / "RECORD"
    record_before = record.read_bytes()
    # 새 파일로 바꿔 넣는다 (uv 캐시와 하드 링크일 수 있어 제자리 쓰기를 하지 않는다)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(b'__version__ = "9.9.9"\n')
    os.replace(tmp, target)
    assert record.read_bytes() == record_before
    assert env_digest(env) != lock_env["digest"]
    assert verify_env(env, lock_env["fingerprint"]) is not None
    result = rig.ops().verify()
    assert not result["ok"]
    assert result["environments"]["shared"]["status"] == "broken"
    # 검증은 읽기만 한다: 표식은 그대로
    assert read_marker(env) == {
        "complete": True,
        "digest": lock_env["digest"],
        "env": "shared",
        "fingerprint": lock_env["fingerprint"],
        "link_mode": "copy",
    }


def test_env_without_copy_link_mode_not_reused(rig: Rig) -> None:
    """복사 설치가 아닌(표식에 `link_mode: copy`가 없는) 환경은 없는 것 — 재사용·실행 후보가
    아니고, 같은 지문 재설치는 새 폴더를 만든다."""
    rig.add("sample")
    old = rig.env_dir("shared")
    fp = rig.lock()["environments"]["shared"]["fingerprint"]
    rig.ops().remove("sample", confirm=lambda _: True)
    marker = json.loads((old / MARKER).read_text(encoding="utf-8"))
    del marker["link_mode"]  # 하드 링크로 만든 옛 환경 흉내
    (old / MARKER).write_text(json.dumps(marker), encoding="utf-8")
    assert read_marker(old) is None
    assert find_env(rig.envs, "shared", fp) is None
    result = rig.add("sample")
    assert result["reused"] is False
    assert rig.env_dir("shared") != old
    assert rig.lock()["environments"]["shared"]["fingerprint"] == fp


def test_pycache_and_generated_metadata_not_counted(rig: Rig) -> None:
    rig.add("conflict_a")
    env = rig.env_dir("shared")
    digest = env_digest(env)
    site = env / "Lib" / "site-packages"
    cache = site / "kbfix_dep" / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "x.cpython-314.pyc").write_bytes(b"\0")
    info = next(site.glob("kbfix_dep-*.dist-info"))
    (info / "direct_url.tmp").write_text("{}", encoding="utf-8")
    os.replace(info / "direct_url.tmp", info / "direct_url.json")
    assert env_digest(env) == digest
