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
    """실행 기록에 메시지를 남긴다. 비밀값은 가려서 남긴다."""
    # 기록 구현이 무엇이든 비밀값 원문이 넘어가지 않게 여기서 가린다 (str(Secret) = 가린 값)
    message = str(text)
    if level == "info":
        ctx.log.info(message)
    elif level == "warn":
        ctx.log.warn(message)
    elif level == "error":
        ctx.log.error(message)
    else:
        raise ValueError(f"모르는 level {level!r}")
    return Result.ok("done")
