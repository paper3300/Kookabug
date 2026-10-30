# 예제 게임 SampleRPG

Kookabug의 테스트·CI·문서 예시가 쓰는 작은 가짜 게임이다. 표준 라이브러리 tkinter만 쓰고, 특정 게임을 흉내 내지 않는 평면 도형과 글자로 그린다.

```
타이틀 ─시작─▶ (점검 팝업) ─▶ 로그인 ─로그인─▶ (로그인 오류 팝업) / 로비 ─서버·입장─▶ 로딩 ─▶ 월드 ─I─▶ 인벤토리
```

## 실행

레포 루트에서:

```powershell
$env:PYTHONPATH = "fixtures/sample-game"
uv run python -m sample_game --event-log build/sample-game.jsonl
```

맞는 계정은 `qa_tester_01` / `sample-pass-01`(옵션으로 바꿀 수 있다).

| 옵션 | 뜻 |
|---|---|
| `--maintenance` | 시작을 누르면 점검 팝업 (확인 → 타이틀) |
| `--login-fail` | 로그인이 항상 실패 (오류 팝업) |
| `--slow-loading MS` | 월드 로딩 화면 시간 (기본 400) |
| `--size WxH` | 클라이언트 크기 (기본 1024x640). 배치는 비율을 지켜 늘리고 남는 곳은 배경 |
| `--dpi-awareness unaware\|system\|pmv2` | DPI 인식 (기본 `pmv2`) |
| `--title` | 창 제목 (기본 `SampleRPG`) |
| `--event-log FILE` | 입력 수신 기록 JSONL |
| `--account`·`--password` | 맞는 계정·비밀번호 |
| `--seed N` | 골드 값·인벤토리 배치 (0 = 기본 그림, 골드 12,345) |
| `--second-window` | 같은 프로세스의 독립 최상위 창(`<제목> Chat`, 소유자 없음) |
| `--owned-popup` | 메인 창이 소유한 팝업(`<제목> Notice`, transient). 메인 클라이언트 왼쪽 위 (40, 40)에 겹친다 |
| `--recreate-after MS` | MS 뒤 메인 창을 닫고 같은 제목으로 한 번 다시 만든다 (게임 상태는 이어짐) |

테스트용 숨은 옵션: `--start-scene <장면>`(그 장면의 대표 상태로 시작), `--font <글꼴>`(기본 `Malgun Gothic`).

- 결정성: 애니메이션 없음, 글자 크기는 픽셀 단위(DPI와 무관). 같은 상태 = 같은 그림
- 팝업(점검·로그인 오류·인벤토리)은 같은 Canvas 안에 그린다 — 창 캡처에 찍힌다. 보조 창 두 개만 실제 별도 창이다
- 글꼴 `Malgun Gothic`이 없으면 종료 코드 3

키: 로그인 `Tab`(다음 칸)·`Backspace`·`Enter`(로그인), 팝업 `Enter`(확인, 오류 팝업은 `Esc`도), 월드 `I`(인벤토리), 인벤토리 `I`·`Esc`(닫기). 클릭은 왼쪽 버튼을 **뗄 때** 그 자리의 버튼으로 판정한다.

## 입력 수신 기록 (`--event-log`)

한 줄에 JSON 하나, 쓰자마자 `flush`한다. 테스트는 이 기록을 "게임이 실제로 받았다"의 증거로 쓴다. 공통 필드 `seq`(1부터)·`ms`(시작 뒤)·`event`.

| event | 필드 |
|---|---|
| `ready` | `pid`, `hwnd`(메인 창), `title`, `client_size`, `dpi`, `dpi_awareness`, `font`, `windows`(`second`·`popup` → hwnd), `recreated` |
| `screen` | `scene`(아래 장면 이름), `screen`, `popup` — 그 장면을 다 그린 뒤 |
| `key_down` · `key_up` | `window`(`main`·`second`·`popup`), `key`(kookabug 키 이름), `keysym`, `vk`, `repeat`(down만) |
| `char` | `window`, `text`(글자 하나). Tk가 키 이벤트 하나에 글자 여러 개를 합쳐 주면 글자마다 한 줄 |
| `mouse_down` · `mouse_up` | `window`, `button`(`left`·`middle`·`right`), `x`, `y`(클라이언트 좌표) |
| `wheel` | `window`, `delta`, `x`, `y` |
| `focus` | `window`, `focused` |
| `resize` | `client_size` |
| `recreate` · `window_closed` · `fatal` · `exit` | 창 다시 만들기 · 보조 창 닫힘 · 시작 실패(`reason`) · 정상 종료 |

## 헤드리스 자료 (`frames/`)

장면: `title`, `maintenance`, `login`, `login_error`, `lobby`, `lobby_server1`, `lobby_server2`, `loading`, `world`, `inventory`.

- `frames/<장면>.png`: 1024x640·Per-Monitor V2로 띄운 실제 창을 WGC로 캡처한 클라이언트 영역. 그림이나 배치를 바꾸면 `uv run python fixtures/sample-game/tools/snap_frames.py`로 다시 찍는다(대화형 데스크톱 필요). `tests/test_frames_fresh.py`가 지금 그림과 같은지 검사한다
- `frames/scenario.json`: 가짜 플랫폼(`FakeScenario`)용 장면 전이 표. 상태 기계(`sample_game/flow.py`)와 버튼 배치(`sample_game/layout.py`)에서 `uv run python fixtures/sample-game/tools/gen_scenario.py`가 만든다. `tests/test_scenario.py`가 게임 코드와 같은지 검사한다. 형식은 `sample_game/scenario.py` 맨 위 설명

로그인 칸은 표의 `forms`가 게임과 같은 규칙(칸 클릭·Tab·Backspace·글자 붙이기·최대 길이, 오류 뒤 비밀번호 비우기)으로 따라가고, 로그인 전이는 칸 값이 기본 계정(`qa_tester_01` / `sample-pass-01`)과 같을 때만 로비로 간다(`when.valid`). 글자를 안 넣거나 칸이 틀리면 헤드리스에서도 로그인 오류가 된다. `--account`·`--password`로 바꾼 값은 표에 반영되지 않는다. 표의 실행 가능한 기준 해석은 `sample_game.scenario.Simulator`이고, `tests/test_scenario.py`가 실제 상태 기계와 무작위 입력으로 대조한다.

## OCR 표본 (`ocr-samples/`)

`ocr-samples/truth.jsonl`: 위 화면 PNG(`../frames/`)의 영역과 정답 문자열. OCR 정확도·속도를
`uv run python tools/ocr_bench.py fixtures/sample-game/ocr-samples`로 잰다(형식은 `tools/ocr_bench.py`
맨 위 설명). 화면 그림이나 글자를 바꾸면 정답과 영역도 맞춘다.

## 테스트

```powershell
uv run pytest fixtures/sample-game/tests tools/tests/test_sample_game_helper.py
```

창이 필요한 검사는 `desktop` 표시다(`KOOKABUG_DESKTOP_TESTS`). 테스트 코드는 `kb_testing.sample_game.launch_sample_game`으로 게임을 테스트 세션 Job 안에서 띄우고 `wait_event`·`wait_screen`으로 기다린다.
