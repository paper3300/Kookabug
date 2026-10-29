"""설치된 플러그인의 노드 스키마 읽기.

`kookabug-sdk build`는 `src/<최상위 패키지>/kookabug.schema.json`을 만든다. 모듈 디렉터리
안에 있으므로 uv_build는 설정 없이 wheel에 넣는다 (다른 빌드 백엔드는 데이터 파일 포함 설정이
따로 필요하다).
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any, Final

__all__ = ["FORMAT", "SCHEMA_FILE", "load_installed"]

SCHEMA_FILE: Final = "kookabug.schema.json"
FORMAT: Final = "kookabug.nodes/0"


def load_installed(package: str) -> dict[str, Any]:
    """설치된 패키지(최상위 import 이름)의 노드 스키마."""
    path = resources.files(package).joinpath(SCHEMA_FILE)
    if not path.is_file():
        raise FileNotFoundError(
            f"{package}에 {SCHEMA_FILE}이(가) 없다 (kookabug-sdk build로 만든다)"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError(f"{package}/{SCHEMA_FILE}의 format이 {FORMAT}이(가) 아니다")
    return data
