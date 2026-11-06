"""daemon 녹화 세션 (M4 계획 2.3·2.8·2.9, T8).

세션은 daemon에 하나다. 상태 `idle → starting → recording ⇄ paused → stopped → committing →
(committed | stopped) | discarded`. 오류 정지(`hook_lost`·`input_overflow`·`window_gone`·
`storage_full`)도 `stopped`이고 이유(`stop_reason`)를 남긴다.

- **연결 소유권**: 세션은 시작한 UI 연결 하나에 속한다. 모든 조작·읽기는 소유 연결만(`not_owner`),
  다른 연결은 `recorder.state`로 상태·경과만 본다. 소유 연결이 끊기면 세션을 버린다(`starting`
  중이면 그 단계가 끝나는 대로)
- **시작 순서**: 실행 시작 잠금 안 `starting` 예약(`RunManager.reserve_recording`) → 임대권
  (`recorder`) → (게임 띄우기) → 대상 창 → 링 캡처·기하 → 첫 검증된 프레임 → 훅 → `recording`.
  어느 단계든 실패하면 앞 단계를 거꾸로 되돌린다
- **상태별 마무리**: 일시정지는 임대권·예약을 쥔 채 입력을 버린다. 정지(단추·오류)는 훅 → 남은
  이벤트 → 변환 마무리(오류면 끊긴 곳 앞까지, 열린 구간은 확인 필요) → 캡처 닫음 → 임대권 깨끗이
  놓음 → 예약 풂. 버리기·연결 끊김은 모든 동작·글자를 버리고 정리
- **두 단계 커밋**: `commit_prepare`가 검사 → target 파일 쓰기(초안마다 써진 경로·revision 기록 —
  다시 부르면 다시 쓰지 않음, 밖에서 바뀌었으면 그 초안만 새 이름) → 조각·토큰(`committing`). 같은
  요청을 다시 부르면 같은 결과. `commit_finish` → `committed` → 정리, `commit_abort` → `stopped`
- **정리**: 세션 저장소, 이 세션이 `recorder.frame`으로 올린 정지 화면과 그 `cache/editor/` PNG,
  메모리 글자. daemon 시작 때 `cache/recorder/`를 비운다

글자 원문은 파이프라인의 `RecorderTexts`(메모리)에만 있다. 알림·저장소·로그에는 글자가 없다.
"""

from __future__ import annotations

import ctypes
import itertools
import json
import logging
import queue
import secrets as _random
import string
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np

from kookabug_core.recorder.actions import ConverterOptions
from kookabug_core.recorder.build import (
    NodeDraft,
    attach_draft,
    build_fragment,
    check_text_draft,
    check_visible_draft,
    click_drafts,
    delay_draft,
    drag_drafts,
    key_draft,
    launch_draft,
    scroll_draft,
    text_draft,
    wait_draft,
)
from kookabug_core.recorder.classify import RevealNotConfirmed
from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.protect import SecretRegionOverlap
from kookabug_core.recorder.secrets import TextNotAvailable
from kookabug_core.workspace import RunOptions, Workspace
from kookabug_daemon.frames import EditorFrame, FrameCache, check_rect
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.recorder_hook import HookStop, HookUpdate
from kookabug_daemon.recorder_lease import RecorderLease
from kookabug_daemon.recorder_pipeline import FrameRef, Pipeline, Step
from kookabug_daemon.recorder_sources import FakeRecording, RealRecording, Recording, launch_game
from kookabug_daemon.recorder_store import RecorderStore

if TYPE_CHECKING:
    from kookabug_daemon.app import Daemon
    from kookabug_daemon.runs import RecordingReservation
    from kookabug_platform.recorder.evidence import ReadText

__all__ = ["RecorderService", "RecorderSession", "default_read_text"]

log = logging.getLogger(__name__)

type SessionState = Literal[
    "idle", "starting", "recording", "paused", "stopped", "committing", "committed", "discarded"
]

TICK_S: Final = 0.1
CLASSIFY_WAIT_S: Final = 5.0
_LIVE: Final = frozenset({"starting", "recording", "paused"})
_ENDED: Final = frozenset({"committed", "discarded"})
_COUNT_KEYS: Final = ("steps", "targets", "ignored_injected", "ignored_outside", "ignored_popup")
STORE_RETRY_S: Final = 1.0
"""저장소를 정리하지 못했을 때 다시 해 보는 간격 (정지·종료 뒤에도)."""
STORE_RETRY_TRIES: Final = 600
_ID_CHARS: Final = string.ascii_lowercase + string.digits

_OCR_LOCK = threading.Lock()
_OCR: list[ReadText | None] = []


def default_read_text() -> ReadText | None:
    """판정·이름용 OCR (프로세스에 하나, 처음 부를 때 모델을 읽는다). 모델이 없으면 None — 글자
    구간은 근거가 없어 `needs_review`가 된다."""
    with _OCR_LOCK:
        if not _OCR:
            try:
                from kookabug_platform.ocr import models
                from kookabug_platform.ocr.engine import RapidOcrEngine
                from kookabug_platform.recorder.evidence import ocr_reader

                engine = RapidOcrEngine(models.find_models())
                engine.load()
                _OCR.append(ocr_reader(engine))
            except Exception as exc:
                log.warning("녹화 판정용 OCR을 쓸 수 없다: %s", exc)
                _OCR.append(None)
        return _OCR[0]


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _system_click_options() -> tuple[int, int]:
    """시스템 이중 클릭 시간(ns)·거리(px). Windows가 아니면 기본값."""
    try:
        user32 = ctypes.WinDLL("user32")
        return int(user32.GetDoubleClickTime()) * 1_000_000, int(user32.GetSystemMetrics(36))
    except AttributeError, OSError:
        return 500_000_000, 4


@dataclass
class _Commit:
    token: str
    key: str
    result: dict[str, Any]


@dataclass
class _EditorShot:
    cache: str
    pixels: Any
    t_ns: int
    dpi: int


@dataclass
class _Session:
    """세션 상태 (서비스 잠금 아래)."""

    session_id: str
    owner: int
    options: dict[str, bool]
    launched: bool
    started_at: str
    started_mono: float
    state: SessionState = "starting"
    stop_reason: str | None = None
    cancelled: bool = False
    shots: dict[str, _EditorShot] = field(default_factory=dict[str, _EditorShot])
    written: dict[str, tuple[str, str]] = field(default_factory=dict[str, tuple[str, str]])
    """써진 초안 ID → (경로, revision). `written`·`materialized`는 파이프라인 잠금이 지킨다."""
    materialized: dict[str, str] = field(default_factory=dict[str, str])
    """`recorder.target.materialize`로 미리 쓴 target 경로 → 그 초안 ID."""
    commit: _Commit | None = None


class RecorderSession:
    """녹화 세션 하나. 메서드는 이벤트 루프 밖(작업 스레드)에서 부른다."""

    def __init__(
        self,
        service: RecorderService,
        owner: int,
        reservation: RecordingReservation,
        params: Mapping[str, Any],
    ) -> None:
        self.service = service
        self.daemon = service.daemon
        self.root: Path = service.daemon.root
        self.lock = threading.RLock()
        options = {
            "crop_targets": True,
            "wait_as_appear": True,
            **dict(params.get("options") or {}),
        }
        self.s = _Session(
            "".join(_random.choice(_ID_CHARS) for _ in range(8)),
            owner,
            options,
            "launch" in params,
            _now_iso(),
            time.monotonic(),
        )
        self.params = dict(params)
        self.reservation = reservation
        self.lease: RecorderLease | None = None
        self.recording: Recording | None = None
        self.pipeline: Pipeline | None = None
        self.store: RecorderStore | None = None
        self._queue: queue.Queue[tuple[HookUpdate, int] | None] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._stopping = threading.Lock()
        self._published_rev = -1
        self._counts: dict[str, int] = dict.fromkeys(_COUNT_KEYS, 0)
        self.store_unclean = False
        """`steps.json`을 새 내용으로 바꾸지도 지우지도 못했다 (지난 원문이 남았을 수 있다)."""
        self._retry_lock = threading.Lock()
        self._retrying = False
        self._retry_tries = 0

    # ------------------------------------------------------------ 읽기

    @property
    def state(self) -> SessionState:
        return self.s.state

    @property
    def owner(self) -> int:
        return self.s.owner

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.s.started_mono) * 1000)

    def counts(self) -> dict[str, int]:
        pipeline = self.pipeline
        if pipeline is None:
            return dict.fromkeys(_COUNT_KEYS, 0)
        # 이벤트 루프(`recorder.state`)에서도 부른다: 파이프라인 잠금(저장 재시도 동안 쥘 수
        # 있다)을 기다리지 않고, 못 쥐면 마지막으로 센 값을 쓴다 (SECFIX M1)
        if pipeline.lock.acquire(blocking=False):
            try:
                counts = pipeline.counts()
                self._counts = dict(counts)
            finally:
                pipeline.lock.release()
        else:
            counts = dict(self._counts)
        if self.recording is not None:
            counts["ignored_injected"] = self.recording.ignored_injected
        return counts

    def warnings(self) -> list[dict[str, Any]]:
        counts = self.counts()
        out: list[dict[str, Any]] = []
        if counts["ignored_injected"]:
            out.append(
                {
                    "code": "injected_ignored",
                    "count": counts["ignored_injected"],
                    "message": (
                        f"다른 프로그램이 보낸 입력 {counts['ignored_injected']}개는 "
                        "녹화하지 않았어요"
                    ),
                }
            )
        if counts["ignored_popup"]:
            out.append(
                {
                    "code": "popup_ignored",
                    "count": counts["ignored_popup"],
                    "message": "게임의 팝업 창 입력은 녹화하지 않아요",
                }
            )
        if self.store_unclean:
            out.append(
                {
                    "code": "store_unclean",
                    "message": "녹화 임시 파일을 정리하지 못했어요 — 다시 시도하는 중이에요",
                }
            )
        if self.s.state in ("recording", "paused") and not self.foreground():
            out.append(
                {
                    "code": "not_foreground",
                    "message": "게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중",
                }
            )
        return out

    def foreground(self) -> bool:
        pipeline = self.pipeline
        if pipeline is None or self.recording is None:
            return True
        fg = pipeline.last_fg
        return fg is None or fg == self.recording.target_hwnd

    def state_json(self, *, owned: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "owned": owned,
            "state": self.s.state,
            "started_at": self.s.started_at,
            "elapsed_ms": self.elapsed_ms(),
        }
        if not owned:
            return out
        out.update(
            session=self.s.session_id,
            counts=self.counts(),
            warnings=self.warnings(),
            foreground=self.foreground(),
            launched=self.s.launched,
            options=dict(self.s.options),
        )
        if self.recording is not None:
            out["window"] = self.recording.window.to_json()
        if self.s.stop_reason is not None:
            out["stop_reason"] = self.s.stop_reason
        return out

    def _require(self, *states: SessionState) -> None:
        if self.s.state not in states:
            raise RequestFailed(
                "recorder_state_invalid",
                f"녹화가 {self.s.state} 상태라 할 수 없다",
                state=self.s.state,
            )

    # ------------------------------------------------------------ 시작

    def open(self) -> None:
        """시작 단계 (예약은 서비스가 이미 잡았다). 실패하면 `rollback` 뒤 오류."""
        self.lease = self.service.lease_factory()
        self.lease.acquire()
        self._check_cancelled()
        self.recording = self.service.make_recording(self)
        self._check_cancelled()
        double_ns, double_px = _system_click_options()
        hotkeys = list(self.params.get("hotkeys") or [])
        secret_hotkey = next((h["keys"] for h in hotkeys if h.get("role") == "mark_secret"), None)
        options = ConverterOptions(
            double_click_ns=double_ns,
            double_click_px=max(1, double_px),
            hotkeys=tuple(h["keys"] for h in hotkeys),
            secret_hotkey=secret_hotkey,
        )
        from kookabug_platform.recorder.targets import workspace_candidates
        from kookabug_platform.vision import Vision

        window = self.recording.window
        self.store = RecorderStore(self.root, self.s.session_id)
        self.pipeline = Pipeline(
            target_hwnd=self.recording.target_hwnd,
            source=self.recording.frames,
            options=options,
            read_text=self.service.read_text_factory(),
            vision=Vision(),
            workspace_targets=workspace_candidates(self.root, window.client_size),
            on_store_frame=self._store_frame,
        )
        self.recording.start_frames()
        self._check_cancelled()
        self._worker = threading.Thread(target=self._work, name="recorder-work", daemon=True)
        self._worker.start()
        self.recording.start_hook()
        self._check_cancelled()
        with self.lock:
            self.s.state = "recording"
            self.reservation.set_state("recording")
        log.info("녹화 시작: 세션 %s", self.s.session_id)

    def _check_cancelled(self) -> None:
        if self.s.cancelled:
            raise RequestFailed(
                "recorder_state_invalid", "녹화를 시작한 연결이 끊겼다", state="discarded"
            )

    def rollback(self) -> None:
        """시작 실패: 앞 단계를 거꾸로 되돌린다 (훅 → 캡처 → 저장소 → 임대권 → 예약)."""
        recording = self.recording
        if recording is not None:
            try:
                recording.stop_hook()
            finally:
                recording.close()
        self._end_worker()
        if self.pipeline is not None:
            with self.pipeline.lock:
                # 먼저: 저장소 재시도가 글자를 다시 내보내지 않고 지우기만 하게
                self.pipeline.wipe()
        self._remove_store()
        if self.lease is not None:
            self.lease.release()
        self.reservation.release()
        self.s.state = "discarded"

    # ------------------------------------------------------------ 훅 → 처리 스레드

    def on_update(self, update: HookUpdate, now_ns: int) -> None:
        """훅 스레드: 프레임을 바로 붙잡고 처리 큐에 넣는다 (여기서 막히지 않는다)."""
        pipeline = self.pipeline
        if pipeline is None:
            return
        pipeline.hold(update.events)
        self._queue.put((update, now_ns))

    def on_hook_stop(self, stop: HookStop) -> None:
        """훅 끊김·유실: 다른 스레드에서 정지 마무리 (훅 스레드가 자기를 기다리지 않게)."""
        threading.Thread(
            target=self.stop, args=(stop.reason,), name="recorder-stop", daemon=True
        ).start()

    def _store_frame(self, ref: FrameRef) -> None:
        store = self.store
        if store is None:
            return
        from kookabug_platform.frames import encode_png

        if not store.put_frame(ref.entry.seq, encode_png(ref.client())):
            threading.Thread(
                target=self.stop, args=("storage_full",), name="recorder-stop", daemon=True
            ).start()

    def _work(self) -> None:
        while True:
            try:
                item = self._queue.get(timeout=TICK_S)
            except queue.Empty:
                self._tick()
                continue
            try:
                if item is None:
                    return
                update, now_ns = item
                pipeline = self.pipeline
                if pipeline is not None:
                    with pipeline.lock:
                        if not pipeline.finished:
                            pipeline.feed(update, now_ns)
                if self._queue.empty():
                    self._tick()
            except Exception as exc:
                log.error("녹화 처리 오류: %s", _error_kind(exc))
            finally:
                self._queue.task_done()

    def _tick(self) -> None:
        pipeline, recording = self.pipeline, self.recording
        if pipeline is None or recording is None or self.s.state not in _LIVE:
            return
        try:
            with pipeline.lock:
                pipeline.latest_ns = max(pipeline.latest_ns, recording.now_ns())
                if not pipeline.finished:
                    pipeline.flush(force=False)
                    pipeline.refresh()
        except Exception as exc:
            log.error("녹화 처리 오류: %s", _error_kind(exc))
        self.changed()
        if isinstance(recording, RealRecording) and not _window_alive(recording.target_hwnd):
            threading.Thread(target=self.stop, args=("window_gone",), daemon=True).start()

    def drain(self) -> None:
        """받은 업데이트를 모두 처리할 때까지 기다린다."""
        if self._worker is not None and self._worker.is_alive():
            self._queue.join()

    def _end_worker(self) -> None:
        worker = self._worker
        if worker is not None and worker.is_alive():
            self._queue.put(None)
            if worker is not threading.current_thread():
                worker.join(10)

    def changed(self) -> None:
        """스텝·상태가 바뀌었으면 저장소에 쓰고 알린다.

        스냅숏·쓰기·쓴 rev 기록을 한 파이프라인 잠금 안에서 한다 (SECFIX): 잠금 밖에서 쓰면
        비밀값으로 바꾸기 전 스냅숏(원문이 든 이름·제목)이 늦게 써져 바꾼 뒤 파일을 덮거나, 쓰기
        전에 rev를 기록해 둔 탓에 다른 `changed()`가 아직 안 써진 파일을 그대로 둔다. 쓰기가
        실패하면 rev를 기록하지 않아 다음에 다시 쓴다. 여기서 쥐는 잠금 순서는 파이프라인(RLock) →
        저장소 → 재시도 표시뿐이다 (알림 `publish`는 이벤트 루프로 넘긴다).

        새 내용으로 바꾸지도 지우지도 못하면(`StoreUnclean`) `store_unclean`을 켜고 정지·종료
        뒤에도 다시 해 본다 (SECFIX H1).

        끝난 세션(파이프라인 글자를 지움 — 버림·커밋·시작 되돌리기·daemon 종료)이면 같은 잠금
        안에서 그것을 보고 스텝을 다시 내보내지 않고 폴더만 지운다. 상태 알림도 보내지 않는다 —
        끝낸 쪽이 이미 보냈고, 늦은 알림이 새 녹화의 상태처럼 보이면 안 된다 (SECFIX 3 H1·H2)."""
        pipeline, store = self.pipeline, self.store
        if pipeline is not None and store is not None:
            with pipeline.lock:
                if pipeline.wiped:
                    removed = store.remove()
                    self.store_unclean = not removed
                    if not removed:
                        self._retry_store_later()
                    return
                self._counts = pipeline.counts()
                if pipeline.rev != self._published_rev:
                    steps = [
                        pipeline.step_json(s, reveal=False) for s in pipeline.steps if not s.deleted
                    ]
                    rev = pipeline.rev  # step_json의 기댓값 가리기가 rev를 올릴 수 있다
                    try:
                        outcome = store.write_steps(steps, session=self.s.session_id, rev=rev)
                    except OSError as exc:
                        self.store_unclean = True
                        log.warning("녹화 임시 파일을 정리하지 못했다 (%s)", _error_kind(exc))
                        self._retry_store_later()
                    else:
                        self.store_unclean = False
                        if outcome == "deleted":
                            # 지난 내용은 지웠지만 새 내용은 못 썼다: 나중에 다시 쓴다
                            self._retry_store_later()
                        else:
                            self._published_rev = rev
        self.service.publish(self)

    def _remove_store(self) -> None:
        """세션 끝: 저장소 폴더째 지운다. 잠긴 파일이 남으면 나중에 다시 지운다."""
        if self.store is not None and not self.store.remove():
            self.store_unclean = True
            log.warning("녹화 임시 폴더를 다 지우지 못했다 — 다시 시도한다")
            self._retry_store_later()

    def _retry_store_later(self) -> None:
        """저장소 정리를 나중에 다시 한다 (녹화 처리 스레드·RPC가 없는 정지·종료 뒤에도)."""
        with self._retry_lock:
            if self._retrying:
                return
            self._retrying = True
        threading.Thread(target=self._retry_store, name="recorder-store-retry", daemon=True).start()

    def _store_settled(self) -> bool:
        """더 다시 할 것이 없다: 끝난 세션은 폴더가 없고, 아니면 깨끗하고 최신 rev를 썼다."""
        store, pipeline = self.store, self.pipeline
        if store is None or pipeline is None:
            return True
        if pipeline.wiped:
            return not store.folder.exists()
        return not self.store_unclean and pipeline.rev == self._published_rev

    def _retry_store(self) -> None:
        """재시도 한 번. 저장할지 지울지는 `changed()`가 파이프라인 잠금 안에서 정한다(끝난 세션이면
        지우기만). 예외가 나도 종류만 남기고, 어떻게 끝나든 예약 표시를 풀며, 다 못 끝냈으면 다음
        한 번을 다시 예약한다 (최대 `STORE_RETRY_TRIES`번)."""
        again = give_up = False
        try:
            time.sleep(STORE_RETRY_S)
            self.changed()
        except Exception as exc:
            log.warning("녹화 임시 파일 정리 재시도 오류 (%s)", _error_kind(exc))
        finally:
            with self._retry_lock:
                self._retrying = False
                again = not self._store_settled()
                self._retry_tries = self._retry_tries + 1 if again else 0
                give_up = self._retry_tries >= STORE_RETRY_TRIES
            if again and not give_up:
                self._retry_store_later()
            elif again:
                log.warning("녹화 임시 파일 정리를 그만 다시 한다 (daemon 다음 시작 때 지운다)")

    def rev(self) -> int:
        return 0 if self.pipeline is None else self.pipeline.rev

    # ------------------------------------------------------------ 일시정지·정지·버리기

    def pause(self) -> None:
        with self.lock:
            self._require("recording", "paused")
            if self.s.state == "paused":
                return
            self.drain()
            assert self.pipeline is not None
            with self.pipeline.lock:
                self.pipeline.pause()
            self.s.state = "paused"
            self.reservation.set_state("paused")
        self.changed()

    def resume(self) -> None:
        with self.lock:
            self._require("recording", "paused")
            if self.s.state == "recording":
                return
            self.drain()
            assert self.pipeline is not None
            with self.pipeline.lock:
                self.pipeline.resume()
            self.s.state = "recording"
            self.reservation.set_state("recording")
        self.changed()

    def stop(self, reason: str = "user") -> None:
        """정지 마무리 (여러 번·여러 스레드에서 불러도 한 번만)."""
        with self._stopping:
            if self.s.state not in ("recording", "paused"):
                return
            recording, pipeline = self.recording, self.pipeline
            assert recording is not None and pipeline is not None
            try:
                overflow = recording.stop_hook()
                self.drain()
                if overflow is not None:
                    reason = overflow.reason
                cut = reason in ("hook_lost", "input_overflow")
                with pipeline.lock:
                    pipeline.latest_ns = max(pipeline.latest_ns, recording.now_ns())
                    pipeline.finish("cut" if cut else "stop")
                    pipeline.refresh()
            except Exception as exc:
                log.error(
                    "녹화 정지 마무리 오류 (훅·캡처를 닫고 임대권을 놓는다): %s", _error_kind(exc)
                )
            finally:
                # 무엇이 실패해도 훅·캡처를 닫고 임대권·실행 거부 예약을 놓는다
                try:
                    self._end_worker()
                    recording.close()
                finally:
                    if self.lease is not None:
                        self.lease.release()
                    self.reservation.release()
                    with self.lock:
                        self.s.state = "stopped"
                        self.s.stop_reason = reason
            counts = self.counts()
            log.info(
                "녹화 정지: 세션 %s, 이유 %s, 스텝 %d, target %d",
                self.s.session_id,
                reason,
                counts["steps"],
                counts["targets"],
            )
        self.changed()

    def discard(self) -> None:
        """버리기·연결 끊김: 훅·캡처를 끝내고 임대권·예약을 놓고 모두 지운다."""
        with self._stopping:
            if self.s.state in _ENDED:
                return
            written = sorted(path for path, _ in self.s.written.values())
            try:
                if self.s.state in _LIVE and self.recording is not None:
                    try:
                        self.recording.stop_hook()
                    finally:
                        self.recording.close()
                self._end_worker()
            finally:
                try:
                    if self.lease is not None:
                        self.lease.release()
                    self.reservation.release()
                finally:
                    self._cleanup()
                    with self.lock:
                        self.s.state = "discarded"
        if written:  # 경로는 남기지 않는다 (이름에 원문이 있었을 수 있다)
            log.info("녹화를 버렸다: 써진 target %d개는 남는다", len(written))
        self.service.publish(self)

    def _cleanup(self) -> None:
        """세션 저장소·이 세션이 올린 정지 화면과 그 PNG·메모리 글자."""
        if self.pipeline is not None:
            with self.pipeline.lock:
                self.pipeline.wipe()
        self._remove_store()
        for frame_id, shot in list(self.s.shots.items()):
            self.daemon.frames.discard(frame_id)
            self.daemon.image_cache.remove(shot.cache)
        self.s.shots.clear()
        self.service.session_ended(self)

    # ------------------------------------------------------------ 스텝

    def _settled(self) -> Pipeline:
        """받은 것을 다 처리하고 만들 수 있는 스텝을 만든 파이프라인 (잠금은 부르는 쪽)."""
        pipeline = self.pipeline
        if pipeline is None:
            raise RequestFailed("recorder_state_invalid", "녹화가 아직 없다", state=self.s.state)
        self.drain()
        return pipeline

    def steps(self) -> dict[str, Any]:
        pipeline = self._settled()
        with pipeline.lock:
            if not pipeline.finished:
                pipeline.refresh()
            steps = [pipeline.step_json(s, reveal=True) for s in pipeline.steps if not s.deleted]
            return {"rev": pipeline.rev, "steps": steps}

    def _step(self, pipeline: Pipeline, step_id: str) -> Step:
        step = pipeline.find_step(step_id)
        if step is None or step.deleted:
            raise RequestFailed("not_found", f"스텝 {step_id}이(가) 없다", path=step_id)
        return step

    def step_update(self, step_id: str, patch: Mapping[str, Any]) -> dict[str, Any]:
        with self.lock:
            self._require("recording", "paused", "stopped")
        pipeline = self._settled()
        with pipeline.lock:
            step = self._step(pipeline, step_id)
            texts = pipeline.texts
            span = step.span_id
            try:
                if patch.get("delete"):
                    step.deleted = True
                    if span is not None:
                        texts.drop(span)
                    pipeline.rev += 1
                    result: dict[str, Any] = {"rev": pipeline.rev, "step": None}
                    self._after_update()
                    self._require_store_clean()
                    return result
                state = patch.get("text_state")
                if state is not None and span is None:
                    raise RequestFailed(
                        "recorder_state_invalid", "글자 스텝이 아니다", state=self.s.state
                    )
                if state == "ordinary":
                    assert span is not None
                    texts.confirm_ordinary(span, confirm_reveal=bool(patch.get("confirm_reveal")))
                    pipeline.protect.release(span)
                elif state == "secret":
                    assert span is not None
                    texts.mark_secret(span)
                    pipeline.protect.protect_again(span)
                if "secret_key" in patch and span is not None:
                    texts.set_secret_key(span, patch["secret_key"])
                if "text" in patch and span is not None:
                    texts.replace_ordinary(span, str(patch["text"]))
                if "equals" in patch:
                    if step.kind != "check_text":
                        raise RequestFailed(
                            "recorder_state_invalid", "값 확인 스텝이 아니다", state=self.s.state
                        )
                    equals = str(patch["equals"])
                    # 기댓값도 이름·제목처럼 세션의 비밀값·판정 대기·확인 필요 원문을 담지 않는다
                    if pipeline.leaks_secret(equals):
                        raise RequestFailed(
                            "secret_region_overlap",
                            "비밀값 글자는 기댓값으로 쓸 수 없다",
                            steps=[step.step_id],
                        )
                    step.equals = equals
                if patch.get("keep"):
                    step.kept = True
                if "timeout_ms" in patch:
                    step.timeout_ms = int(patch["timeout_ms"])
                node_type = patch.get("node_type")
                if node_type is not None:
                    allowed = {
                        "click": {"core.image.click", "core.input.click"},
                        "wait": {"core.image.wait", "core.flow.delay"},
                        "delay": {"core.flow.delay"},
                    }.get(step.kind, {step.node_type})
                    if node_type not in allowed:
                        raise RequestFailed(
                            "recorder_state_invalid",
                            f"{step.kind} 스텝은 {node_type}로 바꿀 수 없다",
                            state=self.s.state,
                        )
                    step.node_type = node_type
                if "target" in patch or "frame" in patch or "frame_id" in patch:
                    self._retarget(pipeline, step, patch)
            except (TextNotAvailable, RevealNotConfirmed, ValueError) as exc:
                raise RequestFailed("recorder_state_invalid", str(exc), state=self.s.state) from exc
            except SecretRegionOverlap as exc:
                raise RequestFailed(
                    "secret_region_overlap", str(exc), steps=[step.step_id]
                ) from exc
            # 보호 상태가 바뀌었을 수 있다 (일반 → 비밀값): 만든 것을 지금 기준으로 다시 본다
            self._revalidate(pipeline)
            pipeline.rev += 1
            result = {"rev": pipeline.rev, "step": pipeline.step_json(step, reveal=True)}
        self._after_update()
        self._require_store_clean()
        return result

    def _revalidate(self, pipeline: Pipeline) -> None:
        """파이프라인 재검사 + 버린 초안 중 이 세션이 이미 쓴 target 파일 정리 (잠금은 부르는
        쪽)."""
        bad = set(pipeline.revalidate())
        # 미리 쓴(materialize) target의 초안이 버려졌으면 그 경로를 가리키는 스텝도 버린다 —
        # 아래에서 그 파일을 지운다(이 세션이 쓴 그대로일 때)
        gone = {rel for rel, draft in self.s.materialized.items() if draft in bad}
        if gone:
            for step in pipeline.steps:
                if not step.deleted and step.target in gone:
                    pipeline.invalidate(step)
            for rel in gone:
                self.s.materialized.pop(rel, None)
            pipeline.rev += 1
        self._forget_written(pipeline)

    def _forget_written(self, pipeline: Pipeline) -> None:
        """버린 초안의 써진 target(JSON·PNG)을 지운다. 이 세션이 쓴 그대로일 때만(밖에서 바뀌었으면
        남기고 기록만 지운다) — 원문이 찍혔을 수 있는 파일이다."""
        import json as _json

        from kookabug_daemon.targets import target_path

        for draft_id in [d for d in self.s.written if d not in pipeline.targets.drafts]:
            rel, revision = self.s.written.pop(draft_id)
            # 로그에는 초안 ID와 오류 종류만 (경로·이름·예외 문구에 원문이 있을 수 있다)
            if self._revision(rel) != revision:
                log.warning("버린 녹화 초안 %s의 target이 밖에서 바뀌어 남긴다", draft_id)
                continue
            where = target_path(self.root, rel)
            try:
                image = _json.loads(where.path.read_text(encoding="utf-8")).get("image")
                where.path.unlink()
                if isinstance(image, str) and "/" not in image and "\\" not in image:
                    (where.path.parent / image).unlink(missing_ok=True)
            except (OSError, ValueError) as exc:
                log.warning(
                    "버린 녹화 초안 %s의 target을 지우지 못했다 (%s)", draft_id, _error_kind(exc)
                )

    def _after_update(self) -> None:
        """응답 전에 저장소까지 쓴다: 비밀값으로 바꾼 RPC가 끝난 뒤 지난 스텝 파일이 남지 않게
        (SECFIX). 부르는 곳은 모두 작업 스레드(`asyncio.to_thread`)라 이벤트 루프는 막지 않는다."""
        self.changed()

    def _require_store_clean(self) -> None:
        """보호 상태를 바꿀 수 있는 RPC(스텝 고치기·비밀값 만들기)의 응답 직전: 저장소를 정리하지
        못했으면 메모리 스텝은 바뀐 채로 두고 `recorder_store_unclean`으로 응답한다 (경로·글자는
        싣지 않는다. daemon이 다시 정리하고 알림 경고로 보인다)."""
        if self.store_unclean:
            raise RequestFailed(
                "recorder_store_unclean",
                "녹화 임시 파일을 정리하지 못했다 — 스텝은 바뀌었고 daemon이 다시 정리한다",
            )

    def _retarget(self, pipeline: Pipeline, step: Step, patch: Mapping[str, Any]) -> None:
        """REC 탭에서 고른 영역·프레임으로 초안을 다시 만든다 (보호 영역 검사)."""
        if not step.needs_target:
            raise ValueError("찾기 대상이 없는 스텝이다")
        frame_id = patch.get("frame_id")
        if frame_id is not None:
            shot = self.s.shots.get(str(frame_id))
            if shot is None:
                raise RequestFailed(
                    "not_owner", "이 녹화 세션이 올린 정지 화면이 아니다", state=self.s.state
                )
            self.daemon.frames.get(str(frame_id))  # 사라졌으면 frame_expired
            pixels, t_ns, dpi = shot.pixels, shot.t_ns, shot.dpi
        else:
            which = str(
                patch.get("frame") or ("pre_hover" if "pre_hover" in step.frames else "pre_click")
            )
            ref = step.frames.get(which) or step.frames.get("pre_next")
            if ref is None:
                raise RequestFailed("no_frame", "고를 프레임이 없다")
            pixels = ref.client() if isinstance(ref, FrameRef) else ref
            t_ns = ref.arrival_ns if isinstance(ref, FrameRef) else step.t_ns
            dpi = ref.dpi if isinstance(ref, FrameRef) else 96
        spec = dict(patch.get("target") or {})
        old = pipeline.targets.drafts.get(step.target or "")
        rect = spec.get("rect") or (None if old is None else list(old.box))
        if rect is None:
            raise ValueError("영역(rect)이 없다")
        x, y, w, h = (int(v) for v in rect)
        height, width = int(pixels.shape[0]), int(pixels.shape[1])
        if w < 1 or h < 1 or x < 0 or y < 0 or x + w > width or y + h > height:
            raise ValueError("영역이 정지 화면 밖이다")
        box = (x, y, w, h)
        pipeline.overlap_check(box, t_ns, pixels)
        image = np.ascontiguousarray(pixels)
        from kookabug_platform.vision import FrameMeta

        meta = FrameMeta((width, height), dpi, backend="recorder")
        offset = spec.get("offset")
        draft_id = pipeline.targets.add_draft(
            image,
            meta,
            box,
            name=lambda n: step.name or f"click_{n}",
            frame_t_ns=t_ns,
            offset=(float(offset[0]), float(offset[1])) if offset else (0.0, 0.0),
            search_region=None if not spec.get("search") else tuple(spec["search"]),  # pyright: ignore[reportArgumentType]
        )
        draft = pipeline.targets.drafts[draft_id]
        old_click = draft.spec.get("click")
        click: dict[str, Any] = dict(old_click) if isinstance(old_click, dict) else {}  # pyright: ignore[reportUnknownArgumentType]
        if "anchor" in spec:
            click["anchor"] = spec["anchor"]
        draft.spec["click"] = click
        match: dict[str, Any] = {}
        for key in ("threshold", "rgb", "methods", "color_tolerance"):
            if key in spec:
                match[key] = spec[key]
        if match:
            draft.spec["match"] = match
        if spec.get("sensitive"):
            draft.spec["sensitive"] = True
        pipeline.draft_frames[draft_id] = image
        step.target, step.reused = draft_id, False
        if step.invalidated:  # 사람이 영역을 다시 골랐다 (보호 영역 검사를 지났다)
            step.invalidated = False
            step.needs_review = [r for r in step.needs_review if r != "secret_overlap"]
        step.name = draft.name

    def frame(self, which: str, step_id: str | None) -> dict[str, Any]:
        pipeline = self._settled()
        with pipeline.lock:
            if which == "live":
                if self.s.state not in _LIVE or self.recording is None:
                    raise RequestFailed("no_frame", "녹화가 끝나 실시간 화면이 없다")
                ref = pipeline._ref(self.recording.frames.ring.latest())  # pyright: ignore[reportPrivateUsage]
            else:
                assert step_id is not None
                ref = self._step(pipeline, step_id).frames.get(which)
            if ref is None:
                raise RequestFailed("no_frame", "고를 프레임이 없다")
            pixels = ref.client() if isinstance(ref, FrameRef) else np.ascontiguousarray(ref)
            t_ns = ref.arrival_ns if isinstance(ref, FrameRef) else pipeline.latest_ns
            dpi = ref.dpi if isinstance(ref, FrameRef) else 96
            protected = [list(r.box) for r in pipeline.protect.active(t_ns, pixels)]
        from kookabug_platform.frames import encode_png

        frame_id = FrameCache.new_id()
        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        frame = EditorFrame(
            frame_id, pixels, size, max(1, dpi), f"{frame_id}.png", origin="recorder"
        )
        self.daemon.image_cache.put(frame.cache, encode_png(pixels))
        self.daemon.frames.add(frame)
        with self.lock:
            self.s.shots[frame_id] = _EditorShot(frame.cache, pixels, t_ns, max(1, dpi))
        return {"frame": frame.to_json(), "protected": protected, "which": which}

    def materialize(self, step_id: str) -> dict[str, Any]:
        """REC 탭 "찾기 대상 탭으로 열기": 그 스텝의 녹화 초안만 지금 파일로 쓴다. 최신 보호
        영역·원문으로 먼저 다시 본다(걸리면 `secret_region_overlap`). 쓴 경로는 커밋 멱등 기록
        (`written`)에 들어가 커밋이 다시 쓰지 않고, 스텝은 이후 그 파일을 가리킨다(사람이 TARGET
        탭에서 고쳐도 그 파일을 쓴다)."""
        with self.lock:
            self._require("recording", "paused", "stopped")
        pipeline = self._settled()
        with pipeline.lock:
            step = self._step(pipeline, step_id)
            self._revalidate(pipeline)
            draft_id = step.target
            if step.invalidated:
                raise RequestFailed(
                    "secret_region_overlap",
                    "비밀값 칸과 겹치거나 그 글자를 담은 대상이다 — 영역을 다시 고르세요",
                    steps=[step.step_id],
                )
            if draft_id is None or draft_id not in pipeline.targets.drafts:
                raise RequestFailed("target_missing", "파일로 쓸 녹화 초안이 없다", steps=[step_id])
            rel, revision = self._write_target(pipeline, draft_id, self.s.session_id)
            # 세션 잠금(`self.lock`)을 여기서 쥐지 않는다: 잠금 순서는 세션 → 파이프라인 한 방향
            # (`pause`·`resume`이 세션 잠금 안에서 파이프라인 잠금을 쥔다)
            self.s.materialized[rel] = draft_id
            step.target, step.reused = rel, False
            pipeline.rev += 1
        self._after_update()
        return {"path": rel, "revision": revision, "reused": False}

    def insert_check(self, kind: str, frame_id: str, rect: list[int]) -> dict[str, Any]:
        with self.lock:
            self._require("recording", "paused", "stopped")
            shot = self.s.shots.get(frame_id)
        if shot is None:
            raise RequestFailed(
                "not_owner", "이 녹화 세션이 올린 정지 화면이 아니다", state=self.s.state
            )
        frame = self.daemon.frames.get(frame_id)
        box = tuple(check_rect(frame, rect))
        pipeline = self._settled()
        with pipeline.lock:
            if not pipeline.finished:
                pipeline.refresh()
            last = max((s.t_ns for s in pipeline.steps), default=0)
            t_ns = max(shot.t_ns, last + 1)
            try:
                step = pipeline.insert_check(
                    "visible" if kind == "visible" else "text",
                    shot.pixels,
                    shot.dpi,
                    (box[0], box[1], box[2], box[3]),
                    t_ns,
                )
            except SecretRegionOverlap as exc:
                raise RequestFailed("secret_region_overlap", str(exc), steps=[]) from exc
            # 새 스텝(OCR 기댓값·이름)을 응답·알림·저장 전에 지금 원문 목록으로 다시 본다
            self._revalidate(pipeline)
            result = {"rev": pipeline.rev, "step": pipeline.step_json(step, reveal=True)}
        self._after_update()
        return result

    # ------------------------------------------------------------ 비밀값 (secrets.create)

    def text_for_secret(self, step_id: str) -> SecretText:
        pipeline = self._settled()
        with pipeline.lock:
            step = self._step(pipeline, step_id)
            if step.span_id is None:
                raise RequestFailed(
                    "recorder_state_invalid", "글자 스텝이 아니다", state=self.s.state
                )
            try:
                return pipeline.texts.raw_for_secret(step.span_id)
            except TextNotAvailable as exc:
                raise RequestFailed("recorder_state_invalid", str(exc), state=self.s.state) from exc

    def secret_created(self, step_id: str, key: str) -> None:
        pipeline = self._settled()
        with pipeline.lock:
            step = self._step(pipeline, step_id)
            assert step.span_id is not None
            pipeline.texts.mark_secret(step.span_id)
            pipeline.protect.protect_again(step.span_id)
            pipeline.texts.set_secret_key(step.span_id, key)
            self._revalidate(pipeline)
            pipeline.rev += 1
        self._after_update()
        self._require_store_clean()

    # ------------------------------------------------------------ 커밋

    def commit_prepare(self, params: Mapping[str, Any]) -> dict[str, Any]:
        options = {**self.s.options, **dict(params.get("options") or {})}
        key = json.dumps([params["mode"], params["graph_path"], options], sort_keys=True)
        with self.lock:
            if self.s.state == "committing":
                commit = self.s.commit
                if commit is not None and commit.key == key:
                    return commit.result  # 응답을 잃었다: 같은 조각
                raise RequestFailed(
                    "recorder_state_invalid", "다른 커밋이 진행 중이다", state=self.s.state
                )
            self._require("recording", "paused", "stopped")
        if self.s.state in ("recording", "paused"):
            self.stop("user")
        with self.lock:
            self._require("stopped")
        stem = _graph_stem(self.root, str(params["graph_path"]))
        pipeline = self._settled()
        deadline = time.monotonic() + CLASSIFY_WAIT_S
        while True:
            with pipeline.lock:
                pipeline.refresh()
                pending = pipeline.pending_classification()
            if not pending or time.monotonic() > deadline:
                break
            time.sleep(0.1)
        with pipeline.lock:
            # 커밋 직전: 모든 내보내기(초안 그림·이름·제목·문구)를 최신 보호 영역·원문으로 다시
            # 본다. 이미 써진 초안의 재사용도 이 검사를 지난 초안만이다
            self._revalidate(pipeline)
            self._check_blocked(pipeline, options)
            fragment, written = self._fragment(pipeline, params, options, stem)
        token = _random.token_urlsafe(16)
        result = {"fragment": fragment, "targets": written, "token": token}
        with self.lock:
            self.s.commit = _Commit(token, key, result)
            self.s.state = "committing"
        self.service.publish(self)
        return result

    def _active(self, pipeline: Pipeline) -> list[Step]:
        return [s for s in pipeline.steps if not s.deleted]

    def _check_blocked(self, pipeline: Pipeline, options: Mapping[str, bool]) -> None:
        by_span = {s.span_id: s.step_id for s in self._active(pipeline) if s.span_id is not None}
        blocked = pipeline.texts.commit_blocked(pipeline.active_spans())
        if blocked is not None:
            steps = [by_span[s] for s in blocked.spans if s in by_span]
            raise RequestFailed(blocked.code, _BLOCK_TEXT[blocked.code], steps=steps)
        crop = options.get("crop_targets", True)
        wait_on = options.get("wait_as_appear", True)

        def needs_file(s: Step) -> bool:
            """커밋에서 target 파일이 필요한 스텝: 좌표 클릭·지연으로 바꾼 스텝은 아니다 (검수
            M1)."""
            coordinate = not crop or s.node_type == "core.input.click"
            if s.kind == "click" and "point" in s.input and coordinate:
                return False
            if s.kind == "wait" and (not wait_on or s.node_type == "core.flow.delay"):
                return False
            return s.needs_target

        invalid = [s.step_id for s in self._active(pipeline) if s.invalidated and needs_file(s)]
        invalid += [
            s.step_id for s in self._active(pipeline) if s.invalidated and s.kind == "check_text"
        ]
        if invalid:
            raise RequestFailed(
                "secret_region_overlap",
                "비밀값 칸과 겹치거나 그 글자를 담은 대상이 있다 — 영역을 다시 고르거나 지우세요",
                steps=sorted(set(invalid), key=invalid.index),
            )
        missing = [s.step_id for s in self._active(pipeline) if needs_file(s) and s.target is None]
        if missing:
            raise RequestFailed("target_missing", "찾기 대상이 없는 스텝이 있다", steps=missing)

    def _fragment(
        self,
        pipeline: Pipeline,
        params: Mapping[str, Any],
        options: Mapping[str, bool],
        stem: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        crop = options.get("crop_targets", True)
        wait_on = options.get("wait_as_appear", True)
        written: dict[str, dict[str, Any]] = {}

        def path_of(step: Step) -> str:
            key = step.target
            assert key is not None
            if key not in pipeline.targets.drafts:
                if key not in written:
                    written[key] = {
                        "path": key,
                        "revision": self._revision(key) or "missing",
                        "reused": True,
                    }
                return key
            if key not in written:
                path, revision = self._write_target(pipeline, key, stem)
                written[key] = {"path": path, "revision": revision, "reused": False}
            return str(written[key]["path"])

        drafts: list[list[NodeDraft]] = []
        for step in self._active(pipeline):
            drafts.append(self._drafts(pipeline, step, path_of, crop=crop, wait_on=wait_on))
        mode = params["mode"]
        start = None
        if mode == "new_test":
            recording = self.recording
            title = "" if recording is None else recording.window.title
            start = launch_draft() if self.s.launched else attach_draft(title)
        fragment = build_fragment(drafts, mode=mode, start=start)
        return fragment, list(written.values())

    def _drafts(
        self,
        pipeline: Pipeline,
        step: Step,
        path_of: Callable[[Step], str],
        *,
        crop: bool,
        wait_on: bool,
    ) -> list[NodeDraft]:
        inputs = step.input
        match step.kind:
            case "click":
                if not crop or step.node_type == "core.input.click":
                    body: dict[str, Any] = {"point": list(inputs["point"])}
                    if inputs.get("button", "left") != "left":
                        body["button"] = inputs["button"]
                    if inputs.get("count", 1) != 1:
                        body["count"] = inputs["count"]
                    x, y = inputs["point"]
                    return [NodeDraft("core.input.click", f"클릭 ({x}, {y})", "done", body)]
                return click_drafts(
                    path_of(step),
                    step.name,
                    button=str(inputs.get("button", "left")),
                    count=int(inputs.get("count", 1)),
                    timeout_ms=step.timeout_ms,
                )
            case "drag":
                return drag_drafts(
                    path_of(step),
                    step.name,
                    inputs.get("end") or inputs.get("point") or [0, 0],
                    int(inputs.get("duration_ms", 0)),
                    step.timeout_ms or 10000,
                )
            case "scroll":
                return [scroll_draft(inputs.get("point") or [0, 0], int(inputs["amount"]))]
            case "key":
                return [key_draft(str(inputs["keys"]), inputs.get("hold_ms"))]
            case "text":
                assert step.span_id is not None
                # 비밀값은 칸을 비우고 한 번에 친다 (M4 계획 2.7 — 같은 $secret을 나눠 넣지 않는다)
                secret = pipeline.texts.state(step.span_id) == "secret"
                value = pipeline.texts.graph_text(step.span_id)
                return [text_draft(value, clear=step.clear or secret)]
            case "wait":
                if not wait_on or step.node_type == "core.flow.delay":
                    return [delay_draft(int(inputs.get("gap_ms", 0)))]
                return [wait_draft(path_of(step), step.name, step.timeout_ms or 10000)]
            case "delay":
                ms = step.ms if wait_on else int(inputs.get("gap_ms", 0))
                return [delay_draft(int(ms or 0))]
            case "check_visible":
                return [check_visible_draft(path_of(step), step.name)]
            case "check_text":
                return [check_text_draft(path_of(step), step.name, step.equals or "")]
        return []

    def _revision(self, rel: str) -> str | None:
        from kookabug_daemon.targets import combined_revision, read_bytes, target_path

        where = target_path(self.root, rel)
        data = read_bytes(where.path)
        return None if data is None else combined_revision(self.root, where, data)

    def _write_target(self, pipeline: Pipeline, draft_id: str, stem: str) -> tuple[str, str]:
        """초안 하나를 target 파일로 (멱등: 써진 기록이 있고 그대로면 다시 쓰지 않는다)."""
        known = self.s.written.get(draft_id)
        if known is not None and self._revision(known[0]) == known[1]:
            return known
        from kookabug_daemon.targets import target_path

        draft = pipeline.targets.drafts[draft_id]
        source = pipeline.draft_frames[draft_id]
        pixels = source.client() if isinstance(source, FrameRef) else np.ascontiguousarray(source)
        dpi = source.dpi if isinstance(source, FrameRef) else 96
        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        frame_id = FrameCache.new_id()
        self.daemon.frames.add(
            EditorFrame(frame_id, pixels, size, max(1, dpi), f"{frame_id}.png", origin="recorder")
        )
        spec = {k: v for k, v in draft.spec.items() if k not in ("image", "recorded")}
        number = int(draft_id.removeprefix("d"))
        base = f"{number:02d}_{draft.name}"
        try:
            for attempt in itertools.count(1):
                name = base if attempt == 1 else f"{base}_{attempt}"
                rel = f"targets/rec/{stem}/{name}.target.json"
                try:
                    where = target_path(self.root, rel, save=True)
                    outcome = self.daemon.targets.save(
                        where, spec, {"frame_id": frame_id, "rect": list(draft.box)}, None
                    )
                except RequestFailed as exc:
                    if exc.code == "exists" and attempt < 100:
                        continue
                    # 저장 오류 문구·data에는 target 경로(초안 이름)가 든다 — 초안 ID와 코드만
                    text = f"녹화 초안 {draft_id}의 target을 쓰지 못했다 ({exc.code})"
                    extra = {"message": text} if exc.code in ("io_error", "shutting_down") else {}
                    raise RequestFailed(exc.code, text, **extra) from None
                self.s.written[draft_id] = (rel, outcome.revision)  # 파이프라인 잠금 안
                return rel, outcome.revision
        finally:
            self.daemon.frames.discard(frame_id)
        raise AssertionError("unreachable")

    def commit_finish(self, token: str) -> None:
        with self.lock:
            self._check_token(token)
            self.s.state = "committed"
        self._cleanup()
        log.info("녹화 커밋 끝: 세션 %s", self.s.session_id)
        self.service.publish(self)

    def commit_abort(self, token: str) -> None:
        with self.lock:
            self._check_token(token)
            self.s.state = "stopped"
            self.s.commit = None
        self.service.publish(self)

    def _check_token(self, token: str) -> None:
        commit = self.s.commit
        if self.s.state != "committing" or commit is None or commit.token != token:
            raise RequestFailed(
                "recorder_state_invalid", "커밋 토큰이 맞지 않는다", state=self.s.state
            )


_BLOCK_TEXT: Final = {
    "classification_pending": "비밀번호 칸인지 판정하는 중인 입력이 있다",
    "text_review_required": "비밀번호인지 확인해야 하는 입력이 있다",
    "secret_unresolved": "쓸 비밀값을 고르지 않은 비밀번호 입력이 있다",
}


def _error_kind(exc: BaseException) -> str:
    """로그용 오류 표시: 종류와 일어난 자리만 (예외 문구에는 경로·글자가 있을 수 있다)."""
    tb = exc.__traceback__
    while tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    where = "" if tb is None else f" @ {Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}"
    code = getattr(exc, "code", None)
    return f"{type(exc).__name__}{'' if code is None else f'({code})'}{where}"


def _graph_stem(root: Path, given: str) -> str:
    from kookabug_daemon.documents import resolve_path

    where = resolve_path(root, given, graph=True)
    name = where.rel.rsplit("/", 1)[-1]
    return name.removesuffix(".graph.json")


def _window_alive(hwnd: int) -> bool:
    try:
        from kookabug_platform.win32.api import DEFAULT_API

        return bool(DEFAULT_API.is_window(hwnd))
    except Exception:
        return True


class _SecretSource:
    """`Daemon.recorder_secrets` (`secrets.create`): 소유 연결만, 스텝 → 구간 원문."""

    def __init__(self, service: RecorderService) -> None:
        self.service = service

    def text_for_secret(self, connection: int, step: str) -> SecretText:
        return self.service.require(connection).text_for_secret(step)

    def secret_created(self, connection: int, step: str, key: str) -> None:
        self.service.require(connection).secret_created(step, key)


class RecorderService:
    """daemon의 녹화 세션 하나를 쥔다. 메서드는 작업 스레드에서 부른다."""

    def __init__(self, daemon: Daemon) -> None:
        self.daemon = daemon
        self._lock = threading.Lock()
        self.session: RecorderSession | None = None
        self.read_text_factory: Callable[[], ReadText | None] = default_read_text
        self.secret_source = _SecretSource(self)

    # ------------------------------------------------------------ 만들기 (검사가 바꿔 끼운다)

    def lease_factory(self) -> RecorderLease:
        supervisor = getattr(self.daemon.service, "supervisor", None)
        return RecorderLease(self.daemon.root, environ=getattr(supervisor, "env", None))

    def _settings(self, profile: str | None) -> dict[str, Any]:
        ws = Workspace.open(self.daemon.root)
        options = RunOptions(profile=profile)
        return {
            key: ws.lookup_setting(key, options).value
            for key in ("game.executable", "game.args", "game.cwd", "game.title")
        }

    def make_recording(self, session: RecorderSession) -> Recording:
        config = self.daemon.config
        params = session.params
        launch = params.get("launch")
        profile = None if not isinstance(launch, Mapping) else launch.get("profile")
        if config.platform_fake is not None:
            script = config.recorder_script
            if script is None:
                raise RequestFailed(
                    "platform_unavailable",
                    "가짜 플랫폼 녹화에는 각본(--recorder-script)이 필요하다",
                )
            spec = json.loads(config.platform_fake.read_text(encoding="utf-8"))
            scenario = (config.platform_fake.parent / str(spec["scenario"])).resolve()
            args = tuple(str(a) for a in (self._settings(profile).get("game.args") or []))
            return FakeRecording(
                script,
                scenario,
                on_update=session.on_update,
                on_stop=session.on_hook_stop,
                speed=config.recorder_script_speed,
                testing=config.recorder_testing,
                args=args if launch is not None else (),
            )
        hwnd = launch_game(self._settings(profile)) if launch is not None else int(params["window"])
        logs = self.daemon.root / ".kookabug" / "logs"
        return RealRecording(
            hwnd,
            on_update=session.on_update,
            on_stop=session.on_hook_stop,
            testing=config.recorder_testing,
            logs_dir=logs if logs.is_dir() else None,
        )

    # ------------------------------------------------------------ 세션

    def start(self, connection: int, params: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.session
            if current is not None and current.state not in _ENDED:
                raise RequestFailed(
                    "recorder_state_invalid", "녹화 세션이 이미 있다", state=current.state
                )
            reservation = self.daemon.run_manager.reserve_recording()
            session = RecorderSession(self, connection, reservation, params)
            self.session = session
        self.publish(session)
        try:
            session.open()
        except BaseException:
            try:
                session.rollback()
            finally:
                with self._lock:
                    if self.session is session:
                        self.session = None
                self.publish_idle()
            raise
        self.daemon.recorder_secrets = self.secret_source
        session.changed()
        return session.state_json(owned=True)

    def require(self, connection: int) -> RecorderSession:
        session = self.session
        if session is None or session.state in _ENDED:
            state = "idle" if session is None else session.state
            raise RequestFailed("recorder_state_invalid", "녹화 세션이 없다", state=state)
        if session.owner != connection:
            raise RequestFailed("not_owner", "다른 연결의 녹화다", state=session.state)
        return session

    def state(self, connection: int) -> dict[str, Any]:
        session = self.session
        if session is None:
            return {"owned": False, "state": "idle"}
        return session.state_json(owned=session.owner == connection)

    def check_read_region(self, frame_id: str, rect: Sequence[int]) -> None:
        """`target.read_text` 앞 검사 (M4 T11): 녹화 세션이 올린 정지 화면이면 그 프레임 시각의
        보호 영역(비밀번호 칸)과 겹치는 영역은 `secret_region_overlap`으로 거부한다. 다른 프레임은
        그대로 둔다."""
        session = self.session
        if session is None:
            return
        with session.lock:
            shot = session.s.shots.get(frame_id)
        pipeline = session.pipeline
        if shot is None or pipeline is None:
            return
        x, y, w, h = (int(v) for v in rect)
        with pipeline.lock:
            spans = pipeline.protect.overlapping((x, y, w, h), shot.t_ns, shot.pixels)
        if spans:
            raise RequestFailed(
                "secret_region_overlap", "비밀값 칸과 겹치는 영역은 읽지 않는다", steps=[]
            )

    def check_read_result(self, result: Mapping[str, Any]) -> None:
        """`target.read_text` 뒤 검사: 읽은 글자가 녹화 세션의 비밀값·판정 대기·확인 필요 원문을
        담으면(보호 영역 밖 다른 자리에 다시 보인 경우) 결과를 주지 않는다. 오류에 원문을 싣지
        않는다."""
        session = self.session
        pipeline = None if session is None else session.pipeline
        if pipeline is None:
            return
        texts = [str(result.get("text") or "")]
        texts += [str(line.get("text") or "") for line in result.get("lines") or ()]
        with pipeline.lock:
            leaked = any(pipeline.leaks_secret(t) for t in texts)
        if leaked:
            raise RequestFailed(
                "secret_region_overlap", "비밀값 글자가 보이는 영역은 읽지 않는다", steps=[]
            )

    def session_ended(self, session: RecorderSession) -> None:
        if self.daemon.recorder_secrets is self.secret_source:
            self.daemon.recorder_secrets = None

    def connection_closed(self, connection: int) -> None:
        """소유 연결이 끊김 → 세션을 버린다 (U9). `starting`이면 그 단계가 끝나는 대로."""
        session = self.session
        if session is None or session.owner != connection or session.state in _ENDED:
            return
        session.s.cancelled = True
        if session.state == "starting":
            return
        threading.Thread(target=session.discard, name="recorder-discard", daemon=True).start()

    def close(self) -> None:
        """daemon 끝: 진행 중 세션을 버린다."""
        session = self.session
        if session is not None and session.state not in _ENDED:
            session.discard()

    # ------------------------------------------------------------ 알림

    def publish(self, session: RecorderSession) -> None:
        """그 세션이 **지금 세션**일 때만 알린다. 확인과 보내기 예약을 서비스 잠금 안에서 해서, 새
        세션을 연 뒤(그 시작 응답 뒤)에 지난 세션의 늦은 알림(재시도 정리 등)이 나가지 않는다
        (SECFIX 3 H1). 받는 쪽도 `session`으로 지난 세션 알림을 거른다."""
        sid = session.s.session_id
        owner_params: dict[str, Any] = {
            "state": session.state,
            "session": sid,
            "rev": session.rev(),
            "counts": session.counts(),
            "warnings": session.warnings(),
        }
        with self._lock:
            if self.session is not session:
                return
            self._send(session.owner, owner_params, {"state": session.state, "session": sid})

    def publish_idle(self) -> None:
        self._send(None, {"state": "idle"}, {"state": "idle"})

    def _send(self, owner: int | None, owner_params: dict[str, Any], other: dict[str, Any]) -> None:
        transport = self.daemon.transport

        def send() -> None:
            for conn in transport.ui_connections():
                params = owner_params if conn.number == owner else other
                transport.notify(conn, "recorder.changed", params)

        self.daemon.post(send)
