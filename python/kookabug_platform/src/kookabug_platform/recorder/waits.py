"""대기 추론의 픽셀 쪽 (M4 계획 2.7 "대기 추론", 검수 M2, T6). 판단 규칙은
`kookabug_core.recorder.waits.decide_wait`.

`A` = 앞 동작 입력 직전 클라이언트 그림, `B` = 이 동작 입력 직전 그림. 바뀐 영역 `R` = A ↔ B 차이의
바깥 상자(전이 기록에서 잠깐 바뀌었다 돌아온 것은 B에 남지 않으므로 빠진다).

대기 target 자르기: R이 클라이언트 25% 이하면 R(+여백 4), 넘으면 R 안 가장자리 밀도가 가장 높은
`0.2h` 정사각. 보호 영역을 피하고(`ProtectionSet.avoid`), B에서 유일하고, **A에서는 찾아지지
않아야**(임계값 미만) 한다. 못 만들면 None → 보수적 지연 + `wait_target_unknown`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import cv2
import numpy as np

from kookabug_core.recorder.protect import Box, ProtectionSet
from kookabug_core.recorder.waits import NextKind, WaitDecision, WaitFacts, decide_wait
from kookabug_platform.recorder.crop import UNIQUE_SLACK, find_peaks, fit_inside
from kookabug_platform.vision import DEFAULT_THRESHOLD, Pixels

__all__ = ["WaitPlan", "changed_box", "changed_ratio", "infer_wait", "wait_crop"]

_DIFF: Final = 24
_PAD: Final = 4


def _changed(a: Pixels, b: Pixels) -> np.ndarray:
    return np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2) > _DIFF


def changed_ratio(a: Pixels, b: Pixels) -> float:
    if a.shape != b.shape:
        return 1.0
    return float(_changed(a, b).mean())


def changed_box(a: Pixels, b: Pixels) -> Box | None:
    if a.shape != b.shape:
        return (0, 0, int(b.shape[1]), int(b.shape[0]))
    ys, xs = np.nonzero(_changed(a, b))
    if xs.size == 0:
        return None
    x0, y0 = int(xs.min()), int(ys.min())
    return (x0, y0, int(xs.max()) - x0 + 1, int(ys.max()) - y0 + 1)


def _densest_square(b: Pixels, region: Box, side: int) -> Box:
    """R 안에서 가장자리 밀도가 가장 높은 `side` 정사각."""
    x, y, w, h = region
    side = max(8, min(side, w, h))
    gray = cv2.cvtColor(b[y : y + h, x : x + w], cv2.COLOR_BGR2GRAY)
    edges = (cv2.Canny(gray, 40, 120) > 0).astype(np.float32)
    integral = cv2.integral(edges)
    best, best_at = -1.0, (0, 0)
    step = max(1, side // 4)
    for yy in range(0, h - side + 1, step):
        for xx in range(0, w - side + 1, step):
            s = (
                integral[yy + side, xx + side]
                - integral[yy, xx + side]
                - integral[yy + side, xx]
                + integral[yy, xx]
            )
            if s > best:
                best, best_at = float(s), (xx, yy)
    return (x + best_at[0], y + best_at[1], side, side)


def wait_crop(
    a: Pixels,
    b: Pixels,
    region: Box,
    *,
    protect: ProtectionSet | None = None,
    t_ns: int | None = None,
    threshold: float = DEFAULT_THRESHOLD,
) -> Box | None:
    """R에서 기다릴 조각 (B에서 유일, A에 없음, 보호 영역 밖). 못 만들면 None."""
    height, width = int(b.shape[0]), int(b.shape[1])
    size = (width, height)
    x, y, w, h = region
    if w * h <= 0.25 * width * height:
        box = fit_inside((x - _PAD, y - _PAD, w + 2 * _PAD, h + 2 * _PAD), size)
    else:
        box = _densest_square(b, region, round(0.2 * height))
    if protect is not None:
        safe = protect.avoid(box, None, t_ns, frame=b, min_size=(12, 12))
        if safe is None:
            return None
        box = safe
    template = b[box[1] : box[1] + box[3], box[0] : box[0] + box[2]]
    if template.size == 0 or float(template.std()) < 1.0:
        return None  # 평평한 조각은 찾을 수 없다
    floor = threshold - UNIQUE_SLACK
    peaks_b = find_peaks(b, template, count=2)
    if sum(1 for score, _ in peaks_b if score >= floor) != 1:
        return None
    peaks_a = find_peaks(a, template, count=1)
    if peaks_a and peaks_a[0][0] >= threshold:
        return None  # A에도 있다: 전이로 나타난 것이 아니다
    return box


@dataclass(frozen=True, slots=True)
class WaitPlan:
    decision: WaitDecision
    box: Box | None = None
    """`image_wait`이면 B에서 자를 상자."""


def infer_wait(
    a: Pixels,
    b: Pixels,
    *,
    prev_t_ns: int,
    t_ns: int,
    last_change_ns: int | None,
    next_kind: NextKind,
    field_box: Box | None = None,
    click_found_in: Callable[[Pixels], bool] | None = None,
    protect: ProtectionSet | None = None,
    option_on: bool = True,
    threshold: float = DEFAULT_THRESHOLD,
) -> WaitPlan:
    """동작 하나 앞의 대기. `click_found_in(그림)`은 다음 클릭의 target을 재생 규칙으로 찾는다."""
    ratio = changed_ratio(a, b)
    region = changed_box(a, b)
    in_field = False
    if field_box is not None and region is not None:
        fx, fy, fw, fh = field_box
        rx, ry, rw, rh = region
        in_field = (
            rx >= fx - _PAD
            and ry >= fy - _PAD
            and rx + rw <= fx + fw + _PAD
            and ry + rh <= fy + fh + _PAD
        )
    in_a = None if click_found_in is None else click_found_in(a)
    box: Box | None = None
    if (
        region is not None
        and option_on
        and not in_field
        and not (next_kind == "click" and in_a is False)
    ):
        box = wait_crop(a, b, region, protect=protect, t_ns=t_ns, threshold=threshold)
    decision = decide_wait(
        WaitFacts(
            prev_t_ns=prev_t_ns,
            t_ns=t_ns,
            changed_ratio=ratio,
            last_change_ns=last_change_ns,
            next_kind=next_kind,
            r_in_field=in_field,
            click_target_in_a=in_a,
            wait_target=box is not None,
            option_on=option_on,
        )
    )
    return WaitPlan(decision, box if decision.kind == "image_wait" else None)
