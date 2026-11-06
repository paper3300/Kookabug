"""가짜 모델 API 서버 (M5 계획 3.13): 127.0.0.1 HTTP, Anthropic Messages·OpenAI 호환 Chat
Completions 모양으로 답하고 받은 요청을 기록한다.

    with FakeModelApi(reply="{\"answer\": \"a\", \"reason\": \"r\"}") as api:
        api.base            # http://127.0.0.1:<port>   (anthropic endpoint)
        api.base + "/v1"    # openai_compatible endpoint
        api.requests        # [{"path", "headers", "body"}]

- `status`를 주면 그 HTTP 상태로 `error_body`를 답한다 (`{key}`는 받은 키로 바뀜 — 응답에 키가
  섞여 오는 경우 검사)
- `delay_s`만큼 늦게 답한다
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Any, Self

__all__ = ["FakeModelApi"]


class FakeModelApi:
    def __init__(
        self,
        reply: str = "",
        *,
        status: int = 200,
        error_body: str = "",
        delay_s: float = 0.0,
    ) -> None:
        self.reply = reply
        self.status = status
        self.error_body = error_body
        self.delay_s = delay_s
        self.requests: list[dict[str, Any]] = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("content-length", "0"))
                raw = self.rfile.read(length)
                headers = {k.lower(): v for k, v in self.headers.items()}
                api.requests.append(
                    {"path": self.path, "headers": headers, "body": json.loads(raw or b"{}")}
                )
                if api.delay_s:
                    time.sleep(api.delay_s)
                key = headers.get("x-api-key") or headers.get("authorization", "").removeprefix(
                    "Bearer "
                )
                if api.status != 200:
                    data = api.error_body.replace("{key}", key).encode("utf-8")
                    self._reply(api.status, data)
                    return
                if self.path.endswith("/v1/messages"):
                    body: dict[str, Any] = {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": api.reply}],
                        "stop_reason": "end_turn",
                    }
                elif self.path.endswith("/chat/completions"):
                    body = {
                        "id": "c1",
                        "object": "chat.completion",
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": api.reply},
                                "finish_reason": "stop",
                            }
                        ],
                    }
                else:
                    self._reply(404, b'{"error": "not found"}')
                    return
                self._reply(200, json.dumps(body).encode("utf-8"))

            def _reply(self, status: int, data: bytes) -> None:
                try:
                    self.send_response(status)
                    self.send_header("content-type", "application/json")
                    self.send_header("content-length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # 클라이언트가 먼저 끊었다 (시간 초과 검사)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> Self:
        self._thread.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._server.shutdown()
        self._server.server_close()
