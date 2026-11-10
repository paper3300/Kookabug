"""사람 확인 (M5 계획 D4·3.6). 이벤트 루프 안에서만 쓴다.

에이전트 연결의 판정이 ask면:

1. 연결이 사람 없음(`attended: false`)이면 `decide`가 이미 deny다(`unattended_ask`)
2. 사람(ui) 연결이 없으면 기다리지 않고 `approval_required`(`reason: no_approver`)
3. 있으면 확인 요청을 만들어 ui 연결에 `approval.requested`를 알리고 기다린다(120초). 기다리는 동안
   경로 잠금·파일을 쥐지 않는다 — 승인 뒤 쓰기가 revision을 다시 보므로 그 사이 UI가 고쳤으면 늦은
   쪽(에이전트)이 `revision_conflict`
4. 답: `allow_once` → `require(..., approved=True)`로 다시 판정(그 사이 deny로 바뀌었으면 deny).
   `allow_always` → 프로젝트 계층에 그 도구·인자에만 맞는 allow 규칙을 쓴 뒤 같이 다시 판정. control
   도구는 받지 않는다(`always_not_allowed`, U2). `deny` → `approval_denied`. 시간 초과 →
   `approval_timeout`. 요청한 연결이 끊기면 취소. 어느 쪽이든 `approval.resolved`로 카드를 닫는다

답(`approval.respond`)·미리보기(`approval.preview`)는 `ui_only`이고 `AGENT_DENIED`라 에이전트는 자기
요청을 승인할 수 없다. 판정 도구는 daemon 표(`METHOD_TOOLS`)가 정한다.

**이 탐색 동안 허용**(`allow_session`, M7 3.11 U2): 요청 연결에 활성 탐색 세션이 있고 도구가
control 또는 screens 변경 도구일 때만 카드에 나온다(`session`). 범위 = (연결, 세션, 도구, 권한
인자 — control은 창 제목, screens는 도구 전체)이고 **이 브로커의 메모리에만** 있다(파일에 규칙을
쓰지 않음 — daemon 재시작에 사라진다). 같은 범위의 다음 ask는 묻지 않고 승인으로 친다. 판정을 먼저
하므로 deny 규칙이 늘 이긴다(범위는 ask만 건너뛴다). 세션 끝·연결 끊김·예산 다 씀이면 범위가
사라지고(`scope_ended`), 그 세션에 걸린 대기 요청은 `cancelled`(`approval_cancelled`)로 끝난다.
답할 때도 세션이 살아 있는지 다시 보므로 늦은 답은 아무것도 허락하지 않는다. 감사 기록(도구·창
제목·시각)만 `explore.json`에 남기고, 창 제목은 3.5b 글자 검사를 지날 때만 적는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Final, Literal

from kookabug_core import documents as core_documents
from kookabug_core.documents import DocumentError
from kookabug_core.permissions import TOOLS, Decision, Principal, exact_rule
from kookabug_daemon.explore import ExploreSession, check_texts, job_secrets
from kookabug_daemon.graph_patch import PatchInvalid, apply_ops
from kookabug_daemon.methods.tools import METHOD_TOOLS, Authorizer
from kookabug_daemon.protocol import RequestFailed

if TYPE_CHECKING:
    from kookabug_daemon.app import Daemon
    from kookabug_daemon.methods import Call

__all__ = ["APPROVAL_TIMEOUT_S", "ApprovalBroker", "Pending", "scope_arg"]

log = logging.getLogger(__name__)

APPROVAL_TIMEOUT_S: Final = 120.0
PREVIEWABLE: Final = frozenset({"graph.patch", "graph.save", "graph.create"})

type Answer = Literal["allow_once", "allow_always", "allow_session", "deny"]
type Resolved = Literal[
    "allow_once", "allow_always", "allow_session", "deny", "timeout", "cancelled"
]
type State = Literal["waiting", "resolving", "done"]
type Scope = tuple[int, str, str, str]
"""이 탐색 동안 허용 범위: (연결, 세션 ID, 도구, 권한 인자 — screens는 빈 글자)."""

AUDIT_ARG_MAX: Final = 200
"""`explore.json` `approvals[].arg` 최대 길이 (explore 형식)."""


SESSION_EXCLUDED: Final = frozenset({"kb_app_launch"})
"""control이지만 "이 탐색 동안 허용"을 주지 않는 도구."""


def scope_arg(tool: str, arg: str) -> str | None:
    """`allow_session`을 쓸 수 있는 도구면 범위의 권한 인자, 아니면 None. control은 창 제목(그
    인자 그대로), screens 변경 도구는 도구 전체(빈 글자). 게임 실행(`kb_app_launch`)은 권한 인자가
    없어(빈 글자) 한 번 누르면 모든 프로필 실행이 지나가므로 대상이 아니다 (B3 검수 Low 3)."""
    info = TOOLS.get(tool)
    if info is None or tool in SESSION_EXCLUDED:
        return None
    if info.toolset == "control":
        return arg
    if info.toolset == "screens" and info.mutating:
        return ""
    return None


@dataclass(frozen=True, slots=True)
class Authorized:
    """집행한 판정과, 그것이 사람이 승인한 ask인지. 내부 실행 경로(`start_internal`·
    `start_decided`)까지 그대로 넘긴다 — 공개 RPC에는 승인 인자가 없다."""

    decision: Decision | None
    approved: bool = False
    scoped: bool = False
    """승인이 "이 탐색 동안 허용"(범위 또는 `allow_session` 답)에서 왔다 — 탐색 세션이 살아 있는
    동안만 유효하므로 실행 시작 직전에 세션을 다시 본다 (B3 검수 Mid 1)."""


def _timestamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"


@dataclass(eq=False, slots=True)
class Pending:
    id: str
    connection: int
    principal: Principal
    agent_name: str
    method: str
    tool: str
    arg: str
    params: Mapping[str, Any]
    summary: list[str]
    always_rule: str | None
    expires_at: str
    future: asyncio.Future[Answer] = field(repr=False)
    session: tuple[str, str] | None = None
    """`allow_session`을 쓸 수 있으면 요청 때 그 연결의 탐색 세션 (ID, 제목)."""
    state: State = "waiting"
    """waiting → (allow_always 응답) resolving → done. resolving인 동안 시간 초과·연결 끊김·다른
    응답은 이 요청을 끝내지 못한다(규칙 쓰기의 결과로만 끝난다). done이면 쓰기를 시작하지 않는다."""
    failure: RequestFailed | None = None
    """규칙 쓰기가 실패해 끝난 요청의 오류 (요청한 쪽이 받는다)."""

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "connection": self.connection,
            "agent": {"id": self.principal.id, "name": self.agent_name},
            "method": self.method,
            "tool": self.tool,
            "arg": self.arg,
            "summary": list(self.summary),
            "always_rule": self.always_rule,
            "previewable": self.method in PREVIEWABLE,
            "expires_at": self.expires_at,
            "session": (
                None if self.session is None else {"id": self.session[0], "title": self.session[1]}
            ),
        }


def _summary(method: str, arg: str, params: Mapping[str, Any]) -> list[str]:
    """카드에 보이는 요약 줄. 비밀값 원문을 싣지 않는다(입력 글자는 길이만)."""
    if method == "graph.patch":
        ops = list(params.get("ops") or [])
        kinds = Counter(str(op.get("op")) for op in ops)
        detail = ", ".join(f"{k} {n}" for k, n in sorted(kinds.items()))
        return [f"그래프 {arg} 고치기", f"연산 {len(ops)}개 ({detail})"]
    if method == "graph.save":
        return [f"그래프 {arg} 저장 (문서 전체)"]
    if method == "graph.create":
        ops = len(params.get("ops") or [])
        return [f"그래프 {arg} 새로 만들기 ({params.get('kind')})"] + (
            [f"연산 {ops}개"] if ops else []
        )
    if method == "target.save":
        return [f"찾기 대상 {arg} 저장"]
    if method == "run.start":
        return [f"그래프 {arg} 실행"]
    if method == "run.cancel":
        return [f"실행 취소 ({arg})"]
    if method == "control.click":
        where = params.get("target") or params.get("point")
        return [f"창 '{arg}' 클릭", f"위치 {where} · {params.get('button', 'left')}"]
    if method == "control.key":
        return [f"창 '{arg}'에 키 {params.get('keys')}"]
    if method == "control.type":
        if "secret" in params:
            return [f"창 '{arg}'에 비밀값 {params['secret']} 입력 (값은 보이지 않음)"]
        return [f"창 '{arg}'에 글자 {len(str(params.get('text', '')))}자 입력"]
    if method == "app.launch":
        return [f"게임 실행 (프로필 {params.get('profile') or '기본'})"]
    return [f"{METHOD_TOOLS.get(method, method)}({arg})"]


class ApprovalBroker:
    """확인 요청 표 (`approval.*`)."""

    def __init__(self, daemon: Daemon, authorizer: Authorizer, timeout_s: float) -> None:
        self.daemon = daemon
        self.authorizer = authorizer
        self.timeout_s = timeout_s
        self._pending: dict[str, Pending] = {}
        self._scopes: set[Scope] = set()
        """이 탐색 동안 허용 범위 (메모리에만 — 파일에 쓰지 않는다)."""
        self._spent: set[tuple[int, str]] = set()
        """예산을 다 쓴 (연결, 세션) — 범위를 새로 주지 않는다. 세션이 끝나면 지운다."""

    # ---------------------------------------------------------------- 판정 (요청 쪽)

    async def authorize(self, call: Call, arg: str) -> Authorized:
        """판정 → ask면 (이 탐색 동안 허용 범위가 아니면) 사람 확인 → 다시 판정(approved). 집행한
        판정과 승인 여부(`ui_only`면 판정 None). 승인 뒤 다시 판정한 결과는 여전히 `final: ask`
        이므로 `approved`를 함께 넘긴다. deny는 첫 판정에서 끝나므로 범위가 deny 규칙을 넘지
        못한다."""
        try:
            decision = await asyncio.to_thread(
                self.authorizer.require, call.principal, call.method, arg
            )
            return Authorized(decision)
        except RequestFailed as failed:
            if failed.code != "approval_required":
                raise
            if self._in_scope(call, arg):
                log.info("이 탐색 동안 허용: %s(%s) — %s", call.method, arg, call.principal.id)
                scoped = True
            else:
                scoped = await self._ask(call, arg, failed) == "allow_session"
        decision = await asyncio.to_thread(
            self.authorizer.require, call.principal, call.method, arg, approved=True
        )
        return Authorized(decision, approved=True, scoped=scoped)

    async def approve(self, call: Call, arg: str) -> bool:
        """스스로 판정하는 메서드(`run.start`)용: 판정을 **보기만** 하고(집행 아님), ask면 사람
        확인을 받고 True. 허용·거부면 False. 집행하는 판정은 메서드가 제자리(시작 잠금 안 ②)에서
        한 번 한다 — 거부의 오류 순서도 그대로다."""
        peek = await asyncio.to_thread(self.authorizer.peek, call.principal, call.method, arg)
        if peek is None or peek.final != "ask":
            return False
        failed = RequestFailed(
            "approval_required",
            peek.describe(METHOD_TOOLS[call.method]),
            decision=peek.to_dict(),
        )
        await self._ask(call, arg, failed)
        return True

    async def _ask(self, call: Call, arg: str, failed: RequestFailed) -> Answer:
        principal = call.principal
        found = failed.fields.get("decision")
        decision: dict[str, Any] = {} if found is None else {"decision": found}
        if principal.kind != "agent" or not principal.attended:
            raise failed  # decide가 사람 없는 ask를 deny로 바꾸므로 오지 않는다 (방어)
        if not self.daemon.ui_attached():
            raise RequestFailed(
                "approval_required",
                f"{failed.message} — 확인할 사람이 없다 (Kookabug 앱이 열려 있지 않다)",
                reason="no_approver",
                **decision,
            )
        tool = METHOD_TOOLS[call.method]
        always: str | None = None
        if TOOLS[tool].toolset != "control":
            with contextlib.suppress(ValueError):
                always = exact_rule(tool, arg)
        session: tuple[str, str] | None = None
        if scope_arg(tool, arg) is not None:
            active = self.daemon.explore.get(call.connection)
            # 예산을 다 쓴 세션에는 범위를 새로 주지 않는다 (단추 없음)
            if active is not None and (call.connection, active.id) not in self._spent:
                session = (active.id, active.title)
        now = datetime.now(UTC)
        pending = Pending(
            id=f"ap_{secrets.token_hex(8)}",
            connection=call.connection,
            principal=principal,
            agent_name=self.daemon.connection_name(call.connection),
            method=call.method,
            tool=tool,
            arg=arg,
            params=dict(call.params),
            summary=_summary(call.method, arg, call.params),
            always_rule=always,
            expires_at=_timestamp(now + timedelta(seconds=self.timeout_s)),
            future=asyncio.get_running_loop().create_future(),
            session=session,
        )
        self._pending[pending.id] = pending
        log.info("확인 요청 %s: %s(%s) — %s", pending.id, tool, arg, principal.id)
        self.daemon.notify_ui("approval.requested", pending.to_json())
        try:
            try:
                answer = await asyncio.wait_for(asyncio.shield(pending.future), self.timeout_s)
            except TimeoutError:
                if pending.state != "resolving":
                    self._resolve(pending, "timeout", "daemon")
                    raise RequestFailed(
                        "approval_timeout",
                        f"{self.timeout_s:g}초 안에 사람이 답하지 않았다 ({tool})",
                        **decision,
                    ) from None
                # "항상 허용" 규칙을 쓰는 중: 시간 초과로 끝내지 않고 그 결과를 기다린다
                answer = await asyncio.shield(pending.future)
        except asyncio.CancelledError:
            # 요청 연결이 끊겼다. 규칙을 쓰는 중이면 그 결과가 요청을 끝낸다 (카드도 그쪽이 닫음)
            if pending.state == "waiting":
                self._resolve(pending, "cancelled", "daemon")
            raise
        if pending.failure is not None:
            raise pending.failure
        if answer == "deny":
            raise RequestFailed("approval_denied", f"사람이 거부했다 ({tool})", **decision)
        return answer

    def _resolve(self, pending: Pending, verdict: Resolved, by: str) -> None:
        """요청을 끝낸다 (이벤트 루프 안 — 상태 전이는 await 없이 한 번에 한다)."""
        if pending.state == "done":
            return
        pending.state = "done"
        self._pending.pop(pending.id, None)
        self.daemon.notify_ui("approval.resolved", {"id": pending.id, "verdict": verdict, "by": by})

    # ---------------------------------------------------------------- 답 (ui 쪽)

    def list(self) -> list[dict[str, Any]]:
        return [p.to_json() for p in self._pending.values()]

    def _get(self, approval_id: str) -> Pending:
        """답을 받을 수 있는(waiting) 요청. 끝났거나 규칙을 쓰는 중이면 not_found."""
        pending = self._pending.get(approval_id)
        if pending is None or pending.state != "waiting":
            raise RequestFailed("not_found", f"확인 요청 {approval_id}이(가) 없다 (이미 끝남)")
        return pending

    async def respond(self, approval_id: str, verdict: Answer, by: str) -> None:
        # 이벤트 루프 하나에서만 돈다: 아래 상태 확인·전이는 await 전에 끝나므로 시간 초과·끊김·
        # 다른 응답과 겹치지 않는다 (broker 잠금 역할)
        pending = self._get(approval_id)
        if pending.session is not None and self._session_of(pending) is None:
            # 요청 뒤 그 탐색 세션이 끝났다 (범위 소멸 알림이 아직 오지 않았어도): 늦은 답은
            # 아무것도 허락하지 않는다
            self._cancel(pending)
            raise RequestFailed(
                "not_found", f"확인 요청 {approval_id}은(는) 탐색 세션이 끝나 취소됐다"
            )
        if verdict == "allow_session":
            await self._allow_session(pending, by)
            return
        if verdict != "allow_always":
            pending.future.set_result(verdict)
            self._resolve(pending, verdict, by)
            return
        if TOOLS[pending.tool].toolset == "control" or pending.always_rule is None:
            raise RequestFailed(
                "always_not_allowed",
                f"{pending.tool}에는 '항상 허용'을 쓸 수 없다 (게임 조작은 매번 확인)",
            )
        pending.state = "resolving"
        rule = pending.always_rule
        write = asyncio.ensure_future(
            asyncio.to_thread(self.daemon.permission_files.add_rule, "project", rule)
        )

        def finish(done: asyncio.Future[str]) -> None:
            # 쓰기의 실제 결과로만 요청을 끝낸다 (응답한 UI 연결이 그 사이 끊겨도)
            failed = None if done.cancelled() else done.exception()
            if failed is None and not done.cancelled():
                log.info("항상 허용 규칙을 더했다: %s", rule)
                pending.future.set_result("allow_always")
                self._resolve(pending, "allow_always", by)
                return
            # 쓰지 못했다(파일 바이트 그대로): 요청은 그 오류로 끝난다
            if not isinstance(failed, RequestFailed):
                log.error("항상 허용 규칙을 쓰지 못했다: %r", failed)
                failed = RequestFailed("io_error", "규칙을 쓰지 못했다", message=str(failed))
            pending.failure = failed
            pending.future.set_result("deny")
            self._resolve(pending, "cancelled", "daemon")

        write.add_done_callback(finish)
        await asyncio.shield(write)

    # ---------------------------------------------------------------- 이 탐색 동안 허용

    def scopes(self) -> frozenset[Scope]:
        """지금 살아 있는 범위 (진단·검사용 사본)."""
        return frozenset(self._scopes)

    def spent(self) -> frozenset[tuple[int, str]]:
        """예산을 다 써 범위를 새로 주지 않는 (연결, 세션) (진단·검사용 사본)."""
        return frozenset(self._spent)

    def _in_scope(self, call: Call, arg: str) -> bool:
        tool = METHOD_TOOLS[call.method]
        found = scope_arg(tool, arg)
        if found is None or call.principal.kind != "agent" or not call.principal.attended:
            return False
        session = self.daemon.explore.get(call.connection)
        return session is not None and (call.connection, session.id, tool, found) in self._scopes

    def _session_of(self, pending: Pending) -> ExploreSession | None:
        """요청 때의 탐색 세션이 아직 그 연결의 세션이면 그 세션, 아니면 None."""
        if pending.session is None:
            return None
        return self.daemon.explore.live(pending.connection, pending.session[0])

    async def _allow_session(self, pending: Pending, by: str) -> None:
        found = scope_arg(pending.tool, pending.arg)
        if pending.session is None or found is None:
            raise RequestFailed(
                "session_not_allowed",
                f"{pending.tool} 요청에는 '이 탐색 동안 허용'을 쓸 수 없다 "
                "(요청 연결에 탐색 세션이 없거나 게임 조작·화면 지도 저장 도구가 아니다)",
            )
        if (pending.connection, pending.session[0]) in self._spent:
            # 대기 중 예산을 다 써 범위가 사라진 세션: 범위를 다시 만들지 않는다 (B3 검수 Low 4)
            raise RequestFailed(
                "session_not_allowed",
                "탐색 스텝 예산을 다 써 '이 탐색 동안 허용'을 쓸 수 없다 (한 번 허용·거부만)",
            )
        # 감사 기록 한 줄 (창 제목은 글자 검사를 지날 때만 — 비밀값 제공자를 읽으므로 루프 밖에서)
        entry = await asyncio.to_thread(self._audit_entry, pending.tool, found)
        # 기다리는 사이 세션이 끝났거나 요청이 끝났으면(시간 초과·끊김) 아무것도 허락하지 않는다
        session = self._session_of(pending)
        if pending.state != "waiting":
            raise RequestFailed("not_found", f"확인 요청 {pending.id}이(가) 없다 (이미 끝남)")
        if session is None:
            self._cancel(pending)
            raise RequestFailed(
                "not_found", f"확인 요청 {pending.id}은(는) 탐색 세션이 끝나 취소됐다"
            )
        self.daemon.explore.note_approval(session, entry)
        self._scopes.add((pending.connection, session.id, pending.tool, found))
        log.info("이 탐색 동안 허용: %s(%s) — 세션 %s", pending.tool, found, session.id)
        pending.future.set_result("allow_session")
        self._resolve(pending, "allow_session", by)
        await asyncio.to_thread(self.daemon.explore.flush, session)

    def _audit_entry(self, tool: str, arg: str) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "tool": tool,
            "scope": "session",
            "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if arg and len(arg) <= AUDIT_ARG_MAX:
            try:
                check_texts(
                    [("arg", arg)],
                    self.daemon.guard,
                    self.daemon.root,
                    job_secrets(self.daemon),
                )
            except RequestFailed:
                pass  # 비밀값이 들었거나 검사할 수 없다: 창 제목을 적지 않는다
            else:
                entry["arg"] = arg
        return entry

    def scope_ended(self, connection: int, session_id: str, reason: str) -> None:
        """탐색 세션 끝·연결 끊김·예산 다 씀 (이벤트 루프 안): 그 세션의 범위를 지운다. 끝·끊김이면
        그 세션에 걸린 대기 요청도 `cancelled`로 끝낸다(늦은 답으로 범위가 생기지 않는다)."""
        dropped = {s for s in self._scopes if s[0] == connection and s[1] == session_id}
        self._scopes -= dropped
        if dropped:
            log.info(
                "이 탐색 동안 허용 범위 %d개를 지웠다 (세션 %s, %s)",
                len(dropped),
                session_id,
                reason,
            )
        if reason == "budget":
            self._spent.add((connection, session_id))
            return
        self._spent.discard((connection, session_id))
        for pending in list(self._pending.values()):
            if (
                pending.connection == connection
                and pending.session is not None
                and pending.session[0] == session_id
            ):
                self._cancel(pending)

    def _cancel(self, pending: Pending) -> None:
        """탐색 세션이 끝나 대기 요청을 취소한다. 규칙을 쓰는 중(resolving)이면 그 결과가 끝낸다."""
        if pending.state != "waiting":
            return
        pending.failure = RequestFailed(
            "approval_cancelled", f"탐색 세션이 끝나 확인 요청을 취소했다 ({pending.tool})"
        )
        pending.future.set_result("deny")
        self._resolve(pending, "cancelled", "daemon")

    async def preview(self, approval_id: str) -> dict[str, Any]:
        """승인하면 쓰일 그래프 값 (쓰지 않는다)."""
        pending = self._get(approval_id)
        if pending.method not in PREVIEWABLE:
            raise RequestFailed("not_found", f"{pending.tool} 요청은 미리 볼 그래프가 없다")
        return await asyncio.to_thread(self._preview_sync, pending)

    def _preview_sync(self, pending: Pending) -> dict[str, Any]:
        params = pending.params
        registry = self.daemon.checker.registry
        try:
            if pending.method == "graph.save":
                return {
                    "path": pending.arg,
                    "revision": str(params["base_revision"]),
                    "value": dict(params["value"]),
                }
            ops = list(params.get("ops") or [])
            if pending.method == "graph.create":
                title = params.get("title")
                value = core_documents.template(
                    params["kind"], None if title is None else str(title)
                )
                revision = None
            else:
                doc = core_documents.open(self.daemon.root / pending.arg)
                value, revision = doc.value, doc.revision
            if ops:
                value = apply_ops(value, ops, registry).value
            return {"path": pending.arg, "revision": revision, "value": value}
        except PatchInvalid as exc:
            raise RequestFailed("patch_invalid", str(exc), index=exc.index) from exc
        except DocumentError as exc:
            text = str(exc)
            raise RequestFailed("io_error", text, message=text) from exc
