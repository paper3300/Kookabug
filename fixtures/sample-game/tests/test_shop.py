"""예제 상점 (M8 계획 3.16·E10): 상태 기계·헤드리스 표·PNG·예제 워크스페이스 상점 파일.

실제 runner로 상점 가짜 게임(장면 표)을 돌리는 검사는 제품 CLI(`kookabug run --platform-fake
fake-platform-shop.json`)를 하위 프로세스로 띄운다 (`test_workspace.py`와 같은 방식).
"""

from __future__ import annotations

import hashlib
import json
import platform
import random
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.sample_game import EXAMPLE_LOCAL, FRAMES_DIR, WORKSPACE_DIR, copy_example_workspace
from kookabug_core.engine.scenario import ScenarioState
from kookabug_core.knowledge import cheats
from kookabug_core.record import read_run
from kookabug_core.validate import check_graph
from kookabug_core.workspace import Workspace
from kookabug_platform.frames import decode_image
from kookabug_platform.vision import FrameMeta, Vision, load_target_file
from kookabug_sdk.types import Target
from sample_shop.flow import BUTTONS, CHEAT_COMMAND, CONSOLE_KEY, Shop, buttons_for
from sample_shop.render import font_sha256, render
from sample_shop.scenario import BOOT, VARIANT_ARGS, generate, representatives

SHOP_FRAMES = FRAMES_DIR / "shop"
SCENARIO = SHOP_FRAMES / "scenario.json"
GAME_DIR = FRAMES_DIR.parent
GEN = GAME_DIR / "tools" / "gen_shop_scenario.py"
BUY = "targets/shop/buy.target.json"
SHOP_GRAPHS = (
    "tests/shop/buy_potion.graph.json",
    "tests/shop/buy_then_close.graph.json",
    "subgraphs/cheats/console.graph.json",
)


def committed() -> dict[str, Any]:
    return json.loads(SCENARIO.read_text(encoding="utf-8"))


def run_json(out: dict[str, Any]) -> dict[str, Any]:
    return json.loads((Path(out["run_dir"]) / "run.json").read_text(encoding="utf-8"))


def center(button: str) -> tuple[int, int]:
    x, y, w, h = BUTTONS[button]
    return x + w // 2, y + h // 2


# ---------------------------------------------------------------- 상태 기계·표


def test_shop_flow_and_variants() -> None:
    shop = Shop()
    assert shop.scene == "shop" and (shop.gold, shop.potions) == (12345, 0)
    bought = shop.press("buy")
    assert (bought.scene, bought.gold, bought.potions) == ("shop_bought", 12245, 1)
    assert bought.press("buy") == bought  # 한 방문에 거래 하나
    sold = shop.press("sell")
    assert (sold.scene, sold.gold, sold.blade) == ("shop_sold", 12395, False)
    rich = shop.key(CONSOLE_KEY).type(CHEAT_COMMAND).key("enter")
    assert (rich.scene, rich.gold) == ("shop_rich", 13345)
    assert shop.key(CONSOLE_KEY).type("give_gold 5").key("enter") == shop
    confirm = shop.press("charge")
    assert confirm.scene == "shop_purchase_confirm"
    assert confirm.press("pay") == shop and confirm.press("cancel") == shop
    assert shop.press("close").scene == "shop_closed"
    moved = Shop(layout="moved")
    assert "buy" not in buttons_for(moved) and moved.press("buy_moved").scene == "shop_moved_bought"
    missing = Shop(layout="missing")
    assert not {"buy", "buy_moved"} & set(buttons_for(missing))
    assert missing.press("sell").scene == "shop_missing_sold"
    assert missing.key(CONSOLE_KEY) == missing  # 콘솔은 기본 갈래만

    # 헤드리스 표(가짜 플랫폼 해석)가 상태 기계와 같은 장면을 따라간다 (갈래마다 무작위 입력)
    spec = committed()
    layouts = {"default": "default", "moved": "moved", "missing": "missing"}
    rng = random.Random(8)
    for variant, layout in layouts.items():
        arg = VARIANT_ARGS[variant]
        for _ in range(40):
            sim = ScenarioState(spec, [arg] if arg else [])
            assert sim.capture() == Shop(layout=layout).scene  # type: ignore[arg-type]
            game = Shop(layout=layout)  # type: ignore[arg-type]
            for _ in range(6):
                choice = rng.random()
                if choice < 0.6:
                    button = rng.choice(sorted(BUTTONS))
                    sim.click(*center(button))
                    game = game.press(button)
                elif choice < 0.8:
                    key = rng.choice([CONSOLE_KEY, "enter", "esc"])
                    sim.key(key)
                    game = game.key(key)
                else:
                    text = rng.choice([CHEAT_COMMAND, "give_gold 9"])
                    sim.text(text)
                    game = game.type(text)
                assert sim.capture() == game.scene, (variant, game)


def test_make_fake_game_shop_variant(tmp_path: Path) -> None:
    """검사 도우미 `make_fake_game(scenario="shop", variant=…)`: 이미 떠 있는 상점이 그 갈래다."""
    from kb_testing.fake_game import make_fake_game
    from kookabug_core.engine.scenario import FakeScenario

    for variant, scene in (("moved", "shop_moved"), ("missing", "shop_missing"), (None, "shop")):
        game = make_fake_game(tmp_path / str(variant), scenario="shop", variant=variant)
        spec = json.loads(game.platform.read_text(encoding="utf-8"))
        assert spec["draw_fields"] == {"console": ["command"]}
        loaded = FakeScenario.load(Path(spec["scenario"]))
        assert loaded.latest().state.capture() == scene
    with pytest.raises(ValueError):
        make_fake_game(tmp_path / "bad", scenario="shop", variant="nope")


def test_shop_scenario_matches_generator() -> None:
    from kookabug_core.canonical import canonical_dumps

    assert SCENARIO.read_text(encoding="utf-8") == canonical_dumps(generate())
    assert set(committed()["scenes"]) == {*representatives(), BOOT}
    for scene in committed()["scenes"]:
        assert (SHOP_FRAMES / f"{scene}.png").is_file(), scene
    snapshot = json.loads((SHOP_FRAMES / "frames.snapshot.json").read_text(encoding="utf-8"))
    for scene, sha in snapshot["frames"].items():
        assert hashlib.sha256((SHOP_FRAMES / f"{scene}.png").read_bytes()).hexdigest() == sha
    # 렌더 소스 sha·PNG·target 최신 여부는 OS와 무관하게 생성기 검사가 본다
    done = subprocess.run(
        [sys.executable, "-X", "utf8", str(GEN), "--check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert done.returncode == 0, done.stderr
    # 찍은 환경(Windows 판·글꼴)이 같으면 지금 렌더와 바이트까지 같다
    if snapshot["windows"] != platform.version() or snapshot["font_sha256"] != font_sha256():
        pytest.skip("PNG를 만든 Windows 판·글꼴과 달라 바이트 대조는 건너뛴다")
    for scene, state in representatives().items():
        assert render(state) == (SHOP_FRAMES / f"{scene}.png").read_bytes(), scene


# 생성기를 복사한 상점에서 Windows 판을 다른 값으로 속여 `--check`를 돈다
_OTHER_WINDOWS = """
import platform, runpy, sys
platform.version = lambda: "0.0.0-other"
sys.argv = [sys.argv[1], "--check"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""


def _check_copy(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-X", "utf8", "-c", _OTHER_WINDOWS, str(root / "tools" / GEN.name)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        cwd=root,
    )


def test_shop_check_detects_changed_renderer_on_other_windows(tmp_path: Path) -> None:
    """검수 재현: 그림을 바꾸는 렌더 수정 뒤 PNG를 다시 만들지 않으면, 다른 Windows 판(픽셀 대조를
    건너뛰는 환경)에서도 `--check`가 실패한다."""
    root = tmp_path / "sample-game"
    for part in ("sample_shop", "tools", "frames"):
        shutil.copytree(GAME_DIR / part, root / part, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(
        GAME_DIR / "workspace" / "targets" / "shop", root / "workspace" / "targets" / "shop"
    )
    clean = _check_copy(root)
    assert clean.returncode == 0, clean.stderr  # 손대지 않은 사본은 통과 (픽셀 대조 없이)
    render_py = root / "sample_shop" / "render.py"
    source = render_py.read_text(encoding="utf-8")
    marker = "    c.fill((0, 0, w, h), BG)\n"
    assert marker in source
    render_py.write_text(
        source.replace(marker, marker + "    c.fill((0, 0, 4, 4), 0xFFFFFF)\n", 1),
        encoding="utf-8",
        newline="\n",
    )
    changed = _check_copy(root)
    assert changed.returncode == 1 and "sample_shop/render.py" in changed.stderr
    # PNG가 target과 어긋나도 잡는다
    render_py.write_text(source, encoding="utf-8", newline="\n")
    (root / "workspace" / "targets" / "shop" / "buy.png").write_bytes(
        (root / "workspace" / "targets" / "shop" / "potion_bought.png").read_bytes()
    )
    broken = _check_copy(root)
    assert broken.returncode == 1 and "buy.png" in broken.stderr


# ---------------------------------------------------------------- target·음성 대조


def test_shop_targets_cut_from_frames() -> None:
    """상점 target PNG는 상점 장면 PNG를 생성기 표(`TARGET_CROPS`)대로 자른 것이다."""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[1] / "tools" / "gen_shop_scenario.py"
    spec = importlib.util.spec_from_file_location("gen_shop_scenario", path)
    assert spec is not None and spec.loader is not None
    gen = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gen
    try:
        spec.loader.exec_module(gen)
    finally:
        del sys.modules[spec.name]
    for rel, (scene, rect) in gen.TARGET_CROPS.items():
        expected = gen.crop_png((SHOP_FRAMES / f"{scene}.png").read_bytes(), rect)
        assert (
            decode_image((WORKSPACE_DIR / rel).read_bytes()).tolist()
            == decode_image(expected).tolist()
        ), rel
    for target in sorted((WORKSPACE_DIR / "targets" / "shop").glob("*.target.json")):
        body = json.loads(target.read_text(encoding="utf-8"))
        assert body["recorded"] == {"client_size": [1024, 640], "dpi": 96}
        assert f"targets/shop/{body['image']}" in gen.TARGET_CROPS


def _find(target: str, png: str, *, region: bool = True) -> bool:
    loaded = load_target_file(WORKSPACE_DIR / target)
    spec = dict(loaded.spec)
    if not region:
        spec.pop("search", None)
    pixels = decode_image((SHOP_FRAMES / png).read_bytes())
    found = Vision().find(
        pixels, FrameMeta.of_image(pixels), Target(name=target, path=loaded.path, spec=spec)
    )
    return found.match is not None


def test_sell_not_matching_buy_target() -> None:
    assert _find(BUY, "shop.png")
    # 옮긴 화면: 원래 자리 둘레(region) 밖이라 못 찾고, 창 전체로 넓히면 찾는다 (같은 그림)
    assert not _find(BUY, "shop_moved.png")
    assert _find(BUY, "shop_moved.png", region=False)
    # 판매 단추(같은 모양·다른 글자·옅게 다른 색)는 기본 임계값에서 구매 target에 맞지 않는다
    for png in ("shop_missing.png", "shop_missing_sold.png"):
        assert not _find(BUY, png), png
        assert not _find(BUY, png, region=False), png


def test_shop_workspace_files_validate(tmp_path: Path) -> None:
    ws = Workspace.open(copy_example_workspace(tmp_path))
    for graph in SHOP_GRAPHS:
        _, diagnostics = check_graph(ws, graph)
        assert [d for d in diagnostics if d.severity == "error"] == [], graph
    listed = cheats.list_cheats(ws.root)
    give = next(c for c in listed["cheats"] if c["id"] == "give_gold")
    # 예제는 채택하지 않은 채로 둔다: 채택 digest가 노드 구현 revision을 담아 판마다 달라진다
    assert (give["adopted"], give["problem"]) == (False, None)
    assert listed["enabled"] and [c["id"] for c in listed["categories"]] == ["dev_safe"]


# ---------------------------------------------------------------- 실제 runner


def run_shop(
    tmp_path: Path,
    ocr_models: Path,
    graph: str,
    *args: str,
    ws: Path | None = None,
    agent: bool = False,
) -> tuple[int, dict[str, Any]]:
    ws = ws or copy_example_workspace(tmp_path)
    extra = {"KOOKABUG_AGENT": "agent-cli"} if agent else {}
    env = cli_env(tmp_path, None, KOOKABUG_OCR_MODELS=str(ocr_models), **extra)
    done = run_cli(
        ["run", graph, "--platform-fake", "fake-platform-shop.json", "--json", *args],
        cwd=ws,
        env=env,
        timeout=180,
    )
    assert done.stdout.strip(), done.stderr
    return done.returncode, json.loads(done.stdout)


@pytest.mark.process
def test_shop_buy_passes_on_fake_game(tmp_path: Path, ocr_models: Path) -> None:
    code, out = run_shop(tmp_path, ocr_models, "tests/shop/buy_potion.graph.json")
    assert (code, out["verdict"]) == (0, "pass"), out
    qa = run_json(out)["qa"]
    assert qa["claims"] == [
        {
            "assertions": ["n_assert_gold", "n_assert_item"],
            "executed": ["n_assert_gold", "n_assert_item"],
            "id": "shop.potion.price",
            "passed": ["n_assert_gold", "n_assert_item"],
            "rev": 1,
        }
    ]
    # 구매 단추가 옮겨지면 원래 자리 둘레에서 못 찾아 실패한다 (B6 정상 수리 시나리오의 출발점)
    code, out = run_shop(
        tmp_path / "moved",
        ocr_models,
        "tests/shop/buy_potion.graph.json",
        "--profile",
        "shop_moved",
    )
    assert (out["verdict"], out["code"]) == ("fail", "unhandled_fail"), out
    qa = run_json(out)["qa"]
    assert qa["claims"][0]["executed"] == [] and qa["claims"][0]["passed"] == []


CHEAT_TEST = "tests/shop/cheat_gold.graph.json"


def cheat_graph(amount: int = 1000, *, max_calls: int = 1) -> dict[str, Any]:
    return {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_entry": {"next": {"start": "n_launch"}, "type": "core.graph.entry", "version": 1},
            "n_launch": {
                "in": {
                    "args": {"$setting": "shop.args"},
                    "cwd": {"$setting": "game.cwd"},
                    "path": {"$setting": "game.executable"},
                    "window_title": {"$setting": "shop.title"},
                },
                "next": {"attached": "n_wait"},
                "type": "core.app.launch",
                "version": 1,
            },
            # 상점 화면을 한 번 본 뒤 입력한다 (입장 화면에서 누른 키는 상점에 가지 않는다)
            "n_wait": {
                "in": {"target": {"$target": "targets/shop/buy.target.json"}},
                "next": {"found": "n_cheat"},
                "type": "core.image.wait",
                "version": 1,
            },
            "n_cheat": {
                "config": {"args": {"amount": amount}, "cheat": "give_gold"},
                "next": {"done": "n_gold"},
                "type": "core.qa.cheat",
                "version": 1,
            },
            "n_gold": {
                "in": {"equals": "13,345", "region": [140, 96, 220, 76], "timeout_ms": 5000},
                "type": "core.assert.text",
                "version": 1,
            },
        },
        "plugins": {"core": "0.1.0"},
        "qa": {
            "cheats": {
                "allow": [
                    {"args": {"amount": {"max": 1000}}, "id": "give_gold", "max_calls": max_calls}
                ]
            },
            "format": "kookabug.qa/0",
        },
    }


@pytest.mark.process
def test_adopted_cheat_runs_on_fake_shop(tmp_path: Path, ocr_models: Path) -> None:
    """사람이 채택한 치트가 실제 runner 스냅샷에서 digest를 다시 계산해 통과하고 콘솔 명령을
    보낸다."""
    ws = copy_example_workspace(tmp_path)
    (ws / CHEAT_TEST).write_text(json.dumps(cheat_graph()), encoding="utf-8")
    cheats.adopt(ws, "give_gold", 1, "dev_safe", by="test")
    code, out = run_shop(tmp_path, ocr_models, CHEAT_TEST, ws=ws)
    assert (code, out["verdict"]) == (0, "pass"), out
    run = read_run(out["run_dir"])
    calls = [e for e in run.events if e["event"] == "cheat.call"]
    assert len(calls) == 1 and calls[0]["cheat"] == "give_gold" and calls[0]["before_assertions"]
    assert run_json(out)["qa"]["cheats_used"][0]["calls"] == 1
    # 구현 서브그래프가 받은 명령 = 고정 템플릿 + 검사한 인자 (골드 13,345 검증이 게임 도착을 본다)
    commands = [
        e["outputs"]["command"]
        for e in run.events
        if e["event"] == "step.end" and "command" in e.get("outputs", {})
    ]
    assert commands == ["give_gold 1000"]
    # 구현 파일(콘솔 서브그래프) 한 바이트가 바뀌면 그 뒤 실행은 거부된다 (R2)
    sub = ws / "subgraphs" / "cheats" / "console.graph.json"
    sub.write_bytes(sub.read_bytes() + b"\n")
    code, out = run_shop(tmp_path / "after", ocr_models, CHEAT_TEST, ws=ws)
    assert (out["verdict"], out["code"]) == ("error", "cheat_not_adopted"), out


@pytest.mark.process
def test_cli_agent_run_is_unattended_for_cheats(tmp_path: Path, ocr_models: Path) -> None:
    """`KOOKABUG_AGENT` CLI 실행은 사람 없는 실행이다: 무인 허용이 아닌 분류의 채택 치트는 거부."""
    ws = copy_example_workspace(tmp_path)
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text(encoding="utf-8"))
    body["permissions"] = {"preset": "runner"}  # 에이전트가 실행할 수 있게 (판정 allow)
    local.write_text(json.dumps(body), encoding="utf-8")
    (ws / CHEAT_TEST).write_text(json.dumps(cheat_graph()), encoding="utf-8")
    config = ws / "kookabug.json"
    cheats.set_policy(
        ws,
        enabled=True,
        categories=[{"id": "dev_safe", "title": "사람 있을 때만", "unattended": False}],
        base_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
    )
    cheats.adopt(ws, "give_gold", 1, "dev_safe", by="test")
    code, out = run_shop(tmp_path, ocr_models, CHEAT_TEST, ws=ws, agent=True)
    assert (out["verdict"], out["code"]) == ("error", "cheat_denied"), out
    assert "무인" in out["reason"]
    # 같은 실행을 사람이 하면 통과한다
    code, out = run_shop(tmp_path / "human", ocr_models, CHEAT_TEST, ws=ws)
    assert (code, out["verdict"]) == (0, "pass"), out


def test_example_local_has_shop_paths() -> None:
    assert set(EXAMPLE_LOCAL) == {"game.cwd", "game.executable"}
