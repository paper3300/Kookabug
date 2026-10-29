import pytest

from kookabug_nodes.flow import branch, delay
from kookabug_nodes.log import log_message
from kookabug_nodes.test import assert_compare
from kookabug_sdk import Secret
from kookabug_sdk.testing import FakeClock, fake_context


def test_branch_true_false() -> None:
    assert branch(fake_context(), condition=True).exit == "true"
    assert branch(fake_context(), condition=False).exit == "false"
    with pytest.raises(TypeError):
        branch(fake_context(), condition=1)


def test_delay_uses_fake_clock() -> None:
    clock = FakeClock(start_ms=100)
    ctx = fake_context(clock=clock)
    result = delay(ctx, ms=1500)
    assert (result.exit, result.kind) == ("done", "ok")
    assert clock.now_ms() == 1600
    delay(ctx, ms=0)
    assert clock.now_ms() == 1600


@pytest.mark.parametrize("level", ["info", "warn", "error"])
def test_log_message_levels(level: str) -> None:
    ctx = fake_context()
    assert log_message(ctx, text="안녕", level=level).exit == "done"
    assert ctx.log.records == [(level, "안녕")]


def test_log_message_default_level_info() -> None:
    ctx = fake_context()
    log_message(ctx, text="x")
    assert ctx.log.records == [("info", "x")]


def test_log_message_masks_secret() -> None:
    ctx = fake_context()
    log_message(ctx, text=Secret("hunter2"), level="warn")
    assert ctx.log.records == [("warn", Secret.MASK)]
    assert "hunter2" not in repr(ctx.log.records)


def test_log_message_unknown_level_error() -> None:
    with pytest.raises(ValueError):
        log_message(fake_context(), text="x", level="debug")


def test_assert_compare_ok_fail() -> None:
    ok = assert_compare(fake_context(), a=100, op=">", b=70)
    assert (ok.exit, ok.kind) == ("ok", "ok")
    fail = assert_compare(fake_context(), a=100, op="<", b=70)
    assert (fail.exit, fail.kind) == ("fail", "fail")
    assert fail.message == "100 < 70이(가) 아니다"
    with pytest.raises(TypeError):
        assert_compare(fake_context(), a=100, op="<", b="70")


def test_assert_compare_fail_message_masks_secret() -> None:
    fail = assert_compare(fake_context(), a=[Secret("hunter2")], op="==", b="other")
    assert fail.exit == "fail"
    assert fail.message == '["***"] == "other"이(가) 아니다'


def test_assert_compare_retry_never() -> None:
    spec = assert_compare.spec
    assert spec.assertion is True
    assert spec.retry.mode == "never"
    assert "retry" not in assert_compare.schema()
