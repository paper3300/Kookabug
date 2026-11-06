"""Agent 판단 노드 (MVP 노드 목록 10장, M5 계획 3.11): 스크린샷과 질문을 주고 선택지 중 하나를
고르게 한다. 결정적이지 않다(편집기 "비결정" 배지).

- `config.choices`(글자 1~16개)가 그대로 출구가 되고, 선택지 밖·읽을 수 없는 답은 `unsure`(U9)
- 시간 초과(`timeout_ms`, 기본 60초)·에이전트 시작 실패·프로토콜 오류·HTTP 오류는 출구가 아니라
  `error`다 (`agent_timeout`·`agent_start_failed`·`agent_protocol_error`·`api_http_error` 등)
- 판단 에이전트에는 아무 도구도 주지 않는다: cli는 MCP 서버 없음·파일·터미널 능력 없음·권한 요청
  거절, api는 요청에 도구 정의가 없다
- 호출은 runner의 실행 ctx(`judge`)가 한다. 그것이 없는 ctx(워커·노드 단위 가짜 ctx)에서는
  `not_supported`
"""

from typing import Annotated, Any

from kookabug_sdk import (
    Config,
    Context,
    DynamicExits,
    Exit,
    Input,
    Result,
    RunnerError,
    Secret,
    node,
)
from kookabug_sdk.types import Image

_UNSURE = Exit("unsure", "fail", outputs=["answer", "reason"])


def _judge(ctx: Context, **request: Any) -> Result:
    seen: Any = ctx
    while seen is not None:
        judge = getattr(type(seen), "judge", None)
        if callable(judge):
            got = seen.judge(**request)
            break
        seen = getattr(seen, "inner", None)
    else:
        raise RunnerError("not_supported", "판단 노드는 runner의 core 노드로만 실행한다")
    exit_name = got["exit"]
    outputs = {"answer": got["answer"], "reason": got["reason"]}
    if exit_name == "unsure":
        return Result.fail(
            "unsure", f"선택지 밖이거나 읽을 수 없는 답이다: {got['reason']}", **outputs
        )
    return Result.ok(exit_name, **outputs)


@node(
    type="core.agent.cli_judge",
    version=1,
    title="Agent 판단 · CLI",
    category="agent",
    config={
        "choices": Config(list[str], min_items=1, description="선택지 (출구 이름, 1~16개)"),
        "agent": Config(str, default="", description="사용자 설정의 에이전트 ID (빈 값 = 기본)"),
    },
    exits=DynamicExits(from_config="choices", kind="ok", extra=[_UNSURE]),
    outputs={"answer": str, "reason": str},
)
def cli_judge(
    ctx: Context,
    prompt: str,
    image: Image | None = None,
    timeout_ms: Annotated[int, Input(minimum=1)] = 60000,
) -> Result:
    """사용자 설정의 에이전트 CLI를 도구 없이 따로 띄워 `image`와 `prompt`를 주고, 선택지 중
    하나를 고르게 한다. 고른 선택지의 출구로 나간다."""
    return _judge(
        ctx,
        kind="cli",
        prompt=prompt,
        image=image,
        choices=list(ctx.config["choices"]),
        timeout_ms=timeout_ms,
        agent=ctx.config.get("agent") or None,
    )


@node(
    type="core.agent.api_judge",
    version=1,
    title="Agent 판단 · API",
    category="agent",
    config={
        "choices": Config(list[str], min_items=1, description="선택지 (출구 이름, 1~16개)"),
        "provider": Config(
            str,
            default="anthropic",
            enum=["anthropic", "openai_compatible"],
            description="API 모양 (Anthropic Messages / OpenAI 호환 Chat Completions)",
        ),
        "endpoint": Config(
            str, default="", description="API 주소 (빈 값 = 공급자 기본, https만 — http는 이 PC만)"
        ),
    },
    exits=DynamicExits(from_config="choices", kind="ok", extra=[_UNSURE]),
    outputs={"answer": str, "reason": str},
)
def api_judge(
    ctx: Context,
    prompt: str,
    model: str,
    api_key: Secret,
    image: Image | None = None,
    timeout_ms: Annotated[int, Input(minimum=1)] = 60000,
) -> Result:
    """모델 API를 직접 불러 `image`와 `prompt`를 주고, 선택지 중 하나를 고르게 한다. `api_key`는
    비밀값(`$secret`)만 받는다."""
    return _judge(
        ctx,
        kind="api",
        prompt=prompt,
        image=image,
        choices=list(ctx.config["choices"]),
        timeout_ms=timeout_ms,
        provider=ctx.config["provider"],
        endpoint=ctx.config.get("endpoint") or None,
        model=model,
        api_key=api_key,
    )
