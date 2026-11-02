"""실행 폴더 이름·`run_id`·`run.json` 원자적 교체 (구현 계획 M0b 2.8)."""

import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from kookabug_core.record import (
    create_run_folder,
    new_run_id,
    read_run_json,
    runfolder,
    write_run_json,
)
from kookabug_core.record.runfolder import (
    RUN_ID_ALPHABET,
    folder_name,
    graph_stem,
    run_id_of_folder,
)

KST = timezone(timedelta(hours=9))


def test_folder_name_utc_stem_runid(tmp_path: Path) -> None:
    started = datetime(2026, 10, 29, 15, 2, 11, 500000, tzinfo=KST)
    name = folder_name(started, "tests/inventory_open.graph.json", "r8k2x7qm")
    assert name == "2026-10-29T06-02-11_inventory_open_r8k2x7qm"
    assert graph_stem("tests\\a\\b.graph.json") == "b"
    assert graph_stem("x.json") == "x"
    assert run_id_of_folder(name) == "r8k2x7qm"
    assert run_id_of_folder("whatever") is None

    folder = create_run_folder(
        tmp_path / "runs", "tests/inventory_open.graph.json", now=started, new_id=lambda: "abcd1234"
    )
    assert folder.path == tmp_path / "runs" / "2026-10-29T06-02-11_inventory_open_abcd1234"
    assert folder.run_id == "abcd1234"
    assert {p.name for p in folder.path.iterdir()} == {"logs", "snapshot", "steps"}
    assert folder.events.name == "events.jsonl" and folder.run_json.name == "run.json"
    assert folder.input_recovery.name == "input-recovery.json"


def test_run_id_charset_and_collision_retry(tmp_path: Path) -> None:
    ids = {new_run_id() for _ in range(200)}
    assert all(re.fullmatch(r"[a-z0-9]{8}", i) for i in ids)
    assert len(ids) == 200
    assert set(RUN_ID_ALPHABET) == set("abcdefghijklmnopqrstuvwxyz0123456789")

    runs = tmp_path / "runs"
    # 다른 시각·그래프의 폴더라도 같은 run_id로 끝나면 다시 뽑는다
    (runs / "2020-01-01T00-00-00_old_aaaaaaaa").mkdir(parents=True)
    picks = iter(["aaaaaaaa", "bbbbbbbb"])
    folder = create_run_folder(runs, "tests/t.graph.json", new_id=lambda: next(picks))
    assert folder.run_id == "bbbbbbbb"
    with pytest.raises(ValueError, match="run_id"):
        create_run_folder(runs, "tests/t.graph.json", new_id=lambda: "UPPER123")
    with pytest.raises(RuntimeError):
        create_run_folder(runs, "tests/t.graph.json", new_id=lambda: "aaaaaaaa")


def test_run_json_atomic_replace(tmp_path: Path) -> None:
    path = tmp_path / "run.json"
    first = {"format": "kookabug.run/0", "status": "running", "pad": "x" * 200_000}
    second = {"format": "kookabug.run/0", "status": "finished", "pad": "y" * 200_000}
    write_run_json(path, first)
    assert read_run_json(path) == first
    assert path.read_text(encoding="utf-8").endswith("}\n")

    # 쓰는 동안 읽는 쪽은 언제나 이전 전체나 새 전체를 본다
    seen: set[str] = set()
    errors: list[str] = []
    done = threading.Event()

    def reader() -> None:
        while not done.is_set():
            try:
                text = path.read_text(encoding="utf-8")
            except PermissionError:
                continue  # Windows: 교체 순간 잠깐 열 수 없을 수 있다
            except FileNotFoundError:
                errors.append("파일이 사라졌다")
                continue
            try:
                seen.add(json.loads(text)["status"])
            except ValueError:
                errors.append("반쯤 쓰인 파일")

    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(30):
            write_run_json(path, second if i % 2 else first)
    finally:
        done.set()
        thread.join()
    assert errors == []
    assert seen <= {"running", "finished"}
    # 임시 파일이 남지 않는다
    assert [p.name for p in tmp_path.iterdir()] == ["run.json"]


def test_replace_retried_while_reader_holds_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows: 대상 파일을 연 프로세스가 있으면 교체가 잠깐 PermissionError다
    path = tmp_path / "run.json"
    real = os.replace
    failures = [PermissionError("열려 있음")] * 2

    def flaky(src: str, dst: object) -> None:
        if failures:
            raise failures.pop()
        real(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", flaky)
    write_run_json(path, {"status": "finished"})
    assert read_run_json(path) == {"status": "finished"}
    assert failures == []


def test_read_retried_while_replace_denies_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T11 검수 7: 교체 순간 읽기가 PermissionError면 공개 읽기 함수가 다시 읽는다
    (run.status 내부 오류로 새지 않게). 계속 거부되면 그 오류를 올린다."""
    path = tmp_path / "run.json"
    write_run_json(path, {"status": "finished"})
    real = Path.read_text
    failures = [PermissionError("교체 중")] * 3

    def flaky(self: Path, *args: Any, **kwargs: Any) -> str:
        if failures:
            raise failures.pop()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert read_run_json(path) == {"status": "finished"}
    assert failures == []

    def denied(self: Path, *args: Any, **kwargs: Any) -> str:
        raise PermissionError("거부")

    monkeypatch.setattr(runfolder, "READ_RETRY_S", 0.05)
    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(PermissionError):
        read_run_json(path)


def test_read_run_json_invalid_utf8_is_none(tmp_path: Path) -> None:
    """T11 검수 2차: UTF-8이 깨진 기록은 형식이 틀린 기록(None)이다 (재시도 수정 전과 같음)."""
    path = tmp_path / "run.json"
    path.write_bytes(b'{"status":"finished","pad":"\xff"}')
    assert read_run_json(path) is None
    path.write_bytes(b"\xef\xbb\xbf\xc3")  # 잘린 UTF-8
    assert read_run_json(path) is None


def test_read_run_json_never_raises_during_concurrent_replace(tmp_path: Path) -> None:
    """T11 검수 7: 쓰는 쪽이 계속 교체하는 동안 공개 읽기 함수는 이전 전체나 새 전체를 돌려준다."""
    path = tmp_path / "run.json"
    first = {"status": "running", "pad": "x" * 100_000}
    second = {"status": "finished", "pad": "y" * 100_000}
    write_run_json(path, first)
    errors: list[BaseException] = []
    seen: set[str] = set()
    done = threading.Event()

    def reader() -> None:
        while not done.is_set():
            try:
                value = read_run_json(path)
            except BaseException as exc:
                errors.append(exc)
                continue
            assert value is not None
            seen.add(value["status"])

    # 읽는 쪽 하나 (여럿이 쉬지 않고 열면 쓰는 쪽 교체가 기한 안에 끼어들지 못한다)
    thread = threading.Thread(target=reader)
    thread.start()
    try:
        for i in range(60):
            write_run_json(path, second if i % 2 else first)
    finally:
        done.set()
        thread.join()
    assert errors == []
    assert seen <= {"running", "finished"}


def test_write_failure_leaves_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "run.json"
    write_run_json(path, {"status": "running"})

    def boom(*_: object) -> None:
        raise OSError("교체 실패")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        write_run_json(path, {"status": "finished"})
    assert read_run_json(path) == {"status": "running"}
    assert [p.name for p in tmp_path.iterdir()] == ["run.json"]
    assert read_run_json(tmp_path / "missing.json") is None
    (tmp_path / "bad.json").write_text("[1]", encoding="utf-8")
    assert read_run_json(tmp_path / "bad.json") is None


def test_now_defaults_to_utc(tmp_path: Path) -> None:
    folder = create_run_folder(tmp_path, "t.graph.json")
    stamp = datetime.strptime(folder.path.name[:19], "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)
    assert abs(stamp - datetime.now(UTC)) < timedelta(minutes=1)
