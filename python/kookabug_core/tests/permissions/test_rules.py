import pytest

from kookabug_core.permissions import parse_rule


@pytest.mark.parametrize(
    ("text", "tool", "arg"),
    [
        ("kb_run_start", "kb_run_start", "*"),
        ("kb_run_start(tests/smoke/*)", "kb_run_start", "tests/smoke/*"),
        ("kb_run_start()", "kb_run_start", ""),
        ("kb_input_*", "kb_input_*", "*"),
        ("kb_graph_?et(a(b))", "kb_graph_?et", "a(b)"),
        ("*", "*", "*"),
    ],
)
def test_rule_parse(text: str, tool: str, arg: str) -> None:
    rule = parse_rule(text, "deny")
    assert (rule.verdict, rule.tool, rule.arg, rule.text) == ("deny", tool, arg, text)


@pytest.mark.parametrize(
    "text", ["", "KB_RUN_START", "kb_run_start(", "kb run", "(x)", "kb_run_start(a)b", "kb-x"]
)
def test_rule_parse_rejects(text: str) -> None:
    with pytest.raises(ValueError, match="형식"):
        parse_rule(text, "allow")


def test_rule_parse_rejects_bad_verdict() -> None:
    with pytest.raises(ValueError, match="verdict"):
        parse_rule("kb_run_start", "maybe")  # type: ignore[arg-type]


def test_match_tool_and_arg_glob() -> None:
    rule = parse_rule("kb_run_*(tests/smoke/*)", "allow")
    assert rule.matches("kb_run_start", "tests/smoke/login.graph.json")
    assert rule.matches("kb_run_cancel", "tests/smoke/a/b.graph.json")  # *는 /도 넘는다
    assert not rule.matches("kb_run_start", "tests/full/login.graph.json")
    assert not rule.matches("kb_graph_get", "tests/smoke/login.graph.json")

    bare = parse_rule("kb_graph_patch", "ask")
    assert bare.matches("kb_graph_patch", "")
    assert bare.matches("kb_graph_patch", "anything")

    empty = parse_rule("kb_run_start()", "deny")
    assert empty.matches("kb_run_start", "")
    assert not empty.matches("kb_run_start", "tests/a.graph.json")

    one = parse_rule("kb_screen_?et(screens/?.json)", "deny")
    assert one.matches("kb_screen_get", "screens/a.json")
    assert not one.matches("kb_screen_get", "screens/ab.json")


def test_case_sensitive() -> None:
    rule = parse_rule("kb_run_start(Tests/*)", "deny")
    assert rule.matches("kb_run_start", "Tests/a.graph.json")
    assert not rule.matches("kb_run_start", "tests/a.graph.json")
    assert not rule.matches("KB_RUN_START", "Tests/a.graph.json")
