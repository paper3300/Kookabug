"""설치된 플러그인의 노드 스키마 읽기와 정규 해시.

`kookabug-sdk build`는 `src/<최상위 패키지>/kookabug.schema.json`을 만든다. 모듈 디렉터리
안에 있으므로 uv_build는 설정 없이 wheel에 넣는다 (다른 빌드 백엔드는 데이터 파일 포함 설정이
따로 필요하다).

`schema_digest`(M6 계획 3.1·D9): 설치 때(wheel 안 파일)와 실행 때(워커 hello) 같은 함수로 같은
대상을 해시한다 — `{plugin: 머리 전체, nodes: type 순}`의 정규 JSON(키 정렬·공백 없음·UTF-8)
sha256. `format`은 빼고, 파일의 들여쓰기·키 순서와 무관하다.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib import resources
from typing import Any, Final

__all__ = ["FORMAT", "SCHEMA_FILE", "load_installed", "schema_digest", "schema_package"]

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


def schema_package(modules: list[str] | tuple[str, ...]) -> str:
    """스키마 파일이 있는 최상위 패키지 = `modules` 첫 항목의 첫 이름 (M6 3.1)."""
    return modules[0].split(".", 1)[0]


def schema_digest(document: Mapping[str, Any]) -> str:
    """노드 스키마 문서의 정규 해시 (sha256 hex). 노드는 type 순으로 다시 정렬한다."""
    nodes = sorted(document.get("nodes") or [], key=lambda n: str(n.get("type")))
    target = {"plugin": document.get("plugin"), "nodes": nodes}
    text = json.dumps(
        target, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
