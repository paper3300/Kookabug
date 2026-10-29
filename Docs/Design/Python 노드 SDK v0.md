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
from kookabug_sdk import node, Exit, Result, Context
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
    while not deadline.passed:
        ctx.check_cancel()
        frame = ctx.capture()
        match = ctx.vision.find(frame, target)
        if match:
            return Result.ok("found", match=match)
        ctx.sleep(100)
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
- **`effects={"capture", "input", "process"}`**: 게임에 영향을 주는 동작을 선언한다. 선언하지 않은 효과를 `ctx`로 쓰면(`capture` → `ctx.capture`, `input` → `ctx.input.*`) `error`. 노드 효과는 `[tool.kookabug].permissions`에도 있어야 한다 (빌드 오류)
- 순수 노드(exec 없음)는 `@node(..., pure=True)`. 출구가 없고 출력 dict(`{"result": ...}`)를 반환한다. `effects`·`retry`·`assertion`을 쓸 수 없다
- 재시도 가능 여부는 `@node(..., retry=Retry.observation(on=["timeout"]))`로 선언한다. 생략하면 `never`. `on`은 선언한 fail 출구(동적 출구는 `extra`)만 된다. `effects`에 `input`이나 `process`가 있는 노드는 `observation`으로 선언할 수 없다 (빌드 오류) → [[그래프 JSON 스키마 v0]] 6장
- **`assertion=True`**: 검증 노드. 판정 5행("검증 노드가 하나 이상 성공")과 "연결 안 된 `ok` 출구 경고 예외"는 이 표시로 정한다 → [[그래프 JSON 스키마 v0]] 2장
- **`engine="<이름>"`**: 실행기가 직접 처리하는 노드 (`core.graph.*`, `core.test.*`, `core.flow.repeat`·`while`). SDK로 선언만 하고 함수 본문은 호출되지 않는다. `core` 플러그인만 쓸 수 있다 (빌드 오류). 출구 없는 exec 노드(종료 노드)도 `engine` 노드만 된다
- **`FromInterface("inputs" | "outputs" | "exits")`**: 핀·출구를 그래프 `interface`에서 만든다. `core.graph.entry`의 출력 = `interface.inputs`, `core.graph.exit`의 입력 = `interface.outputs`, `core.graph.call`의 입력·출력·출구 = 부르는 서브그래프의 `interface`. interface에서 온 출력은 출구의 `outputs`에 이름으로 적지 않는다 (서브그래프 출력은 모든 출구에서 주어진다). **`engine` 노드만** 쓸 수 있다 (빌드 오류). interface 핀·출구는 실행기만 해석하므로, 일반 노드에 허용하면 결과(출구·출력) 검사를 할 수 없다
- 입력 노드는 `ctx.input`이 입력 직전에 관측값 세대를 확인하고 필요하면 다시 매칭한다. 노드 코드가 따로 할 일은 없다

---

## 핀 타입

| 타입 | Python | 비고 |
|---|---|---|
| `bool`, `int`, `float`, `string` | `bool`, `int`, `float`, `str` | |
| `secret` | `Secret` | 값을 꺼내려면 `.reveal()`. `str()`·로그·결과에는 가려진다 |
| `target` | `Target` | `*.target.json` |
| `match` | `Match` | 위치, 점수, 창 ID, 캡처 프레임 번호 |
| `rect`, `point` | `Rect`, `Point` | 클라이언트 영역 기준 |
| `image` | `Image` | 기록에는 파일로 저장. `ctx.capture`가 준 이미지에는 러너가 캡처 번호(`capture_id`)를 붙인다. 기록 정책이 이 번호로 "얻을 때 허용됐는가"를 보므로 노드는 받은 이미지를 그대로 넘긴다 (값 비교에는 들지 않는다) |
| `window`, `process` | `WindowRef`, `ProcessRef` | 유효성 확인 가능 |
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
| 현재 대상 창 | `ctx.window` |
| 캡처 | `ctx.capture(region=None)` |
| 이미지·OCR 엔진 | `ctx.vision.find(...)`, `ctx.ocr.read(...)` |
| 입력 | `ctx.input.click(...)`, `ctx.input.key(...)` (입력 직전 창 유효성·포그라운드 확인 포함) |
| 기록 | `ctx.log.info(...)`, `ctx.artifacts.save(image, name) -> str \| None` (실행 폴더 기준 경로. 기록 정책으로 생략하면 `None`) |
| 시간·취소 | `ctx.deadline(ms)`, `ctx.sleep(ms)`, `ctx.check_cancel()` |
| 워크스페이스 | `ctx.setting(key)`, `ctx.path(rel)` |
| 노드 설정 | `ctx.config` (그래프 노드의 `config` 값) |
| 변수 | `ctx.vars.get(name, default)`, `ctx.vars.has(name)`, `ctx.vars.set(name, value)` (호출 프레임 변수) |

**순수 노드의 `ctx`** (부작용 금지 → [[그래프 JSON 스키마 v0]] 7장)

| 막힘 | 됨 |
|---|---|
| `ctx.capture`, `ctx.input`의 모든 메서드, `ctx.artifacts`의 모든 메서드, `ctx.log`의 모든 메서드(`debug`·`info`·`warn`·`error`), `ctx.sleep`, `ctx.vars.set` | `ctx.vars.get`·`has`, `ctx.config`, `ctx.window`, `ctx.setting`, `ctx.path`, `ctx.deadline`, `ctx.check_cancel` |

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

## 노드 버전

- 입력·출구·출력 의미가 바뀌면 `version`을 올린다. 그래프는 노드마다 `version`을 기록한다
- 플러그인은 옛 버전 그래프를 새 버전으로 옮기는 함수를 줄 수 있다: `@node(..., migrations={1: migrate_v1})`
- 옮기지 못하면 실행 전 검증에서 막고, 옛 버전 플러그인으로 실행하라고 안내한다

## 이후 버전

- 비동기(`async def`) 노드
- 노드 단위 병렬 실행
- 노드 하나에 Python 외 언어(실행 파일) 연결
