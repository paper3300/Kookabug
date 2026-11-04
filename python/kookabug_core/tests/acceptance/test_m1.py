"""M1 완료 기준 (구현 계획 v0 1장, M1 계획 2.14 자동 칸) 인수 테스트. 기준 하나에 테스트 하나.

1. 예제 게임 `enter_world` + `inventory_open` 통과 — 헤드리스(장면 표, CI 항상)와 데스크톱(실제
   WGC·SendInput)
2. 일부러 깨뜨리면 실패 위치·스크린샷 — 로그인 실패
3. 일부러 깨뜨리면 실패 위치·스크린샷 — target 바꿔치기
4. Python이 없는 깨끗한 Windows에서 설치 → CLI·캡처·OCR (설치 파일 무인 설치 흉내)
5. 실제 GPU 게임 조건의 예제 게임판 (창 이동·크기 변경·한글 입력·unaware 좌표·독립 창·소유 팝업)
6. 지원하지 않는 조건은 정확한 사유로 끝남 (`*`은 바꿔 끼운 단위 경로)
7. 누른 채 runner를 강제 종료하면 실제 SendInput으로 해제

실제 게임(레포 밖)·깨끗한 Windows·DPI 150/200%는 사람 검증이다(`Docs/verification/m1-manual.md`).
제품 진입점을 쓴다: 그래프 실행은 `kookabug run` 하위 프로세스, 입력 직전 확인은 runner가 쓰는 입력
액터 + `WindowInputGuard`, 강제 종료는 감독자. 다른 테스트 모듈을 import하지 않는다. 자세한 경우는
각 작업의 테스트에 있다(`fixtures/sample-game/tests`, `tests/engine/test_failure_evidence.py`,
`kookabug_platform/tests/*`, `tests/supervisor/test_real_key_release.py`,
`tools/tests/test_installer_*.py`).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pytest
from helpers.cli import cli_env, run_cli
from helpers.graphs import GraphBuilder
from helpers.run import tk
from helpers.supervisor import SupervisorHost, events, runner_stderr, start_run

from installer import build, smoke
from kb_testing import keys
from kb_testing.display import pair_layout, reserve_env, shift_within
from kb_testing.fake_capture import FakeCaptureBackend, FakeScreen
from kb_testing.fake_win32 import FakeWindowApi
from kb_testing.proc import PROCS_DIR, Spawned, barrier, python_cmd, wait_until
from kb_testing.sample_game import (
    EXAMPLE_SECRET_ENV,
    EXAMPLE_SECRETS,
    SampleGame,
    copy_example_workspace,
    launch_sample_game,
)
from kookabug_core.inputs import ClientPoint, InputActor
from kookabug_core.inputs.backends import FakeBackend
from kookabug_core.record import read_run
from kookabug_core.record.runfolder import INPUT_RECOVERY_FILE
from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import RunHandle
from kookabug_platform.capture import CaptureService
from kookabug_platform.deadline import ObservationDeadline
from kookabug_platform.dpi import client_to_screen, per_monitor_v2_thread
from kookabug_platform.errors import (
    CAPTURE_UNSUPPORTED,
    INPUT_DESKTOP_UNAVAILABLE,
    KEY_UNKNOWN,
    OCR_MODEL_CORRUPT,
    POINT_OBSCURED,
    TARGET_ELEVATED,
    WINDOW_GONE,
    WINDOW_MINIMIZED,
    WINDOW_NOT_FOREGROUND,
    PlatformError,
)
from kookabug_platform.frames import decode_image
from kookabug_platform.ocr.models import load_manifest
from kookabug_platform.sendinput import SendInputBackend, WindowInputGuard
from kookabug_platform.tracker import WindowTracker
from kookabug_platform.vision import FrameMeta, Vision, load_target_file
from kookabug_platform.win32 import user32
from kookabug_platform.windows import activate, window_info
from kookabug_sdk.types import Target

INVENTORY_OPEN: Final = "tests/inventory_open.graph.json"
SWAPPED: Final = "tests/broken/swapped_target.graph.json"
FAKE: Final = ("--platform-fake", "fake-platform.json")
RUN_TIMEOUT_S: Final = 240
RESIZE_THRESHOLD: Final = 0.7
START_BUTTON: Final = (412, 380, 200, 64)
"""타이틀 "게임 시작" 버튼 (클라이언트 1024x640, `targets/title/start_button`)."""
INPUT_EVENTS: Final = ("key_down", "key_up", "char", "mouse_down", "mouse_up", "wheel")
INPUT_RUNNER_CMD: Final = python_cmd(PROCS_DIR / "input_runner.py")
ACK_TIMEOUT_S: Final = 10.0
SW_MINIMIZE: Final = 6


# ---------------------------------------------------------------- 예제 워크스페이스 실행


def run_example(
    ws: Path,
    tmp_path: Path,
    ocr_models: Path,
    graph: str,
    *args: str,
    timeout: float = 180,
    extra_env: Mapping[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    """복사한 예제 워크스페이스에서 `kookabug run <graph> --json`."""
    env = cli_env(
        tmp_path,
        None,
        **EXAMPLE_SECRET_ENV,
        KOOKABUG_OCR_MODELS=str(ocr_models),
        **(extra_env or {}),
    )
    done = run_cli(["run", graph, "--json", *args], cwd=ws, env=env, timeout=timeout)
    assert done.stdout.strip(), done.stderr
    return done.returncode, json.loads(done.stdout)


def step_ends(out: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """노드 ID → 그 노드의 마지막 `step.end`."""
    run_events = read_run(out["run_dir"]).events
    nodes = {e["step"]: e["node"] for e in run_events if e["event"] == "step.start"}
    return {nodes[e["step"]]: e for e in run_events if e["event"] == "step.end"}


def found(ws: Path, target: str, png: Path) -> bool:
    """그 PNG에서 target을 찾는가 (runner와 같은 매칭)."""
    spec = load_target_file(ws / target)
    pixels = decode_image(png.read_bytes())
    match = Vision().find(
        pixels, FrameMeta.of_image(pixels), Target(name=target, path=spec.path, spec=spec.spec)
    )
    return match.match is not None


def launch_node(next_node: str) -> dict[str, Any]:
    """예제 그래프와 같은 게임 실행 노드 (설정값 `game.*`)."""
    return {
        "in": {
            "args": {"$setting": "game.args"},
            "cwd": {"$setting": "game.cwd"},
            "path": {"$setting": "game.executable"},
            "timeout_ms": 30000,
            "window_title": {"$setting": "game.title"},
        },
        "next": {"attached": next_node},
        "type": "core.app.launch",
        "version": 1,
    }


def write_test_graph(ws: Path, rel: str, nodes: Mapping[str, Any]) -> str:
    """게임 실행(`n_launch`) → `nodes` → `n_pass` 테스트 그래프를 예제 워크스페이스에 쓴다."""
    body = {
        "format": "kookabug.graph/0",
        "kind": "test",
        "nodes": {
            "n_entry": {"next": {"start": "n_launch"}, "type": "core.graph.entry", "version": 1},
            **nodes,
            "n_pass": {"type": "core.test.pass", "version": 1},
        },
        "plugins": {"core": "0.1.0"},
    }
    path = ws.joinpath(*rel.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return rel


def real_game_args(title: str, event_log: Path, *options: str) -> list[str]:
    """실제 실행에서 `game.args`·`game.title`을 바꾸는 `--set` 인자 (다른 창과 겹치지 않는 제목)."""
    args = ["-m", "sample_game", "--title", title, "--event-log", str(event_log), *options]
    return ["--set", f"game.args={json.dumps(args)}", "--set", f"game.title={json.dumps(title)}"]


def game_events(event_log: Path) -> list[dict[str, Any]]:
    if not event_log.exists():
        return []
    lines = event_log.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture
def no_keys_left() -> Iterator[None]:
    """실제 입력 검사: 시작 전 눌린 키가 없고, 끝에 남은 것을 뗀다."""
    keys.assert_no_keys_held()
    try:
        yield
    finally:
        keys.release_all_for_test()


# ---------------------------------------------------------------- 1. 예제 게임 통과


@pytest.mark.parametrize(
    "mode",
    [
        pytest.param("headless", marks=pytest.mark.process),
        pytest.param("desktop", marks=pytest.mark.desktop_input),
    ],
)
@pytest.mark.timeout(300)
def test_sample_game_enter_world_and_inventory_open_pass(
    tmp_path: Path, ocr_models: Path, mode: str
) -> None:
    # 실제 게임 판은 비밀번호가 기록에 없는지도 본다: 비밀값 가림을 켠 사본 (예제 원본은 기본값)
    ws = copy_example_workspace(tmp_path, redact_secrets=True)
    if mode == "headless":
        code, out = run_example(ws, tmp_path, ocr_models, INVENTORY_OPEN, *FAKE)
        assert (code, out["verdict"], out["code"]) == (0, "pass", "assertion_passed"), out
        ends = step_ends(out)
        assert ends["n_enter_world"]["exit"] == "success"
        assert ends["n_check_inventory"]["exit"] == "ok"
        return

    keys.assert_no_keys_held()
    event_log = tmp_path / "game.jsonl"
    title = f"KBM1 {uuid.uuid4().hex[:8]}"
    try:
        code, out = run_example(
            ws,
            tmp_path,
            ocr_models,
            INVENTORY_OPEN,
            *real_game_args(title, event_log),
            timeout=RUN_TIMEOUT_S,
        )
    finally:
        keys.release_all_for_test()
    seen = game_events(event_log)
    assert (code, out["verdict"], out["code"]) == (0, "pass", "assertion_passed"), (out, seen[-5:])
    # 게임이 실제로 지나간 화면과 받은 글자 (비밀번호는 게임에만, 기록에는 없음)
    scenes = [e["scene"] for e in seen if e["event"] == "screen"]
    for scene in ("title", "login", "lobby_server1", "loading", "world", "inventory"):
        assert scene in scenes, scenes
    typed = "".join(e["text"] for e in seen if e["event"] == "char")
    assert "qa_tester_01" in typed and EXAMPLE_SECRETS["accounts.qa_tester_01"] in typed
    record = (Path(out["run_dir"]) / "events.jsonl").read_text(encoding="utf-8")
    assert EXAMPLE_SECRETS["accounts.qa_tester_01"] not in record


@pytest.mark.process
@pytest.mark.timeout(300)
def test_subgraph_window_not_set_in_caller_is_platform_unavailable_headless(
    tmp_path: Path, ocr_models: Path
) -> None:
    """서브그래프 안에서 띄운 게임 창은 호출 쪽 현재 창이 되지 않는다: 창 출력·`set_current` 없이
    호출 뒤 키를 누르면 가짜 플랫폼도 실제처럼 `platform_unavailable` (잠금 해제 데스크톱 검사에서
    처음 드러난 예제 버그의 헤드리스 회귀)."""
    ws = copy_example_workspace(tmp_path)
    path = ws / INVENTORY_OPEN
    graph = json.loads(path.read_text(encoding="utf-8"))
    del graph["nodes"]["n_use_window"]
    del graph["layout"]["nodes"]["n_use_window"]
    graph["nodes"]["n_enter_world"]["next"]["success"] = "n_press_i"
    path.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    code, out = run_example(ws, tmp_path, ocr_models, INVENTORY_OPEN, *FAKE)
    assert (code, out["verdict"], out["code"]) == (2, "error", "platform_unavailable"), out
    assert out["failure_path"] == ["n_press_i"]
    assert "입력 대상 창이 정해지지 않았다" in out["reason"]
    assert step_ends(out)["n_enter_world"]["exit"] == "success"


# ---------------------------------------------------------------- 2·3. 깨뜨리면 실패 위치·스크린샷


@pytest.mark.process
@pytest.mark.timeout(300)
def test_login_failure_leaves_failure_path_and_popup_evidence(
    tmp_path: Path, ocr_models: Path
) -> None:
    ws = copy_example_workspace(tmp_path)
    code, out = run_example(
        ws, tmp_path, ocr_models, INVENTORY_OPEN, *FAKE, "--profile", "login_fail"
    )
    assert (code, out["verdict"], out["code"]) == (1, "fail", "unhandled_fail"), out
    # 실패 위치 = 월드 접속 (연결하지 않은 login_failed 출구)
    assert out["failure_titles"] == ["월드 접속"]
    call = step_ends(out)["n_enter_world"]
    assert (call["step"], call["exit"]) == (out["failure_step"], "login_failed")
    # 호출 스텝의 실패 증거에 오류 팝업이 보인다: 오류 팝업 target으로 다시 찾으면 찾는다
    shot = Path(out["run_dir"]) / "steps" / f"{call['step']}_fail.png"
    assert call["artifacts"] == [f"steps/{shot.name}"]
    assert found(ws, "targets/login/error_popup.target.json", shot)
    assert not found(ws, "targets/lobby/server_list.target.json", shot)


@pytest.mark.process
@pytest.mark.timeout(300)
def test_swapped_target_leaves_timeout_and_mismatch_evidence(
    tmp_path: Path, ocr_models: Path
) -> None:
    ws = copy_example_workspace(tmp_path)
    code, out = run_example(ws, tmp_path, ocr_models, SWAPPED, *FAKE)
    assert (code, out["verdict"], out["code"]) == (1, "fail", "unhandled_fail"), out
    assert out["failure_titles"] == ["월드 접속", "타이틀 대기"]
    wait = step_ends(out)["n_wait_title"]
    assert (wait["step"], wait["exit"]) == (out["failure_step"], "timeout")
    # 대기 노드의 timeout 증거: 바꾼 target으로는 못 찾고 원래 target으로는 찾는다
    shot = Path(out["run_dir"]) / "steps" / f"{wait['step']}_timeout.png"
    assert not found(ws, "targets/broken/start_button_swapped.target.json", shot)
    assert found(ws, "targets/title/start_button.target.json", shot)


# ---------------------------------------------------------------- 4. 깨끗한 Windows 설치


@pytest.mark.packaging
@pytest.mark.timeout(1800)
def test_installed_cli_runs_capture_and_ocr_without_python(installer_test_setup: Path) -> None:
    """테스트 전용 판 무인 설치(공백·한글 경로) → 최종 트리 감사 → Python 없는 환경 →
    `doctor --profile headless` → 헤드리스 그래프(매칭·OCR·입력) → DLL 검사 → 제거."""
    base = Path(tempfile.mkdtemp(prefix="kb-m1-"))  # MAX_PATH 안에 들도록 짧은 경로
    target = base / "설치 폴더 공백 한글"
    before = smoke.uninstall_entries()
    try:
        report = smoke.run_all(installer_test_setup, target, log=base / "install.log")
    finally:
        if smoke.uninstaller(target) is not None:
            smoke.uninstall(target)
        shutil.rmtree(base, ignore_errors=True)
    body = json.dumps(report.to_json(), ensure_ascii=False, indent=2)
    order = [s.id for s in report.steps]
    wanted = [
        "install",
        "audit.final_tree",
        "env.python_free",
        "cli.doctor_headless",
        "cli.smoke_graph",
        "dll.check",
        "uninstall",
        "uninstall.clean",
    ]
    assert [s for s in order if s in wanted] == wanted, body
    assert report.ok, body
    after = smoke.uninstall_entries()
    assert build.TEST.uninstall_key not in after and after == before


# ---------------------------------------------------------------- 5·6. 입력 직전 확인 (데스크톱)


class Live:
    """runner와 같은 입력 경로: 창 수명 추적기 + `SendInputBackend` + `WindowInputGuard` 액터."""

    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.tracker = WindowTracker().start()
        self.actor = InputActor(SendInputBackend(), guard=WindowInputGuard(self.tracker)).start()

    def launch(self, *options: str) -> SampleGame:
        title = f"KBM1 {uuid.uuid4().hex[:8]}"
        return launch_sample_game(("--title", title, *options), workdir=self.tmp_path)

    def stop(self) -> None:
        quiesced = self.actor.stop(10)
        self.tracker.stop()
        keys.release_all_for_test()
        assert quiesced, f"검사가 키·버튼을 눌린 채 남겼다: {self.actor.held}"


@pytest.fixture
def live(tmp_path: Path) -> Iterator[Live]:
    keys.assert_no_keys_held()
    rig = Live(tmp_path)
    try:
        yield rig
    finally:
        rig.stop()


def bring_front(hwnd: int) -> None:
    wait_until(lambda: activate(hwnd), timeout=5, message=lambda: f"{hwnd:#x}를 앞으로 못 가져옴")


def move_window(hwnd: int, dx: int, dy: int) -> None:
    """창을 옮긴다. 검사 창 모니터(`KOOKABUG_TEST_DISPLAY`)가 있으면 그 작업 영역 안에 남게 이동
    방향을 뒤집을 수 있다 (`kb_testing.display.shift_within`)."""
    rect = window_info(hwnd).window_rect
    with per_monitor_v2_thread():
        dx, dy = shift_within(rect, dx, dy)
    move_to(hwnd, rect[0] + dx, rect[1] + dy)


def move_to(hwnd: int, x: int, y: int) -> None:
    flags = user32.SWP_NOSIZE | user32.SWP_NOZORDER | user32.SWP_NOACTIVATE
    with per_monitor_v2_thread():
        assert user32.SetWindowPos(hwnd, None, x, y, 0, 0, flags)
    wait_until(lambda: window_info(hwnd).window_rect[:2] == (x, y), timeout=5)


def side_by_side(first: int, other: int) -> None:
    """두 창이 겹치지 않게: 기본은 `other`를 `first` 오른쪽 20px 옆으로. 검사 창 모니터가 있으면 그
    작업 영역 안에 가로(안 들어가면 세로)로 나란히 (`kb_testing.display.pair_layout`)."""
    a, b = window_info(first).window_rect, window_info(other).window_rect
    with per_monitor_v2_thread():
        layout = pair_layout(a, b)
    if layout is None:
        move_window(other, (a[2] - a[0]) + 20, 0)
        return
    move_to(first, *layout[0])
    move_to(other, *layout[1])


def inputs_after(game: SampleGame, seq: int) -> list[dict[str, Any]]:
    return [e for e in game.events() if e["seq"] > seq and e["event"] in INPUT_EVENTS]


def refused(code: str, fn: Callable[[], object]) -> PlatformError:
    with pytest.raises(PlatformError) as caught:
        fn()
    assert caught.value.code == code, caught.value.message
    return caught.value


def chars_after(game: SampleGame, seq: int) -> str:
    return "".join(e["text"] for e in inputs_after(game, seq) if e["event"] == "char")


def check_move_then_click(live: Live) -> None:
    with live.launch() as game:
        bring_front(game.hwnd)
        target = live.tracker.bind(game.hwnd)
        move_window(game.hwnd, 60, 40)
        mark = game.last_seq()
        live.actor.click(ClientPoint(123, 77), target=target)
        down = game.wait_event("mouse_down", after=mark)
        up = game.wait_event("mouse_up", after=mark)
        assert (down["x"], down["y"], up["x"], up["y"]) == (123, 77, 123, 77)
        assert down["window"] == "main"


def check_korean_text(live: Live) -> None:
    with live.launch() as game:
        bring_front(game.hwnd)
        target = live.tracker.bind(game.hwnd)
        for text in ("한글 입력", "받침 있는 글자 값", "Server 1 서버 OK"):
            mark = game.last_seq()
            live.actor.type_text(text, target=target)
            wait_until(
                lambda m=mark, t=text: len(chars_after(game, m)) >= len(t),
                timeout=10,
                message=lambda m=mark: chars_after(game, m),
            )
            assert chars_after(game, mark) == text


def check_unaware_coordinates(live: Live) -> None:
    # unaware 게임: 클라이언트 물리 픽셀 점을 누르면 게임은 그 점의 논리 좌표(배율로 나눔)를 받는다
    with live.launch("--dpi-awareness", "unaware") as game:
        assert game.ready["dpi_awareness"] == "unaware"
        bring_front(game.hwnd)
        target = live.tracker.bind(game.hwnd)
        scale = window_info(game.hwnd).monitor_dpi / 96
        mark = game.last_seq()
        live.actor.click(ClientPoint(300, 210), target=target)
        down = game.wait_event("mouse_down", after=mark)
        assert abs(down["x"] - 300 / scale) <= 1 and abs(down["y"] - 210 / scale) <= 1, down


def check_independent_window_and_owned_popup(live: Live) -> None:
    with live.launch("--second-window") as game:
        target = live.tracker.bind(game.hwnd)
        bring_front(game.ready["windows"]["second"])  # 같은 프로세스의 독립 최상위 창
        mark = game.last_seq()
        refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.key("a", target=target))
        assert inputs_after(game, mark) == []
    with live.launch("--owned-popup") as game:
        main = live.tracker.bind(game.hwnd)
        bring_front(game.ready["windows"]["popup"])  # 대상이 소유한 팝업이 포그라운드 → 통과
        mark = game.last_seq()
        live.actor.key("a", target=main)
        game.wait_event("key_up", key="a", after=mark)
        assert {e["window"] for e in inputs_after(game, mark)} == {"popup"}


def relaxed_target(ws: Path, rel: str) -> str:
    """`rel`의 임계값만 `RESIZE_THRESHOLD`로 낮춘 사본(같은 폴더·이미지)을 쓰고 그 경로를 준다.

    예제 게임은 큰 창에서 글자를 그 크기로 다시 그린다(비트맵 확대가 아니다). 1024x640에서 기록한
    시작 버튼을 1.25배로 늘린 템플릿은 1280x800 화면에서 자리는 맞아도 점수가 0.75 근처라 기본
    임계값(0.85)에 못 미친다. 이 검사는 다시 찾기 경로를 보려는 것이라 임계값만 낮춘다."""
    src = ws.joinpath(*rel.split("/"))
    spec = json.loads(src.read_text(encoding="utf-8"))
    spec["match"] = {**spec.get("match", {}), "threshold": RESIZE_THRESHOLD}
    out = rel.removesuffix(".target.json") + "_resize.target.json"
    ws.joinpath(*out.split("/")).write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return out


def check_resize_revalidation(tmp_path: Path, ocr_models: Path) -> None:
    """찾은 뒤 창 크기가 바뀌면 입력 서비스가 target으로 다시 찾아 새 자리를 누른다 (실제
    그래프)."""
    ws = copy_example_workspace(tmp_path / "resize")
    start = relaxed_target(ws, "targets/title/start_button.target.json")
    login = relaxed_target(ws, "targets/login/account_field.target.json")
    graph = write_test_graph(
        ws,
        "tests/m1_resize.graph.json",
        {
            "n_launch": launch_node("n_wait_title"),
            "n_wait_title": {
                "in": {
                    "target": {"$target": start},
                    "timeout_ms": 60000,
                },
                "next": {"found": "n_resize"},
                "type": "core.image.wait",
                "version": 1,
            },
            "n_resize": {
                "in": {"client_size": [1280, 800]},
                "next": {"done": "n_click"},
                "type": "core.window.set_size",
                "version": 1,
            },
            "n_click": {
                "in": {"match": {"$link": "n_wait_title.match"}},
                "next": {"done": "n_wait_login"},
                "type": "core.input.click",
                "version": 1,
            },
            "n_wait_login": {
                "in": {
                    "target": {"$target": login},
                    "timeout_ms": 15000,
                },
                "next": {"found": "n_pass"},
                "type": "core.image.wait",
                "version": 1,
            },
        },
    )
    event_log = tmp_path / "resize-game.jsonl"
    title = f"KBM1R {uuid.uuid4().hex[:8]}"
    code, out = run_example(
        ws,
        tmp_path / "resize",
        ocr_models,
        graph,
        *real_game_args(title, event_log, "--dpi-awareness", "pmv2", "--size", "1024x640"),
        timeout=RUN_TIMEOUT_S,
        # 검사 창 모니터가 있으면 1280x800으로 키울 자리에 처음부터 둔다 (주 모니터를 안 가림)
        extra_env=reserve_env(1280, 800),
    )
    seen = game_events(event_log)
    assert (code, out["verdict"]) == (0, "pass"), (out, seen[-5:])
    assert [e["client_size"] for e in seen if e["event"] == "resize"][-1] == [1280, 800]
    # 다시 찾았다는 기록과, 1.25배로 그린 시작 버튼 안을 누른 게임 수신
    record = read_run(out["run_dir"]).events
    notes = [e for e in record if e["event"] == "log" and "다시 찾아" in str(e.get("message"))]
    assert notes, [e for e in record if e["event"] == "log"]
    x, y, w, h = (round(v * 1.25) for v in START_BUTTON)
    down = next(e for e in seen if e["event"] == "mouse_down")
    assert x <= down["x"] < x + w and y <= down["y"] < y + h, down


@pytest.mark.desktop_input
@pytest.mark.timeout(400)
def test_window_conditions_on_sample_game(tmp_path: Path, ocr_models: Path, live: Live) -> None:
    check_move_then_click(live)
    check_korean_text(live)
    check_unaware_coordinates(live)
    check_independent_window_and_owned_popup(live)
    check_resize_revalidation(tmp_path, ocr_models)


# ---------------------------------------------------------------- 6. 지원하지 않는 조건


def refuse_on_game(live: Live, case: str) -> None:
    """예제 게임에서 입력 직전 확인이 아무것도 보내기 전에 그 사유로 막는다."""
    options = ("--owned-popup",) if case == "obscured" else ()
    with live.launch(*options) as game:
        target = live.tracker.bind(game.hwnd)
        bring_front(game.hwnd)
        mark = game.last_seq()
        if case == "minimized":
            user32.ShowWindow(game.hwnd, SW_MINIMIZE)
            wait_until(lambda: window_info(game.hwnd).minimized, timeout=5)
            refused(WINDOW_MINIMIZED, lambda: live.actor.key("a", target=target))
        elif case == "closed":
            game.close()
            refused(WINDOW_GONE, lambda: live.actor.key("a", target=target))
            return
        elif case == "not_foreground":
            with live.launch() as other:
                side_by_side(game.hwnd, other.hwnd)
                bring_front(other.hwnd)
                other_mark = other.last_seq()
                refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.key("a", target=target))
                refused(WINDOW_NOT_FOREGROUND, lambda: live.actor.type_text("x", target=target))
                assert inputs_after(other, other_mark) == []
        else:
            # 소유 팝업이 클릭 지점을 덮음 (팝업은 클라이언트 (40, 40)부터): 커서도 옮기지 않는다
            refused(POINT_OBSCURED, lambda: live.actor.click(ClientPoint(100, 100), target=target))
            with per_monitor_v2_thread():
                assert keys.cursor_pos() != client_to_screen(game.hwnd, (100, 100))
        assert inputs_after(game, mark) == []
        assert keys.held() == [] and live.actor.held == []


def fail_headless(tmp_path: Path, ocr_models: Path, case: str) -> None:
    """예제 게임 장면 표(헤드리스)에서 그 스텝이 정확한 오류 코드로 끝난다."""
    ws = copy_example_workspace(tmp_path)
    models = ocr_models
    if case == "unknown_key":
        node, code = "n_key", KEY_UNKNOWN
        body = {"in": {"keys": "ctrl+nosuchkey"}, "type": "core.input.key"}
    else:
        # 모델 하나를 같은 크기로 바꿔 끼움 → 해시 불일치
        node, code = "n_read", OCR_MODEL_CORRUPT
        models = tmp_path / "models"
        shutil.copytree(ocr_models, models)
        rec = models / load_manifest().models[-1].file
        data = bytearray(rec.read_bytes())
        data[len(data) // 2] ^= 0xFF
        rec.write_bytes(bytes(data))
        body = {"in": {"region": [312, 150, 400, 80]}, "type": "core.ocr.read"}
    graph = write_test_graph(
        ws,
        f"tests/m1_{case}.graph.json",
        {
            "n_launch": launch_node(node),
            node: {**body, "next": {"done": "n_pass"}, "version": 1},
        },
    )
    exit_code, out = run_example(ws, tmp_path, models, graph, *FAKE)
    assert out["verdict"] == "error" and exit_code != 0, out
    end = step_ends(out)[node]
    assert end.get("exit") is None and end["error"]["code"] == code, end
    assert (out["code"], out["failure_step"]) == (code, end["step"]), out
    if case == "unknown_key":
        log = ws / "runs" / "fake-input.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
        assert not [ln for ln in lines if '"key"' in ln], lines  # 아무 키도 누르지 않았다


GAME_HWND, GAME_PID = 0x100, 10
MEDIUM, HIGH = 0x2000, 0x3000


def refuse_swapped_unit(tmp_path: Path, case: str) -> None:
    """실제로 만들기 어려운 조건은 Win32 창 표·캡처 백엔드만 바꿔 끼우고 같은 제품 경로로 본다."""
    api = FakeWindowApi(names={GAME_PID: "game.exe"})
    api.add(GAME_HWND, GAME_PID, title="Game")
    api.foreground = GAME_HWND
    tracker = WindowTracker(api)
    if case == "capture_unsupported":
        screen = FakeScreen(GAME_HWND, GAME_PID)
        backend = FakeCaptureBackend()
        backend.fail = OSError("GraphicsCaptureItem을 만들 수 없음 (전체화면 독점 흉내)")
        service = CaptureService(
            tracker, backend=backend, info=screen.info, dpi_of=lambda _h: 96, fresh_wait_ms=20
        )
        try:
            with pytest.raises(PlatformError) as caught:
                service.capture(tracker.bind(GAME_HWND), None, deadline=ObservationDeadline(500))
        finally:
            service.close_all()
        assert caught.value.code == CAPTURE_UNSUPPORTED, caught.value.message
        return
    if case == "elevated":
        api.integrity = {None: MEDIUM, GAME_PID: HIGH}
        code = TARGET_ELEVATED
    else:
        api.locked = True  # 잠금 화면 (입력 데스크톱은 Default 그대로)
        code = INPUT_DESKTOP_UNAVAILABLE
    log = tmp_path / "input.jsonl"
    actor = InputActor(FakeBackend(log), guard=WindowInputGuard(tracker, api)).start()
    try:
        target = tracker.bind(GAME_HWND)
        refused(code, lambda: actor.key("a", target=target))
        refused(code, lambda: actor.type_text("x", target=target))
        refused(code, lambda: actor.click(ClientPoint(5, 5), target=target))
    finally:
        assert actor.stop(10)
    assert not log.exists() or log.read_text(encoding="utf-8").strip() == ""


@pytest.mark.parametrize(
    "case",
    [
        pytest.param("minimized", marks=pytest.mark.desktop_input),
        pytest.param("closed", marks=pytest.mark.desktop_input),
        pytest.param("not_foreground", marks=pytest.mark.desktop_input),
        pytest.param("obscured", marks=pytest.mark.desktop_input),
        pytest.param("unknown_key", marks=[pytest.mark.process, pytest.mark.timeout(300)]),
        pytest.param("model_corrupt", marks=[pytest.mark.process, pytest.mark.timeout(300)]),
        pytest.param("elevated", id="elevated*"),
        pytest.param("input_desktop", id="input_desktop*"),
        pytest.param("capture_unsupported", id="capture_unsupported*"),
    ],
)
def test_unsupported_conditions_end_with_exact_reason(
    request: pytest.FixtureRequest, tmp_path: Path, ocr_models: Path, case: str
) -> None:
    if case in ("unknown_key", "model_corrupt"):
        fail_headless(tmp_path, ocr_models, case)
    elif case in ("elevated", "input_desktop", "capture_unsupported"):
        refuse_swapped_unit(tmp_path, case)
    else:
        rig: Live = request.getfixturevalue("live")
        refuse_on_game(rig, case)


# ---------------------------------------------------------------- 7. 강제 종료 뒤 실제 키 해제

HELD: Final = ("shift", "a", "mouse:left")
# 입력 이름 → (게임 수신 기록에서 찾을 것, GetAsyncKeyState 이름)
ACK: Final = {
    "shift": (("key", "lshift"), "shift"),
    "a": (("key", "a"), "a"),
    "b": (("key", "b"), "b"),
    "mouse:left": (("button", "left"), "mouse:left"),
}


def press_graph(game: SampleGame, inputs: Sequence[str]) -> GraphBuilder:
    return (
        tk()
        .entry("n_press")
        .node(
            "n_press",
            "testkit.input.press_window",
            inputs={"title": game.ready["title"], "inputs": list(inputs), "x": 600, "y": 520},
            next={"done": "n_pass"},
        )
        .node("n_pass", "core.test.pass")
    )


def is_ack(record: Mapping[str, Any], kind: str, name: str) -> bool:
    (field, value), _ = ACK[name]
    device = "mouse" if name.startswith("mouse:") else "key"
    return record["event"] == f"{device}_{kind}" and record.get(field) == value


def acks(game: SampleGame, kind: str, names: Sequence[str], after: int) -> list[str]:
    return [
        name
        for record in game.events()
        if record["seq"] > after
        for name in names
        if is_ack(record, kind, name)
    ]


def wait_acks(game: SampleGame, kind: str, names: Sequence[str], after: int) -> None:
    for name in names:
        game.wait_event(
            where=lambda r, n=name: is_ack(r, kind, n), after=after, timeout=ACK_TIMEOUT_S
        )


def os_down(names: Sequence[str]) -> list[str]:
    return [n for n in names if keys.is_down(ACK[n][1])]


def windows_platform(after_down: str | None = None, wall: Path | None = None) -> PlatformSpec:
    hooks = {} if after_down is None else {"after_down": {after_down: f"wait:{wall}"}}
    return PlatformSpec("windows", hooks=hooks)


def wait_wall_or_end(
    reached: Callable[[], bool], ended: Callable[[], bool], why: Callable[[], str]
) -> None:
    def check() -> bool:
        if reached():
            return True
        if ended():
            raise AssertionError(f"장벽 전에 실행이 끝났다: {why()}")
        return False

    wait_until(check, timeout=30, message=why)


@pytest.mark.desktop_input
@pytest.mark.process
@pytest.mark.timeout(240)
@pytest.mark.usefixtures("no_keys_left")
def test_real_inputs_released_after_runner_kill(tmp_path: Path, spawned: Spawned) -> None:
    names = list(HELD)
    title = f"KBM1K {uuid.uuid4().hex[:8]}"
    for part in ("a", "b"):  # 실행 가(감독자 복구)·나(이중 고장)의 워크스페이스·기록 폴더
        (tmp_path / part).mkdir()
    with launch_sample_game(("--title", title), workdir=tmp_path / "game") as game:
        bring_front(game.hwnd)

        # 가. 누른 채 runner kill → 감독자가 실제 SendInput으로 거꾸로 뗀다 (게임 ACK·OS 상태 각각)
        wall = barrier(tmp_path / "barriers" / "a")
        mark = game.last_seq()
        handle: RunHandle = start_run(
            tmp_path / "a",
            spawned,
            press_graph(game, names),
            runner_cmd=INPUT_RUNNER_CMD,
            platform=windows_platform(names[-1], wall.path),
            plugin_modules=(),
        )
        runner = handle.runner
        assert runner is not None
        wait_wall_or_end(
            wall.is_ready, lambda: runner.wait(0) is not None, lambda: runner_stderr(handle)
        )
        wait_acks(game, "down", names, mark)
        assert os_down(names) == names
        runner.terminate(1)
        assert handle.wait_exit(10) == 1
        outcome = handle.wait(30)
        assert outcome.run_end is not None, runner_stderr(handle)
        assert (outcome.run_end["code"], outcome.run_end["input_recovery"]) == (
            "runner_died",
            "recovered",
        )
        wait_acks(game, "up", names, mark)
        assert acks(game, "up", names, mark) == list(reversed(names))
        wait_until(
            lambda: not os_down(names),
            timeout=ACK_TIMEOUT_S,
            message=lambda: f"OS에서 아직 눌림: {os_down(names)}",
        )
        (recovered,) = [e for e in events(handle) if e["event"] == "input.recovered"]
        assert recovered["by"]["kind"] == "supervisor"

        # 나. 이중 고장 대조: 감독자도 복구 직전에 죽으면 아무도 떼지 않고, 다음 실행이 자기 입력
        # 전에 앞 실행의 입력을 뗀다
        bring_front(game.hwnd)
        wall = barrier(tmp_path / "barriers" / "b")
        finalize = barrier(tmp_path / "barriers" / "before_finalize")
        host = SupervisorHost.make(
            tmp_path / "b",
            press_graph(game, names),
            faults=[
                {
                    "point": "recovery.before_finalize",
                    "role": "supervisor",
                    "action": finalize.action,
                }
            ],
            runner_cmd=INPUT_RUNNER_CMD,
            platform=windows_platform(names[-1], wall.path),
            plugin_modules=(),
        )
        mark = game.last_seq()
        host.start(spawned)
        wait_wall_or_end(
            wall.is_ready,
            lambda: (host.out / "started.json").exists() and host.view().run_end is not None,
            host.stderr,
        )
        wait_acks(game, "down", names, mark)
        a_dir = host.run_dir
        host.kill_runner()
        finalize.wait_ready()
        host.kill()
        time.sleep(1.0)
        assert acks(game, "up", names, mark) == []
        assert os_down(names) == names
        assert not (a_dir / INPUT_RECOVERY_FILE).exists()

        env = {k: v for k, v in host.env.items() if k != "KOOKABUG_FAULTS"}
        bring_front(game.hwnd)
        b_mark = game.last_seq()
        handle = start_run(
            tmp_path / "b",
            spawned,
            press_graph(game, ["b"]),
            env=env,
            runner_cmd=INPUT_RUNNER_CMD,
            platform=windows_platform(),
            plugin_modules=(),
        )
        outcome = handle.wait(30)
        assert outcome.exit_code == 0 and outcome.verdict == "pass", runner_stderr(handle)
        first_b = game.wait_event("key_down", key="b", after=b_mark, timeout=ACK_TIMEOUT_S)
        wait_acks(game, "up", names, b_mark)
        ups = [
            r for r in game.events() if r["seq"] > b_mark and any(is_ack(r, "up", n) for n in names)
        ]
        assert all(r["seq"] < first_b["seq"] for r in ups), (ups, first_b)
        wait_until(lambda: not os_down([*names, "b"]), timeout=ACK_TIMEOUT_S)
        marker = json.loads((a_dir / INPUT_RECOVERY_FILE).read_text(encoding="utf-8"))
        assert marker["recovered_by"] == {"kind": "runner", "run_id": handle.run_id}
        assert read_run(a_dir).status == "interrupted"
