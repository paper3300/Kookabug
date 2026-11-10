"""작업 보고 (M8 계획 3.11) — 항목은 구조화 기록에서, 묶음 키는 결정적, 렌더는 생성 시점 rev."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import adopt as rules
from kookabug_core import basis, cases, filetx
from kookabug_core.agent_job import report as reports
from kookabug_core.knowledge import ops, store
from kookabug_core.knowledge.formats import Actor, KnowledgeError, new_id, now
from kookabug_daemon.client import DaemonError

JOB = "j-20261110-090000-aaaa"
OTHER = "j-20261110-090000-bbbb"
TARGET = "targets/shop/buy.target.json"


def no_secret(_: Any) -> None:
    return None


def agent(job: str) -> Actor:
    return Actor("agent", f"job:{job}", client="fake", job=job)


def facts(run: str, node: str, test: str = "tests/shop/buy_potion.graph.json") -> cases.Facts:
    return cases.Facts(
        run=run,
        test=test,
        graph_sha="0" * 64,
        verdict="fail",
        code="target_not_found",
        node=node,
        node_type="core.image.click",
        claims=(("shop.potion.price", 1),),
    )


def open_case(root: Path, job: str, run: str, node: str, cause: str | None) -> str:
    opened = cases.open_case(
        root, facts(run, node), title=None, evidence=None, actor=agent(job), check_secrets=no_secret
    )
    case_id = str(opened["case"])
    if cause is not None:
        doc, _ = cases.get_case(root, case_id)
        hypothesis = {"cause": cause, "state": "supported", "support": [], "note": "근거"}
        cases.update_case(
            root,
            case_id,
            int(doc["revision"]),
            {
                "hypotheses": [hypothesis],
                "needs": [{"unknown": "구매 단추가 있나", "how": "사람 확인"}],
            }
            if cause == "product_regression"
            else {"hypotheses": [hypothesis]},
            actor=agent(job),
            check_secrets=no_secret,
        )
    return case_id


def target_bytes(root: Path, x: int) -> bytes:
    doc = json.loads((root / TARGET).read_text("utf-8"))
    doc.setdefault("click", {})["offset"] = [x, 0]
    return (json.dumps(doc, ensure_ascii=False, indent=2) + "\n").encode()


def fake_adoption(root: Path, job: str, case_id: str, change_id: str) -> str:
    adoption_id = new_id("a")
    record = {
        "format": "kookabug.adoption/0",
        "id": adoption_id,
        "kind": "auto",
        "case": case_id,
        "change": change_id,
        "files": [{"path": TARGET, "before_sha256": "1" * 64, "after_sha256": "2" * 64}],
        "runs": ["r-1", "r-2", "r-3"],
        "negatives": [{"frame": "neg-shop-sell", "source": "예제"}],
        "policy_sha": "3" * 64,
        "by": {"kind": "kookabug"},
        "at": now(),
        "reverted": None,
    }
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.create(rules.adoption_rel(adoption_id), store.encode(record))
        ops.log_into(
            root,
            tx,
            [
                {
                    "op": "adopt",
                    "file": rules.adoption_rel(adoption_id),
                    "id": adoption_id,
                    "result": "applied",
                }
            ],
            Actor("kookabug", "adopt", job=job),
        )
        tx.commit()
    return adoption_id


def apply(root: Path, job: str, request_id: str, ops_list: list[dict[str, Any]]) -> None:
    ops.apply(
        root, {"request_id": request_id, "ops": ops_list}, actor=agent(job), check_secrets=no_secret
    )


def unknown(question: str, human_only: bool, base: int = 0) -> dict[str, Any]:
    return {
        "op": "add",
        "file": "unknowns",
        "base_revision": base,
        "item": {"question": question, "human_only": human_only, "blocks": [], "how": "확인"},
    }


def setup_records(root: Path) -> dict[str, str]:
    regression = open_case(root, JOB, "r-0001", "n_click_buy", "product_regression")
    ui_case = open_case(root, JOB, "r-0002", "n_click_close", "ui_change")
    plain = open_case(root, JOB, "r-0003", "n_assert_gold", None)
    adopted = basis.write(
        root, {TARGET: target_bytes(root, 3)}, actor=agent(JOB), case=ui_case, kind="locator_repair"
    )
    fake_adoption(root, JOB, ui_case, str(adopted["id"]))
    # 같은 target·같은 원인의 작업 기준 변경 두 개(다른 사건) → 한 묶음
    ui_case2 = open_case(root, JOB, "r-0004", "n_click_buy2", "ui_change")
    ui_case3 = open_case(root, JOB, "r-0005", "n_click_buy3", "ui_change")
    w1 = basis.write(
        root,
        {TARGET: target_bytes(root, 7)},
        actor=agent(JOB),
        case=ui_case2,
        kind="locator_repair",
    )
    w2 = basis.write(
        root,
        {TARGET: target_bytes(root, 9)},
        actor=agent(JOB),
        case=ui_case3,
        kind="locator_repair",
    )
    # 다른 작업의 기록 (양성 대조: 이 보고에 섞이지 않는다)
    open_case(root, OTHER, "r-0009", "n_other", "product_regression")
    apply(root, JOB, "u1", [unknown("구매 단추가 이 빌드에서 빠졌나요?", True)])
    apply(root, JOB, "u1b", [unknown("내부 메모", False, 1)])
    apply(root, OTHER, "u2", [unknown("다른 작업 질문", True, 2)])
    cheat = {
        "op": "add",
        "file": "cheats",
        "base_revision": 1,
        "item": {
            "id": "add_potion",
            "title": "물약 지급",
            "effect": "물약을 count만큼 준다",
            "preconditions": [],
            "args": {"count": {"type": "integer", "min": 1, "max": 10}},
            "impl": {
                "kind": "console",
                "graph": "subgraphs/cheats/console.graph.json",
                "template": "add_potion {count}",
            },
            "env": {},
        },
    }
    apply(root, JOB, "c1", [cheat])
    return {
        "regression": regression,
        "ui": ui_case,
        "plain": plain,
        "w1": str(w1["id"]),
        "w2": str(w2["id"]),
    }


def meta(job: str, playbook: str = "repair") -> dict[str, Any]:
    return {
        "id": job,
        "playbook": playbook,
        "trigger": "manual",
        "agent": {"profile": "custom"},
        "started_at": "2026-11-10T09:00:00Z",
        "budget": {"minutes": 60, "runs": 3},
    }


def test_items_from_records_grouped(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    ids = setup_records(root)
    used = {"runs": 3, "tool_calls": 40, "minutes": 12}
    built = reports.build(
        root,
        meta(JOB),
        state="budget_exhausted",
        used=used,
        notes="요약",
        stalled=["tests/a.graph.json"],
    )
    kinds = {i["kind"] for g in built["groups"] for i in g["items"]}
    assert kinds == {
        "auto_adopted",
        "working_only",
        "regression_suspect",
        "undetermined",
        "cheat_candidate",
        "budget",
        "stalled",
    }
    assert kinds <= set(reports.ITEM_KINDS)
    by_kind = {i["kind"]: (g, i) for g in built["groups"] for i in g["items"]}
    group, item = by_kind["auto_adopted"]
    assert group["key"] == f"auto_adopted|ui_change|{TARGET}"
    assert item["checks"] == ["oracle", "negative:1", "affected:2"]
    group, item = by_kind["regression_suspect"]
    assert item["case"] == ids["regression"] and item["claims"] == [
        {"id": "shop.potion.price", "rev": 1}
    ]
    assert group["key"].startswith("regression_suspect|product_regression|")
    working = [g for g in built["groups"] if g["key"].startswith("working_only|")]
    assert [g["key"] for g in working] == [f"working_only|ui_change|{TARGET}"]
    assert sorted(i["change"] for i in working[0]["items"]) == sorted([ids["w1"], ids["w2"]])
    _, item = by_kind["undetermined"]
    assert item["case"] == ids["plain"]
    # 사람만 답할 수 있는 질문만 (이 작업 것만)
    questions = built["unknowns"]
    assert len(questions) == 1
    assert by_kind["cheat_candidate"][1]["cheat"] == "add_potion"
    assert built["budget"] == {"minutes": [12, 60], "runs": [3, 3]}
    # 다른 작업의 사건은 섞이지 않는다
    other_cases = {
        g["key"]
        for g in reports.build(root, meta(OTHER), state="done", used=used, notes=None)["groups"]
    }
    assert all(not k.startswith(("auto_adopted", "working_only")) for k in other_cases)
    assert not any(
        i.get("case") == ids["regression"]
        for g in reports.build(root, meta(OTHER), state="done", used=used, notes=None)["groups"]
        for i in g["items"]
    )
    # 같은 묶음 키 = 같은 종류·원인·대상. 키에 종류가 들어가 다른 종류가 합쳐지지 않는다
    keys = [g["key"] for g in built["groups"]]
    assert len(keys) == len(set(keys))
    for g in built["groups"]:
        assert {i["kind"] for i in g["items"]} == {g["key"].split("|", 1)[0]}
    # 결정적: 같은 기록이면 같은 묶음
    again = reports.build(
        root,
        meta(JOB),
        state="budget_exhausted",
        used=used,
        notes="요약",
        stalled=["tests/a.graph.json"],
    )
    assert again["groups"] == built["groups"]


def test_render_pins_revisions(tmp_path: Path) -> None:
    root = copy_example_workspace(tmp_path)
    ids = setup_records(root)
    used = {"runs": 1, "tool_calls": 1, "minutes": 1}
    built = reports.build(root, meta(JOB), state="done", used=used, notes=None)
    written = reports.write(root, built)
    assert written["revisions"]["claims"] == {"shop.potion.price": 1}
    md = root / written["rendered"]
    assert "shop.potion.price rev 1" in md.read_text("utf-8")
    name = written["rendered"].removeprefix("wiki/")
    assert f"]({name})" in (root / "wiki" / "index.md").read_text("utf-8")
    # 같은 작업의 보고는 하나 — 다시 써도 덮지 않는다 (종료 경로 멱등)
    assert reports.write(root, {**built, "state": "cancelled"})["state"] == "done"
    # 주장이 그 뒤 바뀐다 (rev 2 — 팀 파일을 거래로 직접 바꾼다)
    shop_rel = "knowledge/features/shop.json"
    doc = json.loads((root / shop_rel).read_text("utf-8"))
    for c in doc["claims"]:
        if c["id"] == "shop.potion.price":
            c["rev"] = 2
    with filetx.locked(root):
        tx = filetx.Tx(root)
        tx.write(
            shop_rel, store.encode(doc), expect_sha=filetx.sha256_of((root / shop_rel).read_bytes())
        )
        tx.commit()
    # 양성 대조: 새로 만든 보고는 rev 2를 본다
    fresh = reports.build(root, meta(JOB), state="done", used=used, notes=None)
    assert fresh["revisions"]["claims"] == {"shop.potion.price": 2}
    # 결정 뒤 다시 렌더해도 생성 시점 rev 1 그대로
    group = f"working_only|ui_change|{TARGET}"
    applied: list[tuple[list[str], bool]] = []

    def apply(changes: list[str], accept: bool, also: Any) -> dict[str, bool]:
        applied.append((changes, accept))
        with filetx.locked(root):
            tx = filetx.Tx(root)
            also(tx)  # 보고 결정은 부르는 쪽 거래 안에서 쓴다
            tx.commit()
        return {"ok": True}

    decided = reports.decide(root, JOB, group, "reject", apply=apply)
    assert len(applied) == 1 and sorted(applied[0][0]) == sorted([ids["w1"], ids["w2"]])
    assert applied[0][1] is False and decided["decision"] == "reject"
    text = md.read_text("utf-8")
    assert "shop.potion.price rev 1" in text and "rev 2" not in text
    assert "결정: reject" in text
    stored = reports.read_report(root, JOB)
    assert stored is not None
    assert next(g for g in stored["groups"] if g["key"] == group)["decision"]["by"] == "human"


GROUP = f"working_only|ui_change|{TARGET}"
CHILD = Path(__file__).parents[1] / "procs" / "report_decide_child.py"


def one_change_report(tmp_path: Path) -> tuple[Path, str, dict[str, Any]]:
    """작업 기준 변경 하나(target offset [7, 0])와 그 보고 (묶음 하나 = 변경 하나)."""
    root = copy_example_workspace(tmp_path)
    case = open_case(root, JOB, "r-0001", "n_click_buy", "ui_change")
    change = str(
        basis.write(
            root,
            {TARGET: target_bytes(root, 7)},
            actor=agent(JOB),
            case=case,
            kind="locator_repair",
        )["id"]
    )
    used = {"runs": 1, "tool_calls": 1, "minutes": 1}
    written = reports.write(
        root, reports.build(root, meta(JOB), state="done", used=used, notes=None)
    )
    return root, change, written


def decide_apply(root: Path) -> Any:
    def apply(changes: list[str], accept: bool, also: Any) -> Any:
        return rules.decide(root, changes=changes, claims=[], accept=accept, by="cli", also=also)

    return apply


def state_of(root: Path, change: str) -> tuple[bytes, str, Any, int]:
    """(팀 target 바이트, 변경 상태, 보고 묶음 결정, 채택 기록 수)."""
    loaded = basis.load_change(root, change)
    assert loaded is not None
    stored = reports.read_report(root, JOB)
    assert stored is not None
    decision = next(g for g in stored["groups"] if g["key"] == GROUP)["decision"]
    return (root / TARGET).read_bytes(), loaded.state, decision, len(rules.list_adoptions(root))


def test_report_decide_atomic(tmp_path: Path) -> None:
    """High 3: 보고 쓰기가 IO로 실패하면 팀 target·변경 상태·채택 기록도 그대로다 (한 거래)."""
    root, change, written = one_change_report(tmp_path)
    before = state_of(root, change)
    assert before[1:] == ("active", None, 0)
    md = root / written["rendered"]
    saved = md.read_bytes()
    md.unlink()
    md.mkdir()  # 렌더 경로가 폴더 → 보고 쓰기의 실제 IO 실패
    with pytest.raises(Exception):  # noqa: B017 — 실패 종류는 IO 계층이 정한다
        reports.decide(root, JOB, GROUP, "accept", apply=decide_apply(root))
    assert state_of(root, change) == before
    assert filetx.journals(root) == []
    # 양성 대조: 렌더 경로를 되돌리면 같은 결정이 전부 반영된다
    md.rmdir()
    md.write_bytes(saved)
    done = reports.decide(root, JOB, GROUP, "accept", apply=decide_apply(root))
    target, state, decision, count = state_of(root, change)
    assert target == target_bytes(root, 7) and state == "accepted" and count == 1
    assert decision["decision"] == "accept" and done["result"]["adoption"]
    assert "결정: accept" in md.read_text("utf-8")
    # 같은 묶음은 다시 결정하지 못한다 (잠금 안 재확인)
    with pytest.raises(KnowledgeError) as caught:
        reports.decide(root, JOB, GROUP, "reject", apply=decide_apply(root))
    assert caught.value.code == "revision_conflict"


def _kill_rule(stage: str) -> str:
    return json.dumps(
        [
            {
                "point": "filetx.stage",
                "role": "supervisor",
                "when": {"event": stage, "nth": 1},
                "action": "exit:9",
            }
        ]
    )


@pytest.mark.process
@pytest.mark.timeout(300)
@pytest.mark.parametrize(("stage", "applied"), [("before_commit", False), ("after_commit", True)])
def test_report_decide_kill_all_or_nothing(tmp_path: Path, stage: str, applied: bool) -> None:
    """거래 중단(kill, B3 고장 주입 지점) 뒤 복구하면 팀 변경·변경 상태·채택 기록·보고 결정이 전부
    반영되거나 전부 안 된다."""
    import os
    import subprocess
    import sys

    root, change, _ = one_change_report(tmp_path)
    before = state_of(root, change)
    env = {**os.environ, "KOOKABUG_FAULTS": _kill_rule(stage)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), JOB, GROUP, "accept"],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9, done.stderr.decode("utf-8", "replace")
    with filetx.file_lock(root):
        filetx.recover(root)
    after = state_of(root, change)
    if applied:
        assert after[0] == target_bytes(root, 7) and after[1] == "accepted" and after[3] == 1
        assert after[2] is not None and after[2]["decision"] == "accept"
    else:
        assert after == before
    assert filetx.journals(root) == []


def test_init_summary_from_records(tmp_path: Path) -> None:
    """Init의 결정적 부분 (3.12): 요약 수는 이 작업의 기록(미지수·치트 후보)에서 센다."""
    root = copy_example_workspace(tmp_path)
    setup_records(root)
    used = {"runs": 0, "tool_calls": 1, "minutes": 1}
    built = reports.build(root, meta(JOB, "init"), state="done", used=used, notes=None)
    summary = next(
        i["summary"] for g in built["groups"] for i in g["items"] if i["kind"] == "init_summary"
    )
    assert summary["unknowns"] == 2 and summary["cheat_candidates"] == 1
    # 양성 대조: init이 아니면 요약 항목이 없다
    other = reports.build(root, meta(JOB), state="done", used=used, notes=None)
    assert "init_summary" not in {i["kind"] for g in other["groups"] for i in g["items"]}


@pytest.mark.process
@pytest.mark.timeout(300)
def test_note_secret_checked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`kb_report_note`(job.note)의 글은 글자 검사를 거친다. 걸린 글은 저장하지 않고 보고에도
    없다."""
    secret = "Qx7-note-secret-991"
    monkeypatch.setenv("KOOKABUG_SECRET_ACC_PW", secret)
    root = copy_example_workspace(tmp_path)
    local = root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "curator"}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    with ThreadDaemon(root) as d:
        d.daemon.guard.secret_keys = {"acc.pw"}  # 이 워크스페이스에서 비밀값을 넣은 적이 있다
        job = d.begin_job({"playbook": "repair"})
        info = {
            "kind": "agent",
            "name": "mcp",
            "version": "0",
            "id": job["agent_id"],
            "attended": False,
            "job_token": job["token"],
        }
        with d.client(info) as conn:
            conn.call("agent.toolsets.enable", {"toolsets": ["cases"]})
            with pytest.raises(DaemonError) as caught:
                conn.call("job.note", {"text": f"로그인 비밀번호는 {secret} 이다"})
            assert caught.value.kind == "secret_in_text"
            assert secret not in json.dumps(caught.value.data, ensure_ascii=False)
            # 양성 대조: 깨끗한 글은 받는다
            conn.call("job.note", {"text": "구매 단추가 옮겨졌다"})
        with d.client() as ui:
            ended = ui.call("job.finish", {"job": job["job"]}, timeout=300)
    stored = reports.read_report(root, job["job"])
    assert stored is not None and stored["notes"] == "구매 단추가 옮겨졌다"
    rendered = (root / ended["report"]).read_text("utf-8")
    assert "구매 단추가 옮겨졌다" in rendered and secret not in rendered
    assert secret not in (root / "knowledge" / "log.jsonl").read_text("utf-8")
