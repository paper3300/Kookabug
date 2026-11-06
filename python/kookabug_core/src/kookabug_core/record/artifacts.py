"""스텝 artifacts 저장과 기록 정책 집행 (`Recorder`).

모든 저장은 `Recorder`를 거친다: `ctx.artifacts.save`, 예외 스크린샷, (M1) 캡처 노드.

- 스크린샷은 스텝의 실효 정책(구간 끄기·비밀값 입력)과 **획득 당시 표시**를 둘 다 통과해야 남긴다.
  막히면 저장하지 않고 `step.end.omitted`에 `{kind, name, reason, source}`를 남긴다. 판정은 바꾸지
  않는다
- 캡처 표시: 런타임이 캡처할 때마다 이미지에 실행 안 번호(`Image.capture_id`)를 붙이고, 얻은
  스텝에서 스크린샷이 막혔으면 그 번호에 이유를 남긴다. 번호는 복사·출력·워커 경계를 넘어도
  이미지에 남으므로, 꺼 둔 구간이나 비밀값 스텝에서 얻은 프레임은 나중에 켜진 스텝이 저장하려 해도
  막힌다 (`capture_policy`). 바이트만 있는 이미지도 같다. 같은 화면을 켜진 스텝이 새로 얻으면 새
  캡처다
- 예외 스크린샷: 노드가 `error`로 끝나면 **그 스텝 안에서 얻은 마지막 캡처**만 후보다. 그 스텝에서
  캡처가 없으면 남기지 않는다
- 실패 증거(M1 2.15): 처리되지 않은 fail이 확정된 스텝은 **그 스텝 아래(자기와 안쪽 스텝)에서
  얻은 마지막 캡처**를 `steps/<스텝>_fail`로 남긴다. 안쪽 스텝이 닫힐 때 그 마지막 캡처를 부른
  스텝으로 올린다(부른 스텝의 것보다 나중일 때만). 그 아래에서 캡처가 없으면 남기지 않는다
- 서브그래프 호출 스텝의 실패·예외 증거는 호출 노드의 비밀값 입력으로 막지 않는다(구간 끄기와 획득
  당시 표시는 본다). 그 프레임은 안쪽 스텝이 얻은 것이고, 비밀값을 받은 안쪽 스텝의 프레임은 획득
  당시 표시로 막히므로 안쪽 스텝 각각이 남길 수 있는 것보다 넓게 남기지 않는다 (M1 T12)
- 비밀값 가림(`redact_secrets`, 워크스페이스 `record.redact_secrets`)이 꺼져 있으면(기본, D3) 비밀값
  입력·민감 target으로는 막지 않는다. 아래 `secret_input`·`sensitive_target`은 켜져 있을 때만이다
- 에이전트용 분류 (M5 3.8): 꺼져 있어도 "켜져 있었다면 막혔을" 스크린샷·썸네일·OCR 글자·비밀값이
  든 텍스트 artifact의 경로를 스텝마다 모아 `step.end.agent_withhold`로, 입력·출력에 비밀값이 있던
  스텝은 `step.end.secret`으로 남긴다(`agent_marks`). 파일은 그대로 남고(D3) daemon이 에이전트에게만
  주지 않는다
- OCR 글자: 스텝 안에서 마지막으로 읽은 글자를 스텝을 닫을 때 `steps/<스텝>_ocr.txt`로 남긴다.
  `sensitive` target으로 읽은 적이 있으면 남기지 않고 `sensitive_target`, 그 밖에는 스크린샷과
  같은 정책(구간 끄기·비밀값 입력·획득 당시 표시)을 따른다 — 화면에서 읽은 글자도 화면이다
- 경로는 실행 폴더 기준 `steps/<스텝>_<이름>`. 이미지 파일을 복사할 때는 확장자를 붙인다
- 프레임 저장소(M1 2.7, `FrameRegistry`)가 있으면 캡처 픽셀은 저장소에 있고 노드는 픽셀 없는
  **참조 이미지**(`capture_id`만)를 받는다. 참조 이미지를 남길 때는 저장소 픽셀을 PNG로 인코딩해
  `.png`로 둔다. 기록 정책 판정은 인코딩 전에 `capture_id`로 한다(막힌 프레임은 인코딩도 안 함)

**증거 프레임·썸네일** (M3 2.6, 프레임 저장소가 있는 실행만 — 픽셀을 인코딩할 곳이 저장소다)

- 썸네일: 직접 캡처한 스텝이 닫힐 때 그 스텝의 마지막 캡처를 긴 변 480 JPEG로 `thumbs/<스텝>.jpg`에
  둔다. 스크린샷 정책(구간 끄기·비밀값 입력·획득 당시 표시)을 그대로 따르고 막히면
  `omitted`에 `kind: thumbnail`. 이벤트 `artifacts`에는 적지 않는다 — 반복 안 스텝은 첫 회차와
  마지막 두 회차만 남기므로(회차가 넘어갈 때 그 반복 범위의 두 회차 전 썸네일을 지운다) 파일 유무가
  기준이다
- 실패 스텝 증거: fail 출구·`error`·`stale_observation`으로 끝난 스텝은 마지막 캡처
  (`_fail`·`_error`)에 더해 그 스텝의 첫 캡처(`_first`)와 중간 캡처(`_mid`)를 남기고
  `step.end.evidence`를 쓴다. 중간은
  저장소가 붙잡은 표본 중 (시작 + 끝)/2에 가장 가까운 장이고(최선 노력), 편차가 경과의 1/4을 넘거나
  첫·마지막 말고 표본이 없으면 `mid: null`·`mid_missing: no_sample_near_mid`. 시각은 스텝 시작 기준
  벽시계 ms
- 매칭 후보: 코어 찾기·대기 노드(`CANDIDATE_NODES`)가 fail 출구로 끝나면 그 스텝 마지막 찾기의 상위
  후보 3개와 임계값. 스크린샷이 막힌 스텝(비밀값·구간 끄기)에는 남기지 않는다
"""

from __future__ import annotations

import contextlib
import json
import re
import shutil
import time
from collections.abc import Callable, Collection, Hashable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Protocol, cast, runtime_checkable

from kookabug_core.record.policy import OmitReason, RecordPolicy, StepPolicy, VideoMode, find_secret
from kookabug_sdk import Secret
from kookabug_sdk.types import Image, Match, WindowRef

__all__ = [
    "CANDIDATE_NODES",
    "ERROR_SCREENSHOT",
    "FAIL_SCREENSHOT",
    "FIRST_SCREENSHOT",
    "MID_MISSING",
    "MID_SCREENSHOT",
    "OCR_TEXT",
    "STEPS_DIR",
    "THUMBS_DIR",
    "THUMB_LONG_SIDE",
    "ArtifactStore",
    "CaptureMeta",
    "EvidenceCandidate",
    "FileArtifacts",
    "FindEvidence",
    "FrameRegistry",
    "MidChoice",
    "Recorder",
    "StagedFrame",
    "StepFrames",
    "ThumbnailStore",
    "TimedCapture",
    "artifact_path",
    "choose_mid",
    "find_with_report",
    "image_artifact_path",
    "is_reference_image",
    "thumbnail_path",
]

STEPS_DIR: Final = "steps"
THUMBS_DIR: Final = "thumbs"
"""스텝 썸네일 폴더 (`thumbs/<스텝>.jpg`, M3 2.6)."""
THUMB_LONG_SIDE: Final = 480
ERROR_SCREENSHOT: Final = "error"
"""예외 스크린샷의 이름 (`steps/<스텝>_error.png`)."""
FAIL_SCREENSHOT: Final = "fail"
"""실패 증거의 이름 (`steps/<스텝>_fail.png`, M1 2.15)."""
FIRST_SCREENSHOT: Final = "first"
"""실패 스텝의 첫 캡처 (`steps/<스텝>_first.png`, M3 2.6)."""
MID_SCREENSHOT: Final = "mid"
"""실패 스텝의 중간 캡처 (`steps/<스텝>_mid.png`, M3 2.6)."""
MID_MISSING: Final = "no_sample_near_mid"
OCR_TEXT: Final = "ocr.txt"
"""스텝의 마지막 OCR 글자 (`steps/<스텝>_ocr.txt`)."""
CANDIDATES_KEPT: Final = 3
CANDIDATE_NODES: Final = frozenset(
    {
        "core.image.wait",
        "core.image.wait_any",
        "core.image.wait_gone",
        "core.image.click",
        "core.assert.visible",
    }
)
"""fail 출구로 끝나면 매칭 후보를 남기는 코어 찾기·대기 노드 (조율자 결정 Q11). 플러그인은 SDK
경로가 생길 때."""

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStore(Protocol):
    """artifacts를 실제로 두는 곳. 정책은 보지 않는다 (`Recorder`가 본다)."""

    def save(self, step: str, image: Image, name: str) -> str:
        """저장하고 실행 폴더 기준 경로를 돌려준다."""
        ...

    def save_text(self, step: str, name: str, text: str) -> str: ...


@runtime_checkable
class ThumbnailStore(Protocol):
    """썸네일을 둘 수 있는 곳 (M3 2.6). 같은 스텝이면 덮어쓴다. 없는 파일 지우기는 아무 일 없다."""

    def save_thumbnail(self, step: str, data: bytes) -> str: ...
    def delete_thumbnail(self, rel: str) -> None: ...


def thumbnail_path(step: str) -> str:
    return f"{THUMBS_DIR}/{step}.jpg"


@dataclass(frozen=True, slots=True)
class CaptureMeta:
    """캡처 하나의 관측 조건 (찾기·OCR·재검증용, M1 2.5).

    `client_size`·`dpi`는 캡처 순간 대상 창의 것, `origin`은 픽셀 (0, 0)의 클라이언트 좌표(영역
    캡처면 영역 왼쪽 위), `backend`는 캡처 방식(`wgc`·`fake`), `window`는 캡처한 창(SDK 참조),
    `observed_at`은 관측 시각(벽시계 초), `frame`은 프레임 번호.
    """

    client_size: tuple[int, int]
    dpi: int = 96
    origin: tuple[int, int] = (0, 0)
    backend: str = "image"
    window: WindowRef | None = None
    observed_at: float | None = None
    frame: int | None = None


@dataclass(frozen=True, slots=True)
class StagedFrame:
    """플랫폼이 캡처한 픽셀과 그 동일성 키 — 저장소에 등록하기 전 (M1 2.7).

    `key`가 같으면 같은 픽셀이다(같은 프레임·같은 자르기). 코어는 `pixels`를 열지 않는다.
    `meta`는 그 캡처의 관측 조건이다 (저장소가 캡처 번호와 함께 둔다).
    """

    key: Hashable
    pixels: Any = field(repr=False)
    meta: CaptureMeta | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TimedCapture:
    """캡처 번호와 그 캡처 시각 (실행기 벽시계 ms)."""

    capture_id: int
    at_ms: int


@dataclass(frozen=True, slots=True)
class StepFrames:
    """열린 스텝의 첫 캡처와 저장소가 붙잡은 증거 표본 (시각 순, M3 2.6)."""

    first: TimedCapture
    samples: tuple[TimedCapture, ...] = ()


@dataclass(frozen=True, slots=True)
class MidChoice:
    capture: TimedCapture
    offset_ms: int
    """(시작 + 끝)/2와의 차이 (절댓값)."""


def choose_mid(
    start_ms: int, end_ms: int, samples: Sequence[TimedCapture], exclude: Collection[int] = ()
) -> MidChoice | None:
    """표본 중 (시작 + 끝)/2에 가장 가까운 캡처 (최선 노력, 조율자 결정 Q13). `exclude`(첫·마지막
    캡처 번호)는 고르지 않는다. 그런 표본이 없거나 고른 장의 차이가 경과의 1/4을 넘으면 None —
    캡처하지 않은 시각의 장면은 만들 수 없다."""
    center = (start_ms + end_ms) / 2
    pool = [s for s in samples if s.capture_id not in exclude]
    if not pool:
        return None
    best = min(pool, key=lambda s: abs(s.at_ms - center))
    offset = abs(best.at_ms - center)
    if offset > (end_ms - start_ms) / 4:
        return None
    return MidChoice(best, round(offset))


@dataclass(frozen=True, slots=True)
class EvidenceCandidate:
    """매칭 후보 하나: `rect`는 찾은 이미지 좌표 `(x, y, w, h)`."""

    rect: tuple[int, int, int, int]
    score: float
    scale: float


@dataclass(frozen=True, slots=True)
class FindEvidence:
    """찾기 한 번의 상위 후보 (점수 순, 서로 다른 자리)와 임계값 (`step.end.evidence`, M3 2.6).

    `capture_id`는 찾은 캡처. `refine`이 있으면 증거를 남길 때 한 번 불러 더 나은 후보(점수 지도에서
    겹침 억제로 고른 서로 다른 자리)로 바꾼다 — 찾기마다 하지 않고 실패 증거를 남길 때만 비용을
    쓴다. 실패하면(버린 프레임 등) 이 후보 그대로다."""

    target: str
    threshold: float
    candidates: tuple[EvidenceCandidate, ...] = ()
    capture_id: int | None = None
    refine: Callable[[], FindEvidence] | None = field(default=None, compare=False, repr=False)

    @property
    def best(self) -> float:
        """가장 높은 후보 점수 (후보가 없으면 -1)."""
        return max((c.score for c in self.candidates), default=-1.0)

    def refined(self) -> FindEvidence:
        if self.refine is None:
            return self
        try:
            return self.refine()
        except Exception:
            return self

    def to_event(self) -> dict[str, Any]:
        return {
            "candidates": [
                {"rect": list(c.rect), "scale": c.scale, "score": max(-1.0, min(1.0, c.score))}
                for c in self.candidates[:CANDIDATES_KEPT]
            ],
            "target": self.target,
            "threshold": self.threshold,
        }


def find_with_report(
    engines: Any, image: Image, target: Any, *, region: Any, limits: Any
) -> tuple[Match | None, FindEvidence | None]:
    """엔진의 찾기. 엔진이 매칭 후보를 주면(`find_report`) 그것도, 아니면 후보 없이."""
    report: Any = getattr(engines, "find_report", None)
    if callable(report):
        found, evidence = cast(tuple[Any, Any], report(image, target, region=region, limits=limits))
        return cast(Match | None, found), cast(FindEvidence | None, evidence)
    return engines.find(image, target, region=region, limits=limits), None


class FrameRegistry(Protocol):
    """실행의 프레임 저장소 (`kookabug_platform.frames.FrameStore`). 코어는 이 모양만 안다."""

    def register(
        self, capture_id: int, staged: StagedFrame, step: str, *, at_ms: int | None = None
    ) -> None:
        """캡처 하나를 그 스텝의 프레임으로 등록한다. `at_ms`(캡처 시각)를 주면 그 스텝의 첫
        캡처·증거 표본도 붙잡는다 (M3 2.6)."""
        ...

    def step_frames(self, step: str) -> StepFrames | None:
        """열린 스텝의 첫 캡처와 남아 있는 표본 (시각 없이 등록했으면 None)."""
        ...

    def encode_jpeg(self, capture_id: int, long_side: int) -> bytes:
        """그 캡처를 긴 변 `long_side` 이하 JPEG로 (썸네일). 버린 프레임이면 `frame_expired`."""
        ...

    def close_step(self, step: str, *, parent: str | None = None) -> None:
        """스텝이 닫혔다: 그 스텝 증거 등급을 푼다. `parent`(부른 스텝)를 주면 마지막 캡처를 그
        스텝의 증거로 넘긴다 (실패 증거, M1 2.15)."""
        ...

    def mark_output(self, capture_id: int) -> None:
        """스텝 출력(이미지 핀·`Match`)으로 나간 캡처 (출력 참조 등급)."""
        ...

    def encode_png(self, capture_id: int) -> bytes:
        """그 캡처의 픽셀을 PNG로. 버린 프레임이면 `frame_expired`."""
        ...


def is_reference_image(image: Image) -> bool:
    """픽셀 없는 참조 이미지인가 (`data`·`path` 없이 `capture_id`만)."""
    return image.data is None and image.path is None and image.capture_id is not None


def artifact_path(step: str, name: str, suffix: str, taken: Callable[[str], bool]) -> str:
    """`steps/<스텝>_<이름><확장자>`. 이름의 경로 문자는 `_`로 바꾸고, 이미 쓴 경로면 `-2`, `-3`….

    `suffix`(`.png` 등)는 이름이 그것으로 끝나지 않을 때만 붙인다.
    """
    safe = _UNSAFE.sub("_", name).strip("._") or "artifact"
    if suffix and not safe.lower().endswith(suffix.lower()):
        safe += suffix
    stem, dot, ext = safe.rpartition(".")
    if not dot or not stem:
        stem, ext = safe, ""
    path = f"{STEPS_DIR}/{step}_{safe}"
    n = 2
    while taken(path):
        path = f"{STEPS_DIR}/{step}_{stem}-{n}{'.' + ext if ext else ''}"
        n += 1
    return path


def image_artifact_path(step: str, image: Image, name: str, taken: Callable[[str], bool]) -> str:
    """이미지 artifact 경로. 바이트(`data`)가 우선이고, 파일(`path`)을 복사할 때만 확장자를
    붙인다."""
    suffix = image.path.suffix if image.data is None and image.path is not None else ""
    return artifact_path(step, name, suffix, taken)


class FileArtifacts:
    """실행 폴더(`folder`)의 `steps/`에 파일로 둔다. `Image.data`면 바이트, `Image.path`면 복사."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _taken(self, rel: str) -> bool:
        return (self.folder / rel).exists()

    def _target(self, rel: str) -> Path:
        path = self.folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def save(self, step: str, image: Image, name: str) -> str:
        if image.data is None and image.path is None:
            raise ValueError(f"저장할 이미지 내용이 없다 (path·data 둘 다 없음): '{name}'")
        rel = image_artifact_path(step, image, name, self._taken)
        if image.data is not None:
            self._target(rel).write_bytes(image.data)
        else:
            assert image.path is not None
            shutil.copyfile(image.path, self._target(rel))
        return rel

    def save_text(self, step: str, name: str, text: str) -> str:
        rel = artifact_path(step, name, "", self._taken)
        self._target(rel).write_text(text, encoding="utf-8", newline="\n")
        return rel

    def save_thumbnail(self, step: str, data: bytes) -> str:
        rel = thumbnail_path(step)
        self._target(rel).write_bytes(data)
        return rel

    def delete_thumbnail(self, rel: str) -> None:
        (self.folder / rel).unlink(missing_ok=True)


type LoopKey = tuple[int, int]
"""반복 하나(실행 안 일련번호)와 그 회차."""


@dataclass(frozen=True, slots=True)
class _CaptureMark:
    step: str
    block: tuple[OmitReason, str | None]
    """획득한 스텝에서 스크린샷을 막은 이유와 위치."""


@dataclass(frozen=True, slots=True)
class _OcrRead:
    text: str
    image: Image
    sensitive: bool


@dataclass(eq=False)
class _StepRecord:
    policy: StepPolicy
    artifacts: list[str] = field(default_factory=list[str])
    omitted: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    last_capture: Image | None = None
    """이 스텝이 직접 얻은 마지막 캡처 (예외 스크린샷)."""
    last_under: Image | None = None
    """이 스텝과 안쪽 스텝이 얻은 마지막 캡처 (실패 증거)."""
    ocr: _OcrRead | None = None
    """마지막으로 읽은 OCR 글자."""
    ocr_sensitive: bool = False
    """`sensitive` target으로 읽은 적이 있다."""
    call: bool = False
    """서브그래프 호출 스텝 (실패·예외 증거는 비밀값 입력으로 막지 않는다)."""
    started_ms: int = 0
    """스텝을 연 시각 (벽시계 ms — 증거 시각의 기준)."""
    loops: tuple[LoopKey, ...] = ()
    """이 스텝을 감싼 반복 회차들 (바깥부터, 썸네일 정리)."""
    last_at: int | None = None
    last_under_at: int | None = None
    find: FindEvidence | None = None
    """이 스텝의 마지막 찾기 (매칭 후보)."""
    evidence: dict[str, Any] | None = None
    """`step.end.evidence` (실패·예외 증거를 남길 때 정한다)."""
    secret_input: str | None = None
    """입력 안 첫 비밀값의 위치 (가림 여부와 상관없이, 에이전트용 분류)."""
    secret: bool = False
    """입력이나 출력에 비밀값이 있었다 (`step.end.secret`)."""
    ocr_sensitive_any: bool = False
    """가림 여부와 상관없이 `sensitive` target으로 읽은 적이 있다."""
    withhold: list[str] = field(default_factory=list[str])
    """가림이 켜져 있었다면 남기지 않았을 증거 경로 (`step.end.agent_withhold`)."""
    secret_fields: list[str] = field(default_factory=list[str])
    """노드 쪽이 비밀값을 가린 `step.end` 필드 (pointer, `step.end.secret_paths`에 더한다 —
    판단 노드가 답에서 인증값을 `***`로 바꾼 출력·메시지, M5)."""


class Recorder:
    """한 실행의 기록 정책 집행. 실행기가 스텝마다 `open_step` → … → `close_step`을 부른다.

    `clock`은 증거 시각의 벽시계(ms)다 — 실행기는 경과 시계(`wall`)를 준다."""

    def __init__(
        self,
        store: ArtifactStore,
        frames: FrameRegistry | None = None,
        *,
        clock: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.frames = frames
        """프레임 저장소 (없으면 캡처 이미지가 바이트·파일을 그대로 든다 — M0b)."""
        self.clock: Callable[[], int] = clock or (lambda: time.monotonic_ns() // 1_000_000)
        self._open: dict[str, _StepRecord] = {}
        self._policies: dict[str, StepPolicy] = {}
        self._captures = 0
        self._blocked: dict[int, _CaptureMark] = {}
        """막힌 캡처만 (`capture_id` → 표시). 없으면 얻을 때 허용된 것이다."""
        self._would_block: set[int] = set()
        """가림이 꺼진 실행에서 비밀값 입력 스텝이 얻은 캡처 (켜져 있었다면 `_blocked`였을 것)."""
        self._thumbs: dict[LoopKey, list[tuple[tuple[LoopKey, ...], str]]] = {}
        """반복 회차 → 그 회차 안에서 남긴 썸네일 (회차 사슬, 경로)."""
        self.redact_secrets = False
        """워크스페이스 `record.redact_secrets` (실행기가 정한다). false면 비밀값 입력 스텝의 화면,
        민감 target의 OCR 글자, 텍스트 artifact의 비밀값을 그대로 남긴다 (D3)."""

    # ------------------------------------------------------------ 스텝 수명

    def open_step(
        self,
        step: str,
        policy: RecordPolicy,
        *,
        call: bool = False,
        loops: tuple[LoopKey, ...] = (),
    ) -> None:
        """`call`이면 서브그래프 호출 스텝이다: 그 스텝의 실패·예외 증거(안쪽 스텝이 얻은 프레임)는
        호출 노드의 비밀값 입력으로 막지 않는다. 비밀값을 받은 안쪽 스텝의 프레임은 획득 당시
        표시가 막으므로, 남는 것은 안쪽 스텝이 스스로 남길 수 있던 프레임뿐이다.

        `loops`는 이 스텝을 감싼 반복 회차들이다(호출 경계를 넘어 바깥부터) — 썸네일 정리용."""
        record = _StepRecord(StepPolicy(policy), call=call, started_ms=self.clock(), loops=loops)
        self._open[step] = record
        self._policies[step] = record.policy

    def note_inputs(self, step: str, inputs: Mapping[str, Any], where: str) -> None:
        """스텝 시작 때 계산한 입력. 비밀값 가림(`redact_secrets`)이 켜져 있고 비밀값이 있으면 그
        스텝의 스크린샷·영상을 막는다.

        `where`는 노드 입력의 위치(`<그래프>#/nodes/<노드>/in`)로, 생략 이유의 `source` 앞에 붙는다.
        """
        found = find_secret(inputs)
        if found is None:
            return
        record = self._open[step]
        record.secret_input = where + found
        record.secret = True
        if not self.redact_secrets:
            return
        record.policy = StepPolicy(record.policy.policy, where + found)
        self._policies[step] = record.policy

    def close_step(
        self, step: str, *, parent: str | None = None
    ) -> tuple[list[str], list[dict[str, Any]]]:
        """스텝을 닫고 `(artifacts, omitted)`를 돌려준다. 스텝의 마지막 캡처는 놓는다 — `parent`
        (부른 스텝)를 주면 그 스텝 아래의 마지막 캡처로 올린다(프레임 저장소에서도 그 스텝의 증거로
        넘긴다). OCR 글자는 그 전에 `ocr_artifact`로 남긴다."""
        record = self._open.pop(step, None)
        above = self._open.get(parent) if parent is not None else None
        if self.frames is not None:
            self.frames.close_step(step, parent=parent if above is not None else None)
        if record is None:
            return [], []
        last = record.last_under
        if above is not None and last is not None and _later(last, above.last_under):
            above.last_under = last
            above.last_under_at = record.last_under_at
        return record.artifacts, record.omitted

    def evidence(self, step: str) -> dict[str, Any] | None:
        """그 열린 스텝의 `step.end.evidence` (실패·예외 증거를 남겼을 때만)."""
        record = self._open.get(step)
        return None if record is None else record.evidence

    def note_outputs(self, outputs: Mapping[str, Any]) -> None:
        """스텝 출력에 든 캡처(이미지·`Match`의 `capture_id`)를 출력 참조로 표시한다. 이미 버린
        캡처는 건너뛴다(출력은 그대로 남고, 나중에 쓰면 `frame_expired`)."""
        if self.frames is None:
            return
        # engine 패키지가 이 모듈을 import한다 (_masked_text와 같은 이유로 늦게)
        from kookabug_core.engine.errors import EngineError

        for capture_id in _capture_ids(outputs):
            try:
                self.frames.mark_output(capture_id)
            except EngineError:
                continue

    def policy(self, step: str) -> StepPolicy:
        return self._policies[step]

    def mark_secret(self, step: str) -> None:
        """그 열린 스텝의 출력에 비밀값이 있었다 (`step.end.secret`)."""
        record = self._open.get(step)
        if record is not None:
            record.secret = True

    def mark_secret_fields(self, step: str, pointers: Sequence[str]) -> None:
        """그 열린 스텝의 `step.end` 필드에 비밀값(가린 자리)이 있었다: 에이전트용 분류에 더하고
        스텝도 `secret`으로 둔다."""
        record = self._open.get(step)
        if record is None:
            return
        record.secret = True
        for pointer in pointers:
            if pointer not in record.secret_fields:
                record.secret_fields.append(pointer)

    def secret_fields(self, step: str) -> list[str]:
        record = self._open.get(step)
        return [] if record is None else list(record.secret_fields)

    def agent_marks(self, step: str) -> tuple[bool, list[str]]:
        """스텝을 닫기 전에: (`step.end.secret`, `step.end.agent_withhold`) — 에이전트용 분류."""
        record = self._open.get(step)
        if record is None:
            return False, []
        return record.secret, list(record.withhold)

    def _withheld(self, record: _StepRecord, image: Image | None, *, secret: bool = True) -> bool:
        """가림이 켜져 있었다면 이 증거를 막았을까 (꺼진 실행만 — 켜져 있으면 이미 막았다)."""
        if self.redact_secrets:
            return False
        if secret and record.secret_input is not None:
            return True
        return image is not None and image.capture_id in self._would_block

    # ------------------------------------------------------------ 캡처·저장

    def captured(self, step: str, image: Image, staged: StagedFrame | None = None) -> Image:
        """캡처 표시: 실행 안 새 `capture_id`를 붙인 이미지를 돌려주고, 얻은 스텝에서 스크린샷이
        막혔으면 그 이유를 그 번호에 남긴다. 노드에는 돌려준 이미지를 준다.

        플랫폼이 주는 이미지의 `frame`·`path`·바이트와 상관없이 캡처마다 번호가 하나씩이다.
        `staged`(저장소에 둘 픽셀)를 주면 그 번호로 프레임 저장소에 등록한다.
        """
        record = self._open.get(step)
        if record is None:
            return image
        self._captures += 1
        tagged = replace(image, capture_id=self._captures)
        at = self.clock()
        if staged is not None:
            if self.frames is None:
                raise RuntimeError("프레임 저장소 없이 저장소용 픽셀을 받았다")
            self.frames.register(self._captures, staged, step, at_ms=at)
        record.last_capture = record.last_under = tagged
        record.last_at = record.last_under_at = at
        block = record.policy.screenshot_block()
        if block is not None:
            self._blocked[self._captures] = _CaptureMark(step, block)
        if not self.redact_secrets and record.secret_input is not None:
            self._would_block.add(self._captures)
        return tagged

    def screenshot(
        self, step: str, image: Image, name: str, *, evidence: bool = False
    ) -> str | None:
        """정책을 통과하면 저장하고 경로를, 막히면 `omitted`에 남기고 None을 준다. `evidence`는
        실행기가 남기는 실패·예외 증거다(호출 스텝이면 비밀값 입력을 보지 않는다)."""
        record = self._open[step]
        secret = not (evidence and record.call)
        block = self._block(record, image, secret=secret)
        if block is not None:
            reason, source = block
            entry: dict[str, Any] = {"kind": "screenshot", "name": name, "reason": reason}
            if source is not None:
                entry["source"] = source
            record.omitted.append(entry)
            return None
        if is_reference_image(image) and self.frames is not None:
            assert image.capture_id is not None
            image = replace(image, data=self.frames.encode_png(image.capture_id))
            if not name.lower().endswith(".png"):
                name += ".png"
        withheld = self._withheld(record, image, secret=secret)
        path = self.store.save(step, image, name)
        record.artifacts.append(path)
        if withheld:
            record.withhold.append(path)
        return path

    def error_screenshot(self, step: str) -> str | None:
        """노드가 `error`로 끝났을 때: 그 스텝의 마지막 캡처를 (정책이 허용하면) 남긴다. 첫·중간
        캡처와 `evidence`도 정한다 (M3 2.6)."""
        return self.failure_evidence(step, ERROR_SCREENSHOT)

    def fail_screenshot(self, step: str, *, candidates: bool = False) -> str | None:
        """fail로 끝난 스텝: 그 스텝 아래(자기와 안쪽 스텝)의 마지막 캡처를 (정책이 허용하면)
        남긴다 (M1 2.15). 첫·중간 캡처와 `evidence`도 정한다 (M3 2.6). `candidates`면 그 스텝의
        마지막 찾기 후보도 (코어 찾기·대기 노드가 fail 출구로 끝났을 때)."""
        return self.failure_evidence(step, FAIL_SCREENSHOT, candidates=candidates)

    def failure_evidence(self, step: str, name: str, *, candidates: bool = False) -> str | None:
        """실패 스텝 증거 (M3 2.6): 마지막 캡처(`_fail`·`_error`)를 남기고 그 경로를 돌려준다. 그
        스텝이 직접 캡처했고 저장소가 시각을 붙잡았으면 첫 캡처(`_first`)·중간 캡처(`_mid`)도
        남긴다. 시각·후보와 함께 `evidence`(`step.end.evidence`)를 정한다.

        첫·중간 캡처를 남기지 못하면(버린 프레임 등) 그 칸만 빠진다. 마지막 캡처 저장이 실패하면
        `evidence`는 정한 뒤 그 예외를 그대로 던진다(실행기가 경고로 남긴다)."""
        record = self._open.get(step)
        if record is None:
            return None
        error = name == ERROR_SCREENSHOT
        last = record.last_capture if error else record.last_under
        last_at = record.last_at if error else record.last_under_at
        start = record.started_ms
        evidence: dict[str, Any] = {}
        blocked = record.policy.screenshot_block(secret=not record.call) is not None
        # 첫·중간 캡처: 이 스텝이 직접 얻은 프레임만 (호출 스텝은 안쪽 스텝이 남긴다)
        held = (
            self.frames.step_frames(step)
            if self.frames is not None and record.last_capture is not None and last is not None
            else None
        )
        first_shot: tuple[str, int] | None = None
        mid_entry: dict[str, Any] | None = None
        if held is not None and last is not None:
            end = self.clock()
            first = held.first
            if first.capture_id != last.capture_id:
                path = self._evidence_shot(step, first.capture_id, FIRST_SCREENSHOT)
                if path is not None:
                    first_shot = path, first.at_ms
            exclude = {first.capture_id, last.capture_id or 0}
            choice = choose_mid(start, end, held.samples, exclude)
            if choice is None:
                mid_entry = {} if blocked else {"mid": None, "mid_missing": MID_MISSING}
            else:
                path = self._evidence_shot(step, choice.capture.capture_id, MID_SCREENSHOT)
                if path is not None:
                    mid_entry = {
                        "mid": path,
                        "mid_at_ms": max(0, choice.capture.at_ms - start),
                        "mid_offset_ms": choice.offset_ms,
                    }
        failure: Exception | None = None
        last_path: str | None = None
        if last is not None:
            try:
                last_path = self.screenshot(step, last, name, evidence=True)
            except Exception as exc:
                failure = exc
        if last_path is not None:
            evidence["last"] = last_path
            if last_at is not None:
                evidence["last_at_ms"] = max(0, last_at - start)
            if held is not None and last is not None and held.first.capture_id == last.capture_id:
                first_shot = last_path, held.first.at_ms
        if first_shot is not None:
            evidence["first"] = first_shot[0]
            evidence["first_at_ms"] = max(0, first_shot[1] - start)
        if mid_entry and (first_shot is not None or last_path is not None):
            evidence.update(mid_entry)
        if candidates and record.find is not None and not blocked:
            evidence.update(record.find.refined().to_event())
        record.evidence = evidence or None
        if failure is not None:
            raise failure
        return last_path

    def _evidence_shot(self, step: str, capture_id: int, name: str) -> str | None:
        """저장소 캡처 하나를 증거로 남긴다. 정책이 막으면 생략 기록, 버린 프레임 등으로 남기지
        못하면 None."""
        try:
            return self.screenshot(step, Image(capture_id=capture_id), name, evidence=True)
        except Exception:
            return None

    def found(self, step: str, report: FindEvidence) -> None:
        """그 스텝에서 찾기를 했다 (M3 2.6). 매칭 후보는 그 스텝이 **마지막으로 찾은 캡처**의
        것이고, 같은 캡처에서 여러 target을 찾았으면(`wait_any`) 최고점이 가장 높은
        target(가장 "거의 찾은" 것) 하나다 — 출구 순서와 무관하게."""
        record = self._open.get(step)
        if record is None:
            return
        held = record.find
        if (
            held is not None
            and report.capture_id is not None
            and held.capture_id == report.capture_id
            and held.best >= report.best
        ):
            return
        record.find = report

    # ------------------------------------------------------------ 썸네일 (M3 2.6)

    def thumbnail(self, step: str) -> str | None:
        """스텝을 닫기 전에: 그 스텝이 직접 얻은 마지막 캡처를 썸네일로 남긴다 (정책이 막으면
        `omitted`에 `thumbnail`). 저장소 캡처가 아니거나 썸네일을 둘 곳이 없으면 아무것도 안
        한다."""
        record = self._open.get(step)
        store = self.store
        frames = self.frames
        if (
            record is None
            or record.last_capture is None
            or frames is None
            or not isinstance(store, ThumbnailStore)
            or not is_reference_image(record.last_capture)
        ):
            return None
        image = record.last_capture
        block = self._block(record, image)
        if block is not None:
            entry: dict[str, Any] = {"kind": "thumbnail", "reason": block[0]}
            if block[1] is not None:
                entry["source"] = block[1]
            record.omitted.append(entry)
            return None
        assert image.capture_id is not None
        rel = store.save_thumbnail(step, frames.encode_jpeg(image.capture_id, THUMB_LONG_SIDE))
        if self._withheld(record, image):
            record.withhold.append(rel)
        entry_key = (record.loops, rel)
        for key in record.loops:
            self._thumbs.setdefault(key, []).append(entry_key)
        return rel

    def loop_iteration(self, loop: int, iteration: int) -> None:
        """반복 `loop`이 `iteration` 회차를 시작했다: 그 반복 범위의 두 회차 전 썸네일을 지운다(첫
        회차는 남긴다). 그래서 반복 안 스텝의 썸네일은 첫 회차와 마지막 두 회차만 남는다."""
        old = iteration - 2
        if old < 1:
            return
        entries = self._thumbs.pop((loop, old), [])
        store = self.store
        for chain, rel in entries:
            for key in chain:
                if key == (loop, old):
                    continue
                kept = self._thumbs.get(key)
                if kept is None:
                    continue
                with contextlib.suppress(ValueError):
                    kept.remove((chain, rel))
                if not kept:
                    del self._thumbs[key]
            if isinstance(store, ThumbnailStore):
                store.delete_thumbnail(rel)

    def ocr_read(self, step: str, image: Image, text: str, *, sensitive: bool) -> None:
        """그 스텝에서 읽은 OCR 글자 (스텝을 닫을 때 마지막 것을 남긴다)."""
        record = self._open.get(step)
        if record is None:
            return
        record.ocr_sensitive_any = record.ocr_sensitive_any or sensitive
        sensitive = sensitive and self.redact_secrets
        record.ocr = _OcrRead(text, image, sensitive)
        record.ocr_sensitive = record.ocr_sensitive or sensitive

    def ocr_artifact(self, step: str) -> None:
        """스텝을 닫기 전에: 그 스텝에서 마지막으로 읽은 OCR 글자를 남긴다 (또는 생략 이유)."""
        record = self._open.get(step)
        if record is None or record.ocr is None:
            return
        read = record.ocr
        record.ocr = None
        block: tuple[OmitReason, str | None] | None = (
            ("sensitive_target", None) if record.ocr_sensitive else self._block(record, read.image)
        )
        if block is None:
            path = self.store.save_text(step, OCR_TEXT, read.text)
            record.artifacts.append(path)
            if self._withheld(record, read.image) or (
                record.ocr_sensitive_any and not self.redact_secrets
            ):
                record.withhold.append(path)
            return
        entry: dict[str, Any] = {"kind": "text", "name": "ocr", "reason": block[0]}
        if block[1] is not None:
            entry["source"] = block[1]
        record.omitted.append(entry)

    def text(self, step: str, name: str, value: Any) -> str:
        """텍스트 artifact. 비밀값 가림이 켜져 있으면 비밀값은 가린다 (M0b는 텍스트 구간 끄기가
        없다)."""
        record = self._open[step]
        path = self.store.save_text(step, name, _masked_text(value, redact=self.redact_secrets))
        record.artifacts.append(path)
        # 비밀값이 든 텍스트·JSON은 에이전트에게 통째로 주지 않는다 (가림이 꺼진 실행만 원문이 있다)
        if not self.redact_secrets and _has_secret(value):
            record.withhold.append(path)
        return path

    def _block(
        self, record: _StepRecord, image: Image, *, secret: bool = True
    ) -> tuple[OmitReason, str | None] | None:
        # 저장하는 스텝의 정책이 먼저 (더 구체적인 이유), 그다음 획득 당시 표시
        block = record.policy.screenshot_block(secret=secret)
        if block is not None:
            return block
        mark = self._blocked.get(image.capture_id) if image.capture_id is not None else None
        if mark is not None:
            return "capture_policy", mark.block[1]
        return None

    # ------------------------------------------------------------ 영상 (M3)

    def video_policy(self, step: str) -> VideoMode:
        return self._policies[step].video

    def video_allowed(self, step: str, *, run_failed: bool) -> bool:
        """이 스텝 구간의 영상을 남겨도 되는가 (`failed_only`는 실행이 실패했을 때만)."""
        mode = self.video_policy(step)
        return mode == "on" or (mode == "failed_only" and run_failed)


def _later(image: Image, than: Image | None) -> bool:
    """`image`가 `than`보다 나중에 얻은 캡처인가 (캡처 번호는 실행 안에서 늘어난다)."""
    if than is None:
        return True
    return (image.capture_id or 0) > (than.capture_id or 0)


def _capture_ids(value: Any) -> list[int]:
    found: list[int] = []
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, Image):
            if item.capture_id is not None:
                found.append(item.capture_id)
        elif isinstance(item, Match):
            if item.frame_info is not None and item.frame_info.capture_id is not None:
                found.append(item.frame_info.capture_id)
        elif isinstance(item, Mapping):
            stack.extend(cast(Mapping[Any, Any], item).values())
        elif isinstance(item, list | tuple):
            stack.extend(cast(Sequence[Any], item))
    return found


def _has_secret(value: Any) -> bool:
    # engine 패키지가 이 모듈을 import한다 (_masked_text와 같은 이유로 늦게)
    from kookabug_core.engine.events import classified_value

    return bool(classified_value(value, redact=True, pointer="")[1])


def _masked_text(value: Any, *, redact: bool) -> str:
    # engine 패키지가 이 모듈을 import한다 (engine/__init__ → context → Recorder). 순환을 피한다
    from kookabug_core.engine.events import event_value

    if isinstance(value, str):
        return value
    if isinstance(value, Secret):
        return Secret.MASK if redact else value.reveal()
    return json.dumps(
        event_value(value, redact=redact), ensure_ascii=False, sort_keys=True, indent=2
    )
