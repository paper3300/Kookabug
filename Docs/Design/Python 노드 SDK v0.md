# Python 노드 SDK v0

- 작성일: 2026-10-29
- 상태: 확정 (추천안대로). 세부 API 이름은 구현하면서 바뀔 수 있다
- 근거: [[결정 현황]], [[그래프 JSON 스키마 v0]], [[MVP 노드 목록]]
- 라이선스: SDK·템플릿은 **MIT** (본체는 Apache-2.0)

---

## 방향

| 결정 | 이유 |
|---|---|
| **함수 + 데코레이터 + 타입 힌트**로 노드를 선언한다 | FastAPI·Typer처럼 Python 사용자에게 익숙하다. ComfyUI의 `INPUT_TYPES` 딕셔너리 방식보다 짧고 타입 검사가 된다 |
| 빌드 때 **스키마 JSON을 미리 만들어** 플러그인에 넣는다 | 확정 사항: 매니페스트와 스키마 JSON만으로 팔레트를 그리고, Python은 실행할 때 로드한다 (VSCode activation events) |
| 노드는 **결과 객체를 반환**하고, 예외는 `error`가 된다 | `fail`(판정 실패)과 `error`(노드 고장)를 코드에서도 구분한다 |
| 노드는 `ctx`로만 외부와 만난다 (창, 캡처, 입력, 기록, 취소) | 테스트에서 가짜 `ctx`로 바꿔 끼울 수 있다. 서버를 거치는 동작은 권한 검사를 받는다 |
| 코어 노드도 같은 SDK로 만든다 | SDK가 실제로 쓸 만한지 코어가 먼저 검증한다 |

---

## 노드 예시

```python
from kookabug_sdk import node, Exit, ObservationTimeout, Result, Context
from kookabug_sdk.types import Target, Match

@node(
    type="core.image.wait",
    version=1,
    title="이미지 대기",
    category="image",
    exits=[Exit("found", "ok"), Exit("timeout", "fail")],
    outputs={"match": Match},
    effects={"capture"},
)
def wait_image(ctx: Context, target: Target, timeout_ms: int = 10000) -> Result:
    """대상이 나타날 때까지 기다린다."""
    deadline = ctx.deadline(timeout_ms)
    frame = None
    try:
        while not deadline.passed:
            ctx.check_cancel()
            frame = ctx.capture(deadline=deadline)
            match = ctx.vision.find(frame, target, deadline=deadline)
            if match:
                return Result.ok("found", match=match)
            ctx.sleep(min(100, deadline.remaining_ms))
    except ObservationTimeout:
        pass  # 관측이 노드 기한에 걸렸다 = timeout
    if frame is not None:
        ctx.artifacts.save(frame, "timeout")
    return Result.fail("timeout", message=f"{target.name} 이(가) {timeout_ms}ms 안에 보이지 않음")
```

- 함수 인자 = data 입력 핀. 타입 힌트가 핀 타입, 기본값이 핀 기본값이 된다
- 기본값 자리에 `OMITTED`를 쓰면 **생략할 수 있는 입력**이 된다 (노드 스키마 `optional: true`, `default` 없음). 그래프가 값을 주지 않으면 함수는 `OMITTED`를 받으므로 생략과 명시적 `null`을 구분할 수 있다. 예: `core.var.get`의 `default: Any | None = OMITTED`
- 출력 핀은 `outputs=`로 선언하고, 값은 `Result`에 키워드로 넘긴다 (아래)
- `Result.ok(출구, **출력)` / `Result.fail(출구, message=..., **출력)`. 선언하지 않은 출구, 그 출구가 주지 않는 출력, 출구 종류(`ok`/`fail`)와 다른 반환, 빠진 non-nullable 출력은 `error`. 빠진 nullable 출력은 `null`로 채운다
- 예외가 나면 `error`. 러너가 예외 내용과 **그 노드가 실행 중에 얻은 마지막 캡처**를 기록한다 (그 노드가 캡처하지 않았으면 스크린샷은 없다). 기록 정책이 막으면 남기지 않는다 ([[그래프 JSON 스키마 v0]] 6장 "화면에 찍힌 비밀값")
- docstring은 노드 설명이 된다 (팔레트 툴팁, MCP 도구 설명)

### 출력과 설정 선언

```python
@node(
    type="core.image.wait_any",
    version=1,
    title="여러 대상 중 먼저 보이는 것",
    category="image",
    config={"exits": Config(list[str], min_items=2)},
    exits=DynamicExits(from_config="exits", kind="ok", extra=[Exit("timeout", "fail")]),
    outputs={"match": Match},
    effects={"capture"},
    retry=Retry.observation(on=["timeout"]),
)
def wait_any(ctx: Context, targets: dict[str, Target], timeout_ms: int = 10000) -> Result:
    ...
```

- `config`: 연결할 수 없는 노드 설정. 노드 모양(출구·핀)을 바꿀 수 있다. 노드 코드는 `ctx.config`로 읽는다
- `DynamicExits`: 설정값으로 출구를 만든다. 스키마 JSON에는 "config.exits에서 만든다"는 규칙으로 들어간다. `config` 항목은 `list[str]`이어야 한다
- **출구별 출력**: `Exit(이름, 종류, outputs=[...])`로 그 출구가 주는 출력을 정한다. 생략하면 `ok` 출구는 선언한 출력 전부, `fail` 출구는 출력 없음. `DynamicExits(..., outputs=)`도 같다. 실행 전 검증이 "나간 출구가 그 출력을 주는가"를 이것으로 검사한다
- 출력 선언에 설명·nullable이 필요하면 `outputs={"score": Output(float, nullable=True, description=...)}`. 입력 핀 제약은 `Annotated[int, Input(minimum=1)]`
- **`effects={"capture", "input", "process"}`**: 게임에 영향을 주는 동작을 선언한다. 선언하지 않은 효과를 `ctx`로 쓰면 `error`(`EffectNotDeclared`). 효과별 기능은 아래 "`ctx`가 주는 것"의 효과 표. 노드 효과는 `[tool.kookabug].permissions`에도 있어야 한다 (빌드 오류)
- 순수 노드(exec 없음)는 `@node(..., pure=True)`. 출구가 없고 출력 dict(`{"result": ...}`)를 반환한다. `effects`·`retry`·`assertion`을 쓸 수 없다
- 재시도 가능 여부는 `@node(..., retry=Retry.observation(on=["timeout"]))`로 선언한다. 생략하면 `never`. `on`은 선언한 fail 출구(동적 출구는 `extra`)만 된다. `effects`에 `input`이나 `process`가 있는 노드는 `observation`으로 선언할 수 없다 (빌드 오류) → [[그래프 JSON 스키마 v0]] 6장
- **`assertion=True`**: 검증 노드. 판정 5행("검증 노드가 하나 이상 성공")과 "연결 안 된 `ok` 출구 경고 예외"는 이 표시로 정한다 → [[그래프 JSON 스키마 v0]] 2장
- **`engine="<이름>"`**: 실행기가 직접 처리하는 노드 (`core.graph.*`, `core.test.*`, `core.flow.repeat`·`while`). SDK로 선언만 하고 함수 본문은 호출되지 않는다. `core` 플러그인만 쓸 수 있다 (빌드 오류). 출구 없는 exec 노드(종료 노드)도 `engine` 노드만 된다
- **`FromInterface("inputs" | "outputs" | "exits")`**: 핀·출구를 그래프 `interface`에서 만든다. `core.graph.entry`의 출력 = `interface.inputs`, `core.graph.exit`의 입력 = `interface.outputs`, `core.graph.call`의 입력·출력·출구 = 부르는 서브그래프의 `interface`. interface에서 온 출력은 출구의 `outputs`에 이름으로 적지 않는다 (서브그래프 출력은 모든 출구에서 주어진다). **`engine` 노드만** 쓸 수 있다 (빌드 오류). interface 핀·출구는 실행기만 해석하므로, 일반 노드에 허용하면 결과(출구·출력) 검사를 할 수 없다
- 입력 노드는 `ctx.input`이 입력 직전에 관측값을 확인하고 필요하면 다시 매칭한다. 노드 코드가 따로 할 일은 없다. 다시 찾지 못하면 `StaleObservation`이 노드를 지나 그 스텝의 처리되지 않은 fail(`stale_observation`)이 된다 (아래 "예외")

---

## 핀 타입

| 타입 | Python | 비고 |
|---|---|---|
| `bool`, `int`, `float`, `string` | `bool`, `int`, `float`, `str` | |
| `secret` | `Secret` | 값을 꺼내려면 `.reveal()`. `str()`은 늘 가린 값(`***`)이다. `ctx.log`에 `Secret`을 그대로 주거나 출력으로 내면 실행 기록에 남길 때 워크스페이스 `record.redact_secrets`(기본 false = 원문)를 따른다. 비밀값이 든 실패 메시지는 `message_with_secrets(lambda show: f"... {show(v)} ...")`로 만들면 가린 글·원문을 둘 다 싣는 `SecretMessage`가 되어(`Result.fail`·`ctx.log`가 받는다) 기록 정책을 따른다. 그냥 `str()`·f-string으로 만든 글은 이미 가려져 있다. 워커 노드의 `SecretMessage`도 경계 너머로 가린 글·원문을 둘 다 보내(wire `{"$kb": "secret_message", "masked", "raw"}`, 원문은 인증된 파이프로만) runner가 같은 정책으로 고른다 — `ctx.log`·`Result.fail` 메시지·판정 사유 모두 코어 노드와 같다. `SecretMessage`는 **메시지 전용**이다: 노드 출력·변수 값에 넣으면 워커 경계에서 거부되어(`error`) 기록에 원문이 새지 않고, runner 안 노드가 값에 넣어도 기록에는 정책대로 가린 글·원문 중 하나만 남는다 |
| `target` | `Target` | `*.target.json` |
| `match` | `Match` | `rect`·`score`·`window`·`frame`과 찾은 배율(`scale`)·방법(`method`)·target 파일(`target`, 스냅샷 경로)·클릭 지점(`click`, 없으면 `rect` 중심 — `click_point`)·찾은 관측(`frame_info`: 캡처 방식·그때 클라이언트 크기·DPI·`capture_id`·관측 시각). 입력 직전 재검증이 `frame_info`·`target`을 쓴다. `frame_info`는 값 비교에 들지 않는다 |
| `rect`, `point` | `Rect`, `Point` | 클라이언트 영역 기준 |
| `image` | `Image` | 기록에는 파일로 저장. `ctx.capture`가 준 이미지에는 러너가 캡처 번호(`capture_id`)를 붙인다. 기록 정책이 이 번호로 "얻을 때 허용됐는가"를 보므로 노드는 받은 이미지를 그대로 넘긴다 (값 비교에는 들지 않는다). 실제 캡처 이미지는 **참조 이미지**다: 픽셀(`data`)·파일(`path`) 없이 크기·`frame`·`capture_id`만 들고, 픽셀은 러너의 프레임 저장소에 있다. 찾기·비교·OCR은 러너가 그 픽셀로 하고(`ctx.vision`·`ctx.ocr`), `ctx.artifacts.save`는 저장소 픽셀을 PNG로 남긴다. 저장소는 최근 캡처만 들고 있으므로 오래 전에 얻은 이미지를 나중에 쓰면 `frame_expired`일 수 있다 — 지금 화면이 필요하면 다시 캡처한다. 파일·바이트에서 만든 이미지는 그대로 오간다 |
| `window`, `process` | `WindowRef`, `ProcessRef` | 유효성 확인 가능. `WindowRef`는 `handle`(HWND)·`title`과 `pid`·`process_created`(프로세스 생성 시각 FILETIME 10진 문자열)·`binding`(러너가 창을 처음 정할 때 붙이는 바인딩 ID, 그 실행 안에서만 뜻이 있음). 창이 닫히면 바인딩이 죽어 같은 HWND로 뜬 새 창과 섞이지 않는다(`window_gone`). 노드는 이 셋을 만들지 않고 받은 값을 넘긴다 |
| `list[T]`, `dict[str, T]` | 같음 | |
| `any` | `Any` | 연결 검사를 하지 않음. 가급적 쓰지 않는다 |
| `A\|B` (유니온) | `A \| B` | 예: `str \| Secret` → `string\|secret`. 평문과 비밀을 다 받는 입력. `secret` 값은 `secret`을 포함한 핀에만 연결된다 |

- 맨 바깥의 `| None`은 nullable 핀이다 (예: `str | None = None`). 안쪽(`list[int | None]`)에는 쓸 수 없다
- `Literal["info", "warn", "error"]`은 `string` 핀 + 선택지(`enum`)가 된다. **입력·config 핀에서만** 쓴다. 출력 핀에 쓰면 빌드 오류 (출력의 선택지는 연결 검사·팔레트가 쓰지 않으므로 노드 스키마 출력에 `enum`을 두지 않는다)
- 제약·기본값은 빌드 때 검사한다: `minimum`·`maximum`은 유한한 수(`minimum ≤ maximum`), `min_items`는 0 이상 정수, 정수(기본값·선택지·제약)는 ±(2^53-1) 안, 실수는 유한 (그래프 파일과 같은 숫자 규칙 → [[그래프 JSON 스키마 v0]] 원칙)

플러그인 고유 타입은 `플러그인ID.타입명`으로 등록한다: 클래스에 `@plugin_type("unreal.ActorRef")`

---

## `ctx`가 주는 것

| 기능 | 예 |
|---|---|
| 현재 대상 창 | `ctx.window`, `ctx.set_window(window)` (호출 프레임의 현재 창을 **다음 스텝부터** 바꾼다. 그 노드의 `ctx.window`는 노드 호출 동안 그대로다. 서브그래프는 부른 쪽의 창을 이어받고, 안에서 바꾼 것은 밖으로 나오지 않는다) |
| 캡처 | `ctx.capture(region=None, *, deadline=None) -> Image` (참조 이미지) |
| 이미지 찾기·비교 | `ctx.vision.find(image, target, *, region=None, deadline=None) -> Match \| None`, `ctx.vision.diff(a, b, *, region=None) -> float` (채널 평균 절대 차이 / 255. 0 = 같음, 크기가 다르면 1. `region`(클라이언트 좌표)을 주면 두 관측의 클라이언트 크기가 다를 때 1, 같으면 이미지마다 자기 원점 기준으로 같은 클라이언트 영역끼리. 영역이 두 이미지와 겹치지 않으면 비교할 픽셀이 없으므로 1) |
| OCR | `ctx.ocr.read(image, *, region=None, sensitive=False, deadline=None) -> OcrResult` (`text`·`lines`(`OcrLine`: `text`·`box`·`score`)·`confidence`, 그리고 읽은 이미지의 캡처 시점 관측 `window`·`frame_info` — 줄 상자로 `Match`를 만들 때 실어 입력 직전 재검증이 쓴다. `frame_info`는 값 비교에 들지 않는다). `sensitive=True`(비밀 target 영역)면 글자가 `Secret`으로 온다 |
| 창 | `ctx.windows.find(title=None, process_name=None, *, owned=False) -> WindowRef \| None` (제목 부분 일치·`/정규식/`, 기본은 소유자 없는 창만), `ctx.windows.info(window) -> WindowInfo`, `ctx.windows.set_client_size(window, w, h) -> bool`, `ctx.windows.activate(window)` (최선 노력) |
| 프로세스 | `ctx.process.launch(path, args=(), cwd=None) -> ProcessRef`, `ctx.process.close(process, force_after_ms) -> bool`, `ctx.process.find_window(process, title=None, *, deadline=None) -> WindowRef \| None` (런처가 띄운 아래 프로세스의 창까지) |
| 입력 | `ctx.input.click(at, *, button="left", count=1)`, `ctx.input.drag(start, end, *, duration_ms=0, button="left")`, `ctx.input.scroll(at, amount)`, `ctx.input.key(key, *, hold_ms=0)`, `ctx.input.type_text(text)`. `at`은 `Point`·`Rect`(중심)·`Match`(클릭 지점). 요청은 그 스텝의 대상 창(`in.window` 또는 현재 창)으로 가고, 입력 직전 창 유효성·포그라운드·가림을 확인한다 |
| 기록 | `ctx.log.info(...)`, `ctx.artifacts.save(image, name) -> str \| None` (실행 폴더 기준 경로. 기록 정책으로 생략하면 `None`) |
| 시간·취소 | `ctx.deadline(ms)`, `ctx.sleep(ms)`, `ctx.check_cancel()` |
| 워크스페이스 | `ctx.setting(key)`, `ctx.path(rel)` |
| 노드 설정 | `ctx.config` (그래프 노드의 `config` 값) |
| 변수 | `ctx.vars.get(name, default)`, `ctx.vars.has(name)`, `ctx.vars.set(name, value)` (호출 프레임 변수) |

**효과와 `ctx` 기능** (exec 노드의 `effects`)

| 효과 | 쓸 수 있게 되는 것 |
|---|---|
| `capture` | `ctx.capture`, `ctx.vision.*`, `ctx.ocr.*` |
| `input` | `ctx.input.*` |
| `process` | `ctx.process.*`, `ctx.windows.set_client_size`·`activate` |
| (효과 없이) | `ctx.windows.find`·`info`, `ctx.set_window`, 기록·시간·변수·설정 |

**관측 호출의 기한** (`deadline` 인자): `capture`·`vision.find`·`ocr.read`·`process.find_window`는 노드가 `ctx.deadline(timeout_ms)`로 만든 기한을 받는다. 관측 하나의 유효 기한은 `min(설정 기한 run.capture_timeout_ms, 노드 기한 남은 시간, 전체 기한 남은 시간)`이다. 노드 기한 때문에 끝나면 `ObservationTimeout`이고 노드는 이것을 잡아 `timeout` 출구로 간다. 남은 시간이 0이면 관측을 시작하지 않고 바로 `ObservationTimeout`이다. 설정 기한으로 끝나면 `capture_timeout`(`error`), 전체 기한이면 `deadline_exceeded`다. 워커는 남은 시간(ms)을 관측 요청에 실어 러너가 같은 규칙을 쓴다. 예외: `process.find_window`(창이 뜨기를 기다리기)에는 설정 기한을 걸지 않는다 — `min(노드 기한, 전체 기한)`. 게임 시작은 캡처 한 번보다 길다

**예외**

| 예외 | 바탕 | 뜻 | 노드 쪽 |
|---|---|---|---|
| `ObservationTimeout` | `Exception` | 관측이 노드 기한 안에 끝나지 않았다 | 잡아서 `timeout` 출구 |
| `StaleObservation` | `BaseException` | 입력 직전 재검증에서 `Match`가 지금 창(크기·DPI·캡처 방식)과 맞지 않고 다시 찾지도 못했다 | 잡지 않는다. `except Exception`에 삼켜지지 않고 그 스텝의 처리되지 않은 fail(`stale_observation`, 출구 없음)이 된다. 잡아서 삼켜도 그 스텝은 처리되지 않은 fail이다 |
| `RunnerError` | `RuntimeError` | (워커 노드만) runner가 ctx 요청을 오류 코드(`code`: `frame_expired`·`window_gone`·`capture_timeout` 등)로 거부했다 | 잡지 않으면 그 스텝은 그 코드의 `error`. 같은 프로세스의 코어 노드는 실행기 오류가 그대로 온다 |

**순수 노드의 `ctx`** (부작용 금지 → [[그래프 JSON 스키마 v0]] 7장)

| 막힘 | 됨 |
|---|---|
| `ctx.capture`, `ctx.input`·`vision`·`ocr`·`windows`·`process`·`artifacts`·`log`의 모든 메서드(`log`는 `debug`·`info`·`warn`·`error`), `ctx.set_window`, `ctx.sleep`, `ctx.vars.set` | `ctx.vars.get`·`has`, `ctx.config`, `ctx.window`, `ctx.setting`, `ctx.path`, `ctx.deadline`, `ctx.check_cancel` |

- 창 찾기·정보(`ctx.windows.find`·`info`)는 부작용이 없지만 그 순간의 화면에 따라 값이 달라지므로 순수 노드에서는 막는다 (소비할 때마다 계산하는 순수 노드의 값이 바뀌면 안 된다)

- 막힌 기능을 부르면 `PureContextViolation` → `error`. 노드 코드가 그 예외를 잡아 삼켜도 `error`다
- 순수 노드의 `ctx.vars.get`은 값의 깊은 복사본을 준다. 읽은 list·dict를 고치거나 그대로 출력해도 호출 프레임 변수는 바뀌지 않는다 (소비 횟수가 변수 값을 바꾸지 않게)
- 제한은 SDK의 `PureContext` 래퍼 하나로 건다. 실행기와 `fake_context(pure=True)`가 같은 래퍼를 쓴다. exec 노드의 `effects` 검사(`EffectNotDeclared`)도 같은 방식이다

- 오래 걸리는 노드는 `ctx.check_cancel()`을 자주 부른다. 응답하지 않으면 러너가 워커 프로세스를 종료한다 (취소 순서는 [[구현 계획 v0]] 3장)
- 스크린샷·텍스트 기록은 반드시 `ctx.artifacts`/`ctx.log`를 거친다. 기록 정책(비밀값 생략, 구간 끄기)이 여기서 집행된다. 노드가 파일을 직접 쓰지 않는다
  - `ctx.artifacts.save`가 `None`을 주면 정책으로 생략된 것이다. 경로를 출력이나 로그로 넘기는 노드는 `None`을 처리한다. 가짜 ctx(`fake_context`)는 정책이 없어 늘 경로(이름)를 준다
- 플러그인이 `ctx`를 거치지 않고 OS를 직접 건드릴 수는 있다. 막지 못하므로 매니페스트에 권한을 선언하게 하고 설치할 때 보여 준다

---

## 플러그인 프로젝트

```
kookabug-plugin-sample/
├─ pyproject.toml                 [project] + [tool.kookabug]
├─ src/kookabug_plugin_sample/
│  ├─ __init__.py
│  ├─ nodes.py
│  └─ kookabug.schema.json         `kookabug-sdk build`가 만든다. 배포에 포함
├─ ui/                             (선택) UI 확장 JS
└─ tests/test_nodes.py
```

```toml
[project]
name = "kookabug-plugin-sample"
version = "0.1.0"
dependencies = ["kookabug-sdk>=0.1,<0.2"]

[tool.kookabug]
id = "sample"
title = "Sample 플러그인"
modules = ["kookabug_plugin_sample.nodes"]
permissions = ["capture", "input"]
min_core = "0.1.0"
```

- `id`가 노드 타입 앞부분이 된다 (`sample.xxx.yyy`)
- `permissions` 후보: `capture`, `input`, `process`, `filesystem`, `network`, `secrets`. 설치 화면에 표시한다. 노드의 `effects`는 여기에 있어야 한다
- 노드 스키마는 `src/<최상위 패키지>/kookabug.schema.json`에 만든다 (최상위 패키지 = `modules` 첫 항목의 첫 이름). 모듈 디렉터리 안에 있으므로 빌드 백엔드가 **uv_build면** 설정 없이 wheel에 들어간다. setuptools 등 다른 백엔드는 package-data 같은 데이터 파일 포함 설정이 따로 필요하다. 설치된 스키마는 `kookabug_sdk.schema.load_installed("<패키지>")`(`importlib.resources`)로 읽는다
- 의존성은 `dependencies`로 선언하고 uv로 설치한다. venv는 기본 공유, 충돌하면 그 플러그인만 격리 venv. 워커 프로세스는 venv와 별개로 **실행마다 새로** 띄운다 → [[구현 계획 v0]] 3장

**워커에서 실행될 때**

- 플러그인 노드는 runner가 아니라 워커 프로세스에서 돈다. 워커 호스트는 SDK에 있다(`python -m kookabug_sdk.worker`). 그래서 플러그인 venv에는 SDK만 있으면 되고 본체(`kookabug_core`) 의존성이 들어오지 않는다
- runner는 플러그인 코드를 import하지 않는다. 워커가 `modules`를 import해 모은 노드 선언(노드 스키마와 같은 모양)으로 그래프를 검증한다
- `ctx`의 캡처·찾기·비교·OCR·창·프로세스·입력·기록·변수·설정은 runner에 요청으로 간다. 캡처는 참조 이미지로 오고 찾기·비교·OCR은 runner가 자기 프레임 저장소 픽셀로 하므로 플러그인 venv에 opencv 등이 필요 없다. `ObservationTimeout`·`StaleObservation`은 runner 오류 종류(`observation_timeout`·`stale_observation`)로 와서 워커에서 같은 예외가 된다. runner가 노드 선언(`pure`·`effects`)으로 다시 검사하므로, `ctx`의 제한 래퍼를 건너뛰어도 선언하지 않은 효과는 `error`다. 노드 결과도 runner가 선언과 다시 대조한다
- `ctx`는 그 노드 실행 동안만 쓴다. 노드가 돌아온 뒤 보관해 둔 `ctx`나 노드가 남긴 스레드에서 부르면 `ContextViolation`이다(runner도 끝난 실행의 요청을 처리하지 않는다)
- `print()`와 표준 오류 출력은 실행 폴더 `logs/worker.stdout.log`·`worker.stderr.log`로 간다. 통신에 쓰지 않으므로 출력이 통신을 깨지 않는다. 실행 기록에 남길 것은 `ctx.log`를 쓴다
- `ctx.path(rel)`은 원본 워크스페이스가 아니라 **실행 스냅샷**(`<실행 폴더>/snapshot`) 기준이다. `..`·절대 경로로 그 밖을 가리키면 오류
- 노드 입력·출력은 JSON 값과 SDK 타입(`Secret`·`Rect`·`Image` 등)만 오간다. 비밀값은 워커에서도 `Secret`이다. 노드 예외는 `error`(`node_error`)가 되고 traceback은 실행 기록의 `log`(error)에 남는다
- 취소 뒤 유예(`run.worker_cancel_grace_ms`, 기본 2초) 안에 노드가 끝나지 않으면 runner가 워커 프로세스를 끝낸다. 워커가 죽으면 그 스텝은 `error`(`worker_died`)이고, 그 실행에서 워커를 다시 띄우지 않는다

## 명령

| 명령 | 하는 일 |
|---|---|
| `kookabug-sdk new` | 플러그인 템플릿 생성 |
| `kookabug-sdk build [프로젝트]` | `[tool.kookabug].modules`를 import해 `src/<패키지>/kookabug.schema.json` 생성. 출구·타입·재시도·효과 선언 오류 검사. 같은 코드면 같은 바이트(키 정렬, 노드는 type 순) |
| `kookabug-sdk dev` | 실행 중인 Kookabug에 연결해 핫 리로드 (`.hotreload` 마커 방식) |
| `kookabug-sdk test` | pytest + 가짜 `ctx`. 스크린샷 파일을 캡처 결과로 주입 |

## 노드 테스트

```python
from kookabug_sdk.testing import fake_context, load_target

def test_wait_image_found():
    ctx = fake_context(frames=["tests/fixtures/title.png"])
    result = wait_image(ctx, target=load_target("tests/fixtures/start_button.target.json"))
    assert result.exit == "found"
    assert result.outputs["match"].score > 0.85
```

게임 없이 노드를 테스트할 수 있다. 그래프 단위의 "게임 없이 테스트"(고정 데이터)와는 별개다.

- `frames`는 순서대로 캡처 결과가 된다 (다 쓰면 마지막 프레임). 입력은 실행하지 않고 `ctx.input.calls`에, 로그는 `ctx.log.records`에 남는다. 시간은 가짜 시계(`FakeClock`)라 `ctx.sleep`이 실제로 기다리지 않는다
- 노드를 부르면 실행기와 같은 제한(순수 ctx, `effects`)과 결과 검사가 걸린다. `fake_context(pure=True)`는 `PureContext`로 감싼 ctx를 준다
- `ctx.vision`·`ctx.ocr`: `fake_context(vision=..., ocr=...)`로 엔진을 넣는다. 넣지 않으면 `kookabug_platform`이 있을 때 그 실제 엔진(`kookabug_platform.fake_engines`의 `vision()`·`ocr()`)을 처음 쓸 때 만들고, 없으면 `EngineUnavailable`(어떻게 넣는지 안내). SDK 자체는 `kookabug_platform`에 의존하지 않는다
- `windows=[FakeWindow(...)]`는 처음부터 떠 있는 가짜 창(`ctx.windows.*`), `ctx.process.launch`는 새 PID(처음부터 있던 창·앞서 띄운 프로세스의 PID와 겹치지 않음)를 주고 `launched`에 남긴다. 장면이 준 창은 복사해 넣으므로 같은 창 견본을 여러 번·여러 가짜 ctx에서 띄워도 섞이지 않는다
- `ctx.set_window`는 가짜 ctx(호출 프레임)의 창을 바꾸고, 그 노드 안의 `ctx.window`는 실행기·워커처럼 그 호출 동안 그대로다
- 넣은 엔진이 기한을 보지 않아도 가짜 ctx가 `vision.find`·`ocr.read` 앞에서 지난 기한을 막는다 (엔진을 부르지 않고 `ObservationTimeout`)
- `scenario=`(장면 전이: `capture(region)`·`on_input(call)`·`launch(path, args)`)를 주면 캡처는 그 장면의 지금 화면, 가짜 입력은 장면 전이, 프로세스 띄우기는 장면이 정한 창을 띄운다. 예제 게임의 장면 표(`scenario.json`)를 읽는 구현은 코어의 가짜 플랫폼이 준다
- `deadline`이 이미 지난 관측 호출은 `ObservationTimeout`이다

## 노드 버전

- 입력·출구·출력 의미가 바뀌면 `version`을 올린다. 그래프는 노드마다 `version`을 기록한다
- 플러그인은 옛 버전 그래프를 새 버전으로 옮기는 함수를 줄 수 있다: `@node(..., migrations={1: migrate_v1})`
- 옮기지 못하면 실행 전 검증에서 막고, 옛 버전 플러그인으로 실행하라고 안내한다

## 이후 버전

- 비동기(`async def`) 노드
- 노드 단위 병렬 실행
- 노드 하나에 Python 외 언어(실행 파일) 연결

## 반영 기록

| 바뀐 것 | 이유 |
|---|---|
| M1 SDK 계약: `ctx.vision`(`find`·`diff`)·`ctx.ocr`·`ctx.windows`·`ctx.process`·`ctx.set_window`, 입력 `drag`·`scroll`·`click(count)`·`key(hold_ms)`, 관측 호출의 `deadline` 인자, 예외 `ObservationTimeout`·`StaleObservation`, 효과 표, `Match`(배율·방법·target·클릭 지점·`frame_info`)·`WindowRef`(PID·생성 시각·바인딩) 필드, `fake_context`의 엔진 주입·`scenario`·`windows` | 화면 안정 대기에 두 프레임 비교가 필요하고(`diff`), 관측이 노드 기한을 넘기지 않아야 하며(`ObservationTimeout`), 입력 직전 재검증은 노드가 삼킬 수 없어야 한다(`StaleObservation`). 같은 HWND를 다시 쓴 창은 바인딩으로 가린다. 워커는 픽셀 없이 참조 이미지만 받으므로 찾기·OCR을 runner에 맡긴다. `ctx.ocr.read`의 `sensitive`와 `Match.click`은 계약 표에 없던 것을 더했다 — 비밀 target 영역의 글자가 워커·기록으로 원문 그대로 가지 않게, 워커가 target 없이도 클릭 지점을 넘기게 |
| M1 runner 연결: 워커 예외 `RunnerError(code)`, 삼킨 `StaleObservation`도 처리되지 않은 fail, 가짜 ctx 실제 엔진 `kookabug_platform.fake_engines`(파일·바이트 이미지 매칭·OCR) | 워커 노드가 `frame_expired`·`window_gone` 같은 사유를 코드로 가려 처리할 수 있어야 하고, 잡지 않았을 때 스텝 오류 코드가 `node_error`로 뭉개지면 안 된다. 재검증 실패를 노드가 삼키면 입력하지 않은 채 성공으로 끝난다. 노드 테스트가 실제 매칭·OCR을 게임 없이 돌린다 |
| M1 `OcrResult`의 캡처 시점 관측 `window`·`frame_info`, `vision.diff`의 겹치지 않는 영역 = 1 | OCR 줄 상자로 만든 `Match`가 관측을 잃으면 읽은 뒤 창이 바뀌어도 재검증 없이 옛 좌표를 누른다. 비교할 픽셀이 없는 영역을 0(같음)으로 보면 화면 밖 영역이 늘 멈춘 화면이 된다 |
| 다듬기 P1: `ctx.log`의 `Secret`은 워커에서 가리지 않고 비밀값 그대로 runner에 보내고(`ctx.log` RPC의 `message`가 wire 값), 실행 기록에 남길 때 `record.redact_secrets`를 따른다. 비밀값이 든 메시지는 `SecretMessage`(`message_with_secrets`)이고 워커 경계(`ctx.log`의 `message`, `node.invoke` 결과의 `message` = `SecretMessageWire`)에서도 가린 글·원문을 둘 다 옮긴다. 실행에서 처음 `ctx.set_window`한 창은 실행기가 앞으로 가져온다 (타입 표 `secret`) | 사용자 결정 D3(비밀값 가림은 설정으로만, 메시지까지 "전부 그대로")·D1(실행 시작 때 게임 창을 앞으로). 워커가 `str()`로 가리거나 노드가 메시지를 가린 글 하나로만 만들면 runner가 정책을 따를 수 없다 |
