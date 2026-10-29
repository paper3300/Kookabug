import importlib
from importlib import metadata

import pytest

PACKAGES = [
    ("kookabug-sdk", "kookabug_sdk", "MIT"),
    ("kookabug-nodes", "kookabug_nodes", "Apache-2.0"),
    ("kookabug-core", "kookabug_core", "Apache-2.0"),
]


@pytest.mark.parametrize(("dist", "module", "_license"), PACKAGES)
def test_packages_import_and_versions_match(dist: str, module: str, _license: str) -> None:
    mod = importlib.import_module(module)
    assert mod.__version__ == metadata.version(dist)


def test_all_packages_share_one_version() -> None:
    assert len({metadata.version(dist) for dist, _, _ in PACKAGES}) == 1


@pytest.mark.parametrize(("dist", "_module", "expected"), PACKAGES)
def test_package_licenses(dist: str, _module: str, expected: str) -> None:
    meta = metadata.metadata(dist)
    assert meta["License-Expression"] == expected
