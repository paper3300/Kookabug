"""daemon이 보는 창·캡처 원천 (M7 계획 3.5a·3.12).

- 실제(`RealSource`): Windows 창 목록·WGC 캡처(`methods.windows`·`methods.target`의 함수를 부를
  때 찾는다 — 검사가 그 함수를 바꿔 끼운다)
- 가짜(`FakeSource`, 숨은 `--platform-fake` 사양에 `scenario`가 있을 때): 장면 가짜 게임
  (`FakeScenario`)의 창·장면. 사양의 `state_file`(검사 전용)이 있으면 runner의 제어 실행과 같은
  상태를 읽고 쓴다(캡처 한 번 = `after_frames` 한 프레임, runner와 같은 규칙). `draw_fields`(검사
  전용)면 그 폼 칸의 지금 값을 픽셀에 평문으로 그린다 — 비밀값 보호 검사의 양성 대조군

창 바인딩(`WindowBinding`)은 (HWND, PID, 프로세스 생성 시각)이다. 같은 HWND를 다른 프로세스가 다시
쓰면 다른 바인딩이다(보호 기록은 바인딩에 붙는다).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from kookabug_core.runner.spec import control_title_matches
from kookabug_daemon.protocol import RequestFailed

__all__ = [
    "FakeSource",
    "Grab",
    "RealSource",
    "ScreenSource",
    "WindowBinding",
    "make_source",
]


@dataclass(frozen=True, slots=True)
class WindowBinding:
    hwnd: int
    pid: int
    created: str
    """프로세스 생성 시각 (실제: FILETIME 10진, 가짜: PID 문자열)."""

    def to_json(self) -> dict[str, Any]:
        return {"hwnd": self.hwnd, "pid": self.pid, "created": self.created}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> WindowBinding:
        return cls(int(data["hwnd"]), int(data["pid"]), str(data["created"]))


@dataclass(frozen=True, slots=True)
class Grab:
    """창 한 장. `binding`을 모르면 None (검사의 가짜 캡처 함수 등)."""

    pixels: Any
    client_size: tuple[int, int]
    dpi: int
    binding: WindowBinding | None


class ScreenSource(Protocol):
    def windows(self) -> list[dict[str, Any]]:
        """`windows.list`의 창들 (보이는·최소화 안 된 것)."""
        ...

    def capture(self, hwnd: int) -> Grab: ...

    def alive(self, binding: WindowBinding) -> bool:
        """그 바인딩의 창이 아직 그 프로세스의 것으로 살아 있는가. 모르면 True (보호 유지 쪽)."""
        ...

    def find(self, title: str) -> list[WindowBinding]:
        """창 붙기가 찾는 범위의 창 중 제목이 정확히 같은 창들 (`control_title_matches`). 에이전트
        제어 실행은 이것이 정확히 하나일 때만 그 바인딩에 입력한다."""
        ...


class RealSource:
    """실제 Windows."""

    def windows(self) -> list[dict[str, Any]]:
        from kookabug_daemon.methods import windows as window_methods

        window_methods.require_windows()
        return window_methods._windows()  # pyright: ignore[reportPrivateUsage]

    def capture(self, hwnd: int) -> Grab:
        import numpy as np

        from kookabug_daemon.methods import target as target_methods

        captured = target_methods.capture_window(hwnd)
        info = captured.info
        pixels = np.ascontiguousarray(captured.pixels)
        width, height = (int(v) for v in info.client_size)
        return Grab(pixels, (width, height), int(info.dpi), self._binding(hwnd))

    @staticmethod
    def _binding(hwnd: int) -> WindowBinding | None:
        try:
            from kookabug_platform.windows import window_info

            info = window_info(hwnd)
        except Exception:  # 창이 그 사이 닫힘·검사의 가짜 창: 바인딩 모름
            return None
        return WindowBinding(hwnd, info.pid, str(info.process_created))

    def alive(self, binding: WindowBinding) -> bool:
        try:
            from kookabug_platform.win32.api import DEFAULT_API
            from kookabug_platform.windows import window_info

            if not DEFAULT_API.is_window(binding.hwnd):
                return False
            info = window_info(binding.hwnd)
        except Exception:
            return True  # 확인 못 함 = 살아 있다고 본다 (보호를 풀지 않음)
        return info.pid == binding.pid and str(info.process_created) == binding.created

    def find(self, title: str) -> list[WindowBinding]:
        return [b for b, t in self._all() if control_title_matches(t, title)]

    @staticmethod
    def _all() -> list[tuple[WindowBinding, str]]:
        try:
            from kookabug_platform.windows import find_windows, window_info
        except ImportError:
            return []
        out: list[tuple[WindowBinding, str]] = []
        try:
            handles = find_windows()
        except Exception:
            return out
        for hwnd in handles:
            try:
                info = window_info(hwnd)
            except Exception:
                continue
            out.append((WindowBinding(hwnd, info.pid, str(info.process_created)), info.title))
        return out


class FakeSource:
    """장면 가짜 게임 (`FakeScenario`). 부를 때마다 상태 파일에서 다시 읽는다 (runner와 나눈다)."""

    def __init__(
        self,
        scenario: Path,
        state_file: Path | None,
        draw_fields: Mapping[str, Sequence[str]] | None = None,
    ) -> None:
        self.scenario = scenario
        self.state_file = state_file
        self.draw_fields = {k: tuple(v) for k, v in (draw_fields or {}).items()}

    def _load(self) -> Any:
        from kookabug_core.engine.scenario import FakeScenario

        return FakeScenario.load(self.scenario, state_file=self.state_file)

    def windows(self) -> list[dict[str, Any]]:
        scenario = self._load()
        return [
            {
                "handle": g.window.handle,
                "title": g.window.title,
                "process": scenario.process_name,
                "pid": g.window.pid,
                "client_size": list(scenario.client_size),
                "dpi": scenario.dpi,
            }
            for g in scenario.games()
        ]

    def capture(self, hwnd: int) -> Grab:
        import numpy as np

        from kookabug_platform.frames import decode_image

        scenario = self._load()
        game = next((g for g in scenario.games() if g.window.handle == hwnd), None)
        if game is None:
            raise RequestFailed("window_not_found", f"창 {hwnd:#x}이(가) 없다", message="창이 없다")
        image = scenario.frame(game)  # 캡처 한 번 (상태 파일에 쓴다)
        assert image.path is not None
        pixels = np.array(decode_image(Path(image.path).read_bytes()), copy=True)
        if self.draw_fields:
            _draw(pixels, scenario.field_values(game), self.draw_fields)
        window = game.window
        binding = WindowBinding(window.handle, window.pid, str(window.process_created))
        return Grab(pixels, scenario.client_size, scenario.dpi, binding)

    def alive(self, binding: WindowBinding) -> bool:
        try:
            scenario = self._load()
        except Exception:
            return True
        return any(
            g.window.handle == binding.hwnd
            and g.window.pid == binding.pid
            and str(g.window.process_created) == binding.created
            for g in scenario.games()
        )

    def find(self, title: str) -> list[WindowBinding]:
        scenario = self._load()
        return [
            WindowBinding(g.window.handle, g.window.pid, str(g.window.process_created))
            for g in scenario.games()
            if control_title_matches(g.window.title, title)
        ]


def _draw(
    pixels: Any,
    fields: Mapping[str, tuple[tuple[int, int, int, int], str]],
    wanted: Mapping[str, tuple[str, ...]],
) -> None:
    """검사 전용: 폼 칸 상자 안에 지금 값을 평문으로 그린다 (OpenCV 글자, ASCII)."""
    import cv2

    for form, names in wanted.items():
        for name in names:
            found = fields.get(f"{form}.{name}")
            if found is None or not found[1]:
                continue
            (x, y, w, h), value = found
            text = value.encode("ascii", "replace").decode("ascii")
            cv2.rectangle(pixels, (x + 2, y + 2), (x + w - 3, y + h - 3), (255, 255, 255), -1)
            cv2.putText(
                pixels,
                text,
                (x + 8, y + h // 2 + 9),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 0),
                2,
                cv2.LINE_AA,
            )


def make_source(platform_fake: Path | None) -> ScreenSource:
    """숨은 `--platform-fake` 사양에 `scenario`가 있으면 가짜, 아니면 실제 Windows."""
    if platform_fake is None:
        return RealSource()
    try:
        spec = json.loads(platform_fake.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return RealSource()
    if not isinstance(spec, dict) or spec.get("scenario") is None:
        return RealSource()
    data: dict[str, Any] = spec
    base = platform_fake.parent
    state = data.get("state_file")
    draw = data.get("draw_fields")
    return FakeSource(
        (base / str(data["scenario"])).resolve(),
        None if state is None else (base / str(state)).resolve(),
        draw if isinstance(draw, dict) else None,
    )
