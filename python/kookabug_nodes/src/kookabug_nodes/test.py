"""테스트 판정 노드: 종료 노드(실행기가 처리)와 값 비교 검증."""

from typing import Any

from kookabug_nodes.values import CompareOp, compare_values, show
from kookabug_sdk import Context, Exit, Result, node


@node(
    type="core.test.pass",
    version=1,
    title="성공으로 끝냄",
    category="test",
    exits=[],
    engine="test_pass",
)
def test_pass(ctx: Context, reason: str | None = None) -> Result:
    """테스트를 성공으로 끝낸다 (테스트 전용)."""
    raise NotImplementedError


@node(
    type="core.test.fail",
    version=1,
    title="실패로 끝냄",
    category="test",
    exits=[],
    engine="test_fail",
)
def test_fail(ctx: Context, reason: str | None = None) -> Result:
    """테스트를 실패로 끝낸다 (테스트 전용)."""
    raise NotImplementedError


@node(
    type="core.test.skip",
    version=1,
    title="건너뜀으로 끝냄",
    category="test",
    exits=[],
    engine="test_skip",
)
def test_skip(ctx: Context, reason: str | None = None) -> Result:
    """테스트를 건너뜀으로 끝낸다 (테스트 전용)."""
    raise NotImplementedError


# 입력은 스텝 시작 때 한 번만 계산하므로 재시도해도 결과가 같다 → retry never (G2)
@node(
    type="core.assert.compare",
    version=1,
    title="값 비교 검증",
    category="test",
    exits=[Exit("ok", "ok"), Exit("fail", "fail")],
    assertion=True,
)
def assert_compare(ctx: Context, a: Any, op: CompareOp, b: Any) -> Result:
    """`a op b`가 참인지 검증한다. 예: 구매 후 골드가 줄었는지."""
    if compare_values(a, op, b):
        return Result.ok("ok")
    return Result.fail("fail", message=f"{show(a)} {op} {show(b)}이(가) 아니다")
