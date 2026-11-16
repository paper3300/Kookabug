"""에이전트 정지 화면 보호 판정 `frame_guard` (M7 계획 3.5a, UX11 B).

에이전트 연결이 만든(또는 에이전트에게 나갈) 정지 화면의 **모든 출구** 앞에서 이 판정 하나를 쓴다.
`Clear`가 아니면 그 출구는 이미지·글자를 내지 않는다.

판정 (앞에서부터, 하나라도 걸리면 그 결과):
1. **민감 target**: 워크스페이스 `sensitive: true` target이 그 프레임에 보이면 `protected
   (sensitive_visible)`, 확인 못 하면 `unchecked(sensitive_unchecked)` — 상자만이 아니라 이미지 전체
2. 판정 중 예외는 `unchecked(guard_error)`

UX11 B (2026-11-16 사용자 결정 — 로컬 툴이라 게임 비밀값은 가리지 않는다): 비밀값을 입력한 창의
보호 기록(`secret_field`·`secret_field_unknown`)·칸 상자 근거·기록 손상 시 막기를 없앴다. 옛
`.kookabug/agent-protect.json`은 쓰지도 읽지도 않는다(남아 있어도 무시 — 지워도 된다, UX12).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final, Literal

from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.screen_source import ScreenSource

if TYPE_CHECKING:
    from kookabug_daemon.frames import EditorFrame, FrameCache
    from kookabug_daemon.targets import TargetStore

__all__ = ["CLEAR", "FILE", "HINTS", "FrameGuard", "Guard"]

FILE: Final = ".kookabug/agent-protect.json"
"""옛 보호 기록 파일 (UX11 B부터 daemon은 쓰지도 읽지도 않는다)."""

type GuardState = Literal["clear", "protected", "unchecked"]

HINTS: Final[Mapping[str, str]] = {
    "sensitive_visible": "민감 대상이 보이는 화면이라 이미지를 보내지 않아요",
    "sensitive_unchecked": "민감 대상을 확인하지 못해 이미지를 보내지 않아요",
    "window_unknown": "어느 창인지 확인하지 못해 이미지를 보내지 않아요",
    "guard_error": "보호 판정에 실패해 이미지를 보내지 않아요",
}
_SENSITIVE: Final = frozenset({"sensitive_visible", "sensitive_unchecked"})
_RANK: Final[Mapping[str, int]] = {"clear": 0, "unchecked": 1, "protected": 2}


@dataclass(frozen=True, slots=True)
class Guard:
    state: GuardState
    reason: str | None = None
    path: str | None = None
    """민감 target 사유면 그 target 파일 (워크스페이스 기준 — 값이 아니다)."""

    @property
    def clear(self) -> bool:
        return self.state == "clear"

    def worse(self, other: Guard | None) -> Guard:
        """둘 중 나쁜 쪽 (`clear`로 올라가지 않는다)."""
        if other is None or _RANK[self.state] >= _RANK[other.state]:
            return self
        return other

    def to_json(self) -> dict[str, str]:
        reason = self.reason or "guard_error"
        return {"reason": reason, "hint": HINTS.get(reason, HINTS["guard_error"])}

    def refusal(self) -> RequestFailed:
        """이 판정으로 출구를 막을 때의 오류. 민감 target 사유는 M5의 `sensitive_region` 그대로."""
        info = self.to_json()
        if info["reason"] in _SENSITIVE and self.path is not None:
            # M5 `screen.read_text`와 같은 오류·문구 (그 target 경로 — 값이 아니다)
            text = (
                f"민감 target을 확인하지 못함 ('{self.path}'을(를) 읽거나 판정할 수 없다) — "
                "읽지 않는다"
                if info["reason"] == "sensitive_unchecked"
                else f"민감 target '{self.path}'이(가) 보이는 화면이라 읽지 않는다"
            )
            return RequestFailed("sensitive_region", text, path=self.path, reason=info["reason"])
        code = "sensitive_region" if info["reason"] in _SENSITIVE else "frame_protected"
        return RequestFailed(code, info["hint"], reason=info["reason"], message=info["hint"])


CLEAR: Final = Guard("clear")


class FrameGuard:
    """정지 화면 보호 판정 (민감 target만). 어느 스레드에서 불러도 된다.

    UX11 B: 비밀값을 입력한 창의 보호 기록·칸 상자 근거·손상 시 막기는 없앴다 — 게임 비밀값은
    가리지 않는다. 옛 `.kookabug/agent-protect.json`은 읽지 않는다."""

    def __init__(
        self,
        root: Path,
        frames: FrameCache,
        targets: TargetStore,
        source: ScreenSource,
    ) -> None:
        self.root = root
        self.frames = frames
        self.targets = targets
        self.source = source

    # ------------------------------------------------------------ 판정

    def check(self, frame: EditorFrame) -> Guard:
        """그 정지 화면의 지금 판정 (민감 target이 보이면 막는다)."""
        try:
            hit = self.targets.sensitive_visible(frame)
            if hit is not None:
                return (
                    Guard("unchecked", "sensitive_unchecked", hit.path)
                    if hit.failed
                    else Guard("protected", "sensitive_visible", hit.path)
                )
            return CLEAR
        except Exception:
            return Guard("unchecked", "guard_error")

    def effective(self, frame: EditorFrame) -> Guard:
        """출구에서 쓰는 판정: 캡처 시점 판정과 지금 판정 중 하나라도 `clear`가 아니면 막는다
        (`clear`로 올라가지 않음). 사유는 지금 판정이 막으면 지금 것(안내가 지금 화면에 맞게)."""
        now = self.check(frame)
        if not now.clear or frame.guard is None:
            return now
        return frame.guard

    def require_clear(self, frame: EditorFrame) -> None:
        guard = self.effective(frame)
        if not guard.clear:
            raise guard.refusal()
