"""증거 묶음 고정 (M8 계획 3.2·C8·C9·U6, B3) — 엄격: 비밀값.

- 묶음은 가린 최소 증거만: 이벤트는 안전 필드, 이미지는 보호 판정 `clear`인 것만 480px 사본,
  나머지는 `omitted`(사유). 비밀값 입력이 있는 실패 실행에서 묶음의 모든 파일에 값이
  0이다(원본 기록엔 있음 — 양성 대조)
- 지우거나 고치는 도구가 없다: 같은 ID로 다시 쓰지 않고, 어떤 쓰기 경로도 `knowledge/evidence/`에
  닿지 않는다
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kb_testing.sample_game import copy_example_workspace
from kookabug_core import basis, evidence
from kookabug_core.knowledge import ops
from kookabug_core.knowledge.formats import Actor, KnowledgeError, normalize, secret_checker
from kookabug_core.workspace import MemorySecrets
from kookabug_daemon.adopt import pin_run
from kookabug_daemon.methods.tools import METHOD_TOOLS
from kookabug_platform.frames import decode_image, encode_png

SECRET = "Hunter2-Evidence-Secret"
KEY = "login.password"
RUN_ID = "b3evidence000001"
ACTOR = Actor("agent", "agent-e")


def png(color: tuple[int, int, int], size: tuple[int, int] = (1024, 640)) -> bytes:
    pixels = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    pixels[:, :] = color
    return bytes(encode_png(pixels))


def write_run(ws: Path, *, graph: str = "tests/shop/buy_potion.graph.json") -> Path:
    """비밀값을 입력한 뒤 구매 단추를 못 찾고 실패한 실행 기록 (runner가 남기는 모양)."""
    folder = ws / "runs" / f"20261109-000001_{RUN_ID}"
    (folder / "steps").mkdir(parents=True)
    (folder / "snapshot" / "tests" / "shop").mkdir(parents=True)
    (folder / "snapshot" / "tests" / "shop" / "buy_potion.graph.json").write_bytes(
        (ws / "tests" / "shop" / "buy_potion.graph.json").read_bytes()
    )
    (folder / "steps" / "s1_after.png").write_bytes(png((10, 10, 10)))
    (folder / "steps" / "s3_fail.png").write_bytes(png((0, 120, 0)))
    (folder / "steps" / "s3_guarded.png").write_bytes(png((200, 0, 0)))
    events: list[dict[str, Any]] = [
        {"event": "run.start", "seq": 1, "t": "2026-11-09T00:00:00Z", "run": RUN_ID},
        {"event": "step.start", "seq": 2, "step": "s1", "node": "n_type", "path": ["n_type"]},
        {
            "event": "step.end",
            "seq": 3,
            "step": "s1",
            "status": "ok",
            "secret": True,
            "in": {"text": SECRET},
            "message": f"입력함 {SECRET}",
            "artifacts": ["steps/s1_after.png"],
        },
        {"event": "log", "seq": 4, "level": "info", "message": f"value={SECRET}"},
        {
            "event": "step.start",
            "seq": 5,
            "step": "s3",
            "node": "n_click_buy",
            "path": ["n_click_buy"],
        },
        {
            "event": "step.end",
            "seq": 6,
            "step": "s3",
            "status": "failed",
            "exit": "fail",
            "error": {"code": "target_not_found", "message": f"못 찾음 ({SECRET})"},
            "artifacts": ["steps/s3_fail.png", "steps/s3_guarded.png"],
        },
        {
            "event": "run.end",
            "seq": 7,
            "verdict": "fail",
            "failure_step": "s3",
            "code": "unhandled_fail",
        },
    ]
    body = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events)
    (folder / "events.jsonl").write_text(body, encoding="utf-8")
    run_json = {
        "format": "kookabug.run/0",
        "run_id": RUN_ID,
        "graph": graph,
        "status": "finished",
        "started_at": "2026-11-09T00:00:00Z",
        "ended_at": "2026-11-09T00:00:09Z",
        "verdict": "fail",
        "code": "unhandled_fail",
        "failure_step": "s3",
        "agent_mask": 1,
        "conditions": {
            "profile": "shop_moved",
            "platform": "fake",
            "settings": {KEY: {"secret": True}},
        },
        "secret_paths": [],
    }
    (folder / "run.json").write_text(json.dumps(run_json, ensure_ascii=False), encoding="utf-8")
    return folder


def guard_of(pixels: Any) -> str:
    """보호 판정 대역: 빨간 화면은 민감 대상이 보이는 화면."""
    return "sensitive_visible" if int(pixels[0, 0, 0]) > 150 else "clear"


def pin(ws: Path, folder: Path, **kw: Any) -> dict[str, Any]:
    check = secret_checker([KEY], MemorySecrets({KEY: SECRET}))
    return pin_run(
        ws,
        folder,
        RUN_ID,
        step=None,
        note="원래 실패 고정",
        by={"kind": "agent", "id": "agent-e"},
        actor=ACTOR,
        check_secrets=check,
        guard_of=guard_of,
        **kw,
    )


def has_secret(data: bytes) -> bool:
    return normalize(SECRET) in normalize(data.decode("utf-8", errors="replace"))


def test_pin_minimal_redacted_bundle(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    folder = write_run(ws)
    # 양성 대조: 원본 기록에는 값이 있다
    assert has_secret((folder / "events.jsonl").read_bytes())
    out = pin(ws, folder, bundle_id="e-20261109-000001-0001")
    bundle = ws / "knowledge" / "evidence" / out["id"]
    names = sorted(p.name for p in bundle.iterdir())
    assert names == ["events.jsonl", "manifest.json", "run.json", "s3_fail.png"]
    for path in bundle.iterdir():
        assert not has_secret(path.read_bytes()), path.name
    manifest = json.loads((bundle / "manifest.json").read_text("utf-8"))
    assert {"what": "s3_guarded.png", "reason": "sensitive_visible"} in manifest["omitted"]
    assert manifest["failed_step"] == {
        "step": "s3",
        "node": "n_click_buy",
        "code": "target_not_found",
    }
    assert manifest["verdict"] == "fail" and manifest["run"] == RUN_ID
    assert manifest["env"]["profile"] == "shop_moved"
    assert manifest["graph_sha"] is not None
    # 비밀 스텝(s1)의 이미지는 고른 실패 스텝이 아니라 들지 않는다. 이미지는 긴 변 480px 사본
    small = np.asarray(decode_image((bundle / "s3_fail.png").read_bytes()))
    assert small.shape[:2] == (300, 480)
    events = [
        json.loads(line) for line in (bundle / "events.jsonl").read_text("utf-8").splitlines()
    ]
    assert all("message" not in e and "in" not in e for e in events)
    assert any(e.get("error") == {"code": "target_not_found"} for e in events)
    summary = json.loads((bundle / "run.json").read_text("utf-8"))
    assert summary["conditions"]["settings"] == {KEY: {"secret": True}}
    assert evidence.load_manifest(ws, out["id"]) is not None
    log = (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()
    assert json.loads(log[-1])["op"] == "evidence_pin"
    # 안전 필드에 값이 섞여도(그래프 경로 등) 마지막 글자 검사가 그 파일을 뺀다
    other = copy_example_workspace(tmp_path / "b")
    folder = write_run(other, graph=f"tests/{SECRET}.graph.json")
    out = pin(other, folder, bundle_id="e-20261109-000001-0002")
    bundle = other / "knowledge" / "evidence" / out["id"]
    assert {"what": "run.json", "reason": "secret_in_text"} in out["omitted"]
    for path in bundle.iterdir():
        assert not has_secret(path.read_bytes()), path.name
    # 사람이 쓴 메모에 값이 있으면 묶음을 만들지 않는다
    with pytest.raises(KnowledgeError) as caught:
        pin_run(
            ws,
            write_run(copy_example_workspace(tmp_path / "c")),
            RUN_ID,
            step=None,
            note=f"비밀 {SECRET}",
            by={"kind": "agent"},
            actor=ACTOR,
            check_secrets=secret_checker([KEY], MemorySecrets({KEY: SECRET})),
            guard_of=guard_of,
        )
    assert caught.value.code == "secret_in_text"


def test_review_evidence_manifest_secret(tmp_path: Path) -> None:
    """manifest 자체(`extra`의 원본 필드 복사·파일 이름·생략 목록)도 마지막 글자 검사를 거친다:
    걸린 필드는 값 없이 빠지고 `omitted`에는 위치만 남는다."""
    ws = copy_example_workspace(tmp_path)
    folder = write_run(ws)
    run_json = json.loads((folder / "run.json").read_text("utf-8"))
    run_json["conditions"]["profile"] = SECRET
    (folder / "run.json").write_text(json.dumps(run_json, ensure_ascii=False), encoding="utf-8")
    # 실패 스텝의 이미지 이름에도 값이 섞인 경우
    named = f"s3_{SECRET}.png"
    (folder / "steps" / named).write_bytes(png((0, 90, 0)))
    events = (
        (folder / "events.jsonl")
        .read_text("utf-8")
        .replace('"steps/s3_guarded.png"]', f'"steps/s3_guarded.png", "steps/{named}"]')
    )
    (folder / "events.jsonl").write_text(events, encoding="utf-8")
    out = pin(ws, folder, bundle_id="e-20261109-000001-0003")
    bundle = ws / "knowledge" / "evidence" / out["id"]
    assert {"what": "run.json", "reason": "secret_in_text"} in out["omitted"]
    for path in bundle.iterdir():
        assert not has_secret(path.read_bytes()), path.name
    manifest = json.loads((bundle / "manifest.json").read_text("utf-8"))
    assert "profile" not in manifest["env"]
    assert manifest["env"]["platform"] == "fake"
    reasons = {o["what"] for o in manifest["omitted"] if o["reason"] == "secret_in_text"}
    # run.json·env.profile(위치만)·이미지 이름(자리 이름만)
    assert "run.json" in reasons, reasons
    assert any(w.startswith("manifest/#") for w in reasons), reasons
    assert any(w.startswith("#image") for w in reasons), reasons
    assert all(normalize(SECRET) not in normalize(o["what"]) for o in manifest["omitted"])
    assert "s3_fail.png" in [f["path"] for f in manifest["files"]]
    assert not has_secret(json.dumps(out, ensure_ascii=False).encode())
    assert not has_secret((ws / "knowledge" / "log.jsonl").read_bytes())
    assert not has_secret((ws / "wiki" / "log.md").read_bytes())
    # 감사 이력에 들어갈 주체 글자가 걸리면 묶음을 만들지 않는다
    other = copy_example_workspace(tmp_path / "b")
    with pytest.raises(KnowledgeError) as caught:
        pin_run(
            other,
            write_run(other),
            RUN_ID,
            step=None,
            note="원래 실패 고정",
            by={"kind": "agent", "id": "agent-e"},
            actor=Actor("agent", "agent-e", client=f"client {SECRET}"),
            check_secrets=secret_checker([KEY], MemorySecrets({KEY: SECRET})),
            guard_of=guard_of,
        )
    assert caught.value.code == "secret_in_text"
    assert not (other / "knowledge" / "evidence").exists() or not any(
        p.name.startswith("e-") for p in (other / "knowledge" / "evidence").iterdir()
    )
    # 뺄 수 없는 필수 필드(by.kind)에 걸리면 거부
    check = secret_checker([KEY], MemorySecrets({KEY: "agent"}))
    with pytest.raises(KnowledgeError) as caught:
        evidence.build(
            bundle_id="e-20261109-000001-0004",
            run_id=None,
            by={"kind": "agent"},
            check_secrets=check,
        )
    assert caught.value.code == "secret_in_text"


def test_no_tool_deletes_evidence(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    neg = ws / "knowledge" / "evidence" / "neg-shop-sell"
    before = {p.name: p.read_bytes() for p in neg.iterdir()}
    # daemon 메서드는 고정(pin)뿐이다 — 지우기·고치기 메서드가 없다
    assert sorted(m for m in METHOD_TOOLS if m.startswith("evidence.")) == ["evidence.pin"]
    # 같은 ID로 다시 쓰지 않는다
    bundle = evidence.raw(
        bundle_id="neg-shop-sell",
        files={"x.png": b"x"},
        by={"kind": "agent"},
        origin="덮어쓰기 시도",
    )
    with pytest.raises(KnowledgeError) as caught:
        evidence.publish(ws, bundle, actor=ACTOR)
    assert caught.value.code == "exists"
    # 지식 연산·위키 쓰기·작업 기준 쓰기 어느 쪽도 knowledge/evidence/에 닿지 않는다
    with pytest.raises(KnowledgeError) as caught:
        ops.apply(
            ws,
            {
                "request_id": "r1",
                "ops": [
                    {"op": "add", "file": "evidence/neg-shop-sell", "base_revision": 0, "item": {}}
                ],
            },
            actor=ACTOR,
            check_secrets=lambda _: None,
        )
    assert caught.value.code == "policy_path"
    with pytest.raises(KnowledgeError) as caught:
        ops.wiki_write(
            ws,
            "knowledge/evidence/neg-shop-sell/manifest.json",
            "{}",
            None,
            actor=ACTOR,
            check_secrets=lambda _: None,
        )
    assert caught.value.code == "policy_path"
    with pytest.raises(KnowledgeError) as caught:
        basis.write(ws, {"knowledge/evidence/neg-shop-sell/shop_missing.png": b"x"}, actor=ACTOR)
    assert caught.value.code == "policy_path"
    assert {p.name: p.read_bytes() for p in neg.iterdir()} == before


def test_negative_paths_canonical_only(tmp_path: Path) -> None:
    """음성 대조 묶음은 정규형 경로로만 만들고(`build`), 정규형이 아닌 묶음은 `load_manifest`가
    음성 대조에서 뺀다(이유를 남긴다). `negative`가 없는 묶음(되돌리기용 원래 바이트)은 그대로다."""
    ws = copy_example_workspace(tmp_path)
    png = bytes(encode_png(np.zeros((4, 4, 3), dtype=np.uint8)))
    good = {"targets": ["targets/shop/buy.target.json"], "frames": ["a.png"]}
    bundle = evidence.build(
        bundle_id="neg-review-ok",
        run_id=None,
        by={"kind": "human"},
        check_secrets=lambda _: None,
        images=[evidence.Image("a.png", png, "clear")],
        extra={"negative": good, "origin": "검사"},
    )
    assert bundle.manifest["negative"] == good
    for bad in (
        {"targets": ["targets//shop/buy.target.json"], "frames": ["a.png"]},
        {"targets": ["targets/shop/./buy.target.json"], "frames": ["a.png"]},
        {"targets": ["targets/x/../shop/buy.target.json"], "frames": ["a.png"]},
    ):
        with pytest.raises(KnowledgeError) as caught:
            evidence.build(
                bundle_id="neg-review-bad",
                run_id=None,
                by={"kind": "human"},
                check_secrets=lambda _: None,
                images=[evidence.Image("a.png", png, "clear")],
                extra={"negative": bad, "origin": "검사"},
            )
        assert caught.value.code == "format"
    # 같은 파일의 다른 철자 이미지 두 개는 하나만 담는다
    twice = evidence.build(
        bundle_id="e-review-twice",
        run_id=None,
        by={"kind": "human"},
        check_secrets=lambda _: None,
        images=[evidence.Image("a.png", png, "clear"), evidence.Image("A.PNG", png, "clear")],
    )
    assert [f["path"] for f in twice.manifest["files"]] == ["a.png"]
    assert {"what": "image", "reason": "bad_name"} in twice.manifest["omitted"]
    # 읽기: files[].path 두 개가 같은 파일이면 음성 대조에 쓰지 않는다
    neg = ws / "knowledge" / "evidence" / "neg-shop-sell"
    doc = json.loads((neg / "manifest.json").read_text("utf-8"))
    doc["files"].append(dict(doc["files"][0], path="SHOP_MISSING.png"))
    (neg / "manifest.json").write_text(json.dumps(doc), encoding="utf-8")
    loaded = evidence.load_manifest(ws, "neg-shop-sell")
    assert loaded is not None and "negative" not in loaded
    assert loaded[evidence.NEGATIVE_IGNORED] == {
        "reason": "files[].path에 같은 파일의 다른 철자가 있다",
        "targets": ["targets/shop/buy.target.json"],
    }
    assert evidence.canonical_rel("targets/shop/buy.target.json")
    for rel in ("", "a//b", "./a", "a/..", "a\\b", "c:/a", "/a"):
        assert not evidence.canonical_rel(rel), rel
