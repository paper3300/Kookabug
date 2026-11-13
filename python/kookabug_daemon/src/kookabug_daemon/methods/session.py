"""`session.hello`·`daemon.shutdown` (M2 계획 2.3·2.4).

`session.hello`는 연결의 첫 메시지다. 판단 순서:

1. 토큰을 상수 시간으로 비교한다. 틀리면 `unauthenticated` (전송이 연결을 닫는다)
2. `protocol`이 다르면 `protocol_mismatch`(`protocol` = daemon 판). 연결은 닫지 않고
   `daemon.shutdown`만 받는다 — 앱이 판이 다른 daemon을 "다시 시작"할 수 있어야 하기
   때문이다 (2.3 "프로토콜 판"). 그래서 토큰·판은 params 전체 형식 검사보다 먼저 본다
3. params 형식이 틀리면 `invalid_params` (연결을 닫는다)
4. `client.job_token`이 있으면 작업 토큰을 확인한다(M8 R7). 틀리면 `job_token_invalid` (연결을
   닫는다). 토큰이 없는데 끝나지 않은 작업에 예약된 Agent ID(`job:<작업>`)면 같은 거부 (UX5)
5. 주체를 정하고 결과를 돌려준다
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from kookabug_core.diagnostics import Diagnostic
from kookabug_core.permissions import Principal
from kookabug_core.schema import check_shape
from kookabug_daemon.jobs import JobRegistry, job_namespace, plain_ascii_id
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.principal import principal_json, principal_of
from kookabug_daemon.protocol import DAEMON_VERSION, PROTOCOL, RequestFailed, params_problems

__all__ = ["METHODS", "HelloOutcome", "InvalidHello", "hello"]

# 판이 다른 연결의 주체를 client에서 정할 수 없을 때: 가장 좁은 주체 (shutdown도 못 함)
_UNKNOWN_AGENT: Final = Principal("agent", "unknown", attended=False)


class InvalidHello(Exception):
    """hello params 형식이 틀렸다 (-32602)."""

    def __init__(self, problems: list[Diagnostic]) -> None:
        super().__init__("session.hello params 형식이 틀렸다")
        self.problems = problems


@dataclass(frozen=True, slots=True)
class HelloOutcome:
    """인증된 연결. `mismatch`가 있으면 판이 달라 `daemon.shutdown`만 받는다."""

    principal: Principal
    result: dict[str, Any] | None
    mismatch: RequestFailed | None = None
    client_kind: str = "agent"
    """`client.kind` (`ui`·`agent`). 사람이 UI에서 시작한 실행을 가리는 데 쓴다(M3 2.1) — 주체
    `kind`(`user`)로 판정하지 않는다."""
    client_name: str = ""
    """`client.name` (에이전트 연결 목록 표시용, M5)."""


def hello(
    params: Any,
    *,
    token: str,
    start_id: str,
    workspace: str,
    connection: int,
    jobs: JobRegistry | None = None,
) -> HelloOutcome:
    given = params.get("token") if isinstance(params, dict) else None
    if not isinstance(given, str) or not hmac.compare_digest(
        given.encode("utf-8"), token.encode("utf-8")
    ):
        raise RequestFailed("unauthenticated", "토큰이 틀렸다", protocol=PROTOCOL)
    assert isinstance(params, dict)
    fields: dict[str, Any] = params
    protocol = fields.get("protocol")
    if isinstance(protocol, bool) or protocol != PROTOCOL:
        client: Any = fields.get("client")
        valid_client = not check_shape(client, "daemon-rpc", ref="#/$defs/ClientInfo")
        principal = principal_of(client, connection) if valid_client else _UNKNOWN_AGENT
        mismatch = RequestFailed(
            "protocol_mismatch",
            f"프로토콜 판이 다르다: 클라이언트 {protocol!r}, daemon {PROTOCOL}. "
            "daemon.shutdown만 받는다",
            protocol=PROTOCOL,
        )
        kind = str(client["kind"]) if valid_client else "agent"
        return HelloOutcome(principal, None, mismatch, client_kind=kind)
    if problems := params_problems("session.hello", fields):
        raise InvalidHello(problems)
    client = fields["client"]
    job: str | None = None
    if "job_token" in client:
        # 작업 토큰 (M8 R7): 살아 있는 작업·같은 주체일 때만 묶는다. 아니면 연결을 닫는다
        if jobs is None:
            raise RequestFailed("job_token_invalid", "이 daemon은 작업 토큰을 받지 않는다")
        job = jobs.bind(str(client["job_token"]), str(client["id"])).id
    elif client["kind"] == "agent":
        # 작업 토큰 없는 Agent 연결 (UX5 검수 1~3 High: 작업 ID를 대소문자·공백·닮은 문자로 바꿔
        # 붙으면 작업 밖 연결로 보여 작업 질문 규칙을 피한다). ID를 공백 없는 출력 가능 ASCII로
        # 한정해 닮은 문자 변형을 통째로 없애고, 작업 주체 이름공간(`job:`)은 토큰으로만 붙게 한다
        agent_id = str(client["id"])
        if not plain_ascii_id(agent_id):
            raise RequestFailed(
                "job_token_invalid", "작업 토큰 없는 Agent ID는 공백 없는 ASCII 글자만 쓴다"
            )
        if job_namespace(agent_id):
            raise RequestFailed(
                "job_token_invalid", "작업 Agent ID(job:…)는 작업 토큰 없이 붙을 수 없다"
            )
    principal = principal_of(client, connection, job)
    return HelloOutcome(
        principal,
        {
            "protocol": PROTOCOL,
            "daemon_version": DAEMON_VERSION,
            "start_id": start_id,
            "workspace": workspace,
            "principal": principal_json(principal),
        },
        client_kind=str(fields["client"]["kind"]),
        client_name=str(fields["client"]["name"]),
    )


async def _shutdown(call: Call) -> dict[str, Any]:
    params: Mapping[str, Any] = call.params
    force = bool(params.get("force", False))
    # 실행 중·시작 중 확인과 종료 결정은 시작 예약과 같은 잠금 안에서 한 번에 한다
    active = call.daemon.runs.reserve_shutdown(force=force)
    if active is not None:
        raise RequestFailed(
            "run_active",
            f"진행 중인 실행 {active}이(가) 있다. force면 실행을 취소하고 끝낸다",
            run_id=active,
        )
    call.daemon.request_shutdown(force=force, reason="daemon.shutdown")
    return {}


METHODS: Final = {"daemon.shutdown": MethodSpec(_shutdown)}
"""`session.hello`는 전송이 첫 메시지로 따로 처리한다 (인증 전이라 일반 경로를 지나지 않는다)."""
