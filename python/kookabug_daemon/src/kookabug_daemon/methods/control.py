"""`control.click/key/type`·`app.launch` (M5 계획 3.9, D6): 에이전트의 게임 조작.

새 입력 경로를 만들지 않는다. daemon이 작은 그래프 값(창 붙기 → 입력 노드 하나 → 통과)을 만들어
내부 진입점 `RunManager.start_internal`로 **기존 runner·감독자·입력 임대권·액터 경로**로 돌린다.
그래서 실행·녹화 중이면 `run_busy`·`recording_active`, 다른 주체가 임대권을 쥐었으면
`input_lease_busy`다. 키·버튼은 액터가 누르고 떼고, runner가 죽으면 감독자가, 둘 다 죽으면 다음
임대권 획득자가 뗀다(기존 보장). 기록은 `runs/` 아래 일반 실행 폴더(`run.json` `source:
agent_control`). 실행 사양의 기록 강제로 스크린샷·영상을 끄고 비밀값을 가린다(`record_override`,
M7 R2 — 워크스페이스 설정과 무관).

- 판정은 처리기가 한다(`self_authorized`): 그 도구(`kb_input_*`) 판정 → ask면 사람 확인(control은
  "항상 허용" 없음) → 집행한 판정을 내부 진입점에 넘긴다(`kb_run_start`를 다시 판정하지 않음)
- 권한 인자는 창 제목. 창은 제목이 **정확히 같은** 창이다
- `window: "@game"`(UX7 C2)은 마지막으로 실행한 게임 프로세스(PID·생성 시각)의 주 창이다 — 제목이
  바뀌어도 붙는다. 권한 판정 인자는 그때의 실제 제목이고, 결과·활동 목록·실행 기록에는 `@game`만
  남긴다(창 제목에 계정 ID가 들어가는 게임이 있다). 제목으로 하나로 정해진 창은 그 프로세스를
  게임으로 기억한다
- `explore.step`(`kb_explore_step`, UX7 C)도 같은 경로(`send_input`)로 입력한다
- `control.type{secret}`은 그래프에 `{"$secret": 키}`만 넣는다. 값은 runner가 찾고, 결과·기록의
  에이전트 쪽 보기(3.8 분류)·오류 메시지에 원문이 없다
- `app.launch`는 입력이 아니라 daemon이 직접 띄운다(실행 Job 밖, C5)
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from kookabug_core.documents import template
from kookabug_core.engine.context import FORBIDDEN_CODES
from kookabug_core.permissions import Decision
from kookabug_core.runner.spec import BoundWindow
from kookabug_daemon.agent_view import MASK
from kookabug_daemon.documents import resolve_path
from kookabug_daemon.explore import StepReservation
from kookabug_daemon.forbidden import check_agent_input
from kookabug_daemon.game_window import GAME, is_game
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed
from kookabug_daemon.screen_source import WindowBinding

__all__ = ["METHODS", "InputTarget", "control_graph", "graph_for", "resolve_target", "send_input"]

WAIT_S: Final = 90.0
"""제어 실행 마무리를 기다리는 한도 (실행 기한 30초 + 하드 종료·감독자 복구 여유)."""
TARGET_TIMEOUT_MS: Final = 3_000
"""target 클릭이 그 target을 기다리는 시간 (지금 화면에 있어야 한다)."""


def _window_arg(call: Call) -> str:
    return str(call.params["window"])


def _node(type_: str, title: str, inputs: Mapping[str, Any], exit_: str) -> dict[str, Any]:
    return {
        "type": type_,
        "version": 1,
        "title": title,
        "in": dict(inputs),
        "next": {exit_: "n_pass"},
    }


def control_graph(call: Call) -> dict[str, Any]:
    """처리기의 params → 한 스텝짜리 그래프 값 (창 붙기 → 입력 → 통과)."""
    return graph_for(call.daemon.root, call.method, call.params, _window_arg(call))


def graph_for(root: Any, method: str, params: Mapping[str, Any], window: str) -> dict[str, Any]:
    """입력 종류(`control.click/key/type`)와 그 인자 → 한 스텝짜리 그래프 값. `window`는 기록에
    남을 창 이름(준 제목 또는 `@game`) — runner는 daemon이 정한 바인딩에만 붙으므로 이 글로 다시
    찾지 않는다."""
    if method == "control.click":
        point, target = params.get("point"), params.get("target")
        if (point is None) == (target is None):
            raise RequestFailed("target_invalid", "point와 target 중 하나만 준다")
        options = {
            "button": str(params.get("button", "left")),
            "count": int(params.get("count", 1)),
        }
        if point is not None:
            node = _node(
                "core.input.click", "클릭", {"point": [int(v) for v in point], **options}, "done"
            )
        else:
            rel = resolve_path(root, str(target)).rel
            node = _node(
                "core.image.click",
                "이미지 클릭",
                {"target": {"$target": rel}, "timeout_ms": TARGET_TIMEOUT_MS, **options},
                "done",
            )
        title = "클릭"
    elif method == "control.key":
        node = _node("core.input.key", "키 입력", {"keys": str(params["keys"])}, "done")
        title = f"키 {params['keys']}"
    else:
        text, secret = params.get("text"), params.get("secret")
        if (text is None) == (secret is None):
            raise RequestFailed("target_invalid", "text와 secret 중 하나만 준다")
        value: Any = {"$secret": str(secret)} if secret is not None else str(text)
        node = _node("core.input.type_text", "글자 입력", {"text": value}, "done")
        title = "글자 입력"
    value = template("test", f"에이전트 제어: {title}")  # 형식·플러그인 판은 새 그래프 틀 그대로
    value.pop("layout", None)
    value["record"] = {"video": "off"}
    value["nodes"] = {
        "n_entry": {
            "type": "core.graph.entry",
            "version": 1,
            "title": "시작",
            "next": {"start": "n_attach"},
        },
        "n_attach": {
            "type": "core.window.attach",
            "version": 1,
            "title": "창에 붙기",
            # 제목이 정확히 같은 창 (부분 일치면 다른 창을 누를 수 있다)
            "in": {"title": f"/^{re.escape(window)}$/"},
            "next": {"found": "n_input"},
        },
        "n_input": node,
        "n_pass": {"type": "core.test.pass", "version": 1, "title": "통과"},
    }
    return value


def _result(run_id: str, outcome: Any) -> dict[str, Any]:
    run_end: Mapping[str, Any] | None = None if outcome is None else outcome.run_end
    if run_end is None:
        return {
            "run_id": run_id,
            "verdict": "error",
            "error": {"code": "runner_died", "message": "제어 실행이 끝나지 않았다"},
        }
    verdict = str(run_end.get("verdict", "error"))
    out: dict[str, Any] = {"run_id": run_id, "verdict": verdict}
    if verdict != "pass":
        code = str(run_end.get("code") or "failed")
        if code == "input_lease_busy":
            raise RequestFailed(
                "input_lease_busy",
                "다른 주체가 입력 임대권을 쥐고 있어 게임을 조작하지 않았다",
                run_id=run_id,
            )
        if code in FORBIDDEN_CODES:
            # runner가 입력 직전 판정에서 막았다 (사유는 정책 항목·고정 글자뿐 — `Refusal.message`)
            reason = run_end.get("reason")
            raise RequestFailed(
                code,
                str(reason)
                if isinstance(reason, str) and not run_end.get("secret_paths")
                else "입력 직전 금지 동작 판정에 걸려 입력하지 않았다",
                kind=None,
                value=None,
                reason="runner",
                run_id=run_id,
            )
        # 사유는 실행 때 분류(3.8)대로 가린다: 비밀값이 든 사유면 ***
        reason = run_end.get("reason")
        secret = "/reason" in (run_end.get("secret_paths") or ())
        message = MASK if secret else (str(reason) if isinstance(reason, str) else code)
        out["error"] = {"code": code, "message": message}
    return out


def _input_kind(
    method: str, params: Mapping[str, Any]
) -> tuple[str, tuple[int, int] | None, str | None]:
    """(입력 종류, 점 클릭의 점, 비밀값 키) — 보호 기록·칸 상자 근거(M7 R3)용."""
    if method == "control.click":
        point = params.get("point")
        return "click", None if point is None else (int(point[0]), int(point[1])), None
    if method == "control.key":
        return "key", None, None
    secret = params.get("secret")
    return "type", None, None if secret is None else str(secret)


@dataclass(frozen=True, slots=True)
class InputTarget:
    """입력할 창 (UX7 C2). `label`은 결과·활동·기록에 남길 이름(준 제목 또는 `@game`), `title`은
    권한 판정 인자(지금 실제 제목), `bindings`는 정확히 하나로 정해졌을 때만 그 바인딩."""

    label: str
    title: str
    bindings: list[WindowBinding] | None
    """None이면 아직 찾지 않았다 — 판정 뒤 실행 시작 바로 앞에서 찾는다(제목 입력, M7 R1·B3)."""
    bound: BoundWindow | None


def later(window: str) -> InputTarget:
    """제목 입력: 창은 판정(사람 확인) 뒤에 한 번 찾는다 — 지금까지와 같은 순서."""
    return InputTarget(window, window, None, None)


async def find_titled(call: Call, window: str) -> InputTarget:
    """제목이 **정확히 같은** 창 하나 (runner 붙기와 같은 함수). 아니면 붙지 않는 바인딩(hwnd 0).
    조회만 한다 — 게임 기억은 판정이 허용되고 입력이 성공한 뒤에 쓴다(`remember_target`)."""
    found = await asyncio.to_thread(call.daemon.screen_source.find, window)
    if len(found) == 1:
        only = found[0]
        return InputTarget(
            window, window, [only], BoundWindow(only.hwnd, only.pid, only.created, window)
        )
    return InputTarget(window, window, [], BoundWindow(0, 0, "", window))


async def resolve_target(call: Call, window: str) -> InputTarget:
    """창 이름 → 입력할 창. 제목은 **정확히 같은** 창 하나(runner 붙기와 같은 함수) — 아니면 붙지
    않는 바인딩(hwnd 0)이라 입력 없이 실패한다(M7 R1). `@game`은 기억한 게임 프로세스의 주 창(없으면
    판정을 먼저 한 뒤 `window_not_found` — 거부 정책이면 `permission_denied`)이고 제목 비교 없이
    PID·생성 시각으로 붙는다."""
    if is_game(window):
        try:
            binding, title = await asyncio.to_thread(call.daemon.game.resolve, call.principal)
        except RequestFailed:
            await refuse_if_denied(call, GAME)
            raise
        bound = BoundWindow(binding.hwnd, binding.pid, binding.created, "", match_title=False)
        return InputTarget(GAME, title, [binding], bound)
    return await find_titled(call, window)


def remember_target(call: Call, target: InputTarget) -> None:
    """판정이 허용되고 입력(또는 탐색 걸음)이 성공한 뒤에만: 제목으로 하나로 정해진 창의 프로세스를
    **요청 주체의** 게임으로 기억한다 (UX7 검수 1 High 3 — 거부·승인 대기·실패에는 상태 변경
    없음)."""
    if target.label != GAME and target.bindings is not None and len(target.bindings) == 1:
        call.daemon.game.remember(call.principal, target.bindings[0])


async def refuse_if_denied(call: Call, arg: str) -> None:
    """창을 정하지 못했을 때도 거부 정책이면 `permission_denied`가 먼저다 (사람에게 묻지는 않는다 —
    입력하지 않을 요청이므로)."""
    authorizer = call.daemon.approvals.authorizer
    peek = await asyncio.to_thread(authorizer.peek, call.principal, call.method, arg)
    if peek is not None and peek.final == "deny":
        await asyncio.to_thread(authorizer.require, call.principal, call.method, arg)


async def _control(call: Call) -> dict[str, Any]:
    value = control_graph(call)  # 인자가 틀리면 판정 전에 거부 (아무것도 묻지 않음)
    window = _window_arg(call)
    # `@game`은 판정 인자(지금 제목)가 필요해 먼저 정하고, 제목은 판정 뒤에 찾는다
    target = await resolve_target(call, window) if is_game(window) else later(window)
    return await send_input(call, call.method, call.params, target, value)


async def send_input(
    call: Call,
    method: str,
    params: Mapping[str, Any],
    target: InputTarget,
    value: dict[str, Any],
) -> dict[str, Any]:
    """제어 실행 하나 (`kb_input_*`·`kb_explore_step` 공용). 판정은 `call.method`의 도구로 한다."""
    # 개발 모듈 daemon의 에이전트 제어 실행은 사람 확인을 묻기 전에 거부 (M6 3.7)
    call.daemon.run_manager.refuse_dev_modules(call.principal)
    # 작업 판정(M8 R8)도 사람 확인을 묻기 전에 한 번 본다 (시작 잠금 안에서 다시 본다)
    call.daemon.run_manager.refuse_job_bypass(call.principal)
    # 탐색 세션 스텝 예산: 판정(사람 확인) **전에** 한 칸 예약 (M7 3.4, B3 Mid 2). 제어 실행에
    # 들어가면 스텝으로 확정, 판정 거부·사람 거부·취소·시작 실패면 되돌린다
    # (세션 잠금은 저장 게시 동안 쥐어질 수 있어 이벤트 루프 밖에서)
    step = await asyncio.to_thread(call.daemon.explore.reserve, call.connection)
    try:
        return await _reserved(call, method, params, target, value, step)
    finally:
        if step is not None:
            # 확정했으면 아무 일도 하지 않는다. 취소(연결 끊김) 중에도 되돌려야 하므로 바로 부른다
            step.release()


async def _reserved(
    call: Call,
    method: str,
    params: Mapping[str, Any],
    target: InputTarget,
    value: dict[str, Any],
    step: StepReservation | None,
) -> dict[str, Any]:
    authorized = await call.daemon.approvals.authorize(call, target.title)
    decision = authorized.decision
    assert isinstance(decision, Decision)  # control.*·explore.step은 ui_only가 아니다
    manager = call.daemon.run_manager
    guard = call.daemon.guard
    kind, point, secret = _input_kind(method, params)
    if target.bindings is None:
        # 대상 창을 여기서 **한 번** 정한다 (판정 뒤 — M7 R1). 정확히 하나가 아니면 붙지 않는
        # 바인딩(hwnd 0)을 넘겨 입력 없이 실패한다
        target = await find_titled(call, target.label)
    bindings = target.bindings or []
    bound = target.bound
    assert bound is not None
    # 자동 채택 검증 중이면 Agent 입력을 받지 않는다 (M8 R7 — 시작 예약 안에서 다시 본다)
    manager.refuse_agent_during_verification(call.principal)
    # 금지 동작 (M8 3.7·R6): 창이 하나로 정해졌으면 보내기 전에 그 창 한 장으로 판정한다(비밀값
    # 보호 기록을 쓰기 전 — 이 입력이 만들 보호로 자기 자신을 막지 않게). 창이 없으면 제어 실행이
    # 창 붙기에서 입력 없이 끝난다. 어느 쪽이든 runner가 입력 직전에 같은 판정을 다시 한다
    if bindings:
        await asyncio.to_thread(check_agent_input, call.daemon, call.principal, bindings)
    before = None
    if point is not None and bindings:
        before = await asyncio.to_thread(guard.before_click, bindings)
    if secret is not None and bindings:
        # 그 바인딩의 보호 기록을 디스크에 쓴 뒤에만 비밀값을 보낸다. 실패면 protect_record_failed
        await asyncio.to_thread(guard.record_secret, call.connection, bindings, secret)
    try:
        # "이 탐색 동안 허용"으로 승인된 입력은 그 세션 동안만 유효하다: 판정 뒤 창 찾기·보호 기록
        # 사이에 세션이 끝났으면 실행하지 않는다 (예약은 finally가 되돌림, B3 검수 Mid 1)
        if authorized.scoped and (
            step is None or call.daemon.explore.live(call.connection, step.session.id) is None
        ):
            raise RequestFailed(
                "explore_not_active",
                "탐색 세션이 끝나 '이 탐색 동안 허용'으로 승인된 입력을 보내지 않았다",
            )
        run_id = await asyncio.to_thread(
            functools.partial(
                manager.start_internal,
                call.principal,
                value,
                decision,
                approved=authorized.approved,
                bound_window=bound,
            )
        )
        # 판정을 통과해 제어 실행에 들어갔다: 예약한 칸을 탐색 세션의 스텝 하나로
        if step is not None:
            await asyncio.to_thread(step.commit)
        outcome = await asyncio.to_thread(manager.wait_outcome, run_id, WAIT_S)
    finally:
        # 결과와 상관없이 이 창들로 입력이 갔다고 본다 (칸 상자 근거를 끊는 쪽이 안전)
        await asyncio.to_thread(
            functools.partial(
                guard.note_input, call.connection, bindings, kind, point=point, before=before
            )
        )
    result = _result(run_id, outcome)
    if result["verdict"] == "pass":
        remember_target(call, target)
    return result


async def _launch(call: Call) -> dict[str, Any]:
    call.daemon.run_manager.refuse_job_bypass(call.principal)  # 사람 확인 전 (잠금 안에서 다시)
    await call.daemon.approvals.authorize(call, "")
    profile = call.params.get("profile")
    pid = await asyncio.to_thread(
        functools.partial(
            call.daemon.run_manager.launch_app,
            None if profile is None else str(profile),
            principal=call.principal,
        )
    )
    # `@game`의 대상 (UX7 C2): 띄운 주체의 기억에 PID·프로세스 생성 시각으로 (사람이면 쓰지 않음)
    await asyncio.to_thread(call.daemon.game.remember_pid, call.principal, pid)
    return {"pid": pid}


METHODS: Final = {
    "control.click": MethodSpec(_control, _window_arg, self_authorized=True),
    "control.key": MethodSpec(_control, _window_arg, self_authorized=True),
    "control.type": MethodSpec(_control, _window_arg, self_authorized=True),
    "app.launch": MethodSpec(_launch, self_authorized=True),
}
