"""QA 노드 (M8). 실행기가 직접 처리한다 (`engine=`)."""

from typing import Any

from kookabug_sdk import Config, Context, Exit, Result, node


@node(
    type="core.qa.cheat",
    version=1,
    title="치트",
    # 에디터 분류 표(renderer palette/categories.ts)는 B7이 넓힌다 — 그 전에는 있는 분류
    category="test",
    exits=[Exit("done", "ok"), Exit("failed", "fail")],
    config={
        "cheat": Config(str, description="부를 치트 ID (knowledge/cheats.json)"),
        "args": Config(dict[str, Any], default={}, description="치트 인자 (정의된 인자만, 상수)"),
    },
    # 효과는 구현 서브그래프의 입력 노드가 선언한다 (core.graph.call과 같다)
    engine="qa_cheat",
)
def cheat(ctx: Context) -> Result:
    """채택된 치트를 부른다. 워크스페이스 치트 사용·사람 채택(정의·구현 digest)·무인 분류·루트
    테스트 `qa.cheats.allow`(서브그래프는 줄이기만)·`max_calls`·대상 프로필을 모두 통과해야 하고,
    아니면 실행 오류(`cheat_denied`·`cheat_not_adopted`)다. 통과하면 정의의 고정 템플릿에 검사한
    인자를 넣은 명령을 구현 서브그래프(`command` 입력)로 보낸다."""
    raise NotImplementedError
