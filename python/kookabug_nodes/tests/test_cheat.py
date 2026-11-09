"""치트 노드 `core.qa.cheat` (M8 계획 3.5·9장 R2) — 엄격: 치트.

실행 허용 = 워크스페이스 사용 ∩ 사람 채택(실행 스냅샷에서 다시 계산한 digest) ∩ 무인 분류 ∩ 루트
`qa.cheats.allow` ∩ 서브그래프 `qa`(줄이기만) ∩ `max_calls`(루트 실행 전체) ∩ 대상 프로필. 거부는
실행 오류(`cheat_denied`·`cheat_not_adopted`)이고 구현 서브그래프는 돌지 않는다(입력 0).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.engine import ExecOptions, Executor, FakeClock, MemoryArtifacts, RunResult
from kookabug_core.engine.platform_fake import FakePlatform
from kookabug_core.knowledge import cheats
from kookabug_core.knowledge.formats import KnowledgeError
from kookabug_core.loader import load_program
from kookabug_core.workspace import MemorySecrets, RunOptions, Workspace

TEST = "tests/t.graph.json"
CONSOLE = "subgraphs/cheats/console.graph.json"
NESTED = "subgraphs/wrap.graph.json"


def _write(root: Path, rel: str, value: Any) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def console_graph(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    nodes: dict[str, Any] = {
        "n_entry": {"next": {"start": "n_open"}, "type": "core.graph.entry", "version": 1},
        "n_open": {
            "in": {"keys": "`"},
            "next": {"done": "n_type"},
            "type": "core.input.key",
            "version": 1,
        },
        "n_type": {
            "in": {"text": {"$link": "n_entry.command"}},
            "next": {"done": "n_run"},
            "type": "core.input.type_text",
            "version": 1,
        },
        "n_run": {
            "in": {"keys": "enter"},
            "next": {"done": "n_exit"},
            "type": "core.input.key",
            "version": 1,
        },
        "n_exit": {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1},
    }
    nodes.update(extra or {})
    return {
        "format": "kookabug.graph/0",
        "interface": {"exits": {"done": {"kind": "ok"}}, "inputs": {"command": {"type": "string"}}},
        "kind": "subgraph",
        "nodes": nodes,
        "plugins": {"core": "0.1.0"},
    }


def cheat_def(**over: Any) -> dict[str, Any]:
    item = {
        "adoption": None,
        "args": {"amount": {"max": 100000, "min": 1, "type": "integer"}},
        "effect": "골드를 amount만큼 늘린다",
        "env": {},
        "id": "give_gold",
        "impl": {"graph": CONSOLE, "kind": "console", "template": "give_gold {amount}"},
        "origin": {"kind": "human"},
        "rev": 1,
        "title": "골드 지급",
    }
    item.update(over)
    return item


def graph_with(
    calls: list[dict[str, Any]],
    *,
    allow: list[dict[str, Any]] | None = None,
    qa: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`calls`: 차례대로 부를 노드 (`{"cheat": …, "args": …}` 또는 `{"graph": 서브그래프}`)."""
    nodes: dict[str, Any] = {"n_entry": {"type": "core.graph.entry", "version": 1}}
    prev, exit_name = "n_entry", "start"
    for i, call in enumerate(calls):
        nid = f"n_{i}"
        if "graph" in call:
            nodes[nid] = {
                "config": {"graph": call["graph"]},
                "type": "core.graph.call",
                "version": 1,
            }
            out = "done"
        else:
            nodes[nid] = {
                "config": {
                    "args": call.get("args", {"amount": 10}),
                    "cheat": call.get("cheat", "give_gold"),
                },
                "type": "core.qa.cheat",
                "version": 1,
            }
            out = "done"
        nodes[prev].setdefault("next", {})[exit_name] = nid
        prev, exit_name = nid, out
    nodes["n_pass"] = {"type": "core.test.pass", "version": 1}
    nodes[prev].setdefault("next", {})[exit_name] = "n_pass"
    if qa is None:
        qa = {"format": "kookabug.qa/0"}
        if allow is not None:
            qa["cheats"] = {"allow": allow}
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": nodes,
        "plugins": {"core": "0.1.0"},
        "qa": qa,
    }


def wrap_graph(calls: int = 1, qa: dict[str, Any] | None = None) -> dict[str, Any]:
    """치트 노드를 `calls`번 부르는 서브그래프 (중첩 검사)."""
    nodes: dict[str, Any] = {"n_entry": {"type": "core.graph.entry", "version": 1}}
    prev, exit_name = "n_entry", "start"
    for i in range(calls):
        nid = f"n_c{i}"
        nodes[nid] = {
            "config": {"args": {"amount": 10}, "cheat": "give_gold"},
            "type": "core.qa.cheat",
            "version": 1,
        }
        nodes[prev].setdefault("next", {})[exit_name] = nid
        prev, exit_name = nid, "done"
    nodes["n_exit"] = {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1}
    nodes[prev].setdefault("next", {})[exit_name] = "n_exit"
    graph: dict[str, Any] = {
        "format": "kookabug.graph/0",
        "interface": {"exits": {"done": {"kind": "ok"}}},
        "kind": "subgraph",
        "nodes": nodes,
        "plugins": {"core": "0.1.0"},
    }
    if qa is not None:
        graph["qa"] = qa
    return graph


ALLOW = [{"id": "give_gold", "max_calls": 3, "args": {"amount": {"max": 1000}}}]


def make_ws(
    tmp_path: Path,
    *,
    unattended: bool = True,
    enabled: bool = True,
    cheat: dict[str, Any] | None = None,
    adopt: bool = True,
    graph: dict[str, Any] | None = None,
) -> Path:
    root = tmp_path / "ws"
    _write(
        root,
        "kookabug.json",
        {
            "format": "kookabug.workspace/0",
            "profiles": {"dev": {"settings": {}}},
            "settings": {"console.key": "`"},
            "cheats": {
                "categories": [
                    {"id": "dev_safe", "title": "개발 무해", "unattended": unattended},
                    {"id": "manual", "title": "사람 있을 때만", "unattended": False},
                ],
                "enabled": enabled,
            },
        },
    )
    _write(root, CONSOLE, console_graph())
    _write(
        root,
        "knowledge/cheats.json",
        {"cheats": [cheat or cheat_def()], "format": "kookabug.cheats/0", "revision": 1},
    )
    _write(root, TEST, graph if graph is not None else graph_with([{}], allow=ALLOW))
    if adopt:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="test")
    return root


def run(
    root: Path, *, unattended: bool = False, profile: str | None = None
) -> tuple[RunResult, FakePlatform]:
    platform = FakePlatform()
    program = load_program(
        Workspace.open(root), TEST, options=RunOptions(profile=profile), secrets=MemorySecrets()
    )
    result = Executor(platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()).run(
        program, ExecOptions(unattended=unattended)
    )
    return result, platform


def typed(platform: FakePlatform) -> list[str]:
    return [str(c.args[0]) for c in platform.input.calls if c.method == "type_text"]


def assert_denied(result: RunResult, platform: FakePlatform, code: str = "cheat_denied") -> None:
    assert (result.verdict, result.code) == ("error", code), result.reason
    assert platform.input.calls == []  # 구현 서브그래프는 돌지 않았다


# ---------------------------------------------------------------- 통과


def test_adopted_cheat_runs_template_command(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    result, platform = run(root, unattended=True)
    assert result.verdict == "pass", result.reason
    assert typed(platform) == ["give_gold 10"]
    assert [c.args[0] for c in platform.input.calls if c.method == "key"] == ["`", "enter"]
    assert result.qa is not None and result.qa.cheats["give_gold"]["calls"] == 1


# ---------------------------------------------------------------- 채택·digest


def test_unadopted_cheat_denied(tmp_path: Path) -> None:
    root = make_ws(tmp_path, adopt=False)
    assert_denied(*run(root), code="cheat_not_adopted")
    # 사용 꺼짐도 같은 자리에서 막힌다
    root2 = make_ws(tmp_path / "off", enabled=False)
    assert_denied(*run(root2))


def test_digest_mismatch_denied(tmp_path: Path) -> None:
    root = make_ws(tmp_path)
    # 정의 파일을 손으로 바꿔 채택을 그대로 둔 채 템플릿만 바꾼다 (지식 연산을 거치지 않은 수정)
    path = root / "knowledge" / "cheats.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["cheats"][0]["impl"]["template"] = "give_gold {amount} extra"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert_denied(*run(root), code="cheat_not_adopted")


def test_cheat_impl_file_change_invalidates_adoption(tmp_path: Path) -> None:
    """R2: 구현 폐포의 실제 파일·노드 구현이 바뀌면 그 뒤 실행이 거부된다."""
    root = make_ws(tmp_path)
    assert run(root)[0].verdict == "pass"
    # 1) 구현 서브그래프 파일 한 바이트
    sub = root / CONSOLE
    original = sub.read_bytes()
    sub.write_bytes(original + b"\n")
    assert_denied(*run(root), code="cheat_not_adopted")
    sub.write_bytes(original)
    assert run(root)[0].verdict == "pass"
    # 2) 구현이 쓰는 노드의 구현 revision (코어 노드 소스가 바뀐 것과 같다)
    from kookabug_core.knowledge import cheats as cheats_mod

    real = cheats_mod.node_revision

    def changed(node_type: str, *args: Any) -> str | None:
        rev = real(node_type, *args)
        return None if rev is None else ("0" * 63 + "1" if node_type == "core.input.key" else rev)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cheats_mod, "node_revision", changed)
        assert_denied(*run(root), code="cheat_not_adopted")
    assert run(root)[0].verdict == "pass"


def test_dynamic_dependency_refuses_adoption(tmp_path: Path) -> None:
    """로더가 못 찾는 미해결·동적 의존성($setting·$secret·없는 파일·중첩 치트)은 채택 검증 거부."""
    root = make_ws(tmp_path, adopt=False)
    cases = {
        "setting": {
            "n_extra": {
                "in": {"keys": {"$setting": "console.key"}},
                "type": "core.input.key",
                "version": 1,
            }
        },
        "secret": {
            "n_extra": {
                "in": {"text": {"$secret": "admin.password"}},
                "type": "core.input.type_text",
                "version": 1,
            }
        },
        "missing": {
            "n_extra": {
                "config": {"graph": "subgraphs/none.graph.json"},
                "type": "core.graph.call",
                "version": 1,
            }
        },
        "nested": {
            "n_extra": {"config": {"cheat": "give_gold"}, "type": "core.qa.cheat", "version": 1}
        },
    }
    for name, extra in cases.items():
        _write(root, CONSOLE, console_graph(extra))
        with pytest.raises(KnowledgeError) as caught:
            cheats.adopt(root, "give_gold", 1, "dev_safe", by="test")
        assert caught.value.code == "cheat_not_adoptable", name
    # 채택 뒤 구현에 동적 의존성이 생기면 실행도 거부한다
    _write(root, CONSOLE, console_graph())
    cheats.adopt(root, "give_gold", 1, "dev_safe", by="test")
    _write(root, CONSOLE, console_graph(cases["setting"]))
    assert_denied(*run(root), code="cheat_not_adopted")


# ---------------------------------------------------------------- 무인·범위·인자


def test_unattended_needs_category_flag(tmp_path: Path) -> None:
    root = make_ws(tmp_path, unattended=False)
    assert_denied(*run(root, unattended=True))
    assert run(root, unattended=False)[0].verdict == "pass"  # 사람 있는 실행은 된다


def test_root_allow_required_and_profile(tmp_path: Path) -> None:
    root = make_ws(tmp_path, graph=graph_with([{}], allow=None))
    assert_denied(*run(root))  # 루트 qa.cheats.allow에 없다
    env_root = make_ws(tmp_path / "env", cheat=cheat_def(env={"profiles": ["dev"]}))
    assert_denied(*run(env_root, profile=None))
    assert run(env_root, profile="dev")[0].verdict == "pass"


@pytest.mark.parametrize(
    "args",
    [
        {"amount": "10; give_gold 99999"},
        {"amount": "10\ngive_gold 99999"},
        {"amount": 1001},  # 루트 qa 범위 밖
        {"amount": 0},  # 정의 범위 밖
        {"amount": True},
        {"amount": 10, "extra": 1},
        {},
    ],
)
def test_args_injection_rejected(tmp_path: Path, args: dict[str, Any]) -> None:
    root = make_ws(tmp_path, graph=graph_with([{"args": args}], allow=ALLOW))
    result, platform = run(root)
    assert_denied(result, platform)
    assert "99999" not in result.reason and "\n" not in result.reason


def test_id_and_enum_args_rejected(tmp_path: Path) -> None:
    cheat = cheat_def(
        args={"item": {"type": "id"}, "mode": {"type": "enum", "values": ["a", "b"]}},
        impl={"graph": CONSOLE, "kind": "console", "template": "give {item} {mode}"},
    )
    allow = [{"id": "give_gold", "max_calls": 5}]
    for bad in (
        {"item": "x;y", "mode": "a"},
        {"item": "x y", "mode": "a"},
        {"item": "ok", "mode": "c"},
    ):
        root = make_ws(
            tmp_path / str(len(str(bad))) / bad["item"].replace(";", "_").replace(" ", "_"),
            cheat=cheat,
            graph=graph_with([{"args": bad}], allow=allow),
        )
        assert_denied(*run(root))
    good = make_ws(
        tmp_path / "good",
        cheat=cheat,
        graph=graph_with([{"args": {"item": "potion.small", "mode": "b"}}], allow=allow),
    )
    result, platform = run(good)
    assert result.verdict == "pass" and typed(platform) == ["give potion.small b"]


def test_max_calls(tmp_path: Path) -> None:
    allow = [{"id": "give_gold", "max_calls": 2}]
    root = make_ws(tmp_path, graph=graph_with([{}, {}], allow=allow))
    assert run(root)[0].verdict == "pass"
    over = make_ws(tmp_path / "over", graph=graph_with([{}, {}, {}], allow=allow))
    result, platform = run(over)
    assert (result.verdict, result.code) == ("error", "cheat_denied")
    assert typed(platform) == ["give_gold 10", "give_gold 10"]  # 두 번은 갔고 세 번째에서 멈춤


def test_cheat_call_event_before_assertions(tmp_path: Path) -> None:
    graph = graph_with([{}], allow=ALLOW)
    # 치트 뒤에 검증 노드 하나: 치트 기록은 "판정 노드보다 앞"
    nodes = graph["nodes"]
    nodes["n_0"]["next"] = {"done": "n_assert"}
    nodes["n_assert"] = {
        "in": {"a": 1, "b": 1, "op": "=="},
        "next": {"ok": "n_cheat2"},
        "type": "core.assert.compare",
        "version": 1,
    }
    nodes["n_cheat2"] = {
        "config": {"args": {"amount": 5}, "cheat": "give_gold"},
        "next": {"done": "n_pass"},
        "type": "core.qa.cheat",
        "version": 1,
    }
    root = make_ws(tmp_path, graph=graph)
    result, _ = run(root)
    assert result.verdict == "pass", result.reason
    events = [e for e in result.events if e["event"] == "cheat.call"]
    assert [e["before_assertions"] for e in events] == [True, False]
    assert {e["cheat"] for e in events} == {"give_gold"} and all(
        len(e["digest"]) == 64 for e in events
    )
    assert "args" not in events[0] and len(events[0]["args_digest"]) == 64


# ---------------------------------------------------------------- 중첩 (R2)


def test_nested_cheat_restriction_intersection(tmp_path: Path) -> None:
    # 서브그래프가 qa로 범위를 줄이면 그 범위가 적용된다 (루트 max 1000 ∩ 서브 max 5 → 10은 거부)
    narrow = {
        "cheats": {"allow": [{"id": "give_gold", "max_calls": 3, "args": {"amount": {"max": 5}}}]},
        "format": "kookabug.qa/0",
    }
    root = make_ws(tmp_path, graph=graph_with([{"graph": NESTED}], allow=ALLOW))
    _write(root, NESTED, wrap_graph(qa=narrow))
    assert_denied(*run(root))
    # 서브그래프가 넓히려 해도(루트 허용 없음) 거부된다
    wide = {"cheats": {"allow": [{"id": "give_gold", "max_calls": 99}]}, "format": "kookabug.qa/0"}
    root2 = make_ws(tmp_path / "wide", graph=graph_with([{"graph": NESTED}], allow=None))
    _write(root2, NESTED, wrap_graph(qa=wide))
    assert_denied(*run(root2))
    # 서브그래프가 그 치트를 빼면 거부, qa가 없으면 루트 범위 그대로 통과
    other = {"cheats": {"allow": []}, "format": "kookabug.qa/0"}
    _write(root2, NESTED, wrap_graph(qa=other))
    _write(root2, TEST, graph_with([{"graph": NESTED}], allow=ALLOW))
    assert_denied(*run(root2))
    _write(root2, NESTED, wrap_graph())
    assert run(root2)[0].verdict == "pass"


def test_nested_calls_share_root_budget(tmp_path: Path) -> None:
    allow = [{"id": "give_gold", "max_calls": 2}]
    root = make_ws(
        tmp_path,
        graph=graph_with([{"graph": NESTED}, {"graph": NESTED}, {"graph": NESTED}], allow=allow),
    )
    _write(root, NESTED, wrap_graph())
    result, platform = run(root)
    assert (result.verdict, result.code) == ("error", "cheat_denied")
    assert typed(platform) == [
        "give_gold 10",
        "give_gold 10",
    ]  # 서브그래프 호출마다 새로 세지 않는다


# ---------------------------------------------------------------- knowledge/ 아래 실행 의존성 (R2)

PAYLOAD = "knowledge/working/payload.graph.json"


def wrapper_graph(target: str = PAYLOAD) -> dict[str, Any]:
    """`command`를 그대로 다른 서브그래프로 넘기는 콘솔 구현 (검수 재현)."""
    return {
        "format": "kookabug.graph/0",
        "interface": {"exits": {"done": {"kind": "ok"}}, "inputs": {"command": {"type": "string"}}},
        "kind": "subgraph",
        "nodes": {
            "n_entry": {"next": {"start": "n_call"}, "type": "core.graph.entry", "version": 1},
            "n_call": {
                "config": {"graph": target},
                "in": {"command": {"$link": "n_entry.command"}},
                "next": {"done": "n_exit"},
                "type": "core.graph.call",
                "version": 1,
            },
            "n_exit": {"config": {"exit": "done"}, "type": "core.graph.exit", "version": 1},
        },
        "plugins": {"core": "0.1.0"},
    }


def forge_adoption(root: Path) -> None:
    """채택 거부 규칙이 없다고 치고 계산한 digest로 채택 기록을 손으로 쓴다 (실행 쪽 거부 검사)."""
    from kookabug_core.knowledge.formats import cheat_digest

    ws = Workspace.open(root)
    closure = cheats.graph_closure(ws, CONSOLE)
    path = root / "knowledge" / "cheats.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    cheat = doc["cheats"][0]
    nodes = {t: r for t, r in closure.nodes.items() if r is not None}
    digest = cheat_digest(cheat, closure=closure.digest, nodes=nodes)
    cheat["adoption"] = {
        "at": "2026-11-09T00:00:00Z",
        "by": "human",
        "category": "dev_safe",
        "digest": digest,
    }
    path.write_text(json.dumps(doc), encoding="utf-8")


def run_snapshot(root: Path, tmp_path: Path) -> tuple[RunResult, FakePlatform]:
    """제품 실행과 같이 스냅샷을 만들고 그 프로그램을 돌린다."""
    from kookabug_core.record.snapshot import take_snapshot

    snap = take_snapshot(Workspace.open(root), TEST, tmp_path / "snap", secrets=MemorySecrets())
    platform = FakePlatform()
    result = Executor(platform=platform, clock=FakeClock(), artifacts=MemoryArtifacts()).run(
        snap.program, ExecOptions(unattended=True)
    )
    return result, platform


def test_knowledge_subgraph_change_invalidates_adoption(tmp_path: Path) -> None:
    root = make_ws(tmp_path, adopt=False)
    _write(root, CONSOLE, wrapper_graph())
    _write(root, PAYLOAD, console_graph())
    # 사람 채택도 거부한다: 실행 의존성이 knowledge/ 아래
    with pytest.raises(KnowledgeError) as caught:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="review")
    assert caught.value.code == "cheat_not_adoptable"
    assert "knowledge_dependency" in caught.value.message
    # 그 파일은 폐포 digest에 든다 (위치와 무관)
    before = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert PAYLOAD in before.files
    # 채택 기록이 이미 있어도(손으로 쓴 것) 실행 스냅샷에서 거부, 입력 없음
    forge_adoption(root)
    result, platform = run_snapshot(root, tmp_path / "a")
    assert (result.verdict, result.code) == ("error", "cheat_not_adopted"), result.reason
    assert platform.input.calls == []
    # 검수 재현: 대상 파일의 입력 상수만 바꿔도 digest가 바뀌고 실행은 거부된다
    payload = console_graph()
    payload["nodes"]["n_type"]["in"]["text"] = "give_gold 99999"
    _write(root, PAYLOAD, payload)
    after = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert after.digest != before.digest
    result, platform = run_snapshot(root, tmp_path / "b")
    assert (result.verdict, result.code) == ("error", "cheat_not_adopted"), result.reason
    assert typed(platform) == [] and platform.input.calls == []


def _target_node(target: str) -> dict[str, Any]:
    return {
        "n_look": {"in": {"target": {"$target": target}}, "type": "core.image.wait", "version": 1}
    }


def test_knowledge_target_and_image_change_refused(tmp_path: Path) -> None:
    import subprocess

    root = make_ws(tmp_path, adopt=False)
    target = "knowledge/assets/x.target.json"
    _write(root, target, {"format": "kookabug.target/0", "image": "x.png"})
    (root / "knowledge" / "assets" / "x.png").write_bytes(b"png-1")
    _write(root, CONSOLE, console_graph(_target_node(target)))
    first = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert {target, "knowledge/assets/x.png"} <= set(first.files)
    assert f"knowledge_dependency:{target}" in first.problems
    assert "knowledge_dependency:knowledge/assets/x.png" in first.problems
    with pytest.raises(KnowledgeError) as caught:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="t")
    assert caught.value.code == "cheat_not_adoptable"
    # 이미지 한 바이트, target 파일 한 바이트가 바뀌어도 digest가 바뀐다
    (root / "knowledge" / "assets" / "x.png").write_bytes(b"png-2")
    second = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert second.digest != first.digest
    # 대소문자를 바꾼 경로·정션 별칭도 knowledge/로 본다
    _write(root, CONSOLE, console_graph(_target_node("Knowledge/assets/x.target.json")))
    assert any(
        p.startswith("knowledge_dependency:")
        for p in cheats.graph_closure(Workspace.open(root), CONSOLE).problems
    )
    alias = root / "subgraphs" / "kdir"
    done = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(root / "knowledge" / "assets")],
        capture_output=True,
    )
    if done.returncode == 0:
        _write(root, CONSOLE, console_graph(_target_node("subgraphs/kdir/x.target.json")))
        problems = cheats.graph_closure(Workspace.open(root), CONSOLE).problems
        assert "knowledge_dependency:subgraphs/kdir/x.target.json" in problems


def test_knowledge_metadata_excluded_without_self_invalidation(tmp_path: Path) -> None:
    """치트 정의 파일(메타데이터)은 폐포에 넣지 않는다: 구현에 qa가 있어도 채택이 자기를 무효로
    만들지 않는다."""
    root = make_ws(tmp_path, adopt=False)
    impl = console_graph()
    impl["qa"] = {
        "cheats": {"allow": [{"id": "give_gold", "max_calls": 5}]},
        "format": "kookabug.qa/0",
    }
    _write(root, CONSOLE, impl)
    closure = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert "knowledge/cheats.json" not in closure.files and closure.problems == ()
    cheats.adopt(root, "give_gold", 1, "dev_safe", by="t")
    assert run(root, unattended=True)[0].verdict == "pass"


def test_plugin_node_in_impl_refused(tmp_path: Path) -> None:
    """플러그인 노드는 실행 중 설정·환경을 읽을 수 있어(폐포 밖 바이트) 잠금에 있어도 구현에
    못 쓴다."""
    root = make_ws(tmp_path, adopt=False)
    extra = {"n_extra": {"type": "acme.console.send", "version": 1}}
    _write(root, CONSOLE, console_graph(extra))
    lock = {"acme": {"schema_sha256": "a" * 64, "version": "1.0.0", "wheel_sha256": "b" * 64}}
    closure = cheats.graph_closure(Workspace.open(root), CONSOLE, plugins=lock)
    assert closure.nodes["acme.console.send"] is not None  # 구현 revision은 잠금으로 안다
    assert "impl_node_not_allowed:acme.console.send" in closure.problems
    with pytest.raises(KnowledgeError) as caught:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="t")
    assert caught.value.code == "cheat_not_adoptable"


# ---------------------------------------------------------------- 구현 노드 허용 목록 (3라운드)


def judge_console() -> dict[str, Any]:
    """검수 재현: CLI 판단 노드의 답(`reason`)을 콘솔에 친다 (사용자 Agent 설정이 글자를 정한다)."""
    graph = console_graph(
        {
            "n_judge": {
                "type": "core.agent.cli_judge",
                "version": 1,
                "config": {"choices": ["ok"], "agent": "review"},
                "in": {"prompt": "review", "timeout_ms": 10000},
                "next": {"ok": "n_type"},
            }
        }
    )
    graph["nodes"]["n_open"]["next"] = {"done": "n_judge"}
    graph["nodes"]["n_type"]["in"]["text"] = {"$link": "n_judge.reason"}
    return graph


def test_cli_judge_settings_change_invalidates_adoption(tmp_path: Path) -> None:
    """CLI 판단 노드는 그래프 밖 사용자 Agent 설정(명령·args·env)을 읽어 입력 글자를 바꿀 수
    있다 — 허용 목록 밖이라 채택이 거부되고, 채택 기록이 있어도 실행은 구현 진입 전에 거부된다."""
    root = make_ws(tmp_path, adopt=False)
    _write(root, CONSOLE, judge_console())
    closure = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert "impl_node_not_allowed:core.agent.cli_judge" in closure.problems
    with pytest.raises(KnowledgeError) as caught:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="review")
    assert caught.value.code == "cheat_not_adoptable"
    forge_adoption(root)
    result, platform = run_snapshot(root, tmp_path / "a")
    assert (result.verdict, result.code) == ("error", "cheat_not_adopted"), result.reason
    assert platform.input.calls == []


def test_impl_allowlist_nodes_read_no_outside_bytes() -> None:
    """허용 목록 노드의 실행 함수는 실행 중 설정·판단(사용자 Agent 설정)·외부 프로세스·OCR·환경
    변수·파일을 쓰지 않는다. 엔진 노드는 호출 프레임만 다루는 그래프 경계 노드뿐이다."""
    import inspect

    from kookabug_core.knowledge.cheats import IMPL_NODE_TYPES
    from kookabug_core.registry import default_registry

    registry = default_registry()
    forbidden = (
        "ctx.setting",
        "judge",
        "ctx.process",
        "ctx.ocr",
        "read_area",
        "environ",
        "getenv",
        "subprocess",
        "open(",
        "Path(",
    )
    for node_type in sorted(IMPL_NODE_TYPES):
        nodedef = registry.get(node_type)
        assert nodedef is not None and nodedef.function is not None, node_type
        assert nodedef.effects <= {"input", "capture"}, node_type
        if nodedef.engine is not None:
            assert node_type in {"core.graph.entry", "core.graph.exit", "core.graph.call"}
            continue
        fn = getattr(nodedef.function, "__wrapped__", nodedef.function)
        source = inspect.getsource(fn)
        assert [t for t in forbidden if t in source] == [], node_type
    for outside in (
        "core.agent.cli_judge",
        "core.agent.api_judge",
        "core.ocr.read",
        "core.ocr.wait_text",
        "core.assert.text",
        "core.app.launch",
        "core.var.get",
        "core.qa.cheat",
    ):
        assert outside not in IMPL_NODE_TYPES


# ---------------------------------------------------------------- 스냅샷이 원본 위치 판정을 남긴다


ALIAS = "subgraphs/review_alias/payload.graph.json"


def _junction_payload(root: Path) -> bool:
    """`subgraphs/review_alias`를 `knowledge/review_payload`로 옮기고 원래 자리에 정션."""
    import shutil
    import subprocess

    shutil.move(
        str(root / "subgraphs" / "review_alias"), str(root / "knowledge" / "review_payload")
    )
    done = subprocess.run(
        [
            "cmd",
            "/c",
            "mklink",
            "/J",
            str(root / "subgraphs" / "review_alias"),
            str(root / "knowledge" / "review_payload"),
        ],
        capture_output=True,
    )
    return done.returncode == 0


def test_snapshot_preserves_knowledge_junction_refusal(tmp_path: Path) -> None:
    root = make_ws(tmp_path, adopt=False)
    _write(root, ALIAS, console_graph())
    _write(root, CONSOLE, wrapper_graph(ALIAS))
    cheats.adopt(root, "give_gold", 1, "dev_safe", by="review")  # 정상 위치: 채택된다
    result, platform = run_snapshot(root, tmp_path / "ok")
    assert result.verdict == "pass" and typed(platform) == ["give_gold 10"]
    if not _junction_payload(root):
        pytest.skip("정션을 만들 수 없다")
    # 원본에서는 금지 위치, 다시 채택하면 거부
    source = cheats.graph_closure(Workspace.open(root), CONSOLE)
    assert f"knowledge_dependency:{ALIAS}" in source.problems
    with pytest.raises(KnowledgeError):
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="review")
    # 바이트는 그대로라 digest는 같지만, 스냅샷 실행은 원본 판정으로 거부한다
    from kookabug_core.record.snapshot import take_snapshot

    snap = take_snapshot(Workspace.open(root), TEST, tmp_path / "s", secrets=MemorySecrets())
    assert f"knowledge_dependency:{ALIAS}" in snap.program.cheat_checks["give_gold"]
    result, platform = run_snapshot(root, tmp_path / "junction")
    assert (result.verdict, result.code) == ("error", "cheat_not_adopted"), result.reason
    assert platform.input.calls == []


def test_snapshot_copy_time_location_kept_when_check_is_fooled(tmp_path: Path) -> None:
    """원본 판정이 (복사 뒤 바꿔치기 등으로) 금지 위치를 놓쳐도, 복사할 때 실경로가 knowledge/였던
    파일이 구현 폐포에 있으면 거부한다."""
    root = make_ws(tmp_path, adopt=False)
    _write(root, ALIAS, console_graph())
    _write(root, CONSOLE, wrapper_graph(ALIAS))
    cheats.adopt(root, "give_gold", 1, "dev_safe", by="review")
    if not _junction_payload(root):
        pytest.skip("정션을 만들 수 없다")
    from kookabug_core.knowledge import cheats as cheats_mod

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cheats_mod, "_under_knowledge", lambda workspace, rel: False)
        result, platform = run_snapshot(root, tmp_path / "fooled")
    assert (result.verdict, result.code) == ("error", "cheat_not_adopted"), result.reason
    assert platform.input.calls == []
    with pytest.raises(KnowledgeError) as caught:
        cheats.adopt(root, "give_gold", 1, "dev_safe", by="t")
    assert caught.value.code == "cheat_not_adoptable"
