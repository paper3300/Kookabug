"""화면 지도 승격 거래 (M7 계획 3.7·10장 R4, B4) — 엄격: 사용자 파일 손상.

승격 중 어느 지점에서 죽어도 복구 뒤 "승격본 완전 + 후보 없음" 또는 "원래 그대로" 둘 중 하나다. 외부
편집이 끼면 사용자 바이트를 보존하고 경고·저널을 남긴다. 링크·정션 경유 쓰기·지우기는 없다.
"""

from __future__ import annotations

import _winapi
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Literal

import pytest
from helpers.explored import SESSION, SESSION_REL, make_explored_workspace, read, tree
from helpers.graphs import GraphBuilder, check

from kookabug_core.screen_promote import (
    PromoteError,
    PromoteRequest,
    discard,
    journals,
    pending,
    promote,
    recover_locked,
)
from kookabug_core.screen_promote import check as check_promote
from kookabug_core.workspace import Workspace
from kookabug_sdk import _faults

CHILD = Path(__file__).parent / "procs" / "promote_child.py"


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    return make_explored_workspace(tmp_path / "ws")


def request(root: Path, key: str, **kw: Any) -> PromoteRequest:
    """확인(check)으로 revision을 받아 그대로 넘기는 요청 (사람 흐름)."""
    base = PromoteRequest(SESSION, key, **kw)
    checked = check_promote(root, base)
    assert checked["ok"], checked
    return PromoteRequest(SESSION, key, base_revisions=checked["revisions"], **kw)


def explore(root: Path) -> dict[str, Any]:
    return read(root, f"{SESSION_REL}/explore.json")


def test_promote_new(ws: Path) -> None:
    result = promote(ws, request(ws, "upgrade"))
    assert result == {
        "path": "screens/upgrade.screen.json",
        "id": "upgrade",
        "cleanup_pending": False,
        "warnings": [],
    }
    card = read(ws, "screens/upgrade.screen.json")
    assert card["format"] == "kookabug.screen/1" and "of" not in card
    assert card["detect"] == {"all": [{"$target": "targets/screens/upgrade/1.target.json"}]}
    assert read(ws, "targets/screens/upgrade/1.target.json")["image"] == "1.png"
    assert (ws / "targets/screens/upgrade/1.png").is_file()
    assert card["shot"]["image"] == "screens/upgrade.shot.png"
    assert (ws / "screens/upgrade.shot.png").is_file()
    assert card["origin"]["session"] == SESSION
    # 후보 파일은 모두 지워졌고, 다른 후보는 그대로
    assert not (ws / SESSION_REL / "upgrade.screen.json").exists()
    assert not (ws / SESSION_REL / "upgrade.shot.png").exists()
    assert not (ws / SESSION_REL / "targets" / "upgrade").exists()
    assert (ws / SESSION_REL / "result.screen.json").is_file()
    assert explore(ws)["promoted"] == {"upgrade": "upgrade"}
    assert journals(ws) == []
    # 폴더를 정해 옮기기·예약 장치 이름 거부
    promote(ws, request(ws, "result", folder="shop", id="upgrade_result"))
    assert (ws / "screens/shop/upgrade_result.screen.json").is_file()
    with pytest.raises(PromoteError) as caught:
        promote(ws, PromoteRequest(SESSION, "loading", id="con"))
    assert caught.value.code == "validation_failed"


def test_reserved_device_ids_refused(ws: Path) -> None:
    for bad in ("con", "nul", "aux", "prn", "com1", "lpt9"):
        checked = check_promote(ws, PromoteRequest(SESSION, "upgrade", id=bad))
        assert not checked["ok"] and checked["code"] == "validation_failed", bad
    checked = check_promote(ws, PromoteRequest(SESSION, "upgrade", folder="lpt1"))
    assert not checked["ok"]


def test_promote_rename_rewrites_session_refs(ws: Path) -> None:
    promote(ws, request(ws, "result", id="upgrade_result"))
    assert (ws / "screens/upgrade_result.screen.json").is_file()
    # 같은 세션 남은 후보와 같은 세션에서 승격된 확정 화면의 to: result → upgrade_result
    up = read(ws, f"{SESSION_REL}/upgrade.screen.json")
    assert [m["to"] for m in up["moves"]] == ["upgrade_result", "lobby", None]
    lobby = read(ws, "screens/lobby.screen.json")
    assert lobby["moves"][0]["to"] == "upgrade_result"
    assert explore(ws)["promoted"] == {"result": "upgrade_result"}
    # 다음 승격은 이미 승격된 키를 ID로 고친다 (bag의 to: upgrade → 승격된 ID)
    promote(ws, request(ws, "upgrade", id="enhance"))
    bag = read(ws, f"{SESSION_REL}/bag.screen.json")
    assert [m["to"] for m in bag["moves"]] == ["lobby", "enhance"]
    promoted = read(ws, "screens/upgrade_result.screen.json")
    assert promoted["moves"][0]["to"] == "enhance"  # 같은 세션에서 승격된 확정 화면
    assert explore(ws)["promoted"] == {"result": "upgrade_result", "upgrade": "enhance"}


def test_merge_adds_moves_elements_only(ws: Path) -> None:
    before = read(ws, "screens/old.screen.json")
    promote(ws, request(ws, "bag", mode="merge"))
    after = read(ws, "screens/old.screen.json")
    assert after["title"] == before["title"] == "옛 화면"
    assert after["detect"] == before["detect"]  # 체크하지 않았으니 판정 조건 그대로
    assert "shot" not in after
    assert [e["name"] for e in after["elements"]] == ["닫기"]
    assert [m["to"] for m in after["moves"]] == ["lobby", "upgrade"]
    assert not (ws / SESSION_REL / "bag.screen.json").exists()
    assert explore(ws)["promoted"] == {"bag": "old"}
    # 같은 이동·요소는 다시 더하지 않는다 (bag을 다시 저장해 다시 합침)
    shutil.copy(ws / "screens/old.screen.json", ws / "copy.json")
    (ws / SESSION_REL / "bag.screen.json").write_text(
        json.dumps(
            {
                "format": "kookabug.screen/1",
                "of": "old",
                "elements": [{"name": "닫기", "kind": "button", "rect": [0.9, 0.0, 0.1, 0.1]}],
                "moves": [
                    {"via": {"click": {"element": "닫기"}}, "to": "lobby", "status": "tried"}
                ],
            }
        ),
        encoding="utf-8",
    )
    result = promote(ws, request(ws, "bag", mode="merge"))
    again = read(ws, "screens/old.screen.json")
    assert again["moves"] == after["moves"] and again["elements"] == after["elements"]
    assert result["warnings"] == ["더할 이동·요소가 없다 (후보만 지운다)"]


def test_merge_replace_shot_and_detect(ws: Path) -> None:
    # upgrade(판정 조건·스크린샷 있음)를 lobby에 합치며 둘 다 바꾼다
    promote(
        ws, request(ws, "upgrade", mode="merge", id="lobby", replace_shot=True, replace_detect=True)
    )
    lobby = read(ws, "screens/lobby.screen.json")
    assert lobby["shot"]["image"] == "screens/lobby.shot.png"
    (cond,) = lobby["detect"]["all"]
    assert cond["$target"].startswith("targets/screens/lobby/")
    assert (ws / cond["$target"]).is_file()
    assert lobby["title"] == "로비"  # 제목은 그대로


def test_merge_v0_upgrades_format(ws: Path) -> None:
    raw = (ws / "screens/old.screen.json").read_text(encoding="utf-8")
    assert '"kookabug.screen/0"' in raw
    promote(ws, request(ws, "bag", mode="merge"))
    after = read(ws, "screens/old.screen.json")
    assert after["format"] == "kookabug.screen/1"
    # 원래 키는 그대로 두고 더하기만 한다
    original = json.loads(raw)
    assert {k: after[k] for k in original if k != "format"} == {
        k: v for k, v in original.items() if k != "format"
    }
    # canonical 형식으로 썼고 다시 읽힌다
    from kookabug_core.canonical import canonical_dumps

    text = (ws / "screens/old.screen.json").read_text(encoding="utf-8")
    assert text == canonical_dumps(after)


def test_revision_conflict_writes_nothing(ws: Path) -> None:
    req = request(ws, "result", id="upgrade_result")
    assert f"{SESSION_REL}/upgrade.screen.json" in req.base_revisions  # 고칠 후보도 revision에
    # 확인 뒤 에이전트가 upgrade 후보를 다시 저장했다
    path = ws / SESSION_REL / "upgrade.screen.json"
    path.write_text(path.read_text(encoding="utf-8").replace("장비 강화", "강화"), encoding="utf-8")
    before = tree(ws)
    with pytest.raises(PromoteError) as caught:
        promote(ws, req)
    assert caught.value.code == "revision_conflict"
    assert f"{SESSION_REL}/upgrade.screen.json" in caught.value.fields["paths"]
    assert tree(ws) == before
    assert journals(ws) == []


def test_exists_refused(ws: Path) -> None:
    before = tree(ws)
    for taken in ("lobby", "old"):
        with pytest.raises(PromoteError) as caught:
            promote(ws, PromoteRequest(SESSION, "upgrade", id=taken))
        assert caught.value.code == "screen_exists"
    assert tree(ws) == before
    # target 자리에 이미 파일이 있으면 (사용자가 둔 것) 덮지 않는다
    (ws / "targets/screens/upgrade").mkdir(parents=True)
    (ws / "targets/screens/upgrade/1.png").write_bytes(b"user")
    checked = check_promote(ws, PromoteRequest(SESSION, "upgrade"))
    assert (checked["ok"], checked["code"]) == (False, "exists")
    assert (ws / "targets/screens/upgrade/1.png").read_bytes() == b"user"


def test_incomplete_refused(ws: Path) -> None:
    before = tree(ws)
    cases: list[tuple[str, Literal["new", "merge"]]] = [
        ("loading", "new"),
        ("bag", "new"),
        ("loading", "merge"),
    ]
    for key, mode in cases:
        with pytest.raises(PromoteError) as caught:
            promote(ws, PromoteRequest(SESSION, key, mode=mode))
        assert caught.value.code == "validation_failed", (key, mode)
    checked = check_promote(ws, PromoteRequest(SESSION, "loading"))
    assert not checked["ok"] and "판정 조건" in checked["problems"][0]
    assert tree(ws) == before


# ---------------------------------------------------------------- 실패 주입 (3.7 표 + R4)

# (단계, n번째, 기대) — 승격 대상 result → upgrade_result: 새 파일 3(카드·target·이미지), 바꿀 파일
# 2(upgrade 후보·lobby), 지울 파일 3(카드·target·이미지)
FAULTS: list[tuple[str, int, str]] = [
    ("journal_write", 1, "original"),  # 저널 쓰기 중
    ("created", 1, "original"),  # 새 파일 k개 게시 뒤
    ("created", 2, "original"),
    ("publish_fsync", 2, "original"),  # 게시 fsync 실패
    ("replaced", 1, "original"),  # 바꿀 파일 교체 뒤·커밋 표시 전
    ("replaced", 2, "original"),
    ("before_commit", 1, "original"),  # 커밋 표시 원자 교체 직전
    ("commit_fsync", 1, "original"),  # 커밋 표시 fsync 실패 (교체 전)
    ("after_commit", 1, "promoted"),  # 커밋 표시 직후
    ("deleted", 1, "promoted"),  # 후보 파일별 삭제 직후 (카드·target·이미지)
    ("deleted", 2, "promoted"),
    ("deleted", 3, "promoted"),
    ("before_explore", 1, "promoted"),  # explore.json 갱신 전·후
    ("after_explore", 1, "promoted"),
    ("before_journal_remove", 1, "promoted"),  # 저널 제거 직전
]
REQUEST = {"session": SESSION, "key": "result", "id": "upgrade_result"}


def _rule(stage: str, nth: int, action: str) -> str:
    return json.dumps(
        [
            {
                "point": "screens.stage",
                "role": "supervisor",
                "when": {"event": stage, "nth": nth},
                "action": action,
            }
        ]
    )


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, bytes]]:
    """기대 상태 두 가지: 원래 그대로 / 승격본 완전 + 후보 없음."""
    base = tmp_path_factory.mktemp("expected")
    original = make_explored_workspace(base / "original")
    done = make_explored_workspace(base / "done")
    promote(done, request(done, "result", id="upgrade_result"))
    return {"original": tree(original), "promoted": tree(done)}


@pytest.mark.parametrize("how", ["raise", "kill"])
@pytest.mark.parametrize(
    ("stage", "nth", "expected"), FAULTS, ids=[f"{s}{n}" for s, n, _ in FAULTS]
)
def test_fault_points(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    outcomes: dict[str, dict[str, bytes]],
    stage: str,
    nth: int,
    expected: str,
    how: str,
) -> None:
    root = make_explored_workspace(tmp_path / "ws")
    req = request(root, "result", id="upgrade_result")
    if how == "kill":
        env = {**os.environ, "KOOKABUG_FAULTS": _rule(stage, nth, "exit:9")}
        args = {**REQUEST, "base_revisions": dict(req.base_revisions)}
        done = subprocess.run(
            [sys.executable, "-X", "utf8", str(CHILD), str(root), json.dumps(args)],
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert done.returncode == 9, done.stdout + done.stderr  # 그 지점에서 죽었다
    else:
        monkeypatch.setenv("KOOKABUG_FAULTS", _rule(stage, nth, "raise"))
        _faults.set_role("supervisor")
        try:
            if expected == "original":
                with pytest.raises((RuntimeError, PromoteError)):
                    promote(root, req)
            else:
                assert promote(root, req)["cleanup_pending"] is True  # 성공 응답 + 마무리 남음
        finally:
            _faults.reset()
            monkeypatch.delenv("KOOKABUG_FAULTS")
    recover_locked(root)  # 다음 잠금 (daemon 시작·CLI·다음 승격)
    assert tree(root) == outcomes[expected]
    assert journals(root) == []
    # 복구는 멱등 (다시 해도 아무것도 바꾸지 않는다)
    assert recover_locked(root) == []
    assert tree(root) == outcomes[expected]


def kill_at(root: Path, stage: str, **kw: Any) -> None:
    """`result` → `upgrade_result` 승격을 자식 프로세스에서 그 단계에 죽인다."""
    req = request(root, "result", id="upgrade_result", **kw)
    env = {**os.environ, "KOOKABUG_FAULTS": _rule(stage, 1, "exit:9")}
    args = {**REQUEST, **kw, "base_revisions": dict(req.base_revisions)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), json.dumps(args)],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9, done.stderr


def test_stuck_journal_blocks_later_promotion(tmp_path: Path) -> None:
    """B4 검수 High 1 (probe `test_stuck_journal_deletes_later_promotion`을 반대로): 롤백이 경고로
    멈춘 저널이 남아 있으면 다시 승격·버리기는 `recovery_pending`이고, 그 뒤 어떤 복구도 확정 화면·
    target 바이트를 바꾸지 않는다. 사람이 남은 파일을 정리하면 복구가 끝나고 풀린다."""
    root = make_explored_workspace(tmp_path / "ws")
    original = tree(root)
    # 1) 커밋 직전에 죽음
    kill_at(root, "before_commit")
    # 2) 사람이 이 거래가 고친 확정 화면(lobby)을 고쳤다
    lobby = root / "screens/lobby.screen.json"
    lobby.write_bytes(lobby.read_bytes() + b"\n")
    edited = lobby.read_bytes()
    # 3) 복구: lobby는 보존·경고, 나머지는 되돌림, 저널은 그 항목만 남는다
    warnings = recover_locked(root)
    assert any("lobby.screen.json" in w for w in warnings)
    (left,) = pending(root)
    assert left["paths"] == ["screens/lobby.screen.json"]
    assert left["phase"] == "prepare" and left["warnings"]
    backup = root / left["backups"]["screens/lobby.screen.json"]
    assert backup.read_bytes() == original["screens/lobby.screen.json"]
    stuck = tree(root)
    assert stuck == {**original, "screens/lobby.screen.json": edited}
    # 4) 같은 후보를 다시 승격·버리기: 저널이 남아 있는 동안 거부, 아무것도 쓰지 않음
    checked = check_promote(root, PromoteRequest(SESSION, "result", id="upgrade_result"))
    assert (checked["ok"], checked["code"]) == (False, "recovery_pending")
    for attempt in (
        lambda: promote(root, PromoteRequest(SESSION, "result", id="upgrade_result")),
        lambda: discard(root, SESSION, "result"),
    ):
        with pytest.raises(PromoteError) as caught:
            attempt()
        assert caught.value.code == "recovery_pending"
        assert caught.value.fields["paths"] == ["screens/lobby.screen.json"]
    # 5) 다음 잠금들: 바이트 그대로 (사용자 편집 포함), 저널은 남음
    for _ in range(3):
        recover_locked(root)
        assert tree(root) == stuck
    assert len(journals(root)) == 1
    # 풀리는 길: lobby를 원래 바이트(백업)로 되돌리면 다음 복구가 저널을 지운다
    lobby.write_bytes(backup.read_bytes())
    assert recover_locked(root) == []
    assert journals(root) == [] and tree(root) == original
    # 이제 다시 승격되고, 그 뒤 어떤 복구도 승격본을 건드리지 않는다
    promote(root, request(root, "result", id="upgrade_result"))
    done = tree(root)
    assert "screens/upgrade_result.screen.json" in done
    assert "targets/screens/upgrade_result/1.png" in done
    for _ in range(2):
        assert recover_locked(root) == []
        assert tree(root) == done


def test_committed_conflict_points_to_explore_json_only(tmp_path: Path) -> None:
    """B4 검수 2라운드 Mid 1: 커밋 뒤 `explore.json` 기록에서 멈춘 저널은 그 파일만 막는다고
    안내한다 (승격본·바뀐 파일·백업은 보이지 않음 — 되돌리면 성공한 승격을 망친다)."""
    root = make_explored_workspace(tmp_path / "ws")
    kill_at(root, "before_explore")  # 커밋·후보 지우기 뒤
    explore_rel = f"{SESSION_REL}/explore.json"
    body = read(root, explore_rel)
    body["promoted"] = {"result": "other_id"}  # 그 사이 다른 ID로 기록됨
    (root / explore_rel).write_text(json.dumps(body), encoding="utf-8")
    warnings = recover_locked(root)
    assert any("promoted" in w or "기록돼" in w for w in warnings)
    (left,) = pending(root)
    assert left["phase"] == "committed"
    assert left["paths"] == [explore_rel]
    assert left["backups"] == {}
    assert "승격은 끝났다" in left["guide"] and "promoted['result']" in left["guide"]
    done = tree(root)
    assert "screens/upgrade_result.screen.json" in done
    with pytest.raises(PromoteError) as caught:
        promote(root, PromoteRequest(SESSION, "upgrade"))
    assert caught.value.code == "recovery_pending"
    assert caught.value.fields["paths"] == [explore_rel]
    assert "백업" not in caught.value.message and "promoted['result']" in caught.value.message
    checked = check_promote(root, PromoteRequest(SESSION, "upgrade"))
    assert (checked["ok"], checked["code"]) == (False, "recovery_pending")
    assert "promoted['result']" in checked["problems"][0]
    # 안내대로 promoted를 고치면 풀리고, 승격본은 그대로
    body["promoted"] = {}
    (root / explore_rel).write_text(json.dumps(body), encoding="utf-8")
    assert recover_locked(root) == []
    assert journals(root) == []
    assert read(root, explore_rel)["promoted"] == {"result": "upgrade_result"}
    assert (root / "screens/upgrade_result.screen.json").read_bytes() == done[
        "screens/upgrade_result.screen.json"
    ]


def test_deleted_replaced_file_keeps_backup(tmp_path: Path) -> None:
    """B4 검수 2라운드 Mid 2: 사람이 바뀐 파일을 지워 저널이 끝나도 원래 바이트는
    `.kookabug/screens-tx-kept/<txid>/`에 남고 경고에 위치가 있다 (자동 삭제 없음)."""
    root = make_explored_workspace(tmp_path / "ws")
    original = (root / "screens/lobby.screen.json").read_bytes()
    kill_at(root, "before_commit")
    lobby = root / "screens/lobby.screen.json"
    lobby.write_bytes(lobby.read_bytes() + b"\n")
    recover_locked(root)
    (left,) = pending(root)
    assert "되돌린다" in left["guide"] and "지우" not in left["guide"]
    lobby.unlink()
    notes = recover_locked(root)
    assert journals(root) == []  # 지워서 끝났다
    kept = root / ".kookabug" / "screens-tx-kept" / left["txid"] / "screens" / "lobby.screen.json"
    assert kept.read_bytes() == original
    assert any(".kookabug/screens-tx-kept/" in n and "lobby.screen.json" in n for n in notes)
    assert recover_locked(root) == [] and kept.read_bytes() == original  # 다음 복구도 그대로


def test_stuck_created_file_resolves_when_removed(tmp_path: Path) -> None:
    """만든 파일을 사람이 고친 경우: 그 파일을 지우거나(옮기거나) 하면 풀린다."""
    root = make_explored_workspace(tmp_path / "ws")
    original = tree(root)
    kill_at(root, "before_commit")
    card = root / "screens/upgrade_result.screen.json"
    card.write_bytes(card.read_bytes() + b" ")
    recover_locked(root)
    (left,) = pending(root)
    assert left["paths"] == ["screens/upgrade_result.screen.json"]
    assert card.is_file()  # 사용자 바이트 보존
    card.unlink()
    assert recover_locked(root) == []
    assert journals(root) == [] and tree(root) == original


def test_rollback_keeps_user_empty_folder(tmp_path: Path) -> None:
    """B4 검수 Low 2: 롤백은 이 거래가 만든 폴더만 지운다 (사람이 미리 만든 빈 폴더는 그대로)."""
    root = make_explored_workspace(tmp_path / "ws")
    (root / "screens" / "menus").mkdir()
    kill_at(root, "before_commit", folder="menus")
    assert (root / "screens/menus/upgrade_result.screen.json").is_file()
    assert recover_locked(root) == []
    assert (root / "screens" / "menus").is_dir()  # 사람 것
    assert not (root / "targets" / "screens").exists()  # 거래가 만든 것
    assert journals(root) == []


def test_recovery_preserves_external_edits(tmp_path: Path) -> None:
    root = make_explored_workspace(tmp_path / "ws")
    original = tree(root)
    req = request(root, "result", id="upgrade_result")
    env = {**os.environ, "KOOKABUG_FAULTS": _rule("before_commit", 1, "exit:9")}
    args = {**REQUEST, "base_revisions": dict(req.base_revisions)}
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), json.dumps(args)],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert done.returncode == 9
    # 롤백 지점에서 죽은 뒤, 사람이 새 파일과 바꾼 파일을 고쳤다
    new_card = root / "screens/upgrade_result.screen.json"
    new_card.write_bytes(new_card.read_bytes() + b"\n")
    lobby = root / "screens/lobby.screen.json"
    lobby.write_bytes(lobby.read_bytes().replace(b"upgrade_result", b"user_edit"))
    edited = {
        p: (root / p).read_bytes()
        for p in ("screens/upgrade_result.screen.json", "screens/lobby.screen.json")
    }
    warnings = recover_locked(root)
    assert any("upgrade_result.screen.json" in w for w in warnings)
    assert any("lobby.screen.json" in w for w in warnings)
    # 사용자 바이트 보존, 이 거래가 쓴 나머지는 되돌림, 저널은 남아 다시 시도할 수 있다
    for rel, data in edited.items():
        assert (root / rel).read_bytes() == data
    assert not (root / "targets/screens/upgrade_result").exists()
    assert (root / SESSION_REL / "upgrade.screen.json").read_bytes() == original[
        f"{SESSION_REL}/upgrade.screen.json"
    ]
    assert len(journals(root)) == 1
    assert recover_locked(root)  # 다시 해도 같은 경고, 바이트 그대로
    for rel, data in edited.items():
        assert (root / rel).read_bytes() == data


def test_cli_and_daemon_serialize(tmp_path: Path) -> None:
    """두 프로세스의 승격이 한 잠금으로 차례대로: 앞 거래가 잠금 안에서 멈춘 동안 뒤 거래는
    기다리고, 풀리면 이어서 한다. 저널은 하나씩."""
    root = make_explored_workspace(tmp_path / "ws")
    gate = tmp_path / "gate"
    req = request(root, "result", id="upgrade_result")
    env = {**os.environ, "KOOKABUG_FAULTS": _rule("after_commit", 1, f"wait:{gate}")}
    args = {**REQUEST, "base_revisions": dict(req.base_revisions)}
    child = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(CHILD), str(root), json.dumps(args)],
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 60
        while not Path(f"{gate}.ready").exists():
            assert time.monotonic() < deadline and child.poll() is None
            time.sleep(0.05)
        assert len(journals(root)) == 1  # 앞 거래가 커밋 뒤 잠금 안에서 멈췄다
        result: dict[str, Any] = {}

        def second() -> None:
            # 앞 거래의 rename(result → upgrade_result)으로 upgrade 후보 revision이 바뀐다:
            # 확인부터 다시 (사람 흐름)
            result.update(promote(root, request(root, "bag", mode="merge")))

        worker = threading.Thread(target=second)
        worker.start()
        time.sleep(0.8)
        assert worker.is_alive()  # 잠금을 기다린다
        Path(f"{gate}.go").touch()
        worker.join(30)
        assert not worker.is_alive()
        assert child.wait(30) == 0
    finally:
        if child.poll() is None:
            child.kill()
    assert result["path"] == "screens/old.screen.json"
    assert (root / "screens/upgrade_result.screen.json").is_file()
    assert journals(root) == []
    assert explore(root)["promoted"] == {"result": "upgrade_result", "bag": "old"}


def test_discard_refuses_links(tmp_path: Path) -> None:
    root = make_explored_workspace(tmp_path / "ws")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.screen.json").write_text("{}", encoding="utf-8")
    _winapi.CreateJunction(str(outside), str(root / SESSION_REL / "linked"))
    before = tree(root)
    with pytest.raises(PromoteError) as caught:
        discard(root, SESSION)
    assert caught.value.code == "path_outside_workspace"
    assert (outside / "keep.screen.json").read_text(encoding="utf-8") == "{}"
    assert {k: v for k, v in tree(root).items() if "/linked/" not in k} == {
        k: v for k, v in before.items() if "/linked/" not in k
    }
    # 후보 하나 버리기: 그 후보 파일만 (targets 폴더가 정션이면 거부)
    os.rmdir(root / SESSION_REL / "linked")
    removed = discard(root, SESSION, "upgrade")
    assert sorted(removed) == sorted(
        [
            f"{SESSION_REL}/upgrade.screen.json",
            f"{SESSION_REL}/upgrade.shot.png",
            f"{SESSION_REL}/targets/upgrade/1.png",
            f"{SESSION_REL}/targets/upgrade/1.target.json",
        ]
    )
    shutil.rmtree(root / SESSION_REL / "targets" / "result")
    _winapi.CreateJunction(str(outside), str(root / SESSION_REL / "targets" / "result"))
    with pytest.raises(PromoteError) as caught:
        discard(root, SESSION, "result")
    assert caught.value.code == "path_outside_workspace"
    assert (outside / "keep.screen.json").exists()
    # 진행 중 세션 전체는 버리지 않는다
    os.rmdir(root / SESSION_REL / "targets" / "result")
    with pytest.raises(PromoteError) as caught:
        discard(root, SESSION, active={SESSION})
    assert caught.value.code == "explore_active"
    assert sorted(discard(root, SESSION))[0].startswith(SESSION_REL)
    assert not (root / SESSION_REL).exists()


def test_promote_then_graph_validation_finds_id(ws: Path) -> None:
    interface = {"exits": {"done": {"kind": "ok", "screen": "upgrade_result"}}}
    sub = GraphBuilder("subgraph", interface=interface).entry("n_exit").exit("n_exit", "done")
    rel = sub.write(Workspace.open(ws), "subgraphs/s.graph.json")
    codes = [d.code for d in check(Workspace.open(ws), rel) if d.code.startswith("screen_")]
    assert codes == ["screen_unknown"]  # 후보(_explored/)는 판정·검증에 쓰지 않는다
    promote(ws, request(ws, "result", id="upgrade_result"))
    assert [d for d in check(Workspace.open(ws), rel) if d.code.startswith("screen_")] == []
