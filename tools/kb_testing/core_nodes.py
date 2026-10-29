"""M0a 코어 노드 기대 집합 (구현 계획 M0a 1장 표). 노드 패키지·레지스트리 테스트가 같이 쓴다."""

from typing import Final

ENGINE_NODE_TYPES: Final = frozenset(
    {
        "core.graph.entry",
        "core.graph.exit",
        "core.graph.call",
        "core.test.pass",
        "core.test.fail",
        "core.test.skip",
        "core.flow.repeat",
        "core.flow.while",
    }
)

SDK_NODE_TYPES: Final = frozenset(
    {
        "core.assert.compare",
        "core.flow.branch",
        "core.flow.delay",
        "core.var.set",
        "core.var.get",
        "core.logic.compare",
        "core.text.format",
        "core.log.message",
    }
)

CORE_NODE_TYPES: Final = ENGINE_NODE_TYPES | SDK_NODE_TYPES

# kookabug_nodes의 [tool.kookabug].modules와 같아야 한다 (설치된 wheel에는 pyproject가 없어서
# 레지스트리는 kookabug_nodes.MODULES를 읽는다). 일치는 test_modules_list_matches_pyproject가 본다
CORE_NODE_MODULES: Final = (
    "kookabug_nodes.graph",
    "kookabug_nodes.test",
    "kookabug_nodes.flow",
    "kookabug_nodes.values",
    "kookabug_nodes.log",
)
