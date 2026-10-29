"""runner 역할 프로세스: 워커 하네스로 그래프 하나를 실행하고 결과를 JSON으로 쓴다.

    python worker_runner.py <워크스페이스> <그래프> <작업 폴더> <결과.json>

결과: `{verdict, remote(원격 노드 타입), imported(이 프로세스가 import한 testkit 모듈)}`.
runner가 플러그인 코드를 import하지 않는지 보는 검사가 쓴다 (`PYTHONPATH`에 testkit이 있어도
워커만 읽어야 한다).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from helpers.worker import WorkerHarness

from kookabug_core.workspace import Workspace


def main() -> None:
    root, graph, work, out = sys.argv[1:5]
    harness = WorkerHarness(Workspace.open(root), graph, Path(work), env=dict(os.environ))
    result = harness.run_all()
    registry = harness.registry
    remote = [t for t in registry.types() if (d := registry.get(t)) is not None and d.remote]
    imported = [m for m in sys.modules if m == "testkit" or m.startswith("testkit.")]
    Path(out).write_text(
        json.dumps({"verdict": result.verdict, "remote": sorted(remote), "imported": imported}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
