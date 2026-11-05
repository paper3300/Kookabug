"""target 편집기 확장의 daemon 쪽 (M4 T11): `target.preview` `peaks`(같은 모양 N곳)·
`scale_scores`(다른 배율 점수), `target.read_text`(영역 글자, 녹화 프레임 보호 영역·에이전트
거부)."""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest
from helpers.daemon_targets import (
    PATTERN,
    PATTERN_AT,
    PATTERN_AT2,
    PATTERN_AT3,
    Editor,
    target_workspace,
)

from kb_testing.daemon import ThreadDaemon
from kookabug_core.recorder.protect import ProtectionSet
from kookabug_daemon.client import DaemonError

pytestmark = pytest.mark.process

LOGIN_BUTTON: Final = (432, 380, 160, 56)
"""예제 게임 로그인 화면의 로그인 단추 (layout.py `_LOGIN`)."""
SCALES: Final = [1.0, 1.25, 1.5, 2.0]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return target_workspace(tmp_path)


def _boxes_overlap(a: list[int], b: list[int]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def test_preview_peaks_non_overlapping_count(root: Path) -> None:
    with ThreadDaemon(root) as d, d.client() as client:
        ed = Editor(client)
        frame = ed.load("captures/pattern_three.png")
        rect = (*PATTERN_AT, *PATTERN)
        result = ed.preview(frame, crop=(frame, rect))
        assert result["found"] is True
        peaks = result["peaks"]
        assert len(peaks) == 3, peaks
        spots = sorted(tuple(p["rect"][:2]) for p in peaks)
        assert spots == sorted([PATTERN_AT, PATTERN_AT2, PATTERN_AT3])
        for i, a in enumerate(peaks):
            assert a["score"] >= result["threshold"]
            for b in peaks[i + 1 :]:
                assert not _boxes_overlap(a["rect"], b["rect"])
        # 하나뿐인 화면은 1곳, 못 찾으면 빈 목록
        one = ed.preview(ed.load("captures/pattern_one.png"), crop=(frame, rect))
        assert len(one["peaks"]) == 1
        none = ed.preview(ed.load("captures/pattern_none.png"), crop=(frame, rect))
        assert none["found"] is False and none["peaks"] == []


def test_scale_scores_table(root: Path) -> None:
    with ThreadDaemon(root) as d, d.client() as client:
        ed = Editor(client)
        frame = ed.load("captures/login.png")
        plain = ed.preview(frame, crop=(frame, LOGIN_BUTTON))
        assert "scale_scores" not in plain  # 접힌 줄을 펼칠 때만 계산한다
        result = ed.preview(frame, crop=(frame, LOGIN_BUTTON), scales=SCALES)
        rows = result["scale_scores"]
        assert [r["factor"] for r in rows] == SCALES
        # 1.0배 줄은 기본 결과 그대로
        assert rows[0]["found"] is True and result["found"] is True
        assert rows[0]["score"] == result["match"]["score"]
        assert rows[0]["scale"] == result["match"]["scale"]
        for row in rows[1:]:
            assert isinstance(row["score"], float) and -1.0 <= row["score"] <= 1.0
            # 기대 배율(정지 화면과 같은 비) 둘레에서 찾는다
            assert row["scale"] == pytest.approx(row["factor"], rel=0.25)
        # 배율을 바꾸면 점수가 1.0배보다 높지 않다 (보간으로 무늬가 흐려진다)
        assert all(r["score"] <= rows[0]["score"] + 1e-6 for r in rows[1:])
        # 저장한 target(이미지 템플릿)으로 다시 봐도 1.0배는 바로 매칭 점수 그대로
        saved = ed.save("targets/ext/login.target.json", frame, LOGIN_BUTTON)
        again = ed.preview(
            frame,
            image="login.png",
            base="targets/ext/login.target.json",
            scales=[1.0, 1.25],
        )
        assert again["found"] is True
        assert again["scale_scores"][0]["score"] == saved["preview"]["match"]["score"]


def test_read_text_region(root: Path, ocr_models: Path) -> None:
    with ThreadDaemon(root) as d, d.client() as client:
        frame = client.call("target.load_image", {"path": "captures/login.png"})
        result = client.call(
            "target.read_text", {"frame_id": frame["frame_id"], "rect": list(LOGIN_BUTTON)}
        )
        assert "로그인" in result["text"].replace(" ", ""), result
        for line in result["lines"]:
            x, _, w, _ = line["rect"]
            assert LOGIN_BUTTON[0] <= x and x + w <= LOGIN_BUTTON[0] + LOGIN_BUTTON[2] + 1
            assert 0.0 <= line["score"] <= 1.0
        # 정지 화면 밖 영역은 target_invalid
        with pytest.raises(DaemonError) as caught:
            client.call(
                "target.read_text", {"frame_id": frame["frame_id"], "rect": [1000, 600, 100, 100]}
            )
        assert caught.value.kind == "target_invalid"


class _FakeEngine:
    name = "fake"

    def __init__(self) -> None:
        self.calls: list[Any] = []

    def read(self, image: Any, *, region: Any = None, deadline: Any = None) -> list[Any]:
        from kookabug_platform.ocr.engine import OcrLine

        self.calls.append(tuple(region))
        return [OcrLine("가짜", tuple(region), 0.9)]


def test_read_text_refuses_recorder_protected_region(root: Path) -> None:
    """녹화 세션이 올린 정지 화면의 보호 영역(비밀번호 칸)과 겹치면 OCR 전에 거부한다."""
    with ThreadDaemon(root) as d, d.client() as client:
        engine = _FakeEngine()
        d.daemon.targets.ocr_factory = lambda: engine
        frame = client.call("target.load_image", {"path": "captures/login.png"})
        frame_id = frame["frame_id"]
        protect = ProtectionSet()
        protect.add(1, (400, 285, 320, 50), 0)
        shot = SimpleNamespace(cache="", pixels=None, t_ns=10, dpi=96)
        session = SimpleNamespace(
            lock=threading.RLock(),
            s=SimpleNamespace(shots={frame_id: shot}),
            pipeline=SimpleNamespace(
                lock=threading.RLock(), protect=protect, leaks_secret=lambda text: False
            ),
        )
        d.daemon.recorder.session = session  # pyright: ignore[reportAttributeAccessIssue]
        try:
            with pytest.raises(DaemonError) as caught:
                client.call("target.read_text", {"frame_id": frame_id, "rect": [380, 270, 200, 40]})
            assert caught.value.kind == "secret_region_overlap"
            assert engine.calls == []
            # 겹치지 않는 영역은 읽는다
            ok = client.call("target.read_text", {"frame_id": frame_id, "rect": list(LOGIN_BUTTON)})
            assert ok["text"] == "가짜" and engine.calls == [LOGIN_BUTTON]
            # 보호 영역 밖이어도 읽은 글자가 세션 비밀값 원문을 담으면 주지 않는다 (원문 없는 오류)
            session.pipeline.leaks_secret = lambda text: "가짜" in text
            with pytest.raises(DaemonError) as caught:
                client.call("target.read_text", {"frame_id": frame_id, "rect": list(LOGIN_BUTTON)})
            assert caught.value.kind == "secret_region_overlap"
            assert "가짜" not in str(caught.value) and "가짜" not in str(caught.value.data)
        finally:
            d.daemon.recorder.session = None  # pyright: ignore[reportAttributeAccessIssue]


def test_read_text_agent_denied(root: Path) -> None:
    agent = {"kind": "agent", "name": "mcp", "version": "0", "id": "agent-1", "attended": True}
    with ThreadDaemon(root) as d:
        with d.client() as ui:
            frame = ui.call("target.load_image", {"path": "captures/login.png"})
        with d.client(agent) as client, pytest.raises(DaemonError) as caught:
            client.call(
                "target.read_text", {"frame_id": frame["frame_id"], "rect": list(LOGIN_BUTTON)}
            )
        assert caught.value.kind == "permission_denied"
        assert "ui_only" in caught.value.message
