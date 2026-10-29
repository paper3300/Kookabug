import pytest

from kookabug_sdk import (
    Config,
    Context,
    DynamicExits,
    Exit,
    NodeDeclarationError,
    Result,
    Retry,
    node,
)

EXITS = [Exit("found", "ok"), Exit("timeout", "fail"), Exit("gone", "fail")]


def declare(retry: Retry | None, effects: set[str] | None = None) -> None:
    @node(
        type="sample.image.wait",
        version=1,
        title="대기",
        exits=EXITS,
        retry=retry,
        effects=effects or set(),
    )
    def fn(ctx: Context) -> Result:
        return Result.ok("found")


def test_retry_default_never() -> None:
    @node(type="sample.image.wait", version=1, title="대기", exits=EXITS)
    def fn(ctx: Context) -> Result:
        return Result.ok("found")

    assert fn.spec.retry == Retry.never()
    assert "retry" not in fn.schema()  # 생략 = never (스키마 6장)

    @node(
        type="sample.image.wait",
        version=1,
        title="대기",
        exits=EXITS,
        effects={"capture"},
        retry=Retry.observation(on=["timeout"]),
    )
    def observed(ctx: Context) -> Result:
        return Result.ok("found")

    assert observed.schema()["retry"] == {"mode": "observation", "on": ["timeout"]}


def test_build_rejects_observation_retry_with_input_effect() -> None:
    with pytest.raises(NodeDeclarationError, match="관측 재시도"):
        declare(Retry.observation(on=["timeout"]), {"capture", "input"})


def test_build_rejects_observation_retry_with_process_effect() -> None:
    with pytest.raises(NodeDeclarationError, match="관측 재시도"):
        declare(Retry.observation(on=["timeout"]), {"process"})


def test_retry_on_must_be_declared_fail_exits() -> None:
    declare(Retry.observation(on=["timeout", "gone"]), {"capture"})
    with pytest.raises(NodeDeclarationError, match="fail 출구가 아니다"):
        declare(Retry.observation(on=["found"]))  # ok 출구
    with pytest.raises(NodeDeclarationError, match="fail 출구가 아니다"):
        declare(Retry.observation(on=["nope"]))
    with pytest.raises(NodeDeclarationError, match="하나 이상"):
        declare(Retry.observation(on=[]))
    with pytest.raises(NodeDeclarationError, match="on을 쓰지 않는다"):
        declare(Retry("never", ("timeout",)))

    # 동적 출구는 고정 출구(extra)만 재시도 대상이 된다
    @node(
        type="sample.image.wait_any",
        version=1,
        title="t",
        config={"exits": Config(list[str])},
        exits=DynamicExits(from_config="exits", extra=[Exit("timeout", "fail")]),
        retry=Retry.observation(on=["timeout"]),
    )
    def wait_any(ctx: Context) -> Result:
        return Result.fail("timeout")

    assert wait_any.spec.retry.on == ("timeout",)

    with pytest.raises(NodeDeclarationError, match="재시도"):

        @node(
            type="sample.logic.x",
            version=1,
            title="t",
            pure=True,
            retry=Retry.observation(on=["timeout"]),
        )
        def pure(ctx: Context) -> dict[str, object]:
            return {}
