"""위젯 탐침 노드. config `result`의 위젯이 시도 결과를 값으로 써 넣는다 (ui/index.js)."""

from kookabug_sdk import Config, Context, Widget, node


def _probe(name: str, title: str) -> dict[str, Config]:
    return {"result": Config(str, default="", description=title, ui=Widget(name))}


@node(
    type="widget_probe.probe.fetch",
    version=1,
    title="fetch 탐침",
    pure=True,
    config=_probe("fetch", "fetch할 주소 → 결과"),
    outputs={"result": str},
)
def probe_fetch(ctx: Context) -> dict[str, str]:
    return {"result": str(ctx.config["result"])}


@node(
    type="widget_probe.probe.nav",
    version=1,
    title="이동 탐침",
    pure=True,
    config=_probe("nav", "이동할 주소 → 결과"),
    outputs={"result": str},
)
def probe_nav(ctx: Context) -> dict[str, str]:
    return {"result": str(ctx.config["result"])}


@node(
    type="widget_probe.probe.other",
    version=1,
    title="다른 플러그인 탐침",
    pure=True,
    config=_probe("other", "다른 플러그인 모듈 주소 → 결과"),
    outputs={"result": str},
)
def probe_other(ctx: Context) -> dict[str, str]:
    return {"result": str(ctx.config["result"])}
