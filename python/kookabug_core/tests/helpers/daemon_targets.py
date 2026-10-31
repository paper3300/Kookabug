"""daemon target 편집 검사 헬퍼 (M2 T6).

    root = target_workspace(tmp_path)              # 예제 워크스페이스 + captures/ 정지 화면 PNG
    with ThreadDaemon(root) as d, d.client() as client:
        ed = Editor(client)
        frame = ed.load("captures/title.png")
        saved = ed.save("targets/new/a.target.json", frame, START_BUTTON)

`captures/`의 무늬 화면(`pattern_*.png`)은 잡음 배경에 무늬(`PATTERN`)를 0·1·2번 넣은 것이다.
무늬 자리는 `PATTERN_AT`(하나), `PATTERN_AT`·`PATTERN_AT2`(둘)다.
"""

from __future__ import annotations

import ctypes
import shutil
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

from kb_testing.sample_game import FRAMES_DIR, copy_example_workspace
from kookabug_daemon.client import DaemonClient

__all__ = [
    "CAPTURES",
    "PATTERN",
    "PATTERN_AT",
    "PATTERN_AT2",
    "START_BUTTON",
    "Editor",
    "locked_file",
    "same_frame_match",
    "snapshot",
    "target_workspace",
    "write_png",
]

CAPTURES: Final = "captures"
START_BUTTON: Final = (412, 380, 200, 64)
"""예제 게임 타이틀 화면의 시작 버튼 (화면에 한 번만 있다)."""
PATTERN: Final = (40, 30)
PATTERN_AT: Final = (60, 50)
PATTERN_AT2: Final = (280, 190)
_SIZE: Final = (400, 300)


def write_png(path: Path, pixels: Any) -> None:
    ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels))
    assert ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.tobytes())


def _pattern_frames(folder: Path) -> None:
    rng = np.random.default_rng(7)
    w, h = _SIZE
    background = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    pattern = np.random.default_rng(11).integers(0, 256, (PATTERN[1], PATTERN[0], 3), np.uint8)

    def place(image: Any, at: tuple[int, int], patch: Any) -> Any:
        x, y = at
        image[y : y + PATTERN[1], x : x + PATTERN[0]] = patch
        return image

    write_png(folder / "pattern_none.png", background)
    write_png(folder / "pattern_one.png", place(background.copy(), PATTERN_AT, pattern))
    two = place(place(background.copy(), PATTERN_AT, pattern), PATTERN_AT2, pattern)
    write_png(folder / "pattern_two.png", two)
    # 무늬를 잡음과 반씩 섞은 화면: 점수가 1보다 낮다 (임계값 바꾸기 검사)
    x, y = PATTERN_AT
    region = background[y : y + PATTERN[1], x : x + PATTERN[0]].astype(np.int32)
    faded = ((pattern.astype(np.int32) * 6 + region * 4) // 10).astype(np.uint8)
    write_png(folder / "pattern_faded.png", place(background.copy(), PATTERN_AT, faded))


def target_workspace(tmp_path: Path) -> Path:
    """예제 워크스페이스 사본(가짜 플랫폼 사양이 맞는 자리) + `captures/` 정지 화면 PNG.
    daemon이 쓰는 경로와 비교할 수 있게 해석한 절대 경로를 돌려준다."""
    root = copy_example_workspace(tmp_path).resolve()
    folder = root / CAPTURES
    folder.mkdir()
    for name in ("title", "login", "lobby"):
        shutil.copy(FRAMES_DIR / f"{name}.png", folder / f"{name}.png")
    _pattern_frames(folder)
    return root


def snapshot(folder: Path) -> dict[str, tuple[bytes, int]]:
    """폴더 아래 파일 → (바이트, mtime_ns). `.kookabug/`·`runs/`는 뺀다."""
    found: dict[str, tuple[bytes, int]] = {}
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if rel.split("/", 1)[0] in (".kookabug", "runs") or not path.is_file():
            continue
        found[rel] = (path.read_bytes(), path.stat().st_mtime_ns)
    return found


@dataclass
class Editor:
    """target 편집 메서드를 부르는 얇은 감싸개."""

    client: DaemonClient
    seq: int = 0

    def load(self, path: str) -> dict[str, Any]:
        return self.client.call("target.load_image", {"path": path})

    def open(self, path: str) -> dict[str, Any]:
        return self.client.call("target.open", {"path": path})

    def preview(
        self,
        frame: Mapping[str, Any],
        spec: Mapping[str, Any] | None = None,
        *,
        crop: tuple[Mapping[str, Any], tuple[int, int, int, int]] | None = None,
        image: str | None = None,
        base: str | None = None,
        seq: int | None = None,
    ) -> dict[str, Any]:
        if seq is None:
            self.seq += 1
            seq = self.seq
        template: dict[str, Any]
        if crop is not None:
            template = {"crop": {"frame_id": crop[0]["frame_id"], "rect": list(crop[1])}}
        else:
            assert image is not None
            template = {"image": image}
        params: dict[str, Any] = {
            "frame_id": frame["frame_id"],
            "spec": dict(spec or {}),
            "template": template,
            "seq": seq,
        }
        if base is not None:
            params["base_path"] = base
        return self.client.call("target.preview", params)

    def save(
        self,
        path: str,
        frame: Mapping[str, Any],
        rect: tuple[int, int, int, int],
        spec: Mapping[str, Any] | None = None,
        base_revision: str | None = None,
    ) -> dict[str, Any]:
        return self.client.call(
            "target.save",
            {
                "path": path,
                "spec": dict(spec or {}),
                "crop": {"frame_id": frame["frame_id"], "rect": list(rect)},
                "base_revision": base_revision,
            },
        )


@contextmanager
def locked_file(path: Path) -> Iterator[None]:
    """그 파일을 공유 없이(`CreateFileW` 공유 모드 0) 열어 두어 다른 곳에서 읽지 못하게 한다."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    generic_read, open_existing, normal = 0x80000000, 3, 0x80
    handle = create(str(path), generic_read, 0, None, open_existing, normal, None)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()
    try:
        try:
            path.read_bytes()
        except PermissionError:
            pass
        else:
            raise AssertionError(f"{path}이(가) 잠기지 않았다")
        yield
    finally:
        close(handle)


def same_frame_match(ed: Editor, frame: Mapping[str, Any], target: str) -> dict[str, Any]:
    """그 target 파일(사양·이미지 그대로)을 그 정지 화면에서 찾은 결과 (시간·seq 제외)."""
    opened = ed.open(target)
    image = opened["spec"]["image"]
    result = ed.preview(frame, opened["spec"], image=image, base=target, seq=0)
    return {k: v for k, v in result.items() if k not in ("elapsed_ms", "seq")}
