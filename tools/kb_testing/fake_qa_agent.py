"""가짜 QA 에이전트 CLI (M8 계획 3.16) — CI에서 실제 모델 없이 `agent-job`을 끝에서 끝까지 돌린다.

    kookabug agent-job run ... --agent-command "python -m kb_testing.fake_qa_agent --script X"

1. stdin 프롬프트를 끝까지 읽고 단언한다: 작업 머리말(작업 ID = `KOOKABUG_JOB_ID`)이 있고,
   워크스페이스 `wiki/` 글이 들어 있지 않다
2. `KOOKABUG_JOB_MCP_CONFIG`의 `mcp.json`대로 실제 `kookabug mcp`를 띄운다 (토큰은 환경 변수로만
   넘어간다 — 인자에 없다)
3. 각본(`qa_scripts/<이름>.json`)의 단계를 차례로 한다. 단계마다 기대 결과(성공 / 특정 오류 코드)를
   단언하고 결과를 `--out`에 JSON으로 쓴다

단계 종류 (`{"tool": 이름, "args": {...}, "expect": "ok" | {"error": 코드}}` 외):
- `"repeat": N`·`"until_error": 코드` — 같은 호출을 그 오류가 날 때까지 (N번까지)
- `{"print": 글}`·`{"print_env": 이름}`·`{"print_split_env": 이름}` — 표준 출력에 쓴다(가림 검사의
  양성 입력: 값을 둘로 나눠 사이에 flush·쉼을 둔다)
- `{"sleep": 초}`·`{"spawn_child_sleep": 초}`(손자 프로세스 — 트리 정리 검사)·`{"exit": 코드}`
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from kb_testing.mcp_client import McpClient

SCRIPTS = Path(__file__).resolve().parent / "qa_scripts"


class ScriptFailed(AssertionError):
    pass


def _prompt_checks(prompt: str, root: Path) -> list[str]:
    problems: list[str] = []
    job = os.environ.get("KOOKABUG_JOB_ID", "")
    if "<!-- kookabug:job -->" not in prompt or f"작업 ID: {job}" not in prompt or not job:
        problems.append("prompt_header_missing")
    wiki = root / "wiki"
    if wiki.is_dir():
        for page in wiki.rglob("*.md"):
            for line in page.read_text("utf-8", errors="replace").splitlines():
                if len(line.strip()) >= 16 and line.strip() in prompt:
                    problems.append(f"wiki_in_prompt:{page.name}")
                    break
    return problems


def _spawn_mcp(config_path: Path, out: Path) -> McpClient:
    config = json.loads(config_path.read_text("utf-8"))
    server = config["mcpServers"]["kookabug"]
    out.mkdir(parents=True, exist_ok=True)
    stderr = (out / "stderr.log").open("ab")
    proc = subprocess.Popen(
        [server["command"], *server["args"]],
        env={**os.environ, **server.get("env", {})},
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=stderr,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return McpClient(proc, out)


def _call(mcp: McpClient, step: dict[str, Any]) -> dict[str, Any]:
    result = mcp.call_tool(
        step["tool"], step.get("args") or {}, timeout=float(step.get("timeout", 300))
    )
    if result.get("isError"):
        return {"error": result["structuredContent"]["error"]["code"]}
    return {"ok": result.get("structuredContent")}


def _check(step: dict[str, Any], got: dict[str, Any]) -> None:
    expect = step.get("expect", "ok")
    if expect == "ok" and "error" in got:
        raise ScriptFailed(f"{step['tool']}: 성공을 기대했는데 {got['error']}")
    if isinstance(expect, dict) and got.get("error") != expect.get("error"):
        raise ScriptFailed(f"{step['tool']}: {expect.get('error')}를 기대했는데 {got}")


def run(
    script: dict[str, Any],
    *,
    root: Path,
    out_dir: Path,
    results: list[dict[str, Any]] | None = None,
    save: Any = None,
) -> list[dict[str, Any]]:
    """`results`에 차례로 더하고 단계마다 `save()` — 감독이 트리를 끝내도 그때까지의 결과가
    남는다."""
    results = [] if results is None else results
    mcp: McpClient | None = None
    try:
        for n, step in enumerate(script.get("steps", [])):
            if save is not None:
                save()
            if "print" in step:
                print(step["print"], flush=True)
                continue
            if "print_env" in step:
                print(f"값: {os.environ.get(step['print_env'], '')}", flush=True)
                continue
            if "print_split_env" in step:
                value = os.environ.get(step["print_split_env"], "")
                half = max(1, len(value) // 2)
                sys.stdout.write(f"앞 {value[:half]}")
                sys.stdout.flush()
                time.sleep(0.3)
                sys.stdout.write(f"{value[half:]} 뒤\n")
                sys.stdout.flush()
                continue
            if "sleep" in step:
                time.sleep(float(step["sleep"]))
                continue
            if "spawn_child_sleep" in step:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-c",
                        f"import time; time.sleep({float(step['spawn_child_sleep'])})",
                    ],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                (out_dir / "grandchild.pid").write_text(str(child.pid), "utf-8")
                continue
            if "exit" in step:
                results.append({"step": n, "exit": step["exit"]})
                return results
            if mcp is None:
                mcp = _spawn_mcp(Path(os.environ["KOOKABUG_JOB_MCP_CONFIG"]), out_dir / "mcp")
                mcp.initialize()
            if "toolsets" in step:
                got = _call(
                    mcp, {"tool": "kb_toolset_enable", "args": {"toolsets": step["toolsets"]}}
                )
                results.append({"step": n, **got})
                continue
            until = step.get("until_error")
            repeat = int(step.get("repeat", 1))
            for i in range(repeat):
                args = json.loads(json.dumps(step.get("args") or {}).replace("{i}", str(i)))
                got = _call(mcp, {**step, "args": args})
                results.append({"step": n, "i": i, "tool": step["tool"], **got})
                then = step.get("then")
                if then is not None and "ok" in got:
                    # 앞 결과의 실행 ID를 다음 호출에 (예: kb_run_start → kb_run_status 기다리기)
                    run_id = str((got["ok"] or {}).get("run", ""))
                    then_args = json.loads(
                        json.dumps(then.get("args") or {}).replace("{run}", run_id)
                    )
                    after = _call(mcp, {**then, "args": then_args})
                    results.append({"step": n, "i": i, "tool": then["tool"], **after})
                if until is not None:
                    if got.get("error") == until:
                        break
                    if "error" in got:
                        raise ScriptFailed(f"{step['tool']}: {until} 전에 {got['error']}")
                    continue
                _check(step, got)
            else:
                if until is not None:
                    raise ScriptFailed(f"{step['tool']}: {repeat}번 안에 {until}가 나지 않았다")
        return results
    finally:
        if mcp is not None:
            mcp.close(30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake_qa_agent")
    parser.add_argument("--script", required=True, help="각본 이름(qa_scripts/) 또는 JSON 파일")
    parser.add_argument("--out", help="결과 JSON 파일")
    args = parser.parse_args(argv)
    # 출력은 UTF-8 (agent-job은 해석하지 않고 바이트 그대로 가려 쓴다)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    path = Path(args.script)
    if not path.suffix:
        path = SCRIPTS / f"{args.script}.json"
    script = json.loads(path.read_text("utf-8"))
    prompt = sys.stdin.buffer.read().decode("utf-8")
    root = Path.cwd()
    out = (
        Path(args.out) if args.out else Path(os.environ.get("KOOKABUG_JOB_DIR", ".")) / "fake.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "job": os.environ.get("KOOKABUG_JOB_ID"),
        "prompt": _prompt_checks(prompt, root),
    }
    report["argv_has_token"] = any(
        os.environ.get("KOOKABUG_JOB_TOKEN", "\0") in a for a in sys.argv
    )
    report["env_names"] = sorted(os.environ)
    report["results"] = []

    def save() -> None:
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")

    code = 0
    try:
        run(script, root=root, out_dir=out.parent, results=report["results"], save=save)
        exits = [r["exit"] for r in report["results"] if "exit" in r]
        code = int(exits[0]) if exits else 0
    except ScriptFailed as exc:
        report["failed"] = str(exc)
        code = 2
    save()
    if report["prompt"]:
        code = code or 3
    return code


if __name__ == "__main__":
    sys.exit(main())
