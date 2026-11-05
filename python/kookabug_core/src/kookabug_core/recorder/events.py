"""변환기 입력의 공용 모양 (M4 계획 2.5·2.7): 기하 세대 조회 계약, 끊긴 곳 자르기.

기하 세대 시간표는 플랫폼(`kookabug_platform.recorder.geometry.GeometryTimeline`)에 있다. 코어는
그 모양만 받는다(`GeometryLookup`) — 이벤트 시각의 세대로 화면 → 클라이언트를 바꾸고, 처리하는
순간의 창 정보를 읽지 않는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

__all__ = [
    "GenerationLike",
    "GeometryLike",
    "GeometryLookup",
    "clip_to_client",
    "to_client",
    "truncate_at_cut",
]


class GeometryLike(Protocol):
    @property
    def client_origin(self) -> tuple[int, int]: ...
    @property
    def client_size(self) -> tuple[int, int]: ...


class GenerationLike(Protocol):
    @property
    def gen(self) -> int: ...
    @property
    def geometry(self) -> GeometryLike: ...


class GeometryLookup(Protocol):
    def generation_at(self, t_ns: int) -> GenerationLike | None: ...


def to_client(gen: GenerationLike, point: Sequence[int]) -> tuple[int, int] | None:
    """화면 점 → 그 세대의 클라이언트 점. 클라이언트 영역 밖이면 None."""
    g = gen.geometry
    x, y = int(point[0]) - g.client_origin[0], int(point[1]) - g.client_origin[1]
    if 0 <= x < g.client_size[0] and 0 <= y < g.client_size[1]:
        return (x, y)
    return None


def clip_to_client(gen: GenerationLike, point: Sequence[int]) -> tuple[tuple[int, int], bool]:
    """화면 점 → 클라이언트 점, 밖이면 가장자리로 자른다 (끌기 끝점). (점, 잘렸는가)."""
    g = gen.geometry
    x, y = int(point[0]) - g.client_origin[0], int(point[1]) - g.client_origin[1]
    cx = min(max(x, 0), g.client_size[0] - 1)
    cy = min(max(y, 0), g.client_size[1] - 1)
    return (cx, cy), (cx, cy) != (x, y)


def truncate_at_cut(
    events: Iterable[Mapping[str, Any]], cut_crit_seq: int | None
) -> list[Mapping[str, Any]]:
    """연속성 위반의 `cut_crit_seq` **앞**까지만 (상태별 마무리 `hook_lost`·`input_overflow`).
    그 번호 이상의 중요 이벤트가 처음 보인 뒤의 이벤트(이동 포함)는 쓰지 않는다."""
    out: list[Mapping[str, Any]] = []
    for event in events:
        seq = event.get("crit_seq")
        if cut_crit_seq is not None and isinstance(seq, int) and seq >= cut_crit_seq:
            break
        out.append(event)
    return out
