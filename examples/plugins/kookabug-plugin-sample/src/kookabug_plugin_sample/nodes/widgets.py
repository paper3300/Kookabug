"""설정 값 노드와 창 노드."""

from kookabug_sdk import Config, Context, Exit, Result, Widget, node
from kookabug_sdk.types import WindowRef


@node(
    type="sample.color.pick",
    version=1,
    title="색 고르기",
    category="sample",
    # 인스펙터에서 색 위젯(ui/index.js의 "color")으로 고친다
    config={
        "color": Config(str, default="#3366ff", description="색 (#rrggbb)", ui=Widget("color"))
    },
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
