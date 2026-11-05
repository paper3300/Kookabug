"""`secrets.list`·`secrets.create` (M4 계획 2.8, T7). 둘 다 `ui_only` + `AGENT_DENIED`.

- `secrets.list`: 자격 증명 관리자에서 이 워크스페이스(`kookabug.json` `id`)의 키만 (값 없음).
  환경 변수 비밀값은 원래 키 이름을 되살릴 수 없어 목록에 없고 `env_note`로 안내한다
- `secrets.create {key, from_step}`: 녹화 세션 메모리의 원문(비밀값·확인 필요 구간)을 자격 증명
  관리자 `kookabug:<ID>:<키>`에 쓰고 그 스텝의 키로 고른다. **값을 RPC로 받지 않는다.** 워크스페이스
  ID가 없으면 처음 만들 때 `kookabug.json`에 넣는다(Q10). 키가 이미 있으면 `exists`

녹화 세션(T8)은 `Daemon.recorder_secrets`에 `RecorderSecretSource`를 둔다. 없으면
`recorder_state_invalid`.
"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from typing import Any, Final, Protocol

from kookabug_core.recorder.fields import SecretText
from kookabug_core.recorder.secrets import SECRET_KEY, RecorderTexts, TextNotAvailable
from kookabug_core.win.credentials import CredentialError, CredentialStore
from kookabug_core.workspace import (
    Workspace,
    WorkspaceError,
    ensure_workspace_id,
    workspace_id,
)
from kookabug_daemon.methods import Call, MethodSpec
from kookabug_daemon.protocol import RequestFailed

__all__ = ["ENV_NOTE", "METHODS", "RecorderSecretSource", "TextsSecretSource"]

ENV_NOTE: Final = (
    "환경 변수 KOOKABUG_SECRET_<키>로 준 비밀값은 목록에 없어요. 실행에서는 환경 변수가 먼저 쓰여요"
)


class RecorderSecretSource(Protocol):
    """녹화 세션 메모리의 원문 (T8 세션이 구현). 소유 연결이 아니면 `not_owner`."""

    def text_for_secret(self, connection: int, step: str) -> SecretText:
        """`from_step`의 원문 (비밀값·확인 필요 구간만). 아니면 `RequestFailed`."""
        ...

    def secret_created(self, connection: int, step: str, key: str) -> None:
        """새 비밀값을 만들었다: 그 스텝을 비밀값으로 두고 키를 고른다."""
        ...


@dataclass
class TextsSecretSource:
    """`RecorderTexts` 위의 단순 구현 (스텝 ID → 구간 ID 표). T8 세션이 감싸 쓴다."""

    texts: RecorderTexts
    owner: int
    steps: dict[str, int]
    session_state: str = "stopped"
    """오류 data `state` (RecorderState)."""

    def _span(self, connection: int, step: str) -> int:
        if connection != self.owner:
            raise RequestFailed("not_owner", "다른 연결의 녹화다", state=self.session_state)
        span = self.steps.get(step)
        if span is None:
            raise RequestFailed("not_found", f"스텝 {step}이(가) 없다", path=step)
        return span

    def text_for_secret(self, connection: int, step: str) -> SecretText:
        span = self._span(connection, step)
        try:
            return self.texts.raw_for_secret(span)
        except TextNotAvailable as exc:
            raise RequestFailed(
                "recorder_state_invalid", str(exc), state=self.session_state
            ) from exc

    def secret_created(self, connection: int, step: str, key: str) -> None:
        span = self._span(connection, step)
        self.texts.mark_secret(span)
        self.texts.set_secret_key(span, key)


def _require_windows() -> None:
    if sys.platform != "win32":
        text = "자격 증명 관리자는 Windows에서만 쓸 수 있다"
        raise RequestFailed("platform_unavailable", text, message=text)


def _list_keys(call: Call) -> dict[str, Any]:
    try:
        ws = Workspace.open(call.daemon.root)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    wid = workspace_id(ws)
    if wid is None:
        return {"keys": [], "env_note": ENV_NOTE}
    try:
        names = CredentialStore().keys(wid)
    except CredentialError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    keys = [{"key": k, "source": "credential"} for k in names if SECRET_KEY.fullmatch(k)]
    return {"keys": keys, "env_note": ENV_NOTE}


async def _list(call: Call) -> dict[str, Any]:
    _require_windows()
    return await asyncio.to_thread(_list_keys, call)


def _create_key(call: Call, source: RecorderSecretSource) -> dict[str, Any]:
    key = str(call.params["key"])
    step = str(call.params["from_step"])
    if not SECRET_KEY.fullmatch(key):  # 스키마 pattern이 먼저 막는다
        raise RequestFailed("not_found", "비밀값 키 형식이 틀렸다", path=key)
    raw = source.text_for_secret(call.connection, step)
    try:
        wid = ensure_workspace_id(call.daemon.root)
    except WorkspaceError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    store = CredentialStore()
    try:
        if store.read(wid, key) is not None:
            raise RequestFailed("exists", f"비밀값 '{key}'이(가) 이미 있다", revision=None)
        store.write(wid, key, raw.reveal())
    except CredentialError as exc:
        raise RequestFailed("io_error", str(exc), message=str(exc)) from exc
    source.secret_created(call.connection, step, key)
    return {"key": key, "source": "credential"}


async def _create(call: Call) -> dict[str, Any]:
    _require_windows()
    source: RecorderSecretSource | None = getattr(call.daemon, "recorder_secrets", None)
    if source is None:
        raise RequestFailed("recorder_state_invalid", "녹화 세션이 없다", state="idle")
    return await asyncio.to_thread(_create_key, call, source)


METHODS: Final[dict[str, MethodSpec]] = {
    "secrets.list": MethodSpec(_list),
    "secrets.create": MethodSpec(_create),
}
