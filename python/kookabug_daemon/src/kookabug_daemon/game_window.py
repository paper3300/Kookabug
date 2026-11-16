"""실행한 게임 기억 (UX7 C2): `window: "@game"`.

**주체별**로 기억한다 (UX7 검수 1 High 3): 키는 작업 연결이면 작업 ID, 아니면 Agent 연결의
agent ID다.
`kb_app_launch`가 띄운 게임, 또는 제목으로 하나로 정해진 입력·탐색 창의 프로세스를 (PID, 프로세스
생성 시각)으로 그 주체의 기억에만 쓴다. 쓰기는 권한 판정이 허용되고 입력·띄우기·탐색 시작이 성공한
뒤에만 한다(거부·승인 대기·실패 경로에는 상태 변경이 없다). `@game`·붙여 실행은 요청 주체 자신의
기억만 쓰고, 없으면 `window_not_found`다. 사람(데스크톱 앱) 연결은 기억에 쓰지도 읽지도 않는다.
기억은 daemon 메모리에만 있다(파일 없음).

`@game`은 그 프로세스의 주 창이다 — 로그인 뒤 창 제목이 바뀌어도 같은 프로세스의 창이면 붙는다.
주 창은 보이고·최소화 아님·cloaked 아님인 창 중 클라이언트 넓이가 가장 큰 창이다(UX8 A — 로딩 중
시작 화면 창을 띄웠다 닫고 본 창을 새로 만드는 게임).
창 제목은 계정 ID 같은 가려야 할 값이 들어 있을 수 있는 글로 본다: `@game`으로 붙은 결과·활동
목록·실행 기록에는 `@game`만 남기고 실제 제목은 권한 판정 인자로만 쓴다.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from kookabug_daemon.protocol import RequestFailed

if TYPE_CHECKING:
    from kookabug_core.permissions import Principal
    from kookabug_daemon.screen_source import ScreenSource, WindowBinding

__all__ = ["GAME", "GameMemory", "GameRef", "game_key", "is_game"]

GAME: Final = "@game"


def is_game(window: object) -> bool:
    return window == GAME


def game_key(principal: Principal) -> str | None:
    """그 주체의 기억 키: 작업이면 `job:<작업 ID>`, Agent면 `agent:<agent ID>`, 사람이면 None."""
    if principal.kind != "agent":
        return None
    if principal.job is not None:
        return f"job:{principal.job}"
    return f"agent:{principal.id}"


@dataclass(frozen=True, slots=True)
class GameRef:
    pid: int
    created: str


class GameMemory:
    """주체별 마지막으로 실행한(또는 입력으로 정해진) 게임 프로세스. 어느 스레드에서나 부른다."""

    def __init__(self, source: ScreenSource) -> None:
        self._source = source
        self._lock = threading.Lock()
        self._refs: dict[str, GameRef] = {}

    def get(self, principal: Principal) -> GameRef | None:
        key = game_key(principal)
        if key is None:
            return None
        with self._lock:
            return self._refs.get(key)

    def remember_pid(self, principal: Principal, pid: int) -> None:
        """`kb_app_launch`가 띄운 PID (생성 시각을 못 읽거나 사람이면 기억하지 않는다)."""
        key = game_key(principal)
        if key is None:
            return
        finder = getattr(self._source, "process_created", None)
        created = None if finder is None else finder(pid)
        if created:
            with self._lock:
                self._refs[key] = GameRef(pid, str(created))

    def remember(self, principal: Principal, binding: WindowBinding) -> None:
        """제목으로 하나로 정해진 창의 프로세스 (런처 뒤에 뜬 실제 게임 등). 사람이면 쓰지
        않는다."""
        key = game_key(principal)
        if key is None:
            return
        with self._lock:
            self._refs[key] = GameRef(binding.pid, binding.created)

    def windows(self, principal: Principal) -> list[tuple[WindowBinding, str]]:
        """그 주체가 기억한 프로세스의 창들 (바인딩, 지금 제목) — 주 창이 맨 앞. 기억이 없으면 빈
        목록."""
        ref = self.get(principal)
        if ref is None:
            return []
        finder = getattr(self._source, "windows_of", None)
        found = [] if finder is None else list(finder(ref.pid, ref.created))
        main = self._main(ref)
        if main is not None:
            found = [main, *(w for w in found if w[0] != main[0])]
        return found

    def _main(self, ref: GameRef) -> tuple[WindowBinding, str] | None:
        finder = getattr(self._source, "main_window_of", None)
        if finder is not None:
            return finder(ref.pid, ref.created)
        others = getattr(self._source, "windows_of", None)
        found = [] if others is None else list(others(ref.pid, ref.created))
        return found[0] if found else None

    def _require(self, principal: Principal) -> GameRef:
        ref = self.get(principal)
        if ref is None:
            raise RequestFailed(
                "window_not_found",
                "@game: 이 연결이 기억한 게임이 없다 — kb_app_launch로 띄우거나 창 제목으로 한 번 "
                "입력한다",
            )
        return ref

    def find(self, principal: Principal) -> tuple[WindowBinding, str] | None:
        """`@game`의 지금 주 창 (UX8 A — 보이고·최소화·cloaked 아님 중 클라이언트 넓이가 가장 큰
        창). 창이 아직 없으면 None, 기억이 없으면 `window_not_found`."""
        return self._main(self._require(principal))

    def alive(self, principal: Principal) -> bool:
        """기억한 게임 프로세스가 아직 살아 있는가 (모르면 True). 기억이 없으면 False."""
        ref = self.get(principal)
        if ref is None:
            return False
        check = getattr(self._source, "process_alive", None)
        return True if check is None else bool(check(ref.pid, ref.created))

    def resolve(self, principal: Principal) -> tuple[WindowBinding, str]:
        """`@game` → (주 창 바인딩, 지금 제목). 그 주체의 기억이 없거나 창이 없으면
        `window_not_found` (제목은 메시지에 넣지 않는다)."""
        found = self.find(principal)
        if found is None:
            raise RequestFailed(
                "window_not_found", "@game: 실행한 게임의 창이 없다 (닫혔거나 아직 뜨지 않았다)"
            )
        return found
