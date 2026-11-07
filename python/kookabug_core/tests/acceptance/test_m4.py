"""M4 완료 기준 (구현 계획 v0 1장, M4 계획 3장 "M4 완료 기준 → 테스트 매핑") 인수 테스트, Python 쪽.

1. 예제 게임 로그인을 녹화한 그래프가 바로 재생 통과 — 가짜 각본(부품 합성 프레임·테두리 있는 버퍼)
   녹화 → 커밋 조각 → 그래프 → 실제 runner(가짜 플랫폼) pass. 느린 전이(200 ms·800 ms)를 녹화하고 더
   느리게 재생해도 pass (검수 M2). 실제 게임·실제 훅은 `desktop_input`
2. 클릭 **이전** 프레임으로 target을 만든다 — 클릭 0.5 ms 뒤 도착한 다음 장면이 아니라 앞 장면에서
   자르고, 마우스를 올리면 바뀌는 단추는 커서가 들어오기 전 프레임에서 자른다. 앞 프레임이 없거나
   기하가 불확실하면 뒤 프레임으로 대신하지 않는다 (검수 H3)
3. 툴 자신이 보낸 합성 입력은 녹화하지 않는다 — 우리 표식·다른 프로그램 입력은 스텝이 없고 같은
   각본의 사람 입력은 스텝이 있다(양성 대조). 녹화 중 실행은 `recording_active`(`starting` 포함)·
   `input_lease_busy`로 거부
4. 비밀번호 칸 입력은 글자 그대로 저장하지 않고 `$secret` 참조를 요구 — 판정 중·커밋 거부·키 고름,
   녹화 데이터에 원문 없음. 재생 `runs/`는 D3대로(기본 원문 있음, `redact_secrets`면 없음) — 녹화와
   별개
(2.13) 하위 층 `video: on` 경고

daemon은 같은 프로세스(`ThreadDaemon`), 녹화 원천은 가짜 각본(`kb_testing.recorder_scripts`)을 가짜
훅 원천(실제 훅 프로세스와 같은 번호 규칙)과 가짜 사람·가짜 게임 장면으로 흘린다. 판정·이름은 실제
OCR이다. 다른 테스트 모듈을 import하지 않는다. 자세한 경우는 근거 테스트에 있다
(`kookabug_daemon/tests/test_recorder_*.py`, `kookabug_platform/tests/test_recorder_*.py`,
`tests/recorder/*`). 사람의 물리 입력은 `Docs/verification/m4-manual.md`다.
"""

from __future__ import annotations

import ctypes
import json
import logging
import queue
import shutil
import threading
import time
from collections.abc import Iterator
from ctypes import wintypes
from pathlib import Path
from typing import Any, Final

import cv2
import numpy as np
import pytest
from helpers.cli import cli_env
from helpers.graphs import GraphBuilder, check, make_workspace
from helpers.recorder_rig import (
    HOTKEYS,
    SECRET_KEY,
    RecorderRig,
    graph_from_fragment,
    run_graph,
    steps_of,
)
from helpers.run import tk
from helpers.runner import RUNNER_CMD, RunnerHarness, step_of

from kb_testing.daemon import ThreadDaemon
from kb_testing.proc import Spawned, wait_until
from kb_testing.recorder_scripts import (
    ACCOUNT,
    ACCOUNT_POINT,
    GEOMETRY,
    LOGIN_POINT,
    PASSWORD,
    START_POINT,
    ScriptBuilder,
    char_vk,
    login_script,
)
from kb_testing.sample_game import EXAMPLE_SECRET_ENV, FRAMES_DIR, copy_example_workspace
from kookabug_core.service import WorkspaceService
from kookabug_core.supervisor import Supervisor
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder import default_read_text
from kookabug_daemon.recorder_lease import RecorderLease
from kookabug_daemon.recorder_sources import FakeRecording
from kookabug_daemon.recorder_store import recorder_cache_dir
from kookabug_platform.frames import decode_image
from kookabug_platform.recorder.frames import RingPolicy, Unresolved, pre_click
from kookabug_platform.recorder.geometry import Geometry
from kookabug_platform.recorder.scripted_frames import ScriptFrameSource, png_scenes
from kookabug_platform.vision import FrameMeta, Vision, load_target_file

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

MS: Final = 1_000_000
START: Final = {"launch": {}, "hotkeys": HOTKEYS}
GRAPH: Final = "tests/rec_m4.graph.json"
LOBBY_TITLE: Final = [412, 90, 200, 60]
"""로비 화면 "서버 선택" 제목 자리 (화면 확인 영역)."""
START_BUTTON: Final = (412, 380, 200, 64)
PIECES: Final = (PASSWORD, "pass-01", "pass-0")
"""원문과 쉬었다 친 뒤 조각 (`sample-`는 경로·창 제목의 `sample`과 겹쳐 따로 보지 않는다)."""


# ---------------------------------------------------------------- 도우미


@pytest.fixture
def secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """daemon 사전 검증은 daemon 프로세스 환경에서 비밀값을 찾는다 (runner는 rig 환경)."""
    for name, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(name, value)


def refused(client: DaemonClient, method: str, params: dict[str, Any] | None = None) -> DaemonError:
    with pytest.raises(DaemonError) as caught:
        client.call(method, params or {})
    return caught.value


def drafts(rig: RecorderRig) -> RecorderRig:
    """워크스페이스 target·그래프를 지운 사본: 모든 클릭이 새 초안 (커밋이 target 파일을 쓴다)."""
    for folder in ("targets", "subgraphs", "tests"):
        shutil.rmtree(rig.root / folder)
    return rig


def frames_dir(rig: RecorderRig) -> Path:
    """사본의 장면 PNG·장면 표 (`fake-platform.json`의 `../frames/scenario.json`)."""
    return rig.root.parent / "frames"


def add_scenes(rig: RecorderRig, images: dict[str, np.ndarray], transitions: list[Any]) -> None:
    folder = frames_dir(rig)
    spec = json.loads((folder / "scenario.json").read_text(encoding="utf-8-sig"))
    for name, image in images.items():
        ok, data = cv2.imencode(".png", image)
        assert ok
        (folder / f"{name}.png").write_bytes(data.tobytes())
        spec["scenes"][name] = f"{name}.png"

    def key(t: dict[str, Any]) -> str:
        return json.dumps([t["from"], t.get("on"), t.get("when")], sort_keys=True)

    # 같은 입력에 맞는 원래 전이는 뺀다 (둘이면 장면 표가 모호하다고 거부)
    replaced = {key(t) for t in transitions if t.get("on")}
    kept = [t for t in spec["transitions"] if key(t) not in replaced]
    spec["transitions"] = [*transitions, *kept]
    (folder / "scenario.json").write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")


def scene_png(name: str) -> np.ndarray:
    data = np.frombuffer((FRAMES_DIR / f"{name}.png").read_bytes(), np.uint8)
    return np.asarray(cv2.imdecode(data, cv2.IMREAD_COLOR), dtype=np.uint8)


def scene_line(s: ScriptBuilder, at_ms: float, scene: str) -> None:
    s.lines.append({"kind": "scene", "t_ns": int(at_ms * MS), "scene": scene})


def human_click_at(s: ScriptBuilder, at_ms: float, point: tuple[int, int]) -> int:
    """이동 → 120 ms 뒤 누름. 누른 시각(ns)을 돌려준다 (떼기는 부르는 쪽이)."""
    s.at(at_ms).move(point).wait(120)
    x, y = s.screen(point)
    s.raw(kind="mouse_down", x=x, y=y, button="left")
    return s.t


def release(s: ScriptBuilder, at_ns: int, point: tuple[int, int]) -> None:
    s.t = at_ns
    x, y = s.screen(point)
    s.raw(kind="mouse_up", x=x, y=y, button="left")


def written_png(rig: RecorderRig, target_rel: str) -> np.ndarray:
    spec = json.loads((rig.root / target_rel).read_text(encoding="utf-8"))
    return decode_image(((rig.root / target_rel).parent / spec["image"]).read_bytes())


def find_click(target_path: Path, scene: np.ndarray) -> tuple[int, int] | None:
    target = load_target_file(target_path)
    found = Vision().find(np.ascontiguousarray(scene), FrameMeta.of_image(scene), target)
    return None if found.match is None else tuple(found.match.click)  # pyright: ignore[reportReturnType]


def wait_recorded(ui: DaemonClient, count: int = 6) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def check_steps() -> bool:
        found[:] = [s for s in steps_of(ui) if s["kind"] not in ("wait", "delay")]
        return len(found) >= count

    wait_until(check_steps, timeout=60, interval=0.1)
    return found


def insert_lobby_check(ui: DaemonClient) -> None:
    live = ui.call("recorder.frame", {"which": "live"})
    ui.call(
        "recorder.insert_check",
        {"kind": "visible", "frame_id": live["frame"]["frame_id"], "rect": LOBBY_TITLE},
    )


def choose_secret(ui: DaemonClient) -> dict[str, Any]:
    secret = next(s for s in steps_of(ui) if s.get("text_state") == "secret")
    ui.call("recorder.step.update", {"step": secret["step"], "patch": {"secret_key": SECRET_KEY}})
    return secret


def commit_new_test(ui: DaemonClient, graph_path: str = GRAPH) -> dict[str, Any]:
    return ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": graph_path})


def lease_free(rig: RecorderRig) -> bool:
    lease = RecorderLease(rig.root, environ=rig.env)
    try:
        lease.acquire()
    except RequestFailed:
        return False
    lease.release()
    return True


def assert_no_raw(where: str, data: bytes | str) -> None:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    for piece in PIECES:
        for encoded in (piece.encode("utf-8"), piece.encode("utf-16-le")):
            assert encoded not in raw, f"{where}에 비밀번호 원문({piece!r})이 있다"


def drain(client: DaemonClient) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    while True:
        try:
            found.append(client.notifications.get_nowait())
        except queue.Empty:
            return found


def run_events(root: Path, ended: dict[str, Any]) -> str:
    return (root / ended["run_dir"] / "events.jsonl").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 1. 녹화 → 바로 재생


@pytest.mark.usefixtures("secret_env")
def test_recorded_login_fragment_replays_pass(tmp_path: Path) -> None:
    """타이틀 → 시작 클릭 → 계정 칸 클릭·글자 → Tab → 쉬었다 이어 친 비밀번호 → 로그인 클릭 → 화면
    확인(로비) → 커밋 → 그래프(게임 띄우기 노드부터) → 실제 runner 가짜 플랫폼 pass (고른 비밀값으로
    `when.valid` 통과, 로비 검증 노드 pass)."""
    rig = RecorderRig.make(tmp_path, login_script(split=True))
    with rig.daemon() as d, d.client() as ui:
        assert ui.call("recorder.start", START)["state"] == "recording"
        steps = wait_recorded(ui)
        assert [s["kind"] for s in steps] == ["click", "click", "text", "key", "text", "click"]
        insert_lobby_check(ui)
        ui.call("recorder.stop", {})
        choose_secret(ui)
        prepared = commit_new_test(ui)
        nodes = prepared["fragment"]["nodes"]
        types = [n["type"] for n in nodes]
        assert types[0] == "core.app.launch", types  # 게임 띄우기 노드부터
        assert types[-1] == "core.assert.visible" and "core.test.pass" not in types
        assert types.count("core.image.click") == 3
        graph = graph_from_fragment(prepared["fragment"])
        ended = run_graph(ui, rig.root, GRAPH, graph)
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        assert ui.call("recorder.state", {})["state"] == "committed"
    # 재생이 실제로 로그인했다: 로비 검증 노드가 ok
    check_id = next(i for i, n in graph["nodes"].items() if n["type"] == "core.assert.visible")
    events = [json.loads(line) for line in run_events(rig.root, ended).splitlines() if line]
    _, end = step_of(events, check_id)
    assert end is not None and end.get("exit") == "ok", end


@pytest.mark.usefixtures("secret_env")
def test_delayed_transition_replay_waits(tmp_path: Path) -> None:
    """시작 클릭 뒤 200 ms, 로그인 클릭 뒤 800 ms 걸려 바뀌는 화면을 녹화하고, 재생에서는 그 전이가
    캡처 몇 장 뒤에야 끝나도(느린 재생) 다음 입력이 목표 화면이 된 뒤에 나가 pass (검수 M2)."""
    rig = RecorderRig.make(tmp_path, [])
    loading = scene_png("loading")
    slow = 6  # 재생: 전이가 캡처 6장 뒤 (녹화의 0.2·0.8초보다 느리다)
    start_click = {"kind": "click", "rect": list(START_BUTTON)}
    login_click = {"kind": "click", "rect": [432, 380, 160, 56]}
    valid = {"form": "login", "valid": True}
    add_scenes(
        rig,
        {"boot": loading, "connecting": loading},
        [
            {"after_frames": 0, "from": "title", "on": start_click, "to": "boot",
             "variants": ["default"]},
            {"after_frames": slow, "from": "boot", "to": "login"},
            {"after_frames": 0, "from": "login", "on": login_click, "to": "connecting",
             "variants": ["default"], "when": valid},
            {"after_frames": slow, "from": "connecting", "to": "lobby"},
        ],
    )  # fmt: skip
    s = ScriptBuilder()
    s.at(500).click(START_POINT)  # 떼기 660 ms → boot
    scene_line(s, 860, "login")  # 200 ms 뒤 저절로
    s.at(1500).click(ACCOUNT_POINT)
    s.at(2000).type(ACCOUNT)
    s.wait(300).key("tab")
    s.wait(500).type(PASSWORD)
    s.wait(600).click(LOGIN_POINT)
    up = s.t / MS
    scene_line(s, up + 800, "lobby")  # 800 ms 뒤 저절로
    s.at(up + 1500).mark("lobby")
    rig.script.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in s.lines), encoding="utf-8"
    )
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        all_steps: list[dict[str, Any]] = []

        def recorded() -> bool:
            all_steps[:] = steps_of(ui)
            return sum(st["kind"] not in ("wait", "delay") for st in all_steps) >= 6

        wait_until(recorded, timeout=60, interval=0.1)
        insert_lobby_check(ui)
        ui.call("recorder.stop", {})
        choose_secret(ui)
        prepared = commit_new_test(ui)
        graph = graph_from_fragment(prepared["fragment"])
        ended = run_graph(ui, rig.root, GRAPH, graph)
        assert ended["outcome"]["verdict"] == "pass", (ended, [st["kind"] for st in all_steps])
        ui.call("recorder.commit_abort", {"token": prepared["token"]})


# ---------------------------------------------------------------- 2. 클릭 이전 프레임


def test_target_cropped_from_frame_before_click(tmp_path: Path) -> None:
    """클릭 누름 0.5 ms 뒤 다음 장면(로그인) 프레임이 도착해도 target은 앞 장면(타이틀)에서 자른다:
    저장된 target PNG = 타이틀 클라이언트 그 자리, 다음 장면에는 그 무늬가 없음, 재생 클릭 점 = 녹화
    클릭 점. 버퍼는 테두리·제목 표시줄이 있는 창 프레임 전체다."""
    s = ScriptBuilder()
    down = human_click_at(s, 500, START_POINT)
    scene_line(s, down / MS + 0.1, "login")
    s.lines.append({"kind": "frame", "arrival_ns": down + MS // 2})
    release(s, down + 40 * MS, START_POINT)
    s.wait(400).mark("done")
    rig = drafts(RecorderRig.make(tmp_path, s.lines))
    assert GEOMETRY["frame_bounds"][2:] != GEOMETRY["client_size"]  # 테두리 있는 버퍼
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        (click,) = wait_recorded(ui, 1)
        ui.call("recorder.stop", {})
        click = next(st for st in steps_of(ui) if st["kind"] == "click")
        assert click["target"]["source"] == "draft", click
        assert click["target"]["frame"] == "pre_click"
        x, y, w, h = click["target"]["spec"]["rect"]
        prepared = commit_new_test(ui)
        (written,) = prepared["targets"]
        png = written_png(rig, written["path"])
        title, login = scene_png("title"), scene_png("login")
        assert png.shape == (h, w, 3)
        assert np.array_equal(png, title[y : y + h, x : x + w]), "앞 장면(타이틀)에서 자르지 않았다"
        assert find_click(rig.root / written["path"], login) is None  # 다음 장면에는 없는 무늬
        assert find_click(rig.root / written["path"], title) == START_POINT
        ui.call("recorder.commit_abort", {"token": prepared["token"]})


def test_hover_state_avoided_with_pre_enter_frame(tmp_path: Path) -> None:
    """마우스를 올리면 밝아지는 시작 단추: 클릭 직전 프레임은 올린 모양이지만 target은 커서가
    들어오기 전 프레임(`pre_hover`)에서 자른다 — 올린 모양이 없는 재생 화면에서 찾힌다."""
    rig = RecorderRig.make(tmp_path, [])
    hover = scene_png("title").copy()
    x0, y0, w0, h0 = START_BUTTON
    patch = hover[y0 : y0 + h0, x0 : x0 + w0].astype(np.int16) + 70
    hover[y0 : y0 + h0, x0 : x0 + w0] = np.clip(patch, 0, 255).astype(np.uint8)
    add_scenes(rig, {"title_hover": hover}, [])
    s = ScriptBuilder()
    s.at(300).move((120, 120))  # 단추 밖
    down = human_click_at(s, 500, START_POINT)  # 500 ms에 단추 안으로
    scene_line(s, 501, "title_hover")  # 게임이 올린 모양으로 (프레임 517 ms < 누름 620 ms)
    s.lines.sort(key=lambda line: int(line.get("t_ns", -1)))
    release(s, down + 40 * MS, START_POINT)
    s.wait(400).mark("done")
    rig.script.write_text(
        "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in s.lines), encoding="utf-8"
    )
    drafts(rig)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_recorded(ui, 1)
        ui.call("recorder.stop", {})
        click = next(st for st in steps_of(ui) if st["kind"] == "click")
        assert click["target"]["frame"] == "pre_hover", click
        assert "hover_maybe" not in [b["code"] for b in click["badges"]]
        x, y, w, h = click["target"]["spec"]["rect"]
        prepared = commit_new_test(ui)
        (written,) = prepared["targets"]
        png = written_png(rig, written["path"])
        assert np.array_equal(png, scene_png("title")[y : y + h, x : x + w])
        assert not np.array_equal(png, hover[y : y + h, x : x + w])
        assert find_click(rig.root / written["path"], scene_png("title")) == START_POINT
        ui.call("recorder.commit_abort", {"token": prepared["token"]})


def test_no_pre_frame_or_geometry_mismatch_not_backfilled(tmp_path: Path) -> None:
    """(a) 창 크기가 클릭 직전에 바뀌고 알림이 늦음 → 클릭 앞 프레임과 입력의 기하가 맞지 않아
    `geometry_unresolved`, 클릭 뒤에 온 새 크기 프레임으로 대신 자르지 않는다. (b) 처리가 늦어 앞
    프레임이 링에서 밀려남 → `no_frame`, 뒤 프레임으로 대신하지 않는다."""
    s = ScriptBuilder()
    down = human_click_at(s, 500, START_POINT)
    left, top = GEOMETRY["frame_bounds"][:2]
    smaller = {
        "frame_bounds": [left, top, 962, 632],
        "client_origin": list(GEOMETRY["client_origin"]),
        "client_size": [960, 600],
        "dpi": 96,
    }
    s.lines.insert(
        len(s.lines) - 1,
        {"kind": "geometry", "t_ns": down - MS // 10, "notify_ns": down + 80 * MS,
         "geometry": smaller},
    )  # fmt: skip
    release(s, down + 40 * MS, START_POINT)
    s.wait(600).mark("done")
    rig = drafts(RecorderRig.make(tmp_path, s.lines))
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_recorded(ui, 1)
        ui.call("recorder.stop", {})
        click = next(st for st in steps_of(ui) if st["kind"] == "click")
        assert "geometry_unresolved" in click["needs_review"], click
        assert click["target"] == {"source": "none"}, click
        assert "point" not in click["input"], click  # 클라이언트 점도 소급해 정하지 않는다
        ui.call("recorder.discard", {})
    # (b) 링 단위: 클릭 앞 프레임이 밀려나면 뒤 장면 프레임을 주지 않는다
    g = Geometry.of_json(GEOMETRY)
    src = ScriptFrameSource(
        g, "title", png_scenes(FRAMES_DIR), policy=RingPolicy(max_age_ns=2500 * MS)
    )
    for i in range(1, 8):
        src.schedule_scene(i * 1000 * MS, "login" if i % 2 else "lobby")
    src.advance_to(8000 * MS)
    got = pre_click(src.ring, src.geometry, 500 * MS, g.to_screen(START_POINT))
    assert got == Unresolved("no_frame")


# ---------------------------------------------------------------- 3. 합성 입력·실행 거부


def test_product_marked_and_injected_inputs_not_recorded(tmp_path: Path) -> None:
    """우리 표식(`KOOKABUG_INPUT_MARK`) 클릭·키와 다른 프로그램의 `INJECTED` 키, 합쳐진 이동이 섞인
    각본: 그 입력은 스텝이 없고 개수만(우리 표식은 훅 프로세스에서 빠져 세지도 않음), 같은 각본의
    사람 입력은 스텝이 있다(양성 대조). `input_overflow` 없음 (2차 N1)."""
    from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK

    ours = {"injected": True, "extra_info": KOOKABUG_INPUT_MARK}
    macro = {"injected": True, "extra_info": 0}
    s = ScriptBuilder()
    s.at(500).click(START_POINT, **ours)  # 실행이 보낸 클릭 (게임은 로그인 화면으로)
    s.at(1000).type("zz", **ours)
    for i in range(300):  # 사람 이동이 합쳐지는 구간
        s.at(1300 + i).move((100 + i, 500))
    s.at(1700).type("mm", **macro)  # 다른 프로그램(매크로)
    s.at(2200).click(ACCOUNT_POINT)  # 사람
    s.at(2600).type("ab")
    s.wait(300).key("tab")
    s.wait(400).mark("done")
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        steps = wait_recorded(ui, 3)
        ui.call("recorder.stop", {})
        state = ui.call("recorder.state", {})
        assert state["stop_reason"] == "user", state
        steps = [st for st in steps_of(ui) if st["kind"] not in ("wait", "delay")]
        assert [st["kind"] for st in steps] == ["click", "text", "key"], steps
        assert steps[1]["text_len"] == 2
        assert state["counts"]["ignored_injected"] == 4  # 매크로 "mm" 누름·뗌 (우리 입력은 0)
        assert any(w["code"] == "injected_ignored" for w in state.get("warnings", [])), state
        ui.call("recorder.discard", {})


def test_runs_rejected_while_recording(
    tmp_path: Path, spawned: Spawned, monkeypatch: pytest.MonkeyPatch
) -> None:
    """같은 daemon의 실행은 `recording_active`(시작 중 `starting` 포함), 다른 runner(같은 임대권)는
    `input_lease_busy`. 정지하면 다시 실행할 수 있다."""
    entered, go = threading.Event(), threading.Event()
    original = FakeRecording.start_frames

    def slow(self: FakeRecording) -> None:
        entered.set()
        go.wait(20)
        original(self)

    monkeypatch.setattr(FakeRecording, "start_frames", slow)
    rig = RecorderRig.make(tmp_path)
    plain = (
        GraphBuilder()
        .entry("n_log")
        .node("n_log", "core.log.message", inputs={"text": "하나"}, next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    held = (
        tk()
        .entry("n_key")
        .node("n_key", "testkit.input.hold", next={"done": "n_pass"})
        .node("n_pass", "core.test.pass")
    )
    with rig.daemon() as d, d.client() as ui, d.client() as other:
        plain.write(rig.root, "tests/plain.graph.json")
        ui.request("recorder.start", START)
        assert entered.wait(20)
        error = refused(other, "run.start", {"path": "tests/plain.graph.json"})
        assert (error.kind, error.data["state"]) == ("recording_active", "starting")
        go.set()
        wait_until(lambda: ui.call("recorder.state", {})["state"] == "recording", timeout=30)
        error = refused(other, "run.start", {"path": "tests/plain.graph.json"})
        assert (error.kind, error.data["state"]) == ("recording_active", "recording")
        h = RunnerHarness.make(
            tmp_path / "other",
            held,
            lease_name=rig.env["KOOKABUG_INPUT_LEASE_NAME"],
            state_dir=Path(rig.env["KOOKABUG_STATE_DIR"]),
        ).start(spawned)
        done = h.finish()
        assert done.run_end is not None and done.run_end["code"] == "input_lease_busy"
        ui.call("recorder.stop", {})
        assert lease_free(rig)
        started = other.call("run.start", {"path": "tests/plain.graph.json"})
        wait_until(
            lambda: other.call("run.status", {"run_id": started["run_id"]})["state"] == "ended",
            timeout=60,
        )
        ui.call("recorder.discard", {})


# ---------------------------------------------------------------- 4. 비밀값


@pytest.mark.usefixtures("secret_env")
def test_password_step_requires_secret_and_absent_from_recording_data(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """판정 중 `steps`에 원문 없음·커밋 `classification_pending` → 판정 뒤 `secret_unresolved` → 키
    고름 → 그래프 `{"$secret": …}` 한 번·`clear: true`. 녹화 구조화 데이터(RPC 결과·알림·세션
    `steps.json`)·그래프·target JSON·파일 이름·노드 제목·daemon 로그에 원문 바이트가 없고 target PNG
    OCR에도 없다. 재생 `runs/`는 대상이 아니다(아래 D3 검사)."""
    caplog.set_level(logging.DEBUG)
    rig = drafts(RecorderRig.make(tmp_path, login_script(split=True, backspace=True)))
    seen: list[Any] = []
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        session = d.daemon.recorder.session
        assert session is not None and session.pipeline is not None
        pipeline: Any = session.pipeline
        pipeline._classify = lambda: False  # 판정이 늦다 (OCR이 아직)
        rig.advance(d, 12000)
        steps = steps_of(ui)
        seen.append(steps)
        texts = [st for st in steps if st["kind"] == "text"]
        assert [st["text_state"] for st in texts] == ["pending", "pending"], texts
        assert all("text" not in st for st in texts)
        error = refused(ui, "recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert error.kind == "classification_pending"
        assert texts[1]["step"] in error.data["steps"]
        del pipeline._classify  # 판정 재료가 옴
        error = refused(ui, "recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        steps = steps_of(ui)
        seen.append(steps)
        secret = next(st for st in steps if st.get("text_state") == "secret")
        assert (error.kind, error.data["steps"]) == ("secret_unresolved", [secret["step"]])
        assert secret["text_len"] == len(PASSWORD) and "text" not in secret
        assert session.store is not None
        stored = (session.store.folder / "steps.json").read_bytes()
        choose_secret(ui)
        prepared = commit_new_test(ui)
        seen.append(prepared)
        secret_nodes = [
            n
            for n in prepared["fragment"]["nodes"]
            if n["in"].get("text") == {"$secret": SECRET_KEY}
        ]
        assert len(secret_nodes) == 1 and secret_nodes[0]["in"]["clear"] is True
        graph = graph_from_fragment(prepared["fragment"])
        (rig.root / GRAPH).parent.mkdir(parents=True, exist_ok=True)
        (rig.root / GRAPH).write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        seen.extend(drain(ui))
    assert_no_raw("recorder RPC 결과·알림", json.dumps(seen, ensure_ascii=False))
    assert_no_raw("세션 steps.json", stored)
    # Kookabug 로그만 (websockets DEBUG 프레임 덤프는 사람 연결 알림 그대로 — daemon은 그 로거를
    # WARNING으로 둔다, 알림 도착 시점에 따라 섞인다)
    assert_no_raw(
        "daemon 로그",
        "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("kookabug")),
    )
    graph_bytes = (rig.root / GRAPH).read_bytes()
    assert_no_raw("그래프 파일", graph_bytes)
    assert ACCOUNT.encode() in graph_bytes and SECRET_KEY.encode() in graph_bytes
    titles = [n.get("title", "") for n in graph["nodes"].values()]
    assert_no_raw("노드 제목", json.dumps(titles, ensure_ascii=False))
    files = sorted((rig.root / "targets").rglob("*"))
    assert any(p.name.endswith(".target.json") for p in files)
    read = default_read_text()
    assert read is not None, "OCR 모델이 없다"
    for path in files:
        assert_no_raw("target 파일 이름", path.name)
        if path.suffix == ".json":
            assert_no_raw(f"target {path.name}", path.read_bytes())
        if path.suffix == ".png":
            image = decode_image(path.read_bytes())
            text = read(image, (0, 0, int(image.shape[1]), int(image.shape[0]))) or ""
            assert_no_raw(f"target PNG OCR {path.name}", text)
    # 커밋 뒤 녹화 임시 화면(D3 예외)은 지워졌다
    folder = recorder_cache_dir(rig.root)
    assert not folder.is_dir() or not any(folder.iterdir())


@pytest.mark.usefixtures("secret_env")
def test_split_password_secret_span_and_login(tmp_path: Path) -> None:
    """비밀번호를 쉬었다 이어 치고 Backspace로 고친 뒤 바로 Enter: 구간 하나가 비밀값 스텝 하나가
    되고, 고른 비밀값으로 재생이 로그인에 성공한다(로비 확인 pass)."""
    s = ScriptBuilder()
    s.at(500).click(START_POINT)
    s.at(1500).click(ACCOUNT_POINT)
    s.at(2000).type(ACCOUNT)
    s.wait(300).key("tab")
    s.wait(500).type("sample-").wait(3000).type("pass-0")
    s.type("9").wait(200).key("backspace").wait(150).type("1")
    s.wait(30).key("enter")  # 마지막 글자 바로 뒤 — 칸이 사라진다
    s.wait(1200).mark("lobby")
    rig = RecorderRig.make(tmp_path, s.lines)
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_recorded(ui, 6)  # Enter 스텝까지 (확인은 열린 끝에 들어간다)
        insert_lobby_check(ui)
        ui.call("recorder.stop", {})
        steps = [st for st in steps_of(ui) if st["kind"] not in ("wait", "delay")]
        assert [st["kind"] for st in steps] == [
            "click", "click", "text", "key", "text", "key", "check_visible",
        ], steps  # fmt: skip
        texts = [st for st in steps if st["kind"] == "text"]
        assert texts[0]["text_state"] == "ordinary" and texts[0]["text"] == ACCOUNT
        assert texts[1]["text_state"] == "secret" and texts[1]["text_len"] == len(PASSWORD)
        choose_secret(ui)
        prepared = commit_new_test(ui)
        graph = graph_from_fragment(prepared["fragment"])
        ended = run_graph(ui, rig.root, GRAPH, graph)
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})


@pytest.mark.usefixtures("secret_env")
def test_replay_runs_follow_d3(tmp_path: Path) -> None:
    """녹화한 그래프의 재생 `runs/`는 D3: 기본은 비밀값을 받은 스텝도 영상에 남고(빈 구간 없음),
    워크스페이스 `record.redact_secrets: true`면 그 스텝이 영상의 `secret_input` 빈 구간이다.
    녹화 데이터의 원문 부재 검사와는 따로다 (검수 M7). 녹화 그래프의 글자 입력 노드는 비밀값을
    출력·로그에 싣지 않아 이벤트에는 어느 쪽이든 원문이 없다 — 원문이 남을 수 있는 곳은
    화면(영상·스크린샷)이다."""
    rig = RecorderRig.make(tmp_path, login_script(), KOOKABUG_VIDEO_TEST='{"encoder": "fake"}')
    set_record(rig, {"video": "on"})
    with rig.daemon() as d, d.client() as ui:
        ui.call("recorder.start", START)
        wait_recorded(ui)
        insert_lobby_check(ui)
        ui.call("recorder.stop", {})
        choose_secret(ui)
        prepared = commit_new_test(ui)
        graph = graph_from_fragment(prepared["fragment"])
        assert_no_raw("녹화 그래프", json.dumps(graph, ensure_ascii=False))
        ended = run_graph(ui, rig.root, GRAPH, graph)
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
    secret_node = next(
        i
        for i, n in graph["nodes"].items()
        if n.get("in", {}).get("text") == {"$secret": SECRET_KEY}
    )
    plain = video_gaps(rig.root, ended)
    assert [g for g in plain if g["gap"] == "secret_input"] == [], plain
    set_record(rig, {"video": "on", "redact_secrets": True})
    with rig.daemon() as d, d.client() as ui:
        redacted = run_graph(ui, rig.root, GRAPH, graph)
    assert redacted["outcome"]["verdict"] == "pass", redacted
    events = [json.loads(line) for line in run_events(rig.root, redacted).splitlines() if line]
    start, _ = step_of(events, secret_node)
    assert start is not None
    gaps = [g for g in video_gaps(rig.root, redacted) if g["gap"] == "secret_input"]
    assert [g.get("step") for g in gaps] == [start["step"]], gaps
    for run in (ended, redacted):
        assert_no_raw("재생 이벤트", run_events(rig.root, run))


def set_record(rig: RecorderRig, record: dict[str, Any]) -> None:
    path = rig.root / "kookabug.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["record"] = record
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")


def video_gaps(root: Path, ended: dict[str, Any]) -> list[dict[str, Any]]:
    index = root / ended["run_dir"] / "video" / "index.json"
    return list(json.loads(index.read_text(encoding="utf-8"))["gaps"])


# ---------------------------------------------------------------- 2.13 video: on 경고


def test_video_on_under_failed_only_warns(tmp_path: Path) -> None:
    """워크스페이스 기본(`failed_only`) 아래 테스트·노드 층의 `video: "on"`은 효과가 없다는 경고
    (`video_on_ineffective`, 이긴 층 이름). 워크스페이스가 `on`이면 경고 없음."""
    ws = make_workspace(tmp_path / "a")
    test = "tests/t.graph.json"
    GraphBuilder(record={"video": "on"}).entry("n").node(
        "n", "core.test.pass", record={"video": "on"}
    ).write(ws, test)
    found = [d for d in check(ws, test) if d.code == "video_on_ineffective"]
    assert sorted(d.pointer or "" for d in found) == ["/nodes/n/record/video", "/record/video"]
    assert all(d.severity == "warning" and "failed_only" in d.message for d in found)
    on = make_workspace(tmp_path / "b", record={"video": "on"})
    GraphBuilder(record={"video": "on"}).entry("n").node("n", "core.test.pass").write(on, test)
    assert not [d for d in check(on, test) if d.code == "video_on_ineffective"]


# ---------------------------------------------------------------- desktop_input (개발자 PC)
# 조율자가 잠금 해제 데스크톱에서 직렬로 돌린다
# (KOOKABUG_DESKTOP_TESTS=require KOOKABUG_DESKTOP_INPUT=1).
# "사람" 입력은 검사 표식을 실은 SendInput이고, 같은 녹화에서 그 입력이 녹화되어야 "우리 입력 0"이
# 의미가 있다(양성 대조). 물리 입력·IME 실제 조합·지연 체감은 사람 확인(m4-manual)이다.

TEST_MARK: Final = 0x7E57_0001
VK_TAB: Final = 0x09
VK_SHIFT: Final = 0xA0
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_SetCursorPos = _user32.SetCursorPos
_SetCursorPos.restype = wintypes.BOOL
_SetCursorPos.argtypes = (ctypes.c_int, ctypes.c_int)


def _live_click(hwnd: int, point: tuple[int, int], extra: int = TEST_MARK) -> None:
    from kb_testing.keys import button_input, send_inputs
    from kookabug_platform.dpi import per_monitor_v2_thread
    from kookabug_platform.windows import window_info

    with per_monitor_v2_thread():
        origin = window_info(hwnd).client_origin
        _SetCursorPos(origin[0] + point[0], origin[1] + point[1])
    time.sleep(0.15)
    send_inputs(button_input("mouse:left", extra_info=extra))
    time.sleep(0.05)
    send_inputs(button_input("mouse:left", up=True, extra_info=extra))
    time.sleep(0.3)


def _live_tap(vk: int, extra: int = TEST_MARK) -> None:
    from kb_testing.keys import key_input, send_inputs

    send_inputs(key_input(vk, extra_info=extra))
    time.sleep(0.03)
    send_inputs(key_input(vk, up=True, extra_info=extra))
    time.sleep(0.06)


def _live_type(text: str) -> None:
    from kb_testing.keys import key_input, send_inputs

    for ch in text:
        vk, shift = char_vk(ch)
        if shift:
            send_inputs(key_input(VK_SHIFT, extra_info=TEST_MARK))
        _live_tap(vk)
        if shift:
            send_inputs(key_input(VK_SHIFT, up=True, extra_info=TEST_MARK))


@pytest.fixture
def live_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    from kb_testing.keys import release_all_for_test
    from kb_testing.sample_game import post_close
    from kookabug_platform.windows import find_windows

    for name, value in EXAMPLE_SECRET_ENV.items():
        monkeypatch.setenv(name, value)
    root = copy_example_workspace(tmp_path / "example")
    yield root
    release_all_for_test()
    for hwnd in find_windows(title="SampleRPG"):
        post_close(hwnd)


def _live_daemon(root: Path, tmp_path: Path) -> ThreadDaemon:
    from kookabug_daemon.recorder_hook import HookTesting

    env = cli_env(tmp_path, None, **EXAMPLE_SECRET_ENV)
    service = WorkspaceService(
        root, environ=env, supervisor=Supervisor(runner_cmd=RUNNER_CMD, env=env)
    )
    return ThreadDaemon(
        root, service=service, recorder_testing=HookTesting(accept_extra_info=TEST_MARK)
    )


@pytest.mark.desktop_input
@pytest.mark.timeout(600)
def test_recorded_login_live_replays_pass(live_ws: Path, tmp_path: Path) -> None:
    """실제 예제 게임·실제 훅·검사 표식 입력으로 로그인 녹화 → 커밋 → 녹화 창은 로비에 둔 채 재생은
    새로 띄운 게임(다른 PID·창)에서 실제 SendInput으로 로비 검증 pass."""
    from kookabug_platform.windows import activate, window_info

    with _live_daemon(live_ws, tmp_path) as d, d.client() as ui:
        started = ui.call("recorder.start", START)
        hwnd = started["window"]["handle"]
        recorded_pid = window_info(hwnd).pid
        activate(hwnd)
        time.sleep(0.5)
        _live_click(hwnd, START_POINT)
        time.sleep(0.8)
        _live_click(hwnd, ACCOUNT_POINT)
        _live_type(ACCOUNT)
        _live_tap(VK_TAB)
        _live_type(PASSWORD[:7])
        time.sleep(3.0)
        _live_type(PASSWORD[7:])
        time.sleep(0.6)
        _live_click(hwnd, LOGIN_POINT)
        time.sleep(1.5)
        insert_lobby_check(ui)
        ui.call("recorder.stop", {})
        assert ui.call("recorder.state", {})["stop_reason"] == "user"
        choose_secret(ui)
        prepared = commit_new_test(ui, "tests/rec_live_m4.graph.json")
        graph = graph_from_fragment(prepared["fragment"])
        ended = run_graph(ui, live_ws, "tests/rec_live_m4.graph.json", graph, 180)
        assert ended["outcome"]["verdict"] == "pass", ended
        ui.call(
            "recorder.commit_finish",
            {"token": prepared["token"], "graph_path": "tests/rec_live_m4.graph.json"},
        )
    launch_id = next(i for i, n in graph["nodes"].items() if n["type"] == "core.app.launch")
    events = [json.loads(line) for line in run_events(live_ws, ended).splitlines() if line]
    _, end = step_of(events, launch_id)
    assert end is not None and end["outputs"]["window"]["handle"] != hwnd
    assert end["outputs"]["process"]["pid"] != recorded_pid


@pytest.mark.desktop_input
@pytest.mark.timeout(600)
def test_pre_click_frame_live(live_ws: Path, tmp_path: Path) -> None:
    """예제 게임 `--press-feedback`(누르는 동안 단추 색이 바뀜), 제목 표시줄 있는 실제 창: 저장
    target PNG가 눌리기 전 모양이고 그 픽셀이 클라이언트 캡처의 같은 자리와 같으며, 재생 클릭 점이
    녹화 클릭 점과 같다."""
    from kb_testing.sample_game import launch_sample_game
    from kookabug_platform.windows import activate

    for folder in ("targets", "subgraphs", "tests"):
        shutil.rmtree(live_ws / folder)
    game = launch_sample_game(["--press-feedback"], workdir=tmp_path / "game")
    try:
        with _live_daemon(live_ws, tmp_path) as d, d.client() as ui:
            ui.call("recorder.start", {"window": game.hwnd, "hotkeys": HOTKEYS})
            activate(game.hwnd)
            time.sleep(0.5)
            before = ui.call("recorder.frame", {"which": "live"})["frame"]
            client = decode_image(
                d.daemon.image_cache.path_of(before["image"]["cache"]).read_bytes()
            )
            _live_click(game.hwnd, START_POINT)
            time.sleep(1.0)
            ui.call("recorder.stop", {})
            click = next(st for st in steps_of(ui) if st["kind"] == "click")
            assert click["target"]["source"] == "draft", click
            x, y, w, h = click["target"]["spec"]["rect"]
            prepared = commit_new_test(ui, "tests/pre_click_live.graph.json")
            written = prepared["targets"][0]["path"]
            spec = json.loads((live_ws / written).read_text(encoding="utf-8"))
            png = decode_image(((live_ws / written).parent / spec["image"]).read_bytes())
            assert np.abs(png.astype(np.int16) - client[y : y + h, x : x + w]).max() <= 8
            assert find_click(live_ws / written, client) == START_POINT
            ui.call("recorder.commit_abort", {"token": prepared["token"]})
    finally:
        game.close()


@pytest.mark.desktop_input
@pytest.mark.timeout(600)
def test_live_kookabug_sendinput_not_recorded(live_ws: Path, tmp_path: Path) -> None:
    """녹화 중 제품 `SendInputBackend`(우리 표식)로 클릭·키·글자·P1 Alt → 그 스텝 0. 같은 녹화의
    검사 표식 입력은 녹화된다(훅이 살아 있음 — 양성 대조). `hook_lost`·`input_overflow` 없음."""
    from kb_testing.sample_game import launch_sample_game
    from kookabug_platform.dpi import per_monitor_v2_thread
    from kookabug_platform.sendinput import SendInputBackend
    from kookabug_platform.windows import activate, window_info
    from kookabug_sdk.types import Point

    game = launch_sample_game(workdir=tmp_path / "game")
    backend = SendInputBackend()
    try:
        with _live_daemon(live_ws, tmp_path) as d, d.client() as ui:
            ui.call("recorder.start", {"window": game.hwnd, "hotkeys": HOTKEYS})
            activate(game.hwnd)
            time.sleep(0.5)
            with per_monitor_v2_thread():
                origin = window_info(game.hwnd).client_origin
            at = Point(origin[0] + START_POINT[0], origin[1] + START_POINT[1])  # 화면 점
            backend.mouse_down("left", at)
            time.sleep(0.05)
            backend.mouse_up("left")
            time.sleep(0.8)
            backend.down("alt")  # P1 첫 창 앞으로의 Alt
            backend.up("alt")
            backend.down("tab")
            backend.up("tab")
            backend.text("zz")
            time.sleep(0.5)
            _live_click(game.hwnd, ACCOUNT_POINT)  # 검사 표식 = 사람
            _live_type("ab")
            time.sleep(1.0)
            ui.call("recorder.stop", {})
            state = ui.call("recorder.state", {})
            assert state["stop_reason"] == "user", state
            steps = [st for st in steps_of(ui) if st["kind"] not in ("wait", "delay")]
            assert [st["kind"] for st in steps] == ["click", "text"], steps
            assert steps[1]["text_len"] == 2
            ui.call("recorder.discard", {})
    finally:
        game.close()
