"""프로세스 사슬을 띄우고 각 단계의 식별을 파일로 남긴 뒤 끝없이 기다린다 (테스트 보조).

    python tree.py --out DIR --depth N [--job NAME] [--report-job NAME]

- `--job`: 맨 먼저 이름 있는 Job을 열어 자기를 넣는다 (runner의 시작 순서 1과 같다)
- `--report-job`: 그 Job에 자기가 들어 있는지 시작하자마자 확인해 남기고 핸들을 바로 닫는다
  (자식은 넣지 않아도 생성 시점부터 소속이어야 한다)
- 단계마다 `DIR/level<L>.json`(`{level, pid, created, in_job}`)을 쓰고, 남은 깊이가 있으면 다음
  단계를 띄운다. 끝내기는 바깥에서 한다
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from kookabug_core.win import Job, current


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=1)
    parser.add_argument("--level", type=int, default=0)
    parser.add_argument("--job")
    parser.add_argument("--report-job")
    args = parser.parse_args()

    in_job: bool | None = None
    job_name = args.job or args.report_job
    if job_name:
        job = Job.open(job_name)
        if args.job:
            job.assign_current()
        in_job = job.contains()
        if args.report_job:
            # 확인만 하는 단계는 핸들을 바로 닫는다: Job 핸들은 `--job` 단계(runner)만 쥔다
            job.close()

    me = current()
    record = {"level": args.level, "pid": me.pid, "created": me.created, "in_job": in_job}
    path = args.out / f"level{args.level}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record), encoding="utf-8")
    os.replace(tmp, path)

    if args.depth > 1:
        # venv 런처를 거치지 않는다: 런처의 자손 정리가 Job 동작을 가리지 않게 (kb_testing.proc)
        base = getattr(sys, "_base_executable", sys.executable)
        cmd = [base, __file__, "--out", str(args.out)]
        cmd += ["--depth", str(args.depth - 1), "--level", str(args.level + 1)]
        if job_name:
            cmd += ["--report-job", job_name]
        subprocess.Popen(cmd, env={**os.environ, "__PYVENV_LAUNCHER__": sys.executable})
    while True:
        time.sleep(60)


if __name__ == "__main__":
    main()
