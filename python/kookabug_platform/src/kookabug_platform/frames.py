"""프레임 저장소와 PNG 인코딩 (구현 계획 M1 2.7, 계획 검수 6, 계획 2차 검수 Mid 두 건).

캡처 픽셀은 runner 안 이 저장소에만 있고, 노드·워커는 픽셀 없는 참조 이미지(`capture_id`)를
받는다.

- **픽셀 공유**: 픽셀은 **동일성 키**(`StagedFrame.key` — WGC면 `(백엔드, frame_seq,
  클라이언트 자르기, 영역)`, `frame_seq`는 프로세스 안 유일) 단위로 한 번만 보관한다. 정지
  화면 재사용으로 같은 픽셀을 여러 `capture_id`가 가리켜도 바이트가 늘지 않는다. 다른 창·
  다시 만든 세션·다른 자르기는 키가 다르다 (`identity`로 비교한다 — `diff`의 0 단축은 키가
  같을 때만)
- **보관 등급**: 캡처 하나(`capture_id`)는 아래 중 하나라도 해당하면 남고, 하나도 없으면 바로
  버린다
  1. **작업 중**: 관측 호출이 쓰는 동안(`pinned`)
  2. **스텝 최근**: 열린 스텝마다 **마지막 두 캡처**. 마지막 것이 그 스텝의 증거(예외·실패
     스크린샷)이고, 그 앞 것은 연속 두 관측 비교용(`a = capture(); b = capture();
     diff(a, b)`)이다. 새 캡처가 오면 세 번째 전 것은 이 등급에서 빠진다. 스텝이 닫히면
     빠진다(`close_step`, 부모를 주면 마지막 것을 부모 증거로 넘긴다 — 부모의 지금 증거보다
     나중 것만)
  3. **출력 참조**: 스텝 출력으로 나간 캡처(`mark_output`). 최근 `output_refs`(32)개
- **바이트 예산**(`budget_bytes`, 512 MiB): 1·2등급은 예산과 무관하게 지킨다(열린 스텝 수의
  두 배). 넘으면 3등급을 오래된 것부터 버린다 — 1·2등급만으로 넘으면 출력 참조는 전부
  버려진다
- 버린(또는 모르는) 캡처를 쓰면 `frame_expired`

모든 메서드는 여러 스레드에서 불러도 된다(워커 RPC 스레드).
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

import cv2
import numpy as np

from kookabug_core.record.artifacts import CaptureMeta, StagedFrame
from kookabug_platform.errors import FRAME_EXPIRED, PlatformError

if TYPE_CHECKING:
    from numpy.typing import NDArray

__all__ = [
    "DEFAULT_BUDGET_BYTES",
    "DEFAULT_OUTPUT_REFS",
    "STEP_RECENT",
    "FrameStore",
    "decode_image",
    "encode_png",
]

MIB: Final = 1 << 20
DEFAULT_BUDGET_BYTES: Final = 512 * MIB
"""`run.frame_budget_mib` 기본값 (조율자 결정 Q15)."""
DEFAULT_OUTPUT_REFS: Final = 32
"""`run.frame_output_refs` 기본값."""
STEP_RECENT: Final = 2
"""열린 스텝마다 남기는 최근 캡처 수 (증거 1 + 연속 비교용 직전 1)."""

type Pixels = NDArray[np.uint8]


def decode_image(data: bytes) -> Pixels:
    """이미지 바이트(PNG 등) → BGR 픽셀 (읽기 전용). 한글 경로도 되게 바이트로 받는다."""
    pixels = None
    if data:  # 빈 버퍼는 imdecode가 None 대신 cv2.error를 던진다
        try:
            pixels = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        except cv2.error:
            pixels = None
    if pixels is None:
        raise ValueError("이미지를 읽을 수 없다 (형식이 깨졌거나 이미지가 아님)")
    result = np.asarray(pixels, dtype=np.uint8)
    result.setflags(write=False)
    return result


def encode_png(pixels: Pixels) -> bytes:
    ok, buffer = cv2.imencode(".png", pixels)
    if not ok:
        raise ValueError(f"PNG로 인코딩할 수 없다: {pixels.shape}")
    return buffer.tobytes()


@dataclass(eq=False, slots=True)
class _Entry:
    pixels: Pixels
    nbytes: int
    refs: set[int] = field(default_factory=set[int])


@dataclass(eq=False, slots=True)
class _Ref:
    key: Hashable
    meta: CaptureMeta | None = None
    working: int = 0
    recent: int = 0
    """이 캡처를 최근 목록에 둔 열린 스텝 수."""
    output: bool = False


class FrameStore:
    """한 실행의 캡처 픽셀. `kookabug_core.record.artifacts.FrameRegistry`를 구현한다."""

    def __init__(
        self,
        *,
        budget_bytes: int = DEFAULT_BUDGET_BYTES,
        output_refs: int = DEFAULT_OUTPUT_REFS,
    ) -> None:
        if budget_bytes <= 0 or output_refs < 0:
            raise ValueError(f"잘못된 저장소 한도: 예산 {budget_bytes}, 출력 참조 {output_refs}")
        self.budget_bytes = budget_bytes
        self.output_refs = output_refs
        self._lock = threading.Lock()
        self._entries: dict[Hashable, _Entry] = {}
        self._refs: dict[int, _Ref] = {}
        self._steps: dict[str, list[int]] = {}
        self._outputs: OrderedDict[int, None] = OrderedDict()
        self._expired: dict[int, str] = {}
        self.bytes_held = 0
        self.peak_bytes = 0

    # ------------------------------------------------------------ 등록·등급

    def register(self, capture_id: int, staged: StagedFrame, step: str) -> None:
        """캡처 하나를 그 스텝의 최근 캡처로 둔다. 같은 키의 픽셀이 있으면 그것을 같이 쓴다."""
        pixels = staged.pixels
        if (
            not isinstance(pixels, np.ndarray)
            or pixels.dtype != np.uint8
            or pixels.ndim
            not in (
                2,
                3,
            )
        ):
            raise TypeError(f"저장소 픽셀은 uint8 배열이다: {type(pixels).__name__}")
        with self._lock:
            if capture_id in self._refs or capture_id in self._expired:
                raise ValueError(f"캡처 {capture_id}는 이미 등록됐다")
            entry = self._entries.get(staged.key)
            if entry is None:
                if pixels.base is not None:
                    # 뷰는 더 큰 원본 할당을 붙잡는다 — 자기 메모리를 가진 복사본만 보관해
                    # 예산에 센 바이트가 실제로 붙잡은 바이트가 되게 한다
                    pixels = np.array(pixels, copy=True)
                    pixels.setflags(write=False)
                entry = _Entry(pixels, int(pixels.nbytes))
                self._entries[staged.key] = entry
                self.bytes_held += entry.nbytes
            entry.refs.add(capture_id)
            self._refs[capture_id] = _Ref(staged.key, staged.meta)
            self._push_recent(step, capture_id)
            self._enforce_budget()
            self.peak_bytes = max(self.peak_bytes, self.bytes_held)

    def _push_recent(self, step: str, capture_id: int) -> None:
        recent = self._steps.setdefault(step, [])
        recent.append(capture_id)
        self._refs[capture_id].recent += 1
        while len(recent) > STEP_RECENT:
            self._unrecent(recent.pop(0), "스텝의 최근 캡처에서 밀려남")

    def _unrecent(self, capture_id: int, reason: str) -> None:
        ref = self._refs.get(capture_id)
        if ref is not None:
            ref.recent -= 1
            self._maybe_drop(capture_id, reason)

    def mark_output(self, capture_id: int) -> None:
        """스텝 출력(이미지 핀·`Match`)으로 나간 캡처. 최근 `output_refs`개만 남는다."""
        with self._lock:
            ref = self._ref(capture_id)
            ref.output = True
            self._outputs[capture_id] = None
            self._outputs.move_to_end(capture_id)
            while len(self._outputs) > self.output_refs:
                self._drop_output(next(iter(self._outputs)), "출력 참조 수를 넘음")
            self._enforce_budget()

    def _drop_output(self, capture_id: int, reason: str) -> None:
        self._outputs.pop(capture_id, None)
        ref = self._refs.get(capture_id)
        if ref is not None:
            ref.output = False
            self._maybe_drop(capture_id, reason)

    def _enforce_budget(self) -> None:
        while self.bytes_held > self.budget_bytes and self._outputs:
            self._drop_output(next(iter(self._outputs)), "프레임 바이트 예산을 넘음")

    def close_step(self, step: str, *, parent: str | None = None) -> None:
        """스텝이 닫혔다. `parent`를 주면 마지막 캡처를 부모의 증거로 넘긴다(부모 것보다 나중일
        때만, 실패 증거 M1 2.15)."""
        with self._lock:
            recent = self._steps.pop(step, [])
            if parent is not None and recent:
                last = recent[-1]
                held = self._steps.get(parent, [])
                if last in self._refs and (not held or held[-1] < last):
                    self._push_recent(parent, last)
            for capture_id in recent:
                self._unrecent(capture_id, "스텝이 닫힘")

    def _maybe_drop(self, capture_id: int, reason: str) -> None:
        ref = self._refs[capture_id]
        if ref.working or ref.recent or ref.output:
            return
        del self._refs[capture_id]
        self._expired[capture_id] = reason
        entry = self._entries[ref.key]
        entry.refs.discard(capture_id)
        if not entry.refs:
            del self._entries[ref.key]
            self.bytes_held -= entry.nbytes

    def _ref(self, capture_id: int) -> _Ref:
        ref = self._refs.get(capture_id)
        if ref is None:
            reason = self._expired.get(capture_id)
            detail = "저장소가 모르는 캡처" if reason is None else f"이미 버림: {reason}"
            raise PlatformError(
                FRAME_EXPIRED, f"캡처 {capture_id}의 프레임을 쓸 수 없다 ({detail})"
            )
        return ref

    # ------------------------------------------------------------ 읽기

    @contextmanager
    def pinned(self, *capture_ids: int) -> Iterator[tuple[Pixels, ...]]:
        """관측 호출이 쓰는 동안 고정한다(작업 중 등급). 하나라도 버렸으면 `frame_expired`."""
        with self._lock:
            refs = [self._ref(capture_id) for capture_id in capture_ids]
            for ref in refs:
                ref.working += 1
            arrays = tuple(self._entries[ref.key].pixels for ref in refs)
        try:
            yield arrays
        finally:
            with self._lock:
                for capture_id, ref in zip(capture_ids, refs, strict=True):
                    ref.working -= 1
                    self._maybe_drop(capture_id, "관측 호출이 끝남")

    def identity(self, capture_id: int) -> Hashable:
        """픽셀 동일성 키. 두 캡처의 키가 같으면 같은 픽셀이다."""
        with self._lock:
            return self._ref(capture_id).key

    def meta(self, capture_id: int) -> CaptureMeta | None:
        """그 캡처의 관측 조건 (등록할 때 받은 것). 버렸으면 `frame_expired`."""
        with self._lock:
            return self._ref(capture_id).meta

    def encode_png(self, capture_id: int) -> bytes:
        with self.pinned(capture_id) as (pixels,):
            return encode_png(pixels)

    # ------------------------------------------------------------ 상태 (검사·진단)

    def evidence(self, step: str) -> int | None:
        """그 스텝의 증거 캡처(마지막으로 얻은 것)."""
        with self._lock:
            recent = self._steps.get(step)
            return recent[-1] if recent else None

    def held(self) -> set[int]:
        """지금 남아 있는 캡처들."""
        with self._lock:
            return set(self._refs)

    def is_expired(self, capture_id: int) -> bool:
        with self._lock:
            return capture_id not in self._refs
