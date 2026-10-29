"""그래프 경계 노드. 실행기가 직접 처리한다 (`engine=`)."""

from kookabug_sdk import Config, Context, Exit, FromInterface, Result, node


@node(
    type="core.graph.entry",
    version=1,
    title="시작",
    category="graph",
    outputs=FromInterface("inputs"),
    exits=[Exit("start", "ok")],
    engine="graph_entry",
)
def entry(ctx: Context) -> Result:
    """그래프 시작점. 서브그래프면 `interface.inputs`가 출력 핀이 된다."""
    raise NotImplementedError


@node(
    type="core.graph.exit",
    version=1,
    title="공개 출구",
    category="graph",
    inputs=FromInterface("outputs"),
    exits=[],
    config={"exit": Config(str, description="나갈 `interface.exits` 이름")},
    engine="graph_exit",
)
def exit_(ctx: Context) -> Result:
    """서브그래프를 끝내고 공개 출구로 나간다. 입력 핀은 `interface.outputs`다."""
    raise NotImplementedError


@node(
    type="core.graph.call",
    version=1,
    title="서브그래프 호출",
    category="graph",
    inputs=FromInterface("inputs"),
    outputs=FromInterface("outputs"),
    exits=FromInterface("exits"),
    config={"graph": Config(str, description="부를 서브그래프 경로 (워크스페이스 기준)")},
    engine="graph_call",
)
def call(ctx: Context) -> Result:
    """서브그래프를 새 호출 프레임에서 실행한다. 핀·출구는 서브그래프 `interface`에서 만든다."""
    raise NotImplementedError
