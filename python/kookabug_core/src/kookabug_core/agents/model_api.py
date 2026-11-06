"""판단용 모델 API 호출 (M5 계획 D9·3.11, 사용자 결정 U8): HTTP로 모델을 직접 부른다.

- `anthropic`: Messages API (`<endpoint>/v1/messages`, 기본 `https://api.anthropic.com`)
- `openai_compatible`: Chat Completions (`<endpoint>/chat/completions`, 기본
  `https://api.openai.com/v1` — 호환 서버는 `/v1`까지 준다)

요청 본문에는 도구 정의가 없다(글자 + 이미지 하나). `endpoint`는 `https`만, `http`는 이 PC
(`127.0.0.1`·`localhost`·`::1`)만 받는다 — API 키를 평문으로 밖에 보내지 않는다. redirect는 따르지
않는다(3xx = `api_http_error` — 다른 곳으로 인증 헤더를 보내지 않음). 오류 메시지·응답 발췌에서 키는
`***`로 바꾼다(정상 답의 키는 `judge`가 같은 경계에서 바꾼다).
"""

from __future__ import annotations

import base64
import http.client
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, Final, Literal, cast

__all__ = [
    "DEFAULT_ENDPOINTS",
    "PROVIDERS",
    "ApiFailure",
    "Provider",
    "ask",
    "request_for",
    "scrub",
]

type Provider = Literal["anthropic", "openai_compatible"]
PROVIDERS: Final[tuple[Provider, ...]] = ("anthropic", "openai_compatible")
DEFAULT_ENDPOINTS: Final[Mapping[str, str]] = {
    "anthropic": "https://api.anthropic.com",
    "openai_compatible": "https://api.openai.com/v1",
}
ANTHROPIC_VERSION: Final = "2023-06-01"
MAX_TOKENS: Final = 1024
_LOOPBACK: Final = frozenset({"127.0.0.1", "localhost", "::1"})
_POLL_S: Final = 0.05
_BODY_LIMIT: Final = 4 * 1024 * 1024
_EXCERPT: Final = 300
_TIMEOUT_TEXT: Final = "모델 API가 제한 시간 안에 답하지 않았다"


class ApiFailure(Exception):
    """모델 API 고장. `code`는 노드 `error` 코드(`api_http_error`·`api_endpoint_invalid`·
    `agent_protocol_error`·`agent_timeout`)다. 메시지에는 키가 없다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def scrub(text: str, secret: str) -> str:
    """`text`에서 비밀값을 `***`로 바꾼다 (길이와 상관없이 — 짧은 키도 원문을 남기지 않는다)."""
    return text.replace(secret, "***") if secret else text


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """자동 redirect를 따르지 않는다: 3xx는 `HTTPError`(→ `api_http_error`). 처음 검사한
    endpoint 밖으로 인증 헤더가 가지 않게 한다."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _base(provider: str, endpoint: str | None) -> str:
    url = (endpoint or DEFAULT_ENDPOINTS[provider]).rstrip("/")
    parts = urllib.parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.username is not None or parts.password is not None:
        raise ApiFailure("api_endpoint_invalid", "endpoint에 사용자 정보를 넣지 않는다")
    if parts.scheme == "https" and host:
        return url
    if parts.scheme == "http" and host in _LOOPBACK:
        return url
    raise ApiFailure(
        "api_endpoint_invalid",
        f"endpoint는 https 주소여야 한다 (http는 이 PC만): {parts.scheme}://{host}",
    )


def request_for(
    provider: str,
    endpoint: str | None,
    model: str,
    api_key: str,
    text: str,
    png: bytes | None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """(URL, 머리, 본문). 본문에 도구 정의는 넣지 않는다."""
    if provider not in PROVIDERS:
        raise ApiFailure("api_endpoint_invalid", f"모르는 공급자: {provider}")
    base = _base(provider, endpoint)
    data = base64.b64encode(png).decode("ascii") if png is not None else None
    if provider == "anthropic":
        content: list[dict[str, Any]] = []
        if data is not None:
            content.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": data},
                }
            )
        content.append({"type": "text", "text": text})
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": content}],
        }
        headers = {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
        }
        return f"{base}/v1/messages", headers, body
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if data is not None:
        parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}})
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": parts}],
    }
    headers = {"content-type": "application/json", "authorization": f"Bearer {api_key}"}
    return f"{base}/chat/completions", headers, body


def ask(
    provider: str,
    endpoint: str | None,
    model: str,
    api_key: str,
    text: str,
    png: bytes | None,
    *,
    deadline: float,
    check: Callable[[], None],
) -> str:
    """모델에 한 번 묻고 답 글자를 돌려준다. `deadline`은 `time.monotonic()` 기준 끝 시각,
    `check()`는 취소 확인이다(취소면 예외 — 요청 스레드는 소켓 기한에 끝난다)."""
    url, headers, body = request_for(provider, endpoint, model, api_key, text, png)
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    # 이 PC 서버는 프록시를 거치지 않는다 (환경의 HTTP_PROXY가 가로채지 않게)
    handlers: list[urllib.request.BaseHandler] = [_NoRedirect()]
    if host in _LOOPBACK:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    outcome: dict[str, Any] = {}

    def call() -> None:
        # 이 스레드에서는 어떤 예외도 밖(기본 처리기 → stderr traceback)으로 내보내지 않는다.
        # 호출자에게는 키를 가린 (코드, 메시지)만 넘긴다 — 원 예외 객체·traceback은 넘기지 않는다
        try:
            try:
                timeout = max(0.1, deadline - time.monotonic())
                with opener.open(request, timeout=timeout) as response:
                    outcome["body"] = response.read(_BODY_LIMIT + 1)
            except urllib.error.HTTPError as exc:
                try:
                    excerpt = exc.read(64 * 1024).decode("utf-8", errors="replace")
                except Exception:
                    excerpt = ""
                outcome["error"] = (
                    "api_http_error",
                    f"모델 API가 HTTP {exc.code}로 답했다: {_cut(scrub(excerpt, api_key))}",
                )
            except (urllib.error.URLError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                if isinstance(exc, TimeoutError) or isinstance(
                    reason, TimeoutError | socket.timeout
                ):
                    outcome["error"] = ("agent_timeout", _TIMEOUT_TEXT)
                else:
                    outcome["error"] = (
                        "api_http_error",
                        f"모델 API에 연결하지 못했다: {_cut(scrub(str(reason), api_key))}",
                    )
            except http.client.HTTPException as exc:
                # 잘못된 상태 줄 등 HTTP 형식 오류 (메시지에 응답 원문이 들어 있다)
                outcome["error"] = (
                    "api_http_error",
                    f"모델 API 응답이 HTTP 형식이 아니다: {type(exc).__name__}: "
                    f"{_cut(scrub(str(exc), api_key))}",
                )
        except BaseException as exc:
            outcome["error"] = (
                "agent_protocol_error",
                f"모델 API 호출이 실패했다: {type(exc).__name__}: {_cut(scrub(str(exc), api_key))}",
            )

    worker = threading.Thread(target=call, name="judge-api", daemon=True)
    worker.start()
    while worker.is_alive():
        check()
        left = deadline - time.monotonic()
        if left <= 0:
            raise ApiFailure("agent_timeout", _TIMEOUT_TEXT)
        worker.join(min(_POLL_S, left))
    if "error" in outcome:
        code, message = cast(tuple[str, str], outcome["error"])
        raise ApiFailure(code, message)
    raw = cast(bytes, outcome.get("body", b""))
    if len(raw) > _BODY_LIMIT:
        raise ApiFailure("agent_protocol_error", "모델 API 응답이 너무 크다")
    try:
        data = json.loads(raw)
    except ValueError:
        raise ApiFailure("agent_protocol_error", "모델 API 응답이 JSON이 아니다") from None
    found = _text_of(provider, data)
    if found is None:
        raise ApiFailure("agent_protocol_error", "모델 API 응답에서 답 글자를 찾지 못했다")
    return found


def _text_of(provider: str, data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    body = cast(dict[str, Any], data)
    if provider == "anthropic":
        blocks = body.get("content")
        if not isinstance(blocks, list):
            return None
        texts = [
            cast(dict[str, Any], b)["text"]
            for b in cast(list[Any], blocks)
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)  # pyright: ignore[reportUnknownMemberType]
        ]
        return "".join(texts) if texts else None
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = cast(list[Any], choices)[0]
    message = first.get("message") if isinstance(first, dict) else None  # pyright: ignore[reportUnknownMemberType]
    content = message.get("content") if isinstance(message, dict) else None  # pyright: ignore[reportUnknownMemberType]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            cast(dict[str, Any], p)["text"]
            for p in cast(list[Any], content)
            if isinstance(p, dict) and isinstance(p.get("text"), str)  # pyright: ignore[reportUnknownMemberType]
        ]
        return "".join(texts) if texts else None
    return None


def _cut(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _EXCERPT else text[:_EXCERPT] + "…"
