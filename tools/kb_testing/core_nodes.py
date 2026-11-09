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
        # M8 B2: 치트 (구현 서브그래프를 실행기가 부른다)
        "core.qa.cheat",
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

# M1 T11: 화면·이미지·검증·OCR (MVP 노드 목록 2·4·5장)
M1_OBSERVE_NODE_TYPES: Final = frozenset(
    {
        "core.image.wait",
        "core.image.wait_any",
        "core.image.wait_gone",
        "core.image.click",
        "core.screen.wait_stable",
        "core.screen.capture",
        "core.assert.visible",
        "core.assert.not_visible",
        "core.assert.text",
        "core.ocr.read",
        "core.ocr.wait_text",
        "core.ocr.click_text",
    }
)

M1_NODE_TYPES: Final = M1_APP_WINDOW_INPUT_NODE_TYPES | M1_OBSERVE_NODE_TYPES
"""M1 노드 22개 (구현 계획 M1 1장)."""

# 다듬기 P1: 산술 (MVP 노드 목록 8장, 사용자 결정 G17)
P1_VALUE_NODE_TYPES: Final = frozenset({"core.math.calc", "core.var.add"})

# M5 B4: Agent 판단 (MVP 노드 목록 10장)
M5_AGENT_NODE_TYPES: Final = frozenset({"core.agent.cli_judge", "core.agent.api_judge"})

SDK_NODE_TYPES: Final = (
    M0A_SDK_NODE_TYPES | M1_NODE_TYPES | P1_VALUE_NODE_TYPES | M5_AGENT_NODE_TYPES
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
    "kookabug_nodes.app",
    "kookabug_nodes.window",
    "kookabug_nodes.input",
    "kookabug_nodes.image",
    "kookabug_nodes.screen",
    "kookabug_nodes.assert_",
    "kookabug_nodes.ocr",
    "kookabug_nodes.agent",
    "kookabug_nodes.qa",
)
