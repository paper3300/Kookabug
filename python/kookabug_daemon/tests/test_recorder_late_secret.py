"""일반 → 비밀값으로 바뀐 구간. UX11 B (2026-11-16 사용자 결정 — 로컬 툴): 그 원문을 쓰는 기존
초안(target 그림·이름·제목·문구 확인 `equals`)은 **가리지도 버리지도 않는다**. 글자 입력 스텝만
`$secret` 참조로 커밋된다(그래프의 입력 노드에 원문을 쓰지 않는 저장 방식은 그대로).

각본: 로그인 화면 계정 칸에 검사 문자열을 친다(근거로 일반 글자) → Tab → 그 칸을 덮는 "값 확인"을
넣는다(제목·기댓값·대기 target 이름에 원문이 들어감) → 사람이 그 스텝을 비밀값으로 바꾼다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, RecorderRig, steps_of

from kb_testing.recorder_scripts import ACCOUNT_POINT, ScriptBuilder
from kookabug_daemon.client import DaemonClient

pytestmark = [pytest.mark.process, pytest.mark.timeout(300)]

START = {"launch": {}, "hotkeys": HOTKEYS}
RAW = "vaultcode42"
BOX = [398, 208, 330, 44]
"""계정 칸을 덮는 값 확인 영역."""
GRAPH = "tests/late_secret.graph.json"


def script() -> list[dict[str, Any]]:
    s = ScriptBuilder(scene="login")
    s.at(500).click(ACCOUNT_POINT)
    s.at(1000).type(RAW)
    s.at(3500).key("tab")
    s.at(4500).mark("done")
    return s.lines


def record_with_check(rig: RecorderRig, d: Any, ui: DaemonClient) -> dict[str, Any]:
    """녹화 → 정지 → 계정 칸 값 확인 넣기. 일반 글자 스텝을 준다."""
    ui.call("recorder.start", START)
    rig.advance(d, 4500)
    shot = ui.call("recorder.frame", {"which": "live"})
    ui.call("recorder.stop", {})
    text = next(s for s in steps_of(ui) if s["kind"] == "text")
    assert text["text_state"] == "ordinary" and text["text"] == RAW
    ui.call(
        "recorder.insert_check",
        {"kind": "text", "frame_id": shot["frame"]["frame_id"], "rect": BOX},
    )
    return text


def make_secret(ui: DaemonClient, text: dict[str, Any]) -> None:
    patch = {"text_state": "secret", "secret_key": "review.test"}
    changed = ui.call("recorder.step.update", {"step": text["step"], "patch": patch})
    assert changed["step"]["text_state"] == "secret"


def rec_files(rig: RecorderRig) -> list[Path]:
    base = rig.root / "targets" / "rec"
    return sorted(base.rglob("*")) if base.is_dir() else []


def test_late_secret_keeps_drafts_and_commits_secret_ref(tmp_path: Path) -> None:
    """나중에 비밀값으로 바꿔도 초안·이름·기댓값은 그대로이고 커밋이 막히지 않는다. 글자 입력은
    `$secret` 참조로만 그래프에 들어간다."""
    rig = RecorderRig.make(tmp_path, script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        text = record_with_check(rig, d, ui)
        before = steps_of(ui)
        make_secret(ui, text)
        after = steps_of(ui)
        assert not any("secret_overlap" in s["needs_review"] for s in after), after
        kept = {s["step"]: s.get("target") for s in before if s["step"] != text["step"]}
        assert {s["step"]: s.get("target") for s in after if s["step"] in kept} == kept
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        nodes = prepared["fragment"]["nodes"]
        typed = [n for n in nodes if n["type"] == "core.input.type_text"]
        assert [n["in"]["text"] for n in typed] == [{"$secret": "review.test"}]
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})


def logs_of(caplog: pytest.LogCaptureFixture) -> str:
    """Kookabug 로그만. websockets 라이브러리의 DEBUG 프레임 덤프(`< TEXT …`)는 사람 연결로 보낸
    알림 그대로라 로그 출구가 아니다 — daemon은 `websockets` 로거를 WARNING으로 둔다(`app.
    _setup_logging`). caplog를 DEBUG로 두면 알림 도착 시점에 따라 그 덤프가 섞인다(CI 부하)."""
    return "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("kookabug"))


def test_websockets_frame_dump_not_in_daemon_log(tmp_path: Path) -> None:
    """`logs_of`가 Kookabug 로거만 보는 근거: daemon 로그 수준을 debug로 올려도 websockets 프레임
    덤프는 stderr·로그 파일에 나가지 않는다 (CI ci_1)."""
    from kookabug_daemon.app import _setup_logging  # pyright: ignore[reportPrivateUsage]

    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    ws_level = logging.getLogger("websockets").level
    try:
        path = _setup_logging(tmp_path, "debug")
        logging.getLogger("websockets.server").debug("< TEXT 02_%s.png", RAW)
        logging.getLogger("kookabug_daemon.recorder").debug("디버그 줄은 나간다")
        for handler in root.handlers:
            handler.flush()
        text = path.read_text(encoding="utf-8")
    finally:
        for handler in [h for h in root.handlers if h not in handlers]:
            root.removeHandler(handler)
            handler.close()
        root.setLevel(level)
        logging.getLogger("websockets").setLevel(ws_level)
    assert "디버그 줄은 나간다" in text
    assert RAW not in text


def test_discard_after_written_targets_logs_count_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """써진 target이 있는 채로 버림: 로그에는 개수만 (이름에 일반 글자가 들어 있어도 로그에
    없다)."""
    caplog.set_level(logging.DEBUG)
    rig = RecorderRig.make(tmp_path, script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        record_with_check(rig, d, ui)
        first = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        ui.call("recorder.commit_abort", {"token": first["token"]})
        assert any(RAW in p.name for p in rec_files(rig))  # 일반 글자일 때는 이름에 허용
        ui.call("recorder.discard", {})
        assert any("써진 target" in r.getMessage() for r in caplog.records)
        assert RAW not in logs_of(caplog)
