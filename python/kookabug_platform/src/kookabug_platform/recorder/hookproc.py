"""녹화 훅 프로세스 (M4 계획 2.1). `python -m kookabug_platform.recorder.hookproc`.

녹화 중에만 사는 자식 프로세스다. daemon(asyncio·매칭·OCR)이나 캡처 콜백과 같은 프로세스에 두지
않는다 — 저수준 훅 함수가 늦으면 시스템 전체 입력이 늦고, `LowLevelHooksTimeout`을 넘기면 Windows가
알리지 않고 훅을 뗀다. 그래서 ctypes·표준 라이브러리만 import한다(numpy·cv2·onnxruntime 없음).

**훅 콜백이 하는 일은 이것뿐이다** (`HookCore.on_mouse`·`on_key`): 단조 시각 찍기 → `event_id`
→ 구조체 필드 복사(해석은 순수 함수) → 우리 표식이면 버리기(`dropped_marker`) → 이동이면 이동
칸 하나를 덮어씀(`coalesced_moves`) → 중요 이벤트면 `crit_seq`를 매긴 뒤 중요 큐(고정 4096칸)에
넣기, 차 있으면 기다리지 않고 버리고 `overflow` → `CallNextHookEx`. 대상 창이나 다른 스레드에
아무것도 묻지 않는다(잠금 대기·I/O·로그 없음). 중요 이벤트 직전에는 그 순간의 이동을 먼저 큐에
넣는다(버튼·휠의 위치, 큐의 event_id 차례).

스레드(`hookwin32`): 훅 스레드(`SetWindowsHookExW` + 메시지 루프), 관측 스레드(즉시 관측 —
메시지 없는 API와 창 이벤트로 갱신하는 Z 순서 표), IME 표본 스레드(대상에 묻는 유일한 조회 —
`SendMessageTimeoutW` 50 ms, 즉시 관측과 따로 돌아 조회가 막혀도 관측이 밀리지 않음 — 3차 검수
N5), 송신 스레드(묶음·관측·표본·생존 보고를 파이프로, 쓰기가 막히면 기다리고 그동안 중요 큐가
차면 `overflow`), 읽기 스레드(`hook.stop`), 부모 감시(daemon이 죽으면 끝난다 — OS가 훅을 뗀다).

진입점 인자: `--pipe`(daemon의 파이프 이름), `--parent-pid`·`--parent-created`,
`--mono-base-ns`(녹화 기준 시각 — 모든 `*_ns`는 여기서 잰 단조 시계), `--target-hwnd`(IME 정기
표본을 뜰 대상), 검사 전용 `--ime-query-window`(IME 조회 대상을 바꿔 끼움)·`--sender-load-ms`
(송신 틱마다 CPU 부하 — 지연 검사). 검사 전용 인자는 `KOOKABUG_TESTING=1`이 아니면 시작하지
않는다. 파이프 키는 stdin 첫 줄(16진).
"""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Any, Final

from kookabug_core.recorder.contract import (
    BATCH_MAX_EVENTS,
    CRIT_QUEUE_SIZE,
    HOOK_PROTOCOL,
    IME_SWITCH_VKS,
    MOVE_COALESCE_NS,
)
from kookabug_platform.inputmark import KOOKABUG_INPUT_MARK
from kookabug_platform.recorder.parse import key_event, mouse_event

__all__ = ["EXIT_HOOK_FAILED", "EXIT_PARENT_GONE", "HookCore", "encode", "main"]

EXIT_HOOK_FAILED: Final = 3
EXIT_PARENT_GONE: Final = 4

_POINTER_KINDS: Final = frozenset({"mouse_down", "mouse_up", "wheel"})


class HookCore:
    """훅 콜백의 상태와 묶음 만들기. Win32를 부르지 않는다 (콜백·송신 스레드가 같이 쓴다).

    콜백 쪽(`on_mouse`·`on_key`·`accept_raw`)은 훅 스레드 하나만, 묶음 쪽(`take_batch`)은 송신
    스레드 하나만 부른다. 둘 사이는 `deque`의 원자적 `append`·`popleft`뿐이고 잠금이 없다.
    """

    def __init__(
        self,
        *,
        base_ns: int = 0,
        clock: Callable[[], int] = time.monotonic_ns,
        crit_capacity: int = CRIT_QUEUE_SIZE,
        max_batch: int = BATCH_MAX_EVENTS,
        coalesce_ns: int = MOVE_COALESCE_NS,
    ) -> None:
        self._clock = clock
        self._base = base_ns
        self._capacity = crit_capacity
        self._max_batch = max_batch
        self._coalesce_ns = coalesce_ns
        self.event_id = 0
        self.crit_seq = 0
        self.batch_no = 0
        self.dropped_marker = 0
        self.coalesced_moves = 0
        self.overflow = 0
        self.last_event_ns: int | None = None
        self._move: dict[str, Any] | None = None
        self._move_sent_ns: int | None = None
        self._crit: deque[dict[str, Any]] = deque()
        self._reported_overflow = 0
        self._reported_marker = 0
        self._sent_id = 0
        """송신이 보낸 마지막 event_id (송신 스레드만 쓴다, 콜백은 읽기만)."""
        self._first_drop_id: int | None = None
        self.obs_requests: deque[dict[str, Any]] = deque()
        """관측 스레드가 즉시 관측을 만들 중요 이벤트 (하나마다 하나)."""
        self.ime_requests: deque[tuple[str, int]] = deque()
        """IME 표본 스레드에 알릴 키: `("key"|"ime_key", t_ns)`."""
        self.force_drop = 0
        """검사·가짜 원천용: 다음 중요 이벤트 이만큼을 큐가 찬 것처럼 버린다 (`overflow`)."""

    def now(self) -> int:
        return self._clock() - self._base

    # ── 콜백 쪽 (훅 스레드) ──────────────────────────────────

    def on_mouse(self, msg: int, x: int, y: int, mouse_data: int, flags: int, extra: int) -> None:
        t = self._clock() - self._base
        self.event_id += 1
        self.last_event_ns = t
        if extra == KOOKABUG_INPUT_MARK:
            self.dropped_marker += 1
            return
        raw = mouse_event(msg, x, y, mouse_data, flags, extra)
        if raw is not None:
            self._accept(raw, t)

    def on_key(self, msg: int, vk: int, scan: int, flags: int, extra: int) -> None:
        t = self._clock() - self._base
        self.event_id += 1
        self.last_event_ns = t
        if extra == KOOKABUG_INPUT_MARK:
            self.dropped_marker += 1
            return
        raw = key_event(msg, vk, scan, flags, extra)
        if raw is not None:
            self._accept(raw, t)

    def accept_raw(self, raw: dict[str, Any], t_ns: int) -> None:
        """이미 해석한 원시 입력 하나를 그 시각에 받는다 (가짜 원천 — 콜백과 같은 규칙)."""
        self.event_id += 1
        self.last_event_ns = t_ns
        if raw.get("extra_info") == KOOKABUG_INPUT_MARK:
            self.dropped_marker += 1
            return
        self._accept(dict(raw), t_ns)

    def _accept(self, raw: dict[str, Any], t: int) -> None:
        raw["event_id"] = self.event_id
        raw["t_ns"] = t
        kind = raw["kind"]
        move = self._move
        if kind == "mouse_move":
            if move is not None and move["event_id"] > self._sent_id:
                self.coalesced_moves += 1
            self._move = raw
            return
        if move is not None:
            # 중요 이벤트 직전에는 그 순간 위치를 먼저 큐에 넣는다 (버튼·휠의 끌기·커서 진입 시각).
            # 키 앞에서도 넣어야 큐가 event_id 차례로 남는다 — 이동이 키보다 앞 번호인데 다음 버튼
            # 앞에서야 넣으면 묶음 경계에서 차례가 뒤집힌다
            self._move = None
            if move["event_id"] > self._sent_id:  # 송신이 이미 칸에서 보낸 이동은 다시 넣지 않음
                if len(self._crit) < self._capacity:
                    self._crit.append(move)
                else:
                    self.coalesced_moves += 1
        self.crit_seq += 1
        raw["crit_seq"] = self.crit_seq
        if self.force_drop > 0 or len(self._crit) >= self._capacity:
            # 기다리지 않는다: 그 번호는 쓰였으니 받는 쪽에 빈틈이 생긴다 (실제 유실의 증거)
            if self.force_drop > 0:
                self.force_drop -= 1
            if self._first_drop_id is None:
                self._first_drop_id = raw["event_id"]
            self.overflow += 1
            return
        self._crit.append(raw)
        self.obs_requests.append(raw)
        if kind == "key_up" and raw["vk"] in IME_SWITCH_VKS:
            self.ime_requests.append(("ime_key", t))
        elif kind in ("key_down", "key_up"):
            self.ime_requests.append(("key", t))

    # ── 묶음 쪽 (송신 스레드) ────────────────────────────────

    def take_batch(self, now_ns: int | None = None) -> dict[str, Any] | None:
        """보낼 `hook.events` params 하나 (보낼 것이 없으면 None).

        묶음 사이에도 event_id가 줄지 않는다: 중요 큐는 콜백이 event_id 차례로만 넣고, 이동 칸의
        이동은 남은 큐 머리보다 앞 번호일 때만 보낸다. 송신은 이동 칸을 비우지 않는다(콜백과 같은
        칸을 다투지 않게) — 대신 보낸 마지막 번호(`_sent_id`)를 적고, 그 번호 이하는 다시 보내지
        않는다. 넘침(`overflow`)은 첫 버린 이벤트 앞의 큐를 다 보낸 묶음부터 알린다 — 받는 쪽이
        유실 지점에서 자르고 그 앞 동작은 남긴다.
        """
        now = self.now() if now_ns is None else now_ns
        items: list[dict[str, Any]] = []
        while self._crit and len(items) < self._max_batch - 1:
            item = self._crit.popleft()
            if item["event_id"] > self._sent_id:
                items.append(item)
        move = self._move
        if move is not None and move["event_id"] > self._sent_id:
            head = self._crit[0]["event_id"] if self._crit else None
            due = self._move_sent_ns is None or now - self._move_sent_ns >= self._coalesce_ns
            if due and (head is None or move["event_id"] < head):
                items.append(move)
                self._move_sent_ns = now
        drop = self._first_drop_id
        overflow = self._reported_overflow
        if drop is not None and (not self._crit or self._crit[0]["event_id"] > drop):
            overflow = self.overflow
        # 우리 표식만 버린 경우에도 누적 개수는 알린다 (빈 묶음) — 받는 쪽이 "우리 입력을 걸렀다"를
        # 셀 수 있게. 이동 합치기 개수는 다음 이동 묶음에 실려 간다
        marker = (
            self.dropped_marker
        )  # 한 번 읽는다 (콜백이 그 사이 올려도 보낸 값과 적은 값이 같게)
        marker_changed = marker != self._reported_marker
        if not items and overflow == self._reported_overflow and not marker_changed:
            return None
        items.sort(key=lambda e: e["event_id"])
        if items:
            self._sent_id = items[-1]["event_id"]
        crit = [e["crit_seq"] for e in items if "crit_seq" in e]
        self.batch_no += 1
        self._reported_overflow = overflow
        self._reported_marker = marker
        return {
            "batch_no": self.batch_no,
            "events": items,
            "crit_first": crit[0] if crit else None,
            "crit_last": crit[-1] if crit else None,
            "dropped_marker": marker,
            "coalesced_moves": self.coalesced_moves,
            "overflow": overflow,
        }


def encode(method: str, params: dict[str, Any]) -> bytes:
    """응답 없는 JSON-RPC 알림 프레임 본문."""
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kookabug-hookproc", description="녹화 훅 프로세스")
    parser.add_argument("--pipe", required=True)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("--parent-created", type=int, required=True)
    parser.add_argument("--mono-base-ns", type=int, required=True)
    parser.add_argument("--target-hwnd", type=int, default=None)
    parser.add_argument("--ime-query-window", type=int, default=None)
    # 검사 전용: 송신 틱마다 이만큼 CPU를 붙잡는다 (GIL 경쟁 속 훅 콜백 지연 검사)
    parser.add_argument("--sender-load-ms", type=float, default=0.0)
    args = parser.parse_args(argv)
    testing_only = args.ime_query_window is not None or args.sender_load_ms > 0
    if testing_only and os.environ.get("KOOKABUG_TESTING") != "1":
        parser.error("--ime-query-window·--sender-load-ms는 검사 전용이다 (KOOKABUG_TESTING=1)")
    return args


def _watch_parent(pid: int, created: int) -> None:
    """daemon이 죽으면 바로 끝난다 (Job과 별도로 — 훅은 프로세스가 끝나면 OS가 뗀다)."""
    from kookabug_core.win import Process, ProcessId

    try:
        parent = Process.open(ProcessId(pid, created))
    except ProcessLookupError:
        os._exit(EXIT_PARENT_GONE)
    parent.wait()
    os._exit(EXIT_PARENT_GONE)


def main(argv: list[str] | None = None) -> int:
    # 첫 줄: Per-Monitor V2 (MSLLHOOKSTRUCT.pt가 물리 화면 좌표)
    from kookabug_core.win import dpi as core_dpi

    try:
        core_dpi.ensure_per_monitor_v2()
        awareness = "per_monitor_v2"
    except core_dpi.DpiAwarenessUnavailable:
        awareness = "system"
    args = _parse_args(argv)
    key = bytes.fromhex(sys.stdin.readline().strip())
    from kookabug_core.win import current
    from kookabug_platform.recorder import hookwin32
    from kookabug_sdk import pipe

    sys.setswitchinterval(0.0005)
    threading.Thread(
        target=_watch_parent,
        args=(args.parent_pid, args.parent_created),
        name="hook-parent",
        daemon=True,
    ).start()
    conn = pipe.connect(args.pipe, key)
    core = HookCore(base_ns=args.mono_base_ns)
    api = hookwin32.Win32Api()
    hooks = hookwin32.HookThread(core)
    if not hooks.start():
        print(f"훅을 걸지 못했다: {hooks.error}", file=sys.stderr)
        conn.close()
        return EXIT_HOOK_FAILED
    stop = threading.Event()
    sampler = hookwin32.ImeSampler(
        core, api, target_hwnd=args.target_hwnd, query_window=args.ime_query_window
    )
    observer = hookwin32.Observer(core, api, on_change=sampler.request)
    me = current()
    hello = {
        "pid": me.pid,
        "created": str(me.created),
        "dpi_awareness": awareness,
        "hooks": {"mouse": True, "keyboard": True},
        "mono_base_ns": str(args.mono_base_ns),
        "protocol": HOOK_PROTOCOL,
    }
    conn.send_frame(encode("hook.hello", hello), timeout=None)
    sender = hookwin32.Sender(
        core,
        api,
        conn,
        observer.out,
        sampler.out,
        on_broken=stop.set,
        load_s=args.sender_load_ms / 1000,
    )
    for worker in (observer, sampler, sender):
        worker.start()
    hookwin32.start_reader(conn, on_stop=stop.set)
    # 훅 프로세스는 오래 쌓는 객체가 없다: 수집 멈춤으로 콜백 진입 전 대기를 줄인다
    gc.freeze()
    gc.disable()
    stop.wait()
    hooks.stop()
    observer.stop()
    sampler.stop()
    sender.stop(flush=True)
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
