"""해석의 SDK 후보는 앱 SDK wheel 하나다 (M6 계획 3.3·C1, B1 3라운드).

인덱스에 같은 판(build tag 포함)의 다른 `kookabug-sdk` artifact가 있어도 그 메타데이터·의존성이
해석에 들어오지 않는다. 검사마다 따로 띄운 인덱스(`own_index`)와 빈 uv 캐시를 쓴다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from helpers.plugins import Rig, env_run

from kb_testing.plugin_fixtures import dist_wheel

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(600)]


def _other_sdk(index: Path, version: str, requires: list[str], *, build_tag: bool) -> Path:
    wheel = dist_wheel(
        index, "kookabug-sdk", version, {"kbfix_other_sdk.py": b""}, requires=requires
    )
    if build_tag:
        wheel = wheel.rename(wheel.with_name(wheel.name.replace("-py3-", "-1-py3-")))
    return wheel


def _assert_app_sdk_only(rig: Rig, env: str) -> None:
    lock = rig.lock()
    installed = env_run(
        rig.env_dir(env), "from importlib.metadata import version; print(version('kookabug-sdk'))"
    ).strip()
    assert installed == lock["sdk"]["version"]
    assert all(p["name"] != "kookabug-sdk" for p in lock["environments"][env]["packages"])
    text = (rig.root / "kookabug.lock").read_text(encoding="utf-8")
    # 해석에 쓴 앱 SDK wheel의 로컬 경로(직접 참조)가 잠금에 남지 않는다
    assert "file:" not in text and "kookabug_sdk-" not in text
    # 인덱스의 SDK는 보지도 받지도 않았다
    assert not [r for r in rig.world.index.requests if "kookabug-sdk" in r or "kookabug_sdk" in r]


@pytest.mark.parametrize("build_tag", [False, True], ids=["plain", "build_tag"])
def test_index_same_sdk_artifact_metadata_ignored(
    rig: Rig, own_index: Path, build_tag: bool
) -> None:
    # 인덱스의 같은 판 SDK에만 없는 배포판 요구가 있다: 앱 SDK로 풀면 정상 설치다
    version = rig.ops().app.sdk_version
    _other_sdk(own_index, version, ["kbfix-review-nonexistent==1.0.0"], build_tag=build_tag)
    result = rig.add("sdk_user")
    _assert_app_sdk_only(rig, result["env"])
    assert rig.ops().verify()["ok"]


@pytest.mark.parametrize("isolation", ["auto", "isolated"])
def test_index_sdk_foreign_dependencies_not_locked(
    rig: Rig, own_index: Path, isolation: str
) -> None:
    version = rig.ops().app.sdk_version
    dist_wheel(own_index, "kbfix-review-shadow", "1.0.0", {"kbfix_review_shadow.py": b""})
    _other_sdk(own_index, version, ["kbfix-review-shadow==1.0.0"], build_tag=True)
    result = rig.add("sdk_user", isolation=isolation)
    names = [p["name"] for p in rig.lock()["environments"][result["env"]]["packages"]]
    assert names == ["kbfix-dep", "kbfix-sdk-user"]
    _assert_app_sdk_only(rig, result["env"])
    assert rig.ops().verify()["ok"]
