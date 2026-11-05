"""비밀값 보호 영역 (M4 계획 2.6 "비밀값 보호 영역", 검수 M6).

비밀값·판정 대기·확인 필요 입력 칸 구간의 칸 상자는 **보호 영역**이다. 구간 시작 뒤 프레임부터
세션 끝까지 목록에 남는다. 칸이 없음으로 확정된(`end`) 보호도 풀리지 않고, **자를 그 프레임에서**
칸이 없다는 근거(네 근거 조각 모두·칸 자체·장면이 바뀜)가 있을 때만 그 프레임의 겹침을 허용한다
— 일부 가림·판정 불가는 보호. 사람이 "일반 글자"로 확인한 구간은 보호 영역이 아니다.

모든 target 내보내기(자동 클릭 자르기·넓히기·대기 자르기·REC 탭 수동 영역·화면/값 확인 삽입·즉시
저장)와 이름·제목 짓기가 이 모듈 하나를 거친다. 모두 자를 프레임(`frame`)을 같이 넘긴다:

- `ProtectionSet.overlaps(box, t_ns, frame)`: 그 프레임에서 보호하는 칸과 겹치는가
- `ProtectionSet.require_clear(box, t_ns, frame)`: 사람이 고른 영역 — 겹치면 `SecretRegionOverlap`
- `ProtectionSet.avoid(box, point, t_ns, frame=…)`: 자동 자르기 — 겹치지 않게 줄이거나 옮긴다(점은
  안에 남긴다). 못 하면 None
- `safe_name(ocr_text, raw_texts, fallback)`: 이름·제목용 글자. 세션의 보호 대상 원문을 포함하면
  버린다
"""

from __future__ import annotations

import re
import threading
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from kookabug_core.recorder.fields import SecretText

__all__ = [
    "NAME_MAX",
    "AbsentIn",
    "Box",
    "ProtectedRegion",
    "ProtectionSet",
    "SecretRegionOverlap",
    "boxes_overlap",
    "safe_name",
    "sanitize_name",
]

type Box = tuple[int, int, int, int]
"""`(x, y, w, h)` 클라이언트 물리 픽셀."""

NAME_MAX: Final = 20
"""이름에 쓰는 글자 수 상한 (파일 이름·노드 제목)."""
_NAME_BAD: Final = re.compile(r"[\\/:*?\"<>|\x00-\x1f.\s]+")


class SecretRegionOverlap(Exception):
    """사람이 고른 영역이 보호 영역과 겹친다 (`secret_region_overlap`)."""

    code = "secret_region_overlap"

    def __init__(self, spans: Iterable[int]) -> None:
        self.spans = tuple(sorted(set(spans)))
        super().__init__("비밀번호 칸과 겹친 영역은 찾기 대상으로 저장할 수 없다")


def boxes_overlap(a: Box, b: Box) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


type AbsentIn = Callable[[int, Box, object], bool]
"""(구간 ID, 칸 상자, 자를 프레임) → 그 프레임에서 칸이 없다는 근거가 확실한가 (플랫폼
`FieldPresenceTracker.absent_in`). 모르면 False."""


@dataclass(slots=True)
class ProtectedRegion:
    span_id: int
    box: Box
    from_ns: int
    ended_ns: int | None = None
    """칸이 없음으로 확정된 시각. 끝난 보호도 목록에 남는다 — 끝났다고 풀리지 않고, 자를 프레임에서
    칸이 없다는 근거가 있을 때만 그 프레임의 겹침을 허용한다."""
    released: bool = False
    """사람이 일반 글자로 확인했다 (보호 영역이 아니다)."""

    def applies(self, t_ns: int | None) -> bool:
        """`t_ns` 프레임이 이 보호의 대상인가 (구간 시작 전 프레임만 아니다). 시각을 모르면 대상."""
        if self.released:
            return False
        return t_ns is None or self.from_ns <= t_ns


class ProtectionSet:
    """녹화 세션 하나의 보호 영역 목록. 여러 스레드에서 불러도 된다.

    판정은 **자를 프레임 기준**이다: 진행 중인 보호는 늘 보호, 끝난 보호(`end`)는 그 프레임에서
    `absent_in`이 칸이 없다고 확인할 때만 겹침을 허용한다(일부 가림·판정 불가·프레임 없음은 보호).
    `absent_in`이 없으면 끝난 보호도 늘 보호한다.
    """

    def __init__(self, absent_in: AbsentIn | None = None) -> None:
        self._lock = threading.Lock()
        self._regions: dict[int, ProtectedRegion] = {}
        self.absent_in = absent_in

    def add(self, span_id: int, box: Box, from_ns: int) -> None:
        """구간의 칸 상자를 보호한다 (이미 있으면 상자·시작을 넓힌다)."""
        with self._lock:
            old = self._regions.get(span_id)
            if old is None:
                self._regions[span_id] = ProtectedRegion(span_id, box, from_ns)
                return
            old.box = _union(old.box, box)
            old.from_ns = min(old.from_ns, from_ns)

    def end(self, span_id: int, at_ns: int) -> None:
        """칸이 없음으로 확정됐다. 보호는 목록에 남고, 그 뒤 프레임은 `absent_in`으로 본다."""
        with self._lock:
            region = self._regions.get(span_id)
            if region is not None and region.ended_ns is None:
                region.ended_ns = at_ns

    def release(self, span_id: int) -> None:
        """사람이 "일반 글자로" 확인했다."""
        with self._lock:
            region = self._regions.get(span_id)
            if region is not None:
                region.released = True

    def protect_again(self, span_id: int) -> None:
        """일반 → 비밀로 되돌렸다."""
        with self._lock:
            region = self._regions.get(span_id)
            if region is not None:
                region.released = False

    def active(self, t_ns: int | None, frame: object = None) -> list[ProtectedRegion]:
        """`t_ns`에 도착한 프레임 `frame`에서 보호하는 칸 (프레임을 모르면 끝난 보호도 보호)."""
        with self._lock:
            regions = [r for r in self._regions.values() if r.applies(t_ns)]
            judge = self.absent_in
        return [
            r
            for r in regions
            if r.ended_ns is None or judge is None or frame is None or not _absent(judge, r, frame)
        ]

    def overlapping(self, box: Box, t_ns: int | None, frame: object = None) -> list[int]:
        return [r.span_id for r in self.active(t_ns, frame) if boxes_overlap(r.box, box)]

    def overlaps(self, box: Box, t_ns: int | None, frame: object = None) -> bool:
        return bool(self.overlapping(box, t_ns, frame))

    def require_clear(self, box: Box, t_ns: int | None, frame: object = None) -> None:
        """사람이 고른 영역(`frame`에서 자름): 겹치면 거부한다."""
        spans = self.overlapping(box, t_ns, frame)
        if spans:
            raise SecretRegionOverlap(spans)

    def avoid(
        self,
        box: Box,
        point: tuple[int, int] | None,
        t_ns: int | None,
        *,
        frame: object = None,
        min_size: tuple[int, int] = (16, 16),
    ) -> Box | None:
        """자동 자르기(`frame`에서 자름): 보호 영역과 겹치지 않게 상자를 줄인다. 줄인 상자는
        `point`를 안에 두고 `min_size` 이상이어야 한다. 겹치지 않으면 그대로, 못 만들면 None."""
        regions = [r.box for r in self.active(t_ns, frame) if boxes_overlap(r.box, box)]
        if not regions:
            return box
        if point is not None and any(_contains(r, point) for r in regions):
            return None  # 점 자체가 비밀 칸 안: 어떤 상자도 그 칸을 덮는다
        current = box
        for region in regions:
            if not boxes_overlap(region, current):
                continue
            current = _cut_away(current, region, point)
            if current is None:
                return None
        if current[2] < min_size[0] or current[3] < min_size[1]:
            return None
        if any(boxes_overlap(r, current) for r in regions):
            return None
        return current


def _absent(judge: AbsentIn, region: ProtectedRegion, frame: object) -> bool:
    try:
        return bool(judge(region.span_id, region.box, frame))
    except Exception:
        return False  # 판정 불가 = 보호


def _contains(box: Box, point: tuple[int, int]) -> bool:
    return box[0] <= point[0] < box[0] + box[2] and box[1] <= point[1] < box[1] + box[3]


def _union(a: Box, b: Box) -> Box:
    x0, y0 = min(a[0], b[0]), min(a[1], b[1])
    x1, y1 = max(a[0] + a[2], b[0] + b[2]), max(a[1] + a[3], b[1] + b[3])
    return (x0, y0, x1 - x0, y1 - y0)


def _cut_away(box: Box, region: Box, point: tuple[int, int] | None) -> Box | None:
    """`box`에서 `region` 쪽을 잘라 낸 네 후보(왼·오른·위·아래 남김) 중 점을 품고 가장 넓은 것."""
    x, y, w, h = box
    rx, ry, rw, rh = region
    candidates = [
        (x, y, rx - x, h),  # region 왼쪽만 남김
        (rx + rw, y, x + w - (rx + rw), h),  # 오른쪽
        (x, y, w, ry - y),  # 위
        (x, ry + rh, w, y + h - (ry + rh)),  # 아래
    ]
    usable = [
        c for c in candidates if c[2] > 0 and c[3] > 0 and (point is None or _contains(c, point))
    ]
    if not usable:
        return None
    return max(usable, key=lambda c: c[2] * c[3])


def sanitize_name(text: str) -> str:
    """파일 이름·노드 제목에 쓸 수 있게 정리 (앞 20자). 남는 것이 없으면 빈 문자열."""
    text = unicodedata.normalize("NFC", text)
    text = _NAME_BAD.sub("_", text).strip("_")
    return text[:NAME_MAX].strip("_")


def safe_name(ocr_text: str | None, raw_texts: Iterable[SecretText], fallback: str) -> str:
    """이름용 OCR 글자 → 이름. 글자가 없거나 세션의 보호 대상 원문(비밀값·판정 대기·확인 필요
    구간)을 하나라도 포함하면 `fallback`. 원문은 비교에만 쓰고 결과·예외에 넣지 않는다."""
    if not ocr_text:
        return fallback
    name = sanitize_name(ocr_text)
    if not name:
        return fallback
    folded_name = name.casefold()
    folded_text = ocr_text.casefold()
    for raw in raw_texts:
        if not raw:
            continue
        secret = raw.reveal().casefold()
        # 길이 예외 없음: 짧은 값 때문에 일반 이름이 대체 이름이 되는 불편은 감수한다
        if secret in folded_text or secret in folded_name or folded_name in secret:
            return fallback
    return name
