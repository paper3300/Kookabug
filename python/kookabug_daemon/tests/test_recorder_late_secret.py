"""일반 → 비밀값으로 바뀐 구간 (B3 검수 H1): 그 원문을 쓰는 기존 초안(target 그림·이름·제목·문구
확인 `equals`)은 무효가 되고, 커밋 직전 모든 내보내기를 최신 보호 영역·원문 목록으로 다시 본다.
이미 써진 초안(멱등 커밋의 재사용)도 같은 검사를 거친다.

각본: 로그인 화면 계정 칸에 검사 문자열을 친다(근거로 일반 글자) → Tab → 그 칸을 덮는 "값 확인"을
넣는다(제목·기댓값·대기 target 이름에 원문이 들어감) → 사람이 그 스텝을 비밀값으로 바꾼다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from helpers.recorder_rig import HOTKEYS, RecorderRig, graph_from_fragment, steps_of

from kb_testing.recorder_scripts import ACCOUNT_POINT, ScriptBuilder
from kookabug_daemon.client import DaemonClient, DaemonError
from kookabug_daemon.recorder import default_read_text
from kookabug_platform.frames import decode_image

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


def assert_exports_clean(rig: RecorderRig, graph_text: str) -> None:
    assert RAW not in graph_text
    read = default_read_text()
    assert read is not None, "OCR 모델이 없다"
    for path in rec_files(rig):
        assert RAW not in path.name, path
        if path.suffix == ".json":
            assert RAW not in path.read_text(encoding="utf-8"), path
        if path.suffix == ".png":
            image = decode_image(path.read_bytes())
            seen = read(image, (0, 0, int(image.shape[1]), int(image.shape[0]))) or ""
            assert RAW not in seen, (path, seen)


def test_late_secret_revalidates_exported_target(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    rig = RecorderRig.make(tmp_path, script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        text = record_with_check(rig, d, ui)
        assert RAW in json.dumps(steps_of(ui), ensure_ascii=False)  # 일반 글자일 때는 보인다
        make_secret(ui, text)
        # 바꾼 즉시: 스텝 목록·세션 저장소에 원문이 없다 (제목·이름이 대체 이름으로)
        steps = steps_of(ui)
        assert RAW not in json.dumps(steps, ensure_ascii=False), steps
        session = d.daemon.recorder.session
        assert session is not None and session.store is not None
        session.changed()
        stored = (session.store.folder / "steps.json").read_text(encoding="utf-8")
        assert RAW not in stored
        bad = [s["step"] for s in steps if "secret_overlap" in s["needs_review"]]
        assert bad, steps  # 비밀 칸과 겹친 초안 스텝이 확인 필요로
        # 커밋 직전 재검사: 무효가 된 스텝이 남아 있으면 거부 (원문 없는 오류)
        with pytest.raises(DaemonError) as caught:
            ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert caught.value.kind == "secret_region_overlap"
        assert set(caught.value.data["steps"]) == set(bad)
        assert RAW not in str(caught.value) + json.dumps(caught.value.data)
        assert not rec_files(rig)
        # 사람이 고침: 대기는 지연으로, 값 확인은 지운다
        for step in (s for s in steps if s["step"] in bad):
            patch: dict[str, Any] = (
                {"node_type": "core.flow.delay"} if step["kind"] == "wait" else {"delete": True}
            )
            ui.call("recorder.step.update", {"step": step["step"], "patch": patch})
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert RAW not in json.dumps(prepared, ensure_ascii=False)
        graph = json.dumps(graph_from_fragment(prepared["fragment"]), ensure_ascii=False)
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        assert_exports_clean(rig, graph)
    assert RAW not in "\n".join(r.getMessage() for r in caplog.records)


def test_written_draft_revalidated_after_abort_and_late_secret(tmp_path: Path) -> None:
    """일반일 때 커밋 준비로 써진 초안(이름·그림에 원문) → 중단 → 비밀값으로 바꿈: 이 세션이 쓴 그
    파일은 지워지고 다시 쓰지 않는다 (멱등 재사용 경로도 같은 검사)."""
    rig = RecorderRig.make(tmp_path, script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        text = record_with_check(rig, d, ui)
        first = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert any(RAW in p.name for p in rec_files(rig))  # 일반 글자일 때는 허용
        ui.call("recorder.commit_abort", {"token": first["token"]})
        make_secret(ui, text)
        assert not any(RAW in p.name for p in rec_files(rig)), rec_files(rig)
        with pytest.raises(DaemonError) as caught:
            ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert caught.value.kind == "secret_region_overlap"
        for step in caught.value.data["steps"]:
            ui.call("recorder.step.update", {"step": step, "patch": {"delete": True}})
        prepared = ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        graph = json.dumps(graph_from_fragment(prepared["fragment"]), ensure_ascii=False)
        ui.call("recorder.commit_finish", {"token": prepared["token"], "graph_path": GRAPH})
        assert_exports_clean(rig, graph)


def logs_of(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


def test_abort_modified_target_does_not_log_secret(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """써진 초안을 사람이 밖에서 고친 뒤 비밀값으로 바꿈: 그 파일은 남기되(사용자 수정 보존)
    로그에는 경로 대신 초안 ID만 (B3 2차 검수 H2)."""
    caplog.set_level(logging.DEBUG)
    rig = RecorderRig.make(tmp_path, script())
    with rig.daemon(speed=None) as d, d.client() as ui:
        text = record_with_check(rig, d, ui)
        params = {"mode": "new_test", "graph_path": GRAPH}
        first = ui.call("recorder.commit_prepare", params)
        assert ui.call("recorder.commit_prepare", params) == first
        ui.call("recorder.commit_abort", {"token": first["token"]})
        target = next(
            p for p in rec_files(rig) if p.name.endswith(".target.json") and RAW in p.name
        )
        body = json.loads(target.read_text(encoding="utf-8"))
        body["match"] = {"threshold": 0.91}
        changed_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
        target.write_bytes(changed_bytes)
        caplog.clear()
        make_secret(ui, text)
        assert target.read_bytes() == changed_bytes  # 사용자 수정은 보존한다
        with pytest.raises(DaemonError) as caught:
            ui.call("recorder.commit_prepare", params)
        assert caught.value.kind == "secret_region_overlap"
        assert any("남긴다" in r.getMessage() for r in caplog.records)  # 경고는 남는다
        assert RAW not in logs_of(caplog)


def test_reused_target_path_is_removed_after_secret(tmp_path: Path) -> None:
    """기존 워크스페이스 target 이름에 나중에 비밀값이 된 글자가 있음: 무효가 된 재사용 경로는 공개
    스텝·세션 저장소에서 빠진다(기존 파일은 그대로) (B3 2차 검수 H1)."""
    rig = RecorderRig.make(tmp_path, script())
    old = rig.root / "targets/login/account_field.target.json"
    named = old.with_name(RAW + ".target.json")
    named.write_bytes(old.read_bytes())
    old.unlink()
    path = f"targets/login/{RAW}.target.json"
    with rig.daemon(speed=None) as d, d.client() as ui:
        ui.call("recorder.start", START)
        rig.advance(d, 4500)
        ui.call("recorder.stop", {})
        steps = steps_of(ui)
        text = next(s for s in steps if s["kind"] == "text")
        reused = next(s for s in steps if s.get("target", {}).get("path") == path)
        assert reused["target"]["reused"]
        make_secret(ui, text)
        after = steps_of(ui)
        session = d.daemon.recorder.session
        assert session is not None and session.store is not None
        session.changed()
        stored = (session.store.folder / "steps.json").read_text(encoding="utf-8")
        click = next(s for s in after if s["step"] == reused["step"])
        assert click["target"] == {"source": "none"}
        assert "secret_overlap" in click["needs_review"]
        with pytest.raises(DaemonError) as caught:
            ui.call("recorder.commit_prepare", {"mode": "new_test", "graph_path": GRAPH})
        assert caught.value.kind == "secret_region_overlap"
        assert reused["step"] in caught.value.data["steps"]
        assert RAW not in json.dumps(after, ensure_ascii=False) and RAW not in stored
        assert named.is_file()  # 기존 사용자 파일은 지우지 않는다


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
