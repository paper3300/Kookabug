"""가짜 탐색 에이전트 (M7 계획 3.13): 실제 모델 없이 각본대로 실제 `kookabug mcp`의 도구를 부른다.

    python -m kb_testing.fake_explorer --workspace WS [--script 각본.json] [--out 폴더] [--json]

`kb_toolset_enable[observe, control, screens]` → `kb_explore_start` → 장면마다 캡처 →
`kb_screen_identify` → 처음이면 `kb_screen_save` → 입력 → … → `kb_explore_end`. 단계마다 기대
(처음 보는 화면 / 아는 화면 / 보호 중)를 단언한다. 보호 중 화면에 판정 조건을 저장하려 하면
`frame_protected`여야 한다(`try_save`). 이동은 다음 화면을 확인한 뒤 앞 화면 카드에 `to`로 남긴다.

검사 결과물을 미리 쓰지 않는다 — 모든 것이 MCP → daemon → runner(가짜 게임)를 거친다. 권한은
워크스페이스 설정(control allow)을 그대로 쓴다(사람 확인 카드는 B3 이후).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from kb_testing.mcp_client import McpClient
from kb_testing.proc import Spawned

__all__ = ["DEFAULT_SCRIPT", "ExploreFailed", "main", "run_script"]

DEFAULT_SCRIPT = Path(__file__).with_name("explore_scripts") / "sample_game.json"


class ExploreFailed(AssertionError):
    """각본의 기대와 다르다."""


def _tool(mcp: McpClient, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    result = mcp.call_tool(name, dict(args), timeout=180)
    if result.get("isError"):
        raise ExploreFailed(f"{name} 실패: {result['content'][0]['text']}")
    return result["structuredContent"]


def _error(mcp: McpClient, name: str, args: Mapping[str, Any]) -> dict[str, Any]:
    result = mcp.call_tool(name, dict(args), timeout=180)
    if not result.get("isError"):
        raise ExploreFailed(f"{name}이(가) 실패해야 하는데 성공했다")
    return result["structuredContent"]["error"]


def run_script(mcp: McpClient, script: Mapping[str, Any]) -> dict[str, Any]:
    """각본 하나를 끝까지. 요약(세션·저장한 키·보호 횟수·단계 기록)을 돌려준다."""
    window = str(script["window"])
    _tool(mcp, "kb_toolset_enable", {"toolsets": ["observe", "control", "screens"]})
    started = _tool(
        mcp,
        "kb_explore_start",
        {
            "title": script["title"],
            # 각본에 없으면 키를 보내지 않는다 (빈 글자는 daemon이 거부)
            **({"goal": script["goal"]} if script.get("goal") else {}),
            "window": window,
            "max_steps": int(script.get("max_steps", 200)),
        },
    )
    summary: dict[str, Any] = {
        "session": started["session"],
        "saved": [],
        "protected": 0,
        "images": 0,
        "log": [],
    }
    pending: tuple[str, Mapping[str, Any]] | None = None  # (앞 화면 키, via) — 다음 화면이 to

    def capture() -> dict[str, Any]:
        shot = mcp.call_tool("kb_screen_capture", {"window": window}, timeout=60)
        if shot.get("isError"):
            raise ExploreFailed(f"캡처 실패: {shot['content'][0]['text']}")
        if any(c.get("type") == "image" for c in shot["content"]):
            summary["images"] += 1
        return shot["structuredContent"]

    def current(frame: Mapping[str, Any]) -> str | None:
        found = _tool(mcp, "kb_screen_identify", {"frame_id": frame["frame_id"]})
        keys = [str(m.get("key") or m.get("id")) for m in found["matches"]]
        if len(keys) > 1:
            raise ExploreFailed(f"화면이 여럿으로 식별됐다: {keys}")
        return keys[0] if keys else None

    def link(to: str, frame: Mapping[str, Any]) -> None:
        nonlocal pending
        if pending is None:
            return
        source, via = pending
        pending = None
        _tool(
            mcp,
            "kb_screen_save",
            {
                "key": source,
                "frame_id": frame["frame_id"],
                "moves": [{"via": dict(via), "to": to, "status": "tried"}],
            },
        )

    for index, step in enumerate(script["steps"]):
        entry: dict[str, Any] = {"step": index}
        if "act" in step:
            _tool(mcp, str(step["act"]), {"window": window, **step.get("args", {})})
            entry["act"] = step["act"]
            if "from" in step:
                pending = (str(step["from"]), step["via"])
        elif "see" in step:
            frame = capture()
            expect = step["see"]
            entry["see"] = expect
            if expect == "protected":
                protected = frame.get("protected")
                if not protected or protected["reason"] != step.get("reason", protected["reason"]):
                    raise ExploreFailed(f"단계 {index}: 보호 중이어야 한다 ({frame})")
                summary["protected"] += 1
                if "try_save" in step:
                    # 보호 중 화면에 판정 조건을 저장하려 하면 거부 (스크린샷·crop·OCR 없음)
                    error = _error(
                        mcp,
                        "kb_screen_save",
                        {
                            "key": step["try_save"],
                            "frame_id": frame["frame_id"],
                            "detect": {"all": [{"image": [400, 205, 320, 50]}]},
                        },
                    )
                    if error["code"] != "frame_protected":
                        raise ExploreFailed(f"단계 {index}: frame_protected여야 한다 ({error})")
                    entry["save_refused"] = error["code"]
                if "save_bare" in step:
                    # 보호 중 화면: 판정 조건·스크린샷 없이 제목만 (미완성 후보 — 사람이 채운다)
                    bare = dict(step["save_bare"])
                    saved = _tool(mcp, "kb_screen_save", {"frame_id": frame["frame_id"], **bare})
                    if saved["shot"] != "omitted" or not saved.get("incomplete"):
                        raise ExploreFailed(
                            f"단계 {index}: 스크린샷 없는 미완성이어야 한다 ({saved})"
                        )
                    summary["saved"].append(str(bare["key"]))
                    link(str(bare["key"]), frame)
                    entry["incomplete"] = str(bare["key"])
            else:
                if frame.get("protected"):
                    raise ExploreFailed(f"단계 {index}: 보호 중이면 안 된다 ({frame['protected']})")
                key = str(step["key"])
                seen = current(frame)
                if expect == "new":
                    if seen is not None:
                        raise ExploreFailed(f"단계 {index}: 처음 보는 화면이어야 한다 ({seen})")
                    saved = _tool(
                        mcp,
                        "kb_screen_save",
                        {"key": key, "frame_id": frame["frame_id"], **step["save"]},
                    )
                    summary["saved"].append(key)
                    entry["shot"] = saved["shot"]
                elif seen != key:
                    raise ExploreFailed(f"단계 {index}: '{key}'여야 한다 (식별 {seen})")
                link(key, frame)
                entry["screen"] = key
        elif step.get("wait") == "change":
            for _ in range(int(step.get("max_captures", 8))):
                frame = capture()
                if frame.get("protected"):
                    continue
                if current(frame) != step["from"]:
                    break
            else:
                raise ExploreFailed(f"단계 {index}: '{step['from']}'에서 넘어가지 않았다")
        summary["log"].append(entry)
    ended = _tool(mcp, "kb_explore_end", {})
    summary["counts"] = ended["counts"]
    return summary


def main(argv: list[str] | None = None) -> int:
    from kb_testing.daemon import daemon_env

    parser = argparse.ArgumentParser(prog="python -m kb_testing.fake_explorer")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--script", default=str(DEFAULT_SCRIPT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.workspace).resolve()
    out = Path(args.out) if args.out else root / ".kookabug" / "fake-explorer"
    script = json.loads(Path(args.script).read_text(encoding="utf-8"))
    spawned = Spawned()
    try:
        # 비밀값은 daemon(그 환경)이 찾는다 — shim에는 넘기지 않는다
        with McpClient.start(spawned, root, out, env=daemon_env(out)) as mcp:
            mcp.initialize()
            summary = run_script(mcp, script)
    except ExploreFailed as exc:
        print(f"탐색 각본 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        spawned.close()
    print(json.dumps(summary, ensure_ascii=False) if args.json else f"탐색 끝: {summary['saved']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
