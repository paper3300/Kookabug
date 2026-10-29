# MVP 노드 목록

- 작성일: 2026-10-29
- 상태: 확정 (추천안대로)
- 근거: [[결정 현황]], [[그래프 JSON 스키마 v0]], [[벤치마킹 - 다른 툴에서 흡수할 것]]

---

## 기준

- 코어는 **외부 매크로**만 다룬다: 창, 캡처, 이미지 인식, OCR, 마우스·키 입력. 엔진 연동은 플러그인이다
- **녹화 결과가 그대로 이 노드들로 바뀌어야 한다**. 녹화가 만드는 노드는 아래 "녹화 변환"을 참고한다
- 대기는 "나타날 때까지 대기"가 기본이다. 고정 지연 노드(`core.flow.delay`)에는 경고 배지를 단다
- 비슷한 노드를 여러 개 만들기보다 입력 옵션으로 묶는다. 예: 숫자 읽기는 `core.ocr.read`의 `parse` 옵션
- 타입 이름은 `<플러그인>.<분류>.<동작>`. 코어 플러그인 ID는 `core`
- 출구 표기: **굵게** = `ok`, 그냥 = `fail`. `error`(노드 고장)는 출구가 아니라 전파된다

## 공통 입력

| 입력 | 뜻 |
|---|---|
| `window` | 이 노드만 다른 창을 대상으로 한다 (기본: 현재 대상 창). 모든 exec 노드가 가질 수 있고 노드 스키마에 따로 적지 않는다 (M1) |
| `timeout_ms` | 기다리는 노드의 제한 시간. 노드마다 기본값이 있고 무제한은 없다. **기다리는 노드만** 함수 인자로 선언한다 (노드 스키마에 있음). 선언하지 않은 노드에 주면 실행 전 검증 오류(`unknown_input`) |

---

## 1. 그래프

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.graph.entry` | 그래프 시작점. 서브그래프면 `interface.inputs`가 출력 핀이 된다 | | 입력값들 | **start** |
| `core.graph.exit` | 서브그래프 공개 출구 | `config.exit`, 출력값들 | | |
| `core.graph.call` | 서브그래프 호출 | `config.graph`, 서브그래프 입력 | 서브그래프 출력 | 서브그래프 `exits` |

## 2. 테스트 판정

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.test.pass` | 테스트 성공으로 끝냄 (테스트 전용) | `reason` | | |
| `core.test.fail` | 테스트 실패로 끝냄 (테스트 전용) | `reason` | | |
| `core.test.skip` | 테스트 건너뜀으로 끝냄 (테스트 전용) | `reason` | | |
| `core.assert.visible` | 대상이 보이는지 검증 | `target` | `match` | **ok**, fail |
| `core.assert.not_visible` | 대상이 안 보이는지 검증 | `target` | | **ok**, fail |
| `core.assert.text` | OCR 문구 검증 | `region`, `equals` / `contains` / `regex` | `text` | **ok**, fail |
| `core.assert.compare` | 값 비교 검증 (예: 구매 후 골드가 줄었는지). `op`는 `core.logic.compare`와 같다 (8장) | `a`, `op`, `b` | | **ok**, fail |

`core.test.*`의 `reason`은 `string|secret`이다 (생략 가능). 비밀값이 든 사유(`core.text.format` 결과 등)도 받고, 판정 사유와 실행 기록에는 가린 값(`***`)만 남는다. 받는 값만 넓힌 것이라 노드 `version`은 1 그대로다.

## 3. 앱·창

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.app.launch` | 실행 파일을 띄우고 창을 잡아 현재 대상 창으로 정함 | `path`, `args`, `window_title` | `window`, `process` | **attached**, timeout |
| `core.app.close` | 프로세스 종료 (정상 종료 후 시간 초과면 강제) | `process`, `force_after_ms` | | **closed**, timeout |
| `core.window.attach` | 이미 떠 있는 창을 찾아 현재 대상 창으로 정함 | `title` / `process_name` | `window` | **found**, not_found |
| `core.window.set_current` | 현재 대상 창을 바꿈 (호출 프레임 단위) | `window` | | **done** |
| `core.window.set_size` | 클라이언트 영역 크기 맞춤. 녹화 해상도와 맞출 때 | `client_size` | | **done**, fail |

## 4. 화면·이미지

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.image.wait` | 대상이 나타날 때까지 대기 | `target` | `match` | **found**, timeout |
| `core.image.wait_any` | 여러 대상 중 먼저 보이는 것으로 분기. 동시에 보이면 `config.exits` 앞쪽 | `config.exits`, `targets` | `match` | 각 출구, timeout |
| `core.image.wait_gone` | 대상이 사라질 때까지 대기 (로딩 표시 등) | `target` | | **gone**, timeout |
| `core.image.click` | 대기 + 클릭을 한 번에. 녹화 결과 대부분이 이 노드 | `target`, `button`, `count` | `match` | **done**, not_found |
| `core.screen.wait_stable` | 화면이 멈출 때까지 대기 (애니메이션 끝) | `region`, `stable_ms` | | **stable**, timeout |
| `core.screen.capture` | 스크린샷을 기록에 남김 | `region`, `name` | `image` | **done** |

## 5. OCR

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.ocr.read` | 영역의 글자 읽기. `parse: number`면 숫자로 | `region`, `parse` | `text`, `number`, `confidence` | **done**, unreadable |
| `core.ocr.wait_text` | 문구가 나타날 때까지 대기 | `region`, `contains` / `regex` | `text`, `match` | **found**, timeout |
| `core.ocr.click_text` | 문구를 찾아 클릭 | `region`, `text` | `match` | **done**, not_found |

`confidence`는 엔진이 주지 않으면 `null`이다 (Windows OCR은 주지 않음). 엔진마다 척도가 달라서 엔진끼리 비교하지 않는다.

`region`은 찾기 대상(`$target`) 또는 정규화 사각형. 기준 요소 옆을 읽는 Anchor 방식은 target 파일의 옵션으로 둔다.

## 6. 입력

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.input.click` | 매칭 결과나 좌표를 클릭 | `match` / `point`, `button`, `count` | | **done** |
| `core.input.drag` | 끌기 | `from`, `to`, `duration_ms` | | **done** |
| `core.input.scroll` | 휠 | `point`, `amount` | | **done** |
| `core.input.key` | 키 입력·조합·누르고 있기 | `keys`, `hold_ms` | | **done** |
| `core.input.type_text` | 글자 입력 | `target`, `text`, `clear` | | **done** |

입력 노드는 입력 직전에 대상 창이 유효한지, 포그라운드인지 확인한다. 실패하면 `error`다.

## 7. 흐름

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.flow.branch` | 참·거짓 분기 | `condition` | | **true**, **false** |
| `core.flow.repeat` | 정해진 횟수 반복 | `times` | `index` | **body**, **done** |
| `core.flow.while` | 조건이 참인 동안 반복. 횟수 한도 필수 | `condition`, `max_iterations` | `index` | **body**, **done**, limit |
| `core.flow.delay` | 고정 지연. 경고 배지 | `ms` | | **done** |

- `repeat`의 `times`는 0 이상(0이면 바로 `done`), `while`의 `max_iterations`는 1 이상이고 필수다
- `index`(0부터)는 `body` 출구만 주는 출력이다. 그래서 반복 범위 밖(`done` 이후)에서는 읽을 수 없다

재시도는 노드가 아니라 노드 설정(`config.retry`)이다. MVP는 관측 재시도만 한다 → [[그래프 JSON 스키마 v0]] 6장. 대기·OCR 계열(`wait`, `wait_any`, `wait_gone`, `wait_stable`, `ocr.read`, `ocr.wait_text`, `assert.visible`·`not_visible`·`text`)이 `retry.mode: observation`이고, 입력·실행 노드와 `image.click`·`ocr.click_text`는 `never`다. `assert.compare`도 `never`다: 입력은 스텝 시작 때 한 번만 계산하므로 다시 해도 결과가 같다.

## 8. 값

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.var.set` | 그래프 변수에 저장 (호출 프레임 안에서만) | `name`, `value` | | **done** |
| `core.var.get` | 그래프 변수 읽기 (exec 없는 순수 노드) | `name`, `default` | `value` | |
| `core.logic.compare` | 비교 (exec 없는 순수 노드) | `a`, `op`, `b` | `result` | |
| `core.text.format` | 문자열 조합 (exec 없는 순수 노드) | `template`, `values` | `text` | |

순수 노드는 exec 핀이 없고, 값이 필요할 때 계산한다 (Unreal 순수 노드). 부작용이 없어야 한다. 평가 시점과 반복 규칙은 [[그래프 JSON 스키마 v0]] 7장.

- `var.get`: 변수가 없으면 `default`를 준다. `in`에 `default` 키가 **없을 때만** "기본값 없음"이라 `error`다. `"default": null`은 기본값 `null`을 준 것이므로 `null`을 돌려준다 (키 없음과 `null`을 구분. 노드 스키마의 `optional` 입력). 같은 그래프에 그 이름을 상수로 정하는 `var.set`이 없으면 실행 전 검증 경고
- `compare`의 `op`: `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`
  - `==`·`!=`는 JSON 값으로 비교한다. 타입이 다르면 다른 값이다 (`true`와 `1`은 다르고, `1`과 `1.0`은 같다)
  - 대소 비교는 숫자끼리·문자열끼리만 된다. 다른 타입끼리는 `error`
  - `contains`: `a`가 문자열이면 `b`(문자열)가 들어 있는지, `a`가 목록이면 `b`와 같은 원소가 있는지. 그 외는 `error`
- `text.format`: `template`의 `{이름}`을 `values`(`dict[str,any]`)의 값으로 바꾼다. `{{`·`}}`는 중괄호 자체
  - 자리 표시는 `{이름}`만 된다. 속성·인덱스 접근(`{a.b}`, `{a[0]}`)·형식 지정(`{a:>3}`, 빈 지정자 `{a:}`, `{a!r}`)·빈 `{}`·짝 없는 중괄호·`values`에 없는 이름은 `error`
  - 문자열이 아닌 값은 JSON 표기로 넣는다 (`true`, `null`, `[1, 2]`)
  - `values` 중 하나라도 비밀값이면 결과 `text`도 비밀값이다. 그래서 출력 타입은 `string|secret`

## 9. 기록

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.log.message` | 실행 기록에 메시지 남김 | `level`, `text` | | **done** |

`level`은 `info`(기본)·`warn`·`error`. `text`는 `string|secret`이고 비밀값은 가려서 남긴다.

## 10. Agent

결정 사항대로 외부 CLI 방식과 API 키 방식을 **다른 노드 종류**로 만든다. MVP는 "판단"만 한다. 게임을 직접 조작하는 Agent 노드(성공 궤적 캐시·재생, 결정적 노드로 굳히기)는 이후 버전에서 다룬다.

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.agent.cli_judge` | 외부 에이전트 CLI에 스크린샷과 질문을 주고, 정해진 선택지 중 하나를 고르게 함 | `config.choices`, `prompt`, `image` | `answer`, `reason` | 각 선택지, unsure |
| `core.agent.api_judge` | 같은 일을 API 키로 직접 모델 호출 | `config.choices`, `prompt`, `image`, `model` | `answer`, `reason` | 각 선택지, unsure |

- 선택지는 `config.choices` 배열이고 그대로 출구가 된다 (`wait_any`와 같은 방식)
- 프롬프트·응답·이미지는 실행 기록에 남긴다. 결정적이지 않으므로 노드에 배지를 단다

---

## 녹화 변환

| 사람 동작 | 만들어지는 노드 |
|---|---|
| 클릭 | `core.image.click` (클릭 지점 주변을 잘라 target 생성) |
| 클릭 전 화면이 바뀌기를 기다림 | `core.image.wait` 또는 `core.screen.wait_stable` |
| 끌기 | `core.image.wait` + `core.input.drag` |
| 휠 | `core.input.scroll` |
| 키·조합키 | `core.input.key` |
| 글자 입력 | `core.input.type_text` |
| 녹화 중 "검증 넣기" | `core.assert.visible` / `core.assert.text` |

## MVP에서 뺀 것

- 여러 개 찾기(`find_all`, 개수 세기), 색 판정, 템플릿 이외 특징점 매칭 단독 노드
- switch(여러 갈래 문자열 분기). `wait_any`와 `branch`로 대신한다
- 파일·HTTP·DB 노드. 플러그인으로 만든다
- try/catch, 병렬 실행
- 게임을 직접 조작하는 Agent 노드
