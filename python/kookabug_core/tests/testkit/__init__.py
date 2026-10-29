"""테스트 전용 플러그인 `testkit` (배포하지 않는다).

- `testkit.observe.wait`: 가짜 캡처 프레임을 보는 관측 노드 (`effects={"capture"}`, 관측 재시도)
- `testkit.observe.flaky`: 부를 때마다 `script`의 다음 결과(`found`·`timeout`·`missing`·`boom`)를
  내는 관측 노드 (재시도 출구 `timeout`·`missing`, 재시도 시나리오용)
- `testkit.observe.consume`: 받은 중첩 목록을 `SEEN`에 남기고 고친다. 첫 호출 `timeout`, 그 뒤
  `found` (재시도 입력 복사 확인용)
- `testkit.observe.wait_any`: 여러 프레임 중 먼저 보이는 것으로 분기 (`config.exits` 동적 출구 +
  `timeout`, 모든 동적 출구가 `match`를 준다. 문서의 `core.image.wait_any` 자리)
- `testkit.read_text`: `text`(string)를 주는 `done` / 출력 없는 `unreadable`(fail)
- `testkit.input.tap`: 가짜 입력 (`effects={"input"}`)
- `testkit.input.sneak`: `effects` 선언 없이 입력 (→ error)
- `testkit.boom`: 예외 → error
- `testkit.fail_once`: 입력 `exit`로 정한 출구로 나간다 (출구 연결 시나리오용)
- `testkit.flow.choose`: `DynamicExits` + 기본값 있는 config (`exits`, 기본 `["done"]`)
- `testkit.config_value`: `ctx.config["n"]`(기본 3)을 출력 (config 기본값 확인용)
- `testkit.mutate`: 받은 목록을 안쪽까지 고쳐 출력 (입력 복사 확인용)
- `testkit.shot`: 캡처·`ctx.artifacts.save`·예외를 골라 하는 노드, `value`(any)로 비밀값 입력 스텝을
  만든다 (기록 정책 확인용)
- `testkit.pure.count`: 계산될 때마다 `COUNTS[key]`를 올리는 순수 노드 (계산 횟수 확인용)
- `testkit.pure.capture`·`testkit.pure.log`: 금지된 ctx 기능을 쓰는 순수 노드 (→ error)

프로세스 시나리오용 (워커가 `--plugin-module testkit.nodes`로 실행한다, 구현 계획 M0b 2.12):

- `testkit.block`: 로그 `blocking` 뒤 취소될 때까지 `ctx.check_cancel`·`ctx.sleep(10)` 반복
- `testkit.gate`: 로그 `gate` 뒤 신호 파일이 생길 때까지 협력 대기 (정상으로 끝날 수 있다)
- `testkit.hang`: `ctx` 없이 무한 루프 (`hold_gil`이면 GIL을 쥔 채 멈춘다)
- `testkit.input.hold`: `ctx.input.key` 한 번 (가짜 백엔드 훅과 함께 "키를 누른 채 멈춤")
- `testkit.ctx_roundtrip`: 캡처·변수·기록·저장·설정 왕복, `print()`
- `testkit.read_file`: `ctx.path(rel)`로 읽어 출력
- `testkit.crash`: `os._exit(code)`
- `testkit.ctx_sneak`·`testkit.ctx_replay`·`testkit.liar`: SDK 제한·실행 번호·결과 대조를 건너뛰는
  "믿을 수 없는 워커" 흉내

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
