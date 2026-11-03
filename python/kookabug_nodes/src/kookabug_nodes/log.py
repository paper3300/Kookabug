"""기록 노드."""

from typing import Literal

from kookabug_sdk import Context, Exit, Result, Secret, node


@node(
    type="core.log.message",
    version=1,
    title="메시지 기록",
    category="log",
    exits=[Exit("done", "ok")],
)
def log_message(
    ctx: Context, text: str | Secret, level: Literal["info", "warn", "error"] = "info"
) -> Result:
    """실행 기록에 메시지를 남긴다. 비밀값은 워크스페이스 `record.redact_secrets`가 켜져 있을 때만
    가려서 남긴다."""
    # 비밀값은 비밀값 그대로 ctx.log에 준다 — 가릴지는 실행 기록 쪽이 기록 정책으로 정한다
    message = text
    if level == "info":
        ctx.log.info(message)
    elif level == "warn":
        ctx.log.warn(message)
    elif level == "error":
        ctx.log.error(message)
    else:
        raise ValueError(f"모르는 level {level!r}")
    return Result.ok("done")
