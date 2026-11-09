"""자동 채택 검사 재료 (M8 B3): 예제 워크스페이스 + 원래 실패 실행 기록·사건·작업 기준 후보.

사건 열기(B4)가 만들 모양 그대로 사건 파일을 쓰고, 원래 실패 실행의 스냅샷에는 판정 의존성 바이트를
둔다. `FakeVerifier`는 검증 실행 대역이다 — 받은 덧씌움(manifest 폐포) 그대로의 스냅샷 sha를
돌려준다.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from kookabug_core import basis
from kookabug_core.canonical import canonical_dumps
from kookabug_core.knowledge.formats import Actor

TEST = "tests/shop/buy_potion.graph.json"
AFFECTED = "tests/shop/buy_then_close.graph.json"
TARGET = "targets/shop/buy.target.json"
IMAGE = "targets/shop/buy.png"
CLAIM = "shop.potion.price"
RUN_ID = "b3adopt0000000001"
CASE = "c-20261109-000000-0001"
AGENT = Actor("agent", "agent-c")
ASSERTIONS = ["n_assert_gold", "n_assert_item"]
JUDGMENT = (TEST, "targets/shop/potion_bought.target.json", "targets/shop/potion_bought.png")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def moved_target(ws: Path, x: float = 0.6445, y: float = 0.8125, **extra: Any) -> bytes:
    """구매 단추가 옮겨진 자리로 검색 범위만 옮긴 target (같은 넓이, 같은 그림)."""
    value = json.loads((ws / TARGET).read_text("utf-8"))
    value["search"]["region"] = [x, y, 0.2539, 0.1875]
    value.update(extra)
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write_original_run(ws: Path, run_id: str = RUN_ID, profile: str | None = "shop_moved") -> Path:
    folder = ws / "runs" / f"20261109-000000_{run_id}"
    for rel in (*JUDGMENT, "kookabug.json"):  # runner 스냅샷처럼 kookabug.json도
        dst = folder / "snapshot" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ws / rel, dst)
    run_json = {
        "format": "kookabug.run/0",
        "run_id": run_id,
        "graph": TEST,
        "status": "finished",
        "started_at": "2026-11-09T00:00:00Z",
        "verdict": "fail",
        "conditions": {"profile": profile},
    }
    (folder / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    return folder


def write_case(
    ws: Path, case_id: str = CASE, run_id: str = RUN_ID, **original: Any
) -> dict[str, Any]:
    graph = (ws / TEST).read_bytes()
    doc: dict[str, Any] = {
        "format": "kookabug.case/0",
        "id": case_id,
        "revision": 1,
        "title": "상점 구매 단추를 못 찾음",
        "state": "open",
        "signature": "sha256:" + "0" * 64,
        "symptom": {
            "kind": "target_missing",
            "test": TEST,
            "node": "n_click_buy",
            "code": "target_not_found",
        },
        "original": {
            "run": run_id,
            "evidence": None,
            "graph_sha": sha(graph),
            "claims": [{"id": CLAIM, "rev": 1}],
            "basis": {"kind": "team"},
            **original,
        },
        "runs": [],
        "links": {"claims": [], "working": [], "adoption": None, "reports": []},
        "resolution": None,
    }
    path = ws / "knowledge" / "cases" / f"{case_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_dumps(doc), encoding="utf-8")
    return doc


def setup(
    ws: Path, candidate: bytes | None = None, *, extra: Mapping[str, bytes] | None = None
) -> str:
    """원래 실패 실행·사건·후보 변경 하나 (변경 ID)."""
    write_original_run(ws)
    write_case(ws)
    files = {TARGET: candidate if candidate is not None else moved_target(ws), **(extra or {})}
    return str(basis.write(ws, files, actor=AGENT, kind="locator_repair")["id"])


def case_doc(ws: Path, case_id: str = CASE) -> dict[str, Any]:
    return json.loads((ws / "knowledge" / "cases" / f"{case_id}.json").read_text("utf-8"))


def adoptions(ws: Path) -> list[dict[str, Any]]:
    folder = ws / "knowledge" / "adoptions"
    return [json.loads(p.read_text("utf-8")) for p in sorted(folder.glob("a-*.json"))]


class FakeVerifier:
    """검증 실행 대역. `verdicts`(테스트 → 판정), `executed`·`passed`(필수 검증 노드 실행·통과),
    `hook(graph)`는 실행 도중 일(사람·다른 작업이 파일을 바꾸는 경우)."""

    def __init__(
        self,
        *,
        verdicts: Mapping[str, str] | None = None,
        executed: bool = True,
        passed: bool = True,
        hook: Callable[[str], None] | None = None,
        snapshot_extra: Mapping[str, str] | None = None,
    ) -> None:
        self.verdicts = dict(verdicts or {})
        self.executed = executed
        self.passed = passed
        self.hook = hook
        self.snapshot_extra = dict(snapshot_extra or {})
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        graph: str,
        overlay: Mapping[str, bytes],
        *,
        profile: str | None,
        basis: Mapping[str, Any],
    ) -> Any:
        from kookabug_daemon.adopt import VerifyOutcome

        self.calls.append(
            {"graph": graph, "overlay": dict(overlay), "profile": profile, "basis": dict(basis)}
        )
        if self.hook is not None:
            self.hook(graph)
        nodes = ASSERTIONS if self.executed else []
        qa = {
            "claims": [
                {
                    "id": CLAIM,
                    "rev": 1,
                    "assertions": ASSERTIONS,
                    "executed": nodes,
                    "passed": nodes if self.passed else [],
                }
            ]
        }
        snapshot = {rel: sha(data) for rel, data in overlay.items()} | self.snapshot_extra
        return VerifyOutcome(
            f"verify{len(self.calls):04d}",
            verdict=self.verdicts.get(graph, "pass"),
            qa=qa,
            snapshot=snapshot,
        )
