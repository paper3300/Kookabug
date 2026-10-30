"""점·사각형 상수 (스키마 v0 1장 "상수"): 검증기가 모양을 보고 실행기가 핀 타입대로 바꾼다.

`point` = `[x, y]`, `rect` = `[x, y, w, h]` (정수 클라이언트 픽셀, 너비·높이 1 이상). 유니온 핀
(`match|point`, `target|rect`)의 그 항에도 같다. 노드는 바꾸지 않는다 — `Point`·`Rect`를 받는다.
"""

from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import check, make_workspace
from helpers.m1 import ScenePlatform, StubEngines, clicks, run_on
from helpers.run import run_graph, tk
from testkit import registry_with_testkit

from kookabug_core.schema.pintype import parse_pin_type
from kookabug_core.validate.types import coerce
from kookabug_sdk.types import Point, Rect

TEST = "tests/t.graph.json"


def errors(tmp_path: Path, node_type: str, inputs: dict[str, Any]) -> list[tuple[str, str, str]]:
    ws = make_workspace(tmp_path)
    tk().entry("n_x").node("n_x", node_type, inputs=inputs).write(ws, TEST)
    return [(d.code, d.pointer or "", d.message) for d in check(ws, TEST) if d.severity == "error"]


@pytest.mark.parametrize(
    ("node_type", "pin", "value"),
    [
        ("core.input.click", "point", [512, 412]),
        ("core.input.click", "point", [-5, 0]),
        ("core.input.drag", "start", [1, 2]),
        ("core.input.scroll", "point", [0, 0]),
        ("core.screen.capture", "region", [0, 0, 1, 1]),
        ("core.ocr.read", "region", [262, 190, 500, 170]),
        ("core.screen.wait_stable", "region", [-10, 5, 30, 40]),
    ],
)
def test_good_constants_validate(
    tmp_path: Path, node_type: str, pin: str, value: list[int]
) -> None:
    inputs: dict[str, Any] = {pin: value}
    if node_type == "core.input.drag":
        inputs["end"] = [3, 4]
    if node_type == "core.input.scroll":
        inputs["amount"] = 1
    assert errors(tmp_path, node_type, inputs) == []


@pytest.mark.parametrize(
    ("node_type", "pin", "value", "shape"),
    [
        ("core.input.click", "point", [1], "[x, y]"),
        ("core.input.click", "point", [1, 2, 3], "[x, y]"),
        ("core.input.click", "point", [1.5, 2], "[x, y]"),
        ("core.input.click", "point", [True, 2], "[x, y]"),
        ("core.input.click", "point", {"x": 1, "y": 2}, "[x, y]"),
        ("core.input.drag", "start", [1, 2, 3], "[x, y]"),
        ("core.screen.capture", "region", [0, 0, 0, 10], "[x, y, w, h]"),
        ("core.screen.capture", "region", [0, 0, 10], "[x, y, w, h]"),
        ("core.screen.capture", "region", [0.1, 0.2, 0.3, 0.4], "[x, y, w, h]"),
        ("core.ocr.read", "region", [1, 2], "[x, y, w, h]"),
    ],
)
def test_bad_constants_are_type_mismatch_with_shape_hint(
    tmp_path: Path, node_type: str, pin: str, value: Any, shape: str
) -> None:
    inputs: dict[str, Any] = {pin: value}
    if node_type == "core.input.drag":
        inputs["end"] = [3, 4]
    ((code, pointer, message),) = errors(tmp_path, node_type, inputs)
    assert code == "type_mismatch" and pointer == f"/nodes/n_x/in/{pin}"
    assert shape in message


def test_coerce_by_pin_type() -> None:
    assert coerce([1, 2], parse_pin_type("point")) == Point(1, 2)
    assert coerce([1, 2, 3, 4], parse_pin_type("rect")) == Rect(1, 2, 3, 4)
    assert coerce([1, 2], parse_pin_type("match|point")) == Point(1, 2)
    assert coerce([1, 2, 3, 4], parse_pin_type("target|rect")) == Rect(1, 2, 3, 4)
    assert coerce([[1, 2], [3, 4]], parse_pin_type("list[point]")) == [Point(1, 2), Point(3, 4)]
    assert coerce({"a": [0, 0, 5, 5]}, parse_pin_type("dict[str,rect]")) == {"a": Rect(0, 0, 5, 5)}
    # 다른 타입·모양이 다른 값은 그대로 (검증이 따로 막는다)
    assert coerce([1, 2], parse_pin_type("list[int]")) == [1, 2]
    assert coerce([1, 2], parse_pin_type("any")) == [1, 2]
    assert coerce([1, 2, 3], parse_pin_type("point")) == [1, 2, 3]
    assert coerce(Point(1, 2), parse_pin_type("point")) == Point(1, 2)


def test_executor_gives_nodes_point_and_rect(tmp_path: Path) -> None:
    """노드는 상수 모양을 바꾸지 않는다: `testkit.m1.click`(`match|rect|point`)이 받은 값이 그대로
    공용 입력 서비스로 간다 — 점은 그 점, 사각형은 가운데."""
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_point"}
        )
        .node("n_point", "testkit.m1.click", inputs={"at": [5, 6]}, next={"done": "n_rect"})
        .node("n_rect", "testkit.m1.click", inputs={"at": [10, 20, 30, 40]}, next={"done": "n_ok"})
        .node("n_ok", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    )
    ran = run_on(ws, g, ScenePlatform.sample(engines=StubEngines()))
    assert ran.result.verdict == "pass", ran.result.reason
    hwnd = ran.platform.scenario.latest().window.handle
    assert clicks(ran.platform) == [(hwnd, 5, 6), (hwnd, 25, 40)]


def test_runtime_rechecks_constant_shape(tmp_path: Path) -> None:
    """검증을 건너뛰어도 실행기가 입력을 대조해 `error`(`type_mismatch`)로 멈춘다."""
    ws = make_workspace(tmp_path)
    g = tk().entry("n_x").node("n_x", "testkit.m1.click", inputs={"at": [1, 2, 3]})
    ran = run_graph(ws, g, validate=False)
    assert (ran.result.verdict, ran.result.code) == ("error", "type_mismatch")


# ---------------------------------------------------------------- 검수 T11-1 2: 배열 안의 $link


def _linked_click(value: Any, at: Any) -> Any:
    """변수 `x`에 `value`를 두고 `testkit.m1.click.at`에 `at`(그 변수를 읽는 `$link` 포함)."""
    return (
        tk()
        .entry("n_launch")
        .node(
            "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_set"}
        )
        .node(
            "n_set", "core.var.set", inputs={"name": "x", "value": value}, next={"done": "n_click"}
        )
        .node("n_get", "core.var.get", inputs={"name": "x"})
        .node("n_click", "testkit.m1.click", inputs={"at": at}, next={"done": "n_ok"})
        .node("n_ok", "core.assert.compare", inputs={"a": 1, "op": "==", "b": 1})
    )


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        ([{"$link": "n_get.value"}, 412], (512, 412)),  # point 원소
        ([10, 20, {"$link": "n_get.value"}, 40], (10 + 512 // 2, 40)),  # rect 너비
    ],
    ids=["point", "rect"],
)
def test_coordinate_array_accepts_nested_link(
    tmp_path: Path, at: list[Any], expected: tuple[int, int]
) -> None:
    """특수 값은 배열 원소에도 온다(스키마 1장): 실행 전에는 모양·연결 타입만, 값은 실행 때."""
    ws = make_workspace(tmp_path)
    g = _linked_click(512, at)
    g.write(ws, TEST)
    errors = check(ws, TEST, registry=registry_with_testkit())
    assert [d for d in errors if d.severity == "error"] == []
    ran = run_on(ws, g, ScenePlatform.sample(engines=StubEngines()))  # 검증을 켠 실행
    assert ran.result.verdict == "pass", ran.result.reason
    hwnd = ran.platform.scenario.latest().window.handle
    assert clicks(ran.platform) == [(hwnd, *expected)]


def test_nested_link_type_checked_statically(tmp_path: Path) -> None:
    ws = make_workspace(tmp_path)
    g = (
        tk()
        .entry("n_x")
        .node("n_fmt", "core.text.format", inputs={"template": "1", "values": {}})
        .node("n_x", "core.input.click", inputs={"point": [{"$link": "n_fmt.text"}, 4]})
    )
    g.write(ws, TEST)
    ((code, pointer),) = [(d.code, d.pointer) for d in check(ws, TEST) if d.severity == "error"]
    assert (code, pointer) == ("type_mismatch", "/nodes/n_x/in/point")


@pytest.mark.parametrize("value", [1.5, 0, "512"], ids=["float", "zero_width", "string"])
def test_nested_link_value_rechecked_at_run(tmp_path: Path, value: Any) -> None:
    """연결로 온 원소는 실행 때 다시 본다: 정수가 아니거나 너비가 0이면 `type_mismatch`."""
    ws = make_workspace(tmp_path)
    g = _linked_click(value, [10, 20, {"$link": "n_get.value"}, 40])
    ran = run_on(ws, g, ScenePlatform.sample(engines=StubEngines()))
    assert (ran.result.verdict, ran.result.code) == ("error", "type_mismatch")
    assert clicks(ran.platform) == []


# ---------------------------------------------------------------- 검수 T11-1 4: 유니온 + 컨테이너


@pytest.mark.parametrize(
    ("pin", "value", "expected"),
    [
        ("list[string]|list[point]", [[1, 2], [3, 4]], [Point(1, 2), Point(3, 4)]),
        ("list[point]|list[string]", [[1, 2], [3, 4]], [Point(1, 2), Point(3, 4)]),
        ("list[point]|list[string]", ["a", "b"], ["a", "b"]),
        ("dict[str,int]|dict[str,rect]", {"a": [0, 0, 5, 5]}, {"a": Rect(0, 0, 5, 5)}),
        ("dict[str,rect]|dict[str,int]", {"a": 3}, {"a": 3}),
        ("list[int]|point", [1, 2], [1, 2]),  # 앞 항이 맞으면 그 항 (변환 없음)
        ("point|list[int]", [1, 2], Point(1, 2)),
    ],
)
def test_union_container_coercion_uses_matching_branch(pin: str, value: Any, expected: Any) -> None:
    assert coerce(value, parse_pin_type(pin)) == expected
