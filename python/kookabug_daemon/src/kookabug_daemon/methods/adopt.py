"""`adopt.request`·`adopt.revert`·`adoptions.list`·`evidence.pin` (M8 계획 3.8·3.13, B3·B4).

`adopt.request`·`evidence.pin`은 툴셋 `cases`의 도구(`kb_adopt_request`·`kb_evidence_pin`)로
판정한다 (B4 — `qa_runner`는 `kb_adopt_request` deny). `adopt.revert`·`adoptions.list`는 사람 전용
(`ui_only` + `AGENT_DENIED`).

- `adopt.request`: 조건 1~8을 Kookabug가 결정적으로 검사한다(`kookabug_daemon.adopt`). 검증 실행은
  Kookabug가 고른다 — 요청은 실행 ID를 받지 않는다. 요청이 준 음성 프레임은 **이 연결이 만든** 정지
  화면만이다
- `adopt.revert`: 채택 뒤 바이트일 때만 원래 바이트로 한 번
- `evidence.pin`: 실행 기록 → 가림 처리한 최소 묶음. 지우거나 고치는 메서드는 없다
"""

from __future__ import annotations

import asyncio
import functools
import threading
from collections.abc import Callable, Mapping
from typing import Any, Final

from kookabug_core import adopt as rules
from kookabug_core.filetx import TxError
from kookabug_core.knowledge.formats import Actor, KnowledgeError, SecretCheck, secret_checker
from kookabug_core.workspace import Workspace, WorkspaceError, default_secrets
from kookabug_daemon.adopt import Adopter, RunVerifier, pin_run, request_negatives, secret_keys_of
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS", "actor_of", "checker_of", "failed", "guarded", "pin_of", "text_checker"]

_PASS: Final = frozenset(
    {
        "revision_conflict",
        "already_reverted",
        "change_not_active",
        "nothing_to_revert",
        "evidence_missing",
        "recovery_pending",
        "knowledge_busy",
        "policy_path",
        "exists",
        "secret_in_text",
        "secret_unchecked",
    }
)


def failed(exc: KnowledgeError | TxError) -> RequestFailed:
    code = exc.code
    if code == "unknown_id":
        return RequestFailed(
            "not_found", exc.message, path=str(getattr(exc, "fields", {}).get("id", ""))
        )
    if code == "path_outside_workspace":
        return RequestFailed("policy_path", exc.message)
    if code == "format":
        return RequestFailed("validation_failed", exc.message, diagnostics=[])
    if code == "revision_conflict":
        return RequestFailed("revision_conflict", exc.message, revision=None)
    if code in _PASS:
        return RequestFailed(code, exc.message)
    return RequestFailed("io_error", exc.message, message=exc.message)


def guarded(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except (KnowledgeError, TxError) as exc:
        raise failed(exc) from exc
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc


def actor_of(call: Call) -> Actor:
    p = call.principal
    if p.kind == "agent":
        return Actor(
            "agent", p.id, client=call.daemon.connection_name(call.connection) or None, job=p.job
        )
    return Actor("human", p.id)


def _negatives(call: Call, items: list[Mapping[str, Any]]) -> list[Any]:
    """요청 음성 프레임: 이 연결이 만든 정지 화면만 (다른 연결·녹화 프레임은 거부)."""
    out: list[tuple[str, Any, str, str]] = []
    for item in items:
        frame = call.daemon.frames.get(str(item["frame_id"]))
        if frame.owner != call.connection or frame.origin == "recorder":
            raise RequestFailed(
                "frame_not_owned",
                "음성 대조에는 이 연결이 만든 정지 화면만 쓴다",
                frame_id=frame.frame_id,
            )
        out.append(
            (frame.frame_id, frame.pixels, f"connection:{call.connection}", str(item["note"]))
        )
    return request_negatives(out)


def checker_of(call: Call) -> SecretCheck:
    """daemon의 글자 검사기 (지식 연산·위키·사건·채택 기록·감사 이력·증거 묶음·보고 메모 — M7
    3.5b와 같은 규칙 + 작업 토큰 원문, M8 R9). 키를 못 읽거나 보호 기록이 손상됐으면
    `secret_unchecked`."""
    return text_checker(call.daemon)


def text_checker(daemon: Any, keys: set[str] | None = None) -> SecretCheck:
    """보호 기록의 비밀값 키(+ `keys`) 값과 daemon 메모리의 작업 토큰 원문(살아 있는 것 + 폐기했지만
    보고를 아직 쓰지 않은 것)을 거르는 검사기. 보고 생성 직전 재검사도 이것을 쓴다."""
    guard = daemon.guard
    workspace = Workspace.open(daemon.root)
    jobs = getattr(daemon, "jobs", None)
    return secret_checker(
        set(getattr(guard, "secret_keys", ()) or ()) | (keys or set()),
        default_secrets(workspace),
        blocked=bool(getattr(guard, "save_blocked", False)),
        extra=None if jobs is None else jobs.secret_values,
    )


async def _request(call: Call) -> dict[str, Any]:
    p = call.params
    extra = _negatives(call, list(p.get("negatives") or []))
    try:
        check = checker_of(call)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    cancelled = threading.Event()
    case_id, change_id = str(p["case"]), str(p["change"])
    job = call.principal.job
    daemon = call.daemon
    pending = None
    if job is not None:
        # 작업이 끝나면(R8) 이 요청에 취소 표시를 세우고 도는 검증 실행을 취소한다. 종료 경로가
        # 이미 시작됐으면 바로 취소 표시
        pending = daemon.job_adopts.add(job, cancelled)
        live = daemon.jobs.get(job)
        if live is None or live.ending.is_set():
            cancelled.set()

    started = threading.Event()

    def work() -> dict[str, Any]:
        started.set()
        # 검증 세션은 작업 스레드 안에서 열고 **스레드가 실제로 끝날 때** 닫는다 (R7): 요청 Task가
        # 취소돼도(연결 끊김) 스레드는 계속 돌므로 그동안 Agent 입력 차단을 유지한다. 작업 연결의
        # 검증 실행은 작업 실행 예산을 쓴다 (조율자 결정)
        budget = None if job is None else functools.partial(daemon.jobs.take_run, job)
        verifier = RunVerifier(daemon.run_manager, budget=budget, job=job)
        try:
            if pending is not None:
                daemon.job_adopts.attach(pending, verifier)
            adopter = Adopter(
                daemon.root, verifier, check_secrets=check, cancelled=cancelled, job=job
            )
            return guarded(adopter.request, case_id, change_id, extra)
        finally:
            verifier.close()
            if pending is not None:
                daemon.job_adopts.finish(pending)

    try:
        return await asyncio.to_thread(work)
    except asyncio.CancelledError:
        # 요청 취소·연결 끊김: 남은 검증·게시를 하지 않게 표시한다 (이미 게시 거래면 끝까지 간다)
        cancelled.set()
        if pending is not None and not started.is_set():
            daemon.job_adopts.finish(pending)  # 스레드가 시작도 못 했다: 기다릴 것이 없다
        raise


async def _revert(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(
        guarded, rules.revert, call.daemon.root, str(call.params["adoption"]), by=call.principal.id
    )


async def _list(call: Call) -> dict[str, Any]:
    found = await asyncio.to_thread(guarded, rules.list_adoptions, call.daemon.root)
    return {"adoptions": found}


def _pin_sync(call: Call) -> dict[str, Any]:
    p = call.params
    step = p.get("step")
    return pin_of(call, str(p["run"]), None if step is None else str(step), str(p["note"]))


def pin_of(call: Call, run_id: str, step: str | None, note: str | None) -> dict[str, Any]:
    """그 실행의 증거 묶음을 고정한다 (`evidence.pin`과 사건 열기의 원래 실패 자동 고정이 같은
    길)."""
    where = call.daemon.run_manager.locate(run_id)
    guard = call.daemon.guard
    check = text_checker(call.daemon, secret_keys_of(where.folder))

    def guard_of(pixels: Any) -> str:
        from kookabug_daemon.frames import EditorFrame

        size = (int(pixels.shape[1]), int(pixels.shape[0]))
        verdict = guard.check(EditorFrame("evidence", pixels, size, 96, "", origin="run"))
        return "clear" if verdict.clear else str(verdict.reason or "frame_protected")

    actor = actor_of(call)
    by = {"kind": actor.kind} | ({"id": actor.id} if actor.id else {})
    return pin_run(
        call.daemon.root,
        where.folder,
        where.run_id,
        step=step,
        note=note,
        by=by,
        actor=actor,
        check_secrets=check,
        guard_of=guard_of,
    )


async def _pin(call: Call) -> dict[str, Any]:
    return await asyncio.to_thread(guarded, _pin_sync, call)


METHODS: Final[dict[str, MethodSpec]] = {
    "adopt.request": MethodSpec(_request),
    "adopt.revert": MethodSpec(_revert),
    "adoptions.list": MethodSpec(_list),
    "evidence.pin": MethodSpec(_pin),
}
