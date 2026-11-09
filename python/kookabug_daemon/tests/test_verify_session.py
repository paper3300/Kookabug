"""자동 채택 검증 세션 (M8 9장 R7) — 엄격: 입력 안전·Agent 권한.

검증 실행(R1)이 도는 동안(`adopt.request` 하나의 검증 세션) Agent의 제어 입력·실행·게임 띄우기는
`verification_active`로 거부하고, 검증 사이에 다른 입력(사람 실행·녹화·게임 띄우기 포함)이 시작되면
그 뒤 검증은 무효(`verify_error`, `input_between_verifications`)다.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from helpers.adopt_rig import (
    CASE,
    TARGET,
    TEST,
    FakeVerifier,
    adoptions,
    case_doc,
    setup,
)
from helpers.cli import cli_env

from kb_testing.daemon import ThreadDaemon
from kb_testing.fake_game import FakeGame, make_fake_game
from kb_testing.proc import count_inputs
from kb_testing.sample_game import copy_example_workspace
from kookabug_core import adopt as rules
from kookabug_core import basis
from kookabug_daemon.adopt import Adopter, RunVerifier
from kookabug_daemon.client import DaemonError
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.runs import InputBetweenVerifications

PASS_GRAPH = "tests/pass.graph.json"
AGENT = {"kind": "agent", "name": "mcp", "version": "0", "id": "panel", "attended": True}


class FakeManager:
    def __init__(self) -> None:
        self.epoch = 0
        self.holds = 0
        self.started: list[str] = []

    def begin_verification(self) -> int:
        self.holds += 1
        return self.epoch

    def end_verification(self) -> None:
        self.holds -= 1

    def input_epoch(self) -> int:
        return self.epoch

    def start_verify(self, graph: str, *, epoch: int, **_: Any) -> str:
        # 실제 관리자와 같이 예약 잠금 안에서 세대를 본다
        if epoch != self.epoch:
            raise InputBetweenVerifications()
        self.started.append(graph)
        raise AssertionError("검증이 무효면 실행을 시작하지 않는다")


def test_input_between_verifications_invalidates() -> None:
    manager = FakeManager()
    verifier = RunVerifier(manager)  # type: ignore[arg-type]
    assert manager.holds == 1
    manager.epoch += 1  # 첫 검증 뒤 다른 입력이 시작됐다
    out = verifier.run("tests/a.graph.json", {}, profile=None, basis={})
    assert (out.error, out.code, out.run_id) == (
        "verify_error",
        "input_between_verifications",
        None,
    )
    assert manager.started == []
    verifier.close()
    verifier.close()  # 한 번만 푼다
    assert manager.holds == 0


@pytest.mark.process
@pytest.mark.timeout(300)
def test_verification_run_carries_forbidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검증 실행은 Agent가 준 locator로 누르므로 금지 동작 판정을 싣는다 (무인 실행 — 공용 실행
    진입점이 감독자 시작 직전에 싣는다)."""
    ws = copy_example_workspace(tmp_path)
    seen: list[Any] = []
    with ThreadDaemon(ws) as d:
        manager = d.daemon.run_manager

        def capture(root: Any, graph: str, options: Any) -> Any:
            seen.append(options)
            raise RuntimeError("검사: 시작하지 않는다")

        monkeypatch.setattr(manager.service.supervisor, "start", capture)
        with pytest.raises(RequestFailed) as caught:
            manager.start_verify(
                PASS_GRAPH, overlay={}, profile=None, basis={}, epoch=manager.input_epoch()
            )
        assert caught.value.code == "io_error"
    assert seen[0].forbidden == ({"kind": "text", "value": "결제"},)
    assert seen[0].unattended is True


@pytest.mark.process
@pytest.mark.timeout(300)
def test_agent_input_refused_during_verification(tmp_path: Path) -> None:
    ws = copy_example_workspace(tmp_path)
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "full"}
    local.write_text(json.dumps(body), encoding="utf-8")
    graph = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_pass"}},
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
    }
    (ws / PASS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
    with ThreadDaemon(ws) as d:
        manager = d.daemon.run_manager
        start = manager.begin_verification()
        try:
            with d.client(AGENT) as agent:
                for method, params in (
                    ("control.key", {"window": "SampleRPG", "keys": "a"}),
                    ("control.click", {"window": "SampleRPG", "point": [1, 1]}),
                    ("app.launch", {}),
                    ("run.start", {"path": PASS_GRAPH, "idempotency_key": "v"}),
                ):
                    with pytest.raises(DaemonError) as caught:
                        agent.call(method, params, timeout=60)
                    assert caught.value.kind == "verification_active", method
            assert manager.input_epoch() == start  # 거부된 시도는 세대를 올리지 않는다
            # 사람 실행은 막지 않지만, 그 사이 검증은 무효가 된다
            with d.client() as ui:
                run_id = ui.call("run.start", {"path": PASS_GRAPH})["run_id"]
                deadline = time.monotonic() + 120
                while ui.call("run.status", {"run_id": run_id})["state"] != "ended":
                    assert time.monotonic() < deadline
                    time.sleep(0.2)
            assert manager.input_epoch() == start + 1
        finally:
            manager.end_verification()
        with d.client(AGENT) as agent:
            started = agent.call("run.start", {"path": PASS_GRAPH, "idempotency_key": "after"})
            assert started["run_id"]


# ---------------------------------------------------------------- 문제 구간의 사람 클릭 (R7)
#
# 실제 daemon·runner·실행 관리자와 예제 상점 가짜 게임. 사람(UI 연결)의 실제 `control.click`을
# 훅으로 문제 구간에 끼운다 — 시간에 기대지 않는다. 사람 입력은 그대로 게임에 간다(집계가 오름).

SHOP = "SampleRPG 상점"
CHARGE = (902, 52)


@pytest.fixture
def game(tmp_path: Path, ocr_models: Path, monkeypatch: pytest.MonkeyPatch) -> FakeGame:
    monkeypatch.setenv("KOOKABUG_OCR_MODELS", str(ocr_models))
    shop = make_fake_game(tmp_path, scenario="shop")
    graph = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "plugins": {"core": "0.1.0"},
        "nodes": {
            "n_entry": {"type": "core.graph.entry", "version": 1, "next": {"start": "n_pass"}},
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
    }
    (shop.root / PASS_GRAPH).write_text(json.dumps(graph), encoding="utf-8")
    return shop


@pytest.fixture
def daemon(game: FakeGame, tmp_path: Path, ocr_models: Path) -> Iterator[ThreadDaemon]:
    env = cli_env(tmp_path, None)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(tmp_path / "user")
    env["KOOKABUG_OCR_MODELS"] = str(ocr_models)
    with game.daemon(env) as d:
        yield d


def human_click(d: ThreadDaemon) -> None:
    with d.client() as ui:
        assert ui.call("control.click", {"window": SHOP, "point": list(CHARGE)}, timeout=180)


def charges(game: FakeGame) -> int:
    return count_inputs(game.inputs(), "click", at=CHARGE)


def verify_runs(game: FakeGame) -> list[str]:
    """검증 실행(PASS_GRAPH)으로 만든 실행 폴더."""
    out: list[str] = []
    for folder in game.run_folders():
        info = json.loads((folder / "run.json").read_text("utf-8"))
        if info.get("graph") == PASS_GRAPH:
            out.append(str(info["run_id"]))
    return out


@pytest.mark.process
@pytest.mark.timeout(600)
def test_human_click_before_reserve_invalidates(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """세대 확인 → 예약 사이: 예약 직전에 끼어든 사람 클릭이면 그 검증은 시작하지 않고 무효다."""
    manager = daemon.daemon.run_manager
    verifier = RunVerifier(manager)
    original = manager.start_verify

    def hooked(*args: Any, **kwargs: Any) -> str:
        human_click(daemon)  # 문제 구간 (예전에는 여기서 이미 세대를 본 뒤였다)
        return original(*args, **kwargs)

    monkeypatch.setattr(manager, "start_verify", hooked)
    try:
        out = verifier.run(
            PASS_GRAPH, {}, profile=None, basis=basis.freeze(game.root, "team").record
        )
    finally:
        verifier.close()
    assert (out.error, out.code, out.run_id) == (
        "verify_error",
        "input_between_verifications",
        None,
    )
    assert charges(game) == 1  # 사람 입력은 그대로 게임에 갔다 (양성 대조)
    assert verify_runs(game) == []


@pytest.mark.process
@pytest.mark.timeout(600)
def test_human_click_after_last_verification_invalidates(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """마지막 검증 실행이 끝난 뒤 결과를 받아들이기 전에 끼어든 사람 클릭이면 그 검증은 무효다.
    끼어들지 않으면 같은 검증이 통과한다(양성 대조)."""
    manager = daemon.daemon.run_manager
    record = basis.freeze(game.root, "team").record
    verifier = RunVerifier(manager)
    try:
        clean = verifier.run(PASS_GRAPH, {}, profile=None, basis=record)
        assert (clean.error, clean.verdict) == (None, "pass"), clean
        original = manager.wait_outcome
        fired: list[str] = []

        def hooked(run_id: str, timeout: float) -> Any:
            outcome = original(run_id, timeout)
            if not fired:  # 제어 처리기도 이 함수로 클릭 실행을 기다린다 — 한 번만 끼운다
                fired.append(run_id)
                human_click(daemon)  # 문제 구간: 검증 실행은 끝났고 결과는 아직 받지 않았다
            return outcome

        monkeypatch.setattr(manager, "wait_outcome", hooked)
        out = verifier.run(PASS_GRAPH, {}, profile=None, basis=record)
    finally:
        verifier.close()
    assert (out.error, out.code) == ("verify_error", "input_between_verifications")
    assert out.run_id in verify_runs(game)  # 실행은 했지만 결과를 받아들이지 않았다
    assert charges(game) == 1


class _SessionVerifier(RunVerifier):
    """검증 세션(세대)은 실제 실행 관리자, 검증 실행 결과는 대역(늘 통과) — 게시 직전 재확인만
    본다."""

    def __init__(self, manager: Any) -> None:
        super().__init__(manager)
        self.fake = FakeVerifier()

    def run(self, graph: str, overlay: Any, *, profile: Any, basis: Any) -> Any:
        return self.fake.run(graph, overlay, profile=profile, basis=basis)


@pytest.mark.process
@pytest.mark.timeout(600)
def test_human_click_before_publish_invalidates(
    game: FakeGame, daemon: ThreadDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """검증이 모두 끝난 뒤 게시 직전에 끼어든 사람 클릭: 채택 잠금 안 재확인이 `verify_error`
    (`input_between_verifications`)로 거부하고 아무것도 게시하지 않는다."""
    ws = game.root
    change_id = setup(ws)
    before = {p: (ws / p).read_bytes() for p in (TARGET, TEST)}
    manager = daemon.daemon.run_manager
    original = rules.publish_auto

    def hooked(*args: Any, **kwargs: Any) -> Any:
        human_click(daemon)  # 문제 구간: 검증 결과는 받았고 게시 거래는 아직
        return original(*args, **kwargs)

    monkeypatch.setattr(rules, "publish_auto", hooked)
    verifier = _SessionVerifier(manager)
    try:
        result = Adopter(ws, verifier).request(CASE, change_id)
    finally:
        verifier.close()
    assert result["adopted"] is False
    assert result["failed"]["code"] == "verify_error", result
    assert "input_between_verifications" in result["failed"]["detail"]
    assert {p: (ws / p).read_bytes() for p in before} == before
    assert adoptions(ws) == [] and case_doc(ws)["state"] == "open"
    assert charges(game) == 1
    # 양성 대조: 끼어들지 않으면 같은 요청이 채택된다
    monkeypatch.setattr(rules, "publish_auto", original)
    verifier = _SessionVerifier(manager)
    try:
        assert Adopter(ws, verifier).request(CASE, change_id)["adopted"] is True
    finally:
        verifier.close()


# ---------------------------------------------------------------- 취소된 채택 요청 (R7)


@pytest.mark.process
@pytest.mark.timeout(300)
def test_cancelled_adopt_keeps_hold_until_thread_ends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """연결이 끊겨 요청 Task가 취소돼도 작업 스레드가 끝날 때까지 검증 세션(Agent 입력 차단)을
    유지하고, 작업 스레드는 취소 표시를 본다."""
    ws = copy_example_workspace(tmp_path)
    change_id = setup(ws)
    entered, release = threading.Event(), threading.Event()
    seen: dict[str, Any] = {}

    def blocking(self: Adopter, case_id: str, change_id: str, extra: Any = ()) -> dict[str, Any]:
        entered.set()
        assert release.wait(120)
        seen["cancelled"] = self.cancelled.is_set()
        return {"adopted": False}

    monkeypatch.setattr(Adopter, "request", blocking)
    local = ws / ".kookabug" / "local.json"
    body = json.loads(local.read_text("utf-8"))
    body["permissions"] = {"preset": "full"}
    local.write_text(json.dumps(body), encoding="utf-8")
    with ThreadDaemon(ws) as d:
        manager = d.daemon.run_manager
        conn = d.client()
        errors: list[BaseException] = []

        def call() -> None:
            try:
                conn.call("adopt.request", {"case": CASE, "change": change_id}, timeout=120)
            except BaseException as exc:  # 연결을 닫았다
                errors.append(exc)

        caller = threading.Thread(target=call)
        caller.start()
        assert entered.wait(60)
        assert manager._verify_holds == 1  # pyright: ignore[reportPrivateUsage]
        conn.close()  # 연결 끊김 → 요청 Task 취소
        caller.join(60)
        assert not caller.is_alive() and errors
        time.sleep(0.5)  # 취소가 처리기에 닿을 시간 (닿지 않았다면 아래 단언이 잡는다)
        # 스레드는 아직 돈다: 검증 세션 유지 — Agent 입력은 계속 거부된다
        assert manager._verify_holds == 1  # pyright: ignore[reportPrivateUsage]
        with d.client(AGENT) as agent, pytest.raises(DaemonError) as caught:
            agent.call("control.key", {"window": "SampleRPG", "keys": "a"}, timeout=60)
        assert caught.value.kind == "verification_active"
        release.set()
        deadline = time.monotonic() + 60
        while manager._verify_holds:  # pyright: ignore[reportPrivateUsage]
            assert time.monotonic() < deadline
            time.sleep(0.05)
    assert seen["cancelled"] is True


@pytest.mark.parametrize("when", ["during_verify", "before_publish"])
def test_cancelled_adopt_not_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    """취소 표시가 서면 남은 검증·게시를 하지 않는다. 사건·변경은 그대로이고 감사 이력에 취소가
    남는다. 표시가 없으면 같은 요청이 채택된다(양성 대조)."""
    ws = copy_example_workspace(tmp_path)
    change_id = setup(ws)
    before = {p: (ws / p).read_bytes() for p in (TARGET, TEST)}
    cancelled = threading.Event()
    if when == "during_verify":
        verifier = FakeVerifier(hook=lambda graph: cancelled.set())
    else:
        verifier = FakeVerifier()
        original = rules.publish_auto

        def hooked(*args: Any, **kwargs: Any) -> Any:
            cancelled.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(rules, "publish_auto", hooked)
    result = Adopter(ws, verifier, cancelled=cancelled).request(CASE, change_id)
    assert result["adopted"] is False
    assert result["failed"]["code"] == "adopt_cancelled", result
    assert {p: (ws / p).read_bytes() for p in before} == before
    assert adoptions(ws) == [] and case_doc(ws)["state"] == "open"
    assert basis.load_change(ws, change_id).state == "active"  # type: ignore[union-attr]
    log = [json.loads(x) for x in (ws / "knowledge" / "log.jsonl").read_text("utf-8").splitlines()]
    assert any(x.get("code") == "adopt_cancelled" and x["id"] == change_id for x in log)
    monkeypatch.undo()
    assert Adopter(ws, FakeVerifier()).request(CASE, change_id)["adopted"] is True
