"""가짜 ACP 에이전트 (M5 계획 3.13): 표준 라이브러리만 쓰는 단독 스크립트.

    python fake_acp_agent.py      # 환경 변수 KB_FAKE_ACP_SCRIPT = 각본 JSON 경로
                                  #           KB_FAKE_ACP_LOG    = 기록 JSONL 경로

각본(모두 선택):

- `image`(기본 true): `promptCapabilities.image`
- `die_at`: 그 요청(`initialize`·`session/new`·`session/prompt`)을 받으면 답하지 않고 끝남
  (`exit_code`, 기본 3)
- `stop_reason`(기본 `end_turn`)
- `stall_after`: 그 요청(예: `session/new`)에 답한 뒤 입력을 더 읽지 않음 (막힌 stdin 검사)
- `steps`: `session/prompt`를 받으면 차례로
  - `{"do": "say_env", "var"}`: 답 JSON의 `reason`에 환경 변수 값을 그대로 (인증값 반사 검사)
  - `{"do": "error_env", "var"}`: `session/prompt`를 그 값이 든 JSON-RPC 오류로 답하고 끝
  - `{"do": "spawn_child", "pidfile"}`: 잠자는 자식 프로세스를 띄워 PID를 파일에 (트리 종료 검사)
  - `{"do": "say", "text"}`: `agent_message_chunk`
  - `{"do": "tool", "title"}`: `tool_call` 알림 (다음 say는 새 메시지)
  - `{"do": "permission", "options"?}`: `session/request_permission` → 받은 답을 기록
  - `{"do": "client", "method", "params"}`: 그 밖의 클라이언트 요청(`fs/*` 등) → 받은 답을 기록
  - `{"do": "answer", "answer", "reason", "prefix"?}`: 답 JSON 한 줄을 say
  - `{"do": "sleep", "ms"}`: 느리게 (`session/cancel`이 오면 멈춤)
  - `{"do": "exit", "code"}`: 죽기
  - `{"do": "mcp_call", "tool", "arguments"}`: `session/new`로 받은 첫 MCP 서버를 띄워 한 번 호출
    (B5 패널 검사용 — B4에서는 쓰지 않는다)

기록 파일(JSONL)의 줄: `start`(`pid`·`cwd`·`cwd_entries`·`env` — env는 `KOOKABUG_*`만),
`request`(`method`·`params`, 이미지 data는 길이만), `response`(에이전트 → 클라이언트 요청의 답:
`method`·`result`|`error`), `cancel`, `exit`, `mcp`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

_lock = threading.Lock()
_pending: dict[int, dict[str, Any]] = {}
_cancelled = threading.Event()
_next_id = [1000]


def _log(entry: dict[str, Any]) -> None:
    path = os.environ.get("KB_FAKE_ACP_LOG")
    if not path:
        return
    with _lock, open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _send(message: dict[str, Any]) -> None:
    data = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False)
    with _lock:
        sys.stdout.write(data + "\n")
        sys.stdout.flush()


def _shown(params: Any) -> Any:
    """기록용: 이미지 data는 길이만."""
    if isinstance(params, dict):
        out: dict[str, Any] = {}
        for key, value in params.items():
            if key == "data" and isinstance(value, str) and len(value) > 64:
                out["data_len"] = len(value)
            else:
                out[key] = _shown(value)
        return out
    if isinstance(params, list):
        return [_shown(v) for v in params]
    return params


def _ask_client(method: str, params: dict[str, Any]) -> dict[str, Any]:
    rid = _next_id[0]
    _next_id[0] += 1
    waiter: dict[str, Any] = {"event": threading.Event()}
    _pending[rid] = waiter
    _send({"id": rid, "method": method, "params": params})
    waiter["event"].wait(30)
    reply = waiter.get("reply", {"error": "no reply"})
    _log({"event": "response", "method": method, **{k: v for k, v in reply.items() if k != "id"}})
    return reply


def _update(session: str, update: dict[str, Any]) -> None:
    _send({"method": "session/update", "params": {"sessionId": session, "update": update}})


def _say(session: str, text: str) -> None:
    _update(
        session,
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
    )


def _mcp_call(server: dict[str, Any], tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """session/new로 받은 MCP 서버(stdio)를 띄워 initialize → tools/call 한 번."""
    env = dict(os.environ)
    for item in server.get("env", []):
        env[item["name"]] = item["value"]
    proc = subprocess.Popen(
        [server["command"], *server.get("args", [])],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None

    def rpc(rid: int | None, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if rid is not None:
            body["id"] = rid
        assert proc.stdin is not None and proc.stdout is not None
        proc.stdin.write((json.dumps(body) + "\n").encode("utf-8"))
        proc.stdin.flush()
        if rid is None:
            return None
        while True:
            line = proc.stdout.readline()
            if not line:
                return {"error": "eof"}
            msg = json.loads(line)
            if msg.get("id") == rid:
                return msg

    try:
        rpc(
            1,
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "fake-acp", "version": "0"},
            },
        )
        rpc(None, "notifications/initialized", {})
        return rpc(2, "tools/call", {"name": tool, "arguments": arguments}) or {}
    finally:
        proc.stdin.close()
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _prompt(script: dict[str, Any], session: str, servers: list[dict[str, Any]]) -> dict[str, Any]:
    for step in script.get("steps", []):
        if _cancelled.is_set():
            return {"stopReason": "cancelled"}
        do = step.get("do")
        if do == "say":
            _say(session, step["text"])
        elif do == "say_env":
            body = {"answer": step.get("answer", "loading"), "reason": os.environ[step["var"]]}
            _say(session, json.dumps(body, ensure_ascii=False))
        elif do == "error_env":
            return {
                "__error__": {"code": -32000, "message": "bad token: " + os.environ[step["var"]]}
            }
        elif do == "spawn_child":
            child = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(120)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            Path(step["pidfile"]).write_text(str(child.pid), encoding="utf-8")
        elif do == "answer":
            body = {"answer": step.get("answer"), "reason": step.get("reason", "")}
            _say(session, step.get("prefix", "") + json.dumps(body, ensure_ascii=False))
        elif do == "tool":
            _update(
                session,
                {
                    "sessionUpdate": "tool_call",
                    "toolCallId": f"t{time.monotonic_ns()}",
                    "title": step.get("title", "도구"),
                    "kind": "other",
                    "status": "completed",
                },
            )
        elif do == "permission":
            _ask_client(
                "session/request_permission",
                {
                    "sessionId": session,
                    "toolCall": {"toolCallId": "p1", "title": step.get("title", "파일 편집")},
                    "options": step.get(
                        "options",
                        [
                            {"optionId": "allow", "name": "허용", "kind": "allow_once"},
                            {"optionId": "allow-all", "name": "항상 허용", "kind": "allow_always"},
                            {"optionId": "reject", "name": "거부", "kind": "reject_once"},
                        ],
                    ),
                },
            )
        elif do == "client":
            _ask_client(step["method"], step.get("params", {}))
        elif do == "sleep":
            end = time.monotonic() + step["ms"] / 1000
            while time.monotonic() < end and not _cancelled.is_set():
                time.sleep(0.02)
        elif do == "exit":
            _log({"event": "exit", "code": step.get("code", 1)})
            os._exit(step.get("code", 1))
        elif do == "mcp_call":
            if not servers:
                _say(session, "no mcp server")
                continue
            reply = _mcp_call(servers[0], step["tool"], step.get("arguments", {}))
            _log({"event": "mcp", "tool": step["tool"], "reply": reply})
    return {"stopReason": script.get("stop_reason", "end_turn")}


def main() -> None:
    # ACP는 UTF-8 JSON 줄이다 (콘솔 코드 페이지와 무관하게)
    sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    script_path = os.environ.get("KB_FAKE_ACP_SCRIPT")
    script: dict[str, Any] = (
        json.loads(Path(script_path).read_text(encoding="utf-8")) if script_path else {}
    )
    cwd = os.getcwd()
    _log(
        {
            "event": "start",
            "pid": os.getpid(),
            "cwd": cwd,
            "cwd_entries": sorted(os.listdir(cwd)),
            "env": {k: v for k, v in os.environ.items() if k.upper().startswith("KOOKABUG_")},
        }
    )
    servers: list[dict[str, Any]] = []
    workers: list[threading.Thread] = []
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        msg = json.loads(line)
        method = msg.get("method")
        if method is None:  # 클라이언트의 답
            waiter = _pending.pop(msg.get("id"), None)
            if waiter is not None:
                waiter["reply"] = msg
                waiter["event"].set()
            continue
        _log({"event": "request", "method": method, "params": _shown(msg.get("params"))})
        if method == script.get("die_at"):
            os._exit(script.get("exit_code", 3))
        rid = msg.get("id")
        params = msg.get("params") or {}
        if method == "initialize":
            _send(
                {
                    "id": rid,
                    "result": {
                        "protocolVersion": 1,
                        "agentCapabilities": {
                            "loadSession": False,
                            "promptCapabilities": {"image": script.get("image", True)},
                        },
                        "authMethods": [],
                    },
                }
            )
        elif method == "session/new":
            servers = list(params.get("mcpServers", []))
            _send({"id": rid, "result": {"sessionId": "s1"}})
        elif method == "session/prompt":

            def run(
                rid: Any = rid,
                session: str = params.get("sessionId", "s1"),
                mcp: list[dict[str, Any]] = servers,
            ) -> None:
                result = _prompt(script, session, mcp)
                if "__error__" in result:
                    _send({"id": rid, "error": result["__error__"]})
                else:
                    _send({"id": rid, "result": result})

            worker = threading.Thread(target=run, daemon=True)
            workers.append(worker)
            worker.start()
        elif method == "session/cancel":
            _log({"event": "cancel"})
            _cancelled.set()
        elif rid is not None:
            _send({"id": rid, "error": {"code": -32601, "message": f"unknown {method}"}})
        if method is not None and method == script.get("stall_after"):
            _log({"event": "stall"})
            time.sleep(120)  # 입력을 더 읽지 않는다 (보내는 쪽 쓰기가 막힌다)


if __name__ == "__main__":
    main()
