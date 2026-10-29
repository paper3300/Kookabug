"""테스트 전용 플러그인 `testkit` (배포하지 않는다).

- `testkit.observe.wait`: 가짜 캡처 프레임을 보는 관측 노드 (`effects={"capture"}`, 관측 재시도)
- `testkit.input.tap`: 가짜 입력 (`effects={"input"}`)
- `testkit.boom`: 예외 → error
- `testkit.fail_once`: 입력 `exit`로 정한 출구로 나간다 (출구 연결 시나리오용)
- `testkit.flow.choose`: `DynamicExits` + 기본값 있는 config (`exits`, 기본 `["done"]`)

그래프의 `plugins`에 `"testkit"`을 넣고 `registry_with_testkit()`으로 검증·실행한다.
"""

from kookabug_core.registry import Registry, default_registry
from testkit.nodes import NODES, PLUGIN_ID, PLUGIN_VERSION

__all__ = ["NODES", "PLUGIN_ID", "PLUGIN_VERSION", "registry_with_testkit"]


def registry_with_testkit() -> Registry:
    """코어 노드 + testkit."""
    registry = default_registry()
    registry.add_functions(PLUGIN_ID, PLUGIN_VERSION, NODES)
    return registry
