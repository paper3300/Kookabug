"""이미지 매칭과 프레임 비교 (구현 계획 M1 2.5).

**찾기** (`Vision.find`)

- target 이미지는 바이트로 읽어 `cv2.imdecode`(한글 경로). 알파가 0인 픽셀은 마스크로 빼고
  (`TM_CCOEFF_NORMED` + mask), 알파가 전부 불투명이면 마스크 없이. 실행(이 `Vision`) 안에서 캐시
- 방법은 `match.methods` 앞에서부터(기본 `template_multiscale` → `template`). `template` =
  배율 1.0. `template_multiscale` = 기대 배율 `s0` * `SCALE_STEPS` 순서. `s0` = 지금 클라이언트
  높이 / `recorded.client_size[1]`, 없으면 `dpi / recorded.dpi`, 없으면 1.0
- 점수는 `TM_CCOEFF_NORMED` 최댓값. `rgb`(기본 true)면 BGR, false면 회색조. `threshold`(기본
  0.85) 이상인 **첫 방법·첫 배율**에서 끝난다
- 색 확인: `rgb`일 때 찾은 자리와 템플릿(마스크 안)의 채널별 평균 차이가 `color_tolerance`(기본
  40)를 넘으면 그 후보는 실패(다음 배율·방법을 계속 본다)
- 검색 범위: 호출의 `region`(클라이언트 좌표)이 있으면 그것, 없으면 target `search.region`(정규화),
  없으면 프레임 전체. 프레임이 영역 캡처면 픽셀 (0, 0)이 클라이언트 `origin`이다
- 클릭 지점 = 찾은 상자의 `click.anchor`(9분할, 상자 안 픽셀: 오른쪽·아래 끝은 `x + w - 1`) +
  `offset * scale`. 정수는 0.5 올림
- 못 찾으면 `match`가 None이고, 가장 높은 점수 후보(`best`)를 같이 준다 (`target test` 미리보기)
- 속도: 방법·배율마다 **원래 크기 전체**를 계산한다(근사 없음 — 줄여 찾는 1차 탐색은 비슷한
  패치가 많은 화면에서 정확히 같은 대상도 놓쳐 쓰지 않는다, T6 검수 1). 대신 방법·배율들을
  공용 스레드 풀(`WORKERS`개, opencv `matchTemplate`는 GIL을 놓는다)에서 함께 계산하고 결과는
  시도 순서대로 본다 — 첫 성공·점수·위치는 순서대로 하나씩 계산한 것과 같다
- 픽셀 수명 (T6 검수 2): 찾기 하나는 일감(`_Job`)이고, 풀에는 그 일감에서 시도를 하나씩 꺼내 도는
  일꾼을 최대 `WORKERS`개만 넣는다(대기 중인 일꾼은 전체 `MAX_PENDING_LANES`까지, 적어도 1).
  픽셀은 일감만 쥔다. 호출이 끝나면(첫 성공·기한·취소·예외) 일감을 놓아 **아직 시작하지 않은
  시도는 픽셀 없이 버려지고**, 이미 계산 중인 시도만 그 계산이 끝날 때까지 픽셀을 쥔다.
  저장소 캡처에서 찾을 때(`find_capture`)는 작업 중 고정도 그때까지 유지한다 — 저장소 바이트
  계산이 실제로 붙잡은 픽셀과 같다. 호출은 계산이 끝나기를 기다리지 않고 기한에 돌아온다

**프레임 비교** (`Vision.diff`)

두 캡처(같은 영역)의 채널 평균 절대 차이 / 255(0~1). 두 캡처의 픽셀 동일성 키가 같으면(같은
WGC 프레임·같은 자르기 — `FrameStore.identity`) 계산 없이 0이다. `frame_seq`만 같은 것은 같은
픽셀이 아니다(다른 자르기·다른 창, 계획 2차 검수 N3). 크기가 다르면 1.0. 버린 캡처면
`frame_expired`.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import cv2
import numpy as np

from kookabug_core.canonical import loads_strict
from kookabug_core.schema import check_shape
from kookabug_platform.dpi import normalized_to_pixels, round_half_up
from kookabug_platform.errors import CAPTURE_TIMEOUT, TARGET_IMAGE_INVALID, PlatformError
from kookabug_sdk.types import Rect, Target

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from kookabug_platform.capture import CapturedFrame
    from kookabug_platform.deadline import ObservationDeadline
    from kookabug_platform.frames import FrameStore

__all__ = [
    "ANCHORS",
    "DEFAULT_COLOR_TOLERANCE",
    "DEFAULT_METHODS",
    "DEFAULT_THRESHOLD",
    "SCALE_STEPS",
    "WORKERS",
    "Box",
    "Candidate",
    "FindResult",
    "FrameMeta",
    "FrameRef",
    "Pixels",
    "TargetFileError",
    "TargetImage",
    "TargetSpec",
    "Vision",
    "VisionMatch",
    "click_point",
    "diff_pixels",
    "expected_scale",
    "load_target_file",
    "load_target_image",
    "score_peaks",
]

type Pixels = NDArray[np.uint8]
type Box = tuple[int, int, int, int]
"""`(x, y, w, h)` 물리 픽셀."""

DEFAULT_METHODS: Final = ("template_multiscale", "template")
DEFAULT_THRESHOLD: Final = 0.85
DEFAULT_COLOR_TOLERANCE: Final = 40.0
SCALE_STEPS: Final = (1.0, 0.95, 1.05, 0.9, 1.1, 0.85, 1.15, 0.8, 1.2)
"""멀티스케일 배율 (기대 배율에 곱한다, 이 순서로 시도). 조율자 결정 Q11."""
MIN_TEMPLATE_PX: Final = 4
"""배율을 곱한 템플릿의 한 변이 이보다 작으면 그 배율은 건너뛴다."""
WORKERS: Final = max(1, min(8, os.cpu_count() or 1))
"""방법·배율을 함께 계산하는 스레드 수 (프로세스에 하나인 풀, 처음 찾을 때 만든다)."""
MAX_PENDING_LANES: Final = 2 * WORKERS
"""풀에서 아직 시작하지 않은 일꾼 수 상한 (넘으면 새 찾기는 일꾼 하나만 넣는다)."""
ANCHORS: Final[Mapping[str, tuple[float, float]]] = {
    "top_left": (0.0, 0.0),
    "top": (0.5, 0.0),
    "top_right": (1.0, 0.0),
    "left": (0.0, 0.5),
    "center": (0.5, 0.5),
    "right": (1.0, 0.5),
    "bottom_left": (0.0, 1.0),
    "bottom": (0.5, 1.0),
    "bottom_right": (1.0, 1.0),
}


# ---------------------------------------------------------------- target


class TargetFileError(Exception):
    """target 파일을 읽을 수 없거나 형식이 틀렸다 (워크스페이스 밖 `target test`용)."""


def load_target_file(path: Path) -> Target:
    """target 파일 하나를 워크스페이스 없이 읽는다 (`image`는 이 파일 기준 상대 경로)."""
    try:
        data = loads_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise TargetFileError(f"target 파일 {path}을(를) 읽을 수 없다: {exc}") from exc
    problems = check_shape(data, "target", file=path.name)
    if problems:
        detail = "; ".join(f"{d.pointer or '/'} {d.message}" for d in problems[:3])
        raise TargetFileError(f"target 파일 {path}의 형식이 틀렸다: {detail}")
    return Target(name=path.name, path=path, spec=data)


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """target 파일의 매칭 설정 (기본값을 채운 것)."""

    name: str
    image_path: Path
    methods: tuple[str, ...] = DEFAULT_METHODS
    threshold: float = DEFAULT_THRESHOLD
    rgb: bool = True
    color_tolerance: float = DEFAULT_COLOR_TOLERANCE
    search_region: tuple[float, float, float, float] | None = None
    anchor: str = "center"
    offset: tuple[float, float] = (0.0, 0.0)
    recorded_size: tuple[int, int] | None = None
    recorded_dpi: int | None = None
    sensitive: bool = False

    @classmethod
    def of(cls, target: Target | TargetSpec) -> TargetSpec:
        if isinstance(target, TargetSpec):
            return target
        if target.path is None or not isinstance(target.spec.get("image"), str):
            raise PlatformError(
                TARGET_IMAGE_INVALID, f"target '{target.name}'에 파일 경로·이미지가 없다"
            )
        spec = target.spec
        match: Mapping[str, Any] = spec.get("match") or {}
        click: Mapping[str, Any] = spec.get("click") or {}
        recorded: Mapping[str, Any] = spec.get("recorded") or {}
        search: Mapping[str, Any] = spec.get("search") or {}
        region = search.get("region")
        size = recorded.get("client_size")
        offset = click.get("offset") or (0, 0)
        return cls(
            name=target.name,
            image_path=Path(target.path).parent.joinpath(*spec["image"].split("/")),
            methods=tuple(match.get("methods") or DEFAULT_METHODS),
            threshold=float(match.get("threshold", DEFAULT_THRESHOLD)),
            rgb=bool(match.get("rgb", True)),
            color_tolerance=float(match.get("color_tolerance", DEFAULT_COLOR_TOLERANCE)),
            search_region=None if region is None else (region[0], region[1], region[2], region[3]),
            anchor=str(click.get("anchor", "center")),
            offset=(float(offset[0]), float(offset[1])),
            recorded_size=None if size is None else (int(size[0]), int(size[1])),
            recorded_dpi=recorded.get("dpi"),
            sensitive=bool(spec.get("sensitive", False)),
        )


@dataclass(frozen=True, slots=True, eq=False)
class TargetImage:
    """읽은 target 이미지: BGR·회색조와 마스크(알파 0 = 0, 나머지 255. 전부 불투명이면 None)."""

    path: Path
    bgr: Pixels
    gray: Pixels
    mask: Pixels | None

    @property
    def size(self) -> tuple[int, int]:
        return int(self.bgr.shape[1]), int(self.bgr.shape[0])

    @classmethod
    def of_pixels(cls, bgr: Pixels, path: Path) -> TargetImage:
        """메모리의 BGR 픽셀(편집기에서 저장 전에 자른 영역) → 마스크 없는 target 이미지.
        `path`는 이름표다 (읽지 않는다)."""
        image = np.array(bgr[:, :, :3], dtype=np.uint8, copy=True)
        gray = _u8(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
        image.setflags(write=False)
        gray.setflags(write=False)
        return cls(path, image, gray, None)


def load_target_image(path: Path) -> TargetImage:
    """이미지 파일 → `TargetImage`. 없거나 깨졌으면 `target_image_invalid`."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise PlatformError(
            TARGET_IMAGE_INVALID, f"target 이미지 {path}을(를) 읽을 수 없다: {exc}"
        ) from exc
    raw = None
    if data:  # 빈 버퍼는 imdecode가 None 대신 cv2.error를 던진다
        try:
            raw = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        except cv2.error:
            raw = None
    if raw is None or raw.size == 0:
        raise PlatformError(TARGET_IMAGE_INVALID, f"target 이미지 {path}이(가) 이미지가 아니다")
    image = np.asarray(raw)
    if image.dtype == np.uint16:
        image = (image // 257).astype(np.uint8)
    elif image.dtype != np.uint8:
        raise PlatformError(
            TARGET_IMAGE_INVALID, f"target 이미지 {path}의 픽셀 형식을 쓸 수 없다: {image.dtype}"
        )
    mask: Pixels | None = None
    if image.ndim == 2:
        bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    elif image.shape[2] == 4:
        alpha = image[:, :, 3]
        bgr = np.ascontiguousarray(image[:, :, :3])
        if not alpha.any():
            raise PlatformError(TARGET_IMAGE_INVALID, f"target 이미지 {path}이(가) 전부 투명하다")
        if (alpha == 0).any():
            mask = np.where(alpha > 0, 255, 0).astype(np.uint8)
    elif image.shape[2] == 3:
        bgr = image
    else:
        raise PlatformError(
            TARGET_IMAGE_INVALID, f"target 이미지 {path}의 채널 수를 쓸 수 없다: {image.shape}"
        )
    bgr = _u8(bgr)
    gray = _u8(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    for array in (bgr, gray, mask):
        if array is not None:
            array.setflags(write=False)
    return TargetImage(path, bgr, gray, mask)


def _u8(image: Any) -> Pixels:
    """opencv 결과(`MatLike`)를 uint8 배열 타입으로 (값은 이미 uint8이다)."""
    return np.asarray(image, dtype=np.uint8)


# ---------------------------------------------------------------- 프레임


@dataclass(frozen=True, slots=True)
class FrameRef:
    """`Match`가 가리키는 관측 (재검증용, M1 2.8 `Match.frame_info`)."""

    backend: str
    client_size: tuple[int, int]
    dpi: int
    capture_id: int | None
    observed_at: float | None


@dataclass(frozen=True, slots=True)
class FrameMeta:
    """찾기에 넘기는 프레임 픽셀의 정보.

    `client_size`·`dpi`는 캡처 순간 대상 창의 것(기대 배율·정규화 검색 범위에 쓴다). 픽셀이
    영역 캡처면 `origin`이 픽셀 (0, 0)의 클라이언트 좌표다. 파일 이미지는 이미지 크기·96 DPI.
    """

    client_size: tuple[int, int]
    dpi: int = 96
    origin: tuple[int, int] = (0, 0)
    backend: str = "image"
    capture_id: int | None = None
    observed_at: float | None = None
    frame: int | None = None
    window: Any = None

    @classmethod
    def of_image(cls, pixels: Pixels, *, dpi: int = 96) -> FrameMeta:
        return cls((int(pixels.shape[1]), int(pixels.shape[0])), dpi)

    @classmethod
    def of_capture(cls, frame: CapturedFrame, capture_id: int | None = None) -> FrameMeta:
        info = frame.info
        origin = (0, 0) if info.region is None else (info.region[0], info.region[1])
        return cls(
            client_size=info.client_size,
            dpi=info.dpi,
            origin=origin,
            backend=info.backend,
            capture_id=capture_id,
            observed_at=info.observed_at,
            frame=info.frame_seq,
            window=info.window,
        )

    def ref(self) -> FrameRef:
        return FrameRef(self.backend, self.client_size, self.dpi, self.capture_id, self.observed_at)


# ---------------------------------------------------------------- 결과


@dataclass(frozen=True, slots=True)
class Candidate:
    """방법·배율 하나의 최고 후보. `rect`는 클라이언트 좌표.

    `reason`: 받아들였으면 "", 점수 미달 `threshold`, 색 확인 실패 `color`.
    """

    method: str
    scale: float
    rect: Box
    score: float
    color_diff: float | None
    accepted: bool
    reason: str


@dataclass(frozen=True, slots=True)
class VisionMatch:
    """찾은 결과 (M1 2.5 `Match`). SDK `Match`로 옮기는 것은 runner 연결(T9)이 한다."""

    rect: Box
    score: float
    scale: float
    method: str
    click: tuple[int, int]
    target: str
    frame_info: FrameRef
    window: Any = None
    frame: int | None = None


@dataclass(frozen=True, slots=True)
class FindResult:
    match: VisionMatch | None
    best: Candidate | None
    """받아들인 후보, 없으면 점수가 가장 높은 후보 (시도한 것이 없으면 None)."""
    candidates: tuple[Candidate, ...]
    """시도한 순서."""
    search: Box
    """검색 범위 (클라이언트 좌표, 프레임 안으로 자른 것)."""
    threshold: float
    expected_scale: float
    elapsed_ms: float

    @property
    def found(self) -> bool:
        return self.match is not None


# ---------------------------------------------------------------- 계산


def expected_scale(spec: TargetSpec, meta: FrameMeta) -> float:
    """기대 배율 `s0`: 지금 클라이언트 높이 / 녹화 높이 → DPI 비 → 1.0."""
    if spec.recorded_size is not None and spec.recorded_size[1] > 0:
        return meta.client_size[1] / spec.recorded_size[1]
    if spec.recorded_dpi and meta.dpi:
        return meta.dpi / spec.recorded_dpi
    return 1.0


def click_point(
    rect: Box, anchor: str, offset: tuple[float, float], scale: float
) -> tuple[int, int]:
    """상자의 9분할 지점(상자 안 픽셀) + `offset * scale`."""
    fx, fy = ANCHORS.get(anchor, ANCHORS["center"])
    x, y, w, h = rect
    return (
        round_half_up(x + fx * (w - 1) + offset[0] * scale),
        round_half_up(y + fy * (h - 1) + offset[1] * scale),
    )


def _intersect(a: Box, b: Box) -> Box:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)


def _box(region: Rect | Sequence[int]) -> Box:
    if isinstance(region, Rect):
        return region.x, region.y, region.width, region.height
    x, y, w, h = region
    return int(x), int(y), int(w), int(h)


def diff_pixels(a: Pixels, b: Pixels, region: Rect | Sequence[int] | None = None) -> float:
    """두 픽셀 배열의 채널 평균 절대 차이 / 255. 모양이 다르면 1.0.

    `region`은 이미지 기준 `(x, y, w, h)`이고 이미지 안으로 자른다. 잘라서 비면 1.0 — 비교할 픽셀이
    없는 영역을 "같다"로 보면 화면 밖 영역이 늘 멈춘 화면으로 판정된다(T11 검수 3).
    """
    if a.shape != b.shape:
        return 1.0
    if region is not None:
        x, y, w, h = _intersect(_box(region), (0, 0, int(a.shape[1]), int(a.shape[0])))
        if w == 0 or h == 0:
            return 1.0
        a, b = a[y : y + h, x : x + w], b[y : y + h, x : x + w]
    if a.size == 0:
        return 0.0
    return float(np.mean(cv2.absdiff(a, b))) / 255.0


def _find_timeout() -> PlatformError:
    return PlatformError(CAPTURE_TIMEOUT, "이미지 찾기가 설정 기한 안에 끝나지 않았다")


def _resize(image: Pixels, scale: float, interpolation: int | None = None) -> Pixels:
    if scale == 1.0:
        return image
    h, w = image.shape[:2]
    size = (max(1, round_half_up(w * scale)), max(1, round_half_up(h * scale)))
    if interpolation is None:
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
    return np.asarray(cv2.resize(image, size, interpolation=interpolation), dtype=np.uint8)


def _scores(area: Pixels, template: Pixels, mask: Pixels | None) -> NDArray[np.float32]:
    result = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED, mask=mask)
    # 마스크가 있거나 평평한 자리에서는 분모가 0이라 NaN·inf가 나온다: 맞지 않음으로 본다
    return np.where(np.isfinite(result), result, np.float32(-1.0)).astype(np.float32)


def score_peaks(
    area: Pixels, template: Pixels, count: int, mask: Pixels | None = None
) -> list[tuple[float, tuple[int, int]]]:
    """점수 지도에서 **서로 겹치지 않는** 봉우리 상위 `count`개 `(점수, 왼쪽 위)` (점수 차례).
    봉우리를 하나 고를 때마다 그 상자와 겹치는 자리를 지운다 (`Vision.peaks`·녹화 유일성 검사)."""
    th, tw = template.shape[:2]
    if th > area.shape[0] or tw > area.shape[1]:
        return []
    scores = _scores(area, template, mask)
    found: list[tuple[float, tuple[int, int]]] = []
    while len(found) < count:
        _, score, _, loc = cv2.minMaxLoc(scores)
        if score <= -1.0:
            break
        x, y = int(loc[0]), int(loc[1])
        found.append((float(min(max(score, -1.0), 1.0)), (x, y)))
        # 이 상자와 겹치는 모든 자리(왼쪽 위가 ±상자 크기 안)를 지운다
        scores[max(0, y - th + 1) : y + th, max(0, x - tw + 1) : x + tw] = -1.0
    return found


def _best(area: Pixels, template: Pixels, mask: Pixels | None) -> tuple[float, tuple[int, int]]:
    _, score, _, loc = cv2.minMaxLoc(_scores(area, template, mask))
    return float(min(max(score, -1.0), 1.0)), (int(loc[0]), int(loc[1]))


_pool: ThreadPoolExecutor | None = None
_pool_lock = threading.Lock()


def _executor() -> ThreadPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(WORKERS, thread_name_prefix="kb-vision")
        return _pool


_pending_lanes = 0
"""풀 대기열에 있고 아직 시작하지 않은 일꾼 수 (`_pool_lock`)."""

type _Args = tuple[TargetSpec, TargetImage, Pixels, tuple[int, int]]
type _Outcome = tuple[Candidate | None, BaseException | None]


class _Job:
    """찾기 하나의 시도 목록과 그 픽셀. 일꾼은 시도를 하나씩 꺼내 계산한다.

    픽셀(`args`)은 일감만 쥔다. `release()` 뒤에는 새 시도를 꺼내 주지 않고 픽셀을 놓는다 —
    대기열의 일꾼은 일감만 들고 있으므로 픽셀을 붙잡지 않는다. 계산 중인 일꾼이 모두 끝나면
    (`active == 0`) `on_idle`(작업 중 고정 풀기)을 한 번 부른다.
    """

    def __init__(
        self, args: _Args, attempts: list[tuple[str, float]], on_idle: Callable[[], None] | None
    ) -> None:
        self.cond = threading.Condition()
        self.args: _Args | None = args
        self.attempts = attempts
        self.next = 0
        self.active = 0
        self.results: dict[int, _Outcome] = {}
        self._on_idle = on_idle

    def take(self) -> tuple[int, _Args] | None:
        with self.cond:
            if self.args is None or self.next >= len(self.attempts):
                return None
            index = self.next
            self.next += 1
            self.active += 1
            return index, self.args

    def put(self, index: int, outcome: _Outcome) -> None:
        with self.cond:
            self.results[index] = outcome
            self.active -= 1
            idle = self._idle_locked()
            self.cond.notify_all()
        if idle is not None:
            idle()

    def release(self) -> None:
        with self.cond:
            self.args = None
            idle = self._idle_locked()
            self.cond.notify_all()
        if idle is not None:
            idle()

    def _idle_locked(self) -> Callable[[], None] | None:
        if self.args is not None or self.active:
            return None
        idle, self._on_idle = self._on_idle, None
        return idle

    def wait(self, index: int, deadline: ObservationDeadline | None) -> _Outcome:
        """시도 `index`의 결과. 기한이 있으면 조각마다 취소·기한을 확인한다."""
        with self.cond:
            if deadline is None:
                self.cond.wait_for(lambda: index in self.results)
            else:
                deadline.wait(self.cond, lambda: index in self.results, _find_timeout)
            return self.results[index]


def _lane(job: _Job) -> None:
    """일꾼 하나: 일감이 놓이거나 시도가 다 떨어질 때까지 꺼내 계산한다."""
    global _pending_lanes
    with _pool_lock:
        _pending_lanes -= 1
    while (taken := job.take()) is not None:
        index, args = taken
        del taken
        method, scale = job.attempts[index]
        try:
            outcome: _Outcome = (Vision._try(*args, method, scale), None)
        except BaseException as exc:
            outcome = (None, exc)
        del args  # 계산이 끝났으면 픽셀을 바로 놓는다
        job.put(index, outcome)
        del outcome


def _start(job: _Job) -> None:
    """일꾼을 넣는다: 시도 수·`WORKERS`까지, 대기 중인 일꾼이 많으면 하나만."""
    global _pending_lanes
    pool = _executor()
    with _pool_lock:
        room = max(1, MAX_PENDING_LANES - _pending_lanes)
        lanes = max(1, min(WORKERS, len(job.attempts), room))
        _pending_lanes += lanes
    for _ in range(lanes):
        pool.submit(_lane, job)


class Vision:
    """한 실행의 비전 엔진. target 이미지를 캐시하고, 저장소(`store`)가 있으면 캡처 ID로 찾고
    비교한다. 여러 스레드에서 불러도 된다(워커 RPC 스레드)."""

    def __init__(self, store: FrameStore | None = None) -> None:
        self.store = store
        self._lock = threading.Lock()
        self._images: dict[Path, TargetImage] = {}

    def target_image(self, spec: TargetSpec) -> TargetImage:
        key = spec.image_path
        with self._lock:
            cached = self._images.get(key)
        if cached is not None:
            return cached
        loaded = load_target_image(key)
        with self._lock:
            return self._images.setdefault(key, loaded)

    def put_image(self, image: TargetImage) -> None:
        """아직 파일이 아닌 target 이미지(녹화 초안)를 그 경로 이름으로 캐시에 넣는다."""
        with self._lock:
            self._images[image.path] = image

    def _need_store(self) -> FrameStore:
        if self.store is None:
            raise RuntimeError("프레임 저장소 없이 만든 Vision이다")
        return self.store

    # ------------------------------------------------------------ 찾기

    def find_capture(
        self,
        capture_id: int,
        meta: FrameMeta,
        target: Target | TargetSpec,
        *,
        region: Rect | Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
        exhaustive: bool = False,
    ) -> FindResult:
        """저장소의 캡처에서 찾는다 (버렸으면 `frame_expired`). 작업 중 고정은 호출이 끝나고
        계산 중인 시도까지 끝나면 풀린다 (모듈 설명 "픽셀 수명")."""
        if deadline is not None:
            deadline.start(_find_timeout)
        pin = self._need_store().pinned(capture_id)
        (pixels,) = pin.__enter__()
        unpinned = False

        def unpin() -> None:
            nonlocal unpinned
            if not unpinned:
                unpinned = True
                pin.__exit__(None, None, None)

        try:
            return self._find(
                pixels,
                meta,
                target,
                region=region,
                deadline=deadline,
                exhaustive=exhaustive,
                on_idle=unpin,
            )
        finally:
            del pixels

    def find(
        self,
        pixels: Pixels,
        meta: FrameMeta,
        target: Target | TargetSpec,
        *,
        region: Rect | Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
        exhaustive: bool = False,
    ) -> FindResult:
        """`pixels`(BGR)에서 target을 찾는다. `exhaustive`면 찾은 뒤에도 모든 방법·배율을 계산해
        `candidates`에 남긴다(`target test --all-scales`). 결과 `match`는 그래도 첫 성공이다."""
        return self._find(
            pixels, meta, target, region=region, deadline=deadline, exhaustive=exhaustive
        )

    def _find(
        self,
        pixels: Pixels,
        meta: FrameMeta,
        target: Target | TargetSpec,
        *,
        region: Rect | Sequence[int] | None,
        deadline: ObservationDeadline | None,
        exhaustive: bool,
        on_idle: Callable[[], None] | None = None,
    ) -> FindResult:
        """`on_idle`은 어느 경로로 끝나든 한 번, 이 픽셀을 쓰는 계산이 모두 끝난 뒤 불린다."""
        started = time.perf_counter()
        try:
            if deadline is not None:
                deadline.start(_find_timeout)
            spec = TargetSpec.of(target)
            image = self.target_image(spec)
            s0 = expected_scale(spec, meta)
            search = self._search_box(spec, meta, pixels, region)
            ox, oy = meta.origin
            sx, sy, sw, sh = search
            area = pixels[sy - oy : sy - oy + sh, sx - ox : sx - ox + sw]
            # 검색 범위가 프레임과 겹치지 않으면(빈 범위) 계산할 것이 없다: 후보 없음
            attempts = self._attempts(spec, s0) if area.size else []
            if attempts and not spec.rgb and area.ndim == 3:
                area = _u8(cv2.cvtColor(area, cv2.COLOR_BGR2GRAY))
        except BaseException:
            if on_idle is not None:
                on_idle()  # 일감을 만들기 전: 이 픽셀을 쓰는 계산이 없다
            raise
        candidates: list[Candidate] = []
        accepted: Candidate | None = None
        job = _Job((spec, image, area, (sx, sy)), attempts, on_idle)
        del area
        try:
            if attempts:
                _start(job)
            for index in range(len(attempts)):
                if accepted is not None and not exhaustive:
                    break
                candidate, error = job.wait(index, deadline)
                if error is not None:
                    raise error
                if candidate is None:
                    continue
                candidates.append(candidate)
                if candidate.accepted and accepted is None:
                    accepted = candidate
        finally:
            job.release()  # 시작하지 않은 시도는 픽셀 없이 버려진다
        if deadline is not None:
            deadline.ensure(_find_timeout)
        best = accepted or max(candidates, key=lambda c: c.score, default=None)
        match = None
        if accepted is not None:
            match = VisionMatch(
                rect=accepted.rect,
                score=accepted.score,
                scale=accepted.scale,
                method=accepted.method,
                click=click_point(accepted.rect, spec.anchor, spec.offset, accepted.scale),
                target=spec.name,
                frame_info=meta.ref(),
                window=meta.window,
                frame=meta.frame,
            )
        return FindResult(
            match=match,
            best=best,
            candidates=tuple(candidates),
            search=search,
            threshold=spec.threshold,
            expected_scale=s0,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    def peaks_capture(
        self,
        capture_id: int,
        meta: FrameMeta,
        target: Target | TargetSpec,
        *,
        scale: float,
        method: str = "template_multiscale",
        region: Rect | Sequence[int] | None = None,
        count: int = 3,
    ) -> tuple[Candidate, ...]:
        """저장소 캡처에서 `peaks` (버렸으면 `frame_expired`)."""
        with self._need_store().pinned(capture_id) as (pixels,):
            return self.peaks(
                pixels, meta, target, scale=scale, method=method, region=region, count=count
            )

    def peaks(
        self,
        pixels: Pixels,
        meta: FrameMeta,
        target: Target | TargetSpec,
        *,
        scale: float,
        method: str = "template_multiscale",
        region: Rect | Sequence[int] | None = None,
        count: int = 3,
    ) -> tuple[Candidate, ...]:
        """매칭 후보 증거용 (M3 2.6): 그 배율의 점수 지도에서 **서로 다른 자리** 상위 `count`개.
        봉우리를 하나 고를 때마다 그 상자와 겹치는 자리를 지운다(겹침 억제) — 그래서 상자끼리
        겹치지 않는다. 색 확인은 하지 않는다(점수만). 실패 증거를 남길 때만 부른다."""
        spec = TargetSpec.of(target)
        image = self.target_image(spec)
        search = self._search_box(spec, meta, pixels, region)
        ox, oy = meta.origin
        sx, sy, sw, sh = search
        area = pixels[sy - oy : sy - oy + sh, sx - ox : sx - ox + sw]
        if not area.size:
            return ()
        if not spec.rgb and area.ndim == 3:
            area = _u8(cv2.cvtColor(area, cv2.COLOR_BGR2GRAY))
        template = _resize(image.bgr if spec.rgb else image.gray, scale)
        th, tw = template.shape[:2]
        if tw < MIN_TEMPLATE_PX or th < MIN_TEMPLATE_PX or tw > area.shape[1] or th > area.shape[0]:
            return ()
        mask = None if image.mask is None else _resize(image.mask, scale, cv2.INTER_NEAREST)
        found: list[Candidate] = []
        for value, (x, y) in score_peaks(area, template, count, mask):
            accepted = value >= spec.threshold
            found.append(
                Candidate(
                    method,
                    scale,
                    (sx + x, sy + y, tw, th),
                    value,
                    None,
                    accepted,
                    "" if accepted else "threshold",
                )
            )
        return tuple(found)

    @staticmethod
    def _attempts(spec: TargetSpec, s0: float) -> list[tuple[str, float]]:
        attempts: list[tuple[str, float]] = []
        for method in spec.methods:
            if method == "template":
                attempts.append((method, 1.0))
            elif method == "template_multiscale":
                attempts.extend((method, s0 * step) for step in SCALE_STEPS)
        return attempts

    @staticmethod
    def _search_box(
        spec: TargetSpec, meta: FrameMeta, pixels: Pixels, region: Rect | Sequence[int] | None
    ) -> Box:
        frame_box = (meta.origin[0], meta.origin[1], int(pixels.shape[1]), int(pixels.shape[0]))
        if region is not None:
            wanted = _box(region)
        elif spec.search_region is not None:
            wanted = normalized_to_pixels(spec.search_region, meta.client_size)
        else:
            return frame_box
        return _intersect(wanted, frame_box)

    @staticmethod
    def _try(
        spec: TargetSpec,
        image: TargetImage,
        area: Pixels,
        at: tuple[int, int],
        method: str,
        scale: float,
    ) -> Candidate | None:
        template = _resize(image.bgr if spec.rgb else image.gray, scale)
        th, tw = template.shape[:2]
        if tw < MIN_TEMPLATE_PX or th < MIN_TEMPLATE_PX:
            return None
        if tw > area.shape[1] or th > area.shape[0]:
            return None
        mask = None if image.mask is None else _resize(image.mask, scale, cv2.INTER_NEAREST)
        score, (x, y) = _best(area, template, mask)
        rect = (at[0] + x, at[1] + y, tw, th)
        color_diff: float | None = None
        reason = "" if score >= spec.threshold else "threshold"
        if spec.rgb:
            found = area[y : y + th, x : x + tw]
            mean_found = np.array(cv2.mean(found, mask=mask)[:3])
            mean_template = np.array(cv2.mean(template, mask=mask)[:3])
            color_diff = float(np.max(np.abs(mean_found - mean_template)))
            if not reason and color_diff > spec.color_tolerance:
                reason = "color"
        return Candidate(method, scale, rect, score, color_diff, not reason, reason)

    # ------------------------------------------------------------ 비교

    def diff(
        self,
        a: int,
        b: int,
        *,
        region: Rect | Sequence[int] | None = None,
        deadline: ObservationDeadline | None = None,
    ) -> float:
        """두 캡처의 차이 (0~1). 같은 픽셀(동일성 키)이면 0. `region`은 이미지 기준. 계산이
        짧아 기한은 시작 전에만 본다(M1 2.5)."""
        if deadline is not None:
            deadline.start(_find_timeout)
        store = self._need_store()
        if store.identity(a) == store.identity(b):
            return 0.0
        with store.pinned(a, b) as (pa, pb):
            return diff_pixels(pa, pb, region)
