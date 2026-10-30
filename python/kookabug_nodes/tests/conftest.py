"""앱·창·입력 노드 검사 공용: 예제 게임 화면에서 잘라 만든 target (`targets` 픽스처)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

import pytest

from kb_testing.sample_game import FRAMES_DIR


class Targets:
    """예제 게임 화면 PNG를 잘라 target 파일을 쓴다."""

    # 로그인 화면(1024x640)의 칸 이름표를 잘라 target으로 쓰고, 클릭 지점은 칸 가운데로 옮긴다.
    # 칸 테두리는 포커스에 따라 색이 바뀌므로 이미지에 넣지 않는다.
    # target 경로 → (이름표 상자 [x, y, w, h], 상자 가운데에서 칸 가운데까지 offset)
    LOGIN: Final[dict[str, tuple[tuple[int, int, int, int], tuple[int, int]]]] = {
        "targets/login/account_field.target.json": ((320, 210, 60, 40), (210, 0)),
        "targets/login/password_field.target.json": ((280, 290, 100, 40), (230, 0)),
    }
    ACCOUNT: Final = "targets/login/account_field.target.json"
    PASSWORD: Final = "targets/login/password_field.target.json"

    def crop(
        self,
        root: Path,
        rel: str,
        frame: str,
        rect: tuple[int, int, int, int],
        *,
        offset: tuple[int, int] = (0, 0),
        extra: Mapping[str, Any] | None = None,
    ) -> Path:
        """`frames/<frame>`의 `rect`를 잘라 PNG와 target 파일을 쓴다 (클릭 = 가운데 + offset)."""
        import cv2
        import numpy as np

        from kookabug_platform.frames import decode_image

        pixels = decode_image((FRAMES_DIR / frame).read_bytes())
        x, y, w, h = rect
        ok, data = cv2.imencode(".png", np.ascontiguousarray(pixels[y : y + h, x : x + w]))
        assert ok
        path = root.joinpath(*rel.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        image = path.name.removesuffix(".target.json") + ".png"
        (path.parent / image).write_bytes(data.tobytes())
        body: dict[str, Any] = {
            "click": {"anchor": "center", "offset": list(offset)},
            "format": "kookabug.target/0",
            "image": image,
            "recorded": {"client_size": [1024, 640], "dpi": 96},
            **(extra or {}),
        }
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def login(self, root: Path) -> None:
        """로그인 칸 target 두 개 (`ACCOUNT`·`PASSWORD`)."""
        for rel, (rect, offset) in self.LOGIN.items():
            self.crop(root, rel, "login.png", rect, offset=offset)


@pytest.fixture
def targets() -> Targets:
    return Targets()
