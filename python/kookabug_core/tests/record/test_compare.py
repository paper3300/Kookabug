"""지난 성공과 비교 (M3 계획 2.8, T8): 기준 실행 고르기·스냅샷 해시·환경 차이·회차 변곡·화면 차이.

실행 폴더는 합성 이벤트로 심는다(`seq`·`t`를 붙임). 화면 차이는 플랫폼의 OpenCV 함수
(`kookabug_platform.imagediff.screen_diff`)로 가짜 장면을 비교한다.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pytest
from helpers.evidence import LOGIN_TITLE, START, SceneRun, run_scene
from helpers.graphs import GraphBuilder, subgraph_interface, target
from helpers.run import tk

from kookabug_core.record import compare as compare_mod
from kookabug_core.record.compare import (
    NO_BASELINE,
    RunSide,
    compare_runs,
    env_diff,
    finish_compare,
    inflection,
    pick_baseline,
    prepare_compare,
    snapshot_digest,
)
from kookabug_core.record.index import RunIndex
from kookabug_core.schema import check_shape
from kookabug_platform.frames import encode_jpeg, encode_png
from kookabug_platform.imagediff import screen_diff

TEST = "tests/t.graph.json"
BASE = datetime(2026, 11, 2, 1, 0, 0, tzinfo=UTC)
POPUP = (440, 220, 400, 280)
"""가짜 점검 팝업 [x, y, w, h] (가로 1280, 세로 720 장면)."""


# ---------------------------------------------------------------- 도움


def stamp(ms: int, base: datetime = BASE) -> str:
    return (base + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def folder_for(runs: Path, run_id: str, started: datetime, graph: str = TEST) -> Path:
    stem = Path(graph).name.removesuffix(".graph.json")
    return runs / f"{started.strftime('%Y-%m-%dT%H-%M-%S')}_{stem}_{run_id}"


def plant_run(
    runs: Path,
    run_id: str,
    *,
    started_ms: int = 0,
    events: Iterable[Mapping[str, Any]] = (),
    graph: str = TEST,
    **run_json: Any,
) -> Path:
    """끝난 실행 폴더 하나 (`run.json` + `events.jsonl`). 이벤트의 `t`가 없으면 시작부터 1 ms씩."""
    started = BASE + timedelta(milliseconds=started_ms)
    folder = folder_for(runs, run_id, started, graph)
    folder.mkdir(parents=True)
    lines = []
    for i, event in enumerate(events, start=1):
        line = {**event, "seq": i, "run": run_id}
        line.setdefault("t", stamp(started_ms + i))
        lines.append(json.dumps(line, ensure_ascii=False))
    (folder / "events.jsonl").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
    data: dict[str, Any] = {
        "format": "kookabug.run/0",
        "graph": graph,
        "run_id": run_id,
        "started_at": stamp(started_ms),
        "status": "finished",
        "verdict": "pass",
        "conditions": {"deadline_ms": 1000, "platform": "fake", "profile": None, "settings": {}},
        **run_json,
    }
    (folder / "run.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return folder


def side(folder: Path) -> RunSide:
    data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    return RunSide(data["run_id"], folder, data, RunIndex(folder).update())


def assert_shape(result: Mapping[str, Any]) -> None:
    assert check_shape(dict(result), "run-index", ref="#/$defs/CompareResult") == []


def start(step: str, node: str, path: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "event": "step.start",
        "attempt": 1,
        "node": node,
        "parent": None,
        "path": path or [node],
        "step": step,
        **extra,
    }


def end(step: str, exit_: str | None, status: str = "success", **extra: Any) -> dict[str, Any]:
    return {
        "event": "step.end",
        "attempt": 1,
        "duration_ms": extra.pop("duration_ms", 1),
        "exit": exit_,
        "outputs": {},
        "status": status,
        "step": step,
        **extra,
    }


def run_end(verdict: str = "pass", failure_step: str | None = None) -> dict[str, Any]:
    return {
        "event": "run.end",
        "verdict": verdict,
        "code": "passed" if verdict == "pass" else "unhandled_fail",
        "reason": "",
        "failure_step": failure_step,
        "failure_path": None if failure_step is None else ["n_w"],
        "finalized_by": "runner",
        "duration_ms": 1,
    }


RUN_START = {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}}


# ---------------------------------------------------------------- 기준 실행


def test_baseline_latest_pass_same_graph_profile_excluding_debug(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    minute = 60_000
    profile = {"deadline_ms": 1000, "platform": "fake", "profile": "dev", "settings": {}}
    other_profile = {**profile, "profile": "qa"}
    plant_run(runs, "old00001", started_ms=0 * minute, conditions=profile)
    # 기대: 같은 초 안에서 더 늦게 시작한 pass (폴더 이름 초가 같다)
    plant_run(runs, "best0001", started_ms=5 * minute + 900, conditions=profile)
    plant_run(runs, "early001", started_ms=5 * minute + 100, conditions=profile)
    # 빼야 하는 것들 (모두 기대 기준보다 늦게, 비교할 실행보다 먼저 시작)
    plant_run(runs, "debug001", started_ms=6 * minute, conditions=profile, debug_intervened=True)
    plant_run(runs, "fail0001", started_ms=7 * minute, conditions=profile, verdict="fail")
    plant_run(runs, "prof0001", started_ms=8 * minute, conditions=other_profile)
    plant_run(runs, "skip0001", started_ms=8 * minute + 1, conditions=profile, verdict="skipped")
    plant_run(
        runs, "graph001", started_ms=9 * minute, conditions=profile, graph="tests/other.graph.json"
    )
    # 줄기가 같은 다른 폴더의 그래프 (tests/sub/t.graph.json)
    plant_run(
        runs,
        "graph002",
        started_ms=9 * minute + 1,
        conditions=profile,
        graph="tests/sub/t.graph.json",
    )
    plant_run(runs, "live0001", started_ms=9 * minute + 2, conditions=profile, status="running")
    target = plant_run(runs, "this0001", started_ms=10 * minute, conditions=profile, verdict="fail")
    # 비교할 실행보다 늦게 시작한 pass
    plant_run(runs, "late0001", started_ms=11 * minute, conditions=profile)

    data = json.loads((target / "run.json").read_text(encoding="utf-8"))
    found = pick_baseline(runs, data)
    assert found is not None
    assert found[0] == "best0001" and found[1].name.endswith("_best0001")

    # 프로필 없음(null)끼리도 같은 프로필이다
    data_none = {**data, "conditions": {**profile, "profile": None}}
    assert pick_baseline(runs, data_none) is None
    plant_run(runs, "none0001", started_ms=9 * minute + 3)
    assert pick_baseline(runs, data_none) == (
        "none0001",
        folder_for(runs, "none0001", BASE + timedelta(milliseconds=9 * minute + 3)),
    )


def test_baseline_scan_skips_run_json_with_invalid_utf8(tmp_path: Path) -> None:
    """T11 검수 2차: UTF-8이 깨진 run.json 하나(더 최근)가 기준 찾기를 깨지 않고 건너뛰어진다."""
    runs = tmp_path / "runs"
    plant_run(runs, "good0001", started_ms=0)
    broken = plant_run(runs, "bad00001", started_ms=1000)
    (broken / "run.json").write_bytes(b'{"status":"finished","pad":"\xff"}')
    target = plant_run(runs, "this0001", started_ms=2000, verdict="fail")
    data = json.loads((target / "run.json").read_text(encoding="utf-8"))
    found = pick_baseline(runs, data)
    assert found is not None and found[0] == "good0001"


def test_no_baseline_message(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    events = [RUN_START, start("s1", "n_w"), end("s1", None, "fail"), run_end("fail", "s1")]
    folder = plant_run(runs, "this0001", events=events, verdict="fail")
    data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert pick_baseline(runs, data) is None
    assert pick_baseline(tmp_path / "missing", data) is None

    result = compare_runs(side(folder), None, picked="auto")
    assert result == {
        "run_id": "this0001",
        "baseline": None,
        "baseline_picked": "auto",
        "message": NO_BASELINE,
    }
    assert NO_BASELINE == "비교할 성공 실행 없음"
    assert_shape(result)


# ---------------------------------------------------------------- 그래프


def write_snapshot(folder: Path, files: Mapping[str, str]) -> None:
    for rel, text in files.items():
        path = folder / "snapshot" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_snapshot_hash_equal_and_changed_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs = tmp_path / "runs"
    files = {
        "kookabug.json": '{"format": "kookabug.workspace/0"}',
        TEST: '{"nodes": {}}',
        "subgraphs/s.graph.json": '{"nodes": {"n_x": {}}}',
        "screens/main.screen.json": "{}",
    }
    base = plant_run(runs, "base0001", events=[RUN_START, run_end()])
    same = plant_run(runs, "same0001", started_ms=1000, events=[RUN_START, run_end()])
    write_snapshot(base, files)
    write_snapshot(same, files)

    a, b = snapshot_digest(base), snapshot_digest(same)
    assert a is not None and b is not None
    assert a[0] == b[0] and len(a[0]) == 64 and set(a[1]) == set(files)
    result = compare_runs(side(same), side(base), picked="auto")
    assert result["graph"] == {"hash": a[0], "baseline_hash": a[0], "same": True, "changed": []}
    assert_shape(result)

    # 바뀐 파일·더한 파일·뺀 파일
    changed = plant_run(runs, "chg00001", started_ms=2000, events=[RUN_START, run_end()])
    write_snapshot(
        changed,
        {
            **{k: v for k, v in files.items() if k != "screens/main.screen.json"},
            "subgraphs/s.graph.json": '{"nodes": {"n_y": {}}}',
            "subgraphs/new.graph.json": "{}",
        },
    )
    result = compare_runs(side(changed), side(base), picked="user")
    graph = result["graph"]
    assert graph["same"] is False and graph["hash"] != graph["baseline_hash"]
    assert graph["baseline_hash"] == a[0]
    assert graph["changed"] == [
        {"path": "screens/main.screen.json", "change": "removed"},
        {"path": "subgraphs/new.graph.json", "change": "added"},
        {"path": "subgraphs/s.graph.json", "change": "modified"},
    ]
    assert result["baseline_picked"] == "user"
    assert_shape(result)

    # 캐시: 크기·수정 시각이 같은 파일은 다시 읽지 않는다
    cache = tmp_path / "cache" / "base0001.snapshot.json"
    first = snapshot_digest(base, cache)
    assert first == a and cache.is_file()
    read: list[Path] = []
    real = compare_mod._file_sha  # pyright: ignore[reportPrivateUsage]

    def counting(path: Path) -> str | None:
        read.append(path)
        return real(path)

    monkeypatch.setattr(compare_mod, "_file_sha", counting)
    assert snapshot_digest(base, cache) == a and read == []
    (base / "snapshot" / TEST).write_text('{"nodes": {"n_z": {}}}', encoding="utf-8")
    again = snapshot_digest(base, cache)
    assert again is not None and again[0] != a[0]
    assert [p.name for p in read] == ["t.graph.json"]

    # 스냅샷이 없는 예전 실행은 그래프 비교를 뺀다
    old = plant_run(runs, "old00001", started_ms=3000, events=[RUN_START, run_end()])
    assert snapshot_digest(old) is None
    result = compare_runs(side(old), side(base), picked="user")
    assert "graph" not in result
    assert_shape(result)


# ---------------------------------------------------------------- 환경


def test_env_diff_observed_conditions_packages() -> None:
    run = {
        "observed": {"backend": "wgc", "client_size": [1280, 720], "dpi": 144},
        "conditions": {
            "deadline_ms": 1000,
            "platform": "windows",
            "profile": "dev",
            "settings": {
                "game.lang": {"layer": "profile", "value": "ko"},
                "game.server": {"layer": "workspace", "value": "live"},
                "account.password": {"layer": "local", "secret": True},
                "account.token": {"layer": "local", "secret": True},
                "only.here": {"layer": "options", "value": 1},
            },
        },
        "packages": {"kookabug-core": "0.3.0", "kookabug-nodes": "0.3.0"},
        "plugins": [{"id": "acme.nodes", "version": "1.2.0"}],
        "game_build": "1.0.42",
    }
    baseline = {
        "observed": {"backend": "wgc", "client_size": [1920, 1080], "dpi": 96},
        "conditions": {
            "deadline_ms": 5000,
            "platform": "windows",
            "profile": "dev",
            "settings": {
                "game.lang": {"layer": "workspace", "value": "ko"},
                "game.server": {"layer": "workspace", "value": "qa"},
                "account.password": {"layer": "local", "secret": True},
                "account.token": {"layer": "local", "value": "plain"},
            },
        },
        "packages": {"kookabug-core": "0.2.0", "kookabug-nodes": "0.3.0", "old": "1"},
        "plugins": [{"id": "acme.nodes", "version": "1.1.0"}, {"id": "gone", "version": "0"}],
        "game_build": "1.0.41",
    }
    diff = {d["key"]: (d["run"], d["baseline"]) for d in env_diff(run, baseline)}
    assert diff == {
        "observed.client_size": ([1280, 720], [1920, 1080]),
        "observed.dpi": (144, 96),
        "conditions.settings.game.server": ("live", "qa"),
        # 비밀값은 값 없이 키만 (양쪽 다 비밀값이면 같다고 본다)
        "conditions.settings.account.token": ({"secret": True}, "plain"),
        "conditions.settings.only.here": (1, None),
        "packages.kookabug-core": ("0.3.0", "0.2.0"),
        "packages.old": (None, "1"),
        "plugins.acme.nodes": ("1.2.0", "1.1.0"),
        "plugins.gone": (None, "0"),
        "game_build": ("1.0.42", "1.0.41"),
    }
    keys = [d["key"] for d in env_diff(run, baseline)]
    assert keys == sorted(keys)
    # 같은 값(백엔드·프로필·플랫폼·같은 언어 값·같은 패키지)은 넣지 않고, 기한은 환경이 아니다
    assert not {"observed.backend", "conditions.profile", "conditions.platform"} & set(diff)
    assert "conditions.settings.game.lang" not in diff and "packages.kookabug-nodes" not in diff
    assert "conditions.deadline_ms" not in diff
    assert env_diff(run, run) == []
    # observed가 한쪽에만 있으면 그 값들만 null 짝
    no_observed = {k: v for k, v in baseline.items() if k != "observed"}
    diff = {d["key"]: (d["run"], d["baseline"]) for d in env_diff(run, no_observed)}
    assert diff["observed.backend"] == ("wgc", None)
    assert all(
        "password" not in key or value == ({"secret": True}, {"secret": True})
        for key, value in diff.items()
    )


# ---------------------------------------------------------------- 시간


def loop_events(
    durations: list[int], active: Mapping[int, int] | None = None
) -> list[dict[str, Any]]:
    """반복 노드(n_loop) + 회차마다 본문 로그(n_log, 5 ms)와 대기(n_wait, `durations[i]` ms).
    회차 i 경과 = `durations[i] + 5` ms. `active`(회차 → ms)는 그 회차 대기의 멈춤 뺀 경과."""
    events: list[dict[str, Any]] = [{**RUN_START, "t": stamp(0)}]
    n = 0
    t = 1

    def step(node: str, exit_: str, length: int, iteration: int | None = None, **more: Any) -> None:
        nonlocal n, t
        n += 1
        extra: dict[str, Any] = {} if iteration is None else {"iteration": iteration}
        events.append({**start(f"s{n}", node), **extra, "t": stamp(t)})
        t += length
        ended = end(f"s{n}", exit_, duration_ms=length)
        events.append({**ended, **extra, **more, "t": stamp(t)})

    step("n_loop", "body", 0)
    for i, length in enumerate(durations):
        step("n_log", "done", 5, i)
        more = {} if active is None or i not in active else {"active_duration_ms": active[i]}
        step("n_wait", "done", length, i, **more)
        step("n_loop", "body" if i < len(durations) - 1 else "done", 0)
    step("n_pass", "pass", 0)
    events.append({**run_end(), "t": stamp(t + 1)})
    return events


def test_loop_slowdown_inflection_detected(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    fast = [100, 110, 90, 105, 95, 100, 102, 98, 101, 99]
    slow = [100, 110, 90, 105, 95, 100, 320, 340, 310, 330, 300, 315]
    base = plant_run(runs, "base0001", events=loop_events(fast))
    run = plant_run(runs, "slow0001", started_ms=60_000, events=loop_events(slow))

    result = compare_runs(side(run), side(base), picked="auto")
    assert_shape(result)
    time = result["time"]
    [found] = time["inflections"]
    assert found["node"] == "n_loop" and found["graph"] == TEST and found["step"] == "s1"
    assert found["from_iteration"] == 6
    # 회차 경과(로그 5 ms 포함)의 중앙값: 앞 절반 105, 변곡부터 322.5
    assert found["before_ms"] == 105.0
    assert found["after_ms"] == 322.5
    # 본문에서 가장 많이 늦어진 노드와 전·후 평균 ("6회차부터 대기 평균 100 → 319")
    assert found["body_node"] == "n_wait"
    assert found["body_before_ms"] == pytest.approx(sum(slow[:6]) / 6)
    assert found["body_after_ms"] == pytest.approx(sum(slow[6:]) / 6)
    assert "debug_intervened" not in time
    # 노드별 평균 비교 (양쪽에 같은 노드, 한쪽에만 있는 노드는 null)
    nodes = {(n["graph"], n["node"]): n for n in time["nodes"]}
    wait = nodes[(TEST, "n_wait")]
    assert wait["count"] == 12 and wait["baseline_count"] == 10
    assert wait["mean_ms"] == pytest.approx(sum(slow) / 12)
    assert wait["baseline_mean_ms"] == pytest.approx(sum(fast) / 10)
    assert nodes[(TEST, "n_log")]["mean_ms"] == 5
    # 기준 쪽에는 변곡이 없다
    assert compare_runs(side(base), side(run), picked="user")["time"]["inflections"] == []
    # 계획 규칙의 한계: 앞 1/4 안에서 늦어지기 시작하면 앞 절반 중앙값이 이미 늦어 잡지 못한다
    assert inflection([100, 100] + [300] * 10) is None


def test_debug_intervened_run_no_inflection_and_active_means(tmp_path: Path) -> None:
    """디버거로 멈췄던 실행: 브레이크포인트에 멈춘 회차 뒤로 벽시계 경과가 늘어도 변곡을 내지
    않고, 노드 평균은 멈춤을 뺀 경과로 낸다 (스키마 6장 "시간 비교에서 뺀다")."""
    runs = tmp_path / "runs"
    fast = [100] * 10
    # 6회차 대기에서 멈춰 Step으로 넘겼다: 벽시계는 길지만 멈춤을 뺀 경과는 그대로
    paused = [100] * 6 + [5100] * 4
    base = plant_run(runs, "base0001", events=loop_events(fast))
    events = loop_events(paused, active={i: 100 for i in range(6, 10)})
    run = plant_run(runs, "dbg00001", started_ms=60_000, events=events, debug_intervened=True)
    # 같은 이벤트라도 debug_intervened가 아니면 거짓 변곡이 나온다 (회차 경과는 벽시계)
    plain = plant_run(runs, "plain001", started_ms=120_000, events=events)
    assert compare_runs(side(plain), side(base), picked="user")["time"]["inflections"]

    result = compare_runs(side(run), side(base), picked="user")
    assert_shape(result)
    time = result["time"]
    assert time["debug_intervened"] is True and time["inflections"] == []
    wait = next(n for n in time["nodes"] if n["node"] == "n_wait")
    assert wait["mean_ms"] == 100 and wait["baseline_mean_ms"] == 100

    # 진행 중 실행(run.json에 아직 없음)도 색인의 멈춤 구간으로 안다
    live_events = [
        RUN_START,
        {"event": "debug.pause", "step": None, "reason": "request", "where": "boundary"},
        {"event": "debug.resume", "step": None, "mode": "continue", "epoch": 1, "paused_ms": 5},
    ]
    live = plant_run(runs, "live0001", started_ms=180_000, events=live_events, status="running")
    assert compare_runs(side(live), side(base), picked="user")["time"]["debug_intervened"]

    # 한 번 튄 회차·끝 한 회차만 늦음·회차가 적음은 변곡이 아니다
    assert inflection([100, 100, 100, 400, 100, 100, 100, 100]) is None
    assert inflection([100, 100, 100, 100, 100, 100, 100, 900]) is None
    assert inflection([100, 300, 300]) is None
    # 끝에서 두 번 이어지면 남은 전부라 변곡
    assert inflection([100, 100, 100, 100, 100, 100, 300, 300]) == (6, 100.0, 300.0)
    # 앞 절반 중앙값이 0 ms여도 1 ms로 본다
    assert inflection([0, 0, 0, 0, 5, 5, 5, 5]) == (4, 0.0, 5.0)


# ---------------------------------------------------------------- 화면


def scene(popup: bool) -> np.ndarray:
    """가짜 게임 장면 (가로 1280, 세로 720): 배경·위 막대·아이템 칸, 팝업이면 가운데 점검 안내."""
    img = np.zeros((720, 1280, 3), np.uint8)
    img[:] = (70, 50, 30)
    cv2.rectangle(img, (0, 0), (1279, 60), (120, 90, 60), -1)
    cv2.putText(img, "INVENTORY", (30, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (230, 230, 230), 2)
    for i in range(6):
        x = 80 + i * 190
        cv2.rectangle(img, (x, 560), (x + 150, 680), (40 + i * 20, 160, 200 - i * 20), -1)
    if popup:
        x, y, w, h = POPUP
        cv2.rectangle(img, (x, y), (x + w, y + h), (235, 235, 235), -1)
        cv2.rectangle(img, (x, y), (x + w, y + h), (30, 30, 200), 4)
        cv2.putText(
            img, "MAINTENANCE", (x + 40, y + 120), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (20, 20, 20), 3
        )
        cv2.rectangle(img, (x + 140, y + 190), (x + 260, y + 240), (60, 160, 60), -1)
    return img


def screen_runs(
    tmp_path: Path, *, thumbnail: bool = True, base_omitted: bool = False, base_node: str = "n_w"
) -> tuple[Path, Path]:
    """기준(pass, n_w 썸네일 = 팝업 없음)과 실패 실행(n_w 시간 초과, `_fail` = 점검 팝업)."""
    runs = tmp_path / "runs"
    base_extra: dict[str, Any] = {}
    if base_omitted:
        base_extra["omitted"] = [{"kind": "thumbnail", "reason": "policy_off"}]
    base = plant_run(
        runs,
        "base0001",
        events=[
            RUN_START,
            start("s1", "n_a"),
            end("s1", "done"),
            start("s2", base_node),
            {**end("s2", "found"), **base_extra},
            run_end(),
        ],
    )
    run = plant_run(
        runs,
        "fail0001",
        started_ms=60_000,
        verdict="fail",
        events=[
            RUN_START,
            start("s1", "n_a"),
            end("s1", "done"),
            start("s2", "n_w"),
            end(
                "s2",
                "timeout",
                "fail",
                artifacts=["steps/s2_fail.png"],
                evidence={
                    "last": "steps/s2_fail.png",
                    "mid": None,
                    "mid_missing": "no_sample_near_mid",
                },
            ),
            run_end("fail", "s2"),
        ],
    )
    (run / "steps").mkdir()
    (run / "steps" / "s2_fail.png").write_bytes(encode_png(scene(True)))
    (base / "thumbs").mkdir()
    (base / "thumbs" / "s1.jpg").write_bytes(encode_jpeg(scene(False), 480))
    if thumbnail:
        (base / "thumbs" / "s2.jpg").write_bytes(encode_jpeg(scene(False), 480))
    return run, base


def overlap(a: list[int], b: tuple[int, int, int, int]) -> int:
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def test_screen_diff_finds_popup_region(tmp_path: Path) -> None:
    run, base = screen_runs(tmp_path)
    result = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)
    assert_shape(result)
    screen = result["screen"]
    assert screen["step"] == "s2" and screen["file"] == "steps/s2_fail.png"
    assert screen["baseline_step"] == "s2" and screen["baseline_file"] == "thumbs/s2.jpg"
    assert "reason" not in screen
    popup_area = POPUP[2] * POPUP[3]
    assert 0.05 < screen["diff_ratio"] < 0.3
    regions = screen["regions"]
    assert 1 <= len(regions) <= 5
    # 가장 넓은 상자가 팝업과 겹치고, 상자들은 거의 팝업 안에 있다 (이 실행 이미지 좌표)
    assert overlap(regions[0], POPUP) > 0.6 * popup_area
    assert sum(overlap(r, POPUP) for r in regions) > 0.8 * sum(r[2] * r[3] for r in regions)

    # 같은 장면이면 JPEG 잡음만 남아 상자가 없다
    ratio, boxes = screen_diff(encode_png(scene(False)), encode_jpeg(scene(False), 480))
    assert ratio < 0.005 and boxes == []

    # 고른 스텝: 증거가 없으면 썸네일로 비교한다 (s1은 양쪽 썸네일)
    (run / "thumbs").mkdir()
    (run / "thumbs" / "s1.jpg").write_bytes(encode_jpeg(scene(False), 480))
    picked = compare_runs(side(run), side(base), picked="auto", step="s1", differ=screen_diff)
    assert picked["screen"]["file"] == "thumbs/s1.jpg" and picked["screen"]["regions"] == []
    with pytest.raises(KeyError):
        compare_runs(side(run), side(base), picked="auto", step="s99")


def test_screen_diff_reports_reason_when_thumbnail_missing(tmp_path: Path) -> None:
    run, base = screen_runs(tmp_path / "a", thumbnail=False)
    screen = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)["screen"]
    assert screen["reason"] == "no_thumbnail"
    assert screen["baseline_step"] == "s2" and screen["baseline_file"] is None
    assert screen["file"] == "steps/s2_fail.png" and "diff_ratio" not in screen

    # 기준 쪽 썸네일이 정책으로 빠짐
    run, base = screen_runs(tmp_path / "b", thumbnail=False, base_omitted=True)
    result = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)
    assert result["screen"]["reason"] == "policy_omitted"
    assert_shape(result)

    # 기준 실행에 같은 호출 경로·노드 스텝이 없음
    run, base = screen_runs(tmp_path / "c", base_node="n_other")
    screen = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)["screen"]
    assert screen["reason"] == "no_matching_step" and screen["baseline_step"] is None

    # 이 실행에 증거가 없음 (파일이 지워졌거나 정책으로 생략)
    run, base = screen_runs(tmp_path / "d")
    (run / "steps" / "s2_fail.png").unlink()
    screen = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)["screen"]
    assert screen["reason"] == "no_evidence" and screen["file"] is None
    assert screen["baseline_file"] == "thumbs/s2.jpg"

    # 화면 비교 함수가 없으면 파일만 준다 (플랫폼 없는 환경)
    run, base = screen_runs(tmp_path / "e")
    screen = compare_runs(side(run), side(base), picked="auto")["screen"]
    assert screen["file"] and screen["baseline_file"] and "diff_ratio" not in screen
    assert "reason" not in screen

    # 실패 스텝이 없는 pass 실행은 화면 비교를 뺀다
    result = compare_runs(side(base), side(run), picked="user", differ=screen_diff)
    assert "screen" not in result

    # 이 실행 쪽 증거가 정책으로 생략됨 (비밀값 입력 스텝)
    runs = tmp_path / "f" / "runs"
    base = plant_run(
        runs, "base0001", events=[RUN_START, start("s1", "n_w"), end("s1", "found"), run_end()]
    )
    (base / "thumbs").mkdir()
    (base / "thumbs" / "s1.jpg").write_bytes(encode_jpeg(scene(False), 480))
    omitted = [{"kind": "screenshot", "reason": "secret_input"}]
    run = plant_run(
        runs,
        "fail0001",
        started_ms=60_000,
        verdict="fail",
        events=[
            RUN_START,
            start("s1", "n_w"),
            end("s1", None, "error", omitted=omitted),
            run_end("error", "s1"),
        ],
    )
    screen = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)["screen"]
    assert screen["reason"] == "policy_omitted" and screen["file"] is None


def test_screen_baseline_uses_last_iteration_with_thumbnail(tmp_path: Path) -> None:
    """반복 안 스텝: 기준 실행에서 같은 경로의 스텝 중 썸네일이 남아 있는 마지막 회차."""
    runs = tmp_path / "runs"
    body = []
    for i, step in enumerate(("s2", "s4", "s6")):
        loop_step = f"s{int(step[1:]) + 1}"
        body += [
            start(step, "n_w", iteration=i),
            end(step, "found", iteration=i),
            start(loop_step, "n_loop"),
            end(loop_step, "body" if i < 2 else "done"),
        ]
    events = [RUN_START, start("s1", "n_loop"), end("s1", "body"), *body, run_end()]
    base = plant_run(runs, "base0001", events=events)
    (base / "thumbs").mkdir()
    for step in ("s2", "s4"):
        (base / "thumbs" / f"{step}.jpg").write_bytes(encode_jpeg(scene(False), 480))
    run, _ = screen_runs(tmp_path / "other")
    screen = compare_runs(side(run), side(base), picked="user", differ=screen_diff)["screen"]
    # 마지막 회차 s6는 썸네일이 없다 → 썸네일이 남은 마지막 회차 s4 (파일 유무가 기준)
    assert screen["baseline_step"] == "s4" and screen["baseline_file"] == "thumbs/s4.jpg"
    assert screen["regions"] and overlap(screen["regions"][0], POPUP) > 0


# ---------------------------------------------------------------- 화면: 서브그래프 실패 (검수 High)


def scene_side(ran: SceneRun, run_id: str, started: str) -> RunSide:
    """실제 실행기가 남긴 이벤트·증거·썸네일 폴더를 끝난 실행 폴더 모양으로 맞춘다."""
    res = ran.result
    tail = {
        "event": "run.end",
        "verdict": res.verdict,
        "code": res.code,
        "reason": res.reason,
        "failure_step": res.failure_step,
        "failure_path": None if res.failure_path is None else list(res.failure_path),
        "finalized_by": "runner",
        "duration_ms": 1,
    }
    lines = []
    for i, event in enumerate([*ran.events, tail], start=1):
        line = {**event, "seq": i, "run": run_id}
        line.setdefault("t", started)
        lines.append(json.dumps(line, ensure_ascii=False))
    (ran.folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    data = {
        "format": "kookabug.run/0",
        "run_id": run_id,
        "graph": TEST,
        "status": "finished",
        "verdict": res.verdict,
        "started_at": started,
    }
    return RunSide(run_id, ran.folder, data, RunIndex(ran.folder).update())


def wait_sub(tgt: str) -> GraphBuilder:
    """서브그래프: 대기(timeout 0) → 찾으면 done(ok), 못 찾으면 failed(fail) 출구."""
    return (
        tk("subgraph", interface=subgraph_interface(exits={"done": "ok", "failed": "fail"}))
        .entry("n_w")
        .node(
            "n_w",
            "core.image.wait",
            inputs={"target": target(tgt), "timeout_ms": 0},
            next={"found": "n_ok", "timeout": "n_bad"},
        )
        .exit("n_ok", "done")
        .exit("n_bad", "failed")
    )


def call_graph() -> GraphBuilder:
    g = tk().entry("n_launch")
    g.node("n_launch", "core.app.launch", inputs={"path": "game.exe"}, next={"attached": "n_call"})
    g.call("n_call", "subs/s.graph.json", next={"done": "n_pass"})
    g.node("n_pass", "core.test.pass")
    return g


def test_subgraph_fail_exit_compares_inner_capture_thumbnail(tmp_path: Path) -> None:
    """서브그래프가 fail 출구로 나가 호출 스텝이 실패 스텝인 실행 (실제 실행기): 호출 스텝은 직접
    캡처하지 않아 썸네일이 없으므로, 증거를 캡처한 안쪽 대기 스텝의 경로로 기준 썸네일을 찾는다."""
    ok = run_scene(tmp_path / "a", call_graph(), subgraphs={"subs/s.graph.json": wait_sub(START)})
    bad = run_scene(
        tmp_path / "b", call_graph(), subgraphs={"subs/s.graph.json": wait_sub(LOGIN_TITLE)}
    )
    assert ok.result.verdict == "pass" and bad.result.verdict == "fail"
    base = scene_side(ok, "base0001", "2026-11-02T01:00:00.000Z")
    run = scene_side(bad, "fail0001", "2026-11-02T01:01:00.000Z")
    call = bad.step("n_call")
    assert run.index.failure_chain() == [call]
    inner = ok.step("n_w")
    assert ok.thumbs() == {f"thumbs/{inner}.jpg"}

    result = compare_runs(run, base, picked="auto", differ=screen_diff)
    assert_shape(result)
    screen = result["screen"]
    assert screen["step"] == call and screen["file"] == f"steps/{call}_fail.png"
    # 실제로 쓴 기준 스텝 = 안쪽 대기 (경로 [n_call, n_w])
    assert screen["baseline_step"] == inner and screen["baseline_file"] == f"thumbs/{inner}.jpg"
    assert base.index.rows[inner].path == ["n_call", "n_w"]
    assert "reason" not in screen
    # 두 실행 모두 같은 타이틀 화면을 찍었다
    assert screen["diff_ratio"] == pytest.approx(0.0, abs=0.01) and screen["regions"] == []


def test_call_step_without_inner_capture_uses_baseline_thumbnail_under_call(
    tmp_path: Path,
) -> None:
    """이 실행에서 증거를 캡처한 안쪽 스텝을 알 수 없으면(안쪽 증거·썸네일 없음) 기준 실행에서 그
    호출 경로 아래의 마지막 썸네일을 쓴다."""
    runs = tmp_path / "runs"
    call_end = {"graph": "snapshot/subs/s.graph.json"}
    base = plant_run(
        runs,
        "base0001",
        events=[
            RUN_START,
            start("s1", "n_call"),
            {**start("s2", "n_w", ["n_call", "n_w"]), "parent": "s1"},
            end("s2", "found"),
            {**start("s3", "n_x", ["n_call", "n_x"]), "parent": "s1"},
            end("s3", "found"),
            {**end("s1", "done"), **call_end},
            run_end(),
        ],
    )
    (base / "thumbs").mkdir()
    for step in ("s2", "s3"):
        (base / "thumbs" / f"{step}.jpg").write_bytes(encode_jpeg(scene(False), 480))
    run = plant_run(
        runs,
        "fail0001",
        started_ms=60_000,
        verdict="fail",
        events=[
            RUN_START,
            start("s1", "n_call"),
            {**start("s2", "n_w", ["n_call", "n_w"]), "parent": "s1"},
            end("s2", "found"),
            {
                **end("s1", "failed", "fail", artifacts=["steps/s1_fail.png"]),
                **call_end,
                "evidence": {
                    "last": "steps/s1_fail.png",
                    "mid": None,
                    "mid_missing": "no_sample_near_mid",
                },
            },
            run_end("fail", "s1"),
        ],
    )
    (run / "steps").mkdir()
    (run / "steps" / "s1_fail.png").write_bytes(encode_png(scene(True)))
    screen = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)["screen"]
    assert screen["step"] == "s1" and screen["file"] == "steps/s1_fail.png"
    assert screen["baseline_step"] == "s3" and screen["baseline_file"] == "thumbs/s3.jpg"
    assert overlap(screen["regions"][0], POPUP) > 0.6 * POPUP[2] * POPUP[3]


def test_inner_known_baseline_thumbnail_omitted_does_not_fall_to_other_node(
    tmp_path: Path,
) -> None:
    """이 실행에서 증거를 캡처한 안쪽 스텝(n_w)을 안다. 기준 실행의 같은 n_w는 정책으로 썸네일이
    빠졌고 그 뒤 n_x에 썸네일이 있다 → n_x와 비교하지 않고 `policy_omitted` (2라운드 검수 Mid)."""
    runs = tmp_path / "runs"
    call_end = {"graph": "snapshot/subs/s.graph.json"}

    def base_events(omitted: list[dict[str, str]] | None) -> list[dict[str, Any]]:
        extra = {} if omitted is None else {"omitted": omitted}
        return [
            RUN_START,
            start("s1", "n_call"),
            {**start("s2", "n_w", ["n_call", "n_w"]), "parent": "s1"},
            {**end("s2", "found"), **extra},
            {**start("s3", "n_x", ["n_call", "n_x"]), "parent": "s1"},
            end("s3", "found"),
            {**end("s1", "done"), **call_end},
            run_end(),
        ]

    evidence = {"last": "steps/s2_fail.png", "mid": None, "mid_missing": "no_sample_near_mid"}
    run = plant_run(
        runs,
        "fail0001",
        started_ms=60_000,
        verdict="fail",
        events=[
            RUN_START,
            start("s1", "n_call"),
            {**start("s2", "n_w", ["n_call", "n_w"]), "parent": "s1"},
            end("s2", "timeout", "fail", artifacts=["steps/s2_fail.png"], evidence=evidence),
            {
                **end("s1", "failed", "fail", artifacts=["steps/s1_fail.png"]),
                **call_end,
                "evidence": {**evidence, "last": "steps/s1_fail.png"},
            },
            run_end("fail", "s1"),
        ],
    )
    (run / "steps").mkdir()
    for name in ("s1_fail.png", "s2_fail.png"):
        (run / "steps" / name).write_bytes(encode_png(scene(True)))

    omitted = [{"kind": "thumbnail", "reason": "policy_off"}]
    base = plant_run(runs, "base0001", events=base_events(omitted))
    (base / "thumbs").mkdir()
    (base / "thumbs" / "s3.jpg").write_bytes(encode_jpeg(scene(False), 480))
    result = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)
    assert_shape(result)
    screen = result["screen"]
    assert screen["step"] == "s1" and screen["file"] == "steps/s1_fail.png"
    assert screen["baseline_step"] == "s2" and screen["baseline_file"] is None
    assert screen["reason"] == "policy_omitted"
    assert "diff_ratio" not in screen and "regions" not in screen

    # 정책 생략 표시 없이 썸네일만 없으면 no_thumbnail (역시 n_x로 넘어가지 않음)
    plain = plant_run(runs, "base0002", started_ms=1000, events=base_events(None))
    (plain / "thumbs").mkdir()
    (plain / "thumbs" / "s3.jpg").write_bytes(encode_jpeg(scene(False), 480))
    screen = compare_runs(side(run), side(plain), picked="user", differ=screen_diff)["screen"]
    assert screen["baseline_step"] == "s2" and screen["reason"] == "no_thumbnail"

    # 기준 실행에 그 안쪽 노드가 아예 없으면 no_matching_step (호출 스텝으로 대신하지 않음)
    other = plant_run(
        runs,
        "base0003",
        started_ms=2000,
        events=[
            RUN_START,
            start("s1", "n_call"),
            {**start("s2", "n_x", ["n_call", "n_x"]), "parent": "s1"},
            end("s2", "found"),
            {**end("s1", "done"), **call_end},
            run_end(),
        ],
    )
    (other / "thumbs").mkdir()
    (other / "thumbs" / "s2.jpg").write_bytes(encode_jpeg(scene(False), 480))
    screen = compare_runs(side(run), side(other), picked="user", differ=screen_diff)["screen"]
    assert screen["reason"] == "no_matching_step" and screen["baseline_step"] is None


# ---------------------------------------------------------------- 두 단계·읽기 실패 (검수 Low)


def test_prepare_does_no_hashing_or_image_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """색인 잠금 안에서 부르는 `prepare_compare`는 스냅샷 해시·화면 차이를 하지 않는다."""
    run, base = screen_runs(tmp_path)
    for folder in (run, base):
        (folder / "snapshot").mkdir()
        (folder / "snapshot" / "kookabug.json").write_text("{}", encoding="utf-8")

    def boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("잠금 안에서 무거운 일을 했다")

    monkeypatch.setattr(compare_mod, "snapshot_digest", boom)
    prepared = prepare_compare(side(run), side(base), picked="auto")
    assert "graph" not in prepared.result and "diff_ratio" not in prepared.result["screen"]
    monkeypatch.undo()
    result = finish_compare(prepared, differ=screen_diff)
    assert result["graph"]["same"] is True and result["screen"]["regions"]
    assert result == compare_runs(side(run), side(base), picked="auto", differ=screen_diff)


def test_unreadable_image_reports_reason(tmp_path: Path) -> None:
    run, base = screen_runs(tmp_path)
    (base / "thumbs" / "s2.jpg").write_bytes(b"not a jpeg")
    result = compare_runs(side(run), side(base), picked="auto", differ=screen_diff)
    assert_shape(result)
    screen = result["screen"]
    assert screen["reason"] == "image_unreadable" and "diff_ratio" not in screen
    assert screen["baseline_file"] == "thumbs/s2.jpg"
