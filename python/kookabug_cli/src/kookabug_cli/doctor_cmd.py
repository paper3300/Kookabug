"""`kookabug doctor` (구현 계획 M1 2.11, 계획 검수 8).

    kookabug doctor [--profile headless|desktop] [--json]

검사 항목과 프로필은 `kookabug_platform.doctor`. 기본 프로필은 `desktop`(사람이 쓰는 명령), 설치
스모크·헤드리스 CI는 `--profile headless`를 쓴다. 종료 코드: 고른 프로필의 검사가 전부 통과면 `0`,
아니면 `1`. `--json`이면 한 객체 `{ok, profile, checks: [{id, profile, ok, detail}]}`.
"""

from __future__ import annotations

import argparse
import json
from typing import Final, TextIO

from kookabug_core.win import dpi
from kookabug_platform.doctor import Profile, run_checks

__all__ = ["EXIT_FAILED", "EXIT_OK", "run"]

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1


def run(args: argparse.Namespace, out: TextIO, err: TextIO) -> int:
    dpi.enable_at_startup()  # 좌표를 쓰는 CLI 진입점 (결과는 `dpi` 항목이 본다)
    profile: Profile = args.profile
    checks = run_checks(profile)
    ok = all(c.ok for c in checks)
    if args.json:
        body = {"checks": [c.to_json() for c in checks], "ok": ok, "profile": profile}
        out.write(json.dumps(body, ensure_ascii=False) + "\n")
    else:
        for c in checks:
            out.write(f"[{'통과' if c.ok else '실패'}] {c.id} ({c.profile}): {c.detail}\n")
        failed = sum(not c.ok for c in checks)
        summary = "전부 통과" if ok else f"실패 {failed}개"
        out.write(f"doctor ({profile}): 검사 {len(checks)}개, {summary}\n")
    return EXIT_OK if ok else EXIT_FAILED
