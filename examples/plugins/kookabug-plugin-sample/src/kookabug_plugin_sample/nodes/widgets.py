"""설정 값 노드와 창 노드."""

from kookabug_sdk import Config, Context, Exit, Result, node
from kookabug_sdk.types import WindowRef


@node(
    type="sample.color.pick",
    version=1,
    title="색 고르기",
    category="sample",
    config={"color": Config(str, default="#3366ff", description="색 (#rrggbb)")},
    exits=[Exit("done", "ok")],
    outputs={"color": str},
)
def pick(ctx: Context) -> Result:
    """설정한 색을 출력한다."""
    return Result.ok("done", color=str(ctx.config["color"]))


@node(
    type="sample.window.title",
    version=1,
    title="창 제목",
    category="sample",
    exits=[Exit("done", "ok")],
    outputs={"title": str},
    effects={"capture"},
)
def window_title(ctx: Context, window: WindowRef) -> Result:
    """창 제목을 읽는다."""
    return Result.ok("done", title=ctx.windows.info(window).title)
