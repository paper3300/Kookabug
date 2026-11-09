"""그래프 최상위 `qa` (M8 계획 3.5): 해석·필수 검증 노드·설정 오류(qa_config)·미적용(skip).

runner 판정은 제품 CLI(`kookabug run`)로 상점 예제 사본을 돌려 본다 — qa 설정 오류·미적용은 플랫폼을
열기 전에 끝나므로 OCR 모델이 필요 없다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.sample_game import copy_example_workspace
from kookabug_core.engine.executor import Executor
from kookabug_core.loader import load_program
from kookabug_core.qa import QaTrace, not_applicable, run_qa
from kookabug_core.schema import check_shape
from kookabug_core.validate import check_graph
from kookabug_core.workspace import MemorySecrets, Workspace

BUY = "tests/shop/buy_potion.graph.json"


def edit(ws: Path, rel: str, change: Any) -> None:
    path = ws / rel
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def qa_errors(ws: Path, graph: str = BUY) -> list[str]:
    _, diagnostics = check_graph(Workspace.open(ws), graph)
    return [d.message for d in diagnostics if d.code == "qa_invalid"]


def test_qa_parsed_and_required_nodes(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    program = load_program(Workspace.open(ws), BUY, secrets=MemorySecrets())
    assert program.qa is not None and program.qa["feature"] == "shop"
    # 주장 파일은 참조 목록에 든다 (스냅샷이 복사해 실행 시작 때 고정)
    assert "knowledge/features/shop.json" in program.references.discovered
    assert (
        program.knowledge["knowledge/features/shop.json"]["claims"][0]["id"] == "shop.potion.price"
    )
    assert qa_errors(ws) == []
    # 검증 노드가 실제로 실행·통과했나는 루트 그래프 노드 단위로 센다
    trace = QaTrace(executed={"n_click_buy", "n_assert_gold"}, passed={"n_assert_gold"})
    qa = run_qa(program, trace)
    assert qa is not None
    assert qa["claims"] == [
        {
            "assertions": ["n_assert_gold", "n_assert_item"],
            "executed": ["n_assert_gold"],
            "id": "shop.potion.price",
            "passed": ["n_assert_gold"],
            "rev": 1,
        }
    ]
    run_json = {
        "format": "kookabug.run/0",
        "graph": BUY,
        "qa": qa,
        "run_id": "abcd1234",
        "started_at": "2026-11-09T00:00:00.000Z",
        "status": "running",
    }
    assert check_shape(run_json, "run") == []
    # 옛 실행기는 최상위 추가 속성을 거부한다: qa 없는 스키마 형식이라도 다른 최상위 키는 막힌다
    assert check_shape({**json.loads((ws / BUY).read_text(encoding="utf-8")), "qa2": {}}, "graph")


@pytest.mark.process
def test_bad_claim_ref_is_config_error_not_skip(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    # 1) 없는 rev 2) 검증 노드가 아닌 노드 3) 없는 치트 허용
    edit(ws, BUY, lambda g: g["qa"]["claims"][0].update(rev=9))
    assert any("rev 9" in m for m in qa_errors(ws))
    edit(ws, BUY, lambda g: g["qa"]["claims"][0].update(rev=1, assertions=["n_click_buy"]))
    assert any("검증 노드가 아니다" in m for m in qa_errors(ws))
    edit(ws, BUY, lambda g: g["qa"]["claims"][0].update(assertions=["n_assert_gold"]))
    edit(ws, BUY, lambda g: g["qa"].update(cheats={"allow": [{"id": "no_such", "max_calls": 1}]}))
    assert any("no_such" in m for m in qa_errors(ws))
    # 치트 노드가 가리키는 치트·구현이 없으면 설정 오류 (구현 누락)
    edit(ws, BUY, lambda g: g["qa"].pop("cheats"))
    edit(
        ws,
        "knowledge/cheats.json",
        lambda d: d["cheats"][0]["impl"].update(graph="subgraphs/cheats/none.graph.json"),
    )
    edit(
        ws,
        BUY,
        lambda g: g["nodes"].update(
            n_cheat={"config": {"cheat": "give_gold"}, "type": "core.qa.cheat", "version": 1}
        ),
    )
    assert any("구현" in m for m in qa_errors(ws))
    # 주장 rev를 다시 틀리게 두고 실제 runner로: skip이 아니라 error/qa_config
    edit(ws, BUY, lambda g: g["nodes"].pop("n_cheat"))
    edit(ws, BUY, lambda g: g["qa"]["claims"][0].update(rev=9))
    out = run(tmp_path, ws, BUY)
    assert (out["verdict"], out["code"]) == ("error", "qa_config"), out
    qa = json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))["qa"]
    assert qa["config_errors"] and qa["claims"][0]["executed"] == []


def run(tmp_path: Path, ws: Path, graph: str, *args: str) -> dict[str, Any]:
    env = cli_env(tmp_path, None)
    done = run_cli(
        ["run", graph, "--platform-fake", "fake-platform-shop.json", "--json", *args],
        cwd=ws,
        env=env,
        timeout=120,
    )
    assert done.stdout.strip(), done.stderr
    return json.loads(done.stdout)


@pytest.mark.process
def test_profile_not_target_is_not_applicable(tmp_path: Path) -> None:
    assert not_applicable({"format": "kookabug.qa/0", "profiles": ["dev"]}, "dev") is None
    assert not_applicable({"format": "kookabug.qa/0"}, None) is None
    assert not_applicable({"format": "kookabug.qa/0", "profiles": ["dev"]}, None) is not None
    ws = copy_example_workspace(tmp_path)
    edit(ws, BUY, lambda g: g["qa"].update(profiles=["shop_moved"]))
    out = run(tmp_path, ws, BUY)
    assert (out["verdict"], out["code"]) == ("skipped", "qa_not_applicable"), out
    qa = json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))["qa"]
    assert "shop_moved" in qa["not_applicable"]


def test_subgraph_qa_cannot_widen(tmp_path: Path) -> None:
    """서브그래프의 `qa`는 루트 허용을 넓히지 못한다: 루트에 없는 치트는 서브그래프가 허용해도
    거부."""
    from kookabug_core.engine import ExecOptions, FakeClock, MemoryArtifacts
    from kookabug_core.engine.platform_fake import FakePlatform
    from kookabug_core.knowledge import cheats

    ws = copy_example_workspace(tmp_path)
    cheats.adopt(ws, "give_gold", 1, "dev_safe", by="test")
    sub = "subgraphs/cheats/wrap.graph.json"
    (ws / sub).write_text(
        json.dumps(
            {
                "format": "kookabug.graph/0",
                "interface": {"exits": {"done": {"kind": "ok"}}},
                "kind": "subgraph",
                "nodes": {
                    "n_entry": {
                        "next": {"start": "n_cheat"},
                        "type": "core.graph.entry",
                        "version": 1,
                    },
                    "n_cheat": {
                        "config": {"args": {"amount": 1000}, "cheat": "give_gold"},
                        "next": {"done": "n_exit"},
                        "type": "core.qa.cheat",
                        "version": 1,
                    },
                    "n_exit": {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1},
                },
                "plugins": {"core": "0.1.0"},
                "qa": {
                    "cheats": {"allow": [{"id": "give_gold", "max_calls": 99}]},
                    "format": "kookabug.qa/0",
                },
            }
        ),
        encoding="utf-8",
    )
    test = "tests/shop/wrap.graph.json"
    (ws / test).write_text(
        json.dumps(
            {
                "format": "kookabug.graph/0",
                "kind": "test",
                "nodes": {
                    "n_entry": {
                        "next": {"start": "n_call"},
                        "type": "core.graph.entry",
                        "version": 1,
                    },
                    "n_call": {
                        "config": {"graph": sub},
                        "next": {"done": "n_pass"},
                        "type": "core.graph.call",
                        "version": 1,
                    },
                    "n_pass": {"type": "core.test.pass", "version": 1},
                },
                "plugins": {"core": "0.1.0"},
                "qa": {"format": "kookabug.qa/0"},
            }
        ),
        encoding="utf-8",
    )
    program = load_program(Workspace.open(ws), test, secrets=MemorySecrets())
    platform = FakePlatform()
    result = Executor(platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()).run(
        program, ExecOptions()
    )
    assert (result.verdict, result.code) == ("error", "cheat_denied")
    assert "루트 테스트" in result.reason and platform.input.calls == []
