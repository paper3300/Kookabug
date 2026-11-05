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
| `window` | 이 노드만 다른 창을 대상으로 한다 (기본: 현재 대상 창). 모든 exec 노드가 가질 수 있고 노드 스키마에 따로 적지 않는다 (M1). 아래 규칙 |
| `timeout_ms` | 기다리는 노드의 제한 시간. 노드마다 기본값이 있고 무제한은 없다. **기다리는 노드만** 함수 인자로 선언한다 (노드 스키마에 있음). 선언하지 않은 노드에 주면 실행 전 검증 오류(`unknown_input`) |

공통 입력 `window`의 규칙

- 받는 노드: exec 노드 전부(실행기가 직접 처리하는 `core.graph.*`·`core.test.*`·`core.flow.repeat`·`while` 포함). 순수 노드는 exec가 없어 받지 않는다(`unknown_input`). 그 노드의 입력에 이미 `window`가 있으면(노드 스키마가 직접 선언한 `core.window.set_current`, `window`라는 서브그래프 입력) 그 입력이 그 노드의 `window`다
- 타입은 `window`, 생략할 수 있고 `null`이면 현재 대상 창이다. 연결·상수 검사는 다른 `window` 핀과 같다
- 바뀌는 것은 **그 스텝**의 `ctx.window`와 그 스텝이 낸 입력 요청의 대상 창뿐이다. 호출 프레임의 현재 대상 창은 그대로다(바꾸려면 `core.window.set_current`)
- `core.graph.call`에 주면 서브그래프가 부른 쪽의 현재 대상 창 대신 그 창을 이어받는다 (서브그래프 안에서만, 부른 쪽 창은 그대로)

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

- 화면 검증(`visible`·`not_visible`·`text`)은 바로 바뀌지 않는 화면을 위해 `timeout_ms`(기본 5초) 동안 다시 보고, 그 안에 한 번이라도 맞으면 `ok`, 아니면 `fail`이다. `timeout_ms: 0`이면 지금 화면을 한 번만 본다
- `assert.text`는 `equals`(앞뒤 공백 무시 같음)·`contains`·`regex` 중 하나. `text`(마지막으로 읽은 글자)는 `fail`에서도 준다. 민감 target 영역이면 `text`는 비밀값이고, 실패 메시지의 읽은 글자는 워크스페이스 `record.redact_secrets`가 켜져 있으면 가린 값(`***`), 기본(꺼짐)은 원문이다(`assert.compare`·`ocr.read`의 메시지도 같다)

`core.test.*`의 `reason`은 `string|secret`이다 (생략 가능). 비밀값이 든 사유(`core.text.format` 결과 등)도 받는다. 워크스페이스 `record.redact_secrets`가 켜져 있으면 판정 사유와 실행 기록에 가린 값(`***`)만 남고, 기본(꺼짐)은 원문이 남는다. 받는 값만 넓힌 것이라 노드 `version`은 1 그대로다.

## 3. 앱·창

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.app.launch` | 실행 파일을 띄우고 창을 잡아 현재 대상 창으로 정함 | `path`, `args`, `window_title`, `cwd` | `window`, `process` | **attached**, timeout |
| `core.app.close` | 프로세스 종료 (정상 종료 후 시간 초과면 강제) | `process`, `force_after_ms` | | **closed**, timeout |
| `core.window.attach` | 이미 떠 있는 창을 찾아 현재 대상 창으로 정함 | `title` / `process_name`, `owned` | `window` | **found**, not_found |
| `core.window.set_current` | 현재 대상 창을 바꿈 (호출 프레임 단위) | `window` | | **done** |
| `core.window.set_size` | 클라이언트 영역 크기 맞춤. 녹화 해상도와 맞출 때 | `client_size` | | **done**, fail |

- `launch`는 런처가 띄운 아래 프로세스의 창까지 `timeout_ms`(기본 30초) 기다린다. `timeout`으로 나가도 `process`는 준다(그래프가 닫을 수 있게). 띄운 게임은 실행 Job 안이라 실행이 끝나면 같이 정리된다
- `close`는 창에 닫기를 보내고 `force_after_ms`(기본 5초) 안에 끝나지 않으면 강제로 끝내고 `timeout`으로 나간다
- `attach`는 기본으로 소유자 없는 창만 찾는다. 대화 상자 같은 소유 팝업을 대상 창으로 삼으려면 `owned: true`
- `launch`·`attach`·`set_current`는 창을 정한 직후 한 번 앞으로 가져온다(최선 노력). 입력 노드는 가져오지 않는다
- 실행에서 현재 창이 **처음** 정해질 때(위 노드든 플러그인 노드의 `ctx.set_window`든)는 실행기가 그 창을 앞으로 가져온다. 다른 프로그램이 포그라운드를 쥐고 있어도(포그라운드 잠금) `AttachThreadInput`, 그래도 안 되면 Alt 누르기·떼기로 잠금을 푼다 — Alt는 입력 임대권을 가진 실행(입력 노드가 있는 그래프)에서 입력 액터로만 넣고(기록·복구 포함), Alt가 이미 눌려 있으면 넣지 않는다. 그 뒤의 창 전환은 입력 없이 최선 노력이다. 못 가져오면 실행을 막지 않고 `warn` 로그(`foreground_not_acquired: …`)를 남긴다. 실행 **도중** 포커스를 잃은 창은 다시 가져오지 않는다 — 키보드 입력 노드가 `window_not_foreground` 오류다
- `set_size`의 `client_size`는 `[너비, 높이]`(물리 픽셀)이고 대상은 그 스텝의 창이다

## 4. 화면·이미지

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.image.wait` | 대상이 나타날 때까지 대기 | `target` | `match` | **found**, timeout |
| `core.image.wait_any` | 여러 대상 중 먼저 보이는 것으로 분기. 동시에 보이면 `config.exits` 앞쪽 | `config.exits`, `targets` | `match` | 각 출구, timeout |
| `core.image.wait_gone` | 대상이 사라질 때까지 대기 (로딩 표시 등) | `target` | | **gone**, timeout |
| `core.image.click` | 대기 + 클릭을 한 번에. 녹화 결과 대부분이 이 노드 | `target`, `button`, `count` | `match` | **done**, not_found |
| `core.screen.wait_stable` | 화면이 멈출 때까지 대기 (애니메이션 끝) | `region`, `stable_ms`, `tolerance` | | **stable**, timeout |
| `core.screen.capture` | 스크린샷을 기록에 남김 | `region`, `name` | `image` | **done** |

- 기다리는 노드는 `timeout_ms` 동안 100 ms 간격으로 캡처해 보고, 그 안에 못 찾으면 마지막으로 본 프레임을 `steps/<스텝>_timeout`(`click`은 `_not_found`)으로 남긴다. 화면이 멈춰 있으면 같은 프레임을 다시 보는 것이라 오류가 아니다 — `timeout_ms` 안에 `timeout`으로 끝난다. `timeout_ms: 0`이면 기다리지 않고 지금 화면을 한 번 본다
- `wait_any`의 `targets`는 `config.exits`와 같은 이름들이다(다르면 `error`). 한 프레임에 여럿이 보이면 `config.exits` 앞쪽
- `wait_gone`은 처음부터 없으면 바로 `gone`
- `image.click`은 `timeout_ms`(기본 10초) 동안 기다렸다가 target의 클릭 지점을 누른다. `button`·`count`는 `core.input.click`과 같다. 못 찾으면 입력하지 않고 `not_found`
- `wait_stable`: 연속한 두 관측의 차이(채널 평균 절대 차이 / 255)가 `tolerance`(기본 0.001) 이하인 상태가 `stable_ms`(기본 500) 동안 이어지면 `stable`. 1024x640 화면에서 버튼 한 줄의 강조가 바뀌는 정도가 약 0.006이다. 작은 깜박임까지 무시하려면 `region`을 좁힌다
- `region`(`wait_stable`·`capture`)은 사각형 `[x, y, w, h]`(클라이언트 픽셀 — 창 크기·DPI에 따라 바뀌지 않는다. [[그래프 JSON 스키마 v0]] 1장 "상수"). `wait_stable`은 영역이 지금 화면과 겹치지 않으면(창이 작아진 뒤 포함) 멈춘 것으로 보지 않고 `error`(지금 클라이언트 크기와 영역을 메시지에)다. `capture`는 `steps/<스텝>_<name>.png`로 남기고(기록 정책이 막으면 생략) 이미지를 낸다

## 5. OCR

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.ocr.read` | 영역의 글자 읽기. `parse: number`면 숫자로 | `region`, `parse` | `text`, `number`, `confidence` | **done**, unreadable |
| `core.ocr.wait_text` | 문구가 나타날 때까지 대기 | `region`, `contains` / `regex` | `text`, `match` | **found**, timeout |
| `core.ocr.click_text` | 문구를 찾아 클릭 | `region`, `text`, `button` | `match` | **done**, not_found |

- `wait_text`는 `contains`(부분 일치)·`regex`(검색) 중 하나. `match`는 그 문구가 있는 글자 상자(한 줄에 걸치면 그 줄, 여러 줄이면 전부를 덮는 상자)다
- `click_text`는 `timeout_ms`(기본 10초) 동안 `text`가 든 글자 상자를 기다렸다가 그 가운데를 누른다. 못 찾으면 입력하지 않고 `not_found`. OCR이 낸 `match`(`wait_text`·`click_text`)는 영역 종류(target·사각형·전체)와 무관하게 읽은 캡처의 관측(창·캡처 방식·클라이언트 크기·DPI)을 실어, 입력 직전 재검증이 그 뒤의 창 크기·DPI 변화를 알아본다. 다시 찾을 target이 없으므로 바뀌었으면 옛 좌표를 누르지 않고 `stale_observation`이다. 사각형 영역이 지금 화면과 겹치지 않으면 OCR 노드도 `error`다
- `read`는 기다리지 않는다(관측 한 번). 스텝의 마지막 OCR 글자는 실행 기록에 `steps/<스텝>_ocr.txt`로 남는다

`confidence`는 엔진이 주지 않으면 `null`이다 (Windows OCR은 주지 않음). 엔진마다 척도가 달라서 엔진끼리 비교하지 않는다. RapidOCR은 읽은 글자 상자들의 점수 평균(0~1)이고, 글자가 하나도 없으면 `null`이다.

`text`는 같은 높이에 있는 글자 상자들을 왼쪽부터 띄어 이은 줄을 위에서부터 줄바꿈(`\n`)으로 이은 것이다. 검출이 한글 낱말을 글자마다 나눈 경우(상자가 맞닿고 양쪽이 한글)만 띄우지 않는다. 글자가 없으면 빈 문자열이고 `read`는 `unreadable`로 간다.

`parse: "number"`는 천 단위 구분(`,`·공백, 세 자리 묶음)을 빼고 처음 나오는 수(부호·소수점 포함)를 `number`로 낸다. 수가 없으면 `unreadable`.

`sensitive: true` target으로 읽은 `text`는 `secret`이고, `number`는 `null`이다(숫자 비밀 타입이 없다). 워크스페이스 `record.redact_secrets`가 켜져 있으면 그 OCR 텍스트는 기록에 남기지 않는다(`omitted.reason = "sensitive_target"`). 기본(꺼짐)은 남긴다.

`region`은 찾기 대상(`$target` — 지금 화면에서 찾은 상자 안을 읽는다. 지금 없으면 `read`는 `unreadable`, 기다리는 노드는 계속 기다린다) 또는 사각형 `[x, y, w, h]`(클라이언트 픽셀, [[그래프 JSON 스키마 v0]] 1장 "상수"). 화면 비율로 잡을 영역은 target(`search.region`이 정규화 좌표)으로 쓴다. 기준 요소 옆을 읽는 Anchor 방식은 target 파일의 옵션으로 둔다. `region`이 없으면 화면 전체를 읽는데, 큰 화면은 작은 글자를 놓치지 않도록 원래 해상도 타일로 나눠 검출하므로 느리다(1920×1080 약 1.5초, 4K 약 5초). `wait_text`처럼 되풀이해 읽는 노드는 영역을 주는 것이 기본이다.

## 6. 입력

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.input.click` | 매칭 결과나 좌표를 클릭 | `match` / `point`, `button`, `count` | | **done** |
| `core.input.drag` | 끌기 | `start`, `end`, `duration_ms` | | **done** |
| `core.input.scroll` | 휠 | `point`, `amount` | | **done** |
| `core.input.key` | 키 입력·조합·누르고 있기 | `keys`, `hold_ms` | | **done** |
| `core.input.type_text` | 글자 입력 | `target`, `text`, `clear` | | **done** |

입력 노드는 입력 직전에 대상 창이 유효한지, 포그라운드인지 확인한다. 실패하면 `error`다.

- 위치: `match`는 target의 클릭 지점, 점은 클라이언트 픽셀이고 그래프 상수로는 `[x, y]`로 쓴다(실행 전 검증이 모양을 보고 실행기가 점으로 바꾼다 — [[그래프 JSON 스키마 v0]] 1장 "상수"). `drag`의 `start`·`end`는 둘 다 받는다
- `button`은 `left`·`right`·`middle`·`x1`·`x2`, `count` 2면 이중 클릭. `drag`의 `duration_ms` 기본은 300
- `keys`는 키 하나나 `+`로 이은 조합(`ctrl+a`). `hold_ms`만큼 누르고 있다가 뗀다
- `type_text`의 `target`(생략 가능)은 지금 화면에서 한 번 찾아 그 칸을 먼저 클릭한다. 못 찾으면 `error`다 — 칸이 뜰 때까지는 대기 노드로 기다린다. `clear`는 입력 전에 `ctrl+a` → `backspace`로 칸을 비운다(전체 선택이 없는 칸은 끝 글자 하나만 지워진다). `text`가 비밀값이면 비밀값 가림(`record.redact_secrets`)을 켠 워크스페이스에서 그 스텝 화면·영상이 남지 않는다

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
| `core.var.add` | 숫자 변수에 더해 저장 (카운터) | `name`, `amount` | `value` | **done** |
| `core.logic.compare` | 비교 (exec 없는 순수 노드) | `a`, `op`, `b` | `result` | |
| `core.math.calc` | 산술 (exec 없는 순수 노드) | `a`, `op`, `b` | `result` | |
| `core.text.format` | 문자열 조합 (exec 없는 순수 노드) | `template`, `values` | `text` | |

순수 노드는 exec 핀이 없고, 값이 필요할 때 계산한다 (Unreal 순수 노드). 부작용이 없어야 한다. 평가 시점과 반복 규칙은 [[그래프 JSON 스키마 v0]] 7장.

- `var.get`: 변수가 없으면 `default`를 준다. `in`에 `default` 키가 **없을 때만** "기본값 없음"이라 `error`다. `"default": null`은 기본값 `null`을 준 것이므로 `null`을 돌려준다 (키 없음과 `null`을 구분. 노드 스키마의 `optional` 입력). 같은 그래프에 그 이름을 상수로 정하는 `var.set`이 없으면 실행 전 검증 경고
- `compare`의 `op`: `==`, `!=`, `<`, `<=`, `>`, `>=`, `contains`
  - `==`·`!=`는 JSON 값으로 비교한다. 타입이 다르면 다른 값이다 (`true`와 `1`은 다르고, `1`과 `1.0`은 같다)
  - 대소 비교는 숫자끼리·문자열끼리만 된다. 다른 타입끼리는 `error`
  - `contains`: `a`가 문자열이면 `b`(문자열)가 들어 있는지, `a`가 목록이면 `b`와 같은 원소가 있는지. 그 외는 `error`
- `math.calc`의 `op`: `+`, `-`, `*`, `/`, `//`(몫), `%`(나머지)
  - 숫자끼리만 된다(`true`·문자열·`null`·비밀값은 `error`). 입력·출력 핀 타입은 `float`이고 정수도 받는다
  - 정수끼리의 `+`·`-`·`*`·`//`·`%`는 정수, `/`나 실수가 끼면 실수다 (`7 / 2 = 3.5`, `6 / 3 = 2.0`)
  - `//`·`%`는 Python 규칙이다: 나머지의 부호는 `b`를 따른다 (`-7 % 3 = 2`)
  - 0으로 나누기(`/`·`//`·`%`), 무한대·NaN, JSON 정수 한도 ±(2^53-1)를 넘는 결과는 `error`
  - "N번째마다": 반복의 `index`를 `math.calc`(`% N`)로 나누고 `logic.compare`로 0과 비교해 `flow.branch`로 가른다
- `var.add`: 변수 `name`에 `amount`(기본 1)를 `math.calc`의 `+` 규칙으로 더해 저장하고 새 값을 `value`로 낸다. 변수가 없거나 숫자가 아니면 `error`다 — 처음 값은 `var.set`으로 정한다
- `text.format`: `template`의 `{이름}`을 `values`(`dict[str,any]`)의 값으로 바꾼다. `{{`·`}}`는 중괄호 자체
  - 자리 표시는 `{이름}`만 된다. 속성·인덱스 접근(`{a.b}`, `{a[0]}`)·형식 지정(`{a:>3}`, 빈 지정자 `{a:}`, `{a!r}`)·빈 `{}`·짝 없는 중괄호·`values`에 없는 이름은 `error`
  - 문자열이 아닌 값은 JSON 표기로 넣는다 (`true`, `null`, `[1, 2]`)
  - `values` 중 하나라도 비밀값이면 결과 `text`도 비밀값이다. 그래서 출력 타입은 `string|secret`

## 9. 기록

| 타입 | 하는 일 | 주요 입력 | 출력 | 출구 |
|---|---|---|---|---|
| `core.log.message` | 실행 기록에 메시지 남김 | `level`, `text` | | **done** |

`level`은 `info`(기본)·`warn`·`error`. `text`는 `string|secret`이다. 비밀값은 워크스페이스 `record.redact_secrets`가 켜져 있으면 가려서(`***`), 기본(꺼짐)은 그대로 남긴다.

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
| 글자 입력 | 칸 클릭(`core.image.click`, 기다림) + target 없는 `core.input.type_text` — 입력 칸 구간(클릭·Tab ~ 칸 밖 클릭·Tab·Enter·Esc·창 떠남·칸 없음 확정) 하나에 하나, 쉼으로 나뉘지 않음. 구간 안 Backspace·Ctrl+A는 흡수해 최종 문자열과 `clear`로 (M4) |
| 녹화 중 "검증 넣기" | `core.assert.visible` / `core.assert.text` |

## MVP에서 뺀 것

- 여러 개 찾기(`find_all`, 개수 세기), 색 판정, 템플릿 이외 특징점 매칭 단독 노드
- switch(여러 갈래 문자열 분기). `wait_any`와 `branch`로 대신한다
- 파일·HTTP·DB 노드. 플러그인으로 만든다
- try/catch, 병렬 실행
- 게임을 직접 조작하는 Agent 노드

## 반영 기록

| 바뀐 것 | 이유 |
|---|---|
| M1 앱·창·입력 노드: `launch`의 `cwd` 입력·`timeout` 출구의 `process`, `attach`의 `owned`, 창을 정한 노드의 활성화, `drag` 입력 이름 `from`·`to` → `start`·`end`, 점 상수 `[x, y]`, `type_text`의 칸 찾기·`clear` 방법 (3·6장) | 게임은 작업 폴더가 맞아야 뜨는 것이 많다. `from`은 Python 예약어라 노드 함수 인자가 될 수 없다(SDK `ctx.input.drag(start, end)`와 같게). 실행기가 구조 타입 상수를 바꾸지 않아 점 상수의 모양을 정해야 한다. `clear`는 게임 입력 칸이 공통으로 아는 키 조합이 필요하다 |
| M1 OCR: `confidence`(상자 점수 평균, 글자 없으면 `null`)·`text` 합치기(줄·띄어쓰기)·`parse: "number"` 규칙·`sensitive`의 `number = null`, 영역 없는 전체 읽기의 속도 (5장) | 노드 출력의 뜻을 엔진 구현(`kookabug_platform.ocr`)과 맞춘다. 숫자에는 비밀 타입이 없어 가린 값을 낼 수 없다. 큰 화면 전체 읽기는 타일 검출이라 수 초가 걸린다 |
| M1 화면·이미지·검증·OCR 노드: 기다림(100 ms 간격, `timeout_ms: 0` = 한 번), 실패 시 마지막 프레임 `_timeout`·`_not_found`, `wait_any` 이름 일치, `image.click`·`ocr.click_text`의 기다림(`timeout_ms`)·`button`, `wait_stable`의 `tolerance`(기본 0.001), 화면 검증의 기다림과 `assert.text` 비교, `region` 사각형은 클라이언트 픽셀 `[x, y, w, h]`(정규화 사각형이 아님), 점 상수는 실행기의 일반 규칙 (2·4·5·6장) | 화면은 바로 바뀌지 않아 검증도 잠깐 다시 봐야 한다. 정지 화면은 같은 프레임의 반복이라 오류가 아니다. 버튼 한 줄 강조(약 0.006)를 멈춘 화면으로 보면 애니메이션 끝을 놓친다. SDK의 `Rect`가 클라이언트 픽셀이고, 화면 비율에 따르는 영역은 target(정규화 `search.region`)이 맡는다 |
| OCR `match`가 영역 종류와 무관하게 캡처 시점 관측을 실음, 화면 밖 픽셀 영역은 `error` (4·5장) | 사각형·전체 화면 OCR의 `match`에 관측이 없으면 읽은 뒤 창 크기·DPI가 바뀌어도 옛 좌표를 눌렀다. 화면 밖 영역은 비교·읽을 픽셀이 없는데 "안 변함"으로 판정됐다 |
| M1 공통 입력 `window`의 규칙: 받는 노드(exec 노드 전부, 같은 이름 입력이 있으면 그 입력), 타입·`null`, 바뀌는 범위, `core.graph.call`이면 서브그래프가 이어받는 창 (공통 입력) | "모든 exec 노드"만으로는 같은 이름 입력을 가진 노드와 서브그래프 호출에서 뜻이 정해지지 않는다 |
| 산술 `core.math.calc`·`core.var.add` (8장) | 사용자 결정 G17(2026-11-03): "N번째마다"·카운터 흐름을 만들 수 없었다. 연산마다 노드를 두지 않고 `op` 입력으로 묶는다(이 문서 기준) |
| 실행 첫 창을 실행기가 앞으로 가져옴(포그라운드 잠금을 넘음, 실패는 `warn`) (3장) | 사용자 결정 D1(2026-11-03): 보이지 않는 창을 가진 다른 프로그램이 포그라운드를 쥐면 게임이 뒤에 남아 첫 키 입력부터 오류였다. 실행 도중 포커스를 잃은 경우는 그대로 오류(U1) |
| 비밀값 가림은 워크스페이스 `record.redact_secrets`가 켜졌을 때만 (2·5·6·9장) | 사용자 결정 D3(2026-11-03): 개발 환경 전용 도구라 비밀값까지 기록에 남겨도 된다. 옛 동작은 설정으로 되살린다 |
