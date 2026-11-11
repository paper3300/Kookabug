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
- `{"exit": 코드, "if_playbook": 이름}` — 프롬프트 머리말의 플레이북이 그 이름일 때만 끝낸다
  (앱 E2E 훅은 연결 시험과 Init에 같은 명령을 쓴다). UX2부터 `if_playbook`은 모든 단계에 쓴다 —
  플레이북이 다르면 그 단계를 건너뛴다(Init과 이어 하기를 각본 하나로)

앞 결과를 잇는 키 (M8 B6 시나리오 각본):
- `"label"` — 결과에 그대로 남긴다(검사가 단계를 찾는 이름)
- `"save": {변수: 경로}` — 결과(성공이면 `structuredContent`, 오류면 `error` 객체)에서 점 경로
  (`a.b.0.c`, 목록은 `[키=값]`으로 고름)의 값을 변수에 둔다. `${변수}`는 args 안에서 바뀐다(글자
  전체가 `${변수}`면 값 그대로, 아니면 글자로). `${job}`은 작업 ID
- `"check": {경로: 기대}` — 성공 결과의 값 단언. 기대는 값 그대로 또는 `{"$in": [...]}`·
  `{"$len": n}`·`{"$contains": x}`·`{"$not": 값}`
- `"expect": {"error": [코드, ...]}` — 그중 하나
- `{"sha256_file": 경로, "save": {변수: ""}}` — 워크스페이스 파일(원본·위키)을 Agent가 직접 읽어
  sha256(16진)을 둔다. 원본은 Kookabug 도구 밖에서 Agent가 읽는다(3.4)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

from kb_testing.mcp_client import McpClient, McpError

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
    try:
        result = mcp.call_tool(
            step["tool"], step.get("args") or {}, timeout=float(step.get("timeout", 300))
        )
    except McpError as exc:
        # 도구 입력 형식 거부(JSON-RPC -32602 — 도구 스키마에 없는 인자 등)도 결과로 남긴다
        code = "invalid_params" if exc.code == -32602 else f"mcp_error_{exc.code}"
        return {"error": code, "error_detail": {"code": exc.code, "message": exc.message}}
    if result.get("isError"):
        error = result["structuredContent"]["error"]
        return {"error": error["code"], "error_detail": error}
    return {"ok": result.get("structuredContent")}


_MISSING: Any = object()
_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _pick(value: Any, path: str) -> Any:
    """점 경로 값 (`a.b.0`, 목록에서 `[키=값]`으로 고르기). 없으면 `_MISSING`."""
    for part in [p for p in re.split(r"\.(?![^\[]*\])", path) if p]:
        chooser = re.fullmatch(r"\[([^=\]]+)=([^\]]*)\]", part)
        if chooser is not None and isinstance(value, list):
            key, want = chooser.group(1), chooser.group(2)
            items = cast(list[Any], value)
            value = next(
                (i for i in items if isinstance(i, dict) and str(i.get(key)) == want), _MISSING
            )
        elif isinstance(value, list) and part.lstrip("-").isdigit():
            items = cast(list[Any], value)
            index = int(part)
            value = items[index] if -len(items) <= index < len(items) else _MISSING
        elif isinstance(value, dict):
            value = cast(dict[str, Any], value).get(part, _MISSING)
        else:
            return _MISSING
        if value is _MISSING:
            return _MISSING
    return value


def _subst(value: Any, names: dict[str, Any]) -> Any:
    if isinstance(value, str):
        whole = _VAR.fullmatch(value)
        if whole is not None:
            if whole.group(1) not in names:
                raise ScriptFailed(f"변수 {whole.group(1)}이(가) 없다")
            return json.loads(json.dumps(names[whole.group(1)]))

        def one(found: re.Match[str]) -> str:
            if found.group(1) not in names:
                raise ScriptFailed(f"변수 {found.group(1)}이(가) 없다")
            got = names[found.group(1)]
            return got if isinstance(got, str) else json.dumps(got, ensure_ascii=False)

        return _VAR.sub(one, value)
    if isinstance(value, list):
        return [_subst(v, names) for v in cast(list[Any], value)]
    if isinstance(value, dict):
        return {k: _subst(v, names) for k, v in cast(dict[str, Any], value).items()}
    return value


def _matches(got: Any, want: Any) -> bool:
    if isinstance(want, dict) and len(cast(dict[str, Any], want)) == 1:
        (op, arg), *_ = cast(dict[str, Any], want).items()
        if op == "$in":
            return got in arg
        if op == "$len":
            return isinstance(got, list | dict | str) and len(cast(Any, got)) == arg
        if op == "$contains":
            return isinstance(got, list | str) and arg in got
        if op == "$not":
            return got != arg
    return got == want


def _check(step: dict[str, Any], got: dict[str, Any], names: dict[str, Any] | None = None) -> None:
    expect = step.get("expect", "ok")
    name = step.get("label") or step.get("tool")
    if expect == "ok" and "error" in got:
        raise ScriptFailed(f"{name}: 성공을 기대했는데 {got['error']}")
    if isinstance(expect, dict):
        want = expect.get("error")
        codes = want if isinstance(want, list) else [want]
        if got.get("error") not in codes:
            raise ScriptFailed(f"{name}: {want}를 기대했는데 {got}")
    for path, want in _subst(step.get("check") or {}, names or {}).items():
        value = _pick(got.get("ok"), path)
        if value is _MISSING or not _matches(value, want):
            shown = "없음" if value is _MISSING else json.dumps(value, ensure_ascii=False)[:400]
            raise ScriptFailed(f"{name}: {path} = {shown}, 기대 {want}")


def _save(step: dict[str, Any], got: dict[str, Any], names: dict[str, Any]) -> None:
    source = got["ok"] if "ok" in got else got.get("error_detail")
    for var, path in (step.get("save") or {}).items():
        value = _pick(source, path)
        if value is _MISSING:
            raise ScriptFailed(f"{step.get('label') or step.get('tool')}: 저장할 {path}가 없다")
        names[var] = value


def run(
    script: dict[str, Any],
    *,
    root: Path,
    out_dir: Path,
    results: list[dict[str, Any]] | None = None,
    save: Any = None,
    prompt: str = "",
) -> list[dict[str, Any]]:
    """`results`에 차례로 더하고 단계마다 `save()` — 감독이 트리를 끝내도 그때까지의 결과가
    남는다."""
    results = [] if results is None else results
    mcp: McpClient | None = None
    names: dict[str, Any] = {"job": os.environ.get("KOOKABUG_JOB_ID", "")}
    try:
        for n, step in enumerate(script.get("steps", [])):
            if save is not None:
                save()
            only = step.get("if_playbook")
            if only is not None and f"플레이북: {only} (" not in prompt:
                continue
            if "sha256_file" in step:
                data = (root / str(step["sha256_file"])).read_bytes()
                for var in step.get("save") or {}:
                    names[var] = hashlib.sha256(data).hexdigest()
                results.append({"step": n, "label": step.get("label"), "sha256_file": True})
                continue
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
                only = step.get("if_playbook")
                if only is not None and f"플레이북: {only} (" not in prompt:
                    continue
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
                args = _subst(args, names)
                got = _call(mcp, {**step, "args": args})
                label = step.get("label")
                results.append({"step": n, "i": i, "tool": step["tool"], "label": label, **got})
                then = step.get("then")
                if then is not None and "ok" in got:
                    # 앞 결과의 실행 ID를 다음 호출에 (예: kb_run_start → kb_run_status 기다리기)
                    run_id = str((got["ok"] or {}).get("run", ""))
                    then_args = json.loads(
                        json.dumps(then.get("args") or {}).replace("{run}", run_id)
                    )
                    after = _call(mcp, {**then, "args": _subst(then_args, names)})
                    results.append(
                        {"step": n, "i": i, "tool": then["tool"], "label": label, **after}
                    )
                if until is not None:
                    if got.get("error") == until:
                        break
                    if "error" in got:
                        raise ScriptFailed(f"{step['tool']}: {until} 전에 {got['error']}")
                    continue
                _check(step, got, names)
                _save(step, got, names)
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
        run(
            script,
            root=root,
            out_dir=out.parent,
            results=report["results"],
            save=save,
            prompt=prompt,
        )
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
