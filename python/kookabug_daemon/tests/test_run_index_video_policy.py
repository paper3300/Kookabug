"""기록 뷰어 상태 바의 실효 영상 정책 (M4 T12): `run.index` `video_policy`는 실행 스냅샷의
`kookabug.json` → 테스트 그래프 `record`로 정한 실행 단위 값과 그 층이다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from helpers.daemon_runs import TEST, RunRig

from kookabug_daemon.run_index import video_policy

pytestmark = pytest.mark.process


def plant(
    root: Path,
    run_id: str,
    ws_record: dict[str, Any] | None,
    graph_record: dict[str, Any] | None,
    *,
    snapshot: bool = True,
) -> Path:
    folder = root / "runs" / f"2026-11-05T01-00-00_t_{run_id}"
    folder.mkdir(parents=True)
    events = [
        {"event": "run.start", "graph": TEST, "protocol": 1, "runner": {"pid": 1}},
    ]
    lines = [
        json.dumps({**e, "seq": i, "run": run_id, "t": f"2026-11-05T01:00:00.{i:03d}Z"})
        for i, e in enumerate(events, start=1)
    ]
    (folder / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_json = {
        "format": "kookabug.run/0",
        "graph": TEST,
        "run_id": run_id,
        "started_at": "2026-11-05T01:00:00.001Z",
        "status": "running",
    }
    (folder / "run.json").write_text(json.dumps(run_json), encoding="utf-8")
    if snapshot:
        snap = folder / "snapshot"
        ws: dict[str, Any] = {"format": "kookabug.workspace/0"}
        if ws_record is not None:
            ws["record"] = ws_record
        (snap / "tests").mkdir(parents=True)
        (snap / "kookabug.json").write_text(json.dumps(ws), encoding="utf-8")
        graph: dict[str, Any] = {"format": "kookabug.graph/0", "kind": "test", "nodes": {}}
        if graph_record is not None:
            graph["record"] = graph_record
        (snap / TEST).write_text(json.dumps(graph), encoding="utf-8")
    return folder


@pytest.mark.parametrize(
    ("ws_record", "graph_record", "expected"),
    [
        (None, None, {"mode": "failed_only", "source": None}),
        ({"video": "off"}, None, {"mode": "off", "source": "kookabug.json#/record"}),
        (
            {"video": "on"},
            {"video": "failed_only"},
            {"mode": "failed_only", "source": f"{TEST}#/record"},
        ),
        ({"video": "off"}, {"video": "on"}, {"mode": "off", "source": "kookabug.json#/record"}),
        # 명시한 on은 워크스페이스 기본값이 아니라 kookabug.json이 정한 것 (B4 검수 Mid 2)
        ({"video": "on"}, None, {"mode": "on", "source": "kookabug.json#/record"}),
        ({"video": "on"}, {"video": "on"}, {"mode": "on", "source": "kookabug.json#/record"}),
        ({"screenshots": "on"}, None, {"mode": "failed_only", "source": None}),
    ],
    ids=[
        "기본값",
        "워크스페이스 끔",
        "테스트 실패만",
        "아래 on은 못 이김",
        "워크스페이스 켬",
        "워크스페이스·테스트 켬",
        "video 없는 record",
    ],
)
def test_video_policy_from_snapshot(
    tmp_path: Path,
    ws_record: dict[str, Any] | None,
    graph_record: dict[str, Any] | None,
    expected: dict[str, Any],
) -> None:
    folder = plant(tmp_path, "pol00001", ws_record, graph_record)
    assert video_policy(folder, {"graph": TEST}) == expected


def test_run_index_effective_video_policy(tmp_path: Path) -> None:
    rig = RunRig.make(tmp_path)
    plant(rig.root, "pol00002", {"video": "off"}, None)
    plant(rig.root, "pol00003", None, None, snapshot=False)
    with rig.daemon() as d, d.client() as client:
        index = client.call("run.index", {"run_id": "pol00002"})
        assert index["video_policy"] == {"mode": "off", "source": "kookabug.json#/record"}
        # 스냅샷이 없는 옛 실행은 키가 없다
        old = client.call("run.index", {"run_id": "pol00003"})
        assert "video_policy" not in old
