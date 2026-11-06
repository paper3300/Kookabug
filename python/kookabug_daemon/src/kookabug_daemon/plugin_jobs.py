"""daemon 플러그인 작업 관리자 (M6 계획 3.8): 한 번에 하나·취소·진행 알림·미리보기 5분 보관.

- 작업 하나 = 전용 스레드에서 `PluginOps` 거래 하나 (`busy.lock`은 그 거래가 쥔다 — CLI와 같은 코드,
  다른 프로세스의 작업과도 하나씩). 거래 ID = 작업 ID (`op_id`, 작업 로그 이름)
- 미리보기(`plugins.preview`·`plugins.upgrade`)는 거래의 ③ 신뢰 확인 콜백에서 멈춰 `PREVIEW_TTL_S`
  동안 사람의 `plugins.install {op_id}`를 기다린다. ①②(받은 원천·정적 읽기)는 그 거래의 staging에
  그대로 있다. 시간이 지나거나 취소하면 ③에서 취소 — 실행된 코드 없음. 미리보기를 기다리는 동안
  `op.lock`은 쥐지 않는다 (실행 시작이 기다리지 않는다)
- 취소(`plugins.cancel`)·daemon 종료 = 거래 취소(설치 작업 Job 끝내기). 커밋(⑨) 전이면 잠금·기존
  환경 그대로, 커밋 뒤면 효과 없음 (3.5)
- 이 관리자는 권한을 판정하지 않는다: 변경 메서드는 모두 `ui_only` + `AGENT_DENIED`(`tools.py`)
- 결과·오류는 가린 값만 내보낸다: `PluginError.to_json()`(만들 때 가림), 그 밖의 예외는 종류 +
  `redact.mask` 문구, 결과는 `mask_value`
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol

from kookabug_core.plugins import AppInfo, PluginError, PluginOps, Preview
from kookabug_core.plugins.redact import mask, mask_value
from kookabug_daemon.protocol import RequestFailed

__all__ = ["CLOSE_WAIT_S", "PREVIEW_TTL_S", "STAGE_TEXT", "JobSink", "PluginJobs"]

log = logging.getLogger(__name__)

PREVIEW_TTL_S: Final = 300.0
"""미리보기를 보관하는 시간 (그 안에 `plugins.install`이 없으면 ③에서 취소)."""
CLOSE_WAIT_S: Final = 60.0
"""daemon이 끝날 때 취소한 작업이 마무리(staging 정리)되기를 기다리는 시간."""

STAGE_TEXT: Final = {
    "fetched": "원천을 받았어요",
    "manifest": "플러그인 정보를 확인했어요",
    "confirmed": "신뢰 확인을 받았어요",
    "resolved": "의존성을 풀었어요",
    "built": "플러그인을 빌드했어요",
    "env_venv": "환경을 만드는 중이에요",
    "env_synced": "의존성을 설치했어요",
    "env_installed": "플러그인을 설치했어요",
    "env_verified": "플러그인을 확인했어요",
    "env_complete": "환경을 완성했어요",
    "env_reused": "같은 환경을 다시 써요",
    "archived": "wheel을 보관했어요",
    "before_commit": "잠금을 바꾸는 중이에요",
    "committed": "잠금을 바꿨어요",
}
"""진행 알림 문구 (거래 단계 → 사람이 읽는 말)."""

KINDS: Final = ("install", "upgrade", "remove", "sync", "relock", "gc")


class JobSink(Protocol):
    """작업이 알릴 곳 (daemon). 작업 스레드에서 부른다."""

    def post(self, fn: Callable[[], None]) -> None:
        """이벤트 루프에서 `fn`을 부른다."""
        ...

    def notify_ui(self, method: str, params: Mapping[str, Any]) -> None:
        """ui 연결에 알린다 (이벤트 루프 안)."""
        ...

    def plugins_lock_check(self) -> None:
        """잠금이 바뀌었는지 보고 바뀌었으면 레지스트리를 다시 만들고 `plugins.changed`
        (작업 스레드에서, 이벤트 루프 밖)."""
        ...


@dataclass
class _Job:
    op_id: str
    kind: str
    ops: PluginOps
    owner: int | None = None
    """미리보기를 연 연결 (그 연결이 끊기면 승인 대기 중인 미리보기를 취소한다)."""
    announced: bool = False
    """op_id를 클라이언트에 알렸다 (진행·끝 알림 대상)."""
    preview: dict[str, Any] | None = None
    preview_ready: threading.Event = field(default_factory=threading.Event)
    """미리보기가 나왔거나 작업이 끝났다."""
    decided: threading.Event = field(default_factory=threading.Event)
    approved: bool = False
    expired: bool = False
    cancelled: bool = False
    done: bool = False
    stage: str | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    thread: threading.Thread | None = None


def _unexpected(exc: BaseException, stage: str | None) -> dict[str, Any]:
    """`PluginError`가 아닌 예외: 종류 + 가린 문구만 (원문·traceback은 내보내지 않는다)."""
    return {
        "code": "internal_error",
        "stage": stage,
        "message": f"{type(exc).__name__}: {mask(str(exc))}",
    }


def plugin_failed(error: Mapping[str, Any]) -> RequestFailed:
    """플러그인 작업 오류 → 요청 오류 (`plugin_failed`, data.plugin_error)."""
    return RequestFailed("plugin_failed", str(error.get("message", "")), plugin_error=dict(error))


class PluginJobs:
    """워크스페이스 하나의 daemon 플러그인 작업. 메서드는 이벤트 루프 밖(스레드)에서 불러도 된다."""

    def __init__(
        self,
        root: Path,
        environ: Mapping[str, str],
        sink: JobSink,
        *,
        preview_ttl_s: float = PREVIEW_TTL_S,
    ) -> None:
        self.root = root
        self.environ = dict(environ)
        self.sink = sink
        self.preview_ttl_s = preview_ttl_s
        self._lock = threading.Lock()
        self._job: _Job | None = None
        self._closing = False
        self._app: AppInfo | None = None

    # ------------------------------------------------------------ 상태

    def app(self) -> AppInfo:
        """앱 조건 (한 번 찾는다 — 앱의 SDK wheel은 daemon이 도는 동안 바뀌지 않는다). 못 찾으면
        `PluginError(app_incomplete)` (다음에 다시 찾는다)."""
        if self._app is None:
            self._app = AppInfo.detect(self.environ)
        return self._app

    def _app_or_none(self) -> AppInfo | None:
        """못 찾으면 None: 목록은 조건 다름으로 보이고, 거래는 다시 찾다가 app_incomplete로
        끝난다."""
        try:
            return self.app()
        except PluginError:
            return None

    def reader(self) -> PluginOps:
        """목록·판정용 (거래 없음)."""
        return PluginOps(self.root, environ=self.environ, app=self._app_or_none())

    def active(self) -> bool:
        with self._lock:
            return self._job is not None

    def current(self, connection: int | None = None) -> dict[str, Any] | None:
        """진행 중인 작업 (`plugins.list`의 `busy`). 승인을 기다리는 미리보기의 `op_id`는 연
        연결(`connection` = `owner`)에만 보인다 — 다른 연결은 바쁘다는 것만 안다."""
        with self._lock:
            job = self._job
            if job is None:
                return None
            waiting = self._waiting(job)
            shown = None if waiting and job.owner != connection else job.op_id
            return {"op_id": shown, "kind": job.kind, "stage": job.stage, "waiting": waiting}

    # ------------------------------------------------------------ 시작

    def _new(self, kind: str) -> _Job:
        """이 daemon의 작업 자리를 잡는다 (한 번에 하나). 이벤트 루프 밖에서 부른다."""
        op_id = uuid.uuid4().hex
        job_ref: list[_Job] = []

        def progress(stage: str) -> None:
            job = job_ref[0]
            job.stage = stage
            with self._lock:
                announced = job.announced
            if announced and stage in STAGE_TEXT:
                params = {"op_id": op_id, "stage": stage, "message": STAGE_TEXT[stage]}
                self.sink.post(lambda: self.sink.notify_ui("plugins.progress", params))

        ops = PluginOps(
            self.root,
            environ=self.environ,
            app=self._app_or_none(),
            fault=progress,
            op_id=op_id,
        )
        job = _Job(op_id, kind, ops)
        job_ref.append(job)
        with self._lock:
            if self._closing:
                raise RequestFailed("shutting_down", "daemon이 끝나는 중이다", message="끝나는 중")
            if self._job is not None:
                # 승인 대기 미리보기의 ID는 내놓지 않는다 (연 연결만 안다)
                busy = {} if self._waiting(self._job) else {"op_id": self._job.op_id}
                raise plugin_failed(
                    {
                        "code": "plugin_busy",
                        "stage": None,
                        "message": "다른 플러그인 작업이 진행 중이다",
                        **busy,
                    }
                )
            self._job = job
        return job

    def _run(self, job: _Job, body: Callable[[PluginOps], dict[str, Any]]) -> None:
        thread = threading.Thread(
            target=self._body, args=(job, body), name=f"kb-plugin-{job.kind}", daemon=True
        )
        job.thread = thread
        thread.start()

    def _body(self, job: _Job, body: Callable[[PluginOps], dict[str, Any]]) -> None:
        try:
            job.result = mask_value(body(job.ops))
        except PluginError as exc:
            error = exc.to_json()
            if exc.code == "cancelled" and job.expired:
                error["message"] = "미리보기를 5분 안에 승인하지 않아 취소했다"
            job.error = error
        except Exception as exc:
            log.error("플러그인 작업 %s(%s)이 실패했다: %s", job.kind, job.op_id, mask(repr(exc)))
            job.error = _unexpected(exc, job.stage)
        with self._lock:
            job.done = True
            announced = job.announced
            if self._job is job:
                self._job = None
        job.preview_ready.set()
        if announced:
            params: dict[str, Any] = {"op_id": job.op_id, "kind": job.kind, "ok": job.error is None}
            if job.error is not None:
                params["error"] = job.error
            else:
                params["result"] = job.result or {}
            self.sink.post(lambda: self.sink.notify_ui("plugins.done", params))
        try:
            self.sink.plugins_lock_check()
        except Exception:
            log.exception("플러그인 잠금 변경을 알리지 못했다")

    def start(self, kind: str, body: Callable[[PluginOps], dict[str, Any]]) -> dict[str, Any]:
        """곧바로 진행하는 작업 (remove·sync·relock·gc): `{op_id}`를 돌려주고 끝은 알림."""
        assert kind in KINDS
        job = self._new(kind)
        job.announced = True
        self._run(job, body)
        return {"op_id": job.op_id}

    def preview(
        self,
        kind: str,
        body: Callable[[PluginOps, Callable[[Preview], bool]], dict[str, Any]],
        *,
        owner: int | None = None,
    ) -> dict[str, Any]:
        """①②를 돌려 미리보기를 돌려준다 (막히는 호출 — 이벤트 루프 밖에서). ①② 실패는
        `plugin_failed`. 미리보기는 `preview_ttl_s` 동안 `install`을 기다린다 (연 연결 `owner`가
        끊기면 취소)."""
        assert kind in ("install", "upgrade")
        job = self._new(kind)
        job.owner = owner

        def confirm(preview: Preview) -> bool:
            with self._lock:
                job.preview = mask_value({**preview.to_json(), "op_id": job.op_id})
            job.preview_ready.set()
            job.decided.wait(self.preview_ttl_s)
            with self._lock:
                if not job.decided.is_set():
                    job.expired = True
                    job.decided.set()
                return job.approved

        self._run(job, lambda ops: body(ops, confirm))
        job.preview_ready.wait()
        with self._lock:
            if not job.done and job.preview is not None:
                job.announced = True
                return {**job.preview, "expires_in_s": self.preview_ttl_s}
        # ①②에서 끝났다 (오류). 알림 없이 이 요청의 오류로
        assert job.thread is not None
        job.thread.join(5)
        raise plugin_failed(
            job.error or {"code": "cancelled", "stage": "manifest", "message": "작업이 끝났다"}
        )

    @staticmethod
    def _waiting(job: _Job) -> bool:
        """승인을 기다리는 미리보기 (잠금 안에서 본다)."""
        return job.preview is not None and not job.decided.is_set() and not job.done

    @staticmethod
    def _not_owner(op_id: str) -> RequestFailed:
        return RequestFailed(
            "permission_denied",
            "미리보기를 연 연결만 승인·취소한다 (신뢰 확인을 본 사람이 승인한다)",
            op_id=op_id,
        )

    def install(self, op_id: str, connection: int) -> dict[str, Any]:
        """미리보기를 승인한다 (③ 뒤로 진행). 끝은 알림. 미리보기를 연 연결(`connection` =
        `owner`)만 — 신뢰 확인을 본 화면과 승인하는 화면이 같아야 한다. 다른 연결의 요청은 거부하고
        미리보기는 그대로 기다린다."""
        with self._lock:
            job = self._job
            if job is None or job.op_id != op_id or not self._waiting(job):
                raise RequestFailed(
                    "op_not_found",
                    "승인할 미리보기가 없다 (5분이 지났거나 취소했거나 다른 작업이다)",
                    op_id=op_id,
                )
            if job.owner != connection:
                raise self._not_owner(op_id)
            job.approved = True
            job.decided.set()
        return {"op_id": op_id}

    def cancel(self, op_id: str, connection: int) -> dict[str, Any]:
        """그 작업을 취소한다. 미리보기면 ③에서(연 연결만), 진행 중이면 설치 작업 Job을 끝낸다
        (커밋 뒤면 효과 없음 — 진행 중인 작업은 어느 ui 연결이나 취소할 수 있다). 결과는
        `plugins.done`으로 온다."""
        with self._lock:
            job = self._job
            if job is None or job.op_id != op_id or job.done:
                raise RequestFailed("op_not_found", "그 플러그인 작업이 없다", op_id=op_id)
            if self._waiting(job) and job.owner != connection:
                raise self._not_owner(op_id)
            self._cancel_locked(job)
        job.ops.cancel()
        return {}

    def connection_closed(self, connection: int) -> None:
        """그 연결이 연 미리보기가 승인을 기다리는 중이면 취소한다 (승인 뒤 진행 중인 작업은 그대로
        — 끝 알림은 다른 ui 연결이 받는다). busy.lock을 5분 동안 쥐고 있지 않게."""
        with self._lock:
            job = self._job
            if job is None or job.owner != connection or job.decided.is_set() or job.done:
                return
            self._cancel_locked(job)
        job.ops.cancel()

    def _cancel_locked(self, job: _Job) -> None:
        job.cancelled = True
        if not job.decided.is_set():
            job.decided.set()  # approved는 False 그대로: ③에서 취소

    def close(self, wait_s: float = CLOSE_WAIT_S) -> None:
        """daemon 종료: 새 작업을 받지 않고 진행 중인 작업을 취소한 뒤 마무리를 기다린다."""
        with self._lock:
            self._closing = True
            job = self._job
            if job is not None:
                self._cancel_locked(job)
        if job is None:
            return
        job.ops.cancel()
        if job.thread is not None:
            deadline = time.monotonic() + wait_s
            job.thread.join(max(0.0, deadline - time.monotonic()))
            if job.thread.is_alive():
                log.warning("플러그인 작업 %s이 %g초 안에 끝나지 않았다", job.op_id, wait_s)
