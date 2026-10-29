import ast
import sys
from importlib import metadata
from pathlib import Path

import kookabug_sdk

SRC = Path(kookabug_sdk.__file__).parent


def test_sdk_has_no_runtime_deps() -> None:
    assert not metadata.requires("kookabug-sdk")

    # 표준 라이브러리와 자기 자신만 import한다 (본체 kookabug_core도 안 됨: MIT 분리)
    imported: set[str] = set()
    for path in SRC.rglob("*.py"):
        for stmt in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(stmt, ast.Import):
                imported.update(a.name.split(".")[0] for a in stmt.names)
            elif isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module:
                imported.add(stmt.module.split(".")[0])
    assert imported - {"kookabug_sdk"} <= sys.stdlib_module_names
    assert "kookabug_sdk" in imported
