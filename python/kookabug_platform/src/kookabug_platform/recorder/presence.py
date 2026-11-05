"""입력 칸이 그대로 있는가 (M4 계획 2.6 "칸이 그대로 있는가", 2차 N4, T6).
변환기 `FieldPresence` 구현.

칸 안 픽셀은 값·가림 글자·커서·포커스 테두리 때문에 칸이 그대로여도 바뀐다. 그래서 **칸 상자와 그
바깥 4 px까지를 빼고** 안정된 근거만 본다: 왼쪽(라벨 띠 + 왼쪽 둘레)·위·오른쪽·아래 둘레 네 조각
(둘레 = 상자 바깥 4~24 px). 조각마다 구간 시작 직전 프레임과 회색조 가장자리(Sobel) 상관이 0.8
이상이면 그대로다. 네 조각이 모두 그대로면 **있음**.

- **없음으로 확정** (보수적): 검증된 프레임 둘 이상이 150 ms 넘게 이어, 같은 프레임마다 (1) 네 근거
  조각이 **모두** 바뀌고 (2) 칸 자체 픽셀(테두리 안쪽)의 절반 넘게 바뀌고 (3) **장면 전환**(칸·둘레
  밖 구조 픽셀의 30% 넘게 바뀜)일 때만
- 그 밖(라벨·둘레 일부를 가린 팝업, 칸은 그대로 보임, 기하 불확실·검증 안 된 프레임, 상관이
  애매함)은 확정 못 함 → 있다고 본다: 보호 유지(세션 끝까지가 기본), 구간도 끝나지 않음
- 없음 확정은 구간을 끝낼 뿐 보호를 풀지 않는다. 보호는 **자를 프레임마다** `absent_in`으로 본다:
  그 프레임에서 위 (1)~(3)이 모두일 때만 칸이 없다(`ProtectionSet(absent_in=…)`). 칸이 다시 보이거나
  일부만 가려지면 그 프레임은 다시 보호한다

장면 전환은 "바뀐 픽셀 / 클라이언트"가 아니라 "바뀐 구조 픽셀 / 구조 픽셀"로 잰다 — 배경이 평평한
게임 화면은 장면이 통째로 바뀌어도 바뀐 픽셀 비율이 작다(예제 게임 로그인 → 로비 약 10%).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Final, Literal

import cv2
import numpy as np

from kookabug_core.recorder.fields import FieldSpan
from kookabug_core.recorder.protect import Box
from kookabug_platform.vision import Pixels

__all__ = [
    "ABSENT_MIN_FRAMES",
    "ABSENT_MIN_NS",
    "PRESENT_CORR",
    "SCENE_CHANGE",
    "Evidence",
    "FieldPresenceTracker",
    "evidence_parts",
    "evidence_state",
    "field_present",
    "interior_changed",
    "scene_changed",
]

INNER: Final = 4
"""칸 상자 바깥 이만큼은 포커스 테두리 자리라 뺀다."""
RING: Final = 24
PRESENT_CORR: Final = 0.8
SCENE_CHANGE: Final = 0.30
INTERIOR_CHANGE: Final = 0.5
ABSENT_MIN_FRAMES: Final = 2
ABSENT_MIN_NS: Final = 150_000_000
_DIFF: Final = 24


def _rect_mask(shape: tuple[int, int], box: Box, grow: int) -> np.ndarray:
    h, w = shape
    mask = np.zeros((h, w), dtype=bool)
    x, y, bw, bh = box
    x0, y0 = max(0, x - grow), max(0, y - grow)
    x1, y1 = min(w, x + bw + grow), min(h, y + bh + grow)
    mask[y0:y1, x0:x1] = True
    return mask


def evidence_mask(shape: tuple[int, int], box: Box) -> np.ndarray:
    """둘레 띠(상자 바깥 4~24 px) + 라벨 띠(왼쪽으로 상자 너비, 위로 상자 높이 1.5배)."""
    mask = np.zeros(shape, dtype=bool)
    for part in evidence_parts(shape, box):
        mask |= part
    return mask


def evidence_parts(shape: tuple[int, int], box: Box) -> list[np.ndarray]:
    """안정된 근거를 네 조각으로: 왼쪽(라벨 띠 + 왼쪽 둘레), 위·오른쪽·아래 둘레. 조각마다 따로 봐야
    팝업이 일부만 가린 것(남은 조각은 그대로)과 칸이 없어진 것(모든 조각이 바뀜)을 나눈다."""
    outer = _rect_mask(shape, box, RING)
    inner = _rect_mask(shape, box, INNER)
    ring = outer & ~inner
    x, y, w, h = box
    label = _rect_mask(shape, (x - w, y - round(h * 0.5), w, round(h * 1.5)), 0) & ~inner
    rows = np.arange(shape[0])[:, None]
    cols = np.arange(shape[1])[None, :]
    left = (label | (ring & (cols < x))) & (cols < x)
    right = ring & (cols >= x + w)
    top = ring & (rows < y) & (cols >= x) & (cols < x + w)
    bottom = ring & (rows >= y + h) & (cols >= x) & (cols < x + w)
    return [p for p in (left, top, right, bottom) if p.any()]


def _edges(image: Pixels) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    return np.asarray(cv2.magnitude(gx, gy), dtype=np.float32)


def _part_same(
    reference: Pixels, frame: Pixels, edges: tuple[np.ndarray, np.ndarray], mask: np.ndarray
) -> bool:
    a, b = edges[0][mask], edges[1][mask]
    if a.size == 0:
        return True
    if float(a.std()) < 1e-3 or float(b.std()) < 1e-3:
        # 평평한 둘레: 상관을 잴 수 없다 — 픽셀이 거의 같으면 그대로
        diff = np.abs(reference.astype(np.int16) - frame.astype(np.int16)).max(axis=2)[mask]
        return float((diff > _DIFF).mean()) < 0.05
    return float(np.corrcoef(a, b)[0, 1]) >= PRESENT_CORR


type Evidence = Literal["present", "partial", "absent"]


def evidence_state(reference: Pixels, frame: Pixels, box: Box) -> Evidence:
    """근거 조각이 모두 그대로면 `present`, 하나도 없으면 `absent`, 섞였으면 `partial`(일부 가림 —
    확정 못 함)."""
    if reference.shape != frame.shape:
        return "absent"
    edges = (_edges(reference), _edges(frame))
    same = [
        _part_same(reference, frame, edges, p) for p in evidence_parts(reference.shape[:2], box)
    ]
    if all(same):
        return "present"
    return "partial" if any(same) else "absent"


def field_present(reference: Pixels, frame: Pixels, box: Box) -> bool:
    """두 클라이언트 그림에서 칸의 안정된 근거(둘레·라벨 네 조각)가 모두 같은가."""
    return evidence_state(reference, frame, box) == "present"


def interior_changed(reference: Pixels, frame: Pixels, box: Box) -> bool:
    """칸 자체(테두리 3 px 안쪽) 픽셀의 절반 넘게 바뀌었는가. 칸이 그대로 보이면(값을 쳐도 글자 자리
    말고는 칸 바탕이 남는다) 없어진 것이 아니다."""
    if reference.shape != frame.shape:
        return True
    x, y, w, h = box
    a = reference[y + 3 : y + h - 3, x + 3 : x + w - 3].astype(np.int16)
    b = frame[y + 3 : y + h - 3, x + 3 : x + w - 3].astype(np.int16)
    if a.size == 0:
        return False
    return float((np.abs(a - b).max(axis=2) > _DIFF).mean()) > INTERIOR_CHANGE


def scene_changed(reference: Pixels, frame: Pixels, box: Box) -> bool:
    """칸·둘레 밖 클라이언트의 구조 픽셀 중 30% 넘게 바뀌었는가."""
    if reference.shape != frame.shape:
        return True
    outside = ~_rect_mask(reference.shape[:2], box, RING)
    structure = (_edges(reference) > 40) | (_edges(frame) > 40)
    structure = cv2.dilate(structure.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    structure &= outside
    total = int(structure.sum())
    if total == 0:
        return False
    diff = np.abs(reference.astype(np.int16) - frame.astype(np.int16)).max(axis=2) > _DIFF
    return float((diff & structure).sum()) / total > SCENE_CHANGE


@dataclass
class _Field:
    box: Box
    reference: Pixels
    since_ns: int
    absent: list[int] = field(default_factory=list[int])
    gone_at: int | None = None


def _absent(f: _Field, frame: Pixels | None) -> bool:
    """그 프레임에서 칸이 없다: 근거 조각이 모두 바뀌고, 칸 자체도 바뀌고, 장면이 바뀜. 크기가 다른
    프레임(창 크기·배율이 바뀜)은 비교할 수 없으니 판정 불가 = 없다고 하지 않는다."""
    return (
        frame is not None
        and frame.shape == f.reference.shape
        and evidence_state(f.reference, frame, f.box) == "absent"
        and interior_changed(f.reference, frame, f.box)
        and scene_changed(f.reference, frame, f.box)
    )


class FieldPresenceTracker:
    """구간마다 칸을 등록하고, 검증된 프레임이 올 때마다 `observe`. 변환기는 `gone`을 묻는다."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fields: dict[int, _Field] = {}

    def register(self, span_id: int, box: Box, reference: Pixels, t_ns: int) -> None:
        """구간 시작 직전 프레임(`reference`)의 칸 상자."""
        with self._lock:
            self._fields[span_id] = _Field(box, reference, t_ns)

    def observe(self, t_ns: int, frame: Pixels | None) -> list[int]:
        """프레임 하나. `frame`이 None이면 검증 안 된(기하 불확실) 프레임 — 확정을 끊는다.
        이번에 없음으로 확정된 구간 ID를 돌려준다 (구간 끝).
        보호는 풀지 않는다 — `absent_in`이 자를 프레임마다 본다."""
        newly: list[int] = []
        with self._lock:
            for span_id, f in self._fields.items():
                if f.gone_at is not None:
                    continue
                # 없음 후보가 아니면(일부 가림·칸은 그대로·애매·판정 불가) 확정 못 함 — 처음부터
                if t_ns <= f.since_ns or not _absent(f, frame):
                    f.absent.clear()
                    continue
                f.absent.append(t_ns)
                if (
                    len(f.absent) >= ABSENT_MIN_FRAMES
                    and f.absent[-1] - f.absent[0] > ABSENT_MIN_NS
                ):
                    f.gone_at = f.absent[0]
                    newly.append(span_id)
        return newly

    def absent_in(self, span_id: int, box: Box, frame: object) -> bool:
        """`ProtectionSet` 판정: 자를 이 프레임에서 그 칸이 없다는 근거가 확실한가 (네 근거 조각
        모두·칸 자체·장면이 바뀜). 등록 안 된 구간·상자가 다름·프레임이 그림이 아님은 False."""
        with self._lock:
            f = self._fields.get(span_id)
        if f is None or f.box != box or not isinstance(frame, np.ndarray):
            return False
        return _absent(f, np.asarray(frame, dtype=np.uint8))

    def gone_at(self, span_id: int) -> int | None:
        with self._lock:
            f = self._fields.get(span_id)
            return None if f is None else f.gone_at

    def gone(self, span: FieldSpan, t_ns: int) -> bool:
        """`FieldPresence`: 칸이 `t_ns` 전에 없음으로 확정됐는가."""
        at = self.gone_at(span.span_id)
        return at is not None and at <= t_ns
