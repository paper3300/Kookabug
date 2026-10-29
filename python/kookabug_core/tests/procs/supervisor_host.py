"""감독자를 별도 프로세스로 띄우는 보조 스크립트 (테스트 보조, M0b T10). 테스트가 감독자 프로세스를
죽이거나, 감독자 역할의 고장 주입 지점(`recovery.*`)을 쓰게 한다.

    python supervisor_host.py SPEC.json

사양 (JSON):
- `workspace_root`, `graph`, `runner_cmd`(runner를 띄울 명령), `out`(상태 파일 폴더)
- `options`: `StartOptions` 필드(`deadline_ms`, `plugin_modules`, `platform{kind, input_log,
  hooks}`, `runs_dir`, `shutdown_grace_ms`, `self_kill_margin_ms`, `worker_cancel_grace_ms`)

동작: 고장 주입 역할을 `supervisor`로 정하고 `Supervisor.start` → `started.json`(`run_id`·`run_dir`·
`runner`·`supervisor` 식별) → `out/cancel` 파일이 생기면 `cancel()` → `wait()`(runner 종료 → 복구
경로) → `done.json`(`exit_code`·`hard_stopped`·`start_error`·`recover_error`·`appended`·`run_end`).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from kookabug_core.runner.spec import PlatformSpec
from kookabug_core.supervisor import RunHandle, StartOptions, Supervisor
from kookabug_core.win import current
from kookabug_sdk import _faults
from kookabug_sdk.console import utf8_stdio


def write_status(out: Path, name: str, data: Any) -> None:
    tmp = out / f".{name}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out / name)


def options_of(data: dict[str, Any]) -> StartOptions:
    platform = data.pop("platform", {"kind": "none"})
    runs_dir = data.pop("runs_dir", None)
    return StartOptions(
        platform=PlatformSpec(
            kind=platform["kind"],
            input_log=platform.get("input_log"),
            hooks=platform.get("hooks", {}),
        ),
        runs_dir=None if runs_dir is None else Path(runs_dir),
        plugin_modules=tuple(data.pop("plugin_modules", ())),
        **data,
    )


def watch_cancel(out: Path, handle: RunHandle) -> None:
    while not (out / "cancel").exists():
        time.sleep(0.02)
    handle.cancel()


def main() -> int:
    utf8_stdio()
    _faults.set_role("supervisor")
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(spec["out"])
    out.mkdir(parents=True, exist_ok=True)
    # runner도 런처 없이 띄운다: 이 프로세스가 시작할 때 지운 `__PYVENV_LAUNCHER__`를 다시 넣는다
    env = {**os.environ, "__PYVENV_LAUNCHER__": sys.executable}
    handle = Supervisor(runner_cmd=spec["runner_cmd"], env=env).start(
        spec["workspace_root"], spec["graph"], options_of(dict(spec.get("options", {})))
    )
    ident = handle.runner_ident
    write_status(
        out,
        "started.json",
        {
            "run_id": handle.run_id,
            "run_dir": str(handle.run_dir),
            "runner": None if ident is None else ident.to_json(),
            "supervisor": current().to_json(),
            "start_error": handle.start_error,
        },
    )
    threading.Thread(target=watch_cancel, args=(out, handle), daemon=True).start()
    outcome = handle.wait()
    recovered = outcome.recovered
    write_status(
        out,
        "done.json",
        {
            "exit_code": outcome.exit_code,
            "hard_stopped": outcome.hard_stopped,
            "start_error": outcome.start_error,
            "recover_error": outcome.recover_error,
            "appended": None if recovered is None else recovered.finalize.appended,
            "run_end": outcome.run_end,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
