"""UX7 검수 1 High 1: 붙여 실행 기록의 창 참조 제목 — 기억한 게임 프로세스의 창은 `@game`, 그 밖의
창은 비밀값 가림을 거친 제목(가림 함수가 없으면 비움). 실행이 쓰는 값은 그대로다."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.graphs import make_workspace
from helpers.m1 import ScenePlatform
from helpers.run import tk
from testkit import registry_with_testkit

from kookabug_core.engine import (
    ExecOptions,
    Executor,
    FakeClock,
    InProcessInvoker,
    MemoryArtifacts,
    RunResult,
)
from kookabug_core.engine.context import FOREGROUND_NOT_ACQUIRED
from kookabug_core.engine.executor import AttachScrub, AttachStart, attach_record
from kookabug_core.ir import Node
from kookabug_core.loader import load_program
from kookabug_core.record.journal import Journal
from kookabug_core.registry import NodeDef
from kookabug_core.runner.run import _JournalSink  # pyright: ignore[reportPrivateUsage]
from kookabug_sdk import Result
from kookabug_sdk.context import Context
from kookabug_sdk.types import ProcessRef, WindowRef

GAME = WindowRef(handle=1, title="@game", pid=10, process_created="111")


def attach(mask: object = None) -> AttachStart:
    return AttachStart(GAME, ProcessRef(10), None, mask_title=mask)  # type: ignore[arg-type]


def test_game_window_title_becomes_label() -> None:
    real = WindowRef(handle=1, title="Game [Account : acct-77]", pid=10, process_created="111")
    out = attach_record({"window": real, "list": [real]}, attach(lambda t: t))
    assert out["window"].title == "@game" and out["list"][0].title == "@game"
    assert real.title == "Game [Account : acct-77]"  # 실행 값은 그대로


def test_other_window_title_masked_or_dropped() -> None:
    other = WindowRef(handle=2, title="Launcher secret-9", pid=20, process_created="222")
    masked = attach_record({"window": other}, attach(lambda t: "[가림]" if "secret-9" in t else t))
    assert masked["window"].title == "[가림]"
    plain = WindowRef(handle=3, title="Launcher", pid=20, process_created="222")
    assert attach_record({"w": plain}, attach(lambda t: t))["w"].title == "Launcher"
    # 가림 값을 모으지 못했으면 제목을 남기지 않는다
    assert attach_record({"w": other}, attach(None))["w"].title == ""
    # 같은 PID라도 생성 시각이 다르면 다른 프로세스다
    reused = WindowRef(handle=1, title="Other", pid=10, process_created="999")
    assert attach_record(reused, attach(None)).title == ""


def test_values_without_windows_unchanged() -> None:
    value = {"a": [1, "x", {"b": None}]}
    assert attach_record(value, attach(lambda t: t)) is value


# ---------------------------------------------------------------- 검수 2: 기록되기 전 모든 글


ACCOUNT = "review-account-77"
SECRET_VALUE = "pw-Zq81-secret"


class LockedForeground(ScenePlatform):
    """첫 창을 앞으로 가져오지 못한다 (포커스 획득 실패 경고만 대역)."""

    def bring_forward(self, window: WindowRef, step: str | None) -> bool:
        return False


class TitleFails(InProcessInvoker):
    """`n_fail`은 지금 창의 **실제 제목**과 비밀값을 메시지에 넣어 실패, `n_raise`는 예외로."""

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        title = ctx.window.title if ctx.window is not None else ""
        if node.id == "n_log":
            ctx.log.info(f"지금 창 {title} · {SECRET_VALUE}")
            return Result("ok", "ok")
        if node.id == "n_fail":
            return Result("fail", "fail", {}, f"창 '{title}'에서 못 찾았다 ({SECRET_VALUE})")
        if node.id == "n_raise":
            raise RuntimeError(f"창 '{title}'이 응답하지 않는다")
        if node.id == "n_ok":
            return Result("ok", "ok")
        return super().invoke(nodedef, node, ctx, inputs)


def run_attached(
    tmp_path: Path, last: str, *, attached: bool = True
) -> tuple[RunResult, Path, ScenePlatform]:
    platform = LockedForeground(ScenePlatform.sample().scenario)
    launched = platform.scenario.launch_game("game.exe", ())
    launched.window = replace(launched.window, title=f"ReviewGame [Account : {ACCOUNT}]")
    ws = make_workspace(tmp_path)
    graph = (
        tk()
        .entry("n_attach")
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": "ReviewGame"},
            next={"found": "n_log"},
        )
        .node("n_log", "testkit.fail_once", next={"ok": last})
        .node(last, "testkit.fail_once", next={"ok": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    graph.write(ws, "tests/review.graph.json")
    program = load_program(ws, "tests/review.graph.json")
    start = (
        AttachStart(
            replace(launched.window, title="@game"),
            ProcessRef(launched.window.pid),
            mask_title=lambda text: "[가림]" if SECRET_VALUE in text else text,
            scrub_secrets=lambda text: text.replace(SECRET_VALUE, "***"),
        )
        if attached
        else None
    )
    journal_path = tmp_path / "events.jsonl"
    with Journal(journal_path, "reviewr2", writer="runner") as journal:
        executor = Executor(
            registry_with_testkit(),
            platform=platform,
            clock=FakeClock(),
            artifacts=MemoryArtifacts(),
            sink=_JournalSink(journal),
            invoker=TitleFails(),
        )
        result = executor.run(program, ExecOptions(run_id="reviewr2", attach=start))
    return result, journal_path, platform


def agent_events(tmp_path: Path, journal: Path, result: RunResult) -> str:
    """Agent가 읽는 기록 (daemon `AgentRun` — events.jsonl에서)."""
    folder = tmp_path / "runs" / "2026-11-16T00-00-00_review_reviewr2"
    folder.mkdir(parents=True)
    (folder / "events.jsonl").write_bytes(journal.read_bytes())
    (folder / "run.json").write_text(
        json.dumps({"run_id": "reviewr2", "agent_mask": 1, "reason": result.reason}),
        encoding="utf-8",
    )
    from kookabug_daemon.agent_view import AgentRun

    view = AgentRun.load("reviewr2", folder)
    return json.dumps(view.events, ensure_ascii=False)


@pytest.mark.parametrize("last", ["n_ok", "n_fail", "n_raise"])
def test_attach_messages_do_not_leak_title(tmp_path: Path, last: str) -> None:
    """붙여 실행: 포커스 실패 경고·로그·제목이 든 노드 오류·예외·최종 판정 사유 — 디스크
    `events.jsonl`·`RunResult`(run.end·run.json 사유)·Agent 보기 어디에도 계정·비밀값이 없다."""
    result, journal, _ = run_attached(tmp_path, last)
    recorded = journal.read_text(encoding="utf-8")
    seen = [
        recorded,
        json.dumps(result.events, ensure_ascii=False),
        str(result.reason),
        agent_events(tmp_path, journal, result),
    ]
    for text in seen:
        assert ACCOUNT not in text and SECRET_VALUE not in text
    assert FOREGROUND_NOT_ACQUIRED in recorded  # 양성 대조: 경고는 남는다 (HWND·프로세스만)
    assert "@game" in recorded
    if last == "n_ok":
        assert result.verdict == "pass"
    else:
        assert result.verdict in ("fail", "error") and "@game" in str(result.reason)


def test_normal_run_warning_has_no_title(tmp_path: Path) -> None:
    """보통 실행의 포커스 실패 경고도 창 제목 대신 HWND·프로세스 이름 (제목에 계정이 든 게임)."""
    result, journal, _ = run_attached(tmp_path, "n_ok", attached=False)
    warns = [e for e in result.events if e["event"] == "log" and e.get("level") == "warn"]
    assert len(warns) == 1
    assert FOREGROUND_NOT_ACQUIRED in journal.read_text(encoding="utf-8")
    message = warns[0]["message"]
    assert message.startswith(f"{FOREGROUND_NOT_ACQUIRED}: ")
    assert "HWND 0x" in message and "프로세스 " in message
    assert ACCOUNT not in message and "ReviewGame" not in message


# ---------------------------------------------------------------- 검수 3: 구조 필드 보존


def real_masks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, secret: str) -> tuple[Any, Any]:
    """비밀값 공급자 값만 고정하고 가림 함수(정규식 포함)는 실제 `Runner._attach_masks`."""
    from types import SimpleNamespace

    from kookabug_core.runner.run import Runner

    monkeypatch.setattr("kookabug_core.agent_job.runner.known_secrets", lambda root, env: [secret])
    fake = SimpleNamespace(spec=SimpleNamespace(workspace_root=tmp_path))
    return Runner._attach_masks(fake)  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType, reportPrivateUsage]


class LogsLine(InProcessInvoker):
    """`n_log`는 비밀값과 지금 창의 실제 제목을 로그에 쓴다."""

    def __init__(self, secret: str) -> None:
        self.secret = secret

    def invoke(
        self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
    ) -> Result:
        if node.id == "n_log":
            title = ctx.window.title if ctx.window is not None else ""
            ctx.log.info(f"값 {self.secret} · 창 {title}")
            return Result("ok", "ok")
        return super().invoke(nodedef, node, ctx, inputs)


def run_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    secret: str,
    title: str,
    run_id: str,
    attached: bool = True,
) -> tuple[RunResult, Path]:
    platform = ScenePlatform.sample()
    launched = platform.scenario.launch_game("game.exe", ())
    launched.window = replace(launched.window, title=title)
    ws = make_workspace(tmp_path)
    graph = (
        tk()
        .entry("n_attach")
        .node("n_attach", "core.window.attach", inputs={"title": title}, next={"found": "n_log"})
        .node("n_log", "testkit.fail_once", next={"ok": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    graph.write(ws, "tests/collide.graph.json")
    program = load_program(ws, "tests/collide.graph.json")
    mask, scrub = real_masks(tmp_path, monkeypatch, secret)
    start = (
        AttachStart(
            replace(launched.window, title="@game"),
            ProcessRef(launched.window.pid),
            mask_title=mask,
            scrub_secrets=scrub,
        )
        if attached
        else None
    )
    journal_path = tmp_path / "events.jsonl"
    with Journal(journal_path, run_id, writer="runner") as journal:
        executor = Executor(
            registry_with_testkit(),
            platform=platform,
            clock=FakeClock(),
            artifacts=MemoryArtifacts(),
            sink=_JournalSink(journal),
            invoker=LogsLine(secret),
        )
        result = executor.run(program, ExecOptions(run_id=run_id, attach=start))
    return result, journal_path


STRUCTURE: Final = ("run", "event", "node", "step", "status", "exit", "seq", "t", "attempt")


def assert_structure_kept(result: RunResult, journal: Path, run_id: str) -> None:
    assert result.verdict == "pass", result.reason
    on_disk = [json.loads(x) for x in journal.read_text(encoding="utf-8").splitlines()]
    assert len(on_disk) == len(result.events)
    for event in on_disk:
        assert event["run"] == run_id
    kinds = {e["event"] for e in on_disk}
    assert {"step.start", "step.end", "log"} <= kinds
    nodes = [e["node"] for e in on_disk if e["event"] == "step.start"]
    assert nodes == ["n_entry", "n_attach", "n_log", "n_pass"]
    ends = [e for e in on_disk if e["event"] == "step.end"]
    assert [e["status"] for e in ends] == ["success"] * len(ends) or all(
        e["status"] in ("success", "ok") for e in ends
    )


def test_secret_colliding_with_run_id_keeps_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실행 ID와 겹치는 비밀값: 실행은 끝까지 가고 `run`은 그대로, 메시지의 값만 가린다."""
    result, journal = run_collision(
        tmp_path, monkeypatch, secret="abc", title="ReviewGame", run_id="abc12345"
    )
    assert_structure_kept(result, journal, "abc12345")
    (log,) = [e for e in result.events if e["event"] == "log"]
    assert log["message"] == "값 *** · 창 @game"


def test_secret_equal_to_verdict_keeps_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 값(`pass`)과 같은 비밀값: 판정·상태·노드 ID(`n_pass`)는 그대로, 글만 가린다."""
    result, journal = run_collision(
        tmp_path, monkeypatch, secret="pass", title="ReviewGame", run_id="r7pass01"
    )
    assert_structure_kept(result, journal, "r7pass01")
    (log,) = [e for e in result.events if e["event"] == "log"]
    assert log["message"] == "값 *** · 창 @game"
    # 경계 단위: run.end 모양의 사유는 가리고 verdict는 그대로
    mask, scrub = real_masks(tmp_path, monkeypatch, "pass")
    start = AttachStart(GAME, ProcessRef(10), mask_title=mask, scrub_secrets=scrub)
    event = {"event": "run.end", "run": "12345678", "verdict": "pass", "reason": "password: pass"}
    recorded = AttachScrub(start, object()).event(event)
    assert recorded == {**event, "reason": "***word: ***"}


def test_game_title_equal_to_event_kind_keeps_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이벤트 종류와 같은 게임 제목(`log`): 이벤트 종류·노드 ID(`n_log`)는 그대로, 메시지의 제목만
    `@game`."""
    result, journal = run_collision(
        tmp_path, monkeypatch, secret="zq81secret", title="log", run_id="r7log001"
    )
    assert_structure_kept(result, journal, "r7log001")
    (log,) = [e for e in result.events if e["event"] == "log"]
    assert log["message"] == "값 *** · 창 @game"
    # 보통 실행은 바뀌지 않는다 (대조군)
    plain, _ = run_collision(
        tmp_path / "plain",
        monkeypatch,
        secret="zq81secret",
        title="log",
        run_id="r7log002",
        attached=False,
    )
    (raw,) = [e for e in plain.events if e["event"] == "log"]
    assert raw["message"] == "값 zq81secret · 창 log"


def test_title_lookup_cached_one_second() -> None:
    """게임 창 제목은 가벼운 `window_title`로, 최대 1초에 한 번만 읽는다."""

    class Titles:
        def __init__(self) -> None:
            self.reads = 0

        def window_title(self, window: WindowRef) -> str:
            self.reads += 1
            return "Game Title"

        def window_info(self, window: WindowRef) -> Any:
            raise AssertionError("window_info를 부르지 않는다")

    now = [100.0]
    titles = Titles()
    scrub = AttachScrub(attach(lambda t: t), titles, clock=lambda: now[0])
    for _ in range(5):
        assert scrub.event({"event": "log", "message": "Game Title"})["message"] == "@game"
    assert titles.reads == 1
    now[0] += 0.9
    scrub.event({"event": "log", "message": "x"})
    assert titles.reads == 1
    now[0] += 0.2
    scrub.event({"event": "log", "message": "x"})
    assert titles.reads == 2


# ---------------------------------------------------------------- 검수 4: 메시지에 창 제목 없음


@pytest.mark.parametrize("attached", [True, False], ids=["attach", "normal"])
def test_changed_title_in_platform_error_does_not_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, attached: bool
) -> None:
    """로그인 뒤 바뀐 제목 + 최소화 오류: 오류 글은 실제 Windows 플랫폼 코드(`check_not_minimized`
    → `describe`)가 만든다. 제목 캐시가 아직 옛 제목인 1초 안이어도(시계 고정), 보통 실행이어도
    디스크 `events.jsonl`·`RunResult.events`·판정 사유에 바뀐 제목의 계정이 없다."""
    from types import SimpleNamespace

    from kookabug_platform.windows import check_not_minimized

    original = AttachScrub.__init__

    def fixed_clock(self: AttachScrub, attach: AttachStart, platform: Any) -> None:
        original(self, attach, platform, clock=lambda: 100.0)

    monkeypatch.setattr(AttachScrub, "__init__", fixed_clock)
    platform = ScenePlatform.sample()
    launched = platform.scenario.launch_game("game.exe", ())
    launched.window = replace(launched.window, title="ReviewGame [로그인 대기]")
    account = "review-r4-new-account-77"
    new_title = f"ReviewGame [Account : {account}]"

    class LoginThenMinimize(InProcessInvoker):
        def invoke(
            self, nodedef: NodeDef, node: Node, ctx: Context, inputs: Mapping[str, Any]
        ) -> Result:
            if node.id == "n_fail":
                launched.window = replace(launched.window, title=new_title)
                api = SimpleNamespace(
                    is_minimized=lambda hwnd: True,
                    is_window=lambda hwnd: True,
                    window_pid=lambda hwnd: launched.window.pid,
                    process_name=lambda pid: "game.exe",
                    window_title=lambda hwnd: new_title,
                )
                check_not_minimized(launched.window.handle, api)  # type: ignore[arg-type]
            return super().invoke(nodedef, node, ctx, inputs)

    ws = make_workspace(tmp_path)
    graph = (
        tk()
        .entry("n_attach")
        .node(
            "n_attach",
            "core.window.attach",
            inputs={"title": "ReviewGame"},
            next={"found": "n_fail"},
        )
        .node("n_fail", "testkit.fail_once", next={"ok": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    graph.write(ws, "tests/review.graph.json")
    program = load_program(ws, "tests/review.graph.json")
    mask, scrub = real_masks(tmp_path, monkeypatch, "registered-secret")
    start = (
        AttachStart(
            replace(launched.window, title="@game"),
            ProcessRef(launched.window.pid),
            mask_title=mask,
            scrub_secrets=scrub,
        )
        if attached
        else None
    )
    journal_path = tmp_path / "events.jsonl"
    with Journal(journal_path, "r4cache1", writer="runner") as journal:
        executor = Executor(
            registry_with_testkit(),
            platform=platform,
            clock=FakeClock(),
            artifacts=MemoryArtifacts(),
            sink=_JournalSink(journal),
            invoker=LoginThenMinimize(),
        )
        result = executor.run(program, ExecOptions(run_id="r4cache1", attach=start))
    assert result.verdict == "error"
    assert "window_minimized" in result.code or "최소화" in str(result.reason)
    seen = {
        "journal": journal_path.read_text(encoding="utf-8"),
        "events": json.dumps(result.events, ensure_ascii=False),
        "reason": str(result.reason),
    }
    assert not [name for name, text in seen.items() if account in text]
    assert "HWND 0x" in seen["reason"] and "game.exe" in seen["reason"]
