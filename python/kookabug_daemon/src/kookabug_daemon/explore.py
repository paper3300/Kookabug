"""에이전트 탐색 세션 (M7 계획 3.2·3.4·3.5b).

- `explore.start`(에이전트 전용): 연결마다 하나. 결과 폴더 `screens/_explored/<세션 ID>/`와
  `explore.json`(`kookabug.explore/0`)을 만든다. 세션 ID = `<UTC yyyymmdd-HHMMSS>-<4 hex>`
- `explore.end`·연결 끊김: `status: ended`, `ended_at`. 디스크가 `active`인데 살아 있는 세션이
  아니면 목록에서 `interrupted`
- **스텝** = 활성 세션 동안 그 연결의 control 도구 호출 중 판정을 통과해 제어 실행에 들어간 것.
  판정 **전에** 세션 잠금 안에서 한 칸을 예약하고(`steps + reserved >= max_steps`면
  `explore_budget_exhausted`), 제어 실행에 들어가면 스텝으로 확정, 거부·실패면 되돌린다(B3)
- 세션은 입력 임대권을 쥐지 않는다(클릭마다 기존 거부 그대로)
- "이 탐색 동안 허용"(`allow_session`) 범위는 승인 브로커의 메모리에 있다. 세션 끝·연결 끊김·예산
  다 씀을 `on_scope_end`로 알리고, 감사 기록만 `explore.json` `approvals[]`에 남긴다

저장·내보내는 글자 검사(3.5b, `check_texts`): 보호 기록의 비밀값 키 전부(`FrameGuard.secret_keys`)를
워크스페이스 비밀값 제공자로 읽어, 공백·대소문자 무시로 그 값이 글자에 들어 있으면 아무것도 쓰지
않고 `secret_in_text`(필드 이름만). 기록된 키를 하나라도 못 읽거나 보호 기록이 손상됐으면
`secret_unchecked`로 거부한다(fail closed). 값은 검사 동안만 메모리에 있다.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets as random
import threading
import unicodedata
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from kookabug_core.documents import DocumentError, write_atomic
from kookabug_core.screen_lock import ScreensBusy, screens_lock
from kookabug_core.screens import (
    EXPLORE_FILE,
    EXPLORED_DIR,
    SCREENS_DIR,
    SESSION_PATTERN,
    ScreenDef,
    explored_candidates,
)
from kookabug_core.workspace import Workspace, WorkspaceError, default_secrets
from kookabug_daemon.protocol import RequestFailed

__all__ = [
    "DEFAULT_MAX_STEPS",
    "ExploreSession",
    "ExploreSessions",
    "check_texts",
    "normalize",
]

DEFAULT_MAX_STEPS: Final = 200
FORMAT: Final = "kookabug.explore/0"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize(text: str) -> str:
    """비밀값 비교용: NFKC(전각 등), 서식 문자(`Cf` — 폭 없는 공백 등) 제거, 공백 제거, 대소문자
    무시."""
    folded = unicodedata.normalize("NFKC", text)
    plain = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    return "".join(plain.split()).casefold()


def plain_path(root: Path, parts: Sequence[str], *, within: Path | None = None) -> Path:
    """`root` 아래 `parts` 경로를 쓰기 전에 확인한다 (M7 B2b Mid 1): 있는 조각마다 링크·정션(재분석
    지점)이 아니고, 실경로가 `within`(기본 `root`)의 실경로 아래. 아니면 `path_outside_workspace`.
    `documents.resolve_path`·편집기 캐시와 같은 방식이다."""
    rel = "/".join(parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink() or (current.exists() and current.is_junction()):
            raise RequestFailed(
                "path_outside_workspace", f"'{rel}' 경로에 링크·정션이 있어 쓰지 않는다", path=rel
            )
    anchor = Path(os.path.realpath(within if within is not None else root))
    if not Path(os.path.realpath(current)).is_relative_to(anchor):
        raise RequestFailed(
            "path_outside_workspace", f"'{rel}'의 실경로가 허용된 폴더 밖이다", path=rel
        )
    return current


@contextlib.contextmanager
def write_lock(root: Path, session: ExploreSession | None = None) -> Iterator[None]:
    """화면 지도 쓰기 잠금: `screens.lock` → (있으면) 세션 잠금 (R4 순서). 승격·버리기(B4)도 같은
    `screens.lock`을 쓴다. 못 얻으면 `screens_busy`."""
    try:
        with screens_lock(root):
            if session is None:
                yield
            else:
                with session.lock:
                    yield
    except ScreensBusy as exc:
        raise RequestFailed("screens_busy", str(exc)) from exc


def job_secrets(daemon: Any) -> list[str]:
    """daemon 메모리의 작업 토큰 원문 (글자 검사 대상, M8 R9). 작업 표가 없는 대역이면 빈 목록."""
    jobs = getattr(daemon, "jobs", None)
    return [] if jobs is None else list(jobs.secret_values())


def check_texts(
    texts: Iterable[tuple[str, str]], guard: Any, root: Path, extra: Iterable[str] = ()
) -> None:
    """3.5b 글자 검사. `texts`는 (필드 이름, 글자). 걸리면 `secret_in_text`·`secret_unchecked`.
    `extra`는 메모리 원문 (M8 R9 — daemon의 작업 토큰 원문)."""
    pairs = [(name, text) for name, text in texts if text]
    if getattr(guard, "save_blocked", False):
        raise RequestFailed(
            "secret_unchecked",
            "보호 기록 파일이 손상돼 비밀값 검사를 할 수 없어 저장하지 않았다 (사람 확인 필요)",
        )
    keys = sorted(getattr(guard, "secret_keys", ()) or ())
    values: list[str] = [v for v in (normalize(x) for x in extra) if v]
    if (not keys and not values) or not pairs:
        return
    try:
        provider = default_secrets(Workspace.open(root))
    except (WorkspaceError, OSError) as exc:
        raise RequestFailed(
            "secret_unchecked", "비밀값을 읽지 못해 글자 검사를 할 수 없어 저장하지 않았다"
        ) from exc
    for key in keys:
        try:
            value = provider.get(key)
        except Exception:
            value = None
        if value is None:
            raise RequestFailed(
                "secret_unchecked",
                f"비밀값 '{key}'을(를) 읽지 못해 글자 검사를 할 수 없어 저장하지 않았다",
                reason=key,
            )
        found = normalize(value)
        if found:
            values.append(found)
    try:
        for name, text in pairs:
            plain = normalize(text)
            if any(v in plain for v in values):
                raise RequestFailed(
                    "secret_in_text",
                    f"'{name}'에 비밀값이 들어 있어 저장하지 않았다",
                    field=name,
                )
    finally:
        values.clear()


@dataclass
class ExploreSession:
    id: str
    connection: int
    agent_id: str
    client: str
    title: str
    goal: str | None
    window: str | None
    max_steps: int
    started_at: str
    folder: Path
    steps: int = 0
    reserved: int = 0
    """판정·사람 확인·시작 중인 control 호출 수 (B3 Mid 2 — 예산은 `steps + reserved`로 본다)."""
    approvals: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    lock: threading.Lock = field(default_factory=threading.Lock)
    """세션 파일 쓰기 잠금 (`write_lock` — 저장 게시 동안 오래 쥘 수 있다)."""
    budget: threading.Lock = field(default_factory=threading.Lock)
    """스텝·예약·감사 기록 메모리 값 잠금 (짧게만 쥔다 — 이벤트 루프에서도 부른다)."""

    @property
    def rel(self) -> str:
        return f"{SCREENS_DIR}/{EXPLORED_DIR}/{self.id}"

    def _approvals(self) -> list[dict[str, Any]]:
        with self.budget:
            return [dict(a) for a in self.approvals]

    def record(self, status: str, ended_at: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "format": FORMAT,
            "id": self.id,
            "title": self.title,
            "agent": {"id": self.agent_id, **({"client": self.client} if self.client else {})},
            "started_at": self.started_at,
            "ended_at": ended_at,
            "status": status,
            "steps": self.steps,
            "max_steps": self.max_steps,
            "approvals": self._approvals(),
            "promoted": {},
        }
        if self.goal:
            body["goal"] = self.goal
        if self.window:
            body["window"] = self.window
        return body


type ScopeEnded = Callable[[int, str, str], None]
"""(연결, 세션 ID, 사유 `ended`·`disconnected`·`budget`) — "이 탐색 동안 허용" 범위가 끝났다."""


class StepReservation:
    """control 호출 하나가 쥔 예산 한 칸 (B3 Mid 2). 제어 실행에 들어가면 `commit`(스텝 하나),
    판정 거부·사람 거부·시작 실패면 `release`(되돌림). 둘 다 한 번만 효과가 있다."""

    def __init__(self, owner: ExploreSessions, session: ExploreSession) -> None:
        self._owner = owner
        self.session = session
        self._done = False

    def commit(self) -> None:
        if self._take():
            self._owner.count_step(self.session)

    def release(self) -> None:
        self._take()

    def _take(self) -> bool:
        with self.session.budget:
            if self._done:
                return False
            self._done = True
            self.session.reserved -= 1
            return True


class ExploreSessions:
    """연결별 활성 탐색 세션. 어느 스레드에서 불러도 된다."""

    def __init__(self, root: Path, notify: Callable[[], None] | None = None) -> None:
        self.root = root
        self.notify = notify
        self.on_scope_end: ScopeEnded | None = None
        """세션 끝·연결 끊김·예산 다 씀을 승인 브로커에 알린다 (`allow_session` 범위 소멸, B3)."""
        self._lock = threading.Lock()
        self._active: dict[int, ExploreSession] = {}

    # ------------------------------------------------------------ 수명

    def start(
        self,
        connection: int,
        agent_id: str,
        client: str,
        title: str,
        goal: str | None,
        window: str | None,
        max_steps: int,
    ) -> ExploreSession:
        # 잠금 순서: screens.lock → 세션 표 잠금 (explore.json 쓰기도 승격과 같은 잠금 안)
        with write_lock(self.root), self._lock:
            if connection in self._active:
                current = self._active[connection]
                raise RequestFailed(
                    "explore_active",
                    f"이 연결에는 이미 탐색 세션 {current.id}이(가) 있다 (kb_explore_end 먼저)",
                )
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            session_id = f"{stamp}-{random.token_hex(2)}"
            # screens/·_explored/가 링크·정션이면 거부 (워크스페이스 밖·확정 자리로 새지 않게)
            base = plain_path(self.root, (SCREENS_DIR, EXPLORED_DIR))
            folder = base / session_id
            session = ExploreSession(
                session_id,
                connection,
                agent_id,
                client,
                title,
                goal,
                window,
                max_steps,
                _now(),
                folder,
            )
            try:
                folder.mkdir(parents=True, exist_ok=False)
            except OSError as exc:
                raise RequestFailed("io_error", f"탐색 폴더를 만들 수 없다: {exc}") from exc
            plain_path(self.root, (SCREENS_DIR, EXPLORED_DIR, session_id))
            self._write(session, "active")
            self._active[connection] = session
        self._changed()
        return session

    def end(self, connection: int, reason: str = "ended") -> ExploreSession | None:
        with self._lock:
            session = self._active.pop(connection, None)
        if session is None:
            return None
        # 표에서 뺀 **뒤에** 알린다: 그 사이 온 늦은 답도 살아 있는 세션을 찾지 못해 아무것도
        # 허락하지 않는다 (승인 브로커가 답할 때 세션을 다시 본다)
        self._scope_end(connection, session.id, reason)
        # 잠금을 못 얻으면 디스크는 interrupted로 보인다
        with contextlib.suppress(RequestFailed), write_lock(self.root, session):
            self._write(session, "ended", _now())
        self._changed()
        return session

    def get(self, connection: int) -> ExploreSession | None:
        with self._lock:
            return self._active.get(connection)

    def live(self, connection: int, session_id: str) -> ExploreSession | None:
        """그 연결의 지금 세션이 `session_id`면 그 세션 (끝났거나 다른 세션이면 None)."""
        session = self.get(connection)
        return session if session is not None and session.id == session_id else None

    def require(self, connection: int) -> ExploreSession:
        session = self.get(connection)
        if session is None:
            raise RequestFailed(
                "explore_not_active", "탐색 세션이 없다 (kb_explore_start로 먼저 시작한다)"
            )
        return session

    def live_ids(self) -> set[str]:
        with self._lock:
            return {s.id for s in self._active.values()}

    # ------------------------------------------------------------ 예산 (스텝)

    def reserve(self, connection: int) -> StepReservation | None:
        """판정(사람 확인) **전에** 예산 한 칸을 예약한다 (B3 Mid 2). 세션의 예산 잠금 안에서
        `steps + reserved < max_steps`일 때만 — 승인 대기 중인 요청 여럿이 예산을 넘지 못한다.
        다 썼으면 `explore_budget_exhausted`(세션은 그대로). 세션이 없으면 None."""
        session = self.get(connection)
        if session is None:
            return None
        with session.budget:
            if session.steps + session.reserved >= session.max_steps:
                raise RequestFailed(
                    "explore_budget_exhausted",
                    f"탐색 스텝 예산 {session.max_steps}을(를) 다 썼다 (kb_explore_end 뒤 새 세션)",
                )
            session.reserved += 1
        return StepReservation(self, session)

    def count_step(self, session: ExploreSession) -> None:
        """예약한 칸이 제어 실행에 들어갔다: 스텝 하나. 세션이 이미 끝났으면 세지 않는다."""
        if self.live(session.connection, session.id) is None:
            return
        with session.budget:
            session.steps += 1  # 메모리가 기준 (살아 있는 동안)
            spent = session.steps >= session.max_steps
        # 잠금을 못 얻으면 다음 쓰기에서 따라잡는다
        with contextlib.suppress(RequestFailed), write_lock(self.root, session):
            self._write(session, "active")
        if spent:
            # 예산을 다 썼다: "이 탐색 동안 허용" 범위도 끝난다 (세션은 kb_explore_end까지 그대로)
            self._scope_end(session.connection, session.id, "budget")
        self._changed()

    # ------------------------------------------------------------ 이 탐색 동안 허용 (감사 기록)

    def note_approval(self, session: ExploreSession, entry: Mapping[str, Any]) -> None:
        """`allow_session` 감사 기록을 메모리 세션에 더한다 (짧다 — 이벤트 루프에서 부른다).
        파일은 `flush`나 세션 끝 쓰기가 `explore.json` `approvals[]`로 남긴다 (범위 자체는 브로커
        메모리)."""
        with session.budget:
            session.approvals.append(dict(entry))

    def flush(self, session: ExploreSession) -> None:
        """살아 있는 세션의 `explore.json`을 지금 메모리 값으로 다시 쓴다 (잠금을 못 얻으면
        건너뜀)."""
        if self.live(session.connection, session.id) is None:
            return
        with contextlib.suppress(RequestFailed), write_lock(self.root, session):
            self._write(session, "active")

    def _scope_end(self, connection: int, session_id: str, reason: str) -> None:
        hook = self.on_scope_end
        if hook is not None:
            with contextlib.suppress(Exception):  # 알림 실패가 세션 끝을 막지 않는다
                hook(connection, session_id, reason)

    # ------------------------------------------------------------ 기록

    def _write(self, session: ExploreSession, status: str, ended_at: str | None = None) -> None:
        path = session.folder / EXPLORE_FILE
        body = session.record(status, ended_at)
        old = _read_json(path)
        if old is not None and isinstance(old.get("promoted"), dict):
            body["promoted"] = old["promoted"]  # 승격 기록(사람)은 지우지 않는다
        try:
            write_atomic(path, json.dumps(body, ensure_ascii=False, indent=1).encode("utf-8"))
        except DocumentError as exc:
            raise RequestFailed("io_error", f"explore.json을 쓸 수 없다: {exc}") from exc

    def changed(self) -> None:
        """후보가 바뀌었다 (저장) — 사람 연결에 알린다."""
        self._changed()

    def _changed(self) -> None:
        if self.notify is not None:
            with contextlib.suppress(Exception):  # 알림 실패는 세션을 막지 않는다
                self.notify()

    def listing(self, workspace: Workspace) -> list[dict[str, Any]]:
        """`explore.list`·`explore.changed`: 디스크의 세션들 (최신 먼저)."""
        live = self.live_ids()
        candidates = explored_candidates(workspace)
        out: list[dict[str, Any]] = []
        base = self.root / SCREENS_DIR / EXPLORED_DIR
        if not base.is_dir():
            return out
        for folder in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
            if not folder.is_dir() or SESSION_PATTERN.fullmatch(folder.name) is None:
                continue
            data = _read_json(folder / EXPLORE_FILE)
            if data is None:
                continue
            status = str(data.get("status", "ended"))
            if status == "active" and folder.name not in live:
                status = "interrupted"
            mine = [
                c.screen
                for c in candidates
                if c.session == folder.name and c.placement == "session" and c.screen
            ]
            out.append(
                {
                    "id": folder.name,
                    "title": str(data.get("title", "")),
                    "status": status,
                    "agent": str(_mapping(data.get("agent")).get("id", "")),
                    "steps": int(data.get("steps", 0) or 0),
                    "max_steps": int(data.get("max_steps", DEFAULT_MAX_STEPS) or 1),
                    "started_at": str(data.get("started_at", "")),
                    "counts": _counts(mine),
                }
            )
        return out


def _counts(screens: Iterable[ScreenDef]) -> dict[str, int]:
    items = list(screens)
    moves = [m for s in items for m in s.moves]
    return {
        "screens": len(items),
        "moves": sum(m.status == "tried" for m in moves),
        "untried": sum(m.status == "untried" for m in moves),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError, UnicodeDecodeError:
        return None
    return data if isinstance(data, dict) else None
