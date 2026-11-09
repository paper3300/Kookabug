"""예제 상점의 헤드리스 자료 `frames/shop/`(장면 PNG·전이 표·찍은 환경)를 상점 코드에서 다시 만든다.

    uv run python fixtures/sample-game/tools/gen_shop_scenario.py          # 쓴다
    uv run python fixtures/sample-game/tools/gen_shop_scenario.py --check  # 오래됐으면 실패

PNG는 GDI 오프스크린 렌더라 창·대화형 데스크톱이 필요 없다(Windows·`Malgun Gothic` 글꼴은 필요).
`frames.snapshot.json`에 만든 때의 **렌더 관련 소스 sha**(`sample_shop/*.py`·이 파일, 줄바꿈은 LF로
맞춰 셈)·Windows 판·글꼴 파일 sha·장면별 PNG sha를 남기고, 예제 워크스페이스 target 이미지를 PNG에서
자른다(`TARGET_CROPS`).

`--check`(OS와 무관): 전이 표가 코드와 같고, 지금 렌더 소스 sha가 snapshot과 같고(그림을 바꾸는
코드 수정 뒤 다시 만들지 않으면 실패), PNG·snapshot·target이 서로 맞는지 본다. 같은 Windows 판·
글꼴이면 지금 렌더와 PNG를 바이트로도 대조한다.
"""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
from pathlib import Path
from typing import Any

GAME_DIR = Path(__file__).resolve().parents[1]
FRAMES = GAME_DIR / "frames" / "shop"
SCENARIO = FRAMES / "scenario.json"
SNAPSHOT = FRAMES / "frames.snapshot.json"
WORKSPACE = GAME_DIR / "workspace"
RENDER_SOURCES = (
    "sample_shop/__init__.py",
    "sample_shop/flow.py",
    "sample_shop/render.py",
    "sample_shop/scenario.py",
    "tools/gen_shop_scenario.py",
)
"""그림·장면·자르기를 정하는 소스 (`GAME_DIR` 기준)."""
sys.path.insert(0, str(GAME_DIR))

from kookabug_core.canonical import canonical_dumps  # noqa: E402
from sample_shop.flow import BUTTONS  # noqa: E402
from sample_shop.render import FontMissing, font_sha256, render  # noqa: E402
from sample_shop.scenario import BOOT, generate, representatives  # noqa: E402

TARGET_CROPS: dict[str, tuple[str, tuple[int, int, int, int]]] = {
    # target 경로 → (장면, 자를 사각형)
    "targets/shop/buy.png": ("shop", BUTTONS["buy"]),
    "targets/shop/closed_title.png": ("shop_closed", (380, 268, 264, 44)),
    "targets/shop/potion_bought.png": ("shop_bought", (700, 262, 120, 44)),
}


def scenario_text() -> str:
    return canonical_dumps(generate())


def frames() -> dict[str, bytes]:
    out = {scene: render(state) for scene, state in representatives().items()}
    out[BOOT] = render(representatives()["shop"], boot=True)
    return dict(sorted(out.items()))


def source_hashes(game_dir: Path = GAME_DIR) -> dict[str, str]:
    """렌더 관련 소스의 sha256 (CRLF는 LF로 맞춰 센다 — 체크아웃 줄바꿈 설정과 무관)."""
    return {
        rel: hashlib.sha256((game_dir / rel).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for rel in RENDER_SOURCES
    }


def environment() -> dict[str, Any]:
    return {"font_sha256": font_sha256(), "windows": platform.version()}


def crop_png(png: bytes, rect: tuple[int, int, int, int]) -> bytes:
    from kookabug_platform.frames import decode_image, encode_png

    pixels = decode_image(png)
    x, y, w, h = rect
    return encode_png(pixels[y : y + h, x : x + w])


def _same_pixels(a: bytes, b: bytes) -> bool:
    from kookabug_platform.frames import decode_image

    pa, pb = decode_image(a), decode_image(b)
    return pa.shape == pb.shape and bool((pa == pb).all())


def problems() -> list[str]:
    """`--check`가 보는 것. 비면 최신이다."""
    import json

    found: list[str] = []
    current = SCENARIO.read_text(encoding="utf-8") if SCENARIO.exists() else ""
    if current != scenario_text():
        found.append(f"{SCENARIO}가 상점 코드와 다르다")
    if not SNAPSHOT.exists():
        return [*found, f"{SNAPSHOT}가 없다"]
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    recorded = snapshot.get("sources", {})
    for rel, sha in source_hashes().items():
        if recorded.get(rel) != sha:
            found.append(f"렌더 관련 소스 {rel}가 PNG를 만든 뒤 바뀌었다")
    scenes = set(json.loads(current)["scenes"]) if current else set[str]()
    shots = snapshot.get("frames", {})
    if set(shots) != scenes:
        found.append("snapshot의 장면 목록이 전이 표와 다르다")
    pngs: dict[str, bytes] = {}
    for scene, sha in shots.items():
        path = FRAMES / f"{scene}.png"
        data = path.read_bytes() if path.exists() else b""
        pngs[scene] = data
        if hashlib.sha256(data).hexdigest() != sha:
            found.append(f"{path.name}가 snapshot sha와 다르다")
    for rel, (scene, rect) in TARGET_CROPS.items():
        target = WORKSPACE / rel
        if scene not in pngs or not target.exists():
            found.append(f"target 이미지 {rel}가 없다")
        elif not _same_pixels(target.read_bytes(), crop_png(pngs[scene], rect)):
            found.append(f"target 이미지 {rel}가 {scene}.png에서 자른 것과 다르다")
    # 같은 Windows 판·글꼴이면 지금 렌더와 바이트까지 대조한다 (다른 환경은 위 소스 sha가 지킨다)
    try:
        here = environment()
    except FontMissing:
        here = None
    if (
        here is not None
        and here["windows"] == snapshot.get("windows")
        and here["font_sha256"] == snapshot.get("font_sha256")
    ):
        for scene, data in frames().items():
            if pngs.get(scene) != data:
                found.append(f"{scene}.png가 지금 렌더와 다르다")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="예제 상점 헤드리스 자료를 다시 만든다")
    parser.add_argument("--check", action="store_true", help="쓰지 않고 오래됐으면 종료 코드 1")
    args = parser.parse_args(argv)
    if args.check:
        stale = problems()
        for line in stale:
            print(line, file=sys.stderr)
        if stale:
            print("이 스크립트로 다시 만든다", file=sys.stderr)
        return 1 if stale else 0
    FRAMES.mkdir(parents=True, exist_ok=True)
    SCENARIO.write_text(scenario_text(), encoding="utf-8", newline="\n")
    pngs = frames()
    for scene, data in pngs.items():
        (FRAMES / f"{scene}.png").write_bytes(data)
    snapshot = {
        **environment(),
        "format": "kookabug.sample-shop-frames/0",
        "frames": {scene: hashlib.sha256(data).hexdigest() for scene, data in pngs.items()},
        "sources": source_hashes(),
    }
    SNAPSHOT.write_text(canonical_dumps(snapshot), encoding="utf-8", newline="\n")
    for rel, (scene, rect) in TARGET_CROPS.items():
        dest = WORKSPACE / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(crop_png(pngs[scene], rect))
    print(FRAMES)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
