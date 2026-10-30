"""가짜 ctx(`kookabug_sdk.testing.fake_context`)에 끼우는 실제 비전·OCR 엔진.

    ctx = fake_context(frames=["tests/fixtures/title.png"])   # vision·ocr을 넣지 않으면 이것
    match = ctx.vision.find(ctx.capture(), load_target("tests/fixtures/start.target.json"))

가짜 ctx의 프레임은 파일·바이트 이미지다. 엔진은 그 픽셀을 풀어 runner와 같은 매칭
(`Vision`)·OCR(`RapidOcrEngine`)을 돌린다 — 노드 테스트가 실제 매칭·OCR을 게임 없이 쓴다.

가짜 ctx는 손으로 넘기는 시계(`FakeClock`)라 노드 기한은 실제 계산 시간과 무관하다. 그래서
여기서는 노드 기한으로 계산을 끊지 않는다(지난 기한은 가짜 ctx가 엔진 앞에서
`ObservationTimeout`으로 막는다). 설정 기한도 없다(넉넉한 `CONFIG_MS`). OCR 모델이 없으면 처음
읽을 때 `ocr_model_missing`.
"""

from __future__ import annotations

from typing import Final

from kookabug_core.engine.context import ObservationLimits
from kookabug_platform.engines import RunEngines
from kookabug_sdk.context import Deadline
from kookabug_sdk.types import Image, Match, OcrResult, Rect, Target

__all__ = ["CONFIG_MS", "FakeOcr", "FakeVision", "ocr", "vision"]

CONFIG_MS: Final = 600_000
"""가짜 ctx 관측 하나의 설정 기한 (사실상 없음)."""

_LIMITS: Final = ObservationLimits(CONFIG_MS)


class FakeVision:
    """SDK `VisionApi`: 파일·바이트 이미지에서 찾고 비교한다."""

    def __init__(self, engines: RunEngines | None = None) -> None:
        self.engines = engines or RunEngines()

    def find(
        self,
        image: Image,
        target: Target,
        *,
        region: Rect | None = None,
        deadline: Deadline | None = None,
    ) -> Match | None:
        return self.engines.find(image, target, region=region, limits=_LIMITS)

    def diff(self, a: Image, b: Image, *, region: Rect | None = None) -> float:
        return self.engines.diff(a, b, region=region)


class FakeOcr:
    """SDK `OcrApi`: 파일·바이트 이미지의 글자를 읽는다."""

    def __init__(self, engines: RunEngines | None = None) -> None:
        self.engines = engines or RunEngines()

    def read(
        self,
        image: Image,
        *,
        region: Rect | None = None,
        sensitive: bool = False,
        deadline: Deadline | None = None,
    ) -> OcrResult:
        return self.engines.read_text(image, region=region, sensitive=sensitive, limits=_LIMITS)


def vision() -> FakeVision:
    """`fake_context`가 `vision=`이 없을 때 부르는 팩토리."""
    return FakeVision()


def ocr() -> FakeOcr:
    """`fake_context`가 `ocr=`이 없을 때 부르는 팩토리 (모델은 처음 읽을 때 찾는다)."""
    return FakeOcr()
