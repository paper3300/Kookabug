"""화면 지도 승격·이동 그래프 검사용 워크스페이스 (M7 B4).

확정 화면 `lobby`(/1, 세션 S에서 승격된 것 — 이동 `to: "result"`), `old`(/0), 세션 S 후보:

- `upgrade`: 이미지 조건 crop 하나·대표 스크린샷·요소·이동(`result`로, `lobby`로)
- `result`: 이미지 조건, 이동 `to: "upgrade"`
- `bag`: `of: "old"`(합치기 후보, 판정 조건 없음), 이동·요소
- `loading`: 판정 조건 없음(미완성)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from helpers.graphs import make_workspace, write_json, write_target

SESSION = "20261107-103000-a1b2"
SESSION_REL = f"screens/_explored/{SESSION}"
PNG = b"\x89PNG\r\n\x1a\n" + b"candidate-crop"
SHOT = b"\x89PNG\r\n\x1a\n" + b"candidate-shot"


def candidate_target(root: Path, key: str, n: int = 1, data: bytes = PNG) -> str:
    rel = f"{SESSION_REL}/targets/{key}/{n}.target.json"
    write_json(root, rel, {"format": "kookabug.target/0", "image": f"{n}.png"})
    (root / SESSION_REL / "targets" / key / f"{n}.png").write_bytes(data)
    return rel


def make_explored_workspace(root: Path) -> Path:
    make_workspace(root)
    write_target(root, "targets/lobby/title.target.json")
    write_json(
        root,
        "screens/lobby.screen.json",
        {
            "format": "kookabug.screen/1",
            "title": "로비",
            "detect": {"all": [{"$target": "targets/lobby/title.target.json"}]},
            "moves": [{"via": {"key": "f1"}, "to": "result", "status": "tried"}],
            "origin": {
                "kind": "explored",
                "session": SESSION,
                "agent": "a",
                "at": "2026-11-07T10:00:00Z",
            },
        },
    )
    write_json(
        root,
        "screens/old.screen.json",
        {
            "format": "kookabug.screen/0",
            "title": "옛 화면",
            "detect": {"all": [{"$target": "targets/lobby/title.target.json"}]},
        },
    )
    write_json(
        root,
        f"{SESSION_REL}/explore.json",
        {
            "format": "kookabug.explore/0",
            "id": SESSION,
            "title": "예제 탐색",
            "agent": {"id": "a"},
            "started_at": "2026-11-07T10:30:00Z",
            "ended_at": "2026-11-07T10:40:00Z",
            "status": "ended",
            "steps": 4,
            "max_steps": 200,
            "approvals": [],
            "promoted": {},
        },
    )
    origin = {"kind": "explored", "session": SESSION, "agent": "a", "at": "2026-11-07T10:31:02Z"}
    up_target = candidate_target(root, "upgrade")
    (root / SESSION_REL / "upgrade.shot.png").write_bytes(SHOT)
    write_json(
        root,
        f"{SESSION_REL}/upgrade.screen.json",
        {
            "format": "kookabug.screen/1",
            "title": "장비 강화",
            "kind": "screen",
            "detect": {"all": [{"$target": up_target}]},
            "shot": {
                "image": f"{SESSION_REL}/upgrade.shot.png",
                "client_size": [1024, 640],
                "scale": 1.0,
            },
            "elements": [{"name": "강화 버튼", "kind": "button", "rect": [0.7, 0.8, 0.12, 0.08]}],
            "moves": [
                {"via": {"click": {"element": "강화 버튼"}}, "to": "result", "status": "tried"},
                {"via": {"key": "esc"}, "to": "lobby", "status": "tried"},
                {
                    "via": {"click": {"point": [0.5, 0.9]}},
                    "to": None,
                    "status": "untried",
                    "note": "구매",
                },
            ],
            "origin": origin,
        },
    )
    res_target = candidate_target(root, "result")
    write_json(
        root,
        f"{SESSION_REL}/result.screen.json",
        {
            "format": "kookabug.screen/1",
            "title": "강화 결과",
            "kind": "popup",
            "detect": {"all": [{"$target": res_target}]},
            "moves": [{"via": {"key": "esc"}, "to": "upgrade", "status": "tried"}],
            "origin": origin,
        },
    )
    write_json(
        root,
        f"{SESSION_REL}/bag.screen.json",
        {
            "format": "kookabug.screen/1",
            "title": "가방",
            "of": "old",
            "elements": [{"name": "닫기", "kind": "button", "rect": [0.9, 0.0, 0.1, 0.1]}],
            "moves": [
                {"via": {"click": {"element": "닫기"}}, "to": "lobby", "status": "tried"},
                {"via": {"key": "i"}, "to": "upgrade", "status": "tried"},
            ],
            "origin": origin,
        },
    )
    write_json(
        root,
        f"{SESSION_REL}/loading.screen.json",
        {"format": "kookabug.screen/1", "title": "로딩", "origin": origin},
    )
    return root


def tree(root: Path) -> dict[str, bytes]:
    """사용자 파일 스냅샷: `screens/`·`targets/` 아래 파일 전부 (잠금·캐시·저널 제외)."""
    out: dict[str, bytes] = {}
    for top in ("screens", "targets"):
        base = root / top
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[path.relative_to(root).as_posix()] = path.read_bytes()
    return out


def revisions_for(root: Path, rels: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for rel in rels:
        path = root / rel
        out[rel] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return out


def read(root: Path, rel: str) -> Any:
    return json.loads((root / rel).read_text(encoding="utf-8"))
