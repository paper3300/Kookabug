"""화면 검사: 서브그래프 출구의 `screen`이 `screens/`의 화면 하나를 가리키는지 (M1 2.10).

- 없는 화면 ID → 경고 `screen_unknown` (화면 지도용 정보라 실행은 막지 않는다)
- 같은 ID의 파일이 둘 이상 → 오류 `screen_ambiguous`
- 화면 파일 형식이 틀렸거나 그 target을 쓸 수 없음 → 경고 `screen_invalid`

화면 파일 찾기·읽기는 로더가 한다(`Program.screens`). 실행 중 화면 판정으로 실행을 바꾸지 않는다.
"""

from __future__ import annotations

from kookabug_core.diagnostics import json_pointer
from kookabug_core.loader import exit_screens
from kookabug_core.validate.context import ValidationContext

__all__ = ["check"]


def check(ctx: ValidationContext) -> None:
    for graph in ctx.graphs():
        for exit_name, screen_id in exit_screens(graph):
            found = ctx.program.screens.get(screen_id)
            if found is None or found.status == "ok":
                continue
            pointer = json_pointer("interface", "exits", exit_name, "screen")
            where = f"출구 '{exit_name}'의 화면 '{screen_id}'"
            match found.status:
                case "unknown":
                    message = f"{where}이(가) screens/에 없다 (_explored/는 보지 않는다)"
                    ctx.report("screen_unknown", message, graph, pointer=pointer)
                case "ambiguous":
                    paths = ", ".join(found.paths)
                    message = f"{where} 파일이 여러 개다: {paths}. 파일 이름(화면 ID)을 다르게"
                    ctx.report("screen_ambiguous", message, graph, pointer=pointer)
                case "invalid":
                    ctx.report(
                        "screen_invalid", f"{where}: {found.problem}", graph, pointer=pointer
                    )
