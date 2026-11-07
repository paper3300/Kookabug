"""`kookabug screen test` (구현 계획 M1 2.10·2.11). 예제 게임 화면 PNG로 본다 (`--image`)."""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kb_testing.sample_game import FRAMES_DIR
from kookabug_cli import main as cli
from kookabug_cli import screen_cmd
from kookabug_core.workspace import Workspace
from kookabug_platform.frames import decode_image, encode_png
from kookabug_platform.ocr.engine import Ocr
from kookabug_platform.vision import FrameMeta, Vision

SERVER_ROW = (262, 200, 500, 64)
"""로비 "Server 1" 줄."""
LOADING_BAR = (312, 350, 400, 20)
"""로딩 화면 진행 막대."""
LIST_TARGET = "targets/lobby/server_list.target.json"
LOADING_TARGET = "targets/common/loading.target.json"


def frame(name: str) -> np.ndarray:
    return decode_image((FRAMES_DIR / f"{name}.png").read_bytes())


def crop(name: str, box: tuple[int, int, int, int]) -> np.ndarray:
    x, y, w, h = box
    return np.ascontiguousarray(frame(name)[y : y + h, x : x + w])


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def write_target(ws: Path, rel: str, image: np.ndarray) -> None:
    path = ws / rel
    png = path.name.removesuffix(".target.json") + ".png"
    write_json(path, {"format": "kookabug.target/0", "image": png})
    (path.parent / png).write_bytes(encode_png(image))


def lobby_screen() -> dict[str, Any]:
    return {
        "detect": {"all": [{"$target": LIST_TARGET}], "none": [{"$target": LOADING_TARGET}]},
        "format": "kookabug.screen/0",
        "title": "로비",
    }


def workspace(root: Path) -> Path:
    write_json(root / "kookabug.json", {"format": "kookabug.workspace/0"})
    write_target(root, LIST_TARGET, crop("lobby", SERVER_ROW))
    write_target(root, LOADING_TARGET, crop("loading", LOADING_BAR))
    write_json(root / "screens" / "lobby.screen.json", lobby_screen())
    return root


def run(ws: Path, screen: str, image: Path, *extra: str) -> tuple[int, str, str]:
    argv = ["screen", "test", screen, "--image", str(image), "--workspace", str(ws), *extra]
    args: argparse.Namespace = cli.build_parser().parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    code = screen_cmd.run(args, out, err)
    return code, out.getvalue(), err.getvalue()


def conditions(stdout: str) -> list[tuple[str, str, bool, bool]]:
    report = json.loads(stdout)
    return [(c["kind"], c["target"], c["visible"], c["ok"]) for c in report["conditions"]]


def test_all_and_none_conditions(tmp_path: Path) -> None:
    ws = workspace(tmp_path / "ws")
    code, stdout, _ = run(ws, "lobby", FRAMES_DIR / "lobby.png", "--json")
    assert code == 0
    report = json.loads(stdout)
    assert (report["id"], report["title"], report["matched"]) == ("lobby", "로비", True)
    assert report["path"] == "screens/lobby.screen.json"
    assert conditions(stdout) == [
        ("all", LIST_TARGET, True, True),
        ("none", LOADING_TARGET, False, True),
    ]
    assert report["conditions"][0]["match"]["rect"] == list(SERVER_ROW)
    # 로딩 화면: 목록이 안 보이고(all 틀림) 로딩 막대가 보인다(none 틀림)
    code, stdout, _ = run(ws, "lobby", FRAMES_DIR / "loading.png", "--json")
    assert code == 1
    assert conditions(stdout) == [
        ("all", LIST_TARGET, False, False),
        ("none", LOADING_TARGET, True, False),
    ]
    # 로비 위에 로딩 막대가 겹친 화면: all은 맞지만 none이 틀려 이 화면이 아니다
    mixed = frame("lobby").copy()
    x, y, w, h = 312, 540, 400, 20
    mixed[y : y + h, x : x + w] = crop("loading", LOADING_BAR)
    mixed_png = tmp_path / "mixed.png"
    mixed_png.write_bytes(encode_png(mixed))
    code, stdout, _ = run(ws, "lobby", mixed_png, "--json")
    assert code == 1
    assert conditions(stdout) == [
        ("all", LIST_TARGET, True, True),
        ("none", LOADING_TARGET, True, False),
    ]
    # 사람이 읽는 출력: 조건마다 한 줄
    code, stdout, _ = run(ws, "lobby", FRAMES_DIR / "lobby.png")
    assert code == 0
    lines = stdout.splitlines()
    assert lines[0] == "화면 lobby (로비): 맞음"
    assert len(lines) == 3 and all(line.startswith("  [맞음]") for line in lines[1:])


def test_exit_codes(tmp_path: Path) -> None:
    ws = workspace(tmp_path / "ws")
    lobby = FRAMES_DIR / "lobby.png"
    assert run(ws, "lobby", lobby)[0] == 0
    assert run(ws, "lobby", FRAMES_DIR / "title.png")[0] == 1
    # 파일 경로로도 (워크스페이스는 파일에서 위로 찾는다)
    args = cli.build_parser().parse_args(
        ["screen", "test", str(ws / "screens" / "lobby.screen.json"), "--image", str(lobby)]
    )
    assert screen_cmd.run(args, io.StringIO(), io.StringIO()) == 0
    # 없는 ID, _explored/에만 있는 ID
    code, _, stderr = run(ws, "world", lobby)
    assert code == 6 and "'world'" in stderr
    write_json(ws / "screens" / "_explored" / "world.screen.json", lobby_screen())
    assert run(ws, "world", lobby)[0] == 6
    # 같은 ID 둘
    write_json(ws / "screens" / "more" / "lobby.screen.json", lobby_screen())
    code, stdout, _ = run(ws, "lobby", lobby, "--json")
    assert code == 6 and "screen_ambiguous" in json.loads(stdout)["error"]
    (ws / "screens" / "more" / "lobby.screen.json").unlink()
    # 형식이 틀린 화면 파일, 없는 target
    write_json(ws / "screens" / "bad.screen.json", {"detect": {}, "format": "kookabug.screen/0"})
    assert run(ws, "bad", lobby)[0] == 6
    broken = lobby_screen()
    broken["detect"]["all"] = [{"$target": "targets/none.target.json"}]
    write_json(ws / "screens" / "broken.screen.json", broken)
    code, _, stderr = run(ws, "broken", lobby)
    assert code == 6 and "none.target.json" in stderr
    # 이미지 파일이 없으면 6
    assert run(ws, "lobby", tmp_path / "없음.png")[0] == 6


LOGIN_TITLE = [300 / 1024, 95 / 640, 424 / 1024, 50 / 640]


def login_v1() -> dict[str, Any]:
    return {
        "format": "kookabug.screen/1",
        "title": "로그인",
        "detect": {
            "all": [{"ocr": {"rect": LOGIN_TITLE, "text": "로그인"}}],
            "none": [{"$target": LOADING_TARGET}],
        },
    }


def test_screen_test_ocr_line(
    tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    monkeypatch.delenv("KOOKABUG_AGENT", raising=False)
    ws = workspace(tmp_path / "ws")
    write_json(ws / "screens" / "login.screen.json", login_v1())
    code, stdout, _ = run(ws, "login", FRAMES_DIR / "login.png")
    assert code == 0
    lines = stdout.splitlines()
    assert lines[0] == "화면 login (로그인): 맞음"
    assert lines[1].startswith(
        '  [맞음] all OCR "로그인" [300, 95, 424, 50]: 들어 있어야 함, 들어 있음'
    )
    assert '(읽음 "' in lines[1] and "로그인" in lines[1].split("읽음", 1)[1]
    assert lines[2].startswith("  [맞음] none " + LOADING_TARGET)
    # JSON: OCR 조건은 condition = ocr, 읽은 글자(앞 40자)
    code, stdout, _ = run(ws, "login", FRAMES_DIR / "lobby.png", "--json")
    assert code == 1
    ocr, image = json.loads(stdout)["conditions"]
    assert (ocr["condition"], ocr["visible"], ocr["ok"], ocr["text"]) == (
        "ocr",
        False,
        False,
        "로그인",
    )
    assert ocr["region"] == [300, 95, 424, 50] and len(ocr["read"]) <= 40
    assert (image["condition"], image["target"], image["ok"]) == ("image", LOADING_TARGET, True)
    # 에이전트가 부른 CLI는 OCR 조건을 평가하지 않는다: 일치 여부·종료 코드도 판정 불가(3)
    monkeypatch.setenv("KOOKABUG_AGENT", "agent:1")
    code, stdout, _ = run(ws, "login", FRAMES_DIR / "login.png", "--json")
    report = json.loads(stdout)
    assert (code, report["matched"], report["state"], report["ocr_skipped"]) == (
        3,
        False,
        "unknown",
        "agent",
    )
    ocr, image = report["conditions"]
    assert (ocr["visible"], ocr["ok"], "read" in ocr) == (None, None, False)
    assert image["ok"] is True  # 이미지 조건은 그대로 본다
    code, stdout, _ = run(ws, "login", FRAMES_DIR / "login.png")
    assert code == 3 and "판정 불가" in stdout and "읽음" not in stdout
    assert "들어 있음" not in stdout and "읽지 않음" in stdout
    # 틀린 이미지 조건이 있으면 OCR과 무관하게 아님(1)
    code, _, _ = run(ws, "login", FRAMES_DIR / "loading.png")
    assert code == 1


SENSITIVE_TARGET = "targets/login/protected.target.json"
TITLE_BOX = (300, 95, 424, 50)


def guess_screen(ws: Path, guess: str) -> Path:
    x, y, w, h = TITLE_BOX
    rect = [x / 1024, y / 640, w / 1024, h / 640]
    data = {
        "format": "kookabug.screen/1",
        "detect": {"all": [{"ocr": {"rect": rect, "text": guess}}]},
    }
    return write_json(ws / "screens" / "query.screen.json", data)


def test_agent_cli_never_evaluates_ocr_on_sensitive_frame(
    tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 검수 재현(review_B1_1 High 1)을 반대로 판정한다: 민감 target이 보이는 화면에서 에이전트가 조건
    # 글자를 바꿔 가며 물어도 결과·종료 코드가 같고 OCR이 불리지 않는다
    ws = workspace(tmp_path / "ws")
    path = ws / SENSITIVE_TARGET
    write_json(path, {"format": "kookabug.target/0", "image": "protected.png", "sensitive": True})
    (path.parent / "protected.png").write_bytes(encode_png(crop("login", TITLE_BOX)))
    # 양성 대조군 1: 민감 target이 이 프레임에 실제로 보인다
    target = screen_cmd._loader(Workspace.open(ws))(SENSITIVE_TARGET)  # pyright: ignore[reportPrivateUsage]
    assert target.spec.get("sensitive") is True
    pixels = frame("login")
    assert Vision().find(pixels, FrameMeta.of_image(pixels), target).found
    # 양성 대조군 2: 사람 CLI에서는 추측 글자에 따라 결과가 갈린다 (OCR이 실제로 읽는 화면)
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    monkeypatch.delenv("KOOKABUG_AGENT", raising=False)
    human = [
        run(ws, str(guess_screen(ws, g)), FRAMES_DIR / "login.png")[0] for g in ("로그", "서버")
    ]
    assert human == [0, 1]

    # 에이전트 (같은 프로세스): 엔진 생성·읽기가 불리면 실패
    monkeypatch.setenv("KOOKABUG_AGENT", "agent:1")

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("에이전트 CLI가 OCR을 불렀다")

    monkeypatch.setattr(screen_cmd, "_reader", forbidden)
    monkeypatch.setattr(Ocr, "read", forbidden)
    answers = []
    for guess in ("로그", "서버"):
        code, stdout, _ = run(ws, str(guess_screen(ws, guess)), FRAMES_DIR / "login.png", "--json")
        report = json.loads(stdout)
        (cond,) = report["conditions"]
        answers.append((code, report["matched"], report["state"], cond["visible"], cond["ok"]))
        assert "read" not in cond
    assert answers[0] == answers[1] == (3, False, "unknown", None, None)

    # 에이전트 (실제 CLI 프로세스, 모킹 없음): 모델 폴더가 없어도 종료 3 — OCR 엔진을 만들지 않는다
    env = {**os.environ, "KOOKABUG_AGENT": "agent:1", "KOOKABUG_OCR_MODELS": str(tmp_path / "없음")}
    codes = []
    for guess in ("로그", "서버"):
        query = str(guess_screen(ws, guess))
        image = str(FRAMES_DIR / "login.png")
        argv = ["-X", "utf8", "-m", "kookabug_cli", "screen", "test", query, "--image", image]
        proc = subprocess.run(
            [sys.executable, *argv, "--json"],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        report = json.loads(proc.stdout)
        codes.append((proc.returncode, report["state"], report["conditions"][0]["visible"]))
    assert codes == [(3, "unknown", None), (3, "unknown", None)]


def test_screen_test_no_conditions_exit3(tmp_path: Path) -> None:
    # 판정 조건 없는 후보는 "맞음"이 아니라 판정 불가
    ws = workspace(tmp_path / "ws")
    path = ws / "screens" / "_explored" / "20261107-103000-a1b2" / "empty.screen.json"
    write_json(path, {"format": "kookabug.screen/1", "title": "미완성"})
    code, stdout, _ = run(ws, str(path), FRAMES_DIR / "login.png", "--json")
    report = json.loads(stdout)
    assert (code, report["matched"], report["state"], report["conditions"]) == (
        3,
        False,
        "unknown",
        [],
    )
    code, stdout, _ = run(ws, str(path), FRAMES_DIR / "login.png")
    assert code == 3 and "판정 불가" in stdout and "판정 조건이 없다" in stdout


def test_screen_ocr_model_missing_exit6(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(tmp_path / "없는 모델"))
    ws = workspace(tmp_path / "ws")
    write_json(ws / "screens" / "login.screen.json", login_v1())
    code, stdout, _ = run(ws, "login", FRAMES_DIR / "login.png", "--json")
    report = json.loads(stdout)
    assert code == 6 and report["error_code"] == "ocr_model_missing"
    # OCR 조건이 없는 화면은 모델 없이 그대로
    assert run(ws, "lobby", FRAMES_DIR / "lobby.png")[0] == 0


def list_run(ws: Path, *extra: str) -> tuple[int, str, str]:
    args = cli.build_parser().parse_args(["screen", "list", "--workspace", str(ws), *extra])
    out, err = io.StringIO(), io.StringIO()
    code = screen_cmd.run(args, out, err)
    return code, out.getvalue(), err.getvalue()


def test_screen_list_explored(tmp_path: Path) -> None:
    ws = workspace(tmp_path / "ws")
    session = "20261107-103000-a1b2"
    explored = ws / "screens" / "_explored" / session
    write_json(explored / "login.screen.json", login_v1())
    write_json(explored / "result.screen.json", {"format": "kookabug.screen/1", "title": "결과"})
    write_json(explored / "lobby2.screen.json", {"format": "kookabug.screen/1", "of": "lobby"})
    write_json(explored / "explore.json", {"format": "kookabug.explore/0"})
    write_json(ws / "screens" / "bad.screen.json", {"format": "kookabug.screen/0"})
    loose = ws / "screens" / "_explored" / "loose.screen.json"  # 세션 폴더 없이 둔 파일
    write_json(loose, {"format": "kookabug.screen/1", "title": "옛 자리"})

    code, stdout, _ = list_run(ws, "--json")
    report = json.loads(stdout)
    assert code == 0 and "explored" not in report
    assert [(s["id"], s.get("title"), "problem" in s) for s in report["screens"]] == [
        ("bad", None, True),
        ("lobby", "로비", False),
    ]
    code, stdout, _ = list_run(ws, "--explored", "--json")
    explored_json = json.loads(stdout)["explored"]
    assert [(c["session"], c["key"], c["placement"]) for c in explored_json] == [
        (session, "lobby2", "session"),
        (session, "login", "session"),
        (session, "result", "session"),
        (None, "loose", "misplaced"),
    ]
    assert [c["promotable"] for c in explored_json] == [True, True, False, False]
    assert explored_json[0]["of"] == "lobby" and "incomplete" not in explored_json[0]
    assert explored_json[1]["title"] == "로그인" and "incomplete" not in explored_json[1]
    assert explored_json[2]["incomplete"] is True
    assert "배치가 잘못됐다" in explored_json[3]["problem"]
    assert explored_json[3]["title"] == "옛 자리"  # 호환 읽기
    code, stdout, _ = list_run(ws, "--explored")
    assert code == 0
    assert "화면 2개" in stdout and "탐색 결과 (확인 전) 4개" in stdout
    assert f"{session}/result  결과 (판정 조건 없음)" in stdout
    assert f"{session}/lobby2   (합칠 화면 lobby)" in stdout
    assert "screens/_explored/loose.screen.json  옛 자리 — 탐색 결과 배치가 잘못됐다" in stdout
    # 워크스페이스가 아니면 6
    assert list_run(tmp_path / "없음")[0] == 6


def protect_run(ws: Path) -> tuple[int, dict[str, Any]]:
    args = cli.build_parser().parse_args(
        ["screen", "protect", "--clear-keys", "--workspace", str(ws), "--json"]
    )
    out, err = io.StringIO(), io.StringIO()
    code = screen_cmd.run(args, out, err)
    return code, json.loads(out.getvalue())


def test_screen_protect_clear_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # M7 R1: 저장 글자 검사의 비밀값 키 목록은 사람만, daemon이 꺼져 있을 때 비운다
    from kookabug_daemon.session import DaemonLock

    monkeypatch.delenv("KOOKABUG_AGENT", raising=False)
    ws = workspace(tmp_path / "ws")
    path = ws / ".kookabug" / "agent-protect.json"
    code, report = protect_run(ws)  # 기록 파일 없음
    assert (code, report["cleared"]) == (0, 0)
    body = {
        "format": "kookabug.agent-protect/0",
        "windows": [
            {"window": {"hwnd": 1, "pid": 2, "created": "3"}, "keys": ["acc.pw"], "fields": [None]}
        ],
        "secret_keys": ["acc.id", "acc.pw"],
    }
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    # daemon이 돌고 있으면 바꾸지 않는다
    with DaemonLock.acquire(ws):
        code, report = protect_run(ws)
        assert code == 6 and "daemon" in report["message"]
    # 에이전트가 부른 CLI는 종료 5
    monkeypatch.setenv("KOOKABUG_AGENT", "agent:1")
    assert protect_run(ws)[0] == 5
    monkeypatch.delenv("KOOKABUG_AGENT")
    code, report = protect_run(ws)
    assert (code, report["cleared"]) == (0, 2)
    after = json.loads(path.read_text(encoding="utf-8"))
    assert after["secret_keys"] == [] and after["windows"] == body["windows"]
    # 손상된 기록은 바꾸지 않는다 (사람이 직접 확인)
    path.write_text('{"format": "kookabug.agent-protect/0", "windows": {}}', encoding="utf-8")
    raw = path.read_bytes()
    assert protect_run(ws)[0] == 6 and path.read_bytes() == raw
