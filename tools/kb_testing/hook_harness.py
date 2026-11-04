"""녹화 훅 프로세스를 파이프 수준에서 직접 다루는 검사 도구 (M4 계획 2.1 T3, 검수 T3-1 지적 4).

`HookClient`는 `RpcPeer` 읽기 스레드가 파이프를 계속 비워 무제한 큐에 쌓는다 — 그래서 "daemon이
파이프 읽기를 멈춤"을 흉내 내려면 그 위에서 막아서는 안 된다. `RawHook`은 같은 방식(Job·named
pipe + HMAC·키는 stdin)으로 훅 프로세스(또는 가짜 자식)를 띄우되, 프레임을 **검사가 직접**
`recv()`로 읽는다. 읽지 않는 동안 파이프 버퍼가 차서 훅의 송신 쓰기가 막힌다.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from kookabug_core.win import Job, current, spawn
from kookabug_sdk.pipe import PipeConnection, PipeListener, PipeTimeout, new_key, new_pipe_name

__all__ = ["RawHook", "hook_entry_lags_ms"]


def hook_entry_lags_ms(
    sent_ns: Sequence[int],
    events: Sequence[Mapping[str, Any]],
    *,
    mono_base_ns: int,
    vk: int,
    extra_info: int,
) -> list[float]:
    """보낸 입력 ↔ 훅이 받은 이벤트의 **훅 진입 지연** (`t_ns + mono_base_ns - 보낸 시각`, ms).

    보낸 차례와 검사 표식(`extra_info`)·키(`vk`)가 같은 `key_down`을 차례로 짝짓는다 — 사람이 친
    키나 다른 입력은 끼지 않는다. 개수가 다르면 `AssertionError` (훅이 입력을 놓쳤다)."""
    downs = [
        e
        for e in events
        if e.get("kind") == "key_down" and e.get("vk") == vk and e.get("extra_info") == extra_info
    ]
    assert len(downs) == len(sent_ns), f"보낸 키 {len(sent_ns)}개, 훅이 받은 키 {len(downs)}개"
    lags = [
        (int(e["t_ns"]) + mono_base_ns - sent) / 1e6 for e, sent in zip(downs, sent_ns, strict=True)
    ]
    assert all(lag >= 0 for lag in lags), f"훅 시각이 보낸 시각보다 앞선다: {min(lags):.3f} ms"
    return lags


class RawHook:
    def __init__(
        self,
        command: Sequence[str],
        *,
        mono_base_ns: int,
        logs_dir: Path,
        env: Mapping[str, str] | None = None,
        extra_args: Sequence[str] = (),
    ) -> None:
        self.command = list(command)
        self.mono_base_ns = mono_base_ns
        self.logs_dir = logs_dir
        self.env = None if env is None else dict(env)
        self.extra_args = list(extra_args)
        self.job: Job | None = None
        self.conn: PipeConnection | None = None
        self.launcher: subprocess.Popen[bytes] | None = None

    def start(self, timeout: float = 30.0) -> RawHook:
        self.job = Job.create(kill_on_close=True)
        listener = PipeListener(new_pipe_name("hook-raw"))
        key = new_key()
        me = current()
        args = [
            *self.command,
            "--pipe",
            listener.name,
            "--parent-pid",
            str(me.pid),
            "--parent-created",
            str(me.created),
            "--mono-base-ns",
            str(self.mono_base_ns),
            *self.extra_args,
        ]
        self.launcher = spawn(
            args,
            stdout=self.logs_dir / "rawhook.stdout.log",
            stderr=self.logs_dir / "rawhook.stderr.log",
            env=self.env,
            stdin=subprocess.PIPE,
        )
        assert self.launcher.stdin is not None
        self.launcher.stdin.write((key.hex() + "\n").encode("ascii"))
        self.launcher.stdin.close()
        self.job.assign(self.launcher.pid)
        try:
            self.conn = listener.accept(key, timeout=timeout)
        finally:
            listener.close()
        return self

    def adopt(self, hello: Mapping[str, Any]) -> None:
        """hello가 알린 실제 프로세스(venv 런처의 자식)도 Job에 넣는다."""
        pid = int(hello["pid"])
        if self.job is not None and self.launcher is not None and pid != self.launcher.pid:
            # 이미 끝났거나 다른 Job — 파이프가 닫히면 스스로 끝난다
            with contextlib.suppress(OSError):
                self.job.assign(pid)

    def recv(self, timeout: float | None = None) -> dict[str, Any] | None:
        """다음 메시지 (기한을 넘기면 None)."""
        assert self.conn is not None
        try:
            frame = self.conn.recv_frame(timeout=timeout)
        except PipeTimeout:
            return None
        return json.loads(frame)

    def send(self, method: str, params: Mapping[str, Any]) -> None:
        assert self.conn is not None
        body = json.dumps({"jsonrpc": "2.0", "method": method, "params": dict(params)})
        self.conn.send_frame(body.encode("utf-8"), timeout=5.0)

    def stderr(self) -> str:
        path = self.logs_dir / "rawhook.stderr.log"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
        if self.job is not None:
            self.job.close()  # 훅 프로세스(와 venv 런처의 자식)를 끝낸다
            self.job = None
        if self.launcher is not None:
            try:
                self.launcher.wait(5)
            except subprocess.TimeoutExpired:
                self.launcher.kill()
