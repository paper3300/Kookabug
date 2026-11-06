"""기록 읽기 (M3 계획 2.7): `run.index`·`run.children`·`run.step`·`run.file`·`run.export`, 지난
성공과 비교 `run.compare` (2.8, 코어 `record.compare`에 화면 차이 함수를 넘긴다).

- 색인은 코어 `record.index`가 만든다. 끝난 실행은 `.kookabug/cache/runs/<run_id>.index.json`
  캐시(이벤트 파일 크기·수정 시각이 같으면 다시 쓰지 않음)를, 진행 중 실행은 메모리 색인을 쓰고
  읽을 때마다 새로 쓰인 완전한 줄만 더 읽어 늘린다. 실행이 끝나면 메모리 색인을 캐시로 옮긴다
  (이 daemon이 띄운 실행은 감독자 마무리 뒤 `finish`, 아니면 다음 기록 읽기가 정리한다)
- 실행이 끝났는지는 실행 관리(`RunManager.locate`)가 정한다: 이 daemon이 띄운 실행은 감독자 마무리,
  아니면 `run.json`이 `finished`이거나 runner가 없음
- 실행 폴더 기준 파일 경로는 `kbimg://ws/<run_dir>/<경로>`로 연다 (`run_dir` = `runs/<폴더>`)
- `run.export`는 진행 중 실행을 거부한다(`run_active`). `dest`가 `runs/` 아래면 거부한다(실행
  폴더는 기록이라 고치지 않는다). zip은 `dest` 옆 임시 파일에 쓰고 끝나면 replace한다.
  에이전트 연결은 전송이 판정 전에 거부하므로(`AGENT_DENIED`) 여기까지 오지 않는다
"""

from __future__ import annotations

import os
import tempfile
import threading
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Final

from kookabug_core.canonical import loads_strict
from kookabug_core.record import read_run_json
from kookabug_core.record.compare import (
    Picked,
    RunSide,
    ScreenDiffer,
    compare_cache_file,
    finish_compare,
    pick_baseline,
    prepare_compare,
    read_compare_cache,
    snapshot_cache_file,
    write_compare_cache,
)
from kookabug_core.record.index import (
    MAX_PAGE,
    RunIndex,
    RunState,
    cached_index,
    index_cache_file,
    thumbnails,
    video_view,
    write_cache,
)
from kookabug_core.record.runfolder import EVENTS_FILE, RUN_JSON_FILE, SNAPSHOT_DIR
from kookabug_core.workspace import WORKSPACE_FILE
from kookabug_daemon.documents import RUNS_NAME
from kookabug_daemon.protocol import InvalidParams, RequestFailed

__all__ = ["FILE_LIMIT", "Located", "RunRecords"]

FILE_LIMIT: Final = 1024 * 1024
"""`run.file`이 돌려주는 글자의 최대 바이트."""
KEEP_INDEXES: Final = 4
"""메모리에 남기는 끝난 실행 색인 수 (쪽 넘김이 캐시 파일을 매번 다시 읽지 않게)."""
_STORED: Final = frozenset({".mp4", ".jpg", ".jpeg", ".png", ".zip"})
"""이미 압축된 파일은 zip에 그대로 넣는다."""


@dataclass(frozen=True, slots=True)
class Located:
    """실행 폴더와 지금 상태."""

    run_id: str
    folder: Path
    state: RunState


@dataclass(eq=False, slots=True)
class _Entry:
    index: RunIndex
    lock: threading.Lock
    state: RunState


class RunRecords:
    """실행 기록 읽기. 메서드는 막히는 호출이다 (스레드에서 부른다)."""

    def __init__(self, root: Path, locate: Callable[[str], Located]) -> None:
        self.root = root
        self.locate = locate
        self._lock = threading.Lock()
        self._live: dict[str, _Entry] = {}
        """진행 중 실행의 메모리 색인."""
        self._ended: OrderedDict[str, _Entry] = OrderedDict()
        """최근에 읽은 끝난 실행 색인 (`KEEP_INDEXES`개)."""

    # ---------------------------------------------------------------- 색인

    def _index(self, run_id: str) -> tuple[Located, _Entry]:
        where = self.locate(run_id)
        self._sweep_live(run_id)
        if where.state == "running":
            with self._lock:
                entry = self._live.get(run_id)
                if entry is None:
                    entry = self._live[run_id] = _Entry(
                        RunIndex(where.folder), threading.Lock(), "running"
                    )
            # 파일 읽기는 그 실행의 잠금만 잡는다 (다른 실행의 기록 읽기를 막지 않게)
            with entry.lock:
                entry.index.update()
            return where, entry
        with self._lock:
            live = self._live.pop(run_id, None)
            cached = self._ended.get(run_id)
        if live is not None:
            entry = self._to_ended(run_id, live)
        elif cached is not None and _same_file(cached.index):
            entry = cached
        else:
            index = cached_index(where.folder, index_cache_file(self.root, run_id))
            entry = _Entry(index, threading.Lock(), "ended")
        self._keep(run_id, entry)
        return where, entry

    def _to_ended(self, run_id: str, live: _Entry) -> _Entry:
        """끝난 실행의 메모리 색인을 마저 읽어 캐시로 옮긴다."""
        with live.lock:
            live.index.update()
            write_cache(live.index, index_cache_file(self.root, run_id))
            return _Entry(live.index, live.lock, "ended")

    def _keep(self, run_id: str, entry: _Entry) -> None:
        with self._lock:
            self._ended[run_id] = entry
            self._ended.move_to_end(run_id)
            while len(self._ended) > KEEP_INDEXES:
                self._ended.popitem(last=False)

    def _sweep_live(self, skip: str) -> None:
        """진행 중에 읽힌 뒤 끝난 실행의 메모리 색인을 캐시로 옮긴다 (그 실행을 다시 읽지 않아도
        daemon이 끝날 때까지 남지 않게). 이 daemon이 띄운 실행은 감독자 마무리가 `finish`를
        부른다."""
        with self._lock:
            others = [rid for rid in self._live if rid != skip]
        for rid in others:
            try:
                state = self.locate(rid).state
            except Exception:
                state = "ended"  # 폴더가 사라졌다: 버린다
            if state == "running":
                continue
            self.finish(rid)

    def finish(self, run_id: str) -> None:
        """실행이 끝났다: 메모리 색인이 있으면 캐시로 옮긴다 (없으면 할 일 없음)."""
        with self._lock:
            live = self._live.pop(run_id, None)
        if live is None:
            return
        try:
            entry = self._to_ended(run_id, live)
        except OSError:
            return  # 캐시를 못 써도 다음 읽기가 파일에서 다시 만든다
        self._keep(run_id, entry)

    def forget(self, run_id: str) -> None:
        """메모리 색인을 버린다 (다음 읽기가 파일·캐시에서 다시 만든다)."""
        with self._lock:
            self._live.pop(run_id, None)
            self._ended.pop(run_id, None)

    def run_dir(self, folder: Path) -> str:
        """실행 폴더의 워크스페이스 기준 경로 ('/' 구분)."""
        try:
            return folder.relative_to(self.root).as_posix()
        except ValueError:
            return Path(os.path.relpath(folder, self.root)).as_posix()

    def index(self, run_id: str) -> dict[str, Any]:
        where, entry = self._index(run_id)
        run_json = read_run_json(where.folder / RUN_JSON_FILE)
        video = video_view(where.folder)
        thumbs = thumbnails(where.folder)
        policy = video_policy(where.folder, run_json)
        with entry.lock:
            result = entry.index.result(
                run_dir=self.run_dir(where.folder),
                state=entry.state,
                run_json=run_json,
                video=video,
                thumbs=thumbs,
            )
        if policy is not None:
            result["video_policy"] = policy
        return result

    def children(
        self, run_id: str, parent: str, iteration: int | None, offset: int, limit: int
    ) -> dict[str, Any]:
        where, entry = self._index(run_id)
        thumbs = thumbnails(where.folder)
        with entry.lock:
            try:
                total, steps = entry.index.children(
                    parent,
                    iteration,
                    offset,
                    min(limit, MAX_PAGE),
                    state=entry.state,
                    thumbs=thumbs,
                )
            except KeyError as exc:
                raise InvalidParams(f"실행 {run_id}에 스텝 {parent}이(가) 없다") from exc
        return {"offset": offset, "total": total, "steps": steps}

    def step(self, run_id: str, step: str) -> dict[str, Any]:
        where, entry = self._index(run_id)
        thumbs = thumbnails(where.folder)
        with entry.lock:
            row = entry.index.rows.get(step)
            if row is None:
                raise InvalidParams(f"실행 {run_id}에 스텝 {step}이(가) 없다")
            node = entry.index.node_json(row, entry.state, thumbs)
            events = entry.index.step_events(step)
        return {
            "run_dir": self.run_dir(where.folder),
            "step": node,
            "events": events,
            "ocr_text": _read_text(where.folder / "steps" / f"{step}_ocr.txt"),
            "thumbnail": f"thumbs/{step}.jpg" if step in thumbs else None,
        }

    # ---------------------------------------------------------------- 비교 (M3 2.8)

    def compare(
        self, run_id: str, baseline: str | None, step: str | None, *, cache_result: bool = True
    ) -> dict[str, Any]:
        """`run.compare`: 지난 성공(또는 고른 실행)과의 차이. 두 실행이 다 끝났으면 결과를
        `.kookabug/cache/runs/<run_id>.compare.json`에 두고 다시 쓴다. `cache_result=False`
        (에이전트용 `run.diff`)면 그 결과 캐시를 읽지도 쓰지도 않는다 (UI 결과와 나눈다, M5
        3.5)."""
        where, entry = self._index(run_id)
        run_json = read_run_json(where.folder / RUN_JSON_FILE) or {}
        picked: Picked
        if baseline is not None:
            if baseline == run_id:
                raise InvalidParams("기준 실행은 비교할 실행과 달라야 한다")
            base_where: Located | None = self.locate(baseline)
            picked = "user"
        else:
            found = pick_baseline(self.root / RUNS_NAME, run_json)
            base_where = None if found is None else self.locate(found[0])
            picked = "auto"
        if base_where is not None and base_where.state == "running":
            raise RequestFailed(
                "run_active",
                f"진행 중인 실행 {base_where.run_id}은(는) 기준으로 쓸 수 없다",
                run_id=base_where.run_id,
            )
        base_id = None if base_where is None else base_where.run_id
        base_folder = None if base_where is None else base_where.folder
        cache = compare_cache_file(self.root, run_id)
        cacheable = where.state == "ended" and cache_result
        if cacheable:
            hit = read_compare_cache(cache, where.folder, base_folder, base_id, step, picked)
            if hit is not None:
                return hit
        base_entry = None if base_id is None else self._index(base_id)[1]
        entries = sorted(
            [(run_id, entry)] + ([] if base_entry is None else [(str(base_id), base_entry)]),
            key=lambda item: item[0],
        )
        base_json = None if base_where is None else read_run_json(base_where.folder / RUN_JSON_FILE)
        with ExitStack() as stack:
            # 두 색인을 실행 ID 순으로 잠근다 (반대쪽 비교와 엇갈려 막히지 않게). 잠금 안에서는
            # 색인에서 꺼낼 것만 하고 스냅샷 해시·이미지 읽기·화면 차이는 잠금 밖에서 한다
            for _, held in entries:
                stack.enter_context(held.lock)
            run = RunSide(run_id, where.folder, run_json, entry.index)
            base = None
            if base_where is not None and base_entry is not None:
                base = RunSide(
                    base_where.run_id, base_where.folder, base_json or {}, base_entry.index
                )
            try:
                prepared = prepare_compare(run, base, picked=picked, step=step)
            except KeyError as exc:
                raise InvalidParams(f"실행 {run_id}에 스텝 {step}이(가) 없다") from exc
        result = finish_compare(
            prepared,
            differ=_screen_differ(),
            snapshot_cache=lambda rid: snapshot_cache_file(self.root, rid),
        )
        if cacheable:
            write_compare_cache(cache, where.folder, base_folder, base_id, step, picked, result)
        return result

    # ---------------------------------------------------------------- 파일

    def file(self, run_id: str, name: str) -> dict[str, Any]:
        where = self.locate(run_id)
        path = where.folder / (RUN_JSON_FILE if name == "run.json" else EVENTS_FILE)
        try:
            with path.open("rb") as f:
                size = os.fstat(f.fileno()).st_size
                if name == "run.json":
                    data = f.read(FILE_LIMIT)
                else:
                    f.seek(max(0, size - FILE_LIMIT))
                    data = f.read(FILE_LIMIT)
        except FileNotFoundError:
            raise RequestFailed("not_found", f"{path.name}이(가) 없다", path=path.name) from None
        except OSError as exc:
            raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
        truncated = size > len(data)
        if truncated and name != "run.json":
            # 잘린 앞 줄은 버린다 (완전한 줄만)
            cut = data.find(b"\n")
            data = data[cut + 1 :] if cut >= 0 else b""
        return {
            "text": data.decode("utf-8", errors="replace"),
            "bytes": size,
            "truncated": truncated,
        }

    def export(self, run_id: str, dest: str) -> dict[str, Any]:
        """실행 폴더를 zip으로 `dest`에 쓴다 (같은 폴더 임시 파일 + replace)."""
        where = self.locate(run_id)
        if where.state == "running":
            raise RequestFailed(
                "run_active", f"진행 중인 실행 {run_id}은(는) 내보낼 수 없다", run_id=run_id
            )
        target = Path(dest)
        if not target.is_absolute() or target.name == "":
            raise InvalidParams(f"dest는 절대 경로 파일이어야 한다: {dest}")
        if not target.parent.is_dir():
            text = f"저장할 폴더가 없다: {target.parent}"
            raise RequestFailed("io_error", text, message=text)
        if _inside(target.parent, self.root / RUNS_NAME):
            # 실행 폴더는 기록이라 고치지 않는다 (zip이 자기 임시 파일을 담는 일도 없게)
            raise InvalidParams(f"실행 기록 폴더(runs/) 안에는 내보낼 수 없다: {dest}")
        try:
            fd, temp = tempfile.mkstemp(dir=target.parent, prefix=".kb-export-", suffix=".tmp")
        except OSError as exc:
            raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
        try:
            with os.fdopen(fd, "wb") as raw, zipfile.ZipFile(raw, "w") as archive:
                _zip_folder(archive, where.folder)
            os.replace(temp, target)
        except BaseException as exc:
            Path(temp).unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
            raise
        return {"path": str(target), "bytes": target.stat().st_size}


def _screen_differ() -> ScreenDiffer | None:
    """화면 차이 함수 (플랫폼의 OpenCV). 플랫폼이 없는 환경이면 None — 화면 비교는 파일만 준다."""
    try:
        from kookabug_platform.imagediff import screen_diff
    except ImportError:
        return None
    return screen_diff


def _zip_folder(archive: zipfile.ZipFile, folder: Path) -> None:
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        name = f"{folder.name}/{path.relative_to(folder).as_posix()}"
        method = zipfile.ZIP_STORED if path.suffix.lower() in _STORED else zipfile.ZIP_DEFLATED
        archive.write(path, name, compress_type=method)


def _inside(folder: Path, parent: Path) -> bool:
    """`folder`가 `parent`이거나 그 아래인가. 같은 폴더는 파일 정체로 본다 (8.3 짧은 이름·대소문자·
    정션으로 표기가 달라도 같은 폴더). 정션·심볼릭 링크를 따라간 실제 경로의 조상도 본다
    (바깥 별칭이 `runs/<실행>`을 가리키는 경우)."""
    try:
        if not parent.is_dir():
            return False
        real = folder.resolve()
    except OSError:
        return False
    for start in (folder, real):
        for at in (start, *start.parents):
            try:
                if at.is_dir() and os.path.samefile(at, parent):
                    return True
            except OSError:
                continue
    return False


def _same_file(index: RunIndex) -> bool:
    try:
        stat = (index.folder / EVENTS_FILE).stat()
    except OSError:
        return False
    return stat.st_size == index.size and stat.st_mtime_ns == index.mtime_ns


def _snapshot_json(snapshot: Path, rel: str) -> Mapping[str, Any] | None:
    """스냅샷 안 JSON 객체 (없거나 읽을 수 없거나 스냅샷 밖 경로면 None)."""
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    if not parts or any(p in ("", ".", "..") or ":" in p for p in parts):
        return None
    try:
        value = loads_strict(snapshot.joinpath(*parts).read_text(encoding="utf-8"))
    except OSError, UnicodeDecodeError, ValueError:
        return None
    return value if isinstance(value, Mapping) else None


def video_policy(folder: Path, run_json: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """실행 단위 실효 영상 정책과 정한 층 (M4 T12, 뷰어 상태 바): 스냅샷의 `kookabug.json` →
    테스트 그래프 `record` (`executor.run_record_policy`와 같은 규칙). 스냅샷의 `kookabug.json`을
    읽지 못하면 None (옛 실행·깨진 폴더)."""
    from kookabug_core.record.policy import graph_source, workspace_policy

    snapshot = folder / SNAPSHOT_DIR
    workspace = _snapshot_json(snapshot, WORKSPACE_FILE)
    if workspace is None:
        return None
    record = workspace.get("record")
    ws_record = record if isinstance(record, Mapping) else None
    policy = workspace_policy(ws_record, graph_source(WORKSPACE_FILE))
    # 워크스페이스가 `on`을 적었으면 정책 계산은 초기값과 같아 출처를 남기지 않는다. 표시할 출처는
    # 워크스페이스 기본값(failed_only)이 아니라 kookabug.json이다 (B4 검수 Mid 2)
    source = policy.sources.get("video")
    if source is None and ws_record is not None and ws_record.get("video") == "on":
        source = graph_source(WORKSPACE_FILE)
    graph = None if run_json is None else run_json.get("graph")
    if isinstance(graph, str):
        value = _snapshot_json(snapshot, graph)
        layer = None if value is None else value.get("record")
        if isinstance(layer, Mapping):
            stronger = policy.layer(layer, graph_source(graph))
            if stronger.video != policy.video:
                source = stronger.sources.get("video")
            policy = stronger
    return {"mode": policy.video, "source": source}


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
