"""판단용 ACP 클라이언트 (M5 계획 D8·3.11): 에이전트 CLI를 도구 없이 띄워 한 번 묻는다.

stdio 줄 단위 JSON-RPC 2.0. 쓰는 메서드는 `initialize` → `session/new` → `session/prompt`(+ 끝낼 때
`session/cancel`)뿐이다. 에이전트에게 주는 것이 없다:

- 클라이언트 능력 `fs` 읽기·쓰기 false, `terminal` false. `session/new`의 `mcpServers`는 빈 목록
- 에이전트가 묻는 `session/request_permission`은 모두 거절한다(거절 선택지가 있으면 그것, 없으면
  `cancelled`). 그 밖의 에이전트 → 클라이언트 요청(`fs/*`·`terminal/*` 등)은 "메서드 없음" 오류
- 보내기는 쓰기 스레드(큐)가 한다: 에이전트가 입력을 읽지 않아 쓰기가 막혀도 주 루프는 기한·취소를
  보고 Job을 끝낸다
- 에이전트 프로세스는 생성 시점부터 자기 Job 안이다(멈춘 채 띄워 넣고 이어 돌림). Job을 준비하지
  못하면 띄우지 않고 `agent_start_failed`. 끝나면(답·시간 초과·취소·오류 모두) Job을 끝내 손자
  프로세스까지 정리한다. runner가 죽으면 Job 핸들이 닫혀 같이 끝난다(`kill_on_close`)
"""

from __future__ import annotations

import contextlib
import itertools
import json
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, cast

from kookabug_core.win import CHILD_FLAGS, Job, resume_suspended

__all__ = [
    "CLIENT_CAPABILITIES",
    "PROTOCOL_VERSION",
    "AgentCommand",
    "AgentFailure",
    "AgentReply",
    "ask",
]

PROTOCOL_VERSION: Final = 1
CLIENT_CAPABILITIES: Final[Mapping[str, Any]] = {
    "fs": {"readTextFile": False, "writeTextFile": False},
    "terminal": False,
}
_POLL_S: Final = 0.05
"""취소·기한 확인 간격 (M5 계획 3.11 "50 ms마다")."""
_TEXT_LIMIT: Final = 1024 * 1024
"""받은 글자 상한 (넘는 것은 버린다)."""
_EXIT_WAIT_S: Final = 5.0
_CANCEL_GRACE_S: Final = 0.2
"""`session/cancel` 알림을 보내려고 기다리는 시간 (막힌 쓰기가 종료를 늦추지 않게)."""
_CREATE_SUSPENDED: Final = 0x00000004
_METHOD_NOT_FOUND: Final = -32601
_REJECT_KINDS: Final = ("reject_once", "reject_always")
_EOF: Final = object()


class AgentFailure(Exception):
    """판단 에이전트 고장. `code`는 노드 `error` 코드(`agent_start_failed`·`agent_protocol_error`·
    `agent_timeout`)다."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class AgentCommand:
    """띄울 명령. `env`는 그대로 쓰는 전체 환경이다(부르는 쪽이 이미 걸렀다)."""

    command: str
    args: Sequence[str]
    env: Mapping[str, str]
    cwd: Path


@dataclass(slots=True)
class AgentReply:
    text: str
    """에이전트가 마지막으로 보낸 메시지 글자 (도구 호출 뒤 새 메시지가 오면 그것부터)."""
    stop_reason: str | None = None
    permission_requests: int = 0
    """거절한 `session/request_permission` 수."""
    segments: list[str] = field(default_factory=list[str])


def ask(
    command: AgentCommand,
    prompt: Sequence[Mapping[str, Any]],
    *,
    deadline: float,
    check: Callable[[], None],
) -> AgentReply:
    """에이전트를 띄워 `prompt`(ACP 내용 블록)를 한 번 묻고 답을 받는다. `deadline`은
    `time.monotonic()` 기준 끝 시각, `check()`는 취소 확인(취소면 예외)이다. 어떻게 끝나든 에이전트
    프로세스 트리는 끝낸다."""
    session = _Session(command, deadline, check)
    try:
        return session.run(prompt)
    finally:
        session.close()


class _Session:
    def __init__(self, command: AgentCommand, deadline: float, check: Callable[[], None]) -> None:
        self._deadline = deadline
        self._check = check
        self._ids = itertools.count(1)
        self._inbox: queue.Queue[Any] = queue.Queue()
        self._reply = AgentReply("")
        self._segment_open = False
        self._size = 0
        self._session_id: str | None = None
        self._job: Job | None = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._outbox: queue.Queue[bytes | None] = queue.Queue()
        self._write_failed = False
        self._cwd = str(command.cwd)
        exe = _resolve(command.command, command.env)
        if exe is None:
            raise AgentFailure(
                "agent_start_failed", f"에이전트 명령 '{command.command}'을(를) 찾지 못했다"
            )
        # 자손 정리를 보장하지 못하면 띄우지 않는다: Job을 먼저 만들고, 멈춘 채 띄워 Job에 넣은 뒤
        # 이어 돌린다 (띄운 뒤 넣으면 그 사이 생긴 손자가 Job 밖에 남는다)
        try:
            job = Job.create()
        except OSError as exc:
            raise AgentFailure(
                "agent_start_failed", f"에이전트를 묶을 Job을 만들지 못했다: {exc}"
            ) from exc
        try:
            self._proc = subprocess.Popen(
                [exe, *command.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=command.cwd,
                env=dict(command.env),
                creationflags=CHILD_FLAGS | _CREATE_SUSPENDED,
            )
        except OSError as exc:
            job.close()
            raise AgentFailure(
                "agent_start_failed", f"에이전트 '{command.command}'을(를) 띄우지 못했다: {exc}"
            ) from exc
        try:
            job.assign(self._proc.pid)
            resume_suspended(self._proc.pid)
        except OSError as exc:
            _discard(self._proc, job)
            raise AgentFailure(
                "agent_start_failed", f"에이전트를 Job에 넣어 시작하지 못했다: {exc}"
            ) from exc
        self._job = job
        self._reader = threading.Thread(target=self._read, name="acp-judge", daemon=True)
        self._reader.start()
        self._writer = threading.Thread(target=self._write, name="acp-judge-write", daemon=True)
        self._writer.start()

    # ------------------------------------------------------------ 흐름

    def run(self, prompt: Sequence[Mapping[str, Any]]) -> AgentReply:
        init = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": CLIENT_CAPABILITIES,
                "clientInfo": {"name": "kookabug-judge", "version": "0"},
            },
            started=False,
        )
        if any(block.get("type") == "image" for block in prompt) and not _accepts_image(init):
            raise AgentFailure(
                "agent_protocol_error",
                "에이전트가 이미지 입력을 받지 않는다 (promptCapabilities.image)",
            )
        new = self._request("session/new", {"cwd": self._cwd, "mcpServers": []})
        session = new.get("sessionId")
        if not isinstance(session, str) or not session:
            raise AgentFailure("agent_protocol_error", "session/new 결과에 sessionId가 없다")
        self._session_id = session
        result = self._request("session/prompt", {"sessionId": session, "prompt": list(prompt)})
        stop = result.get("stopReason")
        self._reply.stop_reason = stop if isinstance(stop, str) else None
        self._session_id = None  # 끝난 차례는 취소하지 않는다
        segments = self._reply.segments
        self._reply.text = segments[-1] if segments else ""
        return self._reply

    # ------------------------------------------------------------ 보내기·받기

    def _send(self, message: Mapping[str, Any]) -> None:
        """보낼 줄을 쓰기 스레드 큐에 넣는다. 에이전트가 입력을 읽지 않아 쓰기가 막혀도 주 루프는
        기한·취소를 계속 본다 (막힌 쓰기는 Job을 끝내면 풀린다)."""
        if self._write_failed:
            raise AgentFailure("agent_protocol_error", "에이전트가 입력을 닫았다")
        data = json.dumps({"jsonrpc": "2.0", **message}, ensure_ascii=False).encode("utf-8")
        self._outbox.put(data + b"\n")

    def _write(self) -> None:
        stdin = self._proc.stdin
        assert stdin is not None
        while True:
            data = self._outbox.get()
            if data is None:
                return
            try:
                stdin.write(data)
                stdin.flush()
            except BaseException:
                # 스레드 밖(기본 처리기 → stderr traceback)으로 내보내지 않는다
                self._write_failed = True
                return
            finally:
                self._outbox.task_done()

    def _request(
        self, method: str, params: Mapping[str, Any], *, started: bool = True
    ) -> dict[str, Any]:
        rid = next(self._ids)
        self._send({"id": rid, "method": method, "params": params})
        while True:
            message = self._next()
            if message is _EOF:
                code = self._proc.poll()
                what = "agent_protocol_error" if started else "agent_start_failed"
                raise AgentFailure(what, f"에이전트가 {method} 답 전에 끝났다 (종료 코드 {code})")
            if not isinstance(message, dict):
                raise AgentFailure(
                    "agent_protocol_error", "에이전트가 JSON 객체가 아닌 줄을 보냈다"
                )
            body = cast(dict[str, Any], message)
            if "method" in body:
                self._incoming(body)
                continue
            if body.get("id") != rid:
                continue  # 모르는 답은 버린다
            if "error" in body:
                error = body["error"]
                text = error.get("message") if isinstance(error, dict) else error
                raise AgentFailure(
                    "agent_protocol_error", f"에이전트가 {method}을(를) 거부했다: {_short(text)}"
                )
            result = body.get("result")
            if not isinstance(result, dict):
                raise AgentFailure("agent_protocol_error", f"{method} 결과가 객체가 아니다")
            return cast(dict[str, Any], result)

    def _next(self) -> Any:
        while True:
            self._check()
            left = self._deadline - time.monotonic()
            if left <= 0:
                raise AgentFailure("agent_timeout", "판단 에이전트가 제한 시간 안에 답하지 않았다")
            try:
                return self._inbox.get(timeout=min(_POLL_S, left))
            except queue.Empty:
                continue

    def _read(self) -> None:
        stdout = self._proc.stdout
        assert stdout is not None
        # 이 스레드의 예외는 밖(기본 처리기 → stderr traceback, 받은 줄이 들어 있을 수 있음)으로
        # 내보내지 않는다. 주 루프에는 표식("bad line"·EOF)만 넘긴다
        try:
            for raw in stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    message: Any = json.loads(line)
                except BaseException:
                    message = "bad line"
                self._inbox.put(message)
        except BaseException:
            pass
        finally:
            self._inbox.put(_EOF)

    def _incoming(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params")
        params = cast(dict[str, Any], params) if isinstance(params, dict) else {}
        if "id" not in message:
            if method == "session/update":
                self._update(params)
            return
        if method == "session/request_permission":
            self._reply.permission_requests += 1
            self._send({"id": message["id"], "result": {"outcome": _reject(params)}})
            return
        self._send(
            {
                "id": message["id"],
                "error": {"code": _METHOD_NOT_FOUND, "message": f"지원하지 않는다: {method}"},
            }
        )

    def _update(self, params: Mapping[str, Any]) -> None:
        update = params.get("update")
        if not isinstance(update, dict):
            return
        update = cast(dict[str, Any], update)
        kind = update.get("sessionUpdate")
        if kind == "agent_message_chunk":
            content = update.get("content")
            if not isinstance(content, dict):
                return
            content = cast(dict[str, Any], content)
            text = content.get("text")
            if content.get("type") != "text" or not isinstance(text, str):
                return
            if self._size + len(text) > _TEXT_LIMIT:
                return
            self._size += len(text)
            segments = self._reply.segments
            if not self._segment_open or not segments:
                segments.append("")
                self._segment_open = True
            segments[-1] += text
        elif kind in ("tool_call", "tool_call_update", "plan"):
            # 도구 호출 뒤의 메시지는 새 덩어리 (답은 마지막 덩어리에서 읽는다)
            self._segment_open = False

    # ------------------------------------------------------------ 끝내기

    def close(self) -> None:
        if self._session_id is not None:
            # 취소 알림은 할 수 있으면만: 쓰기가 막혀 있어도 짧게만 기다리고 끝낸다
            with contextlib.suppress(AgentFailure):
                self._send({"method": "session/cancel", "params": {"sessionId": self._session_id}})
            end = time.monotonic() + _CANCEL_GRACE_S
            while self._outbox.unfinished_tasks and time.monotonic() < end:
                time.sleep(0.01)
        job = self._job
        try:
            if job is not None:
                with contextlib.suppress(OSError):
                    job.terminate()
            if self._proc.poll() is None:
                with contextlib.suppress(OSError):
                    self._proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self._proc.wait(timeout=_EXIT_WAIT_S)
        finally:
            self._outbox.put(None)
            writer = self._writer
            if writer is not None:
                # 프로세스가 끝났으므로 막힌 쓰기는 오류로 풀린다
                writer.join(timeout=_EXIT_WAIT_S)
            stuck = writer is not None and writer.is_alive()
            for pipe in (self._proc.stdin, self._proc.stdout):
                if pipe is not None and not (stuck and pipe is self._proc.stdin):
                    with contextlib.suppress(OSError):
                        pipe.close()
            if job is not None:
                job.close()
            if self._reader is not None:
                self._reader.join(timeout=_EXIT_WAIT_S)


def _discard(proc: subprocess.Popen[bytes], job: Job) -> None:
    """시작하지 못한(멈춘 채인) 에이전트를 끝내고 파이프·Job을 닫는다."""
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=_EXIT_WAIT_S)
    for pipe in (proc.stdin, proc.stdout):
        if pipe is not None:
            with contextlib.suppress(OSError):
                pipe.close()
    job.close()


def _resolve(command: str, env: Mapping[str, str]) -> str | None:
    """명령 이름 → 실행 파일 경로 (`PATH`·`PATHEXT`로, `.cmd` 런처 포함)."""
    path = Path(command)
    if path.is_absolute() or len(path.parts) > 1:
        return str(path) if path.is_file() else shutil.which(str(path))
    return shutil.which(command, path=env.get("PATH") or env.get("Path"))


def _accepts_image(init: Mapping[str, Any]) -> bool:
    caps = init.get("agentCapabilities")
    prompt = caps.get("promptCapabilities") if isinstance(caps, dict) else None
    return isinstance(prompt, dict) and cast(dict[str, Any], prompt).get("image") is True


def _reject(params: Mapping[str, Any]) -> dict[str, Any]:
    options = params.get("options")
    if isinstance(options, list):
        for kind in _REJECT_KINDS:
            for option in cast(list[Any], options):
                if isinstance(option, dict) and option.get("kind") == kind:  # pyright: ignore[reportUnknownMemberType]
                    option_id = cast(dict[str, Any], option).get("optionId")
                    if isinstance(option_id, str):
                        return {"outcome": "selected", "optionId": option_id}
    return {"outcome": "cancelled"}


def _short(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"
