"""화면 판정 파일 형식 `/1` (M7 계획 3.1): 읽기·후보 규칙·OCR 조건 모양, `/0` 그대로 읽기."""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers.graphs import make_workspace, write_json

from kookabug_core.schema import check_shape
from kookabug_core.screens import (
    MISPLACED,
    Condition,
    OcrCondition,
    ScreenFileError,
    candidate_ref,
    explored_candidates,
    is_explored,
    is_screen_key,
    parse_screen,
)

UPGRADE: dict[str, Any] = {
    "format": "kookabug.screen/1",
    "title": "장비 강화",
    "description": "장비를 골라 강화를 시도하는 화면. 강화를 누르면 결과 팝업이 뜬다.",
    "kind": "screen",
    "detect": {
        "all": [
            {"$target": "targets/screens/upgrade/title.target.json"},
            {"ocr": {"rect": [0.62, 0.40, 0.20, 0.06], "text": "강화 확률"}},
        ],
        "none": [{"$target": "targets/common/loading.target.json"}],
    },
    "shot": {"image": "screens/upgrade.shot.png", "client_size": [1024, 640], "scale": 1.0},
    "elements": [
        {"name": "강화 버튼", "kind": "button", "rect": [0.70, 0.80, 0.12, 0.08]},
        {"name": "강화 확률", "kind": "text", "rect": [0.62, 0.40, 0.20, 0.06]},
    ],
    "moves": [
        {"via": {"click": {"element": "강화 버튼"}}, "to": "upgrade_result", "status": "tried"},
        {"via": {"key": "esc"}, "to": "bag", "status": "tried"},
        {"via": {"click": {"point": [0.5, 0.9]}}, "to": None, "status": "untried", "note": "구매"},
    ],
    "origin": {
        "kind": "explored",
        "session": "20261107-103000-a1b2",
        "agent": "panel:3",
        "at": "2026-11-07T10:31:02Z",
    },
}
CANDIDATE = "screens/_explored/20261107-103000-a1b2/upgrade.screen.json"


def test_v1_parses_all_fields() -> None:
    assert check_shape(UPGRADE) == []
    screen = parse_screen(UPGRADE, "screens/upgrade.screen.json")
    assert (screen.id, screen.version, screen.kind, screen.title) == (
        "upgrade",
        1,
        "screen",
        "장비 강화",
    )
    assert screen.description is not None and screen.description.startswith("장비를")
    # all·none은 target 경로만(스냅샷·검증이 따라가는 것), conditions는 OCR까지 파일 순서로
    assert screen.all == ("targets/screens/upgrade/title.target.json",)
    assert screen.none == ("targets/common/loading.target.json",)
    assert screen.targets == (*screen.all, *screen.none)
    assert screen.detect() == (
        Condition("all", target="targets/screens/upgrade/title.target.json"),
        Condition("all", ocr=OcrCondition((0.62, 0.40, 0.20, 0.06), "강화 확률")),
        Condition("none", target="targets/common/loading.target.json"),
    )
    assert screen.shot is not None
    assert (screen.shot.image, screen.shot.client_size) == ("screens/upgrade.shot.png", (1024, 640))
    assert [(e.name, e.kind) for e in screen.elements] == [
        ("강화 버튼", "button"),
        ("강화 확률", "text"),
    ]
    first, esc, untried = screen.moves
    assert (first.element, first.to, first.status) == ("강화 버튼", "upgrade_result", "tried")
    assert (esc.key, esc.to) == ("esc", "bag")
    assert (untried.point, untried.to, untried.status, untried.note) == (
        (0.5, 0.9),
        None,
        "untried",
        "구매",
    )
    assert screen.origin is not None and screen.origin.session == "20261107-103000-a1b2"
    assert screen.of is None and not screen.incomplete


def test_v0_still_reads() -> None:
    data = {
        "detect": {"all": [{"$target": "targets/a.target.json"}]},
        "format": "kookabug.screen/0",
        "title": "로비",
    }
    assert check_shape(data) == []
    screen = parse_screen(data, "screens/lobby.screen.json")
    assert (screen.version, screen.all, screen.none, screen.title) == (
        0,
        ("targets/a.target.json",),
        (),
        "로비",
    )
    assert screen.detect() == (Condition("all", target="targets/a.target.json"),)
    # /0에는 OCR 조건·/1 필드를 쓸 수 없다
    bad = copy.deepcopy(data)
    bad["detect"]["all"].append({"ocr": {"rect": [0, 0, 1, 1], "text": "x"}})
    assert check_shape(bad) != []
    assert check_shape({**data, "moves": []}) != []


@pytest.mark.parametrize(
    ("ocr", "code", "pointer"),
    [
        ({"rect": [0, 0, 1], "text": "x"}, "out_of_range", "/detect/all/0/ocr/rect"),
        ({"rect": [0, 0, 1.5, 1], "text": "x"}, "out_of_range", "/detect/all/0/ocr/rect/2"),
        ({"rect": [0, 0, 1, 1], "text": ""}, "out_of_range", "/detect/all/0/ocr/text"),
        ({"rect": [0, 0, 1, 1], "text": "가" * 101}, "out_of_range", "/detect/all/0/ocr/text"),
        ({"rect": [0, 0, 1, 1]}, "missing_field", "/detect/all/0/ocr"),
        (
            {"rect": [0, 0, 1, 1], "text": "x", "match": "regex"},
            "invalid_value",
            "/detect/all/0/ocr/match",
        ),
        (
            {"rect": [0, 0, 1, 1], "text": "x", "lang": "ko"},
            "unknown_field",
            "/detect/all/0/ocr/lang",
        ),
    ],
)
def test_ocr_condition_shape(ocr: dict[str, Any], code: str, pointer: str) -> None:
    data = {"format": "kookabug.screen/1", "detect": {"all": [{"ocr": ocr}]}}
    found = {(d.code, d.pointer) for d in check_shape(data)}
    assert (code, pointer) in found, found


def test_ocr_condition_semantics() -> None:
    def ocr(rect: list[float], text: str = "강화") -> dict[str, Any]:
        return {
            "format": "kookabug.screen/1",
            "detect": {"all": [{"ocr": {"rect": rect, "text": text}}]},
        }

    assert parse_screen(ocr([0.5, 0.5, 0.5, 0.5]), "screens/a.screen.json").detect()[0].ocr
    for rect in ([0.6, 0, 0.5, 0.1], [0, 0, 0, 0.1]):  # 클라이언트 밖·빈 사각형
        with pytest.raises(ScreenFileError, match="0~1"):
            parse_screen(ocr(rect), "screens/a.screen.json")
    with pytest.raises(ScreenFileError, match="공백"):
        parse_screen(ocr([0, 0, 1, 1], "  "), "screens/a.screen.json")


def test_candidate_rules() -> None:
    # 확정 화면: detect가 있어야 하고 of를 쓰지 않는다. 후보: 둘 다 된다
    no_detect = {"format": "kookabug.screen/1", "title": "강화 결과"}
    with pytest.raises(ScreenFileError, match="판정 조건"):
        parse_screen(no_detect, "screens/result.screen.json")
    candidate = parse_screen(no_detect, CANDIDATE)
    assert candidate.incomplete
    merge = {**UPGRADE, "of": "upgrade_old"}
    with pytest.raises(ScreenFileError, match="of"):
        parse_screen(merge, "screens/upgrade.screen.json")
    assert parse_screen(merge, CANDIDATE).of == "upgrade_old"
    # of만 있는 합치기 후보는 조건이 없어도 미완성이 아니다 (확정 화면 조건으로 합친다)
    of_only = parse_screen({**no_detect, "of": "upgrade_old"}, CANDIDATE)
    assert not of_only.incomplete and of_only.detect() == ()
    assert is_explored(CANDIDATE) and is_explored("Screens/_Explored/s/a.screen.json")
    assert not is_explored("screens/upgrade.screen.json")
    assert is_screen_key("upgrade_2") and not is_screen_key("Upgrade") and not is_screen_key("2a")


def test_move_rules() -> None:
    def with_moves(*moves: dict[str, Any]) -> dict[str, Any]:
        return {**UPGRADE, "moves": list(moves)}

    path = "screens/upgrade.screen.json"
    with pytest.raises(ScreenFileError, match="to"):
        parse_screen(with_moves({"via": {"key": "esc"}, "status": "tried"}), path)
    with pytest.raises(ScreenFileError, match="elements"):
        parse_screen(
            with_moves({"via": {"click": {"element": "없음"}}, "to": "a", "status": "tried"}), path
        )
    with pytest.raises(ScreenFileError, match="키"):
        parse_screen(with_moves({"via": {"key": "nokey"}, "to": "a", "status": "tried"}), path)
    combo = parse_screen(
        with_moves({"via": {"key": "ctrl+i"}, "to": "bag", "status": "tried"}), path
    )
    assert combo.moves[0].key == "ctrl+i"
    dup = {**UPGRADE, "elements": [UPGRADE["elements"][0], UPGRADE["elements"][0]], "moves": []}
    with pytest.raises(ScreenFileError, match="겹친다"):
        parse_screen(dup, path)
    # to에 경로 구분자는 쓸 수 없다
    assert check_shape(with_moves({"via": {"key": "esc"}, "to": "a/b", "status": "tried"})) != []


def test_explored_placement_read_list_promote(tmp_path: Path) -> None:
    # _explored/ 아래 자리별로 읽기(후보 규칙)·목록(배치 진단)·승격 가능 여부를 한 표로 본다.
    # 정확한 자리는 screens/_explored/<세션 ID>/<키>.screen.json 하나뿐이다
    ws = make_workspace(tmp_path)
    s = "20261107-103000-a1b2"
    no_detect = {"format": "kookabug.screen/1", "title": "미완성"}
    files = {
        f"screens/_explored/{s}/upgrade.screen.json": UPGRADE,
        f"screens/_explored/{s}/merge.screen.json": {**no_detect, "of": "lobby"},
        f"screens/_explored/{s}/empty.screen.json": no_detect,
        f"screens/_explored/{s}/broken.screen.json": {"format": "x"},
        f"screens/_explored/{s}/Bad-Key.screen.json": UPGRADE,
        f"screens/_explored/{s}/deeper/inner.screen.json": UPGRADE,
        "screens/_explored/loose.screen.json": no_detect,
        "screens/_explored/not-a-session/upgrade.screen.json": UPGRADE,
    }
    for rel, data in files.items():
        write_json(ws, rel, data)
    write_json(ws, f"screens/_explored/{s}/explore.json", {"format": "kookabug.explore/0"})

    found = {c.path: c for c in explored_candidates(ws)}
    assert set(found) == set(files)  # 목록에서 조용히 빠지는 파일이 없다
    # (경로, 배치, 읽힘, 승격 가능)
    table = {
        f"screens/_explored/{s}/upgrade.screen.json": ("session", True, True),
        f"screens/_explored/{s}/merge.screen.json": ("session", True, True),
        f"screens/_explored/{s}/empty.screen.json": ("session", True, False),
        f"screens/_explored/{s}/broken.screen.json": ("session", False, False),
        f"screens/_explored/{s}/Bad-Key.screen.json": ("misplaced", True, False),
        f"screens/_explored/{s}/deeper/inner.screen.json": ("misplaced", True, False),
        "screens/_explored/loose.screen.json": ("misplaced", True, False),
        "screens/_explored/not-a-session/upgrade.screen.json": ("misplaced", True, False),
    }
    for rel, (placement, readable, promotable) in table.items():
        c = found[rel]
        assert (c.placement, c.screen is not None, c.promotable) == (
            placement,
            readable,
            promotable,
        ), rel
        # 호환 읽기: _explored/ 아래는 어디든 후보 규칙(detect 생략·of 허용)으로 읽힌다
        assert is_explored(rel)
        assert (candidate_ref(rel) is not None) == (placement == "session"), rel
        if placement == "misplaced":
            assert c.session is None and c.problem == MISPLACED, rel
    assert candidate_ref(f"screens/_explored/{s}/upgrade.screen.json") == (s, "upgrade")
    assert found["screens/_explored/loose.screen.json"].screen is not None
    assert found[f"screens/_explored/{s}/broken.screen.json"].problem is not None


def test_explore_json_shape() -> None:
    record = {
        "format": "kookabug.explore/0",
        "id": "20261107-103000-a1b2",
        "title": "예제 게임 탐색",
        "agent": {"id": "panel:3", "client": "claude"},
        "started_at": "2026-11-07T10:30:00Z",
        "ended_at": None,
        "status": "active",
        "steps": 0,
        "max_steps": 200,
        "approvals": [
            {
                "tool": "kb_input_click",
                "arg": "Sample RPG",
                "scope": "session",
                "at": "2026-11-07T10:30:05Z",
            }
        ],
        "promoted": {"upgrade": "upgrade"},
    }
    assert check_shape(record) == []
    bad = {**record, "max_steps": 1001, "promoted": {"Bad": "x"}, "title": "가" * 201}
    codes = {(d.code, d.pointer) for d in check_shape(bad)}
    assert ("out_of_range", "/max_steps") in codes
    assert ("out_of_range", "/title") in codes
    assert ("invalid_key", "/promoted/Bad") in codes


@pytest.mark.parametrize(
    "module",
    [
        "kookabug_core.screens",
        "kookabug_core.loader",
        "kookabug_core.record.snapshot",
        "kookabug_core.inputs.keys",
        "kookabug_core.runner.spec",
    ],
)
def test_import_alone(module: str) -> None:
    # 화면 파일 읽기가 키 표(engine 패키지)를 써도 import 고리가 없게 (새 프로세스에서 먼저 읽기)
    done = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr
