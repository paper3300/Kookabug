from typing import Annotated, Any, Literal

import pytest

from kookabug_sdk import (
    Config,
    Context,
    DynamicExits,
    Exit,
    FromInterface,
    Input,
    NodeContractError,
    NodeDeclarationError,
    Output,
    Result,
    node,
)
from kookabug_sdk.testing import fake_context
from kookabug_sdk.types import Match, Rect, Target

MATCH = Match(Rect(1, 2, 3, 4), 0.9)


@node(
    type="sample.image.wait",
    version=1,
    title="이미지 대기",
    category="image",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"match": Match, "score": Output(float, nullable=True, description="점수")},
    effects={"capture"},
)
def wait_image(
    ctx: Context,
    target: Target,
    timeout_ms: Annotated[int, Input(minimum=0, description="제한 시간")] = 10000,
    label: str | None = None,
) -> Result:
    """대상이 나타날 때까지 기다린다.

    두 번째 문단."""
    return Result.ok("found", match=MATCH)


def returning(result: Any) -> Any:
    """주어진 결과를 그대로 돌려주는 sample.image.wait 선언의 노드."""

    @node(
        type="sample.image.wait",
        version=1,
        title="이미지 대기",
        exits=[
            Exit("found", "ok"),
            Exit("partial", "fail", outputs=["match"]),
            Exit("timeout", "fail"),
        ],
        outputs={"match": Match, "score": Output(float, nullable=True)},
    )
    def fn(ctx: Context) -> Any:
        return result

    return fn


def test_signature_becomes_inputs_with_defaults() -> None:
    schema = wait_image.schema()
    assert schema["inputs"] == {
        "target": {"type": "target"},
        "timeout_ms": {"type": "int", "default": 10000, "minimum": 0, "description": "제한 시간"},
        "label": {"type": "string", "nullable": True, "default": None},
    }
    assert [p.name for p in wait_image.spec.inputs if p.required] == ["target"]  # type: ignore[union-attr]
    assert schema["outputs"] == {
        "match": {"type": "match"},
        "score": {"type": "float", "nullable": True, "description": "점수"},
    }
    assert schema["effects"] == ["capture"]


def test_signature_errors() -> None:
    with pytest.raises(NodeDeclarationError, match="타입 힌트가 없다"):

        @node(type="sample.a.b", version=1, title="t", exits=[Exit("ok", "ok")])
        def no_hint(ctx: Context, x) -> Result:  # type: ignore[no-untyped-def]
            return Result.ok("ok")

    with pytest.raises(NodeDeclarationError, match=r"\*args"):

        @node(type="sample.a.b", version=1, title="t", exits=[Exit("ok", "ok")])
        def var_args(ctx: Context, *xs: int) -> Result:
            return Result.ok("ok")

    with pytest.raises(NodeDeclarationError, match="기본값 None"):

        @node(type="sample.a.b", version=1, title="t", exits=[Exit("ok", "ok")])
        def bad_default(ctx: Context, x: int = None) -> Result:  # type: ignore[assignment]  # noqa: RUF013
            return Result.ok("ok")

    with pytest.raises(NodeDeclarationError, match="JSON 값이 아니다"):

        @node(type="sample.a.b", version=1, title="t", exits=[Exit("ok", "ok")])
        def bad_json(ctx: Context, x: Any = object()) -> Result:  # noqa: B008
            return Result.ok("ok")

    with pytest.raises(NodeDeclarationError, match="type은"):

        @node(type="Sample.a", version=1, title="t", exits=[Exit("ok", "ok")])
        def bad_type(ctx: Context) -> Result:
            return Result.ok("ok")

    with pytest.raises(NodeDeclarationError, match="exits를 선언"):

        @node(type="sample.a.b", version=1, title="t")
        def no_exits(ctx: Context) -> Result:
            return Result.ok("ok")


def test_docstring_becomes_description() -> None:
    assert wait_image.schema()["description"] == "대상이 나타날 때까지 기다린다.\n\n두 번째 문단."

    @node(type="sample.a.b", version=1, title="t", exits=[Exit("ok", "ok")])
    def undocumented(ctx: Context) -> Result:
        return Result.ok("ok")

    assert "description" not in undocumented.schema()


def test_undeclared_exit_is_error() -> None:
    with pytest.raises(NodeContractError, match="선언하지 않은 출구 'nope'"):
        returning(Result.ok("nope"))(fake_context())
    with pytest.raises(NodeContractError, match="fail 출구"):
        returning(Result.ok("timeout"))(fake_context())
    with pytest.raises(NodeContractError, match=r"Result\.ok/fail"):
        returning({"match": MATCH})(fake_context())


def test_undeclared_output_is_error() -> None:
    with pytest.raises(NodeContractError, match="선언하지 않은 출력 'extra'"):
        returning(Result.ok("found", match=MATCH, extra=1))(fake_context())
    with pytest.raises(NodeContractError, match="이 출구가 주지 않는다"):
        returning(Result.fail("timeout", match=MATCH))(fake_context())
    with pytest.raises(NodeContractError, match=r"'match'이\(가\) 빠졌다"):
        returning(Result.ok("found"))(fake_context())


def test_exit_default_outputs_ok_all_fail_none() -> None:
    assert wait_image.schema()["exits"] == [
        {"kind": "ok", "name": "found", "outputs": ["match", "score"]},
        {"kind": "fail", "name": "timeout", "outputs": []},
    ]
    result = wait_image(fake_context(), Target("t"))
    assert result.exit == "found"
    assert result.kind == "ok"
    assert result.outputs == {"match": MATCH, "score": None}  # nullable 출력은 None으로 채움
    assert returning(Result.fail("timeout", message="안 보임"))(fake_context()).message == "안 보임"


def test_exit_explicit_outputs() -> None:
    fn = returning(None)
    assert fn.schema()["exits"][1] == {"kind": "fail", "name": "partial", "outputs": ["match"]}
    assert returning(Result.fail("partial", match=MATCH))(fake_context()).outputs == {
        "match": MATCH
    }
    with pytest.raises(NodeDeclarationError, match="선언하지 않은 출력"):

        @node(
            type="sample.a.b",
            version=1,
            title="t",
            exits=[Exit("ok", "ok", outputs=["nope"])],
            outputs={"x": int},
        )
        def bad(ctx: Context) -> Result:
            return Result.ok("ok")


@node(
    type="sample.image.wait_any",
    version=1,
    title="여러 대상 중 먼저 보이는 것",
    config={"exits": Config(list[str], min_items=2)},
    exits=DynamicExits(from_config="exits", kind="ok", extra=[Exit("timeout", "fail")]),
    outputs={"match": Match},
    effects={"capture"},
)
def wait_any(ctx: Context, targets: dict[str, Target], timeout_ms: int = 10000) -> Result:
    name = next(iter(targets))
    if name == "none":
        return Result.fail("timeout")
    return Result.ok(name, match=MATCH)


def test_dynamic_exits_from_config() -> None:
    schema = wait_any.schema()
    assert schema["config"] == {"exits": {"type": "list[string]", "min_items": 2}}
    assert schema["exits"] == {
        "extra": [{"kind": "fail", "name": "timeout", "outputs": []}],
        "from_config": "exits",
        "kind": "ok",
        "outputs": ["match"],
    }
    ctx = fake_context(config={"exits": ["lobby", "error"]})
    assert wait_any(ctx, {"lobby": Target("l")}).exit == "lobby"
    assert wait_any(ctx, {"none": Target("n")}).exit == "timeout"
    with pytest.raises(NodeContractError, match="선언하지 않은 출구 'other'"):
        wait_any(ctx, {"other": Target("o")})

    with pytest.raises(NodeDeclarationError, match="DynamicExits"):

        @node(
            type="sample.a.b",
            version=1,
            title="t",
            exits=DynamicExits(from_config="missing"),
        )
        def bad(ctx: Context) -> Result:
            return Result.ok("x")


def test_from_interface_pins_in_schema() -> None:
    @node(
        type="core.graph.call",
        version=1,
        title="서브그래프 호출",
        config={"graph": Config(str)},
        inputs=FromInterface("inputs"),
        outputs=FromInterface("outputs"),
        exits=FromInterface("exits"),
        engine="call",
    )
    def call(ctx: Context) -> Result:
        raise AssertionError("호출되지 않는다")

    @node(
        type="core.graph.entry",
        version=1,
        title="시작",
        outputs=FromInterface("inputs"),
        exits=[Exit("start", "ok")],
        engine="entry",
    )
    def entry(ctx: Context) -> Result:
        raise AssertionError("호출되지 않는다")

    schema = call.schema()
    assert schema["inputs"] == {"from_interface": "inputs"}
    assert schema["outputs"] == {"from_interface": "outputs"}
    assert schema["exits"] == {"from_interface": "exits"}
    assert entry.schema()["outputs"] == {"from_interface": "inputs"}
    # interface 핀은 출구에 이름으로 적지 않는다 (실행기가 interface에서 정한다)
    assert entry.schema()["exits"] == [{"kind": "ok", "name": "start", "outputs": []}]

    with pytest.raises(NodeDeclarationError, match="FromInterface"):

        @node(type="core.a.b", version=1, title="t", exits=FromInterface("inputs"), engine="x")
        def bad_source(ctx: Context) -> Result:
            return Result.ok("x")

    with pytest.raises(NodeDeclarationError, match="ctx 하나뿐"):

        @node(
            type="core.a.b",
            version=1,
            title="t",
            inputs=FromInterface("outputs"),
            exits=[],
            engine="x",
        )
        def with_args(ctx: Context, x: int) -> Result:
            return Result.ok("x")


def test_engine_marker_only_for_core() -> None:
    @node(type="core.test.pass", version=1, title="성공", exits=[], engine="test_pass")
    def test_pass(ctx: Context, reason: str = "") -> Result:
        raise AssertionError("호출되지 않는다")

    assert test_pass.schema()["engine"] == "test_pass"
    assert test_pass.schema()["exits"] == []
    with pytest.raises(NodeContractError, match="실행기가 직접 처리"):
        test_pass(fake_context())

    with pytest.raises(NodeDeclarationError, match="core 플러그인"):

        @node(type="sample.flow.loop", version=1, title="t", exits=[], engine="loop")
        def plugin_engine(ctx: Context) -> Result:
            return Result.ok("x")

    with pytest.raises(NodeDeclarationError, match="종료 노드"):

        @node(type="sample.flow.end", version=1, title="t", exits=[])
        def plugin_terminal(ctx: Context) -> Result:
            return Result.ok("x")


def test_assertion_flag_in_schema() -> None:
    @node(
        type="sample.assert.ok",
        version=1,
        title="검증",
        exits=[Exit("ok", "ok"), Exit("fail", "fail")],
        assertion=True,
    )
    def check(ctx: Context) -> Result:
        return Result.ok("ok")

    assert check.schema()["assertion"] is True
    assert check.spec.assertion
    assert "assertion" not in wait_image.schema()

    with pytest.raises(NodeDeclarationError, match="assertion"):

        @node(type="sample.assert.pure", version=1, title="t", pure=True, assertion=True)
        def pure_check(ctx: Context) -> dict[str, Any]:
            return {}


def test_pure_node_returns_outputs() -> None:
    @node(
        type="sample.logic.not",
        version=1,
        title="부정",
        pure=True,
        outputs={"result": bool, "note": str | None},
    )
    def negate(ctx: Context, value: bool) -> dict[str, Any]:
        return {"result": not value}

    schema = negate.schema()
    assert schema["pure"] is True
    assert "exits" not in schema
    result = negate(fake_context(), True)
    assert (result.exit, result.kind) == (None, None)
    assert result.outputs == {"result": False, "note": None}
    assert negate.invoke(fake_context(), {"value": False}).outputs["result"] is True

    @node(type="sample.logic.bad", version=1, title="t", pure=True, outputs={"x": int})
    def bad(ctx: Context) -> dict[str, Any]:
        return {"y": 1}

    with pytest.raises(NodeContractError, match="선언하지 않은 출력 'y'"):
        bad(fake_context())

    with pytest.raises(NodeDeclarationError, match="순수 노드는 출구가 없다"):

        @node(type="sample.logic.x", version=1, title="t", pure=True, exits=[Exit("ok", "ok")])
        def with_exit(ctx: Context) -> dict[str, Any]:
            return {}


@pytest.mark.parametrize(
    "where",
    [
        {"exits": FromInterface("exits"), "outputs": {"required": int}},
        {"inputs": FromInterface("inputs"), "exits": [Exit("ok", "ok")]},
        {"outputs": FromInterface("outputs"), "exits": [Exit("ok", "ok")]},
    ],
    ids=["exits", "inputs", "outputs"],
)
def test_from_interface_only_for_engine_nodes(where: dict[str, Any]) -> None:
    # 일반 노드가 interface 출구를 쓰면 결과 검사(출구·출력 대조)를 할 수 없다 (검수 T3_1)
    with pytest.raises(NodeDeclarationError, match="engine= 노드"):

        @node(type="sample.flow.probe", version=1, title="t", **where)
        def probe(ctx: Context) -> Result:
            return Result.ok("never_declared", unexpected=1)


def test_literal_output_rejected() -> None:
    # 노드 스키마 OutputPin에는 enum이 없다. 출력 Literal은 선언 오류 (검수 T3_1)
    with pytest.raises(NodeDeclarationError, match="Literal은 입력·config"):

        @node(
            type="sample.value.state",
            version=1,
            title="t",
            pure=True,
            outputs={"state": Literal["ready", "done"]},
        )
        def state(ctx: Context) -> dict[str, Any]:
            return {"state": "ready"}

    with pytest.raises(NodeDeclarationError, match="Literal"):

        @node(
            type="sample.value.state",
            version=1,
            title="t",
            pure=True,
            outputs={"state": Output(Literal["a"], nullable=True)},
        )
        def state2(ctx: Context) -> dict[str, Any]:
            return {}


@pytest.mark.parametrize(
    ("decl", "message"),
    [
        (Config(list[str], min_items=-1), "min_items"),
        (Config(list[str], min_items=1.5), "min_items"),  # type: ignore[arg-type]
        (Config(list[str], min_items=True), "min_items"),  # type: ignore[arg-type]
        (Config(float, minimum=float("nan")), "유한"),
        (Config(float, maximum=float("inf")), "유한"),
        (Config(int, minimum=True), "수여야"),  # type: ignore[arg-type]
        (Config(int, minimum="1"), "수여야"),  # type: ignore[arg-type]
        (Config(int, minimum=5, maximum=1), "maximum"),
        (Config(int, minimum=2**53), "2\\^53"),
        (Config(int, default=2**53), "2\\^53"),
        (Config(int, default=-(2**53)), "2\\^53"),
        (Config(float, default=float("nan")), "유한"),
        (Config(list[int], default=[1, 2**60]), "2\\^53"),
        (Config(int, enum=[1, 2**60]), "2\\^53"),
        (Config(str, description=1), "description"),  # type: ignore[arg-type]
    ],
)
def test_pin_constraints_and_defaults_checked(decl: Config, message: str) -> None:
    with pytest.raises(NodeDeclarationError, match=message):

        @node(type="sample.value.probe", version=1, title="t", pure=True, config={"v": decl})
        def probe(ctx: Context) -> dict[str, Any]:
            return {}


def test_input_constraints_checked_and_safe_bounds_allowed() -> None:
    with pytest.raises(NodeDeclarationError, match="유한"):

        @node(type="sample.value.probe", version=1, title="t", pure=True)
        def bad(ctx: Context, x: Annotated[float, Input(minimum=float("-inf"))] = 0) -> dict:
            return {}

    with pytest.raises(NodeDeclarationError, match="2\\^53"):

        @node(type="sample.value.probe", version=1, title="t", pure=True)
        def big(ctx: Context, x: int = 2**53) -> dict:
            return {}

    @node(
        type="sample.value.probe",
        version=1,
        title="t",
        pure=True,
        config={"n": Config(list[str], min_items=0)},
    )
    def ok(
        ctx: Context,
        x: Annotated[int, Input(minimum=-(2**53 - 1), maximum=2**53 - 1)] = 2**53 - 1,
        y: Annotated[float, Input(minimum=0.5, maximum=0.5)] = 0.5,
    ) -> dict:
        return {}

    schema = ok.schema()
    assert schema["inputs"]["x"] == {
        "type": "int",
        "default": 2**53 - 1,
        "minimum": -(2**53 - 1),
        "maximum": 2**53 - 1,
    }
    assert schema["config"]["n"] == {"type": "list[string]", "min_items": 0}
