"""판단 노드 공용 흐름 (M5 계획 3.11, 사용자 결정 U8·U9·U11).

`core.agent.cli_judge`·`core.agent.api_judge`는 실행 ctx의 `judge(...)`(runner 안 core 노드만,
`StepContext.judge`)를 부르고, 그것이 여기 `run_judge`다.

- 보내는 것: 이미지(긴 변 1568px·1 MiB 이하 PNG) + 질문 + 고정 지시(선택지 중 하나를 JSON
  `{"answer": ..., "reason": ...}`로)
- 답 읽기: 받은 마지막 메시지에서 첫 JSON 객체. `answer`가 선택지와 정확히 같으면 그 출구, 아니면
  `unsure`(`reason`에 받은 글자 앞부분)
- 고장(출구 아님, `EngineError`): `agent_not_configured`·`agent_start_failed`·
  `agent_protocol_error`·`agent_timeout`·`api_http_error`(상태 코드)·`api_endpoint_invalid`
- 에이전트(cli)는 사용자 설정 `agents` 목록에서 고르고(`agent` 빈 값이면 `default_agent`, 없으면
  첫 항목), 실행마다 따로 띄운다. 환경에서 `KOOKABUG_*`를 모두 빼고(세션·토큰·비밀값 환경 변수)
  `KOOKABUG_AGENT=judge:<실행>:<스텝>`만 넣는다. 작업 폴더는 워크스페이스 밖 빈 임시 폴더이고
  끝나면 지운다(워크스페이스 위로 올라가며 `AGENTS.md`·파일을 읽지 않게)
- 기록: `steps/<스텝>_judge.json`(`Recorder.text` — 비밀값 가림 정책 그대로) + 보낸 이미지는
  스크린샷 정책으로. API 키는 기록·오류 메시지에 넣지 않는다
- 인증값(API 키, 에이전트 env의 `$secret` 값)이 답·오류에 섞여 오면 `Scrubber` 한 곳에서 `***`로
  바꾼 뒤 내보내고, 바꾼 필드를 에이전트용 비밀 분류(`secret_paths`)에 표시한다. env에 `$secret`을
  준 cli 스텝은 `secret`(에이전트에게 증거를 주지 않음)
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final, cast

from kookabug_core.agents import acp, model_api
from kookabug_core.canonical import loads_strict
from kookabug_core.engine.errors import EngineError
from kookabug_core.permissions import USER_SETTINGS_FILE, user_config_dir
from kookabug_core.schema.shape import check_shape
from kookabug_core.workspace import SecretProvider, default_secrets
from kookabug_sdk import Secret
from kookabug_sdk.types import Image

if TYPE_CHECKING:
    from kookabug_core.engine.context import Runtime

__all__ = [
    "JUDGE_RECORD",
    "MAX_CHOICES",
    "AgentSpec",
    "JudgeEnv",
    "Scrubber",
    "SecretRef",
    "build_instruction",
    "load_agents",
    "parse_answer",
    "run_judge",
]

JUDGE_RECORD: Final = "judge.json"
"""기록 이름 (`steps/<스텝>_judge.json`)."""
RECORD_FORMAT: Final = "kookabug.judge/0"
MAX_CHOICES: Final = 16
UNSURE: Final = "unsure"
IMAGE_SIDE: Final = 1568
IMAGE_BYTES: Final = 1024 * 1024
_REASON_EXCERPT: Final = 500
_TEXT_KEPT: Final = 64 * 1024
_ENV_PREFIX: Final = "KOOKABUG_"
AGENT_ENV: Final = "KOOKABUG_AGENT"
_ANSWER_FIELDS: Final = ("/outputs/answer", "/outputs/reason", "/message")
"""답에서 인증값을 가렸을 때 에이전트용 비밀 분류에 표시하는 `step.end` 필드."""


@dataclass(frozen=True, slots=True)
class JudgeEnv:
    """판단 노드가 쓰는 바깥: 사용자 설정 폴더, 비밀값 제공자(없으면 워크스페이스 기본), 임시 폴더
    위치(없으면 시스템 임시 폴더), 에이전트 환경의 바탕(없으면 이 프로세스 환경)."""

    user_dir: Path | None
    secrets: SecretProvider | None = None
    temp_root: Path | None = None
    environ: Mapping[str, str] | None = None

    @classmethod
    def from_environ(cls) -> JudgeEnv:
        return cls(user_config_dir())


@dataclass(frozen=True, slots=True)
class SecretRef:
    """설정의 `{"$secret": 키}` (값은 띄울 때 비밀값 제공자에서 찾는다)."""

    key: str


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """사용자 설정의 에이전트 하나 (`user-settings` `#/$defs/Agent`)."""

    id: str
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str | SecretRef] = field(default_factory=dict[str, str | SecretRef])


def load_agents(user_dir: Path | None) -> tuple[list[AgentSpec], str | None]:
    """사용자 설정의 `(agents, default_agent)`. 파일이 없거나 틀리면 `agent_not_configured`."""
    if user_dir is None:
        raise EngineError("agent_not_configured", "사용자 설정 폴더를 정할 수 없다")
    path = user_dir / USER_SETTINGS_FILE
    try:
        data = loads_strict(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        raise EngineError(
            "agent_not_configured", "사용자 설정에 에이전트가 없다 (settings.json 없음)"
        ) from None
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise EngineError("agent_not_configured", f"사용자 설정을 읽을 수 없다: {exc}") from exc
    if not isinstance(data, dict):
        raise EngineError("agent_not_configured", "사용자 설정이 JSON 객체가 아니다")
    body = cast(dict[str, Any], data)
    raw = body.get("agents", [])
    default = body.get("default_agent")
    if not isinstance(raw, list) or not (default is None or isinstance(default, str)):
        raise EngineError("agent_not_configured", "사용자 설정의 agents 형식이 틀렸다")
    agents: list[AgentSpec] = []
    for i, item in enumerate(cast(list[Any], raw)):
        if check_shape(item, "user-settings", ref="#/$defs/Agent"):
            raise EngineError("agent_not_configured", f"사용자 설정 agents[{i}] 형식이 틀렸다")
        entry = cast(dict[str, Any], item)
        env: dict[str, str | SecretRef] = {}
        for key, value in cast(dict[str, Any], entry.get("env", {})).items():
            env[key] = SecretRef(value["$secret"]) if isinstance(value, dict) else str(value)
        agents.append(
            AgentSpec(
                id=entry["id"],
                name=entry["name"],
                command=entry["command"],
                args=tuple(entry.get("args", ())),
                env=env,
            )
        )
    return agents, cast(str | None, default)


def pick_agent(agents: Sequence[AgentSpec], wanted: str | None, default: str | None) -> AgentSpec:
    target = wanted if wanted is not None else default
    if target is None:
        if agents:
            return agents[0]
        raise EngineError("agent_not_configured", "사용자 설정에 에이전트가 없다")
    for agent in agents:
        if agent.id == target:
            return agent
    raise EngineError(
        "agent_not_configured", f"사용자 설정에 에이전트 '{target}'이(가) 없다 (U11: PC마다 설정)"
    )


def build_instruction(prompt: str, choices: Sequence[str]) -> str:
    """질문 + 고정 지시. 지시는 모델이 가장 잘 따르는 영어로 쓴다."""
    listed = json.dumps(list(choices), ensure_ascii=False)
    return (
        f"{prompt}\n\n"
        f"Choose exactly one of these choices: {listed}\n"
        'Reply with only one JSON object: {"answer": "<one choice, copied exactly>", '
        '"reason": "<short reason>"}\n'
        f'If you cannot decide, use "{UNSURE}" as the answer.'
    )


def first_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text, start)
        except ValueError:
            value = None
        if isinstance(value, dict):
            return cast(dict[str, Any], value)
        start = text.find("{", start + 1)
    return None


def parse_answer(text: str, choices: Sequence[str]) -> tuple[str, str, str]:
    """(출구, answer, reason). 선택지와 정확히 같지 않거나 읽을 수 없으면 `unsure`."""
    found = first_json_object(text)
    answer = found.get("answer") if found is not None else None
    reason = found.get("reason") if found is not None else None
    if isinstance(answer, str) and answer in choices:
        return answer, answer, reason if isinstance(reason, str) else ""
    excerpt = text if len(text) <= _REASON_EXCERPT else text[:_REASON_EXCERPT] + "…"
    return UNSURE, answer if isinstance(answer, str) else "", excerpt


def check_choices(choices: Any) -> list[str]:
    if not isinstance(choices, list | tuple) or not choices:
        raise EngineError("config_invalid", "choices는 글자 1~16개 목록이다")
    items = list(cast(Sequence[Any], choices))
    if len(items) > MAX_CHOICES or not all(isinstance(c, str) and c for c in items):
        raise EngineError("config_invalid", f"choices는 글자 1~{MAX_CHOICES}개 목록이다")
    return cast(list[str], items)


class Scrubber:
    """판단 호출 하나에 쓴 인증 비밀값(API 키, 에이전트 env의 `$secret` 값)을 메모리에만 들고,
    답·오류 글자를 반환·기록·이벤트로 내기 전에 `***`로 바꾸는 한 곳. 길이와 상관없이 바꾼다.
    디스크에 쓰지 않는다. `hit`은 바꾼 일이 있었다(그 필드를 에이전트용 비밀 분류에 표시한다)."""

    def __init__(self) -> None:
        self._values: list[str] = []
        self.hit = False

    def add(self, value: str) -> None:
        """원문과 JSON 문자열 안의 이스케이프 형태(`ensure_ascii` 양쪽)를 같이 든다 — 답 JSON에 실려
        온 인증값은 따옴표·역슬래시가 이스케이프되어 원문과 글자가 다르다."""
        if not value:
            return
        forms = (
            value,
            json.dumps(value)[1:-1],
            json.dumps(value, ensure_ascii=False)[1:-1],
        )
        for form in forms:
            if form and form not in self._values:
                self._values.append(form)
        self._values.sort(key=len, reverse=True)  # 긴 값부터 (겹치는 값의 일부가 남지 않게)

    @property
    def active(self) -> bool:
        return bool(self._values)

    def __call__(self, text: str) -> str:
        for value in self._values:
            if value in text:
                text = text.replace(value, "***")
                self.hit = True
        return text


def agent_environ(
    base: Mapping[str, str],
    spec: AgentSpec,
    secrets: SecretProvider,
    marker: str,
    used: Scrubber | None = None,
) -> dict[str, str]:
    """에이전트 환경: 바탕에서 `KOOKABUG_*`를 모두 빼고 설정 `env`(비밀값은 찾아서)를 더한 뒤
    `KOOKABUG_AGENT`만 넣는다. 찾은 비밀값은 `used`에 넣는다(답·오류에서 가림)."""
    env = {k: v for k, v in base.items() if not k.upper().startswith(_ENV_PREFIX)}
    for key, value in spec.env.items():
        if key.upper().startswith(_ENV_PREFIX):
            continue
        if isinstance(value, SecretRef):
            found = secrets.get(value.key)
            if found is None:
                raise EngineError(
                    "agent_not_configured",
                    f"에이전트 '{spec.id}' env {key}의 비밀값 키를 찾지 못했다",
                )
            env[key] = found
            if used is not None:
                used.add(found)
        else:
            env[key] = value
    env[AGENT_ENV] = marker
    return env


# ---------------------------------------------------------------- 실행


def image_png(runtime: Runtime, image: Image) -> tuple[bytes, int, int]:
    """노드 입력 이미지 → 보낼 PNG(긴 변 1568·1 MiB 이하)와 크기."""
    if image.data is not None:
        data = image.data
    elif image.path is not None:
        data = image.path.read_bytes()
    elif image.capture_id is not None and runtime.recorder.frames is not None:
        data = runtime.recorder.frames.encode_png(image.capture_id)
    else:
        raise EngineError("frame_expired", "이미지 픽셀이 없다")
    from kookabug_platform.frames import fit_png

    try:
        return fit_png(data, IMAGE_SIDE, IMAGE_BYTES)
    except ValueError as exc:
        raise EngineError("input_invalid", f"이미지를 읽을 수 없다: {exc}") from exc


def run_judge(
    runtime: Runtime,
    step: str,
    *,
    env: JudgeEnv | None,
    kind: str,
    prompt: str,
    image: Image | None,
    choices: Any,
    timeout_ms: int,
    agent: str | None = None,
    provider: str | None = None,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: Secret | None = None,
) -> dict[str, Any]:
    """판단 한 번. `{"exit", "answer", "reason"}`을 돌려주고, 고장은 `EngineError`."""
    if kind not in ("cli", "api"):
        raise EngineError("config_invalid", f"모르는 판단 종류: {kind}")
    if not isinstance(prompt, str):
        raise EngineError("type_mismatch", "prompt는 글자다")
    names = check_choices(choices)
    if timeout_ms <= 0:
        raise EngineError("input_invalid", "timeout_ms는 1 이상이다")
    env = env or JudgeEnv.from_environ()
    runtime.check()
    record: dict[str, Any] = {
        "format": RECORD_FORMAT,
        "kind": kind,
        "prompt": prompt,
        "choices": names,
        "timeout_ms": timeout_ms,
    }
    started = time.monotonic()
    scrub = Scrubber()
    try:
        png: bytes | None = None
        if image is not None:
            png, width, height = image_png(runtime, image)
            record["image"] = {"width": width, "height": height}
            runtime.recorder.screenshot(step, image, "judge")
        text = build_instruction(prompt, names)
        deadline = started + timeout_ms / 1000
        if kind == "cli":
            received = _ask_cli(runtime, step, env, record, agent, text, png, deadline, scrub)
        else:
            received = _ask_api(
                record, provider, endpoint, model, api_key, text, png, deadline, runtime, scrub
            )
        # 답 글자에 인증값이 섞여 오면 읽기·발췌·출력·기록 전에 가린다 (한 경계)
        result = _finalize(received, names, scrub, record)
        if scrub.hit:
            runtime.recorder.mark_secret_fields(step, _ANSWER_FIELDS)
        return result
    except (acp.AgentFailure, model_api.ApiFailure, EngineError) as exc:
        message = scrub(exc.message)
        if scrub.hit:
            runtime.recorder.mark_secret_fields(step, ["/error/message"])
        record["error"] = {"code": exc.code, "message": message}
        raise EngineError(exc.code, message) from None
    except BaseException:
        record["error"] = {"code": "cancelled", "message": "판단 중 실행이 끝났다"}
        raise
    finally:
        record["duration_ms"] = int((time.monotonic() - started) * 1000)
        with contextlib.suppress(Exception):
            runtime.recorder.text(step, JUDGE_RECORD, record)


def _finalize(
    received: str, names: Sequence[str], scrub: Scrubber, record: dict[str, Any]
) -> dict[str, Any]:
    """답을 반환·기록하기 직전에 한 곳에서 확정한다: 받은 글자를 가리고 → 해석하고 → 해석한 글자도
    다시 가린다(JSON 해석이 이스케이프를 풀어 인증값을 되살릴 수 있다). 해석 뒤에 걸렸으면 기록의
    원문 글자는 남기지 않는다."""
    text = scrub(received)
    exit_name, answer, reason = parse_answer(text, names)
    before = scrub.hit
    scrub.hit = False
    shown_answer, shown_reason = scrub(answer), scrub(reason)
    after = scrub.hit
    scrub.hit = before or after
    if after:
        # 해석이 되살린 인증값: 원문 글자는 가린 형태로만, 인증값이 든 답은 선택지로 보지 않는다
        text = "***"
        if shown_answer != answer:
            exit_name = UNSURE
    record["text"] = text[:_TEXT_KEPT]
    record.update(exit=exit_name, answer=shown_answer, reason=shown_reason)
    return {"exit": exit_name, "answer": shown_answer, "reason": shown_reason}


def _ask_cli(
    runtime: Runtime,
    step: str,
    env: JudgeEnv,
    record: dict[str, Any],
    wanted: str | None,
    text: str,
    png: bytes | None,
    deadline: float,
    scrub: Scrubber,
) -> str:
    agents, default = load_agents(env.user_dir)
    spec = pick_agent(agents, wanted, default)
    record["agent"] = {"id": spec.id, "name": spec.name}
    secrets = env.secrets or default_secrets(runtime.program.workspace)
    base = os.environ if env.environ is None else env.environ
    environ = agent_environ(base, spec, secrets, f"judge:{runtime.run}:{step}", scrub)
    if scrub.active:
        # env에 비밀값을 준 스텝: 에이전트에게 이 스텝 증거를 주지 않는다 (B2 `secret` 분류)
        runtime.recorder.mark_secret(step)
    blocks: list[dict[str, Any]] = []
    if png is not None:
        blocks.append(
            {
                "type": "image",
                "data": base64.b64encode(png).decode("ascii"),
                "mimeType": "image/png",
            }
        )
    blocks.append({"type": "text", "text": text})
    root = env.temp_root
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
    cwd = Path(tempfile.mkdtemp(prefix="kookabug-judge-", dir=root))
    try:
        reply = acp.ask(
            acp.AgentCommand(spec.command, spec.args, environ, cwd),
            blocks,
            deadline=deadline,
            check=runtime.check,
        )
    finally:
        shutil.rmtree(cwd, ignore_errors=True)
    record["stop_reason"] = None if reply.stop_reason is None else scrub(reply.stop_reason)
    record["permission_requests"] = reply.permission_requests
    return reply.text


def _ask_api(
    record: dict[str, Any],
    provider: str | None,
    endpoint: str | None,
    model: str | None,
    api_key: Secret | None,
    text: str,
    png: bytes | None,
    deadline: float,
    runtime: Runtime,
    scrub: Scrubber,
) -> str:
    if provider not in model_api.PROVIDERS:
        raise EngineError(
            "config_invalid", f"provider는 {', '.join(model_api.PROVIDERS)} 중 하나다"
        )
    if not isinstance(model, str) or not model:
        raise EngineError("input_invalid", "model이 비어 있다")
    if not isinstance(api_key, Secret):
        # 그래프에 키 원문을 쓰지 않게 비밀값(`$secret`)만 받는다
        raise EngineError("type_mismatch", "api_key는 비밀값($secret)이어야 한다")
    record.update(provider=provider, model=model, endpoint=endpoint)
    scrub.add(api_key.reveal())
    return model_api.ask(
        provider,
        endpoint,
        model,
        api_key.reveal(),
        text,
        png,
        deadline=deadline,
        check=runtime.check,
    )
