"""매칭 기본 임계값 상수 한 곳 (M4 T12, D2 자리): Python·TS·스키마·스키마 문서의 기본값이 모두
`target.schema.json`의 default 하나에서 나온다. 값은 바꾸지 않는다 (조율자가 D2 결과로 정한다)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Final

from kookabug_platform import vision

REPO: Final = Path(__file__).resolve().parents[3]
SCHEMA: Final = REPO / "packages" / "schema" / "target.schema.json"
TS_CONSTANTS: Final = REPO / "packages" / "schema" / "src" / "generated" / "constants.ts"
EDITOR_SPEC: Final = REPO / "apps" / "desktop" / "src" / "renderer" / "target" / "spec.ts"
SCHEMA_DOC: Final = REPO / "Docs" / "Design" / "그래프 JSON 스키마 v0.md"


def _schema_defaults() -> tuple[float, float]:
    match = json.loads(SCHEMA.read_text(encoding="utf-8"))["$defs"]["Match"]["properties"]
    return match["threshold"]["default"], match["color_tolerance"]["default"]


def _ts_const(name: str) -> float:
    found = re.search(
        rf"export const {name} = ([0-9.]+);", TS_CONSTANTS.read_text(encoding="utf-8")
    )
    assert found is not None, f"{TS_CONSTANTS}에 {name}이 없다 (pnpm -r run gen)"
    return float(found.group(1))


def test_default_threshold_single_source() -> None:
    threshold, tolerance = _schema_defaults()
    # Python: 스키마 값을 읽는다 (패키지 안 사본도 같은 바이트 — gen_schema --check)
    assert threshold == vision.DEFAULT_THRESHOLD
    assert tolerance == vision.DEFAULT_COLOR_TOLERANCE
    assert vision.TargetSpec(name="x", image_path=Path("x.png")).threshold == threshold
    # TS: 생성 상수 (gen.mjs가 같은 default에서 만든다)
    assert _ts_const("DEFAULT_MATCH_THRESHOLD") == threshold
    assert _ts_const("DEFAULT_COLOR_TOLERANCE") == tolerance
    # 편집기는 생성 상수만 쓴다 (숫자를 따로 적지 않는다)
    spec = EDITOR_SPEC.read_text(encoding="utf-8")
    assert "DEFAULT_MATCH_THRESHOLD" in spec
    assert re.search(r"DEFAULT_THRESHOLD\s*=\s*[0-9]", spec) is None, "spec.ts에 기본값 숫자가 있다"
    assert str(threshold) not in spec.replace("0.50", "")
    # 스키마 문서 4장의 기본값 문장
    doc = SCHEMA_DOC.read_text(encoding="utf-8")
    assert f"기본값: `threshold` {threshold}" in doc
