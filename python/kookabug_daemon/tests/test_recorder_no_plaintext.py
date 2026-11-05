"""녹화 데이터에 비밀번호 원문 없음 (M4 계획 2.8, 검수 M7, T8). 재생 `runs/`(D3)는 대상이 아니다.

각본 비밀번호 `sample-pass-01`(쉬었다 이어 침·Backspace): 판정 중·커밋 직후의 `recorder.steps` 결과,
알림 기록, 세션 저장소 `steps.json`, daemon 로그, 그래프 파일, target JSON·파일 이름·노드 제목에
원문 바이트가 없고, 커밋 target PNG는 OCR로도 원문이 없다. 일반 글자 `qa_tester_01`은 그래프에 있다.

녹화 임시 화면(세션 저장소 PNG·`recorder.frame`이 올린 정지 화면과 그 `cache/editor/` 복제본)은
원문 픽셀을 담을 수 있는 D3 예외다 — 세션이 끝나면 지워진다.
"""

from __future__ import annotations

import json
import logging
import queue
import shutil
from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, SECRET_KEY, RecorderRig, graph_from_fragment, steps_of

from kb_testing.recorder_scripts import PASSWORD, login_script
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.image_cache import CACHE_DIR
from kookabug_daemon.recorder import default_read_text
from kookabug_daemon.recorder_store import recorder_cache_dir
from kookabug_platform.frames import decode_image

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

START = {"launch": {}, "hotkeys": HOTKEYS}
GRAPH = "tests/rec_login.graph.json"
PIECES = (PASSWORD, "pass-01", "pass-0")
"""원문과 쉬었다 친 뒤 조각 (`sample-`는 경로·창 제목의 `sample`과 겹쳐 따로 보지 않는다)."""


def drafts_rig(tmp_path: Path) -> RecorderRig:
    rig = RecorderRig.make(tmp_path, login_script(split=True, backspace=True))
    for folder in ("targets", "subgraphs", "tests"):
        shutil.rmtree(rig.root / folder)
    return rig


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


def test_password_absent_from_recording_data(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig = drafts_rig(tmp_path)
    seen: list[Any] = []
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        for t_ms in (4500, 7500, 9300, 10200, 12000):  # 비밀번호를 치는 중·친 뒤·로그인 뒤
            rig.advance(d, t_ms)
            seen.append(steps_of(ui))
            seen.append(ui.call("recorder.state", {}))
        session = d.daemon.recorder.session
        assert session is not None and session.store is not None
        store = session.store.folder
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        seen.append(steps)
        stored = (store / "steps.json").read_bytes()
        secret = next(s for s in steps if s.get("text_state") == "secret")
        ui.call(
            "recorder.step.update", {"step": secret["step"], "patch": {"secret_key": SECRET_KEY}}
        )
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        seen.append(prepared)
        seen.append(steps_of(ui))
        graph = graph_from_fragment(prepared["fragment"])
        (rig.root / GRAPH).parent.mkdir(parents=True, exist_ok=True)
        (rig.root / GRAPH).write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        seen.extend(drain(ui))
    # RPC 결과·알림 (판정 중·판정 뒤·커밋)
    assert_no_raw("recorder.steps·state·commit_prepare 결과·알림", json.dumps(seen))
    assert any(n.get("method") == "recorder.changed" for n in seen if isinstance(n, dict))
    # 세션 저장소 steps.json: 일반 글자도 쓰지 않는다
    assert_no_raw("steps.json", stored)
    assert b"qa_tester_01" not in stored
    # daemon 로그
    assert_no_raw("daemon 로그", "\n".join(r.getMessage() for r in caplog.records))
    # 그래프: 비밀값은 키로만, 일반 글자는 그대로
    graph_bytes = (rig.root / GRAPH).read_bytes()
    assert_no_raw("그래프 파일", graph_bytes)
    assert b"qa_tester_01" in graph_bytes and SECRET_KEY.encode() in graph_bytes
    # target JSON·파일 이름·노드 제목·PNG(OCR)
    files = sorted((rig.root / "targets" / "rec").rglob("*"))
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
    titles = [n.get("title", "") for n in graph["nodes"].values()]
    assert_no_raw("노드 제목", json.dumps(titles, ensure_ascii=False))


def test_recorder_frame_pixels_d3_exception_cleaned(tmp_path: Path) -> None:
    """녹화 임시 화면(원문 픽셀을 담을 수 있음)은 세션 끝에 지워진다: 세션 저장소 폴더, 이 세션이
    `recorder.frame`으로 올린 정지 화면과 `cache/editor/` PNG. daemon 시작 때 `cache/recorder/`
    도."""
    rig = RecorderRig.make(tmp_path, login_script(split=True))
    leftover = recorder_cache_dir(rig.root) / "oldsessn"
    leftover.mkdir(parents=True)
    (leftover / "f1.png").write_bytes(b"x")
    with rig.daemon() as d, d.client() as ui:
        assert not leftover.exists()  # 지난 daemon이 남긴 세션
        ui.call("recorder.start", START)
        steps = steps_of(ui)
        while len(steps) < 6:
            steps = steps_of(ui)
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        secret = next(s for s in steps if s.get("text_state") == "secret")
        login = steps[-1]
        shots = [
            ui.call("recorder.frame", {"step": secret["step"], "which": "pre_next"}),
            ui.call("recorder.frame", {"step": login["step"], "which": "pre_click"}),
        ]
        # 비밀번호 칸이 보이는 프레임은 보호 영역을 함께 준다
        assert shots[1]["protected"], shots[1]
        pngs = [d.daemon.image_cache.path_of(s["frame"]["image"]["cache"]) for s in shots]
        assert all(p.parent == rig.root.joinpath(".kookabug", *CACHE_DIR) for p in pngs)
        assert all(p.is_file() for p in pngs)
        session = d.daemon.recorder.session
        assert session is not None and session.store is not None
        store = session.store.folder
        assert any(store.glob("f*.png"))
        ui.call("recorder.discard", {})
        assert not store.exists()
        assert not any(p.exists() for p in pngs)
        for shot in shots:
            with pytest.raises(Exception, match=r"frame_expired|없다"):
                d.daemon.frames.get(shot["frame"]["frame_id"])
        with pytest.raises(DaemonError) as caught:
            ui.call("recorder.steps", {})
        assert caught.value.kind == "recorder_state_invalid"
