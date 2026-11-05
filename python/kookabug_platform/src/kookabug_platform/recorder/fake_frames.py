"""부품 합성 가짜 프레임 원천과 가짜 세계 (M4 계획 2.9 "가짜 원천", 검수 M10, T8).

`FakeScenario`의 장면 PNG에는 폼 값·포커스 테두리·가림 글자가 없다. 그래서 입력 칸 상태(포커스·값
— 비밀번호 칸은 `●`)를 장면 그림 위에 다시 그린다. 그리는 규칙은 예제 게임 `render.py`와 같은
색·두께·자리다(칸 바탕 `#11161f`, 테두리 2 px — 포커스 `#5fb0ff`·아니면 `#4a5875`, 글자는 왼쪽
14 px에서 시작). 글자는 OpenCV 글꼴, 가림 글자는 지름 14 px 원을 18 px 간격으로 그린다 — 실제 게임
글꼴과 글리프 모양이 다르다(같음 확인은 데스크톱 검사 `test_composed_form_matches_real_capture`).
이름이 `password`인 칸을 가린다(예제 게임 규칙).

`FakeWorld`는 각본 하나를 시각 차례로 흘린다: 입력 줄은 가짜 사람(`FakeHuman`)이 장면 상태에
적용하고 바뀌었으면 `frame_lag_ns` 뒤 프레임을 낸다. 관측 줄은 키·마우스가 게임에 가는지를 정한다.
장면 줄은 게임이 스스로 장면을 바꾼 것, 기하·프레임 줄은 `ScriptFrameSource`가 처리한다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np

from kookabug_core.engine.scenario import FakeScenario, ScenarioState
from kookabug_core.recorder.fake_human import FakeHuman
from kookabug_platform.recorder.frames import CaptureRing, Pixels, RingPolicy
from kookabug_platform.recorder.geometry import Geometry, GeometryTimeline
from kookabug_platform.recorder.scripted_frames import ScriptFrameSource, png_scenes

__all__ = [
    "FIELD_EDGE",
    "FIELD_FILL",
    "FIELD_FOCUS",
    "FIELD_TEXT",
    "FakeWorld",
    "draw_forms",
]

# 예제 게임 render.py 색 (BGR)
FIELD_FILL: Final = (31, 22, 17)
FIELD_FOCUS: Final = (255, 176, 95)
FIELD_EDGE: Final = (117, 88, 74)
FIELD_TEXT: Final = (248, 244, 242)
_MS: Final = 1_000_000


def _field_rect(
    rect: tuple[int, ...], size: tuple[int, int], base: tuple[int, int]
) -> tuple[int, int, int, int, float]:
    """장면 표 좌표(기준 크기) → 클라이언트 픽셀 (예제 게임 `Viewport`: 비율 유지, 가운데)."""
    scale = min(size[0] / base[0], size[1] / base[1])
    ox, oy = (size[0] - base[0] * scale) / 2, (size[1] - base[1] * scale) / 2
    x, y, w, h = rect
    return (
        round(ox + x * scale),
        round(oy + y * scale),
        round(w * scale),
        round(h * scale),
        scale,
    )


def draw_forms(
    image: Pixels,
    spec: Mapping[str, Any],
    state: ScenarioState,
    base: tuple[int, int],
) -> Pixels:
    """그 장면의 입력 칸을 지금 상태로 다시 그린 그림 (입력 장면이 아니면 그대로)."""
    out = np.array(image, dtype=np.uint8, copy=True)
    size = (int(out.shape[1]), int(out.shape[0]))
    for name, form in spec.get("forms", {}).items():
        if state.scene not in form["scenes"] or name not in state.forms:
            continue
        values = state.forms[name]
        for field in form["fields"]:
            x, y, w, h, scale = _field_rect(tuple(field["rect"]), size, base)
            focused = values["focus"] == field["name"] and state.scene == form["input_scene"]
            border = max(1, round(2 * scale))
            cv2.rectangle(out, (x, y), (x + w - 1, y + h - 1), FIELD_FILL, -1)
            color = FIELD_FOCUS if focused else FIELD_EDGE
            cv2.rectangle(out, (x, y), (x + w - 1, y + h - 1), color, border)
            value = str(values["values"].get(field["name"], ""))
            if not value:
                continue
            cy = y + h // 2
            if field["name"] == "password":
                for i in range(len(value)):
                    center = (x + round((20 + i * 18) * scale), cy)
                    cv2.circle(out, center, max(2, round(7 * scale)), FIELD_TEXT, -1, cv2.LINE_AA)
            else:
                cv2.putText(
                    out,
                    value,
                    (x + round(14 * scale), cy + round(8 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8 * scale,
                    FIELD_TEXT,
                    max(1, round(2 * scale)),
                    cv2.LINE_AA,
                )
    return out


class FakeWorld:
    """가짜 각본 → 가짜 게임 장면 + 부품 합성 프레임 (`FrameSource`).

    `advance_to(t)`로 시각을 흘린다 (가짜 훅 원천이 그 시각 메시지를 내기 전에 부른다).
    """

    def __init__(
        self,
        lines: Iterable[Mapping[str, Any]],
        scenario_path: str | Path,
        *,
        frame_lag_ns: int = 16 * _MS,
        policy: RingPolicy | None = None,
        args: Iterable[str] = (),
    ) -> None:
        items = [dict(line) for line in lines]
        if not items or items[0].get("kind") != "header":
            raise ValueError("각본 첫 줄은 header다")
        header = items[0]
        self.header = header
        self.scenario = FakeScenario.load(scenario_path)
        self.state = ScenarioState(self.scenario.spec, tuple(args))
        scene = str(header["scene"])
        if scene != self.state.scene:
            self.state._enter(scene, None)  # pyright: ignore[reportPrivateUsage]
        self.human = FakeHuman(self.state)
        self._base = self.scenario.client_size
        self._scene_png = png_scenes(self.scenario.folder)
        self._file_of = {
            name: Path(file).stem for name, file in self.scenario.spec["scenes"].items()
        }
        self.source = ScriptFrameSource(
            Geometry.of_json(header["geometry"]),
            scene,
            self._render,
            frame_lag_ns=frame_lag_ns,
            policy=policy,
        )
        self.source.load_lines(
            line for line in items[1:] if line.get("kind") in ("geometry", "frame")
        )
        self._lag = frame_lag_ns
        self._events = sorted(
            (line for line in items[1:] if line.get("kind") in ("input", "observe", "scene")),
            key=lambda line: int(line["t_ns"]),
        )
        self._next = 0

    # ------------------------------------------------------------ FrameSource

    @property
    def ring(self) -> CaptureRing:
        return self.source.ring

    @property
    def geometry(self) -> GeometryTimeline:
        return self.source.geometry

    def start(self) -> None:
        pass

    def close(self) -> None:
        self.source.close()

    # ------------------------------------------------------------ 각본

    @property
    def title(self) -> str:
        return str(self.header.get("title", ""))

    def _render(self, _scene: str, size: tuple[int, int]) -> Pixels:
        image = self._scene_png(self._file_of.get(self.state.scene, self.state.scene), size)
        return draw_forms(image, self.scenario.spec, self.state, self._base)

    def advance_to(self, t_ns: int) -> None:
        """`t_ns`까지의 입력·관측·장면 줄과 프레임을 시각 차례로 처리한다."""
        while self._next < len(self._events) and int(self._events[self._next]["t_ns"]) <= t_ns:
            line = self._events[self._next]
            self._next += 1
            at = int(line["t_ns"])
            self.source.advance_to(at)
            if self._apply(line):
                self.state.capture()
                self.source.schedule_frame(at + self._lag)
        self.source.advance_to(max(t_ns, self.source.now_ns))

    def _apply(self, line: Mapping[str, Any]) -> bool:
        kind = line["kind"]
        if kind == "observe":
            fg = line.get("fg", "target")
            point = line.get("point", fg)
            self.human.foreground = fg == "target"
            self.human.pointer_on_game = point == "target"
            return False
        if kind == "scene":
            self.state._enter(str(line["scene"]), None)  # pyright: ignore[reportPrivateUsage]
            return True
        origin = self.source.actual_geometry.client_origin
        return self.human.apply(line["input"], origin)

    def client_pixels(self) -> Pixels:
        """지금 상태의 클라이언트 그림 (검사용)."""
        return self._render(self.state.scene, self.source.actual_geometry.client_size)
