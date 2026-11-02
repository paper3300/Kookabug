"""기록 읽기 `RunRecords` 단위 검사 (M3 T7 검수 Low, T11): 영상이 있는 실행의 `run.index`,
끝난 실행의 메모리 색인 정리, `run.export`의 `dest`가 `runs/` 안이면 거부.

daemon 프로세스 없이 `RunRecords`를 바로 부른다 (메서드 처리기는 이것을 스레드에서 부를 뿐이다).
"""

from __future__ import annotations

import ctypes
import json
import shutil
import sys
from pathlib import Path
from typing import Any, cast

import pytest

from kookabug_core.record.index import index_cache_file
from kookabug_core.schema.shape import check_shape
from kookabug_daemon.protocol import InvalidParams
from kookabug_daemon.run_index import Located, RunRecords

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "run-history"


def plant(root: Path, name: str) -> tuple[str, Path]:
    source = FIXTURES / name
    run_id = json.loads((source / "run.json").read_text(encoding="utf-8"))["run_id"]
    folder = root / "runs" / f"2026-11-02T01-00-00_t_{run_id}"
    shutil.copytree(source, folder)
    return run_id, folder


class Locator:
    """실행 ID → (폴더, 상태). 검사가 상태를 바꾼다."""

    def __init__(self) -> None:
        self.runs: dict[str, tuple[Path, str]] = {}

    def __call__(self, run_id: str) -> Located:
        folder, state = self.runs[run_id]
        return Located(run_id, folder, state)  # type: ignore[arg-type]


def records(tmp_path: Path) -> tuple[RunRecords, Locator, Path]:
    root = tmp_path / "ws"
    (root / "runs").mkdir(parents=True)
    locate = Locator()
    return RunRecords(root, locate), locate, root


SEGMENT = {
    "bytes": 1234,
    "file": "seg-0001.mp4",
    "frame_ms": 200,
    "frames": 15,
    "mode": "failed_only",
    "size": [160, 96],
    "t0": "2026-11-02T01:00:00.000Z",
    "t_end": "2026-11-02T01:00:03.000Z",
    "window": "SampleRPG",
}
GAP = {
    "gap": "secret_input",
    "step": "s3",
    "t_start": "2026-11-02T01:00:03.000Z",
    "t_end": "2026-11-02T01:00:04.000Z",
}


def test_run_index_video_view_finalized_and_segments_only(tmp_path: Path) -> None:
    """`run.index.video`가 null이 아닌 두 경우: 마무리한 `index.json`, 마무리 전
    `segments.jsonl`만."""
    rec, locate, root = records(tmp_path)
    done_id, done = plant(root, "m2-login-fail")
    locate.runs[done_id] = (done, "ended")
    video = done / "video"
    video.mkdir()
    (video / "seg-0001.mp4").write_bytes(b"\0" * 1234)
    index = {
        "bytes": 1234,
        "deleted": [],
        "format": "kookabug.video-index/0",
        "gaps": [GAP],
        "segments": [SEGMENT],
        "status": "recorded",
    }
    (video / "index.json").write_text(json.dumps(index), encoding="utf-8")
    result = rec.index(done_id)
    assert check_shape(result, "run-index") == []
    assert result["video"] == {
        "finalized": True,
        "status": "recorded",
        "segments": [SEGMENT],
        "gaps": [GAP],
    }

    # 아무도 마무리하지 못한 폴더: segments.jsonl만 (파일이 있는 조각만)
    other_root = tmp_path / "ws2"
    (other_root / "runs").mkdir(parents=True)
    rec2 = RunRecords(other_root, locate)
    raw_id, raw = plant(other_root, "m2-swapped-target-timeout")
    locate.runs[raw_id] = (raw, "ended")
    video = raw / "video"
    video.mkdir()
    (video / "seg-0001.mp4").write_bytes(b"\0" * 1234)
    gone = {**SEGMENT, "file": "seg-0002.mp4", "t0": "2026-11-02T01:00:04.000Z"}
    lines = [SEGMENT, GAP, gone]
    (video / "segments.jsonl").write_text(
        "".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8"
    )
    result = rec2.index(raw_id)
    assert check_shape(result, "run-index") == []
    view: dict[str, Any] = result["video"]
    assert view["finalized"] is False
    assert [s["file"] for s in view["segments"]] == ["seg-0001.mp4"]
    assert view["gaps"] == [GAP]
    assert view["status"] == "recorded"


def test_live_index_moved_to_cache_after_run_ends(tmp_path: Path) -> None:
    """진행 중에 읽힌 실행이 끝나면, 그 실행을 다시 읽지 않아도 다른 기록 읽기나 `finish`가 메모리
    색인을 캐시로 옮긴다 (daemon이 끝날 때까지 남지 않음)."""
    rec, locate, root = records(tmp_path)
    a_id, a = plant(root, "m2-login-fail")
    b_id, b = plant(root, "m2-inventory-pass")
    locate.runs[a_id] = (a, "running")
    locate.runs[b_id] = (b, "running")
    assert rec.index(a_id)["state"] == "running"
    assert rec.index(b_id)["state"] == "running"
    assert set(rec._live) == {a_id, b_id}  # pyright: ignore[reportPrivateUsage]

    # a가 끝났다: b를 읽는 것만으로 a의 메모리 색인이 캐시로 옮겨진다
    locate.runs[a_id] = (a, "ended")
    rec.index(b_id)
    assert set(rec._live) == {b_id}  # pyright: ignore[reportPrivateUsage]
    assert index_cache_file(root, a_id).is_file()
    assert rec.index(a_id)["state"] == "ended"

    # 감독자 마무리 뒤 finish: 다시 읽지 않아도 정리된다
    locate.runs[b_id] = (b, "ended")
    rec.finish(b_id)
    assert rec._live == {}  # pyright: ignore[reportPrivateUsage]
    assert index_cache_file(root, b_id).is_file()
    rec.finish(b_id)  # 두 번 불러도 같다


def test_workspace_retention_values_and_defaults(tmp_path: Path) -> None:
    """상태 바 "보관: 통과 N일 · 실패 M일" (`workspace.info.retention`): 정한 값, 없는 값은
    기본값."""
    root = tmp_path / "ws"
    root.mkdir()
    body = {"format": "kookabug.workspace/0", "retention": {"passed_days": 7}}
    (root / "kookabug.json").write_text(json.dumps(body), encoding="utf-8")
    from kookabug_core.workspace import Workspace

    assert Workspace.open(root).retention() == {
        "passed_days": 7,
        "failed_days": 60,
        "keep_last": 50,
    }


def _short_path(path: Path) -> str | None:
    if sys.platform != "win32":
        return None
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, 1024)
    if n == 0 or n >= 1024:
        return None
    return buf.value


def test_run_export_refuses_dest_inside_runs(tmp_path: Path) -> None:
    """T7 검수 Low: `dest`가 실행 폴더나 `runs/` 안이면 `invalid_params`이고 아무것도 만들지 않는다
    (8.3 짧은 이름으로 써도 같은 폴더로 본다). 밖이면 내보낸다."""
    rec, locate, root = records(tmp_path)
    run_id, folder = plant(root, "m2-login-fail")
    locate.runs[run_id] = (folder, "ended")
    (folder / "steps").mkdir(exist_ok=True)
    before = sorted(p.name for p in folder.rglob("*"))
    targets = [folder / "bundle.zip", root / "runs" / "bundle.zip", folder / "steps" / "b.zip"]
    short = _short_path(folder)
    if short is not None and short != str(folder):
        targets.append(Path(short) / "short.zip")
    for dest in targets:
        with pytest.raises(InvalidParams):
            rec.export(run_id, str(dest))
    assert sorted(p.name for p in folder.rglob("*")) == before
    assert sorted(p.name for p in (root / "runs").iterdir()) == [folder.name]

    out = tmp_path / "out"
    out.mkdir()
    result = rec.export(run_id, str(out / "run.zip"))
    assert result["bytes"] == (out / "run.zip").stat().st_size
    # 워크스페이스 안이어도 runs/ 밖이면 된다
    assert rec.export(run_id, str(root / "bundle.zip"))["bytes"] > 0


@pytest.mark.skipif(sys.platform != "win32", reason="정션은 Windows")
def test_run_export_refuses_junction_alias_to_run_folder(tmp_path: Path) -> None:
    """T11 검수 5: 바깥 정션이 `runs/` 자체가 아니라 그 아래 실행 폴더를 가리켜도 거부한다
    (문자열 부모 사슬은 바깥이지만 실제 경로는 runs/ 안)."""
    import _winapi

    rec, locate, root = records(tmp_path)
    run_id, folder = plant(root, "m2-login-fail")
    locate.runs[run_id] = (folder, "ended")
    other = root / "runs" / "other_record"
    other.mkdir()
    aliases = {tmp_path / "alias_other": other, tmp_path / "alias_self": folder}
    for link, target in aliases.items():
        _winapi.CreateJunction(str(target), str(link))
    try:
        for link, target in aliases.items():
            before = sorted(p.name for p in target.iterdir())
            with pytest.raises(InvalidParams):
                rec.export(run_id, str(link / "bundle.zip"))
            assert sorted(p.name for p in target.iterdir()) == before
        # 정션 아래 하위 폴더도 같다
        (other / "sub").mkdir()
        with pytest.raises(InvalidParams):
            rec.export(run_id, str(tmp_path / "alias_other" / "sub" / "b.zip"))
        assert list((other / "sub").iterdir()) == []
    finally:
        for link in aliases:
            link.rmdir()


def test_run_list_skips_run_json_with_invalid_utf8(tmp_path: Path) -> None:
    """T11 검수 2차: UTF-8이 깨진 run.json 하나가 run.list 전체를 깨지 않고 건너뛰어진다."""
    from kookabug_daemon.runs import RunManager

    _rec, _locate, root = records(tmp_path)
    run_id, _folder = plant(root, "m2-login-fail")
    broken = root / "runs" / "2026-11-02T02-00-00_t_aaaa1111"
    broken.mkdir()
    (broken / "run.json").write_bytes(b'{"status":"finished","pad":"\xff"}')
    manager = RunManager(root, cast(Any, None), cast(Any, None), lambda: cast(Any, None))
    try:
        result = manager.list_runs()
    finally:
        manager.close()
    assert [r["run_id"] for r in result["runs"]] == [run_id]
