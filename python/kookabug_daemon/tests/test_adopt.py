"""자동 채택·되돌리기·묶음 수락 (M8 계획 3.8·E5·E6·9장 R1, B3).

엄격: 사용자 파일 손상·채택 조건 우회.

- 검증 실행은 Kookabug가 고르고, 그 변경 하나만 덧씌운 manifest 폐포 바이트로만 돈다
- 조건이 하나라도 실패하면 팀 파일·채택 기록·사건이 그대로이고 변경은 작업 기준에 남는다
- 게시는 채택 잠금 안에서 후보·정책·판정 의존성·누적 상한을 다시 확인한다(R1)
- 모든 실패 지점(예외·kill)에서 복구 뒤 "원래" 또는 "전부" 둘 중 하나
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from helpers.adopt_rig import (
    AFFECTED,
    AGENT,
    ASSERTIONS,
    CASE,
    CLAIM,
    IMAGE,
    TARGET,
    TEST,
    FakeVerifier,
    adoptions,
    case_doc,
    moved_target,
    setup,
    sha,
    write_case,
)

from kb_testing.daemon import ThreadDaemon
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import adopt as rules
from kookabug_core import basis, filetx
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError
from kookabug_core.workspace import Workspace
from kookabug_daemon.adopt import Adopter, Negative
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_sdk import _faults

CHILD = Path(__file__).resolve().parents[2] / "kookabug_core" / "tests" / "procs" / "adopt_child.py"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return copy_example_workspace(tmp_path)


def team_tree(ws: Path) -> dict[str, str]:
    """팀 기준 파일 전부의 sha (tests·subgraphs·targets·screens·kookabug.json)."""
    out = {"kookabug.json": sha((ws / "kookabug.json").read_bytes())}
    for top in ("tests", "subgraphs", "targets", "screens"):
        for path in sorted((ws / top).rglob("*")):
            if path.is_file():
                out[path.relative_to(ws).as_posix()] = sha(path.read_bytes())
    return out


def change_state(ws: Path, change_id: str) -> str:
    change = basis.load_change(ws, change_id)
    assert change is not None
    return change.state


def adopt(
    ws: Path, change_id: str, verifier: FakeVerifier | None = None, **kw: Any
) -> dict[str, Any]:
    return Adopter(ws, verifier or FakeVerifier()).request(CASE, change_id, **kw)


def assert_nothing_published(ws: Path, before: dict[str, str], change_id: str) -> None:
    assert team_tree(ws) == before
    assert adoptions(ws) == []
    assert case_doc(ws)["state"] == "open"
    assert change_state(ws, change_id) == "active"


def crop_png(png: bytes, rect: tuple[int, int, int, int]) -> bytes:
    from kookabug_platform.frames import decode_image, encode_png

    x, y, w, h = rect
    import numpy as np

    pixels = np.ascontiguousarray(np.asarray(decode_image(png))[y : y + h, x : x + w])
    return bytes(encode_png(pixels))


# ---------------------------------------------------------------- 성공·기록


def test_adopted_bytes_and_record(ws: Path) -> None:
    team = (ws / TARGET).read_bytes()
    graph = (ws / TEST).read_bytes()
    candidate = moved_target(ws)
    change_id = setup(ws, candidate)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert result["adopted"] is True and result["failed"] is None, result
    assert result["runs"] == ["verify0001", "verify0002"]
    assert result["negatives"] == ["neg-shop-sell/shop_missing.png"]
    # 팀 target 바이트 = 작업 사본, 그래프·PNG 바이트 그대로
    assert (ws / TARGET).read_bytes() == candidate
    assert (ws / TEST).read_bytes() == graph
    [record] = adoptions(ws)
    assert record["kind"] == "auto" and record["id"] == result["adoption"]
    assert record["files"] == [
        {"path": TARGET, "before_sha256": sha(team), "after_sha256": sha(candidate)}
    ]
    assert record["case"] == CASE and record["change"] == change_id
    assert record["runs"] == result["runs"] and record["reverted"] is None
    assert record["policy_sha"] == rules.policy_sha(Workspace.open(ws).automation())
    assert record["negatives"][0]["source"] == "evidence:neg-shop-sell"
    # 원래 바이트는 증거 묶음으로 보존
    prev = ws / "knowledge" / "evidence" / f"e-{record['id']}-prev"
    assert [p.read_bytes() for p in sorted(prev.glob("0-*"))] == [team]
    case = case_doc(ws)
    assert case["state"] == "resolved" and case["revision"] == 2
    assert case["resolution"]["by"] == "adoption" and case["resolution"]["adoption"] == record["id"]
    assert change_state(ws, change_id) == "adopted"
    log = (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    assert json.loads(log[-1])["op"] == "adopt"


def test_adopt_checks_order_and_verify_overlay_is_manifest(ws: Path) -> None:
    """검증 실행 덧씌움 = 그 변경 하나만 적용한 의존성 폐포(나머지는 팀 바이트 그대로)."""
    candidate = moved_target(ws)
    change_id = setup(ws, candidate)
    # 다른 Agent의 다른 작업 변경은 검증 실행에 들어가지 않는다
    other = basis.write(
        ws, {"targets/shop/potion_bought.target.json": b"{}"}, actor=Actor("agent", "other")
    )
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert result["adopted"] is True, result
    first, second = verifier.calls
    assert (first["graph"], second["graph"]) == (TEST, AFFECTED)
    assert first["profile"] == "shop_moved"
    overlay = first["overlay"]
    assert overlay[TARGET] == candidate
    for rel, data in overlay.items():
        if rel != TARGET:
            assert data == (ws / rel).read_bytes() or rel == TARGET, rel
    assert "targets/shop/potion_bought.target.json" in overlay
    assert overlay["targets/shop/potion_bought.target.json"] != b"{}"
    assert first["basis"]["adopt"] == result["manifest"]
    assert first["basis"]["working"] == [{"id": change_id, "files": {TARGET: sha(candidate)}}]
    assert change_state(ws, str(other["id"])) == "active"


# ---------------------------------------------------------------- 조건 실패


def test_requires_assertions_executed(ws: Path) -> None:
    change_id = setup(ws)
    before = team_tree(ws)
    result = adopt(ws, change_id, FakeVerifier(executed=False))
    assert result["failed"] == {
        "condition": 4,
        "code": "oracle_not_run",
        "detail": result["failed"]["detail"],
    }
    assert result["kept"] == "working"
    assert_nothing_published(ws, before, change_id)
    result = adopt(ws, change_id, FakeVerifier(passed=False))
    assert result["failed"]["code"] == "oracle_failed"
    result = adopt(ws, change_id, FakeVerifier(verdicts={TEST: "fail"}))
    assert result["failed"]["code"] == "oracle_failed"
    # 실행 스냅샷이 manifest와 다르면 그 검증은 무효
    stray = FakeVerifier(snapshot_extra={"targets/x.png": "0" * 64})
    assert adopt(ws, change_id, stray)["failed"]["code"] == "verify_error"
    assert_nothing_published(ws, before, change_id)


def test_policy_scope_and_qa_claims(ws: Path) -> None:
    change_id = setup(ws)
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["automation"]["auto_repair"] = {"enabled": False}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    assert adopt(ws, change_id)["failed"]["code"] == "policy_off"
    config["automation"]["auto_repair"] = {"enabled": True, "profiles": ["dev"]}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    assert adopt(ws, change_id)["failed"]["code"] == "out_of_scope"
    config["automation"]["auto_repair"] = {"enabled": True, "scope": ["tests/other/"]}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    assert adopt(ws, change_id)["failed"]["code"] == "out_of_scope"
    # qa.claims 없는 테스트는 자동 채택하지 않는다 (C3)
    config["automation"]["auto_repair"] = {"enabled": True}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    write_case(ws)
    doc = case_doc(ws)
    doc["symptom"]["test"] = AFFECTED
    (ws / "knowledge" / "cases" / f"{CASE}.json").write_text(canonical_dumps(doc), "utf-8")
    assert adopt(ws, change_id)["failed"] == {
        "condition": 1,
        "code": "no_qa_claims",
        "detail": "테스트에 qa.claims가 없다 (C3)",
    }


def test_negative_control_required_and_matched_refused(ws: Path) -> None:
    neg = ws / "knowledge" / "evidence" / "neg-shop-sell"
    sell_frame = (neg / "shop_missing.png").read_bytes()
    # 은폐 시도 ①: 판매 단추를 구매 locator로 다시 자른다 (같은 넓이 범위로 판매 자리)
    sell_png = crop_png(sell_frame, (360, 452, 180, 60))
    candidate = moved_target(ws, x=0.3125, y=0.6594)
    change_id = setup(ws, candidate, extra={IMAGE: sell_png})
    before = team_tree(ws)
    result = adopt(ws, change_id)
    assert result["failed"]["condition"] == 5 and result["failed"]["code"] == "negative_matched"
    assert_nothing_published(ws, before, change_id)
    # 음성 프레임이 하나도 없으면 채택하지 않는다 (C6)
    shutil.rmtree(neg)
    result = adopt(ws, setup_other(ws))
    assert result["failed"] == {
        "condition": 5,
        "code": "no_negative_control",
        "detail": "음성 대조 프레임이 하나도 없다 (C6)",
    }
    # 요청이 준 이 연결의 정지 화면도 음성 프레임이다 (출처 기록)
    import numpy as np

    from kookabug_platform.frames import decode_image

    pixels = np.asarray(decode_image(sell_frame))
    result = adopt(
        ws, setup_other(ws), extra=[Negative("frame:f1", pixels, "connection:3", "판매 화면")]
    )
    assert result["adopted"] is True, result
    assert adoptions(ws)[0]["negatives"] == [
        {"frame": "frame:f1", "source": "connection:3", "note": "판매 화면"}
    ]


def setup_other(ws: Path) -> str:
    """같은 사건의 새 후보 (옮긴 자리 locator, 다른 Agent)."""
    return str(basis.write(ws, {TARGET: moved_target(ws)}, actor=Actor("agent", "agent-d"))["id"])


def test_affected_tests_rerun(ws: Path) -> None:
    change_id = setup(ws)
    before = team_tree(ws)
    verifier = FakeVerifier(verdicts={AFFECTED: "fail"})
    result = adopt(ws, change_id, verifier)
    assert result["failed"]["condition"] == 6 and result["failed"]["code"] == "affected_failed"
    assert [c["graph"] for c in verifier.calls] == [TEST, AFFECTED]
    assert verifier.calls[1]["overlay"][TARGET] == moved_target(ws)
    assert_nothing_published(ws, before, change_id)


def test_adoption_cap(ws: Path) -> None:
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["automation"]["auto_repair"] = {"max_adoptions": 1}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    first = setup(ws)
    assert adopt(ws, first)["adopted"] is True
    # 같은 정책 아래 두 번째는 상한 (사건을 다시 열고 새 후보)
    write_case(ws)
    second = basis.write(ws, {TARGET: moved_target(ws, x=0.6)}, actor=Actor("agent", "agent-e"))
    result = adopt(ws, str(second["id"]))
    assert result["failed"]["condition"] == 7 and result["failed"]["code"] == "adoption_cap"
    assert len(adoptions(ws)) == 1
    # 정책이 바뀌면 다시 센다
    config["automation"]["auto_repair"] = {"max_adoptions": 2}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    assert adopt(ws, str(second["id"]))["adopted"] is True


def test_team_changed_meanwhile_conflict(ws: Path) -> None:
    change_id = setup(ws)
    user = b'{"edited": "by human"}\n'

    def human_edits(graph: str) -> None:
        if graph == TEST:
            (ws / TARGET).write_bytes(user)

    result = adopt(ws, change_id, FakeVerifier(hook=human_edits))
    assert result["failed"]["condition"] == 8 and result["failed"]["code"] == "revision_conflict"
    assert (ws / TARGET).read_bytes() == user  # 사람 바이트 그대로
    assert adoptions(ws) == [] and case_doc(ws)["state"] == "open"


def test_candidate_changed_during_verify_not_published(ws: Path) -> None:
    candidate = moved_target(ws)
    change_id = setup(ws, candidate)
    team = (ws / TARGET).read_bytes()

    def agent_rewrites(graph: str) -> None:
        if graph == TEST:
            basis.write(ws, {TARGET: moved_target(ws, x=0.5)}, actor=AGENT)

    result = adopt(ws, change_id, FakeVerifier(hook=agent_rewrites))
    assert result["failed"]["code"] == "revision_conflict", result
    assert "후보" in result["failed"]["detail"]
    assert (ws / TARGET).read_bytes() == team and adoptions(ws) == []


@pytest.mark.parametrize("what", ["policy", "oracle", "claims"])
def test_policy_or_oracle_changed_before_commit_refused(ws: Path, what: str) -> None:
    change_id = setup(ws)
    before_target = (ws / TARGET).read_bytes()

    def change(graph: str) -> None:
        if graph != AFFECTED:
            return
        if what == "policy":
            config = json.loads((ws / "kookabug.json").read_text("utf-8"))
            config["automation"]["forbidden"].append({"kind": "text", "value": "환불"})
            (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
        elif what == "oracle":
            png = ws / "targets" / "shop" / "potion_bought.png"
            png.write_bytes(png.read_bytes() + b"\0")
        else:
            ops.apply(
                ws,
                {
                    "request_id": "human-1",
                    "ops": [
                        {
                            "op": "revise",
                            "file": "features/shop",
                            "id": CLAIM,
                            "base_rev": 1,
                            "changes": {"statement": "물약 100골드 (사람 고침)"},
                        }
                    ],
                },
                actor=Actor("human", "ui:1"),
                check_secrets=lambda _: None,
            )

    result = adopt(ws, change_id, FakeVerifier(hook=change))
    assert result["failed"]["condition"] == 8, result
    assert result["failed"]["code"] == "revision_conflict"
    assert (ws / TARGET).read_bytes() == before_target and adoptions(ws) == []
    assert change_state(ws, change_id) == "active"


def test_oracle_dependency_changed_since_original_failure(ws: Path) -> None:
    """조건 3: 원래 실패 뒤 판정 의존성(물약 target PNG)이 바뀌었으면 채택하지 않는다."""
    change_id = setup(ws)
    png = ws / "targets" / "shop" / "potion_bought.png"
    png.write_bytes(png.read_bytes() + b"\0")
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert result["failed"]["condition"] == 3 and result["failed"]["code"] == "oracle_changed"
    assert verifier.calls == []  # 검증 실행 전에 멈춘다


def test_concurrent_adoptions_cannot_exceed_cap(ws: Path) -> None:
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["automation"]["auto_repair"] = {"max_adoptions": 1}
    (ws / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    first = setup(ws)
    second_case = "c-20261109-000000-0002"
    write_case(ws, second_case)
    second = basis.write(ws, {TARGET: moved_target(ws, x=0.6)}, actor=Actor("agent", "agent-f"))
    done: list[dict[str, Any]] = []

    def other_adopts(graph: str) -> None:
        if graph == AFFECTED and not done:
            done.append(Adopter(ws, FakeVerifier()).request(second_case, str(second["id"])))

    result = adopt(ws, first, FakeVerifier(hook=other_adopts))
    assert done[0]["adopted"] is True
    assert result["failed"]["condition"] == 7 and result["failed"]["code"] == "adoption_cap"
    assert len(adoptions(ws)) == 1


def test_adopt_requests_refused_for_inactive_or_foreign_change(ws: Path) -> None:
    change_id = setup(ws)
    assert adopt(ws, change_id)["adopted"] is True
    with pytest.raises(KnowledgeError) as caught:
        adopt(ws, change_id)
    assert caught.value.code == "change_not_active"
    with pytest.raises(KnowledgeError) as caught:
        adopt(ws, "w-20261109-000000-ffff")
    assert caught.value.code == "unknown_id"


# ---------------------------------------------------------------- 검수 B3_1 재현 (회귀)


def make_junction(link: Path, target: Path) -> None:
    import _winapi

    link.parent.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))


def age(path: Path, days: float = 3) -> None:
    old = time.time() - days * 86400
    os.utime(path, (old, old))


def test_review_cache_parent_junction_preserves_external(ws: Path, tmp_path: Path) -> None:
    """`.kookabug/cache`가 바깥 폴더로 가는 정션이면 바깥 사용자 폴더를 만들거나 지우지 않고
    멈춘다 (조상까지 쓰기 경계)."""
    change_id = setup(ws)
    before = team_tree(ws)
    outside = tmp_path / "outside"
    human = outside / "adopt" / "human-folder"
    human.mkdir(parents=True)
    marker = human / "human.txt"
    marker.write_text("human-owned-data", encoding="utf-8")
    age(human)
    age(outside / "adopt")
    shutil.rmtree(ws / ".kookabug" / "cache", ignore_errors=True)
    make_junction(ws / ".kookabug" / "cache", outside)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert marker.read_text("utf-8") == "human-owned-data"
    assert sorted(p.name for p in (outside / "adopt").iterdir()) == ["human-folder"]
    assert result["adopted"] is False
    assert result["failed"]["condition"] == 1
    assert result["failed"]["code"] == "path_outside_workspace"
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


def test_scratch_prunes_only_owned_folders(ws: Path) -> None:
    """캐시 가지치기는 서비스가 만든 항목(UUID 이름 + 소유 표시 파일)만 지운다."""
    from kookabug_daemon.adopt import SCRATCH_OWNER

    base = ws / ".kookabug" / "cache" / "adopt"
    human = base / "human-folder"
    human.mkdir(parents=True)
    (human / "human.txt").write_text("x", encoding="utf-8")
    no_marker = base / ("a" * 32)
    no_marker.mkdir()
    (no_marker / "keep.txt").write_text("x", encoding="utf-8")
    wrong_marker = base / ("b" * 32)
    wrong_marker.mkdir()
    (wrong_marker / SCRATCH_OWNER).write_bytes(b"kookabug.adopt-scratch/0 other\n")
    owned = base / ("c" * 32)
    owned.mkdir()
    (owned / SCRATCH_OWNER).write_bytes(f"kookabug.adopt-scratch/0 {'c' * 32}\n".encode())
    fresh = base / ("d" * 32)
    fresh.mkdir()
    (fresh / SCRATCH_OWNER).write_bytes(f"kookabug.adopt-scratch/0 {'d' * 32}\n".encode())
    for path in (human, no_marker, wrong_marker, owned):
        age(path)
    assert adopt(ws, setup(ws))["adopted"] is True
    left = sorted(p.name for p in base.iterdir())
    assert left == sorted(["human-folder", "a" * 32, "b" * 32, "d" * 32])
    assert (human / "human.txt").exists() and (no_marker / "keep.txt").exists()


def test_review_new_judgment_reference_during_verification(ws: Path) -> None:
    """검증 중 후보 target을 판정에 쓰는 새 테스트가 생기면 게시하지 않는다 (manifest의 참조
    집합·영향 테스트를 게시 잠금 안에서 다시 계산)."""
    change_id = setup(ws)
    before_target = (ws / TARGET).read_bytes()
    new_rel = "tests/shop/review_new.graph.json"

    def add_judgment_test(graph: str) -> None:
        if graph != TEST:
            return
        value = json.loads((ws / AFFECTED).read_text("utf-8"))
        node = value["nodes"]["n_click_buy"]
        node["type"] = "core.assert.visible"
        node["next"] = {"ok": node["next"]["done"]}
        (ws / new_rel).write_text(json.dumps(value, indent=2), encoding="utf-8")

    verifier = FakeVerifier(hook=add_judgment_test)
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    assert result["failed"]["condition"] == 8
    assert result["failed"]["code"] == "revision_conflict"
    assert [c["graph"] for c in verifier.calls] == [TEST, AFFECTED]  # 새 테스트를 더 돌리지 않음
    assert (ws / TARGET).read_bytes() == before_target and adoptions(ws) == []
    assert change_state(ws, change_id) == "active"


def test_new_affected_test_during_verification_conflict(ws: Path) -> None:
    """후보를 조작으로만 쓰는 새 테스트(새 영향 테스트)가 검증 중 생겨도 게시하지 않는다."""
    change_id = setup(ws)

    def add_affected(graph: str) -> None:
        if graph == TEST:
            shutil.copyfile(ws / AFFECTED, ws / "tests" / "shop" / "review_copy.graph.json")

    result = adopt(ws, change_id, FakeVerifier(hook=add_affected))
    assert result["failed"]["code"] == "revision_conflict", result
    assert adoptions(ws) == []


def test_negative_frames_changed_during_verification_conflict(ws: Path) -> None:
    """음성 대조 뒤(영향 테스트 검증 중) 새 음성 프레임이 생기면 게시하지 않는다."""
    change_id = setup(ws)
    frame = ws / "knowledge" / "evidence" / "neg-shop-sell" / "shop_missing.png"

    def add_screen(graph: str) -> None:
        if graph == AFFECTED:
            shutil.copyfile(frame, ws / "screens" / "review_new.png")

    result = adopt(ws, change_id, FakeVerifier(hook=add_screen))
    assert result["failed"]["code"] == "revision_conflict", result
    assert "음성" in result["failed"]["detail"]
    assert adoptions(ws) == []


def edited_png(png: bytes) -> bytes:
    import numpy as np

    from kookabug_platform.frames import decode_image, encode_png

    pixels = np.array(decode_image(png))
    pixels[0, 0] = 255 - pixels[0, 0]
    return bytes(encode_png(np.ascontiguousarray(pixels)))


def test_review_shared_png_case_alias_refused(ws: Path) -> None:
    """대소문자만 다른 후보 PNG 키(`BUY.png`)로 공유 판정 이미지 검사를 우회하지 못한다."""
    shared = "targets/shop/review_shared.target.json"
    value = json.loads((ws / TARGET).read_text("utf-8"))
    (ws / shared).write_text(json.dumps(value, indent=2), encoding="utf-8")
    graph = json.loads((ws / AFFECTED).read_text("utf-8"))
    graph["nodes"] = {
        "n_entry": graph["nodes"]["n_entry"],
        "n_launch": graph["nodes"]["n_launch"],
        "n_seen": {
            "in": {"target": {"$target": shared}, "timeout_ms": 5000},
            "type": "core.assert.visible",
            "version": 1,
        },
    }
    graph["nodes"]["n_launch"]["next"] = {"attached": "n_seen"}
    (ws / "tests" / "shop" / "review_shared.graph.json").write_text(
        json.dumps(graph, indent=2), encoding="utf-8"
    )
    alias = "targets/shop/BUY.png"
    assert os.path.samefile(ws / alias, ws / IMAGE)
    new_png = edited_png((ws / IMAGE).read_bytes())
    change_id = setup(ws, extra={alias: new_png})
    before = team_tree(ws)
    result = adopt(ws, change_id)
    assert not result["adopted"], result
    assert result["failed"]["code"] == "path_alias"
    assert_nothing_published(ws, before, change_id)
    # 같은 파일을 두 철자로 담으면 작업 기준 쓰기부터 거부한다
    with pytest.raises(KnowledgeError) as caught:
        basis.write(ws, {IMAGE: new_png, alias: new_png}, actor=AGENT)
    assert caught.value.code == "path_alias"
    # 철자가 맞으면(같은 파일) 공유 판정 이미지 검사가 막는다
    other = basis.write(ws, {TARGET: moved_target(ws), IMAGE: new_png}, actor=Actor("agent", "z"))
    result = adopt(ws, str(other["id"]))
    assert result["failed"]["code"] == "target_used_for_judgment", result
    assert "shared_image" in result["failed"]["detail"]


def set_gold_setting(ws: Path, value: str) -> None:
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["settings"]["review.gold"] = value
    (ws / "kookabug.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def use_gold_setting(ws: Path) -> None:
    graph = json.loads((ws / TEST).read_text("utf-8"))
    graph["nodes"]["n_assert_gold"]["in"]["equals"] = {"$setting": "review.gold"}
    (ws / TEST).write_text(json.dumps(graph, indent=2), encoding="utf-8")


def test_review_original_assertion_setting_changed(ws: Path) -> None:
    """원래 실패 뒤 판정 기대값이 해석하는 팀 설정이 바뀌면 조건 3 `oracle_changed`."""
    from kookabug_core.loader import load_program
    from kookabug_core.workspace import RunOptions

    use_gold_setting(ws)
    set_gold_setting(ws, "12,245")
    change_id = setup(ws)
    set_gold_setting(ws, "12,345")
    program = load_program(Workspace.open(ws), TEST, options=RunOptions(profile="shop_moved"))
    assert program.settings["review.gold"].value == "12,345"
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    assert (result["failed"]["condition"], result["failed"]["code"]) == (3, "oracle_changed")
    assert "review.gold" in result["failed"]["detail"]
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)
    # 프로필 덮어쓰기도 판정 설정이다
    set_gold_setting(ws, "12,245")
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["profiles"]["shop_moved"]["settings"]["review.gold"] = "99"
    (ws / "kookabug.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    assert adopt(ws, change_id)["failed"]["code"] == "oracle_changed"
    # 같으면 채택된다 (양성 대조)
    del config["profiles"]["shop_moved"]["settings"]["review.gold"]
    (ws / "kookabug.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    assert adopt(ws, change_id)["adopted"] is True


@pytest.mark.parametrize("how", ["secret", "var", "link_to_candidate"])
def test_untraceable_judgment_input_refused(ws: Path, how: str) -> None:
    """판정 입력이 비밀값을 읽거나 `$link`가 그래프 밖 값(변수)·후보 target으로 이어지면 자동
    채택하지 않는다."""
    graph = json.loads((ws / TEST).read_text("utf-8"))
    nodes = graph["nodes"]
    if how == "secret":
        nodes["n_assert_gold"]["in"]["equals"] = {"$secret": "shop.gold"}
    elif how == "var":
        nodes["n_var"] = {"in": {"name": "gold"}, "type": "core.var.get", "version": 1}
        nodes["n_assert_gold"]["in"]["equals"] = {"$link": "n_var.value"}
    else:
        nodes["n_assert_gold"]["in"]["region"] = {"$link": "n_click_buy.match"}
    (ws / TEST).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    change_id = setup(ws)
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    want = {
        "secret": (3, "oracle_untraceable"),
        "var": (3, "oracle_untraceable"),
        "link_to_candidate": (2, "target_used_for_judgment"),
    }[how]
    assert (result["failed"]["condition"], result["failed"]["code"]) == want, result
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


def set_setting(ws: Path, key: str, value: Any) -> None:
    config = json.loads((ws / "kookabug.json").read_text("utf-8"))
    config["settings"][key] = value
    (ws / "kookabug.json").write_text(json.dumps(config, indent=2), encoding="utf-8")


def test_review_var_add_setting_oracle_bypass(ws: Path) -> None:
    """판정 입력이 `$link`로 `core.var.add`(변수 상태를 읽는다)를 거쳐 팀 설정에 기대면 추적할 수
    없다 — 조건 3 `oracle_untraceable`, 검증 실행 0."""
    from kookabug_core.loader import load_program
    from kookabug_core.workspace import RunOptions

    graph = json.loads((ws / TEST).read_text("utf-8"))
    nodes = graph["nodes"]
    nodes["n_click_buy"]["next"] = {"done": "n_set"}
    nodes["n_set"] = {
        "type": "core.var.set",
        "version": 1,
        "in": {"name": "expected", "value": {"$setting": "review.expected"}},
        "next": {"done": "n_add"},
    }
    nodes["n_add"] = {
        "type": "core.var.add",
        "version": 1,
        "in": {"name": "expected", "amount": 0},
        "next": {"done": "n_assert_gold"},
    }
    nodes["n_assert_gold"] = {
        "type": "core.assert.compare",
        "version": 1,
        "in": {"a": 8, "op": "==", "b": {"$link": "n_add.value"}},
        "next": {"ok": "n_assert_item"},
    }
    (ws / TEST).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    set_setting(ws, "review.expected", 7)
    change_id = setup(ws)
    set_setting(ws, "review.expected", 8)
    program = load_program(Workspace.open(ws), TEST, options=RunOptions(profile="shop_moved"))
    assert program.settings["review.expected"].value == 8
    judged = rules.judgment_inputs(
        {TEST: graph}, TEST, is_assertion=lambda t: t.startswith("core.assert."), targets={}
    )
    assert judged.untraceable is not None and "core.var.add" in judged.untraceable
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    assert (result["failed"]["condition"], result["failed"]["code"]) == (3, "oracle_untraceable")
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


def add_link_judgment(ws: Path) -> None:
    """영향 테스트에 `n_click_buy.match`(후보 target 출처)를 판정하는 노드를 넣는다."""
    graph = json.loads((ws / AFFECTED).read_text("utf-8"))
    nodes = graph["nodes"]
    after = nodes["n_click_buy"]["next"]["done"]
    nodes["n_click_buy"]["next"] = {"done": "n_review_assert"}
    nodes["n_review_assert"] = {
        "type": "core.assert.compare",
        "version": 1,
        "in": {"a": {"$link": "n_click_buy.match"}, "op": "!=", "b": None},
        "next": {"ok": after},
    }
    (ws / AFFECTED).write_text(json.dumps(graph, indent=2), encoding="utf-8")


def test_review_link_judgment_in_affected_test(ws: Path) -> None:
    """원래 테스트 밖(영향 테스트)의 판정 입력이 `$link`로 후보 target을 거쳐 와도 조건 2
    `target_used_for_judgment` — 팀 기준 전체에서 조작 전용이어야 한다."""
    from kookabug_core.loader import load_program
    from kookabug_core.workspace import RunOptions

    add_link_judgment(ws)
    program = load_program(Workspace.open(ws), AFFECTED, options=RunOptions(profile="shop_moved"))
    assert not [d for d in program.diagnostics if d.severity == "error"]
    change_id = setup(ws)
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    failed = result["failed"]
    assert (failed["condition"], failed["code"]) == (2, "target_used_for_judgment"), result
    assert AFFECTED in failed["detail"]
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


@pytest.mark.parametrize("suffix", ["GRAPH.json", "graph.JSON", "graph.json"])
def test_review_graph_suffix_judgment(ws: Path, suffix: str) -> None:
    """확장자 대소문자가 다른 팀 그래프(`*.GRAPH.json`·`*.graph.JSON`)도 그래프로 보고 `$link`
    판정 검사에 넣는다 — 소문자는 양성 대조(같은 결과여야 한다). 원래·영향 테스트는 그대로 두고
    영향 테스트를 복제한 그래프에 후보 target 출처 판정을 넣는다."""
    graph = json.loads((ws / AFFECTED).read_text("utf-8"))
    nodes = graph["nodes"]
    after = nodes["n_click_buy"]["next"]["done"]
    nodes["n_click_buy"]["next"] = {"done": "n_review_assert"}
    nodes["n_review_assert"] = {
        "type": "core.assert.compare",
        "version": 1,
        "in": {"a": {"$link": "n_click_buy.match"}, "op": "!=", "b": None},
        "next": {"ok": after},
    }
    rel = f"{Path(AFFECTED).parent.as_posix()}/review_suffix.{suffix}"
    (ws / rel).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    assert rules.is_graph(rel)
    _loads_clean(ws, rel)
    assert rules.target_flow_problem({rel: graph}, TARGET) is not None
    change_id = setup(ws)
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    failed = result["failed"]
    assert (failed["condition"], failed["code"]) == (2, "target_used_for_judgment"), result
    assert "review_suffix" in failed["detail"]
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


NEG = "knowledge/evidence/neg-shop-sell"
ALIASES: dict[str, tuple[str, str]] = {
    # 경우 → (manifest에서 바꾸는 필드, 값). plain은 원본 그대로(양성 대조)
    "plain": ("targets", TARGET),
    "double_separator": ("targets", "targets//shop/buy.target.json"),
    "dot_segment": ("targets", "targets/shop/./buy.target.json"),
    "target_case": ("targets", "targets/SHOP/buy.target.json"),
    "frame_case": ("frames", "SHOP_MISSING.PNG"),
}


@pytest.mark.parametrize("how", list(ALIASES))
def test_review_bound_negative_alias(ws: Path, how: str) -> None:
    """음성 묶음의 target·프레임 철자가 후보 target·`files[].path`와 달라도(같은 파일) 그 음성
    프레임을 빼고 채택하지 않는다. 정규형 철자(대소문자만 다름)는 `path_key`로 맞춰 음성 대조에
    쓰고(`negative_matched`), 정규형이 아닌 철자(빈 조각·`.`)는 `load_manifest`가 음성 대조에서
    빼며 이 target에 묶인 묶음이므로 조건 5에서 거부한다. 다른 정상 음성 프레임(빈 화면) 1장이
    있어 단순 `no_negative_control`(프레임 0개)로 가려지지 않는다."""
    import numpy as np

    from kookabug_core import evidence
    from kookabug_daemon.adopt import target_found
    from kookabug_platform.frames import decode_image, encode_png

    field, value = ALIASES[how]
    manifest_path = ws / NEG / "manifest.json"
    doc = json.loads(manifest_path.read_text("utf-8"))
    doc["negative"][field] = [value]
    manifest_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    neg = ws / NEG
    if field == "targets":
        assert (ws / value).samefile(ws / TARGET)
        canonical = how in ("plain", "target_case")
        if canonical:
            assert rules.path_key(value) == rules.path_key(TARGET)
    else:
        assert (neg / value).samefile(neg / "shop_missing.png")
        assert rules.path_key(value) == rules.path_key("shop_missing.png")
        canonical = True
    loaded = evidence.load_manifest(ws, "neg-shop-sell")
    assert loaded is not None
    if canonical:
        assert loaded["negative"][field] == [value]
    else:
        assert "negative" not in loaded
        assert "정규형" in loaded[evidence.NEGATIVE_IGNORED]["reason"]
        assert loaded[evidence.NEGATIVE_IGNORED]["targets"] == [value]
    # 검수 공통 재료: 판매 자리 템플릿 + 다른 정상 음성 대조(빈 화면) 1장
    frame = np.asarray(decode_image((neg / "shop_missing.png").read_bytes()))
    template = bytes(encode_png(np.ascontiguousarray(frame[452:512, 360:540])))
    (ws / "screens" / "review_blank.PNG").write_bytes(bytes(encode_png(np.zeros_like(frame))))
    candidate = moved_target(ws, x=0.3515625, y=0.70625)
    change_id = setup(ws, candidate, extra={IMAGE: template})
    assert target_found(ws, TARGET, json.loads(candidate), template, frame)
    before = team_tree(ws)
    result = Adopter(ws, FakeVerifier()).request(CASE, change_id)
    if result["adopted"]:
        assert (ws / TARGET).read_bytes() == candidate
        assert (ws / IMAGE).read_bytes() == template
        assert len(adoptions(ws)) == 1
    assert not result["adopted"], result
    failed = result["failed"]
    if canonical:
        assert (failed["condition"], failed["code"]) == (5, "negative_matched"), result
        name = value if field == "frames" else "shop_missing.png"
        assert f"neg-shop-sell/{name}" in result["negatives"]
    else:
        assert (failed["condition"], failed["code"]) == (5, "no_negative_control"), result
        assert "neg-shop-sell" in failed["detail"] and "정규형" in failed["detail"]
    assert_nothing_published(ws, before, change_id)


def test_ignored_negative_bundle_added_during_verification_conflict(ws: Path) -> None:
    """검증 중 이 target에 묶인, 정규형이 아닌 음성 묶음이 생기면 게시하지 않는다."""
    change_id = setup(ws)
    src = ws / NEG

    def add_bundle(graph: str) -> None:
        if graph == AFFECTED:
            dest = ws / "knowledge" / "evidence" / "neg-review-late"
            shutil.copytree(src, dest)
            doc = json.loads((dest / "manifest.json").read_text("utf-8"))
            doc["id"] = "neg-review-late"
            doc["negative"]["targets"] = ["targets//shop/buy.target.json"]
            (dest / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")

    result = adopt(ws, change_id, FakeVerifier(hook=add_bundle))
    assert result["failed"]["code"] == "revision_conflict", result
    assert adoptions(ws) == []


@pytest.mark.parametrize("how", ["plain", "sha_mismatch", "unreadable", "unlisted"])
def test_bound_negative_frame_sha_mismatch_refused(ws: Path, how: str) -> None:
    """이 target에 묶인 음성 묶음의 프레임이 묶음 sha와 다르거나·읽을 수 없거나·목록에 없으면
    조용히 빼지 않고 조건 5 `no_negative_control`로 거부한다 — 다른 정상 음성 프레임(빈 화면)이
    있어도. 상세에는 묶음 ID·프레임 이름·이유만(바이트·sha 값 없음). `plain`은 양성 대조."""
    import numpy as np

    from kookabug_platform.frames import decode_image, encode_png

    neg = ws / NEG
    frame_path = neg / "shop_missing.png"
    original = frame_path.read_bytes()
    frame = np.asarray(decode_image(original))
    (ws / "screens" / "review_blank.png").write_bytes(bytes(encode_png(np.zeros_like(frame))))
    shas = {sha(original)}
    if how == "sha_mismatch":
        changed = edited_png(original)
        shas.add(sha(changed))
        frame_path.write_bytes(changed)
    elif how == "unreadable":
        frame_path.unlink()
    elif how == "unlisted":
        doc = json.loads((neg / "manifest.json").read_text("utf-8"))
        doc["negative"]["frames"] = ["shop_missing.png", "review_extra.png"]
        (neg / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
        (neg / "review_extra.png").write_bytes(original)
    change_id = setup(ws)
    before = team_tree(ws)
    result = adopt(ws, change_id)
    if how == "plain":
        assert result["adopted"] is True, result
        assert "neg-shop-sell/shop_missing.png" in result["negatives"]
        return
    assert not result["adopted"], result
    failed = result["failed"]
    assert (failed["condition"], failed["code"]) == (5, "no_negative_control"), result
    name = "review_extra.png" if how == "unlisted" else "shop_missing.png"
    assert f"neg-shop-sell/{name}" in failed["detail"]
    reason = {
        "sha_mismatch": "묶음 sha와 다르다",
        "unreadable": "읽을 수 없다",
        "unlisted": "목록에 없는",
    }[how]
    assert reason in failed["detail"]
    assert not any(s in json.dumps(result) for s in shas)
    assert_nothing_published(ws, before, change_id)


def test_negative_frame_changed_during_verification_refused(ws: Path) -> None:
    """검증 중 이 target의 음성 묶음 프레임 바이트가 바뀌면 게시 직전 재확인이 거부한다."""
    change_id = setup(ws)
    frame = ws / NEG / "shop_missing.png"

    def tamper(graph: str) -> None:
        if graph == AFFECTED:
            frame.write_bytes(edited_png(frame.read_bytes()))

    result = adopt(ws, change_id, FakeVerifier(hook=tamper))
    assert result["failed"]["code"] == "revision_conflict", result
    assert adoptions(ws) == []
    assert change_state(ws, change_id) == "active"


def test_repair_scope_compared_normalized() -> None:
    """자동 수리 범위(조건 1)도 정규화 키로 본다: 철자만 다른 범위는 안, 폴더 경계 밖은 밖."""
    from kookabug_daemon.adopt import _in_scope  # pyright: ignore[reportPrivateUsage]

    assert _in_scope(TEST, "tests/")
    assert _in_scope(TEST, "Tests\\Shop\\")
    assert _in_scope(TEST, "tests//shop/")
    assert not _in_scope(TEST, "tests/sho/")
    assert _in_scope(TEST, "tests/sho")  # `/` 없는 범위는 앞부분 글자 그대로 (이전과 같다)
    assert not _in_scope(TEST, "/")
    assert _in_scope(TEST, "")


def test_link_judgment_through_subgraph_call_refused(ws: Path) -> None:
    """후보 target을 쓰는 서브그래프의 호출 출력을 다른 테스트가 판정하면(출처 추적 불가) 안전
    쪽으로 조건 2 거부."""
    sub = {
        "format": "kookabug.graph/0",
        "kind": "subgraph",
        "nodes": {
            "n_click": {
                "type": "core.image.click",
                "version": 1,
                "in": {"target": {"$target": TARGET}},
            }
        },
    }
    (ws / "subgraphs" / "review_buy.graph.json").write_text(json.dumps(sub), encoding="utf-8")
    caller = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_call": {
                "type": "core.graph.call",
                "version": 1,
                "config": {"graph": "subgraphs/review_buy.graph.json"},
            },
            "n_eq": {
                "type": "core.assert.compare",
                "version": 1,
                "in": {"a": {"$link": "n_call.match"}, "op": "!=", "b": None},
            },
        },
    }
    (ws / "tests" / "review_caller.graph.json").write_text(json.dumps(caller), encoding="utf-8")
    change_id = setup(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert (result["failed"]["condition"], result["failed"]["code"]) == (
        2,
        "target_used_for_judgment",
    ), result
    assert "review_caller" in result["failed"]["detail"]
    assert verifier.calls == [] and adoptions(ws) == []


def test_link_judgment_added_during_verification_refused(ws: Path) -> None:
    """검증 중 영향 테스트에 `$link` 판정이 생겨도 게시 직전 재확인에서 거부한다."""
    change_id = setup(ws)
    before_target = (ws / TARGET).read_bytes()

    def hook(graph: str) -> None:
        if graph == TEST:
            add_link_judgment(ws)

    result = adopt(ws, change_id, FakeVerifier(hook=hook))
    assert not result["adopted"], result
    assert result["failed"]["code"] in ("revision_conflict", "target_used_for_judgment")
    assert (ws / TARGET).read_bytes() == before_target and adoptions(ws) == []
    assert change_state(ws, change_id) == "active"


def _rewire_affected(ws: Path, extra: dict[str, Any], first: str) -> str:
    """영향 테스트의 `n_click_buy` 다음에 `extra` 노드들을 끼운다 (`first`부터). 원래 다음 노드 ID를
    돌려준다."""
    graph = json.loads((ws / AFFECTED).read_text("utf-8"))
    nodes = graph["nodes"]
    after = nodes["n_click_buy"]["next"]["done"]
    nodes["n_click_buy"]["next"] = {"done": first}
    text = json.dumps(extra).replace('"@AFTER"', json.dumps(after))
    nodes.update(json.loads(text))
    (ws / AFFECTED).write_text(json.dumps(graph, indent=2), encoding="utf-8")
    return after


def _loads_clean(ws: Path, rel: str) -> None:
    from kookabug_core.loader import load_program
    from kookabug_core.workspace import RunOptions

    program = load_program(Workspace.open(ws), rel, options=RunOptions(profile="shop_moved"))
    assert not [d for d in program.diagnostics if d.severity == "error"], program.diagnostics


def test_var_stored_target_branch_judgment_refused(ws: Path) -> None:
    """후보 target 값을 변수에 저장했다가(`image.click.match → var.set`) 읽어 분기로 판정하면
    (`var.get → logic.compare → flow.branch → test.fail`) 조건 2 `target_used_for_judgment`.
    역방향 추적은 분기 조건의 변수 출처를 거부하지 않으므로 정방향 흐름 검사가 막는다."""
    _rewire_affected(
        ws,
        {
            "n_store": {
                "type": "core.var.set",
                "version": 1,
                "in": {"name": "m", "value": {"$link": "n_click_buy.match"}},
                "next": {"done": "n_if"},
            },
            "n_load": {"type": "core.var.get", "version": 1, "in": {"name": "m"}},
            "n_cmp": {
                "type": "core.logic.compare",
                "version": 1,
                "in": {"a": {"$link": "n_load.value"}, "op": "!=", "b": None},
            },
            "n_if": {
                "type": "core.flow.branch",
                "version": 1,
                "in": {"condition": {"$link": "n_cmp.result"}},
                "next": {"true": "@AFTER", "false": "n_fail"},
            },
            "n_fail": {"type": "core.test.fail", "version": 1, "in": {"reason": "구매 단추 없음"}},
        },
        "n_store",
    )
    _loads_clean(ws, AFFECTED)
    change_id = setup(ws)
    before = team_tree(ws)
    verifier = FakeVerifier()
    result = adopt(ws, change_id, verifier)
    assert not result["adopted"], result
    failed = result["failed"]
    assert (failed["condition"], failed["code"]) == (2, "target_used_for_judgment"), result
    assert "n_store" in failed["detail"] and AFFECTED in failed["detail"]
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)


def test_counter_branch_still_adopted(ws: Path) -> None:
    """양성 대조: target 값과 무관한 반복 카운터 분기(`var.set → var.add → logic.compare →
    flow.branch`)만 있는 영향 테스트는 계속 채택된다."""
    _rewire_affected(
        ws,
        {
            "n_set": {
                "type": "core.var.set",
                "version": 1,
                "in": {"name": "i", "value": 0},
                "next": {"done": "n_add"},
            },
            "n_add": {
                "type": "core.var.add",
                "version": 1,
                "in": {"name": "i", "amount": 1},
                "next": {"done": "n_loop"},
            },
            "n_cmp": {
                "type": "core.logic.compare",
                "version": 1,
                "in": {"a": {"$link": "n_add.value"}, "op": ">=", "b": 2},
            },
            "n_loop": {
                "type": "core.flow.branch",
                "version": 1,
                "in": {"condition": {"$link": "n_cmp.result"}},
                "next": {"true": "@AFTER", "false": "n_add"},
            },
        },
        "n_set",
    )
    _loads_clean(ws, AFFECTED)
    candidate = moved_target(ws)
    change_id = setup(ws, candidate)
    result = adopt(ws, change_id)
    assert result["adopted"] is True and result["failed"] is None, result
    assert (ws / TARGET).read_bytes() == candidate


def test_review_adoption_note_secret_refused(ws: Path) -> None:
    """채택 기록에 들어갈 요청 메모에 비밀값이 있으면 아무것도 하지 않는다."""
    import numpy as np

    from kookabug_core.knowledge.formats import secret_checker
    from kookabug_core.workspace import MemorySecrets

    secret = "Hunter2-Adopt-Secret"
    check = secret_checker(["login.password"], MemorySecrets({"login.password": secret}))
    change_id = setup(ws)
    before = team_tree(ws)
    pixels = np.zeros((64, 64, 3), dtype=np.uint8)
    verifier = FakeVerifier()
    with pytest.raises(KnowledgeError) as caught:
        Adopter(ws, verifier, check_secrets=check).request(
            CASE, change_id, [Negative("frame:f1", pixels, "connection:1", f"메모 {secret}")]
        )
    assert caught.value.code == "secret_in_text"
    assert verifier.calls == []
    assert_nothing_published(ws, before, change_id)
    # 검사기가 있어도 비밀값이 없으면 채택된다
    assert Adopter(ws, FakeVerifier(), check_secrets=check).request(CASE, change_id)["adopted"]


# ---------------------------------------------------------------- 되돌리기·묶음 수락·거절


def test_revert_once_and_user_edit_conflict(ws: Path) -> None:
    team = (ws / TARGET).read_bytes()
    change_id = setup(ws)
    record = adopt(ws, change_id)
    out = rules.revert(ws, str(record["adoption"]), by="ui:1")
    assert out["files"] == [TARGET]
    assert (ws / TARGET).read_bytes() == team
    assert case_doc(ws)["state"] == "open" and case_doc(ws)["resolution"] is None
    assert change_state(ws, change_id) == "reverted"
    kinds = sorted((a["kind"], a["reverted"] is not None) for a in adoptions(ws))
    assert kinds == [("auto", True), ("revert", True)]
    with pytest.raises(KnowledgeError) as caught:
        rules.revert(ws, str(record["adoption"]), by="ui:1")
    assert caught.value.code == "already_reverted"
    # 채택 뒤 사람이 고쳤으면 아무것도 하지 않는다
    other = copy_example_workspace(ws.parents[2] / "u")
    record = adopt(other, setup(other))
    user = b'{"user": true}\n'
    (other / TARGET).write_bytes(user)
    snapshot = sorted(p.name for p in (other / "knowledge" / "adoptions").iterdir())
    with pytest.raises(KnowledgeError) as caught:
        rules.revert(other, str(record["adoption"]), by="ui:1")
    assert caught.value.code == "revision_conflict"
    assert (other / TARGET).read_bytes() == user
    assert sorted(p.name for p in (other / "knowledge" / "adoptions").iterdir()) == snapshot
    assert case_doc(other)["state"] == "resolved"


def test_accept_batch_atomic(ws: Path) -> None:
    team_target = (ws / TARGET).read_bytes()
    candidate = moved_target(ws)
    a = basis.write(ws, {TARGET: candidate}, actor=AGENT)
    graph = json.loads((ws / AFFECTED).read_text("utf-8"))
    graph["meta"] = {"title": "구매 뒤 닫기 (작업 기준)"}
    graph_bytes = (json.dumps(graph, indent=2, sort_keys=True) + "\n").encode()
    b = basis.write(ws, {AFFECTED: graph_bytes}, actor=Actor("agent", "agent-g"))
    # 작업 주장(R4): Agent가 기존 expected 주장을 고친 것은 작업 기준에 쌓인다
    ops.apply(
        ws,
        {
            "request_id": "agent-claim-1",
            "ops": [
                {
                    "op": "revise",
                    "file": "features/shop",
                    "id": CLAIM,
                    "base_rev": 1,
                    "changes": {"statement": "체력 물약은 100골드 (작업 기준)"},
                }
            ],
        },
        actor=AGENT,
        check_secrets=lambda _: None,
    )
    shop = (ws / "knowledge" / "features" / "shop.json").read_bytes()
    # 하나가 stale(팀 파일이 바뀜)이면 전부 거부 — 아무것도 바뀌지 않는다
    (ws / AFFECTED).write_bytes((ws / AFFECTED).read_bytes() + b"\n")
    stale_team = (ws / AFFECTED).read_bytes()
    with pytest.raises(KnowledgeError) as caught:
        rules.decide(
            ws,
            changes=[str(a["id"]), str(b["id"])],
            claims=[{"id": CLAIM, "rev": 2}],
            accept=True,
            by="ui:1",
        )
    assert caught.value.code == "revision_conflict"
    assert (ws / TARGET).read_bytes() == team_target and (ws / AFFECTED).read_bytes() == stale_team
    assert (ws / "knowledge" / "features" / "shop.json").read_bytes() == shop
    assert adoptions(ws) == []
    # 보고가 가리킨 작업 rev와 다르면 거부
    with pytest.raises(KnowledgeError) as caught:
        rules.decide(ws, changes=[], claims=[{"id": CLAIM, "rev": 3}], accept=True, by="ui:1")
    assert caught.value.code == "revision_conflict"
    # 팀 파일을 되돌리면 한 거래로 둘 다 + 주장까지
    (ws / AFFECTED).write_bytes(stale_team[:-1])
    out = rules.decide(
        ws,
        changes=[str(a["id"]), str(b["id"])],
        claims=[{"id": CLAIM, "rev": 2}],
        accept=True,
        by="ui:1",
    )
    assert out["files"] == sorted([TARGET, AFFECTED])
    assert out["claims"] == [{"id": CLAIM, "rev": 2, "file": "features/shop"}]
    assert (ws / TARGET).read_bytes() == candidate
    assert (ws / AFFECTED).read_bytes() == graph_bytes
    claim = json.loads((ws / "knowledge" / "features" / "shop.json").read_text("utf-8"))
    assert claim["claims"][0]["statement"] == "체력 물약은 100골드 (작업 기준)"
    assert claim["claims"][0]["rev"] == 2 and claim["history"][-1]["rev"] == 1
    [record] = adoptions(ws)
    assert record["kind"] == "accept" and record["changes"] == [a["id"], b["id"]]
    assert {change_state(ws, str(c["id"])) for c in (a, b)} == {"accepted"}
    over = json.loads((ws / "knowledge" / "working" / "claims" / "shop.json").read_text("utf-8"))
    assert over["claims"] == []
    # 수락도 한 번 되돌릴 수 있다 (파일만 — 주장은 팀 연산으로)
    rules.revert(ws, str(record["id"]), by="ui:1")
    assert (ws / TARGET).read_bytes() == team_target


def test_reject_drops_overlay(ws: Path) -> None:
    team = team_tree(ws)
    change = basis.write(ws, {TARGET: moved_target(ws)}, actor=AGENT)
    ops.apply(
        ws,
        {
            "request_id": "agent-claim-2",
            "ops": [
                {
                    "op": "set_status",
                    "file": "features/shop",
                    "id": CLAIM,
                    "base_rev": 1,
                    "status": "conflicted",
                }
            ],
        },
        actor=AGENT,
        check_secrets=lambda _: None,
    )
    assert basis.freeze(ws, "working", agent="agent-c").overlay
    out = rules.decide(
        ws, changes=[str(change["id"])], claims=[{"id": CLAIM, "rev": 2}], accept=False, by="ui:1"
    )
    assert out["adoption"] is None and out["files"] == []
    assert change_state(ws, str(change["id"])) == "rejected"
    assert basis.freeze(ws, "working", agent="agent-c").overlay == {}
    assert team_tree(ws) == team
    over = json.loads((ws / "knowledge" / "working" / "claims" / "shop.json").read_text("utf-8"))
    assert over["claims"] == []
    with pytest.raises(KnowledgeError) as caught:
        rules.decide(ws, changes=[str(change["id"])], claims=[], accept=True, by="ui:1")
    assert caught.value.code == "change_not_active"


# ---------------------------------------------------------------- 실패 주입 (사용자 파일 손상)

STAGES = [
    ("journal_write", "original"),
    ("created", "original"),
    ("publish_fsync", "original"),
    ("taken", "original"),
    ("replaced", "original"),
    ("before_commit", "original"),
    ("commit_fsync", "original"),
    ("after_commit", "done"),
    ("before_journal_remove", "done"),
]


def fault_rule(stage: str, action: str) -> str:
    return json.dumps(
        [
            {
                "point": "filetx.stage",
                "role": "supervisor",
                "when": {"event": stage, "nth": 1},
                "action": action,
            }
        ]
    )


def state(ws: Path, change_id: str) -> dict[str, Any]:
    """거래 결과의 뜻 (ID·시각과 무관)."""
    records = adoptions(ws)
    prev = sorted((ws / "knowledge" / "evidence").glob("e-*-prev"))
    return {
        "target": sha((ws / TARGET).read_bytes()),
        "tree": team_tree(ws),
        "records": sorted((r["kind"], r["reverted"] is not None) for r in records),
        "prev": len(prev),
        "change": change_state(ws, change_id),
        "case": case_doc(ws)["state"],
    }


def prepare(root: Path, op: str) -> tuple[str, str]:
    """(변경 ID, 연산 인자)."""
    change_id = setup(root)
    if op == "adopt":
        return change_id, change_id
    if op == "accept":
        return change_id, change_id
    record = Adopter(root, FakeVerifier()).request(CASE, change_id)
    return change_id, str(record["adoption"])


def run_op(root: Path, op: str, arg: str) -> Any:
    if op == "adopt":
        return Adopter(root, FakeVerifier()).request(CASE, arg)
    if op == "revert":
        return rules.revert(root, arg, by="human")
    return rules.decide(root, changes=[arg], claims=[], accept=True, by="human")


@pytest.fixture(scope="module")
def expected(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for op in ("adopt", "revert", "accept"):
        root = copy_example_workspace(tmp_path_factory.mktemp(op))
        change_id, arg = prepare(root, op)
        out[(op, "original")] = state(root, change_id)
        run_op(root, op, arg)
        out[(op, "done")] = state(root, change_id)
        assert out[(op, "original")] != out[(op, "done")]
    return out


def recover(root: Path) -> list[str]:
    with filetx.file_lock(root):
        return filetx.recover(root)


@pytest.mark.process
@pytest.mark.timeout(600)
@pytest.mark.parametrize("how", ["raise", "kill"])
@pytest.mark.parametrize("op", ["adopt", "revert", "accept"])
@pytest.mark.parametrize(("stage", "outcome"), STAGES, ids=[s for s, _ in STAGES])
def test_fault_points_adopt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expected: dict[tuple[str, str], dict[str, Any]],
    stage: str,
    outcome: str,
    op: str,
    how: str,
) -> None:
    """채택·되돌리기·묶음 수락의 모든 게시 단계와 (예외, 자식 kill): 복구 뒤 "원래" 또는
    "전부"."""
    root = copy_example_workspace(tmp_path)
    change_id, arg = prepare(root, op)
    if how == "kill":
        env = {**os.environ, "KOOKABUG_FAULTS": fault_rule(stage, "exit:9")}
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(CHILD), str(root), op, arg],
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert done.returncode == 9, done.stdout + done.stderr
    else:
        monkeypatch.setenv("KOOKABUG_FAULTS", fault_rule(stage, "raise"))
        _faults.set_role("supervisor")
        try:
            if outcome == "original":
                try:
                    out = run_op(root, op, arg)
                except RuntimeError, filetx.TxError, KnowledgeError:
                    pass
                else:  # 채택은 게시 실패를 결과로 돌려준다 (변경은 작업 기준에 남음)
                    assert op == "adopt" and out["adopted"] is False, out
                    assert out["failed"]["condition"] == 8, out
            else:
                run_op(root, op, arg)
        finally:
            _faults.reset()
            monkeypatch.delenv("KOOKABUG_FAULTS")
    recover(root)
    assert filetx.journals(root) == []
    assert state(root, change_id) == expected[(op, outcome)]
    assert recover(root) == []


# ---------------------------------------------------------------- daemon 메서드·실제 runner


def wait_ended(client: DaemonClient, run_id: str, timeout: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        status = client.call("run.status", {"run_id": run_id})
        if status["state"] == "ended":
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.3)


@pytest.mark.process
@pytest.mark.timeout(900)
def test_adopt_runs_original_with_only_this_change(ws: Path, ocr_models: Path) -> None:
    """실제 runner·예제 상점 가짜 게임: 구매 단추가 옮겨진 실패 → 옮긴 자리 locator 후보 →
    Kookabug가 원래 테스트·영향 테스트를 그 변경 하나만 덧씌워 돌리고 채택한다."""
    os.environ.setdefault("KOOKABUG_OCR_MODELS", str(ocr_models))
    graph = (ws / TEST).read_bytes()
    png = (ws / IMAGE).read_bytes()
    with ThreadDaemon(ws, platform_fake=ws / "fake-platform-shop.json") as d, d.client() as ui:
        started = ui.call("run.start", {"path": TEST, "profile": "shop_moved"})
        original = wait_ended(ui, started["run_id"])
        assert original["outcome"]["verdict"] == "fail", original
        write_case(ws, run_id=started["run_id"])
        candidate = moved_target(ws)
        change = basis.write(ws, {TARGET: candidate}, actor=AGENT, kind="locator_repair")
        assert (ws / TARGET).read_bytes() != candidate
        result = ui.call("adopt.request", {"case": CASE, "change": change["id"]}, timeout=900)
        assert result["adopted"] is True, result
        assert len(result["runs"]) == 2
        for n, run_id in enumerate(result["runs"]):
            folder = next((ws / "runs").glob(f"*_{run_id}"))
            run_json = json.loads((folder / "run.json").read_text("utf-8"))
            assert run_json["verdict"] == "pass", run_json
            assert run_json["basis"]["kind"] == "working"
            assert run_json["basis"]["adopt"] == result["manifest"]
            assert (folder / "snapshot" / TARGET).read_bytes() == candidate
            if n == 0:
                [claim] = run_json["qa"]["claims"]
                assert claim["executed"] == ASSERTIONS and claim["passed"] == ASSERTIONS
        # 에이전트 연결은 채택·되돌리기를 부르지 못한다 (B4가 도구를 붙일 때까지 사람만)
        agent_info = {"kind": "agent", "name": "mcp", "version": "0", "id": "a1", "attended": True}
        with d.client(agent_info) as agent:
            with pytest.raises(DaemonError) as caught:
                agent.call("adopt.revert", {"adoption": result["adoption"]}, timeout=60)
            assert caught.value.kind == "permission_denied"
        listed = ui.call("adoptions.list", {})
        assert [a["id"] for a in listed["adoptions"]] == [result["adoption"]]
        reverted = ui.call("adopt.revert", {"adoption": result["adoption"]})
        assert reverted["files"] == [TARGET]
        with pytest.raises(DaemonError) as caught:
            ui.call("adopt.revert", {"adoption": result["adoption"]})
        assert caught.value.kind == "already_reverted"
    assert (ws / TEST).read_bytes() == graph and (ws / IMAGE).read_bytes() == png


def test_methods_listed_and_errors(ws: Path) -> None:
    change_id = setup(ws)
    with ThreadDaemon(ws) as d, d.client() as ui:
        listed = ui.call("working.list", {})
        assert [c["id"] for c in listed["changes"]] == [change_id]
        assert listed["changes"][0]["effective_state"] == "active"
        with pytest.raises(DaemonError) as caught:
            ui.call("adopt.revert", {"adoption": "a-20261109-000000-ffff"})
        assert caught.value.kind == "not_found"
        out = ui.call("working.reject", {"changes": [change_id]})
        assert out["changes"] == [change_id]
        with pytest.raises(DaemonError) as caught:
            ui.call("working.accept", {"changes": [change_id]})
        assert caught.value.kind == "change_not_active"
