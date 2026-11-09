"""금지 동작 강제 (M8 계획 3.7·9장 R6) — 엄격: 입력 안전·비밀값.

실제 daemon·runner·예제 상점 가짜 게임(`make_fake_game(scenario="shop")`, 상태 파일을 runner와
daemon 가짜 캡처가 같이 씀). 상점의 "다이아 충전"을 누르면 "결제" 확인 팝업이 뜬다 — 예제
워크스페이스 `automation.forbidden`이 `{"kind": "text", "value": "결제"}`다.

- Agent 연결의 제어 입력(클릭·키·문자)과 Agent가 시작한 실행의 입력 노드는 금지 문구·target·화면이
  보이면 `forbidden_visible`, 확인 못 하면 `forbidden_unverifiable` — 입력은 게임에 가지 않는다
- 사람 입력·사람이 시작한 실행은 판정하지 않는다
- 거부 응답·로그·실행 기록에 화면 글자(OCR 원문)가 남지 않는다
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from helpers.cli import cli_env, run_cli

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kb_testing.proc import count_inputs
from kookabug_core import forbidden as rules
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.forbidden import window_sight
from kookabug_daemon.frame_guard import Guard
from kookabug_daemon.screen_source import Grab, WindowBinding

pytestmark = [pytest.mark.process, pytest.mark.timeout(900)]

SHOP = "SampleRPG 상점"
CHARGE = (902, 52)
"""상점의 "다이아 충전" 단추 (→ "결제" 확인 팝업)."""
PAY = (422, 398)
CANCEL = (602, 398)
PAY_RECT = (352, 372, 140, 52)
CONFIRM_WORDS = ("정말", "1,100")
"""확인 팝업에 보이는 다른 글자 (거부 기록에 남으면 안 되는 OCR 원문 — 양성 대조로 OCR이 읽음을
본다)."""
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}


@pytest.fixture
def game(tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    return make_fake_game(tmp_path, scenario="shop")


@pytest.fixture
def daemon(game: FakeGame, tmp_path: Path, ocr_models: Path) -> Iterator[ThreadDaemon]:
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    env["KOOKABUG_OCR_MODELS"] = str(ocr_models)
    with game.daemon(env) as d:
        yield d


def set_forbidden(game: FakeGame, items: list[dict[str, str]]) -> None:
    path = game.root / "kookabug.json"
    config = json.loads(path.read_text("utf-8"))
    config["automation"]["forbidden"] = items
    path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


def click(conn: DaemonClient, point: tuple[int, int]) -> dict[str, Any]:
    return conn.call("control.click", {"window": SHOP, "point": list(point)}, timeout=180)


def refused(fn: Any, *args: Any) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        fn(*args)
    return caught.value


def control(conn: DaemonClient, method: str, params: dict[str, Any]) -> Any:
    return conn.call(method, params, timeout=180)


def scene(game: FakeGame) -> str:
    return str(game.state().get("scene") or game.state()["games"][0]["scene"])


def clicks_at(game: FakeGame, point: tuple[int, int]) -> int:
    """게임에 실제로 간 그 위치 마우스 누르기 수 (실제 기록 형식 — `count_inputs`)."""
    return count_inputs(game.inputs(), "click", at=point)


def keys_sent(game: FakeGame, key: str | None = None) -> int:
    return count_inputs(game.inputs(), "key", key=key)


def texts_sent(game: FakeGame) -> int:
    return count_inputs(game.inputs(), "text")


def write_pay_target(game: FakeGame) -> str:
    """확인 팝업의 "결제" 단추 target (금지 target·금지 화면 판정용)."""
    import cv2

    from kookabug_platform.frames import decode_image

    pixels = decode_image((game.frames / "shop_purchase_confirm.png").read_bytes())
    x, y, w, h = PAY_RECT
    ok, png = cv2.imencode(".png", pixels[y : y + h, x : x + w])
    assert ok
    folder = game.root / "targets" / "shop"
    (folder / "pay.png").write_bytes(png.tobytes())
    (folder / "pay.target.json").write_text(
        json.dumps(
            {
                "format": "kookabug.target/0",
                "image": "pay.png",
                "recorded": {"client_size": [1024, 640], "dpi": 96},
            }
        ),
        encoding="utf-8",
    )
    return "targets/shop/pay.target.json"


def prepare_capture(game: FakeGame) -> None:
    import shutil

    (game.root / "captures").mkdir(exist_ok=True)
    shutil.copyfile(game.frames / "shop.png", game.root / "captures" / "s.png")


def save_target(conn: DaemonClient, path: str, *, new: bool = False) -> dict[str, Any]:
    """정지 화면(`captures/s.png`)에서 잘라 target을 저장한다 (`prepare_capture` 뒤). `new`면 없는
    파일을 새로 만든다(`base_revision: null`)."""
    frame = conn.call("target.load_image", {"path": "captures/s.png"})
    revision = None if new else conn.call("target.open", {"path": path})["revision"]
    return conn.call(
        "target.save",
        {
            "path": path,
            "base_revision": revision,
            "spec": {"click": {"anchor": "center", "offset": [0, 0]}},
            "crop": {"frame_id": frame["frame_id"], "rect": [40, 560, 140, 52]},
        },
    )


def make_junction(link: Path, target: Path) -> None:
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def file_bytes(game: FakeGame, *rels: str) -> list[bytes]:
    return [(game.root / rel).read_bytes() for rel in rels]


def run_graph(game: FakeGame, name: str, nodes: dict[str, Any]) -> str:
    rel = f"tests/shop/{name}.graph.json"
    graph = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_attach"}},
            "n_attach": {
                "type": "core.window.attach",
                "version": 1,
                "in": {"title": f"/^{SHOP}$/"},
                "next": {"found": "n_cap"},
            },
            # 가짜 게임은 캡처가 화면을 넘긴다 (띄운 직후 boot → shop) — 실제 창처럼 먼저 본다
            "n_cap": {"type": "core.screen.capture", "version": 1, "next": {"done": "n_1"}},
            **nodes,
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
    }
    (game.root / rel).write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    return rel


def tap(point: tuple[int, int], then: str) -> dict[str, Any]:
    return {
        "type": "core.input.click",
        "version": 1,
        "in": {"point": list(point)},
        "next": {"done": then},
    }


def wait_ended(conn: DaemonClient, run_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 180
    while True:
        status = conn.call("run.status", {"run_id": run_id})
        if status["state"] == "ended":
            return status
        assert time.monotonic() < deadline, status
        time.sleep(0.3)


def run_json(game: FakeGame, run_id: str) -> dict[str, Any]:
    folder = next((game.root / "runs").glob(f"*_{run_id}"))
    return json.loads((folder / "run.json").read_text("utf-8"))


# ---------------------------------------------------------------- 제어 입력 (control.*)


def test_text_click_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client(AGENT) as agent:
        assert click(agent, CHARGE)["verdict"] == "pass"  # 상점에는 금지 문구가 없다
        assert clicks_at(game, CHARGE) == 1  # 양성 대조: 집계가 실제 기록 형식을 센다
        assert scene(game) == "shop_purchase_confirm"
        before = len(game.inputs())
        error = refused(click, agent, PAY)
        assert error.kind == "forbidden_visible"
        assert (error.data["kind"], error.data["value"]) == ("text", "결제")
        assert len(game.inputs()) == before and scene(game) == "shop_purchase_confirm"
        assert clicks_at(game, PAY) == 0


def test_human_click_not_checked(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        assert click(ui, CHARGE)["verdict"] == "pass"
        assert scene(game) == "shop_purchase_confirm"
        # 사람은 금지 문구가 보여도 누른다 (판정 대상 아님) — 결제 누르기가 실제로 게임에 간다
        assert click(ui, PAY)["verdict"] == "pass"
        assert scene(game) == "shop"
        assert clicks_at(game, PAY) == 1


def test_key_combo_refused_when_forbidden_visible(game: FakeGame, daemon: ThreadDaemon) -> None:
    with daemon.client() as ui:
        click(ui, CHARGE)
    with daemon.client(AGENT) as agent:
        for method, params in (
            ("control.key", {"window": SHOP, "keys": "ctrl+a"}),
            ("control.key", {"window": SHOP, "keys": "esc"}),
            ("control.type", {"window": SHOP, "text": "abc"}),
            # 취소 단추도: 금지 문구가 보이는 동안 Agent 입력은 모두 거부 (사람이 닫는다)
            ("control.click", {"window": SHOP, "point": list(CANCEL)}),
        ):
            error = refused(control, agent, method, params)
            assert error.kind == "forbidden_visible", method
        assert scene(game) == "shop_purchase_confirm"
        assert (keys_sent(game), texts_sent(game), clicks_at(game, CANCEL)) == (0, 0, 0)
    # 양성 대조: 같은 화면에서 사람의 키·글자 입력은 실제로 게임에 가고 집계가 오른다
    with daemon.client() as ui:
        control(ui, "control.type", {"window": SHOP, "text": "abc"})
        control(ui, "control.key", {"window": SHOP, "keys": "ctrl+a"})
        assert texts_sent(game) >= 1 and keys_sent(game, "a") >= 1 and keys_sent(game, "ctrl") >= 1


def test_target_click_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    target = write_pay_target(game)
    set_forbidden(game, [{"kind": "target", "path": target}])
    with daemon.client(AGENT) as agent:
        assert click(agent, CHARGE)["verdict"] == "pass"  # 상점에는 그 target이 없다
        error = refused(click, agent, PAY)
        assert (error.kind, error.data["kind"], error.data["value"]) == (
            "forbidden_visible",
            "target",
            target,
        )


def test_screen_refuses_all_input(game: FakeGame, daemon: ThreadDaemon) -> None:
    target = write_pay_target(game)
    (game.root / "screens" / "payment.screen.json").write_text(
        json.dumps(
            {
                "format": "kookabug.screen/0",
                "title": "결제 확인",
                "detect": {"all": [{"$target": target}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    set_forbidden(game, [{"kind": "screen", "id": "payment"}])
    with daemon.client(AGENT) as agent:
        assert click(agent, CHARGE)["verdict"] == "pass"
        for method, params in (
            ("control.click", {"window": SHOP, "point": list(CANCEL)}),
            ("control.key", {"window": SHOP, "keys": "esc"}),
            ("control.type", {"window": SHOP, "text": "x"}),
        ):
            error = refused(control, agent, method, params)
            assert (error.kind, error.data["kind"]) == ("forbidden_visible", "screen"), method


def test_screen_identify_failure_refuses(game: FakeGame, daemon: ThreadDaemon) -> None:
    set_forbidden(game, [{"kind": "screen", "id": "no_such_screen"}])
    with daemon.client(AGENT) as agent:
        error = refused(click, agent, CHARGE)
        assert (error.kind, error.data["reason"]) == ("forbidden_unverifiable", "screen_unknown")
        assert scene(game) == "shop"


def test_ocr_unavailable_refuses(game: FakeGame, daemon: ThreadDaemon) -> None:
    def boom() -> Any:
        raise OSError("모델 없음")

    daemon.daemon.targets.ocr = boom  # type: ignore[method-assign]
    with daemon.client(AGENT) as agent:
        error = refused(click, agent, CHARGE)
        assert error.kind == "forbidden_unverifiable"
        assert str(error.data["reason"]).startswith("ocr_failed")
        assert scene(game) == "shop"


def test_protected_frame_refuses(game: FakeGame) -> None:
    """보호 판정이 clear가 아니면 글자를 읽지 않고 거부한다. 비밀값 칸 상자를 모두 알면 그 칸만 가린
    사본으로 읽는다(로그인 단추 같은 흐름이 막히지 않게)."""
    from kookabug_platform.frames import decode_image

    pixels = decode_image((game.frames / "shop_purchase_confirm.png").read_bytes())
    binding = WindowBinding(1, 2, "3")

    class Source:
        def capture(self, hwnd: int) -> Grab:
            return Grab(pixels, (1024, 640), 96, binding)

    class Daemon:
        root = game.root
        screen_source = Source()

        def __init__(self, verdict: Guard, boxes: list[Any] | None) -> None:
            self.guard = self
            self.verdict = verdict
            self.boxes = boxes
            self.read: list[Any] = []
            self.targets = self

        def check(self, frame: Any) -> Guard:
            return self.verdict

        def secret_boxes(self, frame: Any) -> list[Any] | None:
            return self.boxes

        def ocr(self) -> Any:
            daemon = self

            class Engine:
                name = "stub"

                def read(self, image: Any, **_: Any) -> list[Any]:
                    daemon.read.append(image)
                    return []

            return Engine()

    items = (rules.Item("text", "결제"),)
    unknown = Daemon(Guard("protected", "secret_field_unknown"), None)
    refusal = rules.judge(items, window_sight(unknown, [binding]))
    assert refusal is not None
    assert (refusal.code, refusal.reason) == ("forbidden_unverifiable", "secret_field_unknown")
    assert unknown.read == []  # 보호 화면은 OCR에 넘기지 않는다
    sensitive = Daemon(Guard("protected", "sensitive_visible"), [(0, 0, 10, 10)])
    refusal = rules.judge(items, window_sight(sensitive, [binding]))
    assert refusal is not None and refusal.reason == "sensitive_visible"
    known = Daemon(Guard("protected", "secret_field"), [(352, 372, 140, 52)])
    assert rules.judge(items, window_sight(known, [binding])) is None  # 스텁 OCR: 빈 글자
    [seen] = known.read
    assert np.all(seen[372:424, 352:492] == 128)  # 칸 상자는 가린 사본만 읽었다
    assert not np.array_equal(seen, pixels)


def test_forbidden_files_not_writable_by_agent(game: FakeGame, daemon: ThreadDaemon) -> None:
    """옆 경로: Agent가 금지 target 파일(·그 PNG·금지 화면의 판정 target)을 고쳐 판정을 비우지
    못한다. 사람은 고친다."""
    target = write_pay_target(game)
    set_forbidden(game, [{"kind": "target", "path": target}])
    prepare_capture(game)
    before = (game.root / target).read_bytes()

    save = save_target
    with daemon.client(AGENT) as agent:
        for path in (target, "targets/shop/./pay.target.json", "Targets/Shop/PAY.target.json"):
            # `./` 꼴은 경로 검사가 먼저 거부한다 — 어느 쪽이든 쓰지 않는다
            kind = refused(save, agent, path).kind
            assert kind in ("policy_path", "path_outside_workspace"), (path, kind)
        assert (game.root / target).read_bytes() == before
        # 다른 target은 그대로 쓴다 (회귀 없음)
        assert save(agent, "targets/shop/buy.target.json")["revision"]
        # 금지 목록을 읽을 수 없으면 Agent의 target 쓰기를 하지 않는다 (fail closed)
        config = json.loads((game.root / "kookabug.json").read_text("utf-8"))
        config["automation"]["forbidden"] = [{"kind": "text"}]
        (game.root / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
        assert refused(save, agent, "targets/shop/buy.target.json").kind == "policy_path"
        error = refused(click, agent, CHARGE)  # 입력도 확인 못 함으로 거부
        assert (error.kind, error.data["reason"]) == (
            "forbidden_unverifiable",
            "config_unreadable",
        )
    set_forbidden(game, [{"kind": "target", "path": target}])
    with daemon.client() as ui:
        assert save(ui, target)["revision"]  # 사람은 고친다
    assert (game.root / target).read_bytes() != before


# ---------------------------------------------------------------- Agent가 시작한 실행


def test_agent_run_click_node_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    rel = run_graph(game, "pay_flow", {"n_1": tap(CHARGE, "n_2"), "n_2": tap(PAY, "n_pass")})
    with daemon.client(AGENT) as agent:
        started = agent.call("run.start", {"path": rel, "idempotency_key": "k1"})
        status = wait_ended(agent, started["run_id"])
        assert status["outcome"]["verdict"] == "error", status
        info = run_json(game, started["run_id"])
        assert info["code"] == "forbidden_visible", info
        assert clicks_at(game, CHARGE) == 1  # 양성 대조: 앞 노드의 누르기는 셌다
        assert clicks_at(game, PAY) == 0 and scene(game) == "shop_purchase_confirm"
    # 사람이 시작한 실행은 판정하지 않는다 — 결제 누르기가 실제로 게임에 간다(집계가 오름)
    with daemon.client() as ui:
        click(ui, CANCEL)
        started = ui.call("run.start", {"path": rel})
        assert wait_ended(ui, started["run_id"])["outcome"]["verdict"] == "pass"
        assert scene(game) == "shop"
        assert clicks_at(game, PAY) == 1


def test_graph_key_node_refused_when_forbidden_visible(
    game: FakeGame, daemon: ThreadDaemon
) -> None:
    key = {
        "type": "core.input.key",
        "version": 1,
        "in": {"keys": "esc"},
        "next": {"done": "n_pass"},
    }
    rel = run_graph(game, "esc", {"n_1": key})
    with daemon.client() as ui:
        click(ui, CHARGE)
    with daemon.client(AGENT) as agent:
        started = agent.call("run.start", {"path": rel, "idempotency_key": "k2"})
        wait_ended(agent, started["run_id"])
        assert run_json(game, started["run_id"])["code"] == "forbidden_visible"
        assert scene(game) == "shop_purchase_confirm"
        assert keys_sent(game, "esc") == 0
    # 양성 대조: 사람이 시작한 같은 실행의 esc는 게임에 간다
    with daemon.client() as ui:
        started = ui.call("run.start", {"path": rel})
        assert wait_ended(ui, started["run_id"])["outcome"]["verdict"] == "pass"
        assert keys_sent(game, "esc") == 1


def test_no_ocr_text_in_logs(
    game: FakeGame, daemon: ThreadDaemon, caplog: pytest.LogCaptureFixture, ocr_models: Path
) -> None:
    from kookabug_platform.frames import decode_image
    from kookabug_platform.ocr.engine import Ocr, create_engine

    # 양성 대조: 팝업의 다른 글자는 OCR로 실제로 읽힌다
    pixels = decode_image((game.frames / "shop_purchase_confirm.png").read_bytes())
    text = rules.normalize(Ocr(create_engine("rapidocr", {})).read(pixels).text)
    assert all(rules.normalize(w) in text for w in CONFIRM_WORDS), text
    caplog.set_level(logging.DEBUG)
    rel = run_graph(game, "pay_flow2", {"n_1": tap(PAY, "n_pass")})
    seen: list[str] = []
    with daemon.client(AGENT) as agent:
        click(agent, CHARGE)
        error = refused(click, agent, PAY)
        seen.append(json.dumps({"m": error.message, "d": error.data}, ensure_ascii=False))
        started = agent.call("run.start", {"path": rel, "idempotency_key": "k3"})
        status = wait_ended(agent, started["run_id"])
        seen.append(json.dumps(status, ensure_ascii=False))
        events = agent.call("run.events", {"run_id": started["run_id"]})
        seen.append(json.dumps(events, ensure_ascii=False))
    seen.append(caplog.text)
    for path in (game.root / "runs").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".log", ".txt"):
            seen.append(path.read_text("utf-8", errors="replace"))
    for path in (game.root / ".kookabug").rglob("*"):
        if path.is_file() and path.suffix in (".json", ".jsonl", ".log", ".txt"):
            seen.append(path.read_text("utf-8", errors="replace"))
    blob = rules.normalize("\n".join(seen))
    assert "결제" in blob  # 걸린 항목(정책 값)은 남는다
    for word in CONFIRM_WORDS:
        assert rules.normalize(word) not in blob, word


# ---------------------------------------------------------------- 정션 별칭 (같은 비교는 한 함수로)

PAY_FILES = ("targets/shop/pay.target.json", "targets/shop/pay.png")


def test_forbidden_junction_alias_forbidden_alias(
    game: FakeGame, daemon: ThreadDaemon, tmp_path: Path
) -> None:
    """금지 목록은 정션 별칭 경로, Agent 쓰기는 실제 경로 — 같은 실제 경로 키라 쓰지 않는다. 판정은
    별칭으로 실제 파일을 읽어 그대로 막는다."""
    write_pay_target(game)
    make_junction(game.root / "targets" / "alias", game.root / "targets" / "shop")
    alias = "targets/alias/pay.target.json"
    assert rules.real_key(game.root, alias) == rules.real_key(game.root, PAY_FILES[0])
    set_forbidden(game, [{"kind": "target", "path": alias}])
    prepare_capture(game)
    before = file_bytes(game, *PAY_FILES)
    with daemon.client(AGENT) as agent:
        for path in (PAY_FILES[0], "Targets/SHOP/pay.target.json"):
            assert refused(save_target, agent, path).kind == "policy_path", path
        assert file_bytes(game, *PAY_FILES) == before
        assert save_target(agent, "targets/shop/buy.target.json")["revision"]  # 다른 target은 쓴다
        assert click(agent, CHARGE)["verdict"] == "pass"
        error = refused(click, agent, PAY)
        assert (error.kind, error.data["kind"], error.data["value"]) == (
            "forbidden_visible",
            "target",
            alias,
        )
        assert clicks_at(game, PAY) == 0
    # 보호 경로가 워크스페이스 밖으로 나가면 Agent의 target·그래프 쓰기를 모두 거부 (fail closed)
    outside = tmp_path / "outside"
    outside.mkdir()
    make_junction(game.root / "targets" / "out", outside)
    set_forbidden(game, [{"kind": "target", "path": "targets/out/pay.target.json"}])
    with daemon.client(AGENT) as agent:
        assert refused(save_target, agent, "targets/shop/buy.target.json").kind == "policy_path"
        assert (
            refused(
                agent.call,
                "graph.create",
                {"path": "tests/shop/new.graph.json", "kind": "test"},
            ).kind
            == "policy_path"
        )
    with daemon.client() as ui:
        assert save_target(ui, "targets/shop/buy.target.json")["revision"]  # 사람은 그대로


def test_forbidden_junction_alias_write_alias(game: FakeGame, daemon: ThreadDaemon) -> None:
    """금지 목록은 실제 경로, Agent 쓰기는 정션 별칭 — 같은 실제 경로 키라 쓰지 않는다."""
    write_pay_target(game)
    make_junction(game.root / "targets" / "alias", game.root / "targets" / "shop")
    set_forbidden(game, [{"kind": "target", "path": PAY_FILES[0]}])
    prepare_capture(game)
    before = file_bytes(game, *PAY_FILES)
    with daemon.client(AGENT) as agent:
        for path in ("targets/alias/pay.target.json", "targets/ALIAS/./pay.target.json"):
            kind = refused(save_target, agent, path).kind
            assert kind in ("policy_path", "path_outside_workspace"), (path, kind)
        assert refused(save_target, agent, "targets/alias/pay.target.json").kind == "policy_path"
        assert file_bytes(game, *PAY_FILES) == before
        assert save_target(agent, "targets/alias/buy.target.json")["revision"]  # 다른 target


NEW_TARGET = "targets/shop/fresh.target.json"
"""아직 없는 파일 (새로 만들 파일 — 실제 경로로 못 풀어도 허용되는 경우의 양성 대조)."""


def test_realpath_loop_fails_closed(game: FakeGame, daemon: ThreadDaemon) -> None:
    """금지 target이 자기 자신을 가리키는 정션 아래면 실제 경로로 풀 수 없다 — 기본 `realpath`처럼
    풀리지 않은 경로로 넘어가지 않고 Agent 쓰기를 모두 거부한다. 순환이 없으면 새 파일은 쓴다."""
    import subprocess

    prepare_capture(game)
    loop = game.root / "targets" / "loop"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(loop), str(loop)], capture_output=True, check=False
    )
    assert made.returncode == 0, made.stderr
    try:
        with pytest.raises(rules.UnresolvablePath):
            rules.real_key(game.root, "targets/loop/pay.target.json")
        assert rules.real_key(game.root, NEW_TARGET) == NEW_TARGET  # 없는 파일은 푼다
        set_forbidden(game, [{"kind": "target", "path": "targets/loop/pay.target.json"}])
        with daemon.client(AGENT) as agent:
            assert refused(save_target, agent, "targets/shop/buy.target.json").kind == "policy_path"
            assert refused(lambda: save_target(agent, NEW_TARGET, new=True)).kind == "policy_path"
            graph = {"path": "tests/shop/new.graph.json", "kind": "test"}
            assert refused(agent.call, "graph.create", graph).kind == "policy_path"
        assert not (game.root / NEW_TARGET).exists()
        # 양성 대조: 순환 없는 금지 목록이면 같은 새 파일을 쓴다
        write_pay_target(game)
        set_forbidden(game, [{"kind": "target", "path": "targets/shop/pay.target.json"}])
        with daemon.client(AGENT) as agent:
            assert save_target(agent, NEW_TARGET, new=True)["revision"]
    finally:
        os.rmdir(loop)  # 정션만 지운다 (가리키는 폴더는 자기 자신)


@pytest.mark.parametrize("broken", ["missing", "invalid"])
def test_missing_forbidden_target_fails_closed(
    game: FakeGame, daemon: ThreadDaemon, broken: str
) -> None:
    """금지 target 파일이 없거나 형식이 틀리면 보호 목록을 비우지 않고 Agent 쓰기를 모두 거부한다.
    금지 목록이 비면 검사하지 않는다(양성 대조). 사람은 그대로 쓴다."""
    prepare_capture(game)
    target = "targets/shop/pay.target.json"
    if broken == "invalid":
        (game.root / target).write_text("{ 형식이 틀림", encoding="utf-8")
    set_forbidden(game, [{"kind": "target", "path": target}])
    with pytest.raises(rules.ForbiddenConfigError):
        rules.protected_paths(game.root, rules.load_items(game.root))
    with daemon.client(AGENT) as agent:
        assert refused(lambda: save_target(agent, NEW_TARGET, new=True)).kind == "policy_path"
        assert refused(save_target, agent, "targets/shop/buy.target.json").kind == "policy_path"
    assert not (game.root / NEW_TARGET).exists()
    with daemon.client() as ui:
        assert save_target(ui, "targets/shop/buy.target.json")["revision"]  # 사람은 그대로
    set_forbidden(game, [])
    assert rules.protected_paths(game.root, rules.load_items(game.root)) == set()
    # 형식이 틀린 target은 Agent 프레임 읽기(민감 target 검사)도 막으므로 양성 대조 전에 치운다
    (game.root / target).unlink(missing_ok=True)
    with daemon.client(AGENT) as agent:
        assert save_target(agent, NEW_TARGET, new=True)["revision"]


# ---------------------------------------------------------------- CLI Agent 실행 (공용 진입점)


def set_preset(game: FakeGame, preset: str) -> None:
    local = game.root / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8")) if local.exists() else {}
    body["permissions"] = {"preset": preset}
    local.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


def cli_run(
    game: FakeGame, tmp_path: Path, ocr_models: Path, rel: str, agent: str | None
) -> tuple[int, dict[str, Any]]:
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    env["KOOKABUG_OCR_MODELS"] = str(ocr_models)
    env.pop("KOOKABUG_AGENT", None)
    if agent is not None:
        env["KOOKABUG_AGENT"] = agent
    proc = run_cli(
        ["run", rel, "--platform-fake", game.platform, "--json"],
        cwd=game.root,
        env=env,
        timeout=300,
    )
    assert proc.stdout.strip(), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def test_cli_agent_run_forbidden(game: FakeGame, tmp_path: Path, ocr_models: Path) -> None:
    """`KOOKABUG_AGENT` CLI 실행도 공용 실행 진입점을 지나 금지 판정을 싣는다 — 결제 누르기가 게임에
    가지 않는다. 사람 CLI 실행은 판정하지 않는다(양성 대조). 목록을 못 읽으면 시작하지 않는다."""
    set_preset(game, "full")
    rel = run_graph(game, "cli_pay", {"n_1": tap(CHARGE, "n_2"), "n_2": tap(PAY, "n_pass")})
    code, out = cli_run(game, tmp_path, ocr_models, rel, "review-agent")
    assert (out["principal"]["kind"], out["principal"]["attended"]) == ("agent", False)
    assert (out["verdict"], out["code"]) == ("error", "forbidden_visible"), out
    assert code != 0
    assert clicks_at(game, CHARGE) == 1  # 양성 대조: 앞 노드의 누르기는 갔다
    assert clicks_at(game, PAY) == 0 and scene(game) == "shop_purchase_confirm"
    # 사람 CLI 실행: 같은 화면에서 결제 누르기가 실제로 게임에 간다
    pay = run_graph(game, "cli_pay_only", {"n_1": tap(PAY, "n_pass")})
    code, out = cli_run(game, tmp_path, ocr_models, pay, None)
    assert (code, out["verdict"]) == (0, "pass"), out
    assert clicks_at(game, PAY) == 1
    # 금지 목록 형식 오류: Agent CLI 실행은 시작하지 않는다 (실행 폴더·입력 없음)
    config = json.loads((game.root / "kookabug.json").read_text("utf-8"))
    config["automation"]["forbidden"] = [{"kind": "text"}]
    (game.root / "kookabug.json").write_text(json.dumps(config), encoding="utf-8")
    folders, sent = len(game.run_folders()), len(game.inputs())
    code, out = cli_run(game, tmp_path, ocr_models, rel, "review-agent")
    assert code == 5 and "forbidden_unverifiable" in str(out["error"]), out
    assert (len(game.run_folders()), len(game.inputs())) == (folders, sent)


def test_agent_run_subgraph_click_refused(game: FakeGame, daemon: ThreadDaemon) -> None:
    """옆 경로: Agent 실행이 부른 서브그래프 안의 입력 노드도 같은 판정을 지난다."""
    sub = {
        "format": "kookabug.graph/0",
        "kind": "subgraph",
        "plugins": {"core": "0.1.0"},
        "interface": {"exits": {"done": {"kind": "ok"}}, "inputs": {}, "outputs": {}},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_pay"}},
            "n_pay": tap(PAY, "n_exit"),
            "n_exit": {"type": "core.graph.exit", "version": 1, "config": {"exit": "done"}},
        },
    }
    (game.root / "subgraphs" / "pay_sub.graph.json").write_text(
        json.dumps(sub, ensure_ascii=False), encoding="utf-8"
    )
    call = {
        "type": "core.graph.call",
        "version": 1,
        "config": {"graph": "subgraphs/pay_sub.graph.json"},
        "in": {},
        "next": {"done": "n_pass"},
    }
    rel = run_graph(game, "pay_via_sub", {"n_1": tap(CHARGE, "n_2"), "n_2": call})
    with daemon.client(AGENT) as agent:
        started = agent.call("run.start", {"path": rel, "idempotency_key": "sub"})
        wait_ended(agent, started["run_id"])
        assert run_json(game, started["run_id"])["code"] == "forbidden_visible"
        assert clicks_at(game, CHARGE) == 1 and clicks_at(game, PAY) == 0
    with daemon.client() as ui:  # 양성 대조: 사람 실행은 서브그래프 안 결제 누르기가 간다
        click(ui, CANCEL)
        started = ui.call("run.start", {"path": rel})
        assert wait_ended(ui, started["run_id"])["outcome"]["verdict"] == "pass"
        assert clicks_at(game, PAY) == 1
