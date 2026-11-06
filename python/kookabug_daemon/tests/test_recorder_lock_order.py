"""녹화 세션 잠금 순서 (M5 SECFIX 1b): `pause`는 세션 잠금 → 파이프라인 잠금,
`materialize`는 파이프라인 잠금 안에서 세션 잠금을 쥐지 않는다. 같은 연결이 두 RPC를 동시에
보내도 교착하지 않는다. 순서는 이벤트로 강제한다:
materialize가 파이프라인 잠금을 쥔 채 멈춤 → pause가 세션 잠금을 쥐고 파이프라인 잠금을 기다림 →
materialize가 이어서 target을 쓴다.

교착이 다시 생기면 그 프로세스는 정리(daemon 종료)에서 멈추므로, 재현은 제한 시간이 있는 자식
pytest 프로세스에서 하고 부모는 종료 코드만 본다 (회귀 때 실패 하나로 보고하고 뒤 검사는 계속).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, RecorderRig, steps_of

from kb_testing.recorder_scripts import ACCOUNT_POINT, ScriptBuilder

pytestmark = [pytest.mark.process, pytest.mark.timeout(180)]

START = {"launch": {}, "hotkeys": HOTKEYS}
DEADLINE_S = 20.0
CHILD_ENV = "KOOKABUG_LOCK_ORDER_CHILD"
CHILD_TIMEOUT_S = 120.0
DEADLOCK_EXIT = 3


def drafts_rig(tmp_path: Path) -> RecorderRig:
    """워크스페이스 target이 없는 사본: 클릭이 새 초안이 된다."""
    s = ScriptBuilder(scene="login")
    s.at(500).click(ACCOUNT_POINT)
    s.at(1500).mark("done")
    rig = RecorderRig.make(tmp_path, s.lines)
    for name in ("targets", "subgraphs", "tests"):
        shutil.rmtree(rig.root / name)
    return rig


def _plugin_args(config: pytest.Config) -> list[str]:
    """부모가 받은 `-p 플러그인`을 자식에도 (검사용 변이 플러그인이 자식에도 걸리게)."""
    args = list(config.invocation_params.args)
    out: list[str] = []
    for i, arg in enumerate(args):
        if arg == "-p" and i + 1 < len(args):
            out += ["-p", args[i + 1]]
        elif arg.startswith("-p") and len(arg) > 2:
            out.append(arg)
    return out


def test_pause_and_materialize_at_once_do_not_deadlock(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    if os.environ.get(CHILD_ENV):
        pytest.skip("자식 프로세스에서는 아래 검사만 돈다")
    node = f"{Path(__file__).as_posix()}::test_child_pause_and_materialize"
    cmd = [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    cmd += [*_plugin_args(request.config), "--basetemp", str(tmp_path / "child"), node]
    env = {**os.environ, CHILD_ENV: "1"}
    try:
        done = subprocess.run(
            cmd,
            cwd=request.config.rootpath,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CHILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"자식 검사가 {CHILD_TIMEOUT_S:.0f}초 안에 끝나지 않았다 (교착)\n{exc.stdout}")
    output = done.stdout + done.stderr
    assert done.returncode != DEADLOCK_EXIT, f"교착\n{output}"
    assert done.returncode == 0 and "1 passed" in output, output


def test_child_pause_and_materialize(tmp_path: Path) -> None:
    """자식 프로세스 본체. 교착을 보면 정리에서 멈추지 않게 바로 끝낸다."""
    if not os.environ.get(CHILD_ENV):
        pytest.skip("부모 검사가 자식 프로세스로 돌린다")
    rig = drafts_rig(tmp_path)
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 1500)
        click = next(s for s in steps_of(ui) if s["kind"] == "click")
        assert click["target"]["source"] == "draft"
        session = d.daemon.recorder.session
        assert session is not None

        in_pipeline, pause_in_session = threading.Event(), threading.Event()
        write_target, drain = session._write_target, session.drain  # pyright: ignore[reportPrivateUsage]

        def held_write(*args: Any, **kwargs: Any) -> Any:
            in_pipeline.set()  # 파이프라인 잠금 안
            assert pause_in_session.wait(DEADLINE_S)
            threading.Event().wait(0.3)  # pause가 파이프라인 잠금 앞에서 기다리게
            return write_target(*args, **kwargs)

        def marked_drain() -> None:
            if threading.current_thread().name == "pauser":
                pause_in_session.set()  # 세션 잠금 안
            drain()

        session._write_target = held_write  # pyright: ignore[reportAttributeAccessIssue,reportPrivateUsage]
        session.drain = marked_drain  # pyright: ignore[reportAttributeAccessIssue]
        errors: list[BaseException] = []
        results: dict[str, Any] = {}

        def run(name: str, fn: Any) -> threading.Thread:
            def body() -> None:
                try:
                    results[name] = fn()
                except BaseException as exc:  # 스레드 밖으로 넘긴다
                    errors.append(exc)

            t = threading.Thread(target=body, name=name, daemon=True)
            t.start()
            return t

        materializer = run("materializer", lambda: session.materialize(click["step"]))
        assert in_pipeline.wait(DEADLINE_S)
        pauser = run("pauser", session.pause)
        materializer.join(DEADLINE_S)
        pauser.join(DEADLINE_S)
        alive = [t.name for t in (materializer, pauser) if t.is_alive()]
        if alive:
            print(f"교착: {alive}", flush=True)
            os._exit(DEADLOCK_EXIT)  # daemon 정리가 잠긴 세션을 기다리며 멈추지 않게
        assert not errors, errors
        assert results["materializer"]["path"].startswith("targets/rec/")
        assert session.state == "paused"
