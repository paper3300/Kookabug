"""import하면 `KBFIX_MARKER_DIR`에 `import` 표식을 쓴다 (스키마 생성·검증 import 시점 확인)."""

import os
from pathlib import Path

from kookabug_sdk import Context, node

if _folder := os.environ.get("KBFIX_MARKER_DIR"):
    Path(_folder, "import").write_text("ran\n", encoding="utf-8")


@node(type="build_marker.echo", version=1, title="그대로", pure=True, outputs={"text": str})
def echo(ctx: Context, text: str) -> dict[str, str]:
    return {"text": text}
