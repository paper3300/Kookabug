"""세션 저장소 `steps.json`과 늦은 비밀값 (M5 SECFIX).

스텝을 비밀값으로 바꾼 RPC가 끝난 뒤에는 저장소에 바뀌기 전 스냅숏(원문이 든 재사용 target 이름·
제목)이 남거나 다시 써지지 않는다. 부하 때만 나던 순서를 이벤트·실제 파일 잠금으로 강제한다:
- 바꾼 뒤 쓰기가 늦음: RPC는 그 쓰기가 끝나기 전에 응답하지 않고, 응답 직후 디스크에 원문이 없다
- 바꾸기 전 스냅숏을 든 쓰기가 늦게 끝남: 바꾼 뒤 저장소를 덮지 못한다
- 다른 쪽이 `steps.json`을 연 채(Windows 실제 핸들): 쓰기 공유가 있으면 제자리 덮어써 깨끗하고,
  없으면 RPC가 `recorder_store_unclean`으로 응답하고 정지·종료 뒤에도 다시 정리한다
- 저장이 파이프라인 잠금을 쥔 동안에도 상태 조회가 이벤트 루프를 막지 않는다
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, RecorderRig, steps_of

from kb_testing.proc import wait_until
from kb_testing.recorder_scripts import ACCOUNT_POINT, LOGIN_POINT, ScriptBuilder
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.recorder import RecorderSession

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

START = {"launch": {}, "hotkeys": HOTKEYS}
RAW = "vaultcode42"
PATH = f"targets/login/{RAW}.target.json"
WAIT_S = 20.0


def script() -> list[dict[str, Any]]:
    s = ScriptBuilder(scene="login")
    s.at(500).click(ACCOUNT_POINT)
    s.at(1000).type(RAW)
    s.at(3500).key("tab")
    s.at(4500).mark("done")
    return s.lines


def make_secret(ui: DaemonClient, text: dict[str, Any]) -> None:
    patch = {"text_state": "secret", "secret_key": "review.test"}
    changed = ui.call("recorder.step.update", {"step": text["step"], "patch": patch})
    assert changed["step"]["text_state"] == "secret"


def rig_with_named_target(tmp_path: Path) -> RecorderRig:
    """기존 워크스페이스 target 이름에 나중에 비밀값이 될 글자가 있다 (재사용 클릭 스텝)."""
    rig = RecorderRig.make(tmp_path, script())
    old = rig.root / "targets/login/account_field.target.json"
    old.with_name(RAW + ".target.json").write_bytes(old.read_bytes())
    old.unlink()
    return rig


def recorded(rig: RecorderRig, d: Any, ui: DaemonClient) -> tuple[RecorderSession, dict[str, Any]]:
    """녹화 → 정지. 정지 때 쓴 steps.json에는 (일반 글자일 때라) 원문 이름이 있다."""
    ui.call("recorder.start", START)
    rig.advance(d, 4500)
    ui.call("recorder.stop", {})
    steps = steps_of(ui)
    assert any(s.get("target", {}).get("path") == PATH for s in steps)
    session = d.daemon.recorder.session
    assert session is not None and session.store is not None
    assert RAW in stored_text(session)
    return session, next(s for s in steps if s["kind"] == "text")


def stored_text(session: RecorderSession) -> str:
    """`steps.json`과 남은 `steps.json.tmp` (없으면 빈 문자열)."""
    assert session.store is not None
    out = ""
    for name in ("steps.json", "steps.json.tmp"):
        path = session.store.folder / name
        if path.is_file():
            out += path.read_text(encoding="utf-8")
    return out


@contextmanager
def wrapped_writes(
    session: RecorderSession, wrap: Callable[[Callable[..., Any]], Callable[..., Any]]
) -> Iterator[None]:
    store = session.store
    assert store is not None
    original = store.write_steps
    store.write_steps = wrap(original)  # pyright: ignore[reportAttributeAccessIssue]
    try:
        yield
    finally:
        store.write_steps = original  # pyright: ignore[reportAttributeAccessIssue]


def in_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, threading.Event, list[Any]]:
    """`fn`을 다른 스레드에서. 끝나면 이벤트가 켜지고 결과(또는 예외)가 목록에 든다."""
    done, out = threading.Event(), list[Any]()

    def body() -> None:
        try:
            out.append(fn())
        except BaseException as exc:  # 검사 스레드가 단언한다
            out.append(exc)
        finally:
            done.set()

    t = threading.Thread(target=body, daemon=True)
    t.start()
    return t, done, out


# ------------------------------------------------------------ 순서 (이벤트로 강제)


def test_secret_rpc_answers_only_after_store_is_clean(tmp_path: Path) -> None:
    """비밀값으로 바꾼 RPC는 저장이 끝나기 전에 응답하지 않고, 응답 직후(다른 RPC·`changed()`
    없이) 디스크·임시 파일에 원문이 없다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, text = recorded(rig, d, ui)
        entered, release = threading.Event(), threading.Event()

        def held(write: Callable[..., Any]) -> Callable[..., Any]:
            def run(*args: Any, **kwargs: Any) -> Any:
                if not entered.is_set():
                    entered.set()
                    assert release.wait(WAIT_S)
                return write(*args, **kwargs)

            return run

        with wrapped_writes(session, held):
            rpc, answered, out = in_thread(lambda: make_secret(ui, text))
            assert entered.wait(WAIT_S), "비밀값으로 바꾼 뒤 저장하지 않았다"
            # 저장이 붙잡힌 동안 RPC가 먼저 끝나면 응답 시점에 지난 파일이 남는다
            assert not answered.wait(0.5), "저장이 끝나기 전에 응답했다"
            release.set()
            assert answered.wait(WAIT_S)
            on_disk = stored_text(session)  # 응답 직후 그대로 읽는다
            rpc.join(WAIT_S)
        assert out == [None], out
        assert on_disk and RAW not in on_disk


def test_stale_snapshot_cannot_overwrite_after_secret(tmp_path: Path) -> None:
    """바꾸기 전에 스냅숏을 뜬 쓰기가 늦게 끝나도 바꾼 뒤 저장소를 덮지 못한다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, text = recorded(rig, d, ui)
        pipeline = session.pipeline
        assert pipeline is not None
        entered, release = threading.Event(), threading.Event()

        def held(write: Callable[..., Any]) -> Callable[..., Any]:
            def run(*args: Any, **kwargs: Any) -> Any:
                if threading.current_thread().name == "stale-writer":
                    entered.set()
                    assert release.wait(WAIT_S)
                return write(*args, **kwargs)

            return run

        with wrapped_writes(session, held):
            with pipeline.lock:
                pipeline.rev += 1  # 늦은 갱신 하나 (녹화 처리 틱·알림)
            stale = threading.Thread(target=session.changed, name="stale-writer", daemon=True)
            stale.start()
            assert entered.wait(WAIT_S)
            rpc, answered, out = in_thread(lambda: make_secret(ui, text))
            # 지난 스냅숏 쓰기가 끝나기 전에 비밀값 RPC가 끝나면(잠금 밖 쓰기) 그 뒤 덮어쓴다
            answered_early = answered.wait(1.0)
            release.set()
            stale.join(WAIT_S)
            assert answered.wait(WAIT_S)
            rpc.join(WAIT_S)
            on_disk = stored_text(session)
        assert not stale.is_alive() and out == [None], out
        assert not answered_early, "지난 스냅숏 쓰기를 기다리지 않고 응답했다"
        assert on_disk and RAW not in on_disk


# ------------------------------------------------------------ 실제 파일 잠금 (Windows)

GENERIC_READ = 0x80000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 0x1, 0x2
OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL = 3, 0x80


@contextmanager
def held_open(path: Path, share: int) -> Iterator[None]:
    """다른 프로그램(검사 도구·백신)이 그 파일을 읽는 중인 것처럼 Windows 핸들을 쥔다."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType,reportUnknownVariableType]
    create = kernel.CreateFileW  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType]
    close.argtypes = [wintypes.HANDLE]
    handle = create(str(path), GENERIC_READ, share, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0)
    assert handle not in (None, ctypes.c_void_p(-1).value), ctypes.get_last_error()  # pyright: ignore[reportAttributeAccessIssue]
    try:
        yield
    finally:
        close(handle)


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows 파일 공유 규칙")


def warning_codes(ui: DaemonClient) -> list[str]:
    return [w["code"] for w in ui.call("recorder.state", {}).get("warnings", [])]


@windows_only
def test_reader_with_write_share_is_overwritten_in_place(tmp_path: Path) -> None:
    """삭제 공유 없이 읽는 중(바꿔 넣기·지우기 거부, 쓰기 공유 있음): 제자리 덮어써 RPC가 끝나면
    원문이 없다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, text = recorded(rig, d, ui)
        assert session.store is not None
        with held_open(session.store.folder / "steps.json", FILE_SHARE_READ | FILE_SHARE_WRITE):
            make_secret(ui, text)
            on_disk = stored_text(session)
            assert RAW not in str(steps_of(ui))
        assert on_disk and RAW not in on_disk
        assert "store_unclean" not in warning_codes(ui)


@windows_only
def test_reader_without_write_share_fails_rpc_and_cleans_later(tmp_path: Path) -> None:
    """쓰기 공유도 없이 읽는 중(바꿔 넣기·덮어쓰기·지우기 모두 거부): 메모리 스텝은 바뀌고 RPC는
    `recorder_store_unclean`, 경고가 보인다. 핸들이 풀리면 정지 상태에서도 daemon이 다시 정리하고
    경고를 거둔다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, text = recorded(rig, d, ui)
        assert session.store is not None
        with held_open(session.store.folder / "steps.json", FILE_SHARE_READ):
            with pytest.raises(DaemonError) as caught:
                make_secret(ui, text)
            assert caught.value.kind == "recorder_store_unclean"
            assert RAW not in str(caught.value) and str(session.store.folder) not in str(
                caught.value
            )
            steps = steps_of(ui)
            assert RAW not in str(steps)
            assert next(s for s in steps if s["step"] == text["step"])["text_state"] == "secret"
            assert "store_unclean" in warning_codes(ui)
        wait_until(lambda: "store_unclean" not in warning_codes(ui), timeout=WAIT_S, interval=0.1)
        on_disk = stored_text(session)  # 경고를 거둔 뒤에는 다시 쓰지 않는다
        assert on_disk and RAW not in on_disk  # 새 내용으로 다시 썼다


@windows_only
def test_discard_with_locked_store_removes_folder_later(tmp_path: Path) -> None:
    """버릴 때 저장소 파일이 잠겨 폴더가 남아도, 핸들이 풀리면 daemon이 다시 지운다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, _ = recorded(rig, d, ui)
        assert session.store is not None
        folder = session.store.folder
        with held_open(folder / "steps.json", FILE_SHARE_READ):
            ui.call("recorder.discard", {})
            assert folder.exists()
        wait_until(lambda: not folder.exists(), timeout=WAIT_S, interval=0.1)


def drain_notifications(ui: DaemonClient) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    while True:
        try:
            out.append(ui.notifications.get_nowait())
        except queue.Empty:
            return out


@windows_only
def test_old_session_cleanup_does_not_notify_new_recording(tmp_path: Path) -> None:
    """버린 녹화 A의 폴더가 잠겨 정리가 늦어져도, 새 녹화 B를 시작한 뒤 A의 정리 완료가 B 연결에
    `discarded` 같은 상태 알림을 보내지 않는다 (단축키가 풀리지 않게, SECFIX 3 H1)."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        old, _ = recorded(rig, d, ui)
        assert old.store is not None
        folder = old.store.folder
        with held_open(folder / "steps.json", FILE_SHARE_READ):
            ui.call("recorder.discard", {})
            assert folder.exists()
            new = ui.call("recorder.start", START)
            assert new["state"] == "recording" and new["session"] != old.s.session_id
            drain_notifications(ui)
        wait_until(lambda: not folder.exists(), timeout=WAIT_S, interval=0.05)
        wait_until(lambda: not old._retrying, timeout=WAIT_S, interval=0.05)  # pyright: ignore[reportPrivateUsage]
        assert ui.call("recorder.state", {})["state"] == "recording"
        events = [
            m["params"] for m in drain_notifications(ui) if m.get("method") == "recorder.changed"
        ]
        stale = [p for p in events if p["state"] not in ("starting", "recording", "paused")]
        assert not stale, f"지난 세션의 끝 알림: {stale}"
        assert all(p.get("session") == new["session"] for p in events), events


@windows_only
def test_discard_during_retry_keeps_cleaning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """재시도가 저장을 시작하려는 순간 버리기가 끝나도(메모리 글자 지움) 재시도 스레드가 죽지 않고,
    핸들이 풀리면 폴더를 지운다 (SECFIX 3 H2). 순서는 이벤트로 강제한다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, text = recorded(rig, d, ui)
        assert session.store is not None
        folder = session.store.folder
        entered, release = threading.Event(), threading.Event()
        crashes: list[BaseException] = []
        changed = session.changed
        original_hook = threading.excepthook

        def delayed_changed() -> None:
            if threading.current_thread().name == "recorder-store-retry" and not entered.is_set():
                entered.set()
                assert release.wait(WAIT_S)
            changed()

        def hook(args: threading.ExceptHookArgs) -> None:
            if args.thread is not None and args.thread.name == "recorder-store-retry":
                crashes.append(args.exc_value or RuntimeError())
            else:
                original_hook(args)

        monkeypatch.setattr(session, "changed", delayed_changed)
        monkeypatch.setattr(threading, "excepthook", hook)
        try:
            with held_open(folder / "steps.json", FILE_SHARE_READ):
                with pytest.raises(DaemonError) as caught:
                    make_secret(ui, text)
                assert caught.value.kind == "recorder_store_unclean"
                assert entered.wait(WAIT_S)  # 재시도가 저장 직전에 멈췄다
                ui.call("recorder.discard", {})
                assert session.state == "discarded"
                release.set()
                wait_until(lambda: session._retry_tries >= 1, timeout=WAIT_S, interval=0.05)  # pyright: ignore[reportPrivateUsage]
                assert folder.exists()  # 아직 잠겨 있다
            wait_until(lambda: not folder.exists(), timeout=WAIT_S, interval=0.05)
            wait_until(lambda: not session._retrying, timeout=WAIT_S, interval=0.05)  # pyright: ignore[reportPrivateUsage]
        finally:
            release.set()
        assert not crashes, crashes


@windows_only
def test_daemon_shutdown_with_locked_store_finishes_and_cleans_later(tmp_path: Path) -> None:
    """daemon 종료(`close()` → 버리기) 때 저장소가 잠겨 있어도 종료는 끝나고, 핸들이 풀리면
    지운다."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, _ = recorded(rig, d, ui)
        assert session.store is not None
        folder = session.store.folder
        with held_open(folder / "steps.json", FILE_SHARE_READ):
            d.daemon.stop("test")
            assert d.finished(timeout=WAIT_S) == "test"
            assert folder.exists()
        wait_until(lambda: not folder.exists(), timeout=WAIT_S, interval=0.05)
        wait_until(lambda: not session._retrying, timeout=WAIT_S, interval=0.05)  # pyright: ignore[reportPrivateUsage]


# ------------------------------------------------------------ 이벤트 루프


def test_state_rpc_does_not_stall_event_loop_during_store_write(tmp_path: Path) -> None:
    """저장이 파이프라인 잠금을 쥔 동안 이벤트 루프에서 상태를 읽어도 루프가 멈추지 않는다
    (`recorder.state`·RPC 처리기와 같은 호출)."""
    rig = rig_with_named_target(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        session, _ = recorded(rig, d, ui)
        pipeline = session.pipeline
        assert pipeline is not None
        entered, release = threading.Event(), threading.Event()

        def held(write: Callable[..., Any]) -> Callable[..., Any]:
            def run(*args: Any, **kwargs: Any) -> Any:
                entered.set()
                assert release.wait(WAIT_S)
                return write(*args, **kwargs)

            return run

        with wrapped_writes(session, held):
            with pipeline.lock:
                pipeline.rev += 1
            writer = threading.Thread(target=session.changed, daemon=True)
            writer.start()
            try:
                assert entered.wait(WAIT_S)
                started = time.monotonic()
                state = d.call_in_loop(session.service.state, session.owner)
                d.call_in_loop(lambda: None)
                elapsed = time.monotonic() - started
                via_rpc = ui.call("recorder.state", {})
            finally:
                release.set()
                writer.join(WAIT_S)
        assert elapsed < 1.0, f"이벤트 루프가 {elapsed:.3f}초 멈췄다"
        assert state["state"] == "stopped" and via_rpc["state"] == "stopped"


# ------------------------------------------------------------ 늦게 생긴 스텝


def test_reuse_made_after_secret_does_not_carry_raw(tmp_path: Path) -> None:
    """녹화 중 비밀값으로 바꾼 **뒤에** 만든 재사용 클릭(기존 파일 이름에 원문): 바꾼 RPC보다 늦게
    생긴 스텝도 경로·제목을 공개 스텝·저장소에 싣지 않는다 (스텝을 만드는 `refresh`가 같은 잠금
    안에서 재검사한다)."""
    s = ScriptBuilder(scene="login")
    s.at(500).click(ACCOUNT_POINT)
    s.at(1000).type(RAW)
    s.at(3500).key("tab")
    s.at(5000).click(LOGIN_POINT)
    s.at(6500).mark("done")
    rig = RecorderRig.make(tmp_path, s.lines)
    # 로그인 버튼과 맞는 기존 파일 둘(어느 쪽이 재사용돼도) 이름에 원문을 넣는다
    for rel in ("login/login_button", "broken/start_button_swapped"):
        old = rig.root / f"targets/{rel}.target.json"
        old.with_name(RAW + ".target.json").write_bytes(old.read_bytes())
        old.unlink()
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 4500)
        text = next(s for s in steps_of(ui) if s["kind"] == "text")
        make_secret(ui, text)
        rig.advance(d, 6500)
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        late = [s for s in steps if s["kind"] == "click" and s["t_ms"] >= 4500]
        assert late and "secret_overlap" in late[0]["needs_review"]
        assert late[0]["target"] == {"source": "none"}
        assert RAW not in str(steps)
        session = d.daemon.recorder.session
        assert session is not None
        on_disk = stored_text(session)
        assert on_disk and RAW not in on_disk
