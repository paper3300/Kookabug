"""입력 임대권을 쥐는 runner 역할, 또는 감독자 복구 경로 역할 프로세스 (테스트 보조, M0b T6).

    python lease_holder.py SPEC.json

사양 (JSON):
- `mode`: `hold`(runner 역할: 임대권 + 입력 액터 + 저널) | `recover`(감독자 역할: `recover_run`)
- `out`: 상태 파일 폴더. `by`: 가짜 입력 기록의 `by`. `input_log`, `hooks`: 가짜 백엔드
- `hold`: `run_dir`·`run_id`(이 프로세스의 실행 기록), `lease_timeout`(기본 0), `script`(주 스레드가
  차례로 하는 동작)
  - `{"op": "key", "key": "ctrl"}`, `{"op": "click", "x": 1, "y": 2, "button": "left"}`
  - `{"op": "wait", "barrier": 경로}` — 파일 장벽. `{"op": "go", "barrier": 경로}` — 장벽을 연다
  - `{"op": "key_async", "key": "b"}` — 다른 스레드에서 요청하고 끝나면 `key_<키>.json`
    (`error`: 예외 이름 또는 null). `{"op": "wait_queued", "count": N}` — 큐에 N개가 들 때까지
  - `{"op": "finish", "join_timeout": 초}` — 액터 STOP·join → 깨끗한 놓기 시도 → `released.json`
    → 놓았으면 종료 코드 0, 못 놓았으면 4(놓지 않고 끝남 = 하드 종료와 같음)
  - `{"op": "exit", "code": N}` — 놓지 않고 `os._exit`. `{"op": "hang"}`
  - 동작이 다 끝나면 놓지 않고 종료 코드 0
  - `out/cancel` 파일이 생기면 제어 스레드가 액터 게이트를 닫는다(취소 순서 1·2). 그 뒤 주 스레드는
    입력 동작을 건너뛰고 `finish`·`exit`·`hang`만 한다
- `recover`: `target_run_dir`, `timeout`. `recovery.before_input_recovery` 지점을 지난 뒤
  `recover_run` → `recovered.json`

상태 파일: `acquired.json`(`abandoned`, `recovered`), `busy.json`(`owner`·`stale_owner`,
종료 코드 3), `released.json`(`clean`, `log_lines` = 놓은 순간의 가짜 기록 줄 수), `recovered.json`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from kookabug_core.inputs import (
    FakeBackend,
    InputActor,
    InputLease,
    InputLeaseBusy,
    LeaseOwner,
    recover_run,
)
from kookabug_core.record import Journal
from kookabug_core.record.runfolder import EVENTS_FILE
from kookabug_sdk import _faults
from kookabug_sdk.context import Cancelled
from kookabug_sdk.types import Point


def write_status(out: Path, name: str, data: Any) -> None:
    tmp = out / f".{name}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out / name)


def log_lines(path: Path) -> int:
    return path.read_bytes().count(b"\n") if path.exists() else 0


def recover(spec: dict[str, Any], out: Path) -> None:
    _faults.set_role("supervisor")
    backend = FakeBackend(spec["input_log"], run=None, by=spec.get("by", "supervisor"))
    _faults.fault_point("recovery.before_input_recovery")
    outcome = recover_run(
        spec["target_run_dir"], backend=backend, timeout=float(spec.get("timeout", 10))
    )
    write_status(
        out,
        "recovered.json",
        {"status": outcome.status, "inputs": [k.to_event() for k in outcome.inputs]},
    )
    os._exit(0)


def key_async(actor: InputActor, key: str, out: Path) -> None:
    error: str | None = None
    try:
        actor.key(key)
    except BaseException as exc:
        error = type(exc).__name__
    write_status(out, f"key_{key}.json", {"error": error})


def hold(spec: dict[str, Any], out: Path) -> None:
    _faults.set_role("runner")
    run_dir = Path(spec["run_dir"])
    run_dir.mkdir(parents=True, exist_ok=True)
    run_id = spec["run_id"]
    journal = Journal(run_dir / EVENTS_FILE, run_id)
    gate = threading.Event()
    log = Path(spec["input_log"])
    backend = FakeBackend(
        log, run=run_id, by=spec.get("by", run_id), hooks=spec.get("hooks"), gate=gate
    )
    owner = LeaseOwner.current("runner", run_id=run_id, run_dir=run_dir)
    lease = InputLease(owner, backend, emit=journal.emit)
    try:
        acquired = lease.acquire(float(spec.get("lease_timeout", 0)))
    except InputLeaseBusy as busy:
        write_status(out, "busy.json", {"owner": busy.owner, "stale_owner": busy.stale_owner})
        os._exit(3)
    write_status(
        out,
        "acquired.json",
        {
            "abandoned": acquired.abandoned,
            "recovered": [
                {"from_run": r.from_run, "inputs": [k.to_event() for k in r.inputs]}
                for r in acquired.recovered
            ],
        },
    )
    actor = InputActor(backend, emit=journal.emit, gate=gate).start()

    def control() -> None:
        while not (out / "cancel").exists():
            time.sleep(0.01)
        actor.close_gate()

    threading.Thread(target=control, daemon=True, name="control").start()

    cancelled = False
    for op in spec.get("script", []):
        kind = op["op"]
        if kind == "finish":
            quiesced = actor.stop(float(op.get("join_timeout", 10)))
            clean = quiesced and lease.release(actor)
            write_status(out, "released.json", {"clean": clean, "log_lines": log_lines(log)})
            if clean:
                journal.close()
            os._exit(0 if clean else 4)
        if kind == "exit":
            os._exit(int(op.get("code", 0)))
        if kind == "hang":
            _faults.perform(_faults.Action("hang"))
        if cancelled:
            continue
        try:
            match kind:
                case "key":
                    actor.key(op["key"])
                case "key_async":
                    threading.Thread(
                        target=key_async, args=(actor, op["key"], out), daemon=True
                    ).start()
                case "wait_queued":
                    count = int(op["count"])
                    while len(actor._queue) < count:  # pyright: ignore[reportPrivateUsage]
                        time.sleep(0.01)
                case "go":
                    Path(f"{op['barrier']}.go").touch()
                case "click":
                    actor.click(Point(op["x"], op["y"]), button=op.get("button", "left"))
                case "wait":
                    _faults.perform(_faults.Action("wait", op["barrier"]))
                case _:
                    raise ValueError(f"모르는 동작 {kind!r}")
        except Cancelled:
            cancelled = True
    os._exit(0)


def main() -> None:
    spec: dict[str, Any] = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(spec["out"])
    out.mkdir(parents=True, exist_ok=True)
    if spec["mode"] == "recover":
        recover(spec, out)
    else:
        hold(spec, out)


if __name__ == "__main__":
    main()
