"""코어 노드 기대 집합 (구현 계획 M0a 1장 표 + M1 노드). 노드 패키지·레지스트리 테스트가 쓴다."""

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

M0A_SDK_NODE_TYPES: Final = frozenset(
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

# M1 T10: 앱·창·입력 (MVP 노드 목록 3·6장)
M1_APP_WINDOW_INPUT_NODE_TYPES: Final = frozenset(
    {
        "core.app.launch",
        "core.app.close",
        "core.window.attach",
        "core.window.set_current",
        "core.window.set_size",
        "core.input.click",
        "core.input.drag",
        "core.input.scroll",
        "core.input.key",
        "core.input.type_text",
    }
)

SDK_NODE_TYPES: Final = M0A_SDK_NODE_TYPES | M1_APP_WINDOW_INPUT_NODE_TYPES

CORE_NODE_TYPES: Final = ENGINE_NODE_TYPES | SDK_NODE_TYPES

# kookabug_nodes의 [tool.kookabug].modules와 같아야 한다 (설치된 wheel에는 pyproject가 없어서
# 레지스트리는 kookabug_nodes.MODULES를 읽는다). 일치는 test_modules_list_matches_pyproject가 본다
CORE_NODE_MODULES: Final = (
    "kookabug_nodes.graph",
    "kookabug_nodes.test",
    "kookabug_nodes.flow",
    "kookabug_nodes.values",
    "kookabug_nodes.log",
    "kookabug_nodes.app",
    "kookabug_nodes.window",
    "kookabug_nodes.input",
)
