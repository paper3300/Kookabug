"""`kookabug screen test` (구현 계획 M1 2.10·2.11). 예제 게임 화면 PNG로 본다 (`--image`)."""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
from typing import Any

import numpy as np

from kb_testing.sample_game import FRAMES_DIR
from kookabug_cli import main as cli
from kookabug_cli import screen_cmd
from kookabug_platform.frames import decode_image, encode_png

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
