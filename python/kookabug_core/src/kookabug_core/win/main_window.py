"""게임 주 창 고르기 규칙 (UX8 A·UX9 A) — daemon `@game`과 runner `core.app.launch`가 같이 쓴다.

주 창은 그 프로세스의 창 중 **보이고·최소화 아님·cloaked 아님**인 창에서 클라이언트 넓이가 가장
큰 창이다. 시작 화면(splash) 창이 먼저 떠 있어도 본 창이 뜨면 본 창을 고른다. 넓이가 같으면 앞
(Z 순서) 창.
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["pick_main"]


def pick_main[T](candidates: Iterable[tuple[T, bool, int]]) -> T | None:
    """(창, 쓸 수 있음, 클라이언트 넓이) 중 쓸 수 있는 창에서 넓이가 가장 큰 창. 없으면 None."""
    best: T | None = None
    best_area = 0
    for window, usable, area in candidates:
        if usable and area > best_area:
            best, best_area = window, area
    return best
