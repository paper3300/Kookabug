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
- 출력 핀은 `Result`에 넘긴 키워드로 정해지고, 스키마에는 `outputs=`로 선언한다 (아래)
- `Result.ok(출구, **출력)` / `Result.fail(출구, message=..., **출력)`. 선언하지 않은 출구를 반환하면 `error`
- 예외가 나면 `error`. 러너가 예외 내용과 마지막 스크린샷을 기록한다
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
)
def wait_any(ctx: Context, targets: dict[str, Target], timeout_ms: int = 10000) -> Result:
    ...
```

- `config`: 연결할 수 없는 노드 설정. 노드 모양(출구·핀)을 바꿀 수 있다
- `DynamicExits`: 설정값으로 출구를 만든다. 스키마 JSON에는 "config.exits에서 만든다"는 규칙으로 들어간다
- 순수 노드(exec 없음)는 `@node(..., pure=True)`. 출구가 없고 출력만 반환한다
- 재시도 가능 여부는 `@node(..., retry=Retry.observation(on=["timeout"]))`로 선언한다. 생략하면 `never`. 게임에 영향을 주는 노드(입력·실행)는 `observation`으로 선언할 수 없다 (빌드 오류) → [[그래프 JSON 스키마 v0]] 6장
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
| `image` | `Image` | 기록에는 파일로 저장 |
| `window`, `process` | `WindowRef`, `ProcessRef` | 유효성 확인 가능 |
| `list[T]`, `dict[str, T]` | 같음 | |
| `any` | `Any` | 연결 검사를 하지 않음. 가급적 쓰지 않는다 |
| `A\|B` (유니온) | `A \| B` | 예: `str \| Secret` → `string\|secret`. 평문과 비밀을 다 받는 입력. `secret` 값은 `secret`을 포함한 핀에만 연결된다 |

플러그인 고유 타입은 `플러그인ID.타입명`으로 등록한다. 예: `unreal.ActorRef`

---

## `ctx`가 주는 것

| 기능 | 예 |
|---|---|
| 현재 대상 창 | `ctx.window` |
| 캡처 | `ctx.capture(region=None)` |
| 이미지·OCR 엔진 | `ctx.vision.find(...)`, `ctx.ocr.read(...)` |
| 입력 | `ctx.input.click(...)`, `ctx.input.key(...)` (입력 직전 창 유효성·포그라운드 확인 포함) |
| 기록 | `ctx.log.info(...)`, `ctx.artifacts.save(image, name)` |
| 시간·취소 | `ctx.deadline(ms)`, `ctx.sleep(ms)`, `ctx.check_cancel()` |
| 워크스페이스 | `ctx.setting(key)`, `ctx.path(rel)` |

- 오래 걸리는 노드는 `ctx.check_cancel()`을 자주 부른다. 응답하지 않으면 러너가 워커 프로세스를 종료한다 (취소 순서는 [[구현 계획 v0]] 3장)
- 스크린샷·텍스트 기록은 반드시 `ctx.artifacts`/`ctx.log`를 거친다. 기록 정책(비밀값 생략, 구간 끄기)이 여기서 집행된다. 노드가 파일을 직접 쓰지 않는다
- 플러그인이 `ctx`를 거치지 않고 OS를 직접 건드릴 수는 있다. 막지 못하므로 매니페스트에 권한을 선언하게 하고 설치할 때 보여 준다

---

## 플러그인 프로젝트

```
kookabug-plugin-sample/
├─ pyproject.toml                 [project] + [tool.kookabug]
├─ src/kookabug_plugin_sample/
│  ├─ __init__.py
│  └─ nodes.py
├─ kookabug/schema.json            `kookabug-sdk build`가 만든다. 배포에 포함
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
- `permissions` 후보: `capture`, `input`, `process`, `filesystem`, `network`, `secrets`. 설치 화면에 표시한다
- 의존성은 `dependencies`로 선언하고 uv로 설치한다. venv는 기본 공유, 충돌하면 그 플러그인만 격리 venv. 워커 프로세스는 venv와 별개로 **실행마다 새로** 띄운다 → [[구현 계획 v0]] 3장

## 명령

| 명령 | 하는 일 |
|---|---|
| `kookabug-sdk new` | 플러그인 템플릿 생성 |
| `kookabug-sdk build` | 노드를 읽어 `kookabug/schema.json` 생성. 출구·타입 선언 오류 검사 |
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

## 노드 버전

- 입력·출구·출력 의미가 바뀌면 `version`을 올린다. 그래프는 노드마다 `version`을 기록한다
- 플러그인은 옛 버전 그래프를 새 버전으로 옮기는 함수를 줄 수 있다: `@node(..., migrations={1: migrate_v1})`
- 옮기지 못하면 실행 전 검증에서 막고, 옛 버전 플러그인으로 실행하라고 안내한다

## 이후 버전

- 비동기(`async def`) 노드
- 노드 단위 병렬 실행
- 노드 하나에 Python 외 언어(실행 파일) 연결
