"""실행 기록 사슬 (M7 계획 3.3a, B4): 실제 실행기 기록에서 호출 경계를 지키는 화면 간선만, 허용
필드만 읽기, 캐시 열쇠·삭제된 실행."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
from helpers.run_chain import chain_workspace, record_run

from kookabug_core import screen_map
from kookabug_core.screen_map import run_edges

EXPECTED = {
    ("world_field", "inventory", "subgraphs/open_inventory.graph.json", "ok"),
    ("lobby", "loading", "subgraphs/pick_server.graph.json", "ok"),
}


def edges(root: Path, **kw: Any) -> set[tuple[str, str, str, str]]:
    return {(e["from"], e["to"], e["call"], e["exit"]) for e in run_edges(root, **kw)}


@pytest.mark.parametrize("screenshots", ["on", "off"])
@pytest.mark.parametrize("video", ["on", "off"])
@pytest.mark.parametrize("redact", [True, False])
def test_chain_same_under_record_policies(
    tmp_path: Path, screenshots: str, video: str, redact: bool
) -> None:
    record = {"screenshots": screenshots, "video": video, "redact_secrets": redact}
    ws = chain_workspace(tmp_path / "ws", record=record)
    record_run(
        ws, ["enter_world", "open_inventory"], record={"screenshots": screenshots, "video": video}
    )
    assert edges(ws.root, use_cache=False) == EXPECTED


def test_nested_calls_do_not_chain_outward(tmp_path: Path) -> None:
    ws = chain_workspace(tmp_path / "ws")
    record_run(ws, ["enter_world", "open_inventory"])
    found = edges(ws.root)
    # 안쪽 마지막 화면(loading)은 바깥 다음 호출(inventory)과 잇지 않는다
    assert ("loading", "inventory") not in {(a, b) for a, b, _, _ in found}
    assert found == EXPECTED


def test_unscreened_exit_breaks_chain(tmp_path: Path) -> None:
    ws = chain_workspace(tmp_path / "ws")
    record_run(ws, ["enter_world", "no_screen", "open_inventory"])
    assert edges(ws.root) == {("lobby", "loading", "subgraphs/pick_server.graph.json", "ok")}


def test_repeat_counts_once_per_run_and_skips_control_runs(tmp_path: Path) -> None:
    ws = chain_workspace(tmp_path / "ws")
    record_run(ws, ["enter_world", "open_inventory", "enter_world", "open_inventory"])
    record_run(ws, ["enter_world", "open_inventory"])
    record_run(ws, ["enter_world", "open_inventory"], source="agent_control")
    item = next(e for e in run_edges(ws.root) if e["to"] == "inventory")
    assert item["count"] == 2  # 실행당 한 번, 에이전트 제어 실행은 빼고


class Strict(dict[str, Any]):
    """허용 밖 필드를 읽으면 실패하는 기록 (값을 꺼내거나 키 있음을 보거나 값 전체를 훑으면)."""

    FORBIDDEN = frozenset(
        {
            "outputs", "secret_paths", "reason", "message", "error", "evidence", "artifacts",
            "agent_withhold", "omitted", "nodes", "inputs", "text", "secret",
        }
    )  # fmt: skip

    def _guard(self, key: object) -> None:
        if key in self.FORBIDDEN:
            raise AssertionError(f"허용 밖 필드를 읽었다: {key}")

    def __getitem__(self, key: str) -> Any:
        self._guard(key)
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        self._guard(key)
        return super().get(key, default)

    def __contains__(self, key: object) -> bool:
        self._guard(key)
        return super().__contains__(key)

    def values(self) -> Any:  # type: ignore[override]
        for key in self.keys():
            self._guard(key)
        return super().values()

    def items(self) -> Any:  # type: ignore[override]
        for key in self.keys():
            self._guard(key)
        return super().items()


def test_reads_only_allowed_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ws = chain_workspace(tmp_path / "ws")
    folder = record_run(ws, ["enter_world", "open_inventory"])
    # 기록에 읽으면 안 되는 필드가 실제로 있다 (출력·비밀값 경로·사유·서브그래프 노드)
    raw = (folder / "events.jsonl").read_text(encoding="utf-8")
    assert '"outputs"' in raw
    assert "secret_paths" in (folder / "run.json").read_text(encoding="utf-8")
    seen: list[int] = []

    def strict(text: str) -> Any:
        seen.append(1)
        return json.loads(text, object_hook=Strict)

    monkeypatch.setattr(screen_map, "_loads", strict)
    assert edges(ws.root, use_cache=False) == EXPECTED
    assert len(seen) > 10  # 실제로 그 읽기 함수를 거쳤다
    # 대조: 허용 밖 필드를 읽으면 실패한다
    with pytest.raises(AssertionError):
        Strict({"outputs": {}}).get("outputs")


def test_graph_path_outside_run_and_junctions_ignored(tmp_path: Path) -> None:
    """B4 검수 Low 3: `graph` 값의 `..`·절대 경로는 읽지 않고, `runs/`의 정션은 따라가지 않는다."""
    import _winapi

    ws = chain_workspace(tmp_path / "ws")
    folder = record_run(ws, ["enter_world", "open_inventory"])
    # 실행 폴더 밖의 가짜 서브그래프 (읽히면 screen "outside"가 간선에 나온다)
    outside = tmp_path / "evil.graph.json"
    outside.write_text(
        json.dumps({"interface": {"exits": {"ok": {"kind": "ok", "screen": "outside"}}}}),
        encoding="utf-8",
    )
    events = (folder / "events.jsonl").read_text(encoding="utf-8")
    for bad in ("snapshot/../../../../evil.graph.json", str(outside).replace("\\", "/")):
        patched = events.replace("snapshot/subgraphs/open_inventory.graph.json", bad)
        (folder / "events.jsonl").write_text(patched, encoding="utf-8")
        found = edges(ws.root, use_cache=False)
        assert all("outside" not in (a, b) for a, b, _, _ in found), bad
    # runs/ 아래 정션 (다른 곳의 실행 폴더) 은 보지 않는다
    other = chain_workspace(tmp_path / "other")
    elsewhere = record_run(other, ["enter_world", "open_inventory"], run_id="jjjjjjjj")
    shutil.rmtree(folder)
    _winapi.CreateJunction(str(elsewhere), str(ws.root / "runs" / elsewhere.name))
    assert edges(ws.root, use_cache=False) == set()


def test_deleted_run_dropped_from_cache_and_map(tmp_path: Path) -> None:
    ws = chain_workspace(tmp_path / "ws")
    first = record_run(ws, ["enter_world", "open_inventory"])
    record_run(ws, ["enter_world", "no_screen", "open_inventory"])
    assert edges(ws.root) == EXPECTED
    cache = ws.root / ".kookabug/cache/screen-map-runs.json"
    assert first.name in json.loads(cache.read_text(encoding="utf-8"))["runs"]
    shutil.rmtree(first)  # 보관 정책·사람 삭제
    assert edges(ws.root) == {("lobby", "loading", "subgraphs/pick_server.graph.json", "ok")}
    assert first.name not in json.loads(cache.read_text(encoding="utf-8"))["runs"]


def test_cache_key_invalidates_on_change(tmp_path: Path) -> None:
    ws = chain_workspace(tmp_path / "ws")
    folder = record_run(ws, ["enter_world", "no_screen", "open_inventory"])
    assert ("world_field", "inventory") not in {(a, b) for a, b, _, _ in edges(ws.root)}
    # 캐시가 쓰였는지: 기록을 바꾸지 않고 캐시 내용을 지어내면 그대로 쓴다 (열쇠가 같으니까)
    cache = ws.root / ".kookabug/cache/screen-map-runs.json"
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["runs"][folder.name]["edges"].append(["a", "b", "subgraphs/x.graph.json", "ok"])
    cache.write_text(json.dumps(data), encoding="utf-8")
    assert ("a", "b") in {(x, y) for x, y, _, _ in edges(ws.root)}
    # events.jsonl 크기가 바뀌면 다시 읽는다 (지어낸 간선이 사라짐)
    other = record_run(ws, ["enter_world", "open_inventory"], run_id="zzzzzzzz")
    shutil.copy(other / "events.jsonl", folder / "events.jsonl")
    shutil.rmtree(other)
    found = {(x, y) for x, y, _, _ in edges(ws.root)}
    assert ("a", "b") not in found and ("world_field", "inventory") in found
    # run.json 수정 시각만 바뀌어도 다시 읽는다
    data = json.loads(cache.read_text(encoding="utf-8"))
    data["runs"][folder.name]["edges"].append(["c", "d", "subgraphs/x.graph.json", "ok"])
    cache.write_text(json.dumps(data), encoding="utf-8")
    stat = (folder / "run.json").stat()
    os.utime(folder / "run.json", ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000))
    assert ("c", "d") not in {(x, y) for x, y, _, _ in edges(ws.root)}
