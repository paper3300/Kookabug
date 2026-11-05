"""영상 녹화 (구현 계획 M3 2.5): 녹화 게이트, 5 fps 격자 조각 쓰기, 녹화 스레드, 가짜 인코더.

- **게이트**(`VideoGate`): 실행기가 스텝을 열고 닫을 때 바꾼다. 값 = 열린 스텝 스택(호출 스택 전체)
  중 하나라도 실효 `video`가 off이거나 비밀값 입력 스텝이면 off, 멈춘 동안 off, 아니면 열린 스텝들
  중 가장 센 `video`(on < failed_only). 열린 스텝이 없으면 워크스페이스·테스트 층 값. 스텝마다
  `step.start` 전에 보류(`pending`)로 바꾸고(게이트 세대를 올림), 입력 계산·비밀값 분류 뒤 정한다.
  보류 동안 녹화 스레드는 새 프레임을 가져오지 않고 보류 전 프레임을 반복한다(조각은 닫지 않음)
- **녹화 스레드**(`VideoRecorder`): 지금 대상 창의 최신 프레임을 초당 5장 가져와 `video/`에 조각으로
  쓴다. 가져오기 전후로 게이트를 읽어, 가져오는 동안 차단(off·멈춤)이 시작됐거나 끝난 시점에
  기록할 수 없으면 그 프레임을 버린다 — 차단이 시작된 뒤 얻은 픽셀은 파일에 들어가지 않는다
- **격자**: 조각 시작 `t0`부터 200 ms 칸마다 한 장. 칸에 새 프레임이 없으면 직전 프레임을 다시
  쓴다 (`frames.jsonl`의 `repeat`). 재생 위치 `k * 200 ms` = 실행 시각 `t0 + k * 200 ms`. 보류가
  아닌 반복이 2초를 넘으면 조각을 닫고 `capture_missed` 빈 구간
- **조각**: 한 모드·한 창·한 크기·최대 60초. 게이트가 off가 되거나 모드·창·크기가 바뀌면 닫는다.
  쓰는 중에는 `seg-NNNN.part.mp4`, 닫으면 `release` → 이름 바꾸기 → `segments.jsonl` 한 줄
- 녹화 스레드는 조각 파일 쓰기와 `segments.jsonl` 덧붙이기만 한다. 지우기·`index.json` 공개는
  마무리(`record.finalize.finalize_video`)가 작성자가 끝난 뒤에만 한다
- 쓰기 실패는 영상만 멈춘다(`failed` 빈 구간). 인코더를 쓸 수 없으면(`probe`) 실행 내내
  `unavailable`
- **준비 중 모으기**(R1 F1): 인코더 열기 시험을 기다리는 동안에도 프레임을 메모리에 모았다가 시험이
  끝나면 그 시각 그대로 쓴다. `starting` 빈 구간은 프레임이 없던 구간(창이 생기기 전 등)뿐이다.
  실행이 먼저 끝나면(멈춤 요청) 모은 프레임을 들고 시험을 더 기다린다(**늦은 인코더 대기**,
  `awaiting_encoder`): 그동안 `encoder-wait.json` 표식을 두고(준비 대기 `waiting` → 쓰기 중
  `writing`), 포기하면(`abandon_encoder_wait`·자체 상한) `starting` 빈 구간에 `reason:
  encoder_not_ready`를 남긴다. 결과를 모두 기록하면 저널에 완료 줄(`encoder_wait: settled`)을
  덧붙이고 표식은 최선 시도로 지운다. 완료 줄 없이 표식이 남은 채 작성자가 끝나면 마무리가 그
  단계로 `encoder_not_ready`·`encoder_stuck`을 정한다 — 어느 쪽이든 `status: omitted`로 드러난다
- **차단 이력**: 반복 칸 채우기는 채울 때마다 게이트의 최신 차단 이력(`VideoGate.fill_limit`)으로
  자른다. 모은 프레임 쓰기도 프레임마다 실시간 루프와 같은 `_apply_spans`로 그 직전 이력을 반영한다

인코더는 `EncoderFactory`로 받는다: 실제는 `kookabug_platform.video.MsmfFactory`(Media Foundation
H.264), 검사는 `FakeEncoderFactory`(칸마다 시각·장면 표시를 JSON 한 줄로 적음). 숨은 검사 설정
`KOOKABUG_VIDEO_TEST`(JSON)로 runner의 인코더를 고른다 (`encoder_factory_from_env`).
"""

from __future__ import annotations

import contextlib
import itertools
import json
import os
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Literal, Protocol, cast

from kookabug_core.record.policy import VideoMode
from kookabug_sdk.types import WindowRef

__all__ = [
    "ENCODER_WAIT_FILE",
    "ENCODER_WAIT_SETTLED",
    "FRAME_MS",
    "INDEX_FILE",
    "INDEX_FORMAT",
    "MAX_LONG_SIDE",
    "PREROLL_BYTES",
    "PREROLL_STOP_WAIT_S",
    "SEGMENTS_FILE",
    "SEGMENT_SLOTS",
    "STOP_GRACE_S",
    "TEST_ENV",
    "VIDEO_DIR",
    "WRITER_FILE",
    "Encoder",
    "EncoderFactory",
    "EncoderProbe",
    "EncoderUnavailable",
    "FakeEncoderFactory",
    "GapReason",
    "GateView",
    "SegmentMode",
    "VideoFrame",
    "VideoGate",
    "VideoReason",
    "VideoRecorder",
    "VideoSource",
    "VideoStatus",
    "encoder_factory_from_env",
    "finish_wait_from_env",
    "scaled_size",
    "stamp",
    "window_key",
]

FRAME_MS: Final = 200
"""격자 칸 길이 (초당 5장, 조율자 결정 Q7)."""
FPS: Final = 1000 / FRAME_MS
SEGMENT_SLOTS: Final = 300
"""조각 하나의 최대 칸 수 (60초)."""
MISSED_SLOTS: Final = 10
"""보류가 아닌 반복이 이만큼(2초) 넘게 이어지면 조각을 닫는다 (`capture_missed`)."""
MAX_LONG_SIDE: Final = 1920
PREROLL_BYTES: Final = 256 * 1024 * 1024
"""인코더 시험을 기다리는 동안 모으는 프레임의 상한 (넘으면 가장 오래된 것부터 버린다, R1 F1)."""
PREROLL_STOP_WAIT_S: Final = 2.0
"""멈춤 요청 뒤 모은 프레임을 들고 인코더 시험을 스스로 더 기다리는 기본 시간 (`STOP_GRACE_S` 안에
조각을 닫을 여유를 남긴다). runner는 `late_wait_s=None`으로 만들어 포기 시점을 직접 정한다
(`abandon_encoder_wait`, run.end 뒤 영상 마무리 단계)."""
ENCODER_WAIT_FILE: Final = "encoder-wait.json"
"""늦은 인코더 대기 표식 (`phase`·`t_start`·`t_end`·`frames`). 녹화 스레드가 대기에 들어갈 때
`phase: waiting`으로 쓰고 시험이 끝나면 `writing`으로 바꾼다 — "대기에 들어갔고 지금 단계가
무엇인가"만 알린다. 결과가 정해졌다는 근거는 저널(`segments.jsonl`)의 완료 줄
`{"encoder_wait": "settled"}` 하나다(결과 줄을 모두 기록한 뒤 덧붙임). 표식 지우기는 그 뒤의 최선
시도다. 완료 줄 없이 표식이 남으면 작성자가 그 단계에서 끝난 것이다 — 마무리가 `waiting`이면
`encoder_not_ready`, `writing`이면 `encoder_stuck`으로 포기 상태를 남긴다
(`record.finalize.abandoned_reason`)."""
ENCODER_WAIT_SETTLED: Final = "settled"
"""저널 완료 줄의 `encoder_wait` 값."""
STOP_GRACE_S: Final = 3.0
"""녹화 멈춤 유예: 녹화 스레드가 이 안에 끝나지 않으면 그 실행의 영상을 포기한다 (2차 검수 N2).
runner는 마무리 유예(`shutdown_grace_ms`)가 짧으면 이보다 짧게 기다린다
(`runner.run.video_wait_s`)."""
VIDEO_DIR: Final = "video"
WRITER_FILE: Final = ".writer"
"""녹화 스레드가 살아 있는 동안 삭제 공유 없이 열어 두는 표시 파일."""
SEGMENTS_FILE: Final = "segments.jsonl"
INDEX_FILE: Final = "index.json"
INDEX_FORMAT: Final = "kookabug.video-index/0"
TEST_ENV: Final = "KOOKABUG_VIDEO_TEST"
"""숨은 검사 설정 (JSON): `{"encoder": "fake"|"msmf", "fake": {...}, "msmf": {...}}`."""
_WAIT_S: Final = 0.05

type SegmentMode = Literal["on", "failed_only"]
type GapReason = Literal[
    "capture_missed",
    "failed",
    "interrupted",
    "no_window",
    "paused",
    "policy_off",
    "secret_input",
    "starting",
    "unavailable",
]
type VideoReason = Literal[
    "backend_missing",
    "encoder_not_ready",
    "encoder_open_failed",
    "encoder_stuck",
    "mf_missing",
    "write_failed",
]
type VideoStatus = Literal["recorded", "none", "unavailable", "failed", "omitted"]

_STRENGTH: Final[dict[str, int]] = {"on": 0, "failed_only": 1, "off": 2}


def stamp(wall: float) -> str:
    """벽시계 초 → `events.jsonl`의 `t`와 같은 UTC 밀리초 `Z` 시각."""
    now = datetime.fromtimestamp(wall, UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def scaled_size(size: tuple[int, int]) -> tuple[int, int]:
    """긴 변이 1920보다 크면 비율을 지켜 줄인 크기."""
    w, h = size
    longest = max(w, h)
    if longest <= MAX_LONG_SIDE:
        return w, h
    scale = MAX_LONG_SIDE / longest
    return max(1, round(w * scale)), max(1, round(h * scale))


def window_key(window: WindowRef) -> str:
    """조각의 `window` (창 바인딩, 없으면 핸들)."""
    return window.binding or f"hwnd:{window.handle:#x}"


# ---------------------------------------------------------------- 프레임·인코더


@dataclass(frozen=True, slots=True)
class VideoFrame:
    """녹화 프레임 하나. 프레임 저장소·`capture_id`를 쓰지 않는다(노드 관측과 섞이지 않음).

    `pixels`는 BGR `uint8` 배열(가짜 인코더만 쓰면 None이어도 됨), `size`는 [w, h], `at`은 픽셀
    시각(벽시계 초), `marker`는 가짜 플랫폼의 장면 표시(검사용)."""

    pixels: Any
    size: tuple[int, int]
    at: float
    marker: str | None = None


class VideoSource(Protocol):
    """플랫폼의 녹화용 프레임: 그 창의 지금 화면. 실패하면 예외(그 칸은 건너뛴다)."""

    def video_frame(self, window: WindowRef, timeout_ms: int) -> VideoFrame: ...


class EncoderUnavailable(Exception):
    """이 PC에서 영상 인코더를 쓸 수 없다 (`reason`: `mf_missing`·`backend_missing`·
    `encoder_open_failed`)."""

    def __init__(self, reason: VideoReason, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason: VideoReason = reason
        self.detail = detail


class Encoder(Protocol):
    def write(self, frame: VideoFrame) -> None: ...

    def release(self) -> None: ...


class EncoderFactory(Protocol):
    def probe(self, folder: Path) -> None:
        """`folder` 안 임시 파일로 인코더를 열어 본다. 쓸 수 없으면 `EncoderUnavailable`."""
        ...

    def open(self, path: Path, size: tuple[int, int]) -> Encoder:
        """`size`(줄인 크기) 조각 파일을 연다. 못 열면 `EncoderUnavailable`
        (`encoder_open_failed`)."""
        ...


# ---------------------------------------------------------------- 가짜 인코더


class _FakeEncoder:
    """칸마다 `{"n", "marker", "pixels_at", "size"}` JSON 한 줄을 조각 파일에 적는다."""

    def __init__(self, factory: FakeEncoderFactory, path: Path, size: tuple[int, int]) -> None:
        self._factory = factory
        self._size = size
        # 삭제 공유 없이 연다 (Windows: 쓰는 동안 다른 쪽이 지울 수 없다 — 실제 인코더와 같은 조건)
        self._file = path.open("w", encoding="utf-8", newline="\n")
        self._n = 0

    def write(self, frame: VideoFrame) -> None:
        self._factory.on("write")
        line = {"n": self._n, "marker": frame.marker, "pixels_at": stamp(frame.at)}
        line["size"] = list(self._size)
        self._file.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._file.flush()
        self._n += 1

    def release(self) -> None:
        self._factory.on("release")
        self._file.close()


@dataclass
class FakeEncoderFactory:
    """검사용 인코더. 고장 주입(`KOOKABUG_VIDEO_TEST`의 `fake`):

    - `stuck`: `{"op": "write"|"release", "nth": N, "resume_after_s": 초|null, "signal": 경로}` —
      N번째 그 동작에서 멈춘다(`<signal>.ready`를 만든다). `resume_after_s`가 있으면 그만큼 뒤 이어
      간다(`<signal>.resumed`, 없으면 프로세스가 끝날 때까지)
    - `fail_write`: N — N번째 `write`가 `OSError`
    - `unavailable`: 이유 — `probe`가 그 이유로 실패
    - `probe_delay_s`: 초 — `probe`가 그만큼 걸린다 (차가운 Media Foundation 첫 열기 흉내)
    """

    stuck: Mapping[str, Any] | None = None
    fail_write: int | None = None
    unavailable: VideoReason | None = None
    probe_delay_s: float = 0.0
    _counts: dict[str, int] = field(default_factory=dict[str, int])
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> FakeEncoderFactory:
        return cls(
            stuck=data.get("stuck"),
            fail_write=data.get("fail_write"),
            unavailable=data.get("unavailable"),
            probe_delay_s=float(data.get("probe_delay_s", 0.0)),
        )

    def probe(self, folder: Path) -> None:
        if self.probe_delay_s:
            time.sleep(self.probe_delay_s)
        if self.unavailable is not None:
            raise EncoderUnavailable(self.unavailable, "검사 주입")

    def open(self, path: Path, size: tuple[int, int]) -> Encoder:
        return _FakeEncoder(self, path, size)

    def on(self, op: str) -> None:
        with self._lock:
            count = self._counts[op] = self._counts.get(op, 0) + 1
        if op == "write" and self.fail_write is not None and count == self.fail_write:
            raise OSError("가짜 인코더 쓰기 실패 (검사 주입)")
        stuck = self.stuck
        if stuck is None or stuck.get("op") != op or count != int(stuck.get("nth", 1)):
            return
        signal = stuck.get("signal")
        if signal:
            with contextlib.suppress(OSError):
                Path(f"{signal}.ready").write_text("stuck", encoding="utf-8")
        resume: Any = stuck.get("resume_after_s")
        if resume is None:
            while True:  # 프로세스가 끝날 때까지
                threading.Event().wait()
        time.sleep(float(resume))
        if signal:
            with contextlib.suppress(OSError):
                Path(f"{signal}.resumed").write_text("resumed", encoding="utf-8")


def _test_config(env: Mapping[str, str] | None) -> dict[str, Any]:
    raw = (env if env is not None else os.environ).get(TEST_ENV)
    if raw:
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            return cast(dict[str, Any], loaded)
    return {}


def finish_wait_from_env(env: Mapping[str, str] | None = None) -> float | None:
    """숨은 검사 설정의 영상 마무리 단계 상한(`finish_wait_s`, 초). 없으면 None (제품 상한)."""
    try:
        value = _test_config(env).get("finish_wait_s")
    except ValueError:
        return None
    return float(value) if isinstance(value, (int, float)) and value > 0 else None


def encoder_factory_from_env(
    env: Mapping[str, str] | None = None,
) -> tuple[EncoderFactory | None, EncoderUnavailable | None]:
    """runner의 인코더: 기본은 Media Foundation(`kookabug_platform.video.MsmfFactory`). 숨은 검사
    설정 `KOOKABUG_VIDEO_TEST`가 있으면 그것을 따른다. 플랫폼 패키지를 불러올 수 없으면
    `backend_missing`이다(그때 실행은 영상 없이 돈다)."""
    config = _test_config(env)
    if config.get("encoder") == "fake":
        return FakeEncoderFactory.from_json(config.get("fake", {})), None
    try:
        from kookabug_platform.video import MsmfFactory
    except ImportError as exc:
        return None, EncoderUnavailable("backend_missing", f"영상 모듈을 불러올 수 없다: {exc}")
    return MsmfFactory.from_json(config.get("msmf", {})), None


class EncoderProbe:
    """인코더 열기 시험을 따로 도는 스레드에서 한다 (runner 시작 직후 — 스냅샷·워커 시작과 겹쳐
    첫 장면을 놓치지 않게). 시험 파일은 OS 임시 폴더에 둔다: 시험이 멈춰도 `video/`를 쥐지 않는다
    (영상 파일의 작성자는 녹화 스레드 하나)."""

    def __init__(
        self, factory: EncoderFactory | None, unavailable: EncoderUnavailable | None = None
    ) -> None:
        self.factory = factory
        self.error = unavailable
        self.done = threading.Event()
        if unavailable is not None or factory is None:
            if self.error is None:
                self.error = EncoderUnavailable("backend_missing", "인코더가 없다")
            self.done.set()
            return
        threading.Thread(target=self._run, name="kookabug-video-probe", daemon=True).start()

    def _run(self) -> None:
        assert self.factory is not None
        try:
            with tempfile.TemporaryDirectory(prefix="kookabug-video-probe-") as folder:
                self.factory.probe(Path(folder))
        except EncoderUnavailable as exc:
            self.error = exc
        except Exception as exc:
            self.error = EncoderUnavailable("encoder_open_failed", f"{type(exc).__name__}: {exc}")
        finally:
            self.done.set()


# ---------------------------------------------------------------- 게이트


type GateState = Literal["record", "pending", "off"]


@dataclass(frozen=True, slots=True)
class GateView:
    """게이트 한 순간. `generation`은 바뀔 때마다(스텝마다 보류에 들어갈 때 포함) 오른다.
    `blocks`는 차단(구간 끄기·비밀값·멈춤)에 들어간 횟수다. `since_mono`·`since_wall`은 지금 상태가
    시작된 시각."""

    generation: int
    blocks: int
    state: GateState
    mode: SegmentMode | None
    gap: GapReason | None
    step: str | None
    window: WindowRef | None
    since_mono: float
    since_wall: float


@dataclass(slots=True)
class OffSpan:
    """게이트가 off였던 구간 하나 (끝나지 않았으면 `end_*`가 None)."""

    gap: GapReason
    step: str | None
    start_mono: float
    start_wall: float
    end_mono: float | None = None
    end_wall: float | None = None
    serial: int = field(default_factory=lambda: next(_SPAN_SERIAL))


_SPAN_SERIAL = itertools.count()


@dataclass(slots=True)
class _Open:
    step: str
    pending: bool = True
    mode: VideoMode = "on"
    secret: bool = False


class VideoGate:
    """녹화 게이트. 실행기(주 스레드)가 바꾸고 녹화 스레드가 읽는다 (잠금 하나)."""

    def __init__(
        self,
        *,
        mono: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
    ) -> None:
        self.mono = mono
        self.wall = wall
        self._cond = threading.Condition()
        self._stack: list[_Open] = []
        self._base: VideoMode = "on"
        self._paused: str | None = None
        self._paused_on = False
        self._closed = False
        self._keep_spans = True
        self._window: WindowRef | None = None
        self._gen = 0
        self._blocks = 0
        self._now: tuple[GateState, SegmentMode | None, GapReason | None, str | None] = (
            "off",
            None,
            "no_window",
            None,
        )
        self._since = (mono(), wall())
        self._span: OffSpan | None = OffSpan("no_window", None, *self._since)
        self._spans: list[OffSpan] = [self._span]

    # ------------------------------------------------------------ 실행기 쪽

    def set_base(self, mode: VideoMode) -> None:
        """열린 스텝이 없을 때 값 (워크스페이스·테스트 층)."""
        with self._cond:
            self._base = mode
            self._update()

    def hold(self, step: str) -> None:
        """`step.start` 전: 보류 차단. 게이트 세대를 올린다(가져오는 중이던 프레임은 버려진다)."""
        with self._cond:
            self._stack.append(_Open(step))
            self._gen += 1
            self._update()

    def classify(
        self, step: str, mode: VideoMode, *, secret: bool, window: WindowRef | None
    ) -> None:
        """입력 계산·비밀값 분류가 끝났다: 그 스텝의 영상 정책과 대상 창으로 정한다."""
        with self._cond:
            for entry in self._stack:
                if entry.step == step:
                    entry.pending = False
                    entry.mode = mode
                    entry.secret = secret
            self._window = window
            self._update()

    def restrict(self, step: str, mode: VideoMode) -> None:
        """호출 스텝: 서브그래프의 `record`까지 더한 정책이 더 세면 그 호출 스텝 구간 전체에 쓴다
        (자식 스텝 사이에도 다시 켜지지 않게)."""
        with self._cond:
            for entry in self._stack:
                if entry.step == step and _STRENGTH[mode] > _STRENGTH[entry.mode]:
                    entry.mode = mode
            self._update()

    def release(self, step: str) -> None:
        """스텝이 스택에서 빠졌다 (`step.end` 뒤, 또는 예외·취소로 닫힘)."""
        with self._cond:
            self._stack = [e for e in self._stack if e.step != step]
            self._update()

    def set_paused(self, paused: bool, step: str | None = None) -> None:
        """디버거 멈춤 (멈춘 동안 녹화하지 않는다, 사용자 결정 U7)."""
        with self._cond:
            self._paused_on = paused
            self._paused = step if paused else None
            self._update()

    # ------------------------------------------------------------ 녹화 스레드 쪽

    def view(self) -> GateView:
        with self._cond:
            state, mode, gap, step = self._now
            return GateView(
                self._gen,
                self._blocks,
                state,
                mode,
                gap,
                step,
                self._window,
                self._since[0],
                self._since[1],
            )

    def wait_change(self, generation: int, timeout_s: float) -> None:
        """게이트 세대가 `generation`에서 바뀌거나 `timeout_s`가 지날 때까지."""
        with self._cond:
            if self._gen == generation and timeout_s > 0:
                self._cond.wait(timeout_s)

    def wake(self) -> None:
        with self._cond:
            self._gen += 1
            self._cond.notify_all()

    def close(self) -> None:
        """실행기가 끝났다: 판정 뒤 녹화 멈춤까지 기본 정책으로 다시 켜지지 않게 닫는다 (빈 구간
        없이 off — 그 뒤로는 영상이 없다)."""
        with self._cond:
            self._closed = True
            self._update()

    def stop_spans(self) -> None:
        """녹화 스레드가 더 쓰지 않는다(사용 불가·쓰기 실패): off 구간을 쌓지 않는다."""
        with self._cond:
            self._keep_spans = False
            self._spans = []

    def drain(self) -> list[OffSpan]:
        """지난번 뒤로 생긴 off 구간들 (끝난 것과 지금 열린 것). 녹화 스레드가 확인 사이에 놓친 짧은
        차단도 조각 닫기·빈 구간으로 남기기 위해서다."""
        with self._cond:
            out = [replace(span) for span in self._spans]
            self._spans = [span for span in self._spans if span.end_mono is None]
            return out

    def fill_limit(self, at: float) -> float:
        """반복 칸을 `at`(단조)까지 채워도 되는 한계. 지금 보류 중이면 보류 시작(분류 결과 off면 빈
        구간이 거기서 시작한다), 아직 비우지 않았거나 열린 off 구간이 있으면 그 시작을 넘지 않는다.
        채우기 직전에 읽으므로 한 번 받은 구간 목록 뒤에 확정된 차단도 반복 칸이 덮지 않는다
        (vreview_2 Mid). 이 값을 읽은 뒤 생기는 구간은 읽은 시각 뒤에서 시작한다."""
        with self._cond:
            limit = at
            if self._now[0] == "pending":
                limit = min(limit, self._since[0])
            for span in self._spans:
                limit = min(limit, span.start_mono)
            return limit

    # ------------------------------------------------------------ 계산 (잠금 안)

    def _compute(self) -> tuple[GateState, SegmentMode | None, GapReason | None, str | None]:
        if self._closed:
            return "off", None, None, None
        if self._paused_on:
            return "off", None, "paused", self._paused
        for entry in self._stack:
            if not entry.pending and entry.secret:
                return "off", None, "secret_input", entry.step
        if self._base == "off":
            return "off", None, "policy_off", None
        for entry in self._stack:
            if not entry.pending and entry.mode == "off":
                return "off", None, "policy_off", entry.step
        if any(entry.pending for entry in self._stack):
            return "pending", None, None, None
        if self._window is None:
            return "off", None, "no_window", None
        strongest = max((self._base, *(e.mode for e in self._stack)), key=lambda m: _STRENGTH[m])
        return "record", cast(SegmentMode, strongest), None, None

    def _update(self) -> None:
        value = self._compute()
        if value == self._now:
            return
        state, _, gap, step = value
        old_state, _, old_gap, old_step = self._now
        blocking = state == "off" and gap in (None, "paused", "secret_input", "policy_off")
        if blocking and (old_state != "off" or old_gap != gap):
            self._blocks += 1
        now = (self.mono(), self.wall())
        if state != "off" or (old_state == "off" and (old_gap, old_step) != (gap, step)):
            self._end_span(now)
        if state == "off" and self._span is None and gap is not None:
            # 보류에서 바로 off가 되면 빈 구간은 보류가 시작된 때(그 스텝의 step.start 직전)부터
            start = self._since if old_state == "pending" else now
            self._span = OffSpan(gap, step, start[0], start[1])
            if self._keep_spans:
                self._spans.append(self._span)
        self._now = value
        self._gen += 1
        self._since = now
        self._cond.notify_all()

    def _end_span(self, now: tuple[float, float]) -> None:
        if self._span is not None:
            self._span.end_mono, self._span.end_wall = now
            self._span = None
        self._cond.notify_all()


# ---------------------------------------------------------------- 조각


class _WriteFailed(Exception):
    """조각 쓰기가 실패했다 (영상만 멈춘다)."""

    def __init__(self, reason: VideoReason, detail: str) -> None:
        super().__init__(detail)
        self.reason: VideoReason = reason


class _Segment:
    """쓰는 중인 조각 하나 (녹화 스레드만 쓴다). 칸 `k`는 `[t0 + k·200ms, t0 + (k+1)·200ms)`이고 그
    칸이 끝날 때 그 사이 받은 가장 새 프레임(없으면 직전 프레임 반복)을 쓴다."""

    def __init__(
        self,
        rec: VideoRecorder,
        index: int,
        mode: SegmentMode,
        window: str,
        size: tuple[int, int],
        t0: float,
        first: VideoFrame | None,
        last: VideoFrame | None = None,
    ) -> None:
        self.rec = rec
        self.index = index
        self.mode: SegmentMode = mode
        self.window = window
        self.size = size
        self.t0 = t0
        self.t0_wall = rec.wall_of(t0)
        self.part = rec.dir / f"seg-{index:04d}.part.mp4"
        self.final = rec.dir / f"seg-{index:04d}.mp4"
        self.slots = 0
        self.candidate = first
        self.last = last
        self.missed = 0
        try:
            self.encoder = rec.factory.open(self.part, size)
        except EncoderUnavailable as exc:
            raise _WriteFailed(exc.reason, str(exc)) from exc
        except Exception as exc:
            raise _WriteFailed("encoder_open_failed", f"{type(exc).__name__}: {exc}") from exc
        self._frames = (rec.dir / f"seg-{index:04d}.frames.jsonl").open(
            "a", encoding="utf-8", newline="\n"
        )

    def key(self) -> tuple[SegmentMode, str, tuple[int, int]]:
        return self.mode, self.window, self.size

    def slot_of(self, now: float) -> int:
        return int((now - self.t0) * 1000 // FRAME_MS)

    def boundary(self, slot: int) -> float:
        return self.t0 + slot * FRAME_MS / 1000

    @property
    def full(self) -> bool:
        return self.slots >= SEGMENT_SLOTS

    def offer(self, frame: VideoFrame, now: float, *, pending: bool = False) -> None:
        self.fill(now, pending=pending)
        if not self.full:
            self.candidate = frame
            self.missed = 0

    def fill(self, now: float, *, pending: bool = False) -> None:
        """끝난 칸을 모두 쓴다 (`pending`이면 그 반복은 `capture_missed` 셈에 넣지 않는다). 채우기
        직전의 최신 차단 이력으로 자른다 (`VideoGate.fill_limit`)."""
        limit = self.rec.gate.fill_limit(now)
        while not self.full and self.boundary(self.slots + 1) <= limit:
            self._emit(pending=pending)

    def _emit(self, *, pending: bool) -> None:
        if self.candidate is not None:
            frame, repeat = self.candidate, False
            self.candidate = None
        else:
            if self.last is None:
                return
            frame, repeat = self.last, True
            if not pending:
                self.missed += 1
        try:
            self.encoder.write(frame)
            line = {"pixels_at": stamp(frame.at), "repeat": repeat, "slot": self.slots}
            self._frames.write(json.dumps(line) + "\n")
            self._frames.flush()
        except Exception as exc:
            raise _WriteFailed("write_failed", f"{type(exc).__name__}: {exc}") from exc
        self.slots += 1
        self.last = frame

    def close(self, at: float) -> dict[str, Any] | None:
        """`at`까지 끝난 칸을 쓰고 닫는다. 끝나지 않은 칸은 버린다 — 조각 끝(`t_end`)이 `at`을 넘지
        않아 뒤 빈 구간·조각과 겹치지 않는다. 조각 줄을 돌려준다 (칸이 하나도 없으면 None)."""
        self.fill(at)
        try:
            self._frames.close()
            self.encoder.release()
        except Exception as exc:
            raise _WriteFailed("write_failed", f"{type(exc).__name__}: {exc}") from exc
        if self.slots == 0:
            with contextlib.suppress(OSError):
                self.part.unlink()
            with contextlib.suppress(OSError):
                (self.rec.dir / f"seg-{self.index:04d}.frames.jsonl").unlink()
            return None
        try:
            os.replace(self.part, self.final)
            size = self.final.stat().st_size
        except OSError as exc:
            raise _WriteFailed("write_failed", f"{type(exc).__name__}: {exc}") from exc
        return {
            "bytes": size,
            "file": self.final.name,
            "frame_ms": FRAME_MS,
            "frames": self.slots,
            "mode": self.mode,
            "size": list(self.size),
            "t0": stamp(self.t0_wall),
            "t_end": stamp(self.t0_wall + self.slots * FRAME_MS / 1000),
            "window": self.window,
        }

    def abort(self) -> None:
        """쓰기 실패 뒤: 인코더만 놓는다 (`.part.mp4`는 마무리가 지운다)."""
        with contextlib.suppress(Exception):
            self._frames.close()
        with contextlib.suppress(Exception):
            self.encoder.release()


# ---------------------------------------------------------------- 녹화 스레드


class VideoRecorder:
    """한 실행의 녹화 스레드. `start()` → (실행) → `stop()`(유예 안에 끝났으면 True).

    `stop()`이 False면 작성자가 아직 살아 있다: 부르는 쪽은 `video/` 파일을 건드리지 않는다."""

    def __init__(
        self,
        run_dir: Path,
        gate: VideoGate,
        source: VideoSource,
        factory: EncoderFactory | None,
        *,
        unavailable: EncoderUnavailable | None = None,
        probe: EncoderProbe | None = None,
        capture_timeout_ms: int = 2000,
        late_wait_s: float | None = PREROLL_STOP_WAIT_S,
    ) -> None:
        """`probe`를 주면 그 시험 결과를 기다리고(runner: 시작 직후 띄운 것), 없으면 시작할 때
        시험을 띄운다. `late_wait_s`는 늦은 인코더 대기를 스스로 포기하는 시간(멈춤 요청부터)이고,
        None이면 `abandon_encoder_wait()`가 올 때까지 기다린다 (runner가 정한다)."""
        self.dir = Path(run_dir) / VIDEO_DIR
        self.gate = gate
        self.source = source
        self.factory = cast(EncoderFactory, factory)
        self._probe_given = probe
        self._unavailable = unavailable
        self.capture_timeout_ms = capture_timeout_ms
        self.status: VideoStatus = "none"
        self.reason: VideoReason | None = None
        self._stop = threading.Event()
        self._seg: _Segment | None = None
        self._next_index = 1
        self._gap: dict[str, Any] | None = None
        self._span_serial = -1
        """빈 구간으로 연 게이트 off 구간의 번호."""
        self._backlog: dict[int, OffSpan] = {}
        """게이트에서 비웠지만 아직 반영하지 않은 off 구간 (모은 프레임보다 뒤에 시작한 것)."""
        self._last_span: OffSpan | None = None
        """마지막으로 반영한 off 구간 (모은 프레임이 그 안이면 쓰지 않는다)."""
        self._not_before = 0.0
        """인코더 시험이 끝난 시각 (단조). 그 전 off 구간은 `starting` 빈 구간에 든다."""
        self._late_wait_s = late_wait_s
        self._give_up = threading.Event()
        self._late = False
        self._late_marker: dict[str, Any] = {}
        self._late_modes: frozenset[SegmentMode] = frozenset()
        self._miss_since: float | None = None
        self.grab_error: str | None = None
        """녹화 프레임을 가져오지 못한 첫 이유 (진단용, stderr에 한 번 남긴다)."""
        self._offset = gate.wall() - gate.mono()
        self._exit_lock = threading.Lock()
        self._exited = False
        self._exit_listeners: list[threading.Event] = []
        self._thread = threading.Thread(target=self._run, name="kookabug-video", daemon=True)

    def wall_of(self, mono: float) -> float:
        return mono + self._offset

    # ------------------------------------------------------------ 수명

    def start(self) -> VideoRecorder:
        self._thread.start()
        return self

    def request_stop(self) -> None:
        self._stop.set()
        self.gate.wake()

    def join(self, timeout_s: float) -> bool:
        """녹화 스레드가 끝났으면 True."""
        self._thread.join(max(0.0, timeout_s))
        return not self._thread.is_alive()

    def stop(self, grace_s: float = STOP_GRACE_S) -> bool:
        self.request_stop()
        return self.join(grace_s)

    @property
    def exited(self) -> bool:
        """녹화 스레드 본체가 끝났다 (영상 파일을 더 쓰지 않는다. 스레드 객체는 곧 끝난다)."""
        with self._exit_lock:
            return self._exited

    def notify_on_exit(self, event: threading.Event) -> None:
        """녹화 스레드 본체가 끝나면 `event`를 세운다 (이미 끝났으면 바로). 늦은 인코더 대기에
        들어갈 때도 세운다. 마무리가 다른 신호(종료 기한 갱신)와 한 Event로 함께 기다릴 때 쓴다."""
        with self._exit_lock:
            if not self._exited:
                self._exit_listeners.append(event)
                return
        event.set()

    @property
    def awaiting_encoder(self) -> bool:
        """늦은 인코더 대기 중이다: 멈춤 요청을 받았는데 시험이 아직이라 모은 프레임을 들고
        기다리거나, 그 뒤 시험이 끝나 모은 프레임을 쓰는 중 (스레드가 끝나면 False). runner는 이때
        run.end 뒤 영상 마무리 단계를 연다."""
        with self._exit_lock:
            return self._late and not self._exited

    @property
    def late_modes(self) -> frozenset[SegmentMode]:
        """늦은 인코더 대기에서 들고 있는 프레임의 모드 (`on`이 있으면 판정과 상관없이 남는다)."""
        with self._exit_lock:
            return self._late_modes

    def abandon_encoder_wait(self) -> None:
        """늦은 인코더 대기를 포기시킨다: 모은 프레임을 버리고 `starting`/`encoder_not_ready` 빈
        구간을 남긴 뒤 끝난다 (이미 시험이 끝나 쓰는 중이면 영향 없음)."""
        self._give_up.set()

    def _run(self) -> None:
        try:
            self._main()
        finally:
            with self._exit_lock:
                self._exited = True
                listeners, self._exit_listeners = self._exit_listeners, []
            for event in listeners:
                event.set()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    # ------------------------------------------------------------ 본체

    def _main(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            # 작성자 표시: 살아 있는 동안 삭제 공유 없이 열어 둔다 (마무리가 작성자 생존을 본다)
            writer = (self.dir / WRITER_FILE).open("w", encoding="utf-8")
        except OSError:
            self.status, self.reason = "failed", "write_failed"
            return
        with writer:
            self._body()

    def _body(self) -> None:
        started = self.gate.wall()
        probe = self._probe_given or EncoderProbe(self.factory, self._unavailable)
        preroll = self._preroll(probe, started)
        if not probe.done.is_set():
            # 실행이 끝났는데 시험이 끝나지 않았다: 그 구간을 남기고 끝낸다 (시험 스레드는 video/
            # 밖). 모은 프레임이 있었으면 쓸 인코더가 없어 버린 것이므로 이유를 붙인다
            recorded = self._starting(started, end=self._closed_wall(), not_ready=bool(preroll))
            self._settle_late(recorded)
            return
        if probe.error is not None:
            # 기록하지 못하면 표식은 준비 대기(`waiting`)로 남는다 — 인코더가 준비되지 않았다
            self.gate.stop_spans()
            self._settle_late(self._dead("unavailable", probe.error.reason, started))
            return
        if self._late:
            # 준비는 끝났지만 모은 프레임을 쓰고 닫기 전이다: 결과가 확정될 때까지 표식을 둔다
            # (이 사이 쓰기가 멈추거나 끝나면 마무리가 encoder_stuck으로 남긴다, vreview_3)
            self._mark_late("writing")
        try:
            if not self._starting(started, preroll[0][2] if preroll else None):
                raise _WriteFailed("write_failed", "starting 빈 구간을 기록하지 못했다")
            if preroll:
                self._write_preroll(preroll)
            self._loop()
            self._apply_spans()
            now = self.gate.mono()
            self._end_segment(now)
            self._close_gap(self.wall_of(now))
            # 여기까지 온 쓰기는 모두 기록에 성공했다 (실패하면 `_WriteFailed`)
            self._settle_late(True)
        except _WriteFailed as exc:
            failed_at = self.gate.wall()
            if self._seg is not None:
                self._seg.abort()
                self._seg = None
            with contextlib.suppress(Exception):
                self._close_gap(failed_at)
            # 실패 결과도 기록하지 못했으면(디스크 공간 부족 등) 표식이 `writing`으로 남아 마무리가
            # encoder_stuck으로 포기를 드러낸다 (vreview_4)
            self._settle_late(self._dead("failed", exc.reason, failed_at))

    def _preroll(
        self, probe: EncoderProbe, started: float
    ) -> list[tuple[VideoFrame, GateView, float]]:
        """인코더 시험을 기다리는 동안에도 프레임을 메모리에 모은다 (M3 사람 확인 R1 F1).

        인코더 준비가 늦어도(첫 Media Foundation 초기화·PC 부하) 그동안의 화면을 시험이 끝난 뒤 그
        시각 그대로 조각에 쓴다 — `starting` 빈 구간은 프레임이 하나도 없던 구간으로 줄어든다.
        칸마다 한 장, 가장 오래된 것부터 버려 `PREROLL_BYTES` 안. 차단(구간 끄기·비밀값·멈춤)이나
        창 없음이 끼면 그 앞 프레임은 버린다(조각은 차단을 건너 잇지 않는다). 멈추라는 요청을 받으면
        더 모으지 않고, 모은 것이 있으면 늦은 인코더 대기로 시험을 더 기다린다 — 포기는
        `late_wait_s`(None이면 `abandon_encoder_wait`)가 정한다 (모은 것이 없으면 바로 끝낸다)."""
        gate = self.gate
        buf: deque[tuple[VideoFrame, GateView, float]] = deque()
        held = 0
        stop_at: float | None = None
        while not probe.done.is_set():
            if self._stop.is_set():
                if not buf:
                    break  # 모은 것이 없다: 시험을 더 기다릴 까닭이 없다
                if stop_at is None:
                    stop_at = time.monotonic()
                    self._enter_late(started, buf)
                limit = self._late_wait_s
                if self._give_up.is_set() or (
                    limit is not None and time.monotonic() - stop_at >= limit
                ):
                    break
                probe.done.wait(_WAIT_S)
                continue
            view = gate.view()
            closed = view.state == "off" and view.gap is None  # 실행기가 끝남: 모은 것은 둔다
            if buf and not closed and (view.state == "off" or view.blocks != buf[-1][1].blocks):
                buf.clear()
                held = 0
            # 기다림은 실시간 루프처럼 게이트가 바뀌면 바로 깬다 (짧은 스텝의 기록 구간도 놓치지
            # 않게). 시험 끝은 `_WAIT_S` 안에 본다
            if view.state != "record":
                gate.wait_change(view.generation, _WAIT_S)
                continue
            now = gate.mono()
            if buf and now - buf[-1][2] < FRAME_MS / 1000:
                gate.wait_change(
                    view.generation, min(_WAIT_S, FRAME_MS / 1000 - (now - buf[-1][2]))
                )
                continue
            frame = self._grab(view)
            after = gate.view()
            got = gate.mono()
            if frame is None or _changed(view, after):
                gate.wait_change(after.generation, _WAIT_S)
                continue
            if buf:
                last_frame, last_view, _ = buf[-1]
                if (last_view.mode, last_view.window, scaled_size(last_frame.size)) != (
                    after.mode,
                    after.window,
                    scaled_size(frame.size),
                ):
                    buf.clear()  # 모드·창·크기가 바뀌었다: 새 조각부터
                    held = 0
            buf.append((frame, after, got))
            held += _frame_bytes(frame)
            while held > PREROLL_BYTES and len(buf) > 1:
                held -= _frame_bytes(buf.popleft()[0])
        return list(buf)

    def _enter_late(self, started: float, buf: deque[tuple[VideoFrame, GateView, float]]) -> None:
        """늦은 인코더 대기에 들어간다: 표식을 먼저 남겨(대기 중 프로세스가 끝나도 마무리가 이유를
        안다) 기다리는 쪽(runner 마무리)을 깨운다."""
        self._late_marker = {
            "frames": len(buf),
            "t_end": stamp(self._closed_wall()),
            "t_start": stamp(started),
        }
        self._mark_late("waiting")
        modes: frozenset[SegmentMode] = frozenset(
            view.mode for _, view, _ in buf if view.mode is not None
        )
        with self._exit_lock:
            self._late = True
            self._late_modes = modes
            listeners = list(self._exit_listeners)
        for event in listeners:
            event.set()

    def _mark_late(self, phase: Literal["waiting", "writing"]) -> None:
        """늦은 인코더 대기 표식을 그 단계로 (같은 폴더 임시 파일 + replace, 최선 시도). `waiting`:
        시험을 기다린다, `writing`: 시험이 끝나 모은 프레임을 쓰고 닫는 중. 표식은 "대기에 들어갔고
        지금 단계가 무엇인가"만 알린다 — 결과가 정해졌는지는 저널(`settled` 줄)이 정한다."""
        path = self.dir / ENCODER_WAIT_FILE
        tmp = path.with_name(".encoder-wait.tmp")  # `.` 임시 파일은 마무리가 치운다
        with contextlib.suppress(OSError):
            text = json.dumps({**self._late_marker, "phase": phase}, sort_keys=True)
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, path)

    def _settle_late(self, recorded: bool) -> None:
        """늦은 대기를 정리하는 유일한 곳: 모은 프레임의 결과(조각·포기 빈 구간·`failed`·
        `unavailable`)를 저널에 **기록했으면**(`recorded`) 같은 저널에 완료 줄
        (`{"encoder_wait": "settled"}`)을 덧붙인다. 마무리는 이 줄이 있으면 표식을 무시하므로,
        표식 지우기는 그 뒤의 최선 시도이고 실패해도(Windows 공유 위반 등) 판정이 바뀌지 않는다
        (vreview_5). 결과나 완료 줄을 기록하지 못했으면 표식이 그 단계로 남아 마무리가 포기 이유를
        정한다 (vreview_4). 대기에 들어간 적이 없으면 할 일이 없다 (보통 경로에 쓰기를 더하지
        않는다)."""
        if not self._late or not recorded:
            return
        if not self._record({"encoder_wait": ENCODER_WAIT_SETTLED, "t": stamp(self.gate.wall())}):
            return
        with contextlib.suppress(OSError):
            (self.dir / ENCODER_WAIT_FILE).unlink(missing_ok=True)

    def _closed_wall(self) -> float:
        """실행기가 게이트를 닫은 벽시계 시각 (아직 열려 있으면 지금)."""
        view = self.gate.view()
        if view.state == "off" and view.gap is None:
            return view.since_wall
        return self.gate.wall()

    def _write_preroll(self, preroll: list[tuple[VideoFrame, GateView, float]]) -> None:
        """모은 프레임을 그 시각 그대로 조각에 쓴다. 프레임마다 그 직전의 최신 차단 이력을 받아
        (실시간 루프와 같은 `_apply_spans`) 그 프레임 전에 시작한 off 구간을 먼저 반영하고, 프레임이
        반영한 구간 안이면 쓰지 않는다 — 조각은 off 구간 시작에서 닫혀 빈 구간으로 남는다. 끝으로
        게이트를 다시 읽어 남은 구간을 모두 반영하고, 실행기가 끝났으면 닫힌 시각에서 조각을
        닫는다(`_sync_gate`). 반복 칸은 채울 때마다 그때의 이력으로 잘린다(`fill_limit`). 인코더
        열기처럼 오래 걸리는 일 사이에 확정된 차단도 그래서 덮지 않는다 (vreview_1·2 Mid)."""
        for frame, view, got in preroll:
            self._apply_spans(until=got)
            if self._blocked(got):
                continue
            self._take(frame, view, got)  # 모은 시각 그대로 격자에 넣는다
        self._sync_gate()

    def _starting(
        self,
        started: float,
        until: float | None = None,
        *,
        end: float | None = None,
        not_ready: bool = False,
    ) -> bool:
        """인코더 열기 시험을 기다린 구간 (칸 하나보다 길면 `starting` 빈 구간). 시험 중 모은 첫
        프레임 시각(`until`, 단조)이 있으면 거기까지, `end`(벽시계)를 주면 거기까지다. 그 전에
        시작한 게이트 off 구간은 이 구간 뒤로 잘라 겹치지 않게 한다. `not_ready`면 모은 프레임을
        인코더가 없어 버렸다는 이유(`encoder_not_ready`)를 붙이고 길이와 상관없이 남긴다.
        기록했거나 남길 것이 없으면 True, 기록하지 못했으면 False."""
        mono, wall = self.gate.mono(), self.gate.wall()
        if until is not None:
            mono, wall = until, self.wall_of(until)
        elif end is not None:
            wall = end
        self._not_before = mono
        if not_ready or wall - started >= FRAME_MS / 1000:
            line = {
                "gap": "starting",
                "t_end": stamp(max(started, wall)),
                "t_start": stamp(started),
            }
            if not_ready:
                line["reason"] = "encoder_not_ready"
            return self._record(line)
        return True

    def _record(self, line: Mapping[str, Any]) -> bool:
        """결과 줄 하나를 저널에 덧붙이고 성공 여부를 준다 (실패를 삼키는 쪽이 표식을 지우지 않게
        결과를 돌려준다 — `_settle_late`)."""
        try:
            self._append(line)
        except Exception:
            return False
        return True

    def _dead(self, status: VideoStatus, reason: VideoReason, since: float) -> bool:
        """영상을 더 쓰지 않는다: 멈출 때까지 기다렸다가 그 구간을 빈 구간으로 남긴다. 그 줄을
        기록했으면 True (상태는 메모리에도 남지만 마무리는 저널만 본다)."""
        self.gate.stop_spans()  # 비우는 쪽이 없으니 off 구간을 쌓지 않는다
        self.status = status
        self.reason = reason
        self._stop.wait()
        gap = "unavailable" if status == "unavailable" else "failed"
        line = {"gap": gap, "reason": reason, "t_start": stamp(since)}
        line["t_end"] = stamp(max(since, self.gate.wall()))
        return self._record(line)

    def _loop(self) -> None:
        gate = self.gate
        pending = False
        while not self._stop.is_set():
            view = self._sync_gate()
            now = gate.mono()
            if view.state == "off":
                pending = False
                self._miss_since = None
                gate.wait_change(view.generation, _WAIT_S)
                continue
            if view.state == "pending":
                # 보류: 새 프레임을 가져오지 않고 칸도 아직 쓰지 않는다. 분류 결과 off면 조각은 보류
                # 시작에서 닫히고(빈 구간이 step.start부터), 기록이면 보류 칸을 보류 전 프레임
                # 반복으로 채운다 (조각을 자르지 않는다)
                pending = True
                gate.wait_change(view.generation, _WAIT_S)
                continue
            if pending and self._seg is not None:
                self._seg.fill(view.since_mono, pending=True)
                self._rotate()
            pending = False
            seg = self._seg
            if seg is not None:
                seg.fill(now)
                self._rotate()
                seg = self._seg
                if seg is not None and seg.missed > MISSED_SLOTS:
                    # 캡처가 2초 넘게 계속 실패: 조각을 닫고 빈 구간
                    self._end_segment(now)
                    self._open_gap("capture_missed", None, self.wall_of(now))
                    seg = None
                if seg is not None and seg.candidate is not None and seg.slot_of(now) == seg.slots:
                    # 이번 칸 프레임은 받았다: 다음 칸 시작까지
                    gate.wait_change(view.generation, max(0.0, seg.boundary(seg.slots + 1) - now))
                    continue
            frame = self._grab(view)
            after = gate.view()
            got = gate.mono()
            if frame is not None and _changed(view, after):
                frame = None  # 가져오는 동안 차단이 시작됐거나 창·모드가 바뀌었다
            if frame is None:
                self._missed(got, view)
                gate.wait_change(after.generation, FRAME_MS / 1000)
                continue
            self._take(frame, after, got)

    def _grab(self, view: GateView) -> VideoFrame | None:
        if view.window is None:
            return None
        try:
            return self.source.video_frame(view.window, self.capture_timeout_ms)
        except Exception as exc:
            if self.grab_error is None:
                self.grab_error = f"{type(exc).__name__}: {exc}"
                with contextlib.suppress(Exception):
                    print(f"녹화 프레임을 가져오지 못했다: {self.grab_error}", file=sys.stderr)
            return None

    def _missed(self, now: float, view: GateView) -> None:
        seg = self._seg
        if seg is not None:
            seg.fill(now)
            self._rotate()
            return
        # 조각이 없는 채로 캡처가 계속 실패: 2초가 넘으면 빈 구간으로 남긴다
        if self._miss_since is None:
            self._miss_since = now
        elif now - self._miss_since > MISSED_SLOTS * FRAME_MS / 1000:
            self._open_gap("capture_missed", None, self.wall_of(self._miss_since))

    def _take(self, frame: VideoFrame, view: GateView, now: float) -> None:
        assert view.mode is not None and view.window is not None
        key = (view.mode, window_key(view.window), scaled_size(frame.size))
        seg = self._seg
        if seg is not None and seg.key() != key:
            self._end_segment(now)
            seg = None
        self._miss_since = None
        if seg is None:
            if self._gap is not None and self._gap["gap"] == "capture_missed":
                self._close_gap(self.wall_of(now))  # off 구간의 빈 구간은 게이트 구간 끝에서 닫힌다
            self._seg = _Segment(self, self._next_index, key[0], key[1], key[2], now, frame)
            self._next_index += 1
            self.status = "recorded"
            return
        seg.offer(frame, now)
        self._rotate()

    def _rotate(self) -> None:
        """60초 찬 조각을 닫고 같은 격자로 이어지는 새 조각을 연다."""
        seg = self._seg
        if seg is None or not seg.full:
            return
        line = seg.close(seg.boundary(seg.slots))
        if line is not None:
            self._append(line)
        nxt = _Segment(
            self,
            self._next_index,
            seg.mode,
            seg.window,
            seg.size,
            seg.boundary(seg.slots),
            seg.candidate,
            seg.last,
        )
        self._next_index += 1
        self._seg = nxt

    def _end_segment(self, at: float) -> None:
        seg = self._seg
        if seg is None:
            return
        self._seg = None
        line = seg.close(max(at, seg.boundary(seg.slots)))
        if line is not None:
            self._append(line)

    # ------------------------------------------------------------ 빈 구간

    def _sync_gate(self) -> GateView:
        """게이트 상태를 읽고, 그 상태 전에 생긴 off 구간을 모두 반영한다(상태를 읽은 뒤에 비운다 —
        닫힌 게이트는 더 구간을 만들지 않으므로 이력이 완전하다). 실행기가 끝나 게이트가 닫혔으면
        닫힌 시각에서 조각을 닫는다. 실시간 루프와 모은 프레임 쓰기가 같이 쓰는 결정이다."""
        view = self.gate.view()
        self._apply_spans()
        if view.state == "off" and view.gap is None:
            self._end_segment(view.since_mono)
        return view

    def _blocked(self, at: float) -> bool:
        """`at`(단조)이 반영한 마지막 off 구간 안이다 (구간은 겹치지 않고 시작 순서로 반영한다)."""
        span = self._last_span
        return (
            span is not None
            and span.start_mono <= at
            and (span.end_mono is None or span.end_mono > at)
        )

    def _apply_spans(self, until: float | None = None) -> None:
        """게이트의 off 구간을 시작 순서대로: 그 시작에서 조각을 닫고 빈 구간으로 남긴다 (확인
        사이에 지나간 짧은 차단도). 부를 때마다 게이트에서 최신 이력을 비워 받는다. `until`(단조)을
        주면 그때까지 시작한 구간만 반영하고 나머지는 다음 부름까지 둔다(모은 프레임 쓰기). 열린
        구간은 다음 확인에서 다시 오므로 구간 번호로 한 번만 연다."""
        for fresh in self.gate.drain():
            self._backlog[fresh.serial] = fresh  # 같은 구간의 새 사본(그새 끝났을 수 있다)
        ready = sorted(
            (s for s in self._backlog.values() if until is None or s.start_mono <= until),
            key=lambda s: (s.start_mono, s.serial),
        )
        for span in ready:
            del self._backlog[span.serial]
            if span.end_mono is not None and span.end_mono <= self._not_before:
                continue  # 인코더 시험을 기다리던 구간 안에서 끝났다 (starting 빈 구간)
            if span.start_mono < self._not_before:
                span.start_mono = self._not_before
                span.start_wall = self.wall_of(self._not_before)
            self._last_span = span
            if span.serial != self._span_serial:
                self._end_segment(span.start_mono)
                self._miss_since = None
                self._close_gap(span.start_wall)
                self._gap = {"gap": span.gap, "t_start": span.start_wall}
                if span.step is not None:
                    self._gap["step"] = span.step
                self._span_serial = span.serial
            if span.end_wall is not None:
                self._close_gap(span.end_wall)

    def _open_gap(self, reason: GapReason, step: str | None, t_start: float) -> None:
        gap = self._gap
        if gap is not None and gap["gap"] == reason and gap.get("step") == step:
            return
        self._close_gap(t_start)
        self._gap = {"gap": reason, "t_start": t_start}
        if step is not None:
            self._gap["step"] = step

    def _close_gap(self, t_end: float) -> None:
        gap = self._gap
        if gap is None:
            return
        self._gap = None
        start = gap.pop("t_start")
        line = {**gap, "t_start": stamp(start), "t_end": stamp(max(start, t_end))}
        self._append(line)

    def _append(self, line: Mapping[str, Any]) -> None:
        """`segments.jsonl`에 한 줄 (녹화 스레드만 덧붙인다)."""
        text = json.dumps(dict(line), ensure_ascii=False, sort_keys=True) + "\n"
        try:
            with (self.dir / SEGMENTS_FILE).open("a", encoding="utf-8", newline="\n") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
        except OSError as exc:
            raise _WriteFailed("write_failed", f"{type(exc).__name__}: {exc}") from exc


def _frame_bytes(frame: VideoFrame) -> int:
    """모으기 상한에 셀 크기 (픽셀이 없는 검사 프레임도 한 장 = 1바이트 이상)."""
    return max(1, int(getattr(frame.pixels, "nbytes", 0) or 0))


def _changed(before: GateView, after: GateView) -> bool:
    """가져오는 동안 그 프레임을 쓸 수 없게 됐는가: 차단이 시작됐거나(끝났어도), 지금 기록할 수
    없거나, 창·모드가 바뀌었다. 보류가 분류 결과 기록 허용으로 풀린 것은 버릴 이유가 아니다."""
    return (
        after.blocks != before.blocks
        or after.state != "record"
        or after.mode != before.mode
        or after.window != before.window
    )
