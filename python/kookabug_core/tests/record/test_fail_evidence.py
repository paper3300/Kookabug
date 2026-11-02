"""실패 스텝 증거: 첫·중간·마지막 캡처와 매칭 후보 (구현 계획 M3 2.6, T6, 검수 M5·2차 N3).

fail 출구·`error`·`stale_observation`으로 끝난 스텝은 마지막 캡처(`_fail`·`_error`)에 더해 그
스텝의 첫 캡처(`_first`)·중간 캡처(`_mid`)를 남기고 `step.end.evidence`에 시각(스텝 시작 기준
벽시계 ms)을 쓴다. 코어 찾기·대기 노드가 fail 출구로 끝나면 마지막 찾기의 상위 후보 3개와 임계값도.
비밀값 스텝·구간 끄기면 아무것도 남기지 않고 `omitted`에 이유를 남긴다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from helpers.epoch import Debugger
from helpers.evidence import LOADING_TEXT, LOGIN_TITLE, START, run_scene
from helpers.graphs import link, secret, target
from helpers.run import tk

from kookabug_core.schema import check_shape

T = "2026-11-02T00:00:00.000Z"


def valid(event: dict[str, Any]) -> None:
    assert not check_shape({**event, "seq": 1, "t": T}, "events")


def launch(g: Any, then: str) -> Any:
    return g.node(
        "n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": then}
    )


def test_wait_timeout_saves_first_mid_last_and_candidates(tmp_path: Path) -> None:
    # 타이틀 화면에서 로그인 제목을 1.5초 기다린다: 0·100·…·1400 ms에 캡처 15장 (1500 ms에는
    # 노드 기한이 지나 캡처하지 않고 timeout), 스텝은 1500 ms에 끝난다
    g = launch(tk().entry("n_launch"), "n_wait").node(
        "n_wait", "core.image.wait", inputs={"target": target(LOGIN_TITLE), "timeout_ms": 1500}
    )
    ran = run_scene(tmp_path, g)
    assert (ran.result.verdict, ran.result.code) == ("fail", "unhandled_fail")
    end = ran.end("n_wait")
    step = ran.step("n_wait")
    valid(end)
    evidence = end["evidence"]
    first, mid, last = (f"steps/{step}_{name}.png" for name in ("first", "mid", "fail"))
    assert (evidence["first"], evidence["first_at_ms"]) == (first, 0)
    # 찾기는 남은 노드 기한을 **실제 시간**으로 받는다(시계는 가짜). 마지막 찾기(1400 ms)는
    # 100 ms만 남아, 부하로 찾기가 그보다 오래 걸리면 그 자리에서 timeout이 되어 스텝이 그 캡처
    # 시각에 끝난다(전체 실행에서 1번 `(mid, 700, 0)`, 검수 T9-1). 그때도 규칙은 같다:
    # 중간 = (시작 + 끝)/2에 가장 가까운 표본
    ended = end["duration_ms"]
    if ended == 1500:
        assert (evidence["last"], evidence["last_at_ms"]) == (last, 1400)
        # 표본 중 (0 + 1500)/2 = 750에 가장 가까운 장: 700 ms (차이 50)
        assert (evidence["mid"], evidence["mid_at_ms"], evidence["mid_offset_ms"]) == (mid, 700, 50)
    else:
        assert 0 < ended < 1500 and ended % 100 == 0, ended
        assert (evidence["last"], evidence["last_at_ms"]) == (last, ended)
        assert evidence["mid"] == mid
        assert evidence["mid_offset_ms"] == abs(evidence["mid_at_ms"] - ended // 2) <= 100
    assert "mid_missing" not in evidence
    for path in (first, mid, last):
        assert path in end["artifacts"]
        assert ran.image(path).shape[:2] == (640, 1024)
    # 매칭 후보: 마지막 찾기의 서로 다른 자리 상위 3개(점수 순)와 임계값, 상자는 `_fail` 이미지 좌표
    assert evidence["target"] == LOGIN_TITLE
    assert 0 < evidence["threshold"] <= 1
    candidates = evidence["candidates"]
    assert len(candidates) == 3
    scores = [c["score"] for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert all(score < evidence["threshold"] for score in scores)
    for c in candidates:
        x, y, w, h = c["rect"]
        assert x >= 0 and y >= 0 and x + w <= 1024 and y + h <= 640
        assert c["scale"] > 0
    # 배율만 다른 같은 자리가 아니다: 후보 상자끼리 겹치지 않는다 (검수 T6-1 Mid)
    rects = [tuple(c["rect"]) for c in candidates]
    assert all(iou(a, b) == 0 for i, a in enumerate(rects) for b in rects[i + 1 :])


def iou(a: tuple[int, ...], b: tuple[int, ...]) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[0] + a[2], b[0] + b[2]), min(a[1] + a[3], b[1] + b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    return inter / (a[2] * a[3] + b[2] * b[3] - inter)


def test_wait_any_candidates_from_closest_target_not_exit_order(tmp_path: Path) -> None:
    """`wait_any`가 한 프레임에서 여러 target을 찾으면 후보는 최고점이 가장 높은 target 것이다
    (출구 순서와 무관, 검수 T6-1 Low)."""
    best: dict[str, float] = {}
    for name in (LOGIN_TITLE, LOADING_TEXT):
        single = launch(tk().entry("n_launch"), "n_wait").node(
            "n_wait", "core.image.wait", inputs={"target": target(name), "timeout_ms": 0}
        )
        ran = run_scene(tmp_path / f"single{len(best)}", single)
        best[name] = ran.end("n_wait")["evidence"]["candidates"][0]["score"]
    closest = max(best, key=lambda name: best[name])
    assert best[LOGIN_TITLE] != best[LOADING_TEXT]
    for order in ((LOGIN_TITLE, LOADING_TEXT), (LOADING_TEXT, LOGIN_TITLE)):
        exits = ["a", "b"]
        g = launch(tk().entry("n_launch"), "n_any").node(
            "n_any",
            "core.image.wait_any",
            inputs={
                "targets": {e: target(t) for e, t in zip(exits, order, strict=True)},
                "timeout_ms": 300,
            },
            config={"exits": exits},
        )
        ran = run_scene(tmp_path / f"any_{order.index(closest)}", g)
        end = ran.end("n_any")
        valid(end)
        assert end["exit"] == "timeout"
        assert end["evidence"]["target"] == closest
        assert end["evidence"]["candidates"][0]["score"] == best[closest]


def test_stale_observation_step_first_mid_last(tmp_path: Path) -> None:
    """폴링 재개 뒤 입력 재검사로 `stale_observation`이 된 스텝도 그 안에서 캡처했으면 첫·중간·
    마지막 캡처를 남긴다 (검수 T6-1 Low)."""
    g = (
        launch(tk().entry("n_launch"), "n_a")
        .node("n_a", "testkit.shot", next={"done": "n_b"})
        # 앞 스텝 캡처(관측)를 입력으로 받고 100 ms마다 캡처하는 스텝: 4번째 기다림에서 멈췄다
        # 재개 (기다림 하나는 50 ms 조각 둘이라 7번째 조각)
        .node(
            "n_b",
            "testkit.shot",
            inputs={"captures": 8, "gap_ms": 100, "value": link("n_a.image")},
        )
    )
    dbg = Debugger(poll={"n_b": 7})
    ran = run_scene(tmp_path, g, debugger=dbg)
    assert dbg.pauses == [("n_b", "poll")]
    assert (ran.result.verdict, ran.result.code) == ("fail", "unhandled_fail")
    end = ran.end("n_b")
    step = ran.step("n_b")
    valid(end)
    assert end["status"] == "fail" and end["message"].startswith("stale_observation:")
    evidence = end["evidence"]
    # 캡처 0·100·200·300 ms, 재개 직후 재검사에서 끝난다
    assert (evidence["first"], evidence["first_at_ms"]) == (f"steps/{step}_first.png", 0)
    assert (evidence["last"], evidence["last_at_ms"]) == (f"steps/{step}_fail.png", 300)
    assert evidence["mid"] == f"steps/{step}_mid.png" and evidence["mid_at_ms"] in (100, 200)
    assert "candidates" not in evidence


def test_found_wait_has_no_evidence_and_click_not_found_has_candidates(tmp_path: Path) -> None:
    g = (
        launch(tk().entry("n_launch"), "n_ok")
        .node(
            "n_ok",
            "core.image.wait",
            inputs={"target": target(START), "timeout_ms": 500},
            next={"found": "n_click"},
        )
        .node(
            "n_click",
            "core.image.click",
            inputs={"target": target(LOGIN_TITLE), "timeout_ms": 300},
        )
    )
    ran = run_scene(tmp_path, g)
    # 성공한 스텝에는 증거가 없다
    assert "evidence" not in ran.end("n_ok")
    end = ran.end("n_click")
    valid(end)
    assert (end["status"], end["exit"]) == ("fail", "not_found")
    evidence = end["evidence"]
    assert evidence["target"] == LOGIN_TITLE and evidence["candidates"]
    assert (evidence["first_at_ms"], evidence["last_at_ms"]) == (0, 200)


def test_error_step_first_mid(tmp_path: Path) -> None:
    # 캡처 6장(0·100·…·500 ms) 뒤 예외: 첫·중간·마지막(_error), 매칭 후보는 없다
    g = launch(tk().entry("n_launch"), "n_shot").node(
        "n_shot", "testkit.shot", inputs={"captures": 6, "gap_ms": 100, "boom": True}
    )
    ran = run_scene(tmp_path, g)
    assert (ran.result.verdict, ran.result.code) == ("error", "node_error")
    end = ran.end("n_shot")
    step = ran.step("n_shot")
    valid(end)
    evidence = end["evidence"]
    assert (evidence["first"], evidence["first_at_ms"]) == (f"steps/{step}_first.png", 0)
    assert (evidence["last"], evidence["last_at_ms"]) == (f"steps/{step}_error.png", 500)
    # 중간 250 ms: 200·300 ms 표본이 똑같이 50 ms 떨어져 있다 — 실제 시각과 차이를 남긴다
    assert evidence["mid"] == f"steps/{step}_mid.png"
    assert evidence["mid_at_ms"] in (200, 300) and evidence["mid_offset_ms"] == 50
    assert "candidates" not in evidence and "target" not in evidence


def test_single_capture_failure_first_is_last_and_no_mid(tmp_path: Path) -> None:
    g = launch(tk().entry("n_launch"), "n_shot").node(
        "n_shot", "testkit.shot", inputs={"captures": 1, "boom": True}
    )
    ran = run_scene(tmp_path, g)
    end = ran.end("n_shot")
    valid(end)
    evidence = end["evidence"]
    step = ran.step("n_shot")
    # 첫 캡처가 마지막 캡처다 (같은 파일), 중간 장면은 없다
    assert evidence["first"] == evidence["last"] == f"steps/{step}_error.png"
    assert (evidence["mid"], evidence["mid_missing"]) == (None, "no_sample_near_mid")
    assert f"steps/{step}_first.png" not in end["artifacts"]


def test_evidence_omitted_for_secret_or_off(tmp_path: Path) -> None:
    # 구간 끄기: 대기가 실패해도 첫·중간·마지막·후보 모두 남기지 않는다
    off = launch(tk().entry("n_launch"), "n_wait").node(
        "n_wait",
        "core.image.wait",
        inputs={"target": target(LOGIN_TITLE), "timeout_ms": 1000},
        record={"screenshots": "off"},
    )
    ran = run_scene(tmp_path / "off", off)
    end = ran.end("n_wait")
    valid(end)
    assert "evidence" not in end and "artifacts" not in end
    reasons = {(o["kind"], o.get("name"), o["reason"]) for o in end["omitted"]}
    assert ("screenshot", "first", "policy_off") in reasons
    assert ("screenshot", "fail", "policy_off") in reasons
    assert ("thumbnail", None, "policy_off") in reasons

    # 비밀값 입력 스텝: 예외로 끝나도 첫·중간·마지막을 남기지 않는다
    sec = launch(tk().entry("n_launch"), "n_shot").node(
        "n_shot",
        "testkit.shot",
        inputs={"captures": 5, "gap_ms": 100, "boom": True, "value": secret("pw")},
    )
    ran = run_scene(tmp_path / "secret", sec, secrets={"pw": "hunter2"})
    end = ran.end("n_shot")
    valid(end)
    assert "evidence" not in end and "artifacts" not in end
    reasons = {(o["kind"], o.get("name"), o["reason"]) for o in end["omitted"]}
    assert {("screenshot", "first", "secret_input"), ("screenshot", "error", "secret_input")} <= (
        reasons
    )
    assert not list((tmp_path / "secret" / "run").rglob("*.png"))
