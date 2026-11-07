"""화면 지도 e2e 준비 (M7 계획 3.13·B5): 실제 탐색 결과를 만든다 — 결과물을 미리 쓰지 않는다.

    python -X utf8 explore_world.py <폴더>

1. 가짜 예제 게임(상태 유지·확정 화면 없음) + 같은 프로세스 daemon + 실제 `kookabug mcp`로 가짜
   탐색 에이전트 각본(`kb_testing.fake_explorer` 기본 각본)을 끝까지 돈다
   → `screens/_explored/<세션 1>/` 7화면
2. 사람이 CLI로 하듯 `title` 후보를 확정 화면으로 옮긴다 (`kookabug_core.screen_promote` — CLI와
   같은 거래)
3. 다시 탐색(세션 2): 실제 MCP로 타이틀을 캡처해 식별(아는 화면)하고 `of: "title"` 합치기 후보를
   저장한다

결과 JSON 한 줄: {"workspace", "sessions": [세션 1, 세션 2], "saved": [...]}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(REPO / "tools"), str(REPO / "python" / "kookabug_core" / "tests")]

from helpers.cli import cli_env  # noqa: E402

from kb_testing.daemon import daemon_env  # noqa: E402
from kb_testing.fake_explorer import DEFAULT_SCRIPT, ExploreFailed, run_script  # noqa: E402
from kb_testing.fake_game import START_BUTTON, make_fake_game  # noqa: E402
from kb_testing.mcp_client import McpClient  # noqa: E402
from kb_testing.proc import Spawned  # noqa: E402
from kookabug_core.screen_promote import PromoteRequest, check, promote  # noqa: E402

SECRETS = {"KOOKABUG_SECRET_ACC_ID": "qa_tester_01", "KOOKABUG_SECRET_ACC_PW": "sample-pass-01"}
"""예제 게임 로그인 값 (공개 예제 — 검사에서는 비밀값으로 넣는다)."""


def tool(mcp: McpClient, name: str, args: dict[str, object]) -> dict[str, object]:
    result = mcp.call_tool(name, args, timeout=180)
    if result.get("isError"):
        raise ExploreFailed(f"{name} 실패: {result['content'][0]['text']}")
    return result["structuredContent"]


def main() -> int:
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.environ.update(SECRETS)
    os.environ.setdefault("KOOKABUG_OCR_MODELS", str(REPO / "build" / "ocr-models"))
    game = make_fake_game(out, screens=False)
    env = cli_env(out, None, **SECRETS)
    env["KOOKABUG_USER_CONFIG_DIR"] = str(out / "user")
    script = json.loads(DEFAULT_SCRIPT.read_text(encoding="utf-8"))
    spawned = Spawned()
    try:
        with game.daemon(env):
            mcp = McpClient.start(spawned, game.root, out / "mcp1", env=daemon_env(out))
            try:
                mcp.initialize()
                summary = run_script(mcp, script)
            finally:
                mcp.close()
            first = str(summary["session"])
            # 2) 사람이 title 후보를 확정 화면으로 옮긴다 (CLI와 같은 잠금·거래)
            request = PromoteRequest(first, "title")
            checked = check(game.root, request)
            if not checked["ok"]:
                raise ExploreFailed(f"title 승격 확인 실패: {checked['problems']}")
            promote(game.root, PromoteRequest(first, "title", base_revisions=checked["revisions"]))
            # 3) 다시 탐색: 게임을 처음 화면으로 되돌리고(상태 파일 없음 = 장면 표의 start),
            #    타이틀은 이제 아는 화면 — 합치기 후보로 이동 하나를 더한다
            game.state_file.unlink(missing_ok=True)
            mcp = McpClient.start(spawned, game.root, out / "mcp2", env=daemon_env(out))
            try:
                mcp.initialize()
                window = str(script["window"])
                tool(mcp, "kb_toolset_enable", {"toolsets": ["observe", "control", "screens"]})
                second = str(
                    tool(mcp, "kb_explore_start", {"title": "타이틀 다시 보기", "window": window})[
                        "session"
                    ]
                )
                shot = mcp.call_tool("kb_screen_capture", {"window": window}, timeout=60)
                frame = shot["structuredContent"]
                found = tool(mcp, "kb_screen_identify", {"frame_id": frame["frame_id"]})
                if [m.get("id") for m in found["matches"]] != ["title"]:  # type: ignore[union-attr]
                    raise ExploreFailed(f"타이틀이 아는 화면으로 식별되지 않았다: {found}")
                x, y = START_BUTTON
                tool(
                    mcp,
                    "kb_screen_save",
                    {
                        "key": "title_again",
                        "frame_id": frame["frame_id"],
                        "of": "title",
                        "title": "타이틀 (다시 보기)",
                        "elements": [
                            {
                                "name": "도움말",
                                "kind": "button",
                                "rect": [x - 100, y + 120, 200, 40],
                            }
                        ],
                        "moves": [
                            {
                                "via": {"click": {"element": "도움말"}},
                                "to": None,
                                "status": "untried",
                                "note": "도움말 창",
                            }
                        ],
                    },
                )
                tool(mcp, "kb_explore_end", {})
            finally:
                mcp.close()
    except ExploreFailed as exc:
        print(f"탐색 준비 실패: {exc}", file=sys.stderr)
        return 1
    finally:
        spawned.close()
    print(
        json.dumps(
            {"workspace": str(game.root), "sessions": [first, second], "saved": summary["saved"]},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
