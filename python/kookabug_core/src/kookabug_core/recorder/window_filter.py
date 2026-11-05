"""대상 창 거르기 (M4 계획 2.4). 이벤트에 붙은 즉시 관측과 그 시각의 기하 세대로만 판정한다.

- 마우스: 버튼·휠 자리의 점 아래 최상위 창(관측 Z 순서 표)이 대상 창이고 그 세대의 클라이언트
  안이면 녹화. 대상 창의 소유 팝업 위면 `popup`, 그 밖은 `outside`
- 키: 이벤트 때 포그라운드가 대상 창 자신일 때만. 대상의 소유 팝업이 앞이면 `popup`(그 키·글자·
  Enter도 기본 창 사슬에 넣지 않는다), 그 밖은 `outside`
- 관측을 쓸 수 없으면(`obs_usable` 아님 — 50 ms 밖·표가 바뀜·없음) `undetermined`: 버리지 않고
  확인 필요(`window_undetermined`)로 남긴다
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from kookabug_core.recorder.contract import obs_usable
from kookabug_core.recorder.events import GeometryLookup, to_client

__all__ = ["Verdict", "Where", "WindowFilter"]

type Where = Literal["target", "popup", "outside", "undetermined"]


@dataclass(frozen=True, slots=True)
class Verdict:
    where: Where
    client: tuple[int, int] | None = None
    """그 이벤트 세대의 클라이언트 점 (마우스, 세대를 알고 클라이언트 안일 때)."""
    gen: int | None = None
    """이벤트 시각의 확정 세대 (불확실 구간이면 None)."""
    obs: Mapping[str, Any] | None = None
    """쓸 수 있는 즉시 관측."""


class WindowFilter:
    def __init__(self, target_hwnd: int, geometry: GeometryLookup) -> None:
        self.target = target_hwnd
        self.geometry = geometry

    def classify(self, event: Mapping[str, Any], obs: Mapping[str, Any] | None) -> Verdict:
        usable = obs if obs_usable(event, obs) else None
        kind = event.get("kind")
        if kind in ("mouse_down", "mouse_up", "wheel", "mouse_move"):
            gen = self.geometry.generation_at(int(event["t_ns"]))
            client = None if gen is None else to_client(gen, (event["x"], event["y"]))
            gen_no = None if gen is None else gen.gen
            if usable is None:
                return Verdict("undetermined", client, gen_no)
            window = usable.get("point_window")
            if window == self.target:
                if gen is not None and client is None:
                    return Verdict("outside", None, gen_no, usable)  # 제목 표시줄·테두리
                return Verdict("target", client, gen_no, usable)
            if window is None:
                return Verdict("undetermined", client, gen_no)
            if usable.get("point_owner") == self.target:
                return Verdict("popup", None, gen_no, usable)
            return Verdict("outside", None, gen_no, usable)
        if usable is None:
            return Verdict("undetermined")
        fg = usable.get("fg")
        if fg == self.target:
            return Verdict("target", obs=usable)
        if fg is None:
            return Verdict("undetermined")
        if usable.get("fg_owner") == self.target:
            return Verdict("popup", obs=usable)
        return Verdict("outside", obs=usable)
