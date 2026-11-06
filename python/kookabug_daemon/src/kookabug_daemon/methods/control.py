"""`control.click/key/type`·`app.launch` (M5 계획 3.9, D6): 에이전트의 게임 조작.

새 입력 경로를 만들지 않는다. daemon이 작은 그래프 값(창 붙기 → 입력 노드 하나 → 통과)을 만들어
내부 진입점 `RunManager.start_internal`로 **기존 runner·감독자·입력 임대권·액터 경로**로 돌린다.
그래서 실행·녹화 중이면 `run_busy`·`recording_active`, 다른 주체가 임대권을 쥐었으면
`input_lease_busy`다. 키·버튼은 액터가 누르고 떼고, runner가 죽으면 감독자가, 둘 다 죽으면 다음
임대권 획득자가 뗀다(기존 보장). 기록은 `runs/` 아래 일반 실행 폴더(`run.json` `source:
agent_control`, 영상 off).

- 판정은 처리기가 한다(`self_authorized`): 그 도구(`kb_input_*`) 판정 → ask면 사람 확인(control은
  "항상 허용" 없음) → 집행한 판정을 내부 진입점에 넘긴다(`kb_run_start`를 다시 판정하지 않음)
- 권한 인자는 창 제목. 창은 제목이 **정확히 같은** 창이다
- `control.type{secret}`은 그래프에 `{"$secret": 키}`만 넣는다. 값은 runner가 찾고, 결과·기록의
  에이전트 쪽 보기(3.8 분류)·오류 메시지에 원문이 없다
- `app.launch`는 입력이 아니라 daemon이 직접 띄운다(실행 Job 밖, C5)
"""

from __future__ import annotations

import asyncio
import functools
import re
from collections.abc import Mapping
from typing import Any, Final

from kookabug_core.documents import template
from kookabug_core.permissions import Decision
from kookabug_daemon.agent_view import MASK
from kookabug_daemon.documents import resolve_path
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

__all__ = ["METHODS", "control_graph"]

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
    params = call.params
    window = _window_arg(call)
    method = call.method
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
            rel = resolve_path(call.daemon.root, str(target)).rel
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
        # 사유는 실행 때 분류(3.8)대로 가린다: 비밀값이 든 사유면 ***
        reason = run_end.get("reason")
        secret = "/reason" in (run_end.get("secret_paths") or ())
        message = MASK if secret else (str(reason) if isinstance(reason, str) else code)
        out["error"] = {"code": code, "message": message}
    return out


async def _control(call: Call) -> dict[str, Any]:
    value = control_graph(call)  # 인자가 틀리면 판정 전에 거부 (아무것도 묻지 않음)
    authorized = await call.daemon.approvals.authorize(call, _window_arg(call))
    decision = authorized.decision
    assert isinstance(decision, Decision)  # control.*은 ui_only가 아니다
    manager = call.daemon.run_manager
    run_id = await asyncio.to_thread(
        functools.partial(
            manager.start_internal,
            call.principal,
            value,
            decision,
            approved=authorized.approved,
        )
    )
    outcome = await asyncio.to_thread(manager.wait_outcome, run_id, WAIT_S)
    return _result(run_id, outcome)


async def _launch(call: Call) -> dict[str, Any]:
    await call.daemon.approvals.authorize(call, "")
    profile = call.params.get("profile")
    pid = await asyncio.to_thread(
        call.daemon.run_manager.launch_app, None if profile is None else str(profile)
    )
    return {"pid": pid}


METHODS: Final = {
    "control.click": MethodSpec(_control, _window_arg, self_authorized=True),
    "control.key": MethodSpec(_control, _window_arg, self_authorized=True),
    "control.type": MethodSpec(_control, _window_arg, self_authorized=True),
    "app.launch": MethodSpec(_launch, self_authorized=True),
}
