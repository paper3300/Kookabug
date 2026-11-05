"""M3 완료 기준 (구현 계획 v0 1장, M3 계획 3장 "완료 기준 → 테스트 매핑") 인수 테스트, Python 쪽.

1. 실패 실행을 뷰어로 열어 실패 노드까지 한 번에 이동 — 실제 runner 실행 폴더의 색인 실패 사슬이
   `run.end.failure_step`과 같다. 입력 계산 실패(`any → string` `type_mismatch`)도 그 스텝이
   실패 사슬 끝이다(2차 N1). 앱 쪽은 `apps/desktop/e2e/acceptance.m3.spec.ts`
2. 재개 후 대상이 사라졌으면 입력이 나가지 않음 — 실제 runner·가짜 입력 기록
3. 오래된 OCR로 분기하지 않음 — 경계 멈춤, 폴링 중 멈춤(`ocr.wait_text.contains`에 OCR 글자,
   검수 H2), `wait_stable` 재개 (실제 runner·실제 OCR)
4. 멈춘 시간이 두 타임아웃에서 빠짐 — 노드 timeout 안 폴링 멈춤이 노드 기한·전체 기한을 둘 다 넘은
   뒤 pass(검수 M7). 멈춘 채 임대권 유지, UI 없이 멈춘 실행의 자동 취소 뒤 실제 시간 유예 안 종료
5. 성공한 실행의 영상은 지워짐 — `failed_only` pass 삭제·fail 보관(가짜 인코더, `media`면 실제
   MP4), `run.end` 뒤 runner 강제 종료, 인코더 정지(2차 N2)
6. 기록 끈 구간은 영상에도 없음 — `record.video: off` 서브그래프와 비밀값을 받은 호출(그 아래 일반
   대기·중첩 호출 포함), 비밀값 스텝의 `step.start`와 분류 사이에 바뀐 장면(2차 N1). 모든 조각의
   장면 표시를 대조하고 `media`면 실제로 디코드한다(검수 H1)
(5장) 영상 사용 불가 환경에서도 실행 — 이유가 `run.json`에 남는다
(6장) 중단된 실행의 임시 영상을 감독자가 마무리

runner는 실제 프로세스(`RunnerHarness`: 테스트 프로세스 안의 실제 `Supervisor`), 플랫폼은 가짜 장면
표다. 영상 인코더는 숨은 검사 설정(`KOOKABUG_VIDEO_TEST`)으로 가짜 인코더를 쓰고, 실제 MP4는
`media` 표시 검사가 본다. 자동 취소는 daemon(같은 프로세스, `ThreadDaemon`)이 감독자다. 다른 테스트
모듈을 import하지 않는다. 자세한 경우는 각 작업의 테스트에 있다(`tests/runner/test_debugger_*`,
`tests/engine/test_epoch_*`, `tests/inputs/test_revalidate_epoch.py`, `tests/record/test_video_*`,
`tests/record/test_index.py`, `kookabug_daemon/tests/test_debug_methods.py`).
실제 창 녹화·잠금 해제 데스크톱은 개발자 PC(`kookabug_platform/tests/test_video_live.py`)와 사람
확인(`Docs/verification/m3-manual.md`)이다.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.daemon_runs import GRACE, EventLog, RunRig
from helpers.graphs import (
    GraphBuilder,
    link,
    make_workspace,
    secret,
    subgraph_interface,
    target,
)
from helpers.m1 import write_target
from helpers.run import tk
from helpers.runner import TEST, RunnerHarness, step_of
from helpers.video import (
    COLORS,
    VIDEO_ON_REDACT,
    go,
    launch,
    on_event,
    run_video,
    switch,
    write_scenario,
)

from kb_testing.proc import Spawned, wait_until
from kb_testing.sample_game import FRAMES_DIR
from kookabug_core.engine.debug import Breakpoint
from kookabug_core.inputs.lease import STATE_DIR_ENV, read_lease_file
from kookabug_core.record import read_run
from kookabug_core.record.finalize import video_summary
from kookabug_core.record.index import RunIndex, thumbnails, video_view
from kookabug_core.record.video import (
    INDEX_FILE,
    TEST_ENV,
    VIDEO_DIR,
    VideoGate,
    _Open,  # pyright: ignore[reportPrivateUsage] — 대조군 게이트 (보류 차단 없는 변이)
)
from kookabug_core.schema import check_shape
from kookabug_platform.frames import decode_image
from kookabug_platform.video import MsmfFactory

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

TITLE: Final = "targets/title/screen.target.json"
"""타이틀 화면 전체 (타이틀에서만 보인다). target 폴더마다 이미지가 `t.png` 하나라 폴더를 나눈다."""
LOBBY: Final = "targets/lobby/screen.target.json"
SUB: Final = "subgraphs/s.graph.json"
INNER: Final = "subgraphs/inner.graph.json"
TITLE_TEXT: Final = [312, 150, 400, 80]
"""타이틀 화면의 제목 글자 영역."""
EMPTY_CORNER: Final = [0, 0, 120, 60]
"""글자가 없는 왼쪽 위 구석 (그 안에서 기다리는 글자는 나타나지 않는다)."""
FAKE_VIDEO: Final = {TEST_ENV: json.dumps({"encoder": "fake"})}
SECRET_ENV: Final = {"KOOKABUG_SECRET_ACC_PW": "hunter2"}
DELAY: Final = 600


# ---------------------------------------------------------------- 도우미


def title_scenario(folder: Path, after_frames: int) -> Path:
    """예제 게임 타이틀 화면이 캡처 `after_frames`번 뒤 저절로 로비로 넘어가는 가짜 장면."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("title", "lobby"):
        shutil.copyfile(FRAMES_DIR / f"{name}.png", folder / f"{name}.png")
    spec = {
        "format": "kookabug.fake-scenario/0",
        "launch": [{"variant": "default"}],
        "process": {"name": "python.exe"},
        "scenes": {"title": "title.png", "lobby": "lobby.png"},
        "start": "title",
        "transitions": [{"after_frames": after_frames, "from": "title", "to": "lobby"}],
        "variants": ["default"],
        "window": {"client_size": [1024, 640], "dpi": 96, "title": "SampleRPG"},
    }
    path = folder / "scenario.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def title_run(tmp_path: Path, graph: GraphBuilder, after_frames: int, **kw: Any) -> RunnerHarness:
    """타이틀 → 로비 장면의 실제 runner (코어 노드만). target 둘(타이틀·로비 화면 전체)."""
    scenario = title_scenario(tmp_path / "scene", after_frames)
    h = RunnerHarness.make(tmp_path, graph, plugin_modules=(), scenario=str(scenario), **kw)
    write_target(h.ws, TITLE, image="title.png")
    write_target(h.ws, LOBBY, image="lobby.png")
    return h


def video_run(tmp_path: Path, graph: GraphBuilder, **kw: Any) -> RunnerHarness:
    """단색 장면 표 + 가짜 인코더의 실제 runner (testkit 워커 포함)."""
    scenario = write_scenario(tmp_path / "scenario")
    env = {**FAKE_VIDEO, **SECRET_ENV, **kw.pop("env_extra", {})}
    kw.setdefault("shutdown_grace_ms", 8_000)
    return RunnerHarness.make(tmp_path, graph, scenario=str(scenario), env_extra=env, **kw)


def launch_then(node: str) -> GraphBuilder:
    return (
        GraphBuilder()
        .entry("n_launch")
        .node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": node})
    )


def show(g: GraphBuilder, node: str, scene: str, then: str, *, ms: int = DELAY, **kw: Any) -> Any:
    """`node`: 장면을 바꾸는 키 → `node`_w: 기다림 → `then`."""
    g.node(node, "core.input.key", inputs=go(scene), next={"done": f"{node}_w"}, **kw)
    return g.node(f"{node}_w", "core.flow.delay", inputs={"ms": ms}, next={"done": then})


def at(event: Mapping[str, Any]) -> float:
    return datetime.fromisoformat(str(event["t"]).replace("Z", "+00:00")).timestamp()


def pause_in_poll(h: RunnerHarness, node: str) -> None:
    """`node`가 시작되면 일시정지를 요청하고 그 노드의 폴링 확인 지점에서 멈출 때까지."""
    h.wait_event("step.start", node=node)
    assert h.pause() == "pausing"
    h.wait_event("debug.pause")
    (event,) = [e for e in h.events() if e["event"] == "debug.pause"]
    assert (event["node"], event["where"], event["reason"]) == (node, "poll", "request"), event


def wait_pause(h: RunnerHarness) -> None:
    wait_until(lambda: h.has_event("debug.pause"), timeout=60, message=h.stderr)


def index_result(run_dir: Path) -> tuple[RunIndex, dict[str, Any]]:
    index = RunIndex(run_dir).update()
    out = index.result(
        run_dir=f"runs/{run_dir.name}",
        state="ended",
        run_json=None,
        video=video_view(run_dir),
        thumbs=thumbnails(run_dir),
    )
    assert check_shape(out, "run-index") == []
    return index, out


def video_index(run_dir: Path) -> dict[str, Any]:
    return json.loads((run_dir / VIDEO_DIR / INDEX_FILE).read_text(encoding="utf-8"))


def video_files(run_dir: Path) -> list[str]:
    return sorted(p.name for p in (run_dir / VIDEO_DIR).glob("seg-*"))


def fake_markers(run_dir: Path) -> dict[str, list[str | None]]:
    """남은 조각 파일 → 가짜 인코더가 칸마다 적은 장면 표시."""
    out: dict[str, list[str | None]] = {}
    for path in sorted((run_dir / VIDEO_DIR).glob("seg-*.mp4")):
        lines = path.read_text(encoding="utf-8").splitlines()
        out[path.name] = [json.loads(line)["marker"] for line in lines if line]
    return out


# ---------------------------------------------------------------- 1. 실패 노드까지 한 번에


def test_index_failure_chain_matches_run_end(tmp_path: Path, spawned: Spawned) -> None:
    # 호출 → 서브그래프 안 대기 timeout(처리되지 않은 fail). 색인 실패 사슬 = 조상 사슬 + 실패 스텝
    sub = (
        GraphBuilder("subgraph", interface=subgraph_interface())
        .entry("n_wait")
        .node(
            "n_wait",
            "core.image.wait",
            inputs={"target": target(LOBBY), "timeout_ms": 400},
            next={"found": "n_done"},
        )
        .exit("n_done", "done")
    )
    root = launch_then("n_call").call("n_call", SUB, next={"done": "n_pass"})
    root.node("n_pass", "core.test.pass")
    h = title_run(tmp_path, root, after_frames=100_000)
    sub.write(h.ws, SUB)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["verdict"], run_end["code"]) == ("fail", "unhandled_fail"), run_end
    assert run_end["failure_path"] == ["n_call", "n_wait"]

    index, out = index_result(h.run_dir)
    chain = out["failure_chain"]
    assert chain[-1] == run_end["failure_step"]
    rows = {s["step"]: s for s in out["steps"]}
    call_start, _ = step_of(done.view.events, "n_call")
    assert chain[0] == call_start["step"] and rows[chain[0]]["node"] == "n_call"
    # 실패 스텝은 펼친 채 온다 (목록 클릭 한 번 → 그 스텝 선택·증거)
    failing = next(s for s in out["steps"] if s["step"] == chain[-1])
    assert (failing["node"], failing["graph"], failing["status"]) == ("n_wait", SUB, "fail")
    events = index.step_events(chain[-1])
    assert events[0]["event"] == "step.start" and events[-1]["event"] == "step.end"
    evidence = events[-1]["evidence"]
    assert evidence["target"] == LOBBY and evidence["candidates"]
    for name in ("first", "last"):
        assert (h.run_dir / evidence[name]).is_file(), evidence


def test_input_eval_failure_has_failure_step_in_index(tmp_path: Path, spawned: Spawned) -> None:
    # 2차 N1: var.set(7) → var.get(any) → string 핀 = 입력 계산의 type_mismatch. 비밀값 스텝(영상
    # 게이트 off) 뒤라도 그 스텝의 step.start·step.end가 남아 색인 실패 사슬 끝이 된다
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_sec")
    g.node(
        "n_sec",
        "testkit.sleep",
        inputs={"ms": 0, "value": secret("acc.pw")},
        next={"done": "n_set"},
    )
    g.node("n_get", "core.var.get", inputs={"name": "x"})
    g.node("n_set", "core.var.set", inputs={"name": "x", "value": 7}, next={"done": "n_fail"})
    g.node("n_fail", "core.log.message", inputs={"text": link("n_get.value")})
    h = video_run(tmp_path, g)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["code"] == "type_mismatch", run_end
    start, end = step_of(done.view.events, "n_fail")
    assert end is not None and end["status"] == "error"
    assert run_end["failure_step"] == start["step"] and run_end["failure_path"] == ["n_fail"]

    index, out = index_result(h.run_dir)
    assert out["failure_chain"] == [start["step"]]
    failing = next(s for s in out["steps"] if s["step"] == start["step"])
    assert (failing["node"], failing["status"]) == ("n_fail", "error")
    kinds = [e["event"] for e in index.step_events(start["step"])]
    assert kinds[0] == "step.start" and kinds[-1] == "step.end"


# ---------------------------------------------------------------- 2. 재개 후 대상이 사라짐


def target_gone_graph() -> GraphBuilder:
    g = launch_then("n_wait")
    g.node(
        "n_wait",
        "core.image.wait",
        inputs={"target": target(TITLE), "timeout_ms": 5_000},
        next={"found": "n_click"},
    )
    g.node(
        "n_click",
        "core.input.click",
        inputs={"match": link("n_wait.match")},
        next={"done": "n_pass"},
    )
    return g.node("n_pass", "core.test.pass")


def clicks(h: RunnerHarness) -> list[dict[str, Any]]:
    return [line for line in h.fake_inputs() if line.get("by") == "runner"]


@pytest.mark.parametrize("pause", [False, True])
def test_resume_after_target_gone_sends_no_input(
    tmp_path: Path, spawned: Spawned, pause: bool
) -> None:
    # 타이틀은 캡처 1번만 보인다. 대기가 타이틀을 찾고, 클릭 앞 브레이크포인트에서 멈췄다 재개하면
    # 세대가 올라 입력 서비스가 target으로 새 캡처에서 다시 찾는다 → 로비라 없음 → 입력 없이
    # stale_observation. 멈추지 않은 같은 실행은 그 자리를 클릭하고 pass (세대 0, M1 그대로)
    breakpoints = (Breakpoint(TEST, "n_click"),) if pause else ()
    h = title_run(tmp_path, target_gone_graph(), after_frames=1, breakpoints=breakpoints)
    h.start(spawned)
    if pause:
        wait_pause(h)
        (event,) = [e for e in h.events() if e["event"] == "debug.pause"]
        assert (event["node"], event["reason"]) == ("n_click", "breakpoint")
        assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    _, end = step_of(done.view.events, "n_click")
    assert end is not None
    if not pause:
        assert run_end["verdict"] == "pass", run_end
        assert clicks(h), "멈추지 않은 실행은 클릭이 나간다"
        return
    assert (run_end["verdict"], run_end["code"], run_end["failure_path"]) == (
        "fail",
        "unhandled_fail",
        ["n_click"],
    )
    assert str(end["message"]).startswith("stale_observation:"), end
    assert clicks(h) == []  # 입력이 하나도 나가지 않았다
    assert not done.of("input.down")
    (resume,) = done.of("debug.resume")
    assert resume["epoch"] == 1


# ---------------------------------------------------------------- 3. 오래된 OCR로 분기하지 않음


def ocr_env(ocr_models: Path) -> dict[str, str]:
    return {"KOOKABUG_OCR_MODELS": str(ocr_models)}


def stale_branch_graph() -> GraphBuilder:
    """제목 글자 읽기 → (글자 ≠ "") → 분기 → 통과/실패."""
    g = launch_then("n_read")
    g.node("n_read", "core.ocr.read", inputs={"region": TITLE_TEXT}, next={"done": "n_br"})
    g.node("n_cmp", "core.logic.compare", inputs={"a": link("n_read.text"), "op": "!=", "b": ""})
    g.node(
        "n_br",
        "core.flow.branch",
        inputs={"condition": link("n_cmp.result")},
        next={"true": "n_pass", "false": "n_other"},
    )
    g.node("n_pass", "core.test.pass")
    return g.node("n_other", "core.test.fail", inputs={"reason": "글자 없음"})


@pytest.mark.parametrize("pause", [False, True])
def test_stale_ocr_branch_not_taken(
    tmp_path: Path, spawned: Spawned, ocr_models: Path, pause: bool
) -> None:
    # OCR 읽기와 분기 사이 경계 멈춤 → 재개 → 분기는 옛 세대 글자(순수 비교를 거친 값)를 받아
    # 노드를 부르지 않고 stale_observation. 어느 출구로도 가지 않는다
    breakpoints = (Breakpoint(TEST, "n_br"),) if pause else ()
    h = title_run(
        tmp_path,
        stale_branch_graph(),
        after_frames=100_000,
        breakpoints=breakpoints,
        env_extra=ocr_env(ocr_models),
    )
    h.start(spawned)
    if pause:
        wait_pause(h)
        assert h.resume() == "running"
    done = h.finish(60)
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    started = [e["node"] for e in done.of("step.start")]
    if not pause:
        assert run_end["verdict"] == "pass", run_end
        assert "n_pass" in started
        return
    assert (run_end["verdict"], run_end["code"], run_end["failure_path"]) == (
        "fail",
        "unhandled_fail",
        ["n_br"],
    ), run_end
    _, end = step_of(done.view.events, "n_br")
    assert end is not None and end["exit"] is None
    assert str(end["message"]).startswith("stale_observation:"), end
    assert "n_read" in end["message"]
    assert "n_pass" not in started and "n_other" not in started


def test_poll_resume_stale_ocr_input_not_used(
    tmp_path: Path, spawned: Spawned, ocr_models: Path
) -> None:
    # 검수 H2: OCR 글자를 ocr.wait_text.contains에 연결하고 그 노드 폴링 중 멈춤 → 재개 → 시작 때
    # 통과한 입력도 이제 옛 세대라 다음 관측·출구 선택 전에 stale_observation. 뒤 분기는 돌지 않는다
    g = launch_then("n_read")
    g.node("n_read", "core.ocr.read", inputs={"region": TITLE_TEXT}, next={"done": "n_set"})
    # 읽은 글자(string|secret)를 string 핀에 잇는 길: 변수 → var.get(any)
    g.node(
        "n_set",
        "core.var.set",
        inputs={"name": "t", "value": link("n_read.text")},
        next={"done": "n_wait"},
    )
    g.node("n_get", "core.var.get", inputs={"name": "t"})
    g.node(
        "n_wait",
        "core.ocr.wait_text",
        inputs={"region": EMPTY_CORNER, "contains": link("n_get.value"), "timeout_ms": 60_000},
        next={"found": "n_pass", "timeout": "n_other"},
    )
    g.node("n_pass", "core.test.pass")
    g.node("n_other", "core.test.fail", inputs={"reason": "시간 초과"})
    h = title_run(tmp_path, g, after_frames=100_000, env_extra=ocr_env(ocr_models))
    h.start(spawned)
    pause_in_poll(h, "n_wait")
    assert h.resume() == "running"
    done = h.finish(60)
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["verdict"], run_end["code"], run_end["failure_path"]) == (
        "fail",
        "unhandled_fail",
        ["n_wait"],
    ), run_end
    _, end = step_of(done.view.events, "n_wait")
    assert end is not None and (end["status"], end["exit"]) == ("fail", None)
    assert str(end["message"]).startswith("stale_observation:"), end
    assert "'contains'" in end["message"]
    started = [e["node"] for e in done.of("step.start")]
    assert "n_pass" not in started and "n_other" not in started


def test_wait_stable_resume_restarts_from_new_frames(tmp_path: Path, spawned: Spawned) -> None:
    # 정지 화면에서 wait_stable 폴링 중 2초 멈춤 → 재개. 멈춘 시간이 안정 시간(1.2초)을 채우지
    # 않고, 재개 뒤 프레임만으로 1.2초를 다시 잰 뒤 stable
    g = launch_then("n_ws")
    g.node(
        "n_ws",
        "core.screen.wait_stable",
        inputs={"stable_ms": 1_200, "timeout_ms": 20_000},
        next={"stable": "n_pass"},
    )
    g.node("n_pass", "core.test.pass")
    h = title_run(tmp_path, g, after_frames=100_000).start(spawned)
    pause_in_poll(h, "n_ws")
    time.sleep(2.0)
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    _, end = step_of(done.view.events, "n_ws")
    assert end is not None and end["exit"] == "stable"
    (resume,) = done.of("debug.resume")
    assert resume["paused_ms"] >= 1_900 and resume["epoch"] == 1
    assert at(end) - at(resume) >= 1.2 - 0.05, at(end) - at(resume)


# ---------------------------------------------------------------- 4. 멈춘 시간과 두 기한


def test_poll_pause_inside_node_timeout_exceeds_both_then_passes(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 검수 M7: 노드 timeout 3초·전체 기한 4초인 실행이 대기 폴링 중 5초 멈춘 뒤에도 pass (멈춤만으로
    # 두 기한을 다 넘는다). 경과(duration_ms)는 실제 시간이라 멈춘 시간을 포함하고,
    # active_duration_ms는 뺀 값이다. 활성 시간(캡처·찾기 4번 + 폴링 쉼 0.3초)이 느린 러너에서 1초를
    # 넘으므로 기한에 여유를 둔다. 판정 뒤 녹화 마무리도 활성 시간이라 가짜 인코더로 녹화한다
    # (바쁜 CPU에서 실제 인코더 닫기가 전체 기한 검사를 흔든다)
    g = launch_then("n_wait")
    g.node(
        "n_wait",
        "core.image.wait",
        inputs={"target": target(LOBBY), "timeout_ms": 3_000},
        next={"found": "n_pass"},
    )
    g.node("n_pass", "core.test.pass")
    h = title_run(tmp_path, g, after_frames=3, deadline_ms=4_000, env_extra=FAKE_VIDEO)
    h.start(spawned)
    pause_in_poll(h, "n_wait")
    time.sleep(5.0)
    assert not h.has_event("cancel.requested")
    assert h.resume() == "running"
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["verdict"] == "pass", run_end
    assert done.of("cancel.requested") == []
    _, end = step_of(done.view.events, "n_wait")
    assert end is not None and end["exit"] == "found" and end["attempt"] == 1
    (resume,) = done.of("debug.resume")
    paused = resume["paused_ms"]
    assert paused >= 4_900
    assert end["duration_ms"] >= paused > 3_000 > end["active_duration_ms"]
    assert run_end["duration_ms"] >= paused > 4_000 > run_end["active_duration_ms"]
    assert run_end["active_duration_ms"] < run_end["duration_ms"]
    assert (run_end["paused_ms"], run_end["debug_intervened"]) == (paused, True)
    run_json = done.run_json
    assert run_json is not None
    assert (run_json["pause_count"], run_json["debug_intervened"]) == (1, True)
    assert run_json["paused_ms"] == paused


def lease_graph() -> GraphBuilder:
    """키 하나(입력 임대권) → 긴 delay → 통과."""
    return (
        GraphBuilder()
        .entry("n_key")
        .node("n_key", "core.input.key", inputs={"keys": "a"}, next={"done": "n_d1"})
        .node("n_d1", "core.flow.delay", inputs={"ms": 30_000}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )


def test_paused_lease_kept_and_released_after_auto_cancel(tmp_path: Path) -> None:
    # 멈춘 동안 입력 임대권을 쥔다. UI 연결이 하나도 없는 상태가 기한(검사에서 1초, 제품 10분)
    # 이어지면 daemon이 취소하고, 마무리 유예·임대권 정리는 실제 시간으로 끝난다
    rig = RunRig.make(tmp_path, lease_graph())
    with rig.daemon() as d:
        manager = d.daemon.run_manager
        manager.unattended_pause_s = 1.0
        manager.unattended_check_s = 0.1
        ui = d.client()
        ui.call("debug.breakpoints.set", {"breakpoints": [{"graph": TEST, "node": "n_d1"}]})
        started = ui.call("run.start", {"path": TEST})
        ui.call("run.subscribe", {"run_id": started["run_id"], "after_seq": 0})
        log = EventLog(ui, started["run_id"])
        log.until_event(lambda e: e["event"] == "debug.pause" and e["node"] == "n_d1")
        # UI가 붙어 있는 동안은 기한을 넘겨도 취소하지 않는다. 멈춘 채 임대권을 쥔다
        time.sleep(1.5)
        assert manager.active_run() == started["run_id"]
        lease = read_lease_file(rig.env[STATE_DIR_ENV])
        assert lease is not None and lease["clean"] is False and lease["owner"] is not None
        ui.close()
        began = time.monotonic()
        wait_until(lambda: manager.active_run() is None, timeout=30)
        assert time.monotonic() - began < 1.0 + GRACE["shutdown_grace_ms"] / 1000 + 3
    view = read_run(started["run_dir"])
    run_end = view.run_end
    assert run_end is not None
    assert (run_end["cancel_reason"], run_end["debug_intervened"]) == ("cancelled", True)
    lease = read_lease_file(rig.env[STATE_DIR_ENV])
    assert lease is not None and lease["clean"] is True and lease["owner"] is None


# ---------------------------------------------------------------- 5. 성공한 실행의 영상은 지워짐


def short_graph(end: str = "core.test.pass") -> GraphBuilder:
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_b")
    show(g, "n_b", "b", "n_end")
    return g.node("n_end", end)


@pytest.mark.parametrize(
    ("end", "verdict"), [("core.test.pass", "pass"), ("core.test.fail", "fail")]
)
def test_failed_only_video_deleted_on_pass_kept_on_fail(
    tmp_path: Path, spawned: Spawned, end: str, verdict: str
) -> None:
    # 워크스페이스가 정하지 않은 기본 정책(failed_only): pass는 조각을 지우고 fail은 남긴다
    h = video_run(tmp_path, short_graph(end))
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == verdict
    index = video_index(h.run_dir)
    assert index["status"] == "recorded"
    run_json = done.run_json
    assert run_json is not None and run_json["video"] == video_summary(index)
    if verdict == "pass":
        assert index["segments"] == [] and video_files(h.run_dir) == []
        assert index["deleted"] and {d["reason"] for d in index["deleted"]} == {"run_pass"}
        assert run_json["video"]["kept"] == 0
        return
    assert index["deleted"] == [] and index["segments"]
    assert all(s["mode"] == "failed_only" for s in index["segments"])
    markers = {m for scenes in fake_markers(h.run_dir).values() for m in scenes}
    assert {"a", "b"} <= markers


@pytest.mark.media
@pytest.mark.parametrize("verdict", ["pass", "fail"])
def test_failed_only_real_mp4_deleted_on_pass_kept_on_fail(tmp_path: Path, verdict: str) -> None:
    # media: 같은 규칙을 실제 Media Foundation H.264 조각으로 (남은 조각은 디코드된다)
    end = "core.test.pass" if verdict == "pass" else "core.test.fail"
    ran = run_video(
        tmp_path,
        short_graph(end),
        ws_record={"video": "failed_only"},
        factory=MsmfFactory(),
        decode=decode_image,
        stop_grace_s=30.0,
    )
    assert ran.result.verdict == verdict
    assert ran.writer_done and ran.index is not None
    if verdict == "pass":
        assert ran.index["segments"] == [] and video_files(ran.run_dir) == []
        return
    assert ran.index["segments"]
    decoded: set[str] = set()
    for seg in ran.index["segments"]:
        scenes = decode_mp4(ran.run_dir / VIDEO_DIR / seg["file"])
        assert len(scenes) == seg["frames"]
        decoded |= set(scenes)
    assert {"a", "b"} <= decoded, decoded


def test_kill_after_pass_run_end_video_deleted(tmp_path: Path, spawned: Spawned) -> None:
    # runner가 pass run.end를 쓴 직후 죽어도 감독자는 그 판정을 덮지 않고 그대로 조각을 지운다
    faults = [{"point": "runner.after_run_end", "role": "runner", "action": "exit:9"}]
    h = video_run(tmp_path, short_graph(), faults=faults)
    done = h.start(spawned).finish()
    assert done.exit_code == 9
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["verdict"], run_end["finalized_by"]) == ("pass", "runner")
    index = video_index(h.run_dir)
    assert index["segments"] == [] and {d["reason"] for d in index["deleted"]} == {"run_pass"}
    assert video_files(h.run_dir) == []
    assert done.run_json is not None and done.run_json["video"]["kept"] == 0


def test_stuck_encoder_video_omitted_and_cleaned_by_supervisor(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 2차 N2: pass 실행의 인코더가 release에서 멈췄다가 유예(3초) 뒤 늦게 깨어나 조각 이름을 바꾸고
    # segments.jsonl에 줄을 덧붙여도, runner는 영상을 포기(run.end.omitted)하고 파일을 건드리지
    # 않으며 runner 종료를 확인한 감독자가 지운다: 조각 파일 0개, index.json은 디스크와 같다
    signal = tmp_path / "stuck"
    hold = tmp_path / "hold"
    fake = {"stuck": {"op": "release", "nth": 1, "resume_after_s": 3.6, "signal": str(signal)}}
    env = {TEST_ENV: json.dumps({"encoder": "fake", "fake": fake})}
    faults = [{"point": "runner.before_lease_release", "role": "runner", "action": f"wait:{hold}"}]
    h = video_run(tmp_path, short_graph(), env_extra=env, faults=faults).start(spawned)
    resumed = signal.with_name(signal.name + ".resumed")
    wait_until(resumed.exists, timeout=30, message=h.stderr)
    video = h.run_dir / VIDEO_DIR
    wait_until(
        lambda: any(
            "file" in json.loads(line)
            for line in (video / "segments.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ),
        timeout=10,
        message=lambda: f"늦은 작성자가 줄을 쓰지 않았다 {sorted(p.name for p in video.iterdir())}",
    )
    assert not (video / INDEX_FILE).exists()  # runner는 색인을 공개하지 않았다
    run_end = h.view().run_end
    assert run_end is not None and run_end["verdict"] == "pass"
    assert run_end["omitted"] == [{"kind": "video", "reason": "encoder_stuck"}]
    hold.with_name(hold.name + ".go").write_text("", encoding="utf-8")
    done = h.finish()
    assert done.exit_code == 0, h.stderr()
    assert sorted(p.name for p in video.iterdir()) == [INDEX_FILE]
    index = video_index(h.run_dir)
    assert (index["status"], index["reason"], index["segments"]) == (
        "omitted",
        "encoder_stuck",
        [],
    )
    assert "cleanup_failed" not in index
    assert done.run_json is not None and done.run_json["video"] == video_summary(index)


# ---------------------------------------------------------------- 6. 기록 끈 구간은 영상에도 없음


def hidden_tree(seen_ms: int = DELAY) -> tuple[GraphBuilder, dict[str, GraphBuilder]]:
    """a → 비밀값 호출(c: 비밀값 직접, d: 일반 대기, 중첩 호출 e) → b → 영상 끈 서브그래프(f) → h.

    비밀값 호출·영상 끈 서브그래프 구간의 장면(c·d·e·f)은 어느 조각에도 없어야 한다. `seen_ms`는
    보여야 하는 장면(a·b·h)을 띄워 두는 시간이다."""
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_call", ms=seen_ms)
    g.call("n_call", SUB, inputs={"pw": secret("acc.pw")}, next={"done": "n_b"})
    show(g, "n_b", "b", "n_off", ms=seen_ms)
    g.call("n_off", "subgraphs/off.graph.json", next={"done": "n_h"})
    show(g, "n_h", "h", "n_pass", ms=seen_ms)
    g.node("n_pass", "core.test.pass")

    sub = tk("subgraph", interface=subgraph_interface(inputs={"pw": "secret"})).entry("n_c")
    sub.node(
        "n_c",
        "testkit.sleep",
        inputs={"ms": 0, "value": link("n_entry.pw")},
        next={"done": "n_c_key"},
    )
    show(sub, "n_c_key", "c", "n_d")
    show(sub, "n_d", "d", "n_inner")  # 비밀값을 받지 않는 대기 자식
    sub.call("n_inner", INNER, next={"done": "n_back"})
    show(sub, "n_back", "idle", "n_x", ms=0)
    sub.exit("n_x", "done")
    inner = tk("subgraph", interface=subgraph_interface()).entry("n_e")
    show(inner, "n_e", "e", "n_x")
    inner.exit("n_x", "done")
    off = tk("subgraph", interface=subgraph_interface(), record={"video": "off"}).entry("n_f")
    show(off, "n_f", "f", "n_back")
    show(off, "n_back", "idle", "n_x", ms=0)
    off.exit("n_x", "done")
    return g, {SUB: sub, INNER: inner, "subgraphs/off.graph.json": off}


HIDDEN: Final = frozenset({"c", "d", "e", "f"})


def test_record_off_and_secret_call_spans_absent_from_video(
    tmp_path: Path, spawned: Spawned
) -> None:
    # 실제 runner + 가짜 인코더 (워크스페이스 on이라 pass여도 조각이 남는다): 모든 조각의 모든 칸
    g, subs = hidden_tree()
    h = video_run(tmp_path, g)
    make_workspace(h.ws.root, record=VIDEO_ON_REDACT)
    for rel, sub in subs.items():
        sub.write(h.ws, rel)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    assert done.run_end is not None and done.run_end["verdict"] == "pass", done.run_end
    index = video_index(h.run_dir)
    assert index["segments"] and index["deleted"] == []
    written = fake_markers(h.run_dir)
    assert sorted(written) == sorted(s["file"] for s in index["segments"])
    seen = {m for scenes in written.values() for m in scenes}
    assert {"a", "b", "h"} <= seen, seen
    assert not (HIDDEN & seen), seen
    for seg in index["segments"]:
        assert len(written[seg["file"]]) == seg["frames"]
    # 두 구간은 이유와 함께 빈 구간이다
    reasons = {gap["gap"]: gap.get("step") for gap in index["gaps"]}
    call, _ = step_of(done.view.events, "n_call")
    off, _ = step_of(done.view.events, "n_off")
    assert reasons.get("secret_input") == call["step"], index["gaps"]
    assert reasons.get("policy_off") == off["step"], index["gaps"]


def nearest(pixels: Any) -> str:
    mean = pixels.reshape(-1, 3).mean(0)
    return min(COLORS, key=lambda s: float(np.abs(mean - np.array(COLORS[s])).sum()))


def decode_mp4(path: Path) -> list[str]:
    cap = cv2.VideoCapture(str(path), cv2.CAP_MSMF)
    scenes: list[str] = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            scenes.append(nearest(frame))
    finally:
        cap.release()
    return scenes


FLASH_HOLD_S: Final = 0.8
"""분류 전 구간을 녹화 칸(200 ms) 네 칸만큼 붙잡는다. 보류 중이 아니면 녹화 스레드가 그사이 바뀐
장면을 반드시 가져간다 (대조군 `test_flash_check_fails_without_pending_block`)."""


def classify_flash() -> Callable[[dict[str, Any], Any, Any], None]:
    """비밀값 호출의 step.start 직후(입력 계산·분류 전) 장면을 g로 바꾸고 분류를 0.8초 붙잡는다
    (2차 N1, T12 검수 2). 실행기 스레드에서 불리므로 그동안 입력 계산·분류가 늦어진다."""

    def flash(platform: Any, _gate: Any) -> None:
        switch(platform, "g")
        time.sleep(FLASH_HOLD_S)

    return on_event("step.start", "n_call", flash)


def flash_run(tmp_path: Path, seen_ms: int = DELAY, **kw: Any) -> Any:
    g, subs = hidden_tree(seen_ms)
    return run_video(
        tmp_path,
        g,
        subgraphs=subs,
        secrets={"acc.pw": "hunter2"},
        ws_record=VIDEO_ON_REDACT,
        hooks=[classify_flash()],
        **kw,
    )


def test_secret_step_scene_between_start_and_classification_absent(tmp_path: Path) -> None:
    # 2차 N1: 비밀값 호출의 step.start와 비밀값 분류 사이에 바뀐 장면(g)도 조각에 없다
    ran = flash_run(tmp_path)
    assert ran.result.verdict == "pass", ran.result.reason
    seen = ran.markers()
    assert {"a", "b", "h"} <= seen
    assert not ((HIDDEN | {"g"}) & seen), seen


def test_flash_check_fails_without_pending_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 대조군 (T12 검수 2): step.start 전 보류 차단을 없앤 게이트(스택만 쌓음)에서는 위 검사가 g를
    # 찾아낸다 — 위 검사의 통과가 보류 차단 덕분임을 보인다
    def no_pending(self: VideoGate, step: str) -> None:
        with self._cond:  # pyright: ignore[reportPrivateUsage]
            self._stack.append(_Open(step, pending=False))  # pyright: ignore[reportPrivateUsage]
            self._update()  # pyright: ignore[reportPrivateUsage]

    monkeypatch.setattr(VideoGate, "hold", no_pending)
    ran = flash_run(tmp_path)
    assert ran.result.verdict == "pass", ran.result.reason
    assert "g" in ran.markers(), ran.markers()


@pytest.mark.media
def test_record_off_and_secret_spans_absent_from_decoded_mp4(tmp_path: Path) -> None:
    # media: 같은 실행을 실제 H.264 조각으로 쓰고 모든 조각을 디코드해 장면을 대조한다.
    # 빈 구간 뒤 새 조각의 첫 프레임은 MSMF 쓰기 열기만큼 늦을 수 있어(설계상 2초까지 허용) 느린
    # 러너에서 0.6초 장면은 통째로 빠진다 (CI 0455c4e: {'b'}뿐) — 보여야 할 장면을 2.5초 띄운다
    ran = flash_run(
        tmp_path, seen_ms=2500, factory=MsmfFactory(), decode=decode_image, stop_grace_s=30.0
    )
    assert ran.result.verdict == "pass", ran.result.reason
    assert ran.writer_done, "녹화 스레드가 정지 유예 안에 끝나지 않았다 (MSMF 마무리 지연)"
    assert ran.index is not None and ran.index["segments"]
    decoded: set[str] = set()
    for seg in ran.index["segments"]:
        scenes = decode_mp4(ran.run_dir / VIDEO_DIR / seg["file"])
        assert len(scenes) == seg["frames"], seg
        decoded |= set(scenes)
    assert {"a", "b", "h"} <= decoded, decoded
    assert not ((HIDDEN | {"g"}) & decoded), decoded


# ---------------------------------------------------------------- (5장) 영상 사용 불가


def test_video_unavailable_run_passes_status_recorded(tmp_path: Path, spawned: Spawned) -> None:
    # Media Foundation DLL을 불러올 수 없는 환경(N판 흉내): 실행은 영상 없이 pass, 이유가 남는다
    env = {TEST_ENV: json.dumps({"encoder": "msmf", "msmf": {"mf_dlls": ["kb-missing-mf.dll"]}})}
    h = video_run(tmp_path, short_graph(), env_extra=env)
    done = h.start(spawned).finish()
    assert done.exit_code == 0, h.stderr()
    run_end = done.run_end
    assert run_end is not None and run_end["verdict"] == "pass", run_end
    assert "omitted" not in run_end
    assert done.run_json is not None
    assert done.run_json["video"] == {
        "bytes": 0,
        "deleted": 0,
        "kept": 0,
        "reason": "mf_missing",
        "status": "unavailable",
    }
    index = video_index(h.run_dir)
    assert (index["status"], index["reason"]) == ("unavailable", "mf_missing")
    assert [(g["gap"], g["reason"]) for g in index["gaps"]] == [("unavailable", "mf_missing")]
    assert video_files(h.run_dir) == []
    # 기록 뷰어의 영상 보기도 이유를 그대로 준다
    _, out = index_result(h.run_dir)
    assert out["video"] is not None and out["video"]["status"] == "unavailable"


# ---------------------------------------------------------------- (6장) 감독자 영상 마무리


def test_runner_killed_video_finalized_by_supervisor(tmp_path: Path, spawned: Spawned) -> None:
    # 조각 둘째를 쓰는 중에 runner를 죽인다: 감독자가 runner_died로 마무리하고, 쓰던 .part.mp4는
    # 재생 보장이 없어 지우고 빈 구간(interrupted)으로, 닫힌 조각은 error라 남긴다
    g = tk().entry("n_launch")
    launch(g, "n_launch", "n_a")
    show(g, "n_a", "a", "n_off")
    g.node(
        "n_off",
        "core.flow.delay",
        inputs={"ms": 300},
        next={"done": "n_b"},
        record={"video": "off"},
    )
    show(g, "n_b", "b", "n_pass", ms=30_000)
    g.node("n_pass", "core.test.pass")
    h = video_run(tmp_path, g).start(spawned)
    part = h.run_dir / VIDEO_DIR / "seg-0002.part.mp4"

    def writing() -> bool:
        try:
            return len(part.read_text(encoding="utf-8").splitlines()) >= 2
        except OSError:
            return False

    wait_until(writing, timeout=30, message=h.stderr)
    h.kill_runner()
    done = h.finish()
    run_end = done.run_end
    assert run_end is not None
    assert (run_end["code"], run_end["verdict"], run_end["finalized_by"]) == (
        "runner_died",
        "error",
        "supervisor",
    )
    index = video_index(h.run_dir)
    assert [s["file"] for s in index["segments"]] == ["seg-0001.mp4"]
    assert {d["file"]: d["reason"] for d in index["deleted"]} == {
        "seg-0002.part.mp4": "interrupted"
    }
    assert any(gap["gap"] == "interrupted" for gap in index["gaps"])
    assert video_files(h.run_dir) == ["seg-0001.frames.jsonl", "seg-0001.mp4"]
    assert done.run_json is not None and done.run_json["video"] == video_summary(index)
