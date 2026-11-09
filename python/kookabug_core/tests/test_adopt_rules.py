"""자동 채택 조건 2·3 순수 함수 (M8 계획 3.8·E6·R1, B3) — 엄격: 채택 조건 우회.

값을 읽지 않고 필드 이름·sha만 본다. 판정 규칙이 우회되지 않는지 필드마다 고정한다.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

from kookabug_core import adopt as rules

TARGET = "targets/shop/buy.target.json"
IMAGE = "targets/shop/buy.png"
BASE: dict[str, Any] = {
    "click": {"anchor": "center", "offset": [0, 0]},
    "format": "kookabug.target/0",
    "image": "buy.png",
    "recorded": {"client_size": [1024, 640], "dpi": 96},
    "search": {"region": [0.1, 0.6, 0.25, 0.2]},
}


def graph(*nodes: tuple[str, str, str]) -> dict[str, Any]:
    """(노드 ID, 타입, target 핀) → target을 쓰는 그래프."""
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            nid: {"in": {pin: {"$target": TARGET}}, "type": typ, "version": 1}
            for nid, typ, pin in nodes
        },
    }


TEAM_FILES = {"tests/shop/buy.graph.json": graph(("n_click", "core.image.click", "target"))}


def candidate(after: dict[str, Any], *, png: bool = False) -> rules.Problem | None:
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(after).encode())
    }
    if png:
        changed[IMAGE] = (b"old", b"new")
    return rules.candidate_problem(changed, team_files=TEAM_FILES, team_targets={TARGET: BASE})


def edited(**fields: Any) -> dict[str, Any]:
    value = json.loads(json.dumps(BASE))
    for path, new in fields.items():
        node = value
        parts = path.split("__")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        if new is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = new
    return value


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"click__anchor": "top_left"}, None),
        ({"click__offset": [4, -2]}, None),
        ({"recorded__client_size": [1280, 800]}, None),
        ({"recorded__dpi": 120}, None),
        ({"image": "buy-2.png"}, None),
        ({"match__threshold": 0.5}, "threshold_changed"),
        ({"match__methods": ["edge"]}, "threshold_changed"),
        ({"match__color_tolerance": 40}, "threshold_changed"),
        ({"sensitive": True}, "not_locator_only"),
        ({"format": "kookabug.target/1"}, "not_locator_only"),
    ],
)
def test_locator_only_fields(fields: dict[str, Any], code: str | None) -> None:
    problem = candidate(edited(**fields))
    assert (problem.code if problem else None) == code, problem
    if problem is not None:
        assert problem.condition == 2


def test_region_shrink_or_move_ok_widen_refused() -> None:
    assert candidate(edited(search__region=[0.6, 0.7, 0.25, 0.2])) is None  # 옮기기 (같은 넓이)
    assert candidate(edited(search__region=[0.1, 0.6, 0.2, 0.1])) is None  # 줄이기
    widened = candidate(edited(search__region=[0.0, 0.0, 0.5, 0.5]))
    assert widened is not None and widened.code == "search_widened"
    removed = candidate(edited(search=None))
    assert removed is not None and removed.code == "search_widened"
    # 원래 범위가 없던 target은 새로도 없어야 한다
    no_region = {k: v for k, v in BASE.items() if k != "search"}
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(no_region).encode(), json.dumps(BASE).encode())
    }
    added = rules.candidate_problem(changed, team_files=TEAM_FILES, team_targets={})
    assert added is not None and added.code == "search_widened"


def test_target_used_by_assert_refused() -> None:
    files = {
        "tests/shop/buy.graph.json": graph(
            ("n_click", "core.image.click", "target"), ("n_seen", "core.assert.visible", "target")
        )
    }
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(edited(click__offset=[1, 1])).encode())
    }
    problem = rules.candidate_problem(changed, team_files=files, team_targets={TARGET: BASE})
    assert problem is not None and problem.code == "target_used_for_judgment"
    assert "n_seen" in problem.detail
    # image.wait(분기 판정)도 조작 노드 허용 목록 밖이다
    files = {"subgraphs/x.graph.json": graph(("n_wait", "core.image.wait", "target"))}
    problem = rules.candidate_problem(changed, team_files=files, team_targets={TARGET: BASE})
    assert problem is not None and problem.code == "target_used_for_judgment"


def test_target_in_screen_detect_refused() -> None:
    files = {
        **TEAM_FILES,
        "screens/shop.screen.json": {
            "detect": {"all": [{"$target": TARGET}]},
            "format": "kookabug.screen/0",
        },
    }
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(edited(click__offset=[1, 1])).encode())
    }
    problem = rules.candidate_problem(changed, team_files=files, team_targets={TARGET: BASE})
    assert problem is not None and problem.code == "target_used_for_judgment"
    assert "screens/shop.screen.json" in problem.detail


def test_graph_diff_refused() -> None:
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(BASE).encode()),
        "tests/shop/buy.graph.json": (b"{}", b'{"x": 1}'),
    }
    problem = rules.candidate_problem(changed, team_files=TEAM_FILES, team_targets={})
    assert problem is not None and problem.code == "not_locator_only"
    # 새 target·target 둘·target 아닌 PNG도 자동 채택하지 않는다
    new = rules.candidate_problem(
        {TARGET: (None, json.dumps(BASE).encode())}, team_files=TEAM_FILES, team_targets={}
    )
    assert new is not None and new.code == "not_locator_only"
    other_png = rules.candidate_problem(
        {
            TARGET: (json.dumps(BASE).encode(), json.dumps(BASE).encode()),
            "targets/shop/other.png": (b"a", b"b"),
        },
        team_files=TEAM_FILES,
        team_targets={},
    )
    assert other_png is not None and other_png.code == "not_locator_only"
    assert candidate(BASE, png=True) is None  # 제 PNG만 바뀐 제자리 수리는 된다


def test_shared_png_change_checked_via_closure() -> None:
    """R1: 바꾸는 PNG를 판정에 쓰는 다른 target이 함께 쓰면 거부한다 (그 판정이 같이 바뀐다)."""
    other = "targets/shop/potion.target.json"
    targets = {TARGET: BASE, other: {**BASE, "image": "buy.png"}}
    changed: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(BASE).encode()),
        IMAGE: (b"old", b"new"),
    }
    problem = rules.candidate_problem(changed, team_files=TEAM_FILES, team_targets=targets)
    assert problem is not None and problem.code == "target_used_for_judgment"
    assert "shared_image" in problem.detail
    # 다른 target이 다른 PNG를 쓰면 괜찮다
    targets[other] = {**BASE, "image": "potion.png"}
    assert rules.candidate_problem(changed, team_files=TEAM_FILES, team_targets=targets) is None


def test_case_alias_keys_compared_normalized() -> None:
    """후보·target·image 키는 정규화(구분자·casefold)해 비교한다: 대소문자만 다른 PNG 키도 공유
    이미지 검사를 받고, 같은 파일의 두 키는 `path_alias`."""
    other = "targets/shop/potion.target.json"
    targets = {TARGET: BASE, other: {**BASE, "image": "buy.png"}}
    alias: dict[str, tuple[bytes | None, bytes]] = {
        TARGET: (json.dumps(BASE).encode(), json.dumps(BASE).encode()),
        "targets/shop/BUY.png": (b"old", b"new"),
    }
    problem = rules.candidate_problem(alias, team_files=TEAM_FILES, team_targets=targets)
    assert problem is not None and "shared_image" in problem.detail
    twice = {**alias, IMAGE: (b"old", b"new")}
    problem = rules.candidate_problem(twice, team_files=TEAM_FILES, team_targets=targets)
    assert problem is not None and problem.code == "path_alias"
    assert rules.path_key("targets\\Shop//BUY.png") == rules.path_key("targets/shop/buy.png")


def test_file_kind_ignores_case() -> None:
    """파일 종류 판별(`is_graph`·`is_target`·`is_png`)은 `path_key` 정규화 위에서 — 확장자
    대소문자·구분자가 달라도 같은 종류다."""
    for rel in ("tests/a.graph.json", "tests\\a.GRAPH.json", "tests/a.graph.JSON"):
        assert rules.is_graph(rel), rel
    assert not rules.is_graph("tests/a.json") and not rules.is_graph("tests/a.graph.json.bak")
    assert rules.is_target("targets/Shop/BUY.TARGET.JSON") and not rules.is_target("a.json")
    assert rules.is_png("targets/shop/buy.PNG") and not rules.is_png("buy.png.txt")
    assert rules.has_suffix("screens/a.JSON", ".json")


def test_judgment_inputs_follow_settings_and_links() -> None:
    """판정 입력의 `$setting`과 `$link`로 이어진 같은 그래프 노드의 입력까지 모은다. 비밀값·추적
    가능 생산자 목록 밖(변수·서브그래프 경계·OCR·반복 index·코어 표에 없는 노드)은 추적할 수
    없다."""
    root = "tests/shop/buy.graph.json"

    def judged(nodes: dict[str, Any], known: Any = lambda _: True) -> rules.Judgment:
        return rules.judgment_inputs(
            {root: {"nodes": nodes}},
            root,
            is_assertion=lambda t: t.startswith("core.assert."),
            is_known=known,
            targets={TARGET: BASE},
        )

    found = judged(
        {
            "n_fmt": {
                "in": {"template": "{g}", "values": {"g": {"$setting": "shop.region"}}},
                "type": "core.text.format",
            },
            "n_eq": {
                "in": {"equals": {"$link": "n_fmt.text"}, "x": {"$setting": "shop.gold"}},
                "type": "core.assert.compare",
            },
        }
    )
    assert found.settings == {"shop.region", "shop.gold"} and found.untraceable is None
    via_click = judged(
        {
            "n_click": {
                "in": {"target": {"$target": "targets/shop/BUY.target.json"}},
                "type": "core.image.click",
            },
            "n_eq": {"in": {"a": {"$link": "n_click.match"}}, "type": "core.assert.compare"},
        }
    )
    assert {rules.path_key(f) for f in via_click.files} >= {
        rules.path_key(TARGET),
        rules.path_key(IMAGE),
    }
    literal = judged({"n": {"in": {"v": {"$literal": {"$secret": "x"}}}, "type": "core.assert.x"}})
    assert literal.untraceable is None
    for nodes, known in [
        ({"n": {"in": {"v": {"$secret": "pw"}}, "type": "core.assert.text"}}, None),
        (
            {
                "n_var": {"in": {}, "type": "core.var.get"},
                "n": {"in": {"v": {"$link": "n_var.value"}}, "type": "core.assert.text"},
            },
            None,
        ),
        (
            {
                "n_in": {"type": "core.graph.entry"},
                "n": {"in": {"v": {"$link": "n_in.value"}}, "type": "core.assert.text"},
            },
            None,
        ),
        ({"n": {"in": {"v": {"$link": "gone.value"}}, "type": "core.assert.text"}}, None),
        *[
            (
                {
                    "n_p": {"in": {"name": "x"}, "type": producer},
                    "n": {"in": {"v": {"$link": "n_p.out"}}, "type": "core.assert.compare"},
                },
                None,
            )
            for producer in (
                "core.var.add",
                "core.var.set",
                "core.graph.call",
                "core.ocr.read",
                "core.ocr.wait_text",
                "core.assert.text",
                "core.flow.repeat",
                "core.screen.capture",
                "core.agent.api_judge",
                "plugin.any.value",
            )
        ],
        ({"n": {"in": {}, "type": "core.assert.plugin"}}, lambda t: t != "core.assert.plugin"),
    ]:
        got = judged(nodes, known or (lambda _: True))
        assert got.untraceable is not None, nodes


def test_team_setting_profile_then_team() -> None:
    config = {
        "settings": {"a": 1, "b": 2},
        "profiles": {"p": {"settings": {"a": 9}}},
    }
    assert rules.team_setting(config, "a", "p") == 9
    assert rules.team_setting(config, "a", None) == 1
    assert rules.team_setting(config, "b", "p") == 2
    assert rules.team_setting(config, "c", "p") is rules.MISSING
    assert rules.team_setting(None, "a", "p") is rules.UNKNOWN
    changed = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[],
        current_claims={},
        original_deps={},
        current_deps={},
        original_settings={"a": "12,245"},
        current_settings={"a": "12,345"},
    )
    assert changed is not None and changed.code == "oracle_changed"
    unknown = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[],
        current_claims={},
        original_deps={},
        current_deps={},
        original_settings={"a": rules.UNKNOWN},
        current_settings={"a": "x"},
    )
    assert unknown is not None and unknown.code == "oracle_changed"


def test_oracle_dependency_changed_refused() -> None:
    graphs = {
        "tests/shop/buy.graph.json": {
            "nodes": {
                "n_click": {"in": {"target": {"$target": TARGET}}, "type": "core.image.click"},
                "n_item": {
                    "in": {"target": {"$target": "targets/shop/item.target.json"}},
                    "type": "core.assert.visible",
                },
            }
        }
    }
    deps = rules.judgment_dependencies(
        graphs,
        "tests/shop/buy.graph.json",
        is_assertion=lambda t: t.startswith("core.assert."),
        targets={"targets/shop/item.target.json": {"image": "item.png"}},
    )
    assert deps == {
        "tests/shop/buy.graph.json",
        "targets/shop/item.target.json",
        "targets/shop/item.png",
    }
    assert TARGET not in deps  # 조작 전용 target은 판정 의존성이 아니다
    same = dict.fromkeys(deps, "a")
    ok = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[{"id": "shop.potion.price", "rev": 1}],
        current_claims={"shop.potion.price": 1},
        original_deps=same,
        current_deps=same,
    )
    assert ok is None
    changed = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[],
        current_claims={},
        original_deps=same,
        current_deps={**same, "targets/shop/item.png": "b"},
    )
    assert changed is not None and (changed.condition, changed.code) == (3, "oracle_changed")
    graph_changed = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="h",
        original_claims=[],
        current_claims={},
        original_deps={},
        current_deps={},
    )
    assert graph_changed is not None and graph_changed.code == "oracle_changed"
    claims = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[{"id": "shop.potion.price", "rev": 1}],
        current_claims={"shop.potion.price": 2},
        original_deps={},
        current_deps={},
    )
    assert claims is not None and claims.code == "claims_changed"
    # 원래 실행 스냅샷이 없으면(None) 같다고 보지 않는다
    missing = rules.oracle_problem(
        original_graph_sha="g",
        current_graph_sha="g",
        original_claims=[],
        current_claims={},
        original_deps=dict.fromkeys(deps),
        current_deps=same,
    )
    assert missing is not None and missing.code == "oracle_changed"


# ---------------------------------------------------------------- 추적 가능 생산자 허용 목록

_PURE_FORBIDDEN = ("ctx", "environ", "getenv", "subprocess", "open(", "Path(", "import")
_TARGET_FORBIDDEN = (
    "ctx.vars",
    "ctx.setting",
    "ctx.secret",
    "ctx.ocr",
    "read_area",
    "judge",
    "ctx.process",
    "environ",
    "getenv",
    "subprocess",
    "open(",
    "Path(",
)


def _body(fn: Any) -> str:
    """함수 본문 소스 (데코레이터·서명 제외 — 첫 줄 `def`부터 `:` 줄 끝까지 버린다)."""
    import inspect

    lines, _ = inspect.getsourcelines(fn)
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("def "))
    end = next(i for i in range(start, len(lines)) if lines[i].rstrip().endswith(":"))
    return "".join(lines[end + 1 :])


def _helpers(fn: Any, seen: set[str]) -> list[Any]:
    """`fn`이 이름으로 부르는 노드 패키지 모듈 함수 (재귀)."""
    import inspect

    out: list[Any] = []
    for name in fn.__code__.co_names:
        found = fn.__globals__.get(name)
        if (
            inspect.isfunction(found)
            and found.__module__.startswith("kookabug_nodes")
            and found.__qualname__ not in seen
        ):
            seen.add(found.__qualname__)
            out += [found, *_helpers(found, seen)]
    return out


def test_traceable_producers_read_only_inputs() -> None:
    """허용 목록 노드마다: 순수 노드는 `ctx`를 쓰지 않고(본문·부르는 함수까지) 출력이 `in`만으로
    정해진다. target 출처 노드는 출력이 `match` 하나이고 변수·설정·비밀값·OCR·판단·외부를 읽지
    않는다(`ctx.vision.find`로 `in`의 target을 찾을 뿐). 상태를 읽는 노드는 목록에 없다."""
    import inspect

    from kookabug_core.registry import default_registry

    registry = default_registry()
    assert set(rules.TRACEABLE_PRODUCERS.values()) == {"pure", "target"}
    for node_type, kind in sorted(rules.TRACEABLE_PRODUCERS.items()):
        nodedef = registry.get(node_type)
        assert nodedef is not None and nodedef.function is not None, node_type
        assert nodedef.engine is None, node_type
        fn = getattr(nodedef.function, "__wrapped__", nodedef.function)
        body = _body(fn)
        helpers = _helpers(fn, set())
        if kind == "pure":
            assert nodedef.pure and nodedef.effects == frozenset(), node_type
            assert [t for t in _PURE_FORBIDDEN if t in body] == [], node_type
            for helper in helpers:
                assert "ctx" not in inspect.signature(helper).parameters, helper.__qualname__
                text = inspect.getsource(helper)
                assert [t for t in _PURE_FORBIDDEN if t in text] == [], helper.__qualname__
        else:
            assert nodedef.effects <= {"capture", "input"}, node_type
            outputs = cast(tuple[Any, ...], nodedef.outputs)
            assert [o.name for o in outputs] == ["match"], node_type
            assert "ctx.vision.find" in body, node_type
            for text in [body, *(inspect.getsource(h) for h in helpers)]:
                assert [t for t in _TARGET_FORBIDDEN if t in text] == [], node_type
    for outside in (
        "core.var.add",
        "core.var.get",
        "core.var.set",
        "core.graph.entry",
        "core.graph.call",
        "core.graph.exit",
        "core.flow.repeat",
        "core.flow.while",
        "core.ocr.read",
        "core.ocr.wait_text",
        "core.ocr.click_text",
        "core.assert.text",
        "core.screen.capture",
        "core.agent.cli_judge",
        "core.agent.api_judge",
        "core.app.launch",
        "core.qa.cheat",
    ):
        assert outside not in rules.TRACEABLE_PRODUCERS, outside


def test_judged_use_problem_scans_every_team_graph() -> None:
    """조건 2 팀 스캔: 원래 테스트 밖 그래프의 판정 입력이 `$link`로 후보 target을 거쳐 오면 거부.
    target을 쓰는 그래프(부르는 쪽·불리는 쪽 포함)의 추적 불가 판정 입력도 거부, target과 무관한
    그래프의 추적 불가 판정은 상관하지 않는다."""

    def check(graphs: dict[str, Any]) -> rules.Problem | None:
        return rules.judged_use_problem(
            graphs,
            TARGET,
            is_assertion=lambda t: t.startswith("core.assert."),
            targets={TARGET: BASE},
        )

    click = {"in": {"target": {"$target": TARGET}}, "type": "core.image.click"}
    link = {"in": {"a": {"$link": "n_click.match"}}, "type": "core.assert.compare"}
    assert check(TEAM_FILES) is None
    other = {"tests/other.graph.json": {"nodes": {"n_click": click, "n_eq": link}}}
    problem = check({**TEAM_FILES, **other})
    assert problem is not None
    assert (problem.condition, problem.code) == (2, "target_used_for_judgment")
    assert "tests/other.graph.json" in problem.detail
    # 서브그래프가 target을 쓰고, 부르는 테스트가 호출 출력을 판정한다 (추적 불가 → 거부)
    sub = {"subgraphs/s.graph.json": {"nodes": {"n_click": click}}}
    call = {"config": {"graph": "subgraphs/S.graph.json"}, "type": "core.graph.call"}
    caller = {
        "tests/caller.graph.json": {
            "nodes": {
                "n_call": call,
                "n_eq": {"in": {"a": {"$link": "n_call.m"}}, "type": "core.assert.compare"},
            }
        }
    }
    problem = check({**TEAM_FILES, **sub, **caller})
    assert problem is not None and "caller" in problem.detail
    # target을 쓰는 테스트가 부르는 서브그래프가 호출 입력을 판정한다 (추적 불가 → 거부)
    callee = {
        "subgraphs/judge.graph.json": {
            "nodes": {
                "n_in": {"type": "core.graph.entry"},
                "n_eq": {"in": {"a": {"$link": "n_in.m"}}, "type": "core.assert.compare"},
            }
        }
    }
    judge_call = {"config": {"graph": "subgraphs/judge.graph.json"}, "type": "core.graph.call"}
    user = {"tests/user.graph.json": {"nodes": {"n_click": click, "n_call": judge_call}}}
    problem = check({**TEAM_FILES, **callee, **user})
    assert problem is not None and "judge" in problem.detail
    # target과 무관한 그래프의 추적 불가 판정은 이 target의 채택을 막지 않는다
    unrelated = {
        "tests/unrelated.graph.json": {
            "nodes": {
                "n_var": {"in": {"name": "x"}, "type": "core.var.get"},
                "n_eq": {"in": {"a": {"$link": "n_var.value"}}, "type": "core.assert.compare"},
            }
        }
    }
    assert check({**TEAM_FILES, **unrelated}) is None
    # 흐름 분기 조건이 후보 target 출처면 판정 사용 (분기 → core.test.fail)
    branch = {
        "tests/branch.graph.json": {
            "nodes": {
                "n_click": click,
                "n_cmp": {
                    "in": {"a": {"$link": "n_click.match"}, "op": "==", "b": None},
                    "type": "core.logic.compare",
                },
                "n_if": {
                    "in": {"condition": {"$link": "n_cmp.result"}},
                    "type": "core.flow.branch",
                },
                "n_fail": {"type": "core.test.fail"},
            }
        }
    }
    problem = check({**TEAM_FILES, **branch})
    assert problem is not None and "branch" in problem.detail


def test_target_flow_only_to_operation_sinks() -> None:
    """정방향: 후보 target을 읽는 노드의 출력은 입력 장치 조작 핀(`TARGET_VALUE_SINKS`)으로만 흘러갈
    수 있다. 변수 저장·비교·분기·그래프 경계·플러그인으로 흘러가면(순수 노드를 거쳐도) 거부.
    target과 무관한 반복 카운터 분기는 상관하지 않는다."""
    click = {"in": {"target": {"$target": TARGET}}, "type": "core.image.click"}

    def flow(*extra: tuple[str, dict[str, Any]]) -> rules.Problem | None:
        nodes: dict[str, Any] = {"n_click": click, **dict(extra)}
        return rules.target_flow_problem({"tests/t.graph.json": {"nodes": nodes}}, TARGET)

    m = {"$link": "n_click.match"}
    assert flow(("n_tap", {"in": {"match": m}, "type": "core.input.click"})) is None
    assert flow(("n_drag", {"in": {"start": m, "end": [1, 2]}, "type": "core.input.drag"})) is None
    for name, spec in [
        ("n_store", {"in": {"name": "m", "value": m}, "type": "core.var.set"}),
        ("n_cmp", {"in": {"a": m, "op": "!=", "b": None}, "type": "core.logic.compare"}),
        ("n_fmt", {"in": {"template": "{m}", "values": {"m": m}}, "type": "core.text.format"}),
        ("n_if", {"in": {"condition": m}, "type": "core.flow.branch"}),
        ("n_out", {"in": {"m": m}, "type": "core.graph.exit"}),
        ("n_call", {"in": {"m": m}, "type": "core.graph.call"}),
        ("n_plug", {"in": {"m": m}, "type": "plugin.any.node"}),
        ("n_scroll", {"in": {"point": m, "amount": 1}, "type": "core.input.scroll"}),
        ("n_tap", {"in": {"point": m}, "type": "core.input.click"}),
    ]:
        problem = flow((name, spec))
        assert problem is not None, name
        assert (problem.condition, problem.code) == (2, "target_used_for_judgment")
        assert name in problem.detail
    # 대소문자만 다른 target 철자도 같은 출처
    alias = {
        "in": {"target": {"$target": "targets/Shop/BUY.target.json"}},
        "type": "core.image.click",
    }
    graphs = {
        "tests/t.graph.json": {
            "nodes": {
                "n_click": alias,
                "n_store": {"in": {"name": "m", "value": m}, "type": "core.var.set"},
            }
        }
    }
    assert rules.target_flow_problem(graphs, TARGET) is not None
    # 반복 카운터 분기 (target 값 없음)는 통과
    counter = {
        "n_set": {"in": {"name": "i", "value": 0}, "type": "core.var.set"},
        "n_add": {"in": {"name": "i", "amount": 1}, "type": "core.var.add"},
        "n_cmp": {
            "in": {"a": {"$link": "n_add.value"}, "op": ">=", "b": 3},
            "type": "core.logic.compare",
        },
        "n_loop": {"in": {"condition": {"$link": "n_cmp.result"}}, "type": "core.flow.branch"},
    }
    graphs = {"tests/t.graph.json": {"nodes": {"n_click": click, **counter}}}
    assert rules.target_flow_problem(graphs, TARGET) is None
    problem = rules.judged_use_problem(
        graphs,
        TARGET,
        is_assertion=lambda t: t.startswith("core.assert."),
        targets={TARGET: BASE},
    )
    assert problem is None
