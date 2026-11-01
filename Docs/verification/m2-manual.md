# M2 사람 검증 절차서

M2(에디터) 완료도 M1처럼 두 단계다 ([[구현 계획 v0]] 1장 M2 행).

1. **자동 완료**: 자동 테스트(CI + 잠긴 PC에서도 도는 Electron E2E), 인수 테스트(`python/kookabug_core/tests/acceptance/test_m2.py`, `apps/desktop/e2e/acceptance.spec.ts`), 설치 파일 CI, 이 절차서·결과 양식
2. **최종 완료**: 이 절차서의 **결과**가 결과 양식(`m2-result-template.md`)에 기록되고 모든 항목이 통과 기준을 만족. 한 항목이라도 실패하면 그 항목은 별도 결정(고칠 작업·범위 조정)으로 올리고 최종 완료로 세지 않는다

M1 사람 검증(`m1-manual.md`)이 아직 끝나지 않았다면 그것도 따로 한다. M2는 그 위에 쌓였지만 항목은 겹치지 않는다(아래 D5만 M1 D6과 같은 명령이라 한 번만 돌리면 된다).

절은 여섯이다. 순서대로 하면 D(약 1시간, 대부분 기다림) → V(30분) → E(40분) → T(20분) → S(30분) → U(15분)다.

| 절 | 내용 | 어디서 |
|---|---|---|
| D1~D6 | 잠금 해제 상태에서만 도는 자동 검사, 시안 비교 PNG 만들기 | 레포가 있는 PC |
| V1~V11 | 시안과 앱 화면을 나란히 놓은 비교 PNG 보기 (다크·라이트) | 레포가 있는 PC |
| E1~E9 | 편집 조작감 (개발 빌드 앱) | 레포가 있는 PC |
| T1~T2 | 실제 창으로 target 만들기, 실제 입력으로 실행 | 레포가 있는 PC |
| S1~S6 | NSIS 설치 → 앱 실행 → 제거 (화면으로) | Windows Sandbox |
| U1~U15 | 기본값으로 진행한 사용자 결정 확인 | 어디서든 |

**레포에 두는 것과 두지 않는 것**: 이 절차서와 결과 양식은 레포(공개)에 있다. 결과 `manual_result.md`와 증거 폴더(로그·스크린샷·비교 PNG 사본)는 레포 밖 `.orchestration/M2/`(git 제외)에 둔다.

## 0. 준비 (공통)

PowerShell을 하나 열고 아래를 붙여 넣는다. `$repo`만 자기 레포 위치로 바꾼다. 이 창을 끝까지 쓴다(새 창이면 이 블록을 다시 붙여 넣는다).

```powershell
$repo = "C:\src\Kookabug"                       # 레포 위치로 바꾼다
$ev   = "$repo\.orchestration\M2\manual_evidence" # 증거 폴더 (git에 올리지 않는 폴더)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
New-Item -ItemType Directory -Force $ev | Out-Null
if (-not (Test-Path "$repo\.orchestration\M2\manual_result.md")) {
  Copy-Item "$repo\Docs\verification\m2-result-template.md" "$repo\.orchestration\M2\manual_result.md"
}
cd $repo
uv sync --locked --all-packages; uv run python tools/fetch_ocr_models.py
pnpm install --frozen-lockfile; pnpm --filter @kookabug/desktop exec install-electron
pnpm --filter @kookabug/desktop build
```

- 결과는 `$repo\.orchestration\M2\manual_result.md`에 항목 ID(D1, V3, E5 …)별로 적는다
- **D·T절 동안에는 PC를 쓰지 않는다.** 실제 마우스·키보드 입력을 보내는 검사가 있다. 설정 → 시스템 → 전원의 "화면 끄기"·"절전"을 검사하는 동안 "안 함"으로 둔다

### 예제 워크스페이스 사본과 개발 빌드 앱 (E·T절에서 씀)

E·T절은 레포의 예제를 직접 고치지 않도록 임시 사본을 연다. 아래 첫 블록은 사본을 만든다(게임 실행 설정 `local.json`, 편집 조작용 그래프 사본 `tests/manual_edit.graph.json`, 정지 화면 PNG `captures/`). 두 번째 블록은 비밀값·OCR 모델 위치를 넣고 개발 빌드 앱을 띄운다. 앱을 다시 띄울 때는 두 번째 블록만 붙여 넣는다.

```powershell
# M2 사본 만들기
$kb = "$env:TEMP\kb-m2"
Remove-Item -Recurse -Force $kb -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $kb | Out-Null
Copy-Item -Recurse "$repo\fixtures\sample-game\workspace" "$kb\sample-rpg"
Copy-Item -Recurse "$repo\fixtures\sample-game\frames" "$kb\frames"
Copy-Item "$kb\sample-rpg\tests\inventory_open.graph.json" "$kb\sample-rpg\tests\manual_edit.graph.json"
New-Item -ItemType Directory -Force "$kb\sample-rpg\captures", "$kb\sample-rpg\.kookabug" | Out-Null
Copy-Item "$kb\frames\title.png", "$kb\frames\login.png" "$kb\sample-rpg\captures\"
$local = @{ format = "kookabug.local/0"; settings = @{ "game.cwd" = "$repo\fixtures\sample-game"; "game.executable" = "$repo\.venv\Scripts\python.exe" } }
[IO.File]::WriteAllText("$kb\sample-rpg\.kookabug\local.json", ($local | ConvertTo-Json))   # BOM 없는 UTF-8
```

```powershell
# M2 앱 띄우기
$kb = "$env:TEMP\kb-m2"
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
$env:KOOKABUG_OCR_MODELS = "$repo\build\ocr-models"
pnpm --filter @kookabug/desktop exec electron .
```

- 앱이 뜨면 시작 화면의 "프로젝트 열기"로 `%TEMP%\kb-m2\sample-rpg`를 고른다
- **E3~E6의 편집은 사본 그래프 `tests/manual_edit.graph.json`에서만 한다.** 실행에 쓰는 `tests/inventory_open.graph.json`·`subgraphs/enter_world.graph.json`은 E7 앞의 복구 블록으로 원본과 같게 되돌린 뒤 실행한다
- 앱을 닫아도 daemon은 남는다(정상). 끝나면 `uv run kookabug daemon --workspace "$kb\sample-rpg"`를 띄우지 말고, 작업 관리자에서 `kookabug.exe daemon`을 끝내거나 그냥 둔다(연결·실행이 없으면 10분 뒤 스스로 끝난다)

## 1. 잠금 해제 상태 자동 검사 (D)

화면 잠금이 풀린 상태에서만 도는 검사다(창·WGC 캡처·실제 SendInput). 잠긴 세션이면 탐지가 실패해 `require`에서는 실패, `auto`(기본)에서는 건너뛴다. M2 개발 중에는 PC가 잠겨 있어 이 검사들이 **한 번도 실제로 돌지 않았다**. 레포 루트(`cd $repo`)에서 한다.

### D1 데스크톱 탐지

```powershell
$env:PYTHONPATH = "tools"; uv run python -m kb_testing.desktop | Tee-Object "$ev\d1_probe.txt"; Remove-Item Env:PYTHONPATH
```

- 기대 결과: `결과: **통과**`, 표의 4개(`window_station`·`input_desktop`·`wgc_frame`·`foreground`) 모두 통과
- 기록: 결과, 실패한 항목의 내용 칸

### D2 M2 인수 테스트 (Python, 실제 창 포함)

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"
uv run pytest python/kookabug_core/tests/acceptance/test_m2.py -v 2>&1 | Tee-Object "$ev\d2_acceptance.log"
```

- 기대 결과: 마지막 줄 `17 passed`(실패·건너뜀 0). `test_saved_target_matches_same_frame[desktop]`이 예제 게임 창을 띄워 찍고, 만든 target을 새 캡처에서 다시 찾는다
- 기록: 통과·실패·건너뜀 수, 시간

### D3 daemon 실제 창 검사 (target 캡처·창 목록·프레임)

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"
uv run pytest python/kookabug_daemon/tests/test_target_live.py python/kookabug_platform/tests/test_windows.py fixtures/sample-game/tests/test_frames_fresh.py -v 2>&1 | Tee-Object "$ev\d3_daemon_live.log"
```

- 기대 결과: 전부 통과. `test_windows.py`·`test_frames_fresh.py`는 M2 T4 때 이 PC에서 12개가 환경 사유로 실패했던 검사다(잠금 추정). 잠금을 풀고도 실패하면 검사 이름과 마지막 `AssertionError` 줄을 적는다
- 기록: 통과 수, 실패 이름

### D4 앱 인수·실제 창 target (Electron)

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"
pnpm --filter @kookabug/desktop exec playwright test --project=e2e e2e/acceptance.spec.ts e2e/target.live.spec.ts 2>&1 | Tee-Object "$ev\d4_app.log"
```

- 기대 결과: `5 passed`. `target.live.spec.ts`는 앱의 "창에서 캡처"로 예제 게임 창을 찍어 target을 만들고 실제 창에서 다시 찾는다(M2 T12 때 잠금으로 "2000ms 안에 첫 프레임이 오지 않았다"로 실패)
- 기록: 통과·실패 수

### D5 전체 자동 검사

M1 D6과 같은 명령이다. M1 절차서에서 이미 돌렸고 그 뒤 레포가 바뀌지 않았으면 그 결과를 쓴다. 수십 분 걸린다.

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"; $env:KOOKABUG_SOAK = "1"
uv run pytest 2>&1 | Tee-Object "$ev\d5_full.log"
pnpm --filter @kookabug/desktop e2e 2>&1 | Tee-Object "$ev\d5_e2e.log"
Remove-Item Env:KOOKABUG_DESKTOP_TESTS, Env:KOOKABUG_DESKTOP_INPUT, Env:KOOKABUG_SOAK
```

- 기대 결과: pytest 실패 0, 끝의 "데스크톱 검사" 요약에 `탐지: 통과`·건너뜀 줄 없음. E2E 실패 0
- 기록: pytest 통과·실패·건너뜀 수와 시간, E2E 통과·실패 수

### D6 시안 비교 PNG 만들기

```powershell
node tools/design-ref/render.mjs; node tools/design-ref/extract.mjs
pnpm --filter @kookabug/desktop shots
node tools/design-ref/compare.mjs welcome shell-empty main-canvas main-palette palette-drag connect-drag close-confirm inspector inspector-link main-running target
Copy-Item -Recurse build\ui-compare "$ev\ui-compare"
(Get-ChildItem "$ev\ui-compare\*.png").Count
```

- 기대 결과: 마지막 줄 `22`(화면 11개 × 다크·라이트). `shots`에서 실패 0. 역할 색·치수·글꼴 자동 검사(`shell.metrics.spec.ts`, vitest `tokens.test.ts`)는 D5에서 돌았다
- 기록: PNG 수. 이 PNG가 V절의 재료다

## 2. 시안 대비 화면 (V)

`$ev\ui-compare\<화면>-<테마>.png`를 연다. 왼쪽이 시안(UX 시안 v0.1을 렌더한 것), 오른쪽이 앱이다. 픽셀 일치는 보지 않는다(내용이 다르다). **색·글꼴·크기·자리·모양**이 시안 언어와 같은지, 아래 "의도한 차이" 밖의 차이가 있는지 본다. 화면마다 다크·라이트 둘 다 본다.

공통 의도한 차이(어느 화면이든 차이로 세지 않음):

- 아직 없는 기능의 아이콘·버튼 숨김(U3): 액티비티 바는 탐색기만, 메뉴 "플러그인" 없음, 녹화·디버그 툴바 없음, 하단 패널에 고정 데이터·터미널 없음
- 툴바 "대상" 자리는 실행 프로필 고르기(U4)
- 오른쪽 에이전트 패널 자리는 속성 편집기(U1). 에이전트 패널은 M5
- 탐색기 파일은 예제 워크스페이스라 시안과 이름이 다르다. 본문 글꼴은 Noto Sans KR이 먼저라 영문·숫자 모양이 시안(Segoe UI)과 조금 다르다(U6)

| ID | 화면 (`<id>`) | 시안 | 볼 것 | 이 화면의 의도한 차이 |
|---|---|---|---|---|
| V1 | 시작 화면 (`welcome`) | Setup0Welcome(·Light), 1120×720 | 로고·워드마크(Fraunces)·제목·소개 칩·기본 단추·미리보기 그림 자리, 테마 고르기 | "시작하기" 숨김, "프로젝트 열기"가 기본 단추(U5). 오른쪽 위 창 단추, 테마 고르기는 그 아래 |
| V2 | 앱 틀 (`shell-empty`) | Main(·Light) | 타이틀 바 35px·메뉴·명령 검색 자리, 액티비티 바, 사이드바 머리·줄 높이·들여쓰기, 탭·경로 표시줄, 하단 패널 탭, 상태 바 | 상태 바는 대기 중 무채색(시안은 실행 중 파랑만). 하단 패널이 시안보다 10px 남짓 위에서 시작 |
| V3 | 캔버스 (`main-canvas`) | Main(·Light) | 노드 폭·32px 머리·분류 머리 색, 흐름 삼각·데이터 원 핀과 색, fail 출구 주황 점선, 경고 노드 노랑, 점 격자, 줌 상자·미니맵, 문제 탭 배지 | 핀 이름이 스키마 이름(`found`·`window`), 시안의 "Agent 판단"·"CSV 행 추가"는 실제 노드로 바꿈, 하단은 실행 로그 대신 문제 탭. **남은 차이**: 뒤로 가는 연결선이 노드 밑을 가로지름(시안은 노드를 돌아감) → U14 |
| V4 | 팔레트 (`main-palette`) | Main(·Light) | 사이드바 "노드" 섹션 머리·검색 상자, 묶음 줄·점 색, 노드 줄 글자색, 저장 안 된 탭의 ● | 실제 노드를 다 보이고 스크롤, Agent 묶음 없음(M5), "엔진 연동" 자리는 "플러그인", 탐색기 머리 "+T·+S" |
| V5 | 팔레트에서 끌어 놓기 중 (`palette-drag`) | Main(·Light) (이 상태는 시안 없음) | 강조 색 점선·정보 띠 색이 시안 언어인지 | 시안에 없는 상태 |
| V6 | 핀 잇기 중 (`connect-drag`) | Main(·Light) (이 상태는 시안 없음) | 호환 핀 강조·나머지 흐림 | **남은 차이**: 데이터 연결을 끄는 동안 숨은 입력 핀이 나타나 노드가 길어지고 아래 노드와 겹칠 수 있다 → E3에서 조작감으로 판정 |
| V7 | 닫기 확인 (`close-confirm`) | Main(·Light) (이 상태는 시안 없음) | 대화 상자 표면·테두리·그림자, 기본 단추 강조 색 | 시안에 없는 상태 |
| V8 | 속성 편집기 (`inspector`) | Main(·Light) 에이전트 패널 자리 | 패널 자리·폭·왼쪽 테두리·배경, 35px 머리 줄, 22px 섹션 머리, 26px 입력 상자 | 시안에 없는 화면(U1). **남은 차이**: 핀마다 "값" 고르기 상자가 붙어 빽빽함 → E5 |
| V9 | 속성 편집기, 연결된 핀 (`inspector-link`) | Main(·Light) | 연결 표시·"연결 끊기" 단추가 시안 회색 단추 모양인지 | 시안에 없는 화면(U1) |
| V10 | 실행 중 (`main-running`) | Main(·Light) | 강조 노드 2px 파랑 테두리, 지나간 노드 "✓ Nms" 초록, 반복 "1 / 10,000", 흐린 미실행 노드, 실행 로그 줄 모양, 상태 바 파랑·"▶ 실행 중"·"입력: 실행 #…" | 정지 ■가 탭 줄 툴바에 있음(시안은 디버그 툴바, U3로 숨김) → U10. 실행 ID 8자, 상태 바에 문제 수·창·MCP 칸 없음 |
| V11 | target 편집기 (`target`) | Recorder (라이트 앱도 다크 Recorder와 나란히) | 안내 줄, 정지 화면 판·테두리, 검색 범위 청록 점선, 찾은 상자 노랑·점수 배지, 클릭 지점 빨간 십자, 매칭 미리보기 패널(임계값 슬라이더·색 확인·배율), 9분할 | 왼쪽 녹화 사이드바·REC 탭은 M4, "여러 개면 좌상단부터" 없음(U7), "후보 1개" 대신 "찾음 · 점수 · 배율", 단추는 "창에서 캡처"·"이미지에서"·"저장", 오프셋은 입력 칸 둘 |

- 기록: 화면마다 "의도한 차이 밖의 차이" 목록(없으면 "없음")과 통과(O/X). 고치고 싶은 차이는 결과 양식의 "고칠 것" 표에 적는다

## 3. 편집 조작감 (E)

0절 "예제 워크스페이스 사본과 개발 빌드 앱"으로 앱을 띄우고 `%TEMP%\kb-m2\sample-rpg`를 연다. 항목마다 **기대 결과**대로 되는지와 **느낌**(끊김·헷갈림·불편)을 적는다.

### E1 시작 화면·프로젝트 열기·테마

1. 앱을 닫았다 다시 띄운다("M2 앱 띄우기" 블록만). 시작 화면에 최근 프로젝트 `sample-rpg`가 보인다
2. 시작 화면 오른쪽 위 테마 고르기에서 라이트 → 다크 → 시스템을 차례로 고른다
3. 최근 목록에서 `sample-rpg`를 눌러 연다

- 기대 결과: 테마가 즉시 바뀌고 글자가 깨지지 않는다. 열면 탐색기에 `tests`·`subgraphs`·`targets` 폴더, 상태 바 왼쪽에 연결됨 표시
- 기록: 기대대로인지, 걸린 시간 느낌

### E2 그래프 보기

1. 탐색기 `tests` → `inventory_open.graph.json`을 연다
2. 휠로 확대·축소, 빈 곳 끌기로 이동, 오른쪽 아래 미니맵 누르기, 줌 상자 −·+를 써 본다
3. `subgraphs/enter_world.graph.json`도 연다. 탭을 오가 본다

- 기대 결과: 노드·연결선이 모두 보이고, 확대·이동이 부드럽다. 열기만 해서는 탭에 ●(저장 안 됨)가 생기지 않는다
- 기록: 기대대로인지, 뒤로 가는 연결선(노드 밑을 가로지름)이 읽기에 방해되는지(U14)

### E3 노드 더하기·옮기기·잇기·지우기

E3~E6은 편집 조작용 사본 `tests/manual_edit.graph.json`에서 한다(내용은 `inventory_open`과 같다). 탐색기 `tests` → `manual_edit.graph.json`을 연다.

1. 사이드바 "노드" 검색 칸에 `이미지 대기`를 넣고 그 줄을 캔버스 빈 곳으로 끌어 놓는다
2. 새 노드가 빨간 테두리(오류: 필수 입력 없음)로 보이고, 하단 "문제" 탭에 그 노드 줄이 생긴다. 문제 줄을 누르면 그 노드로 간다
3. "I 키" 노드의 `done` 출구(오른쪽 삼각)를 새 노드의 흐름 입력(왼쪽 삼각)으로 끈다
4. 새 노드의 `match` 출력(원)을 아무 "클릭" 노드의 입력 쪽으로 천천히 끈다. 끄는 동안 맞는 핀만 밝게, 나머지는 흐리게 보인다
5. 노드 머리를 잡고 옮긴다. 노드를 눌러 고르고 Delete로 지운다. 연결선을 눌러 Delete로 지운다

- 기대 결과: 모든 조작이 바로 보이고, 탭에 ●가 생긴다
- 기록: 기대대로인지. **4번에서 숨은 입력 핀이 나타나 노드가 길어지며 아래 노드와 겹치는 것**이 거슬리는지(고칠지 판단, V6)

### E4 실행 취소·저장·닫기 확인

1. E3의 편집을 Ctrl+Z로 하나씩 되돌린다. 모두 되돌리면 탭의 ●가 사라진다. Ctrl+Y로 다시 하고 Ctrl+S로 저장한다
2. 다시 하나 옮긴 뒤 탭의 ×를 누른다 → "저장할까요?" 대화 상자 → 취소. 창 오른쪽 위 닫기(X) → "저장하지 않은 그래프가 1개" → 취소
3. 탐색기 머리 "+T"로 새 테스트 `조작감`을 만든다(시작 노드 하나짜리 그래프가 열린다)

- 기대 결과: 위와 같다. 저장한 파일을 메모장으로 열어 보면 옮긴 노드의 좌표와 바꾼 곳만 다르다
- 기록: 기대대로인지, 단축키·대화 상자가 자연스러운지

### E5 속성 편집기

1. `manual_edit`의 "인벤토리 창 확인" 노드를 고른다. 오른쪽 속성 편집기에 입력이 보인다
2. `timeout_ms`에 `abc`를 넣어 본다(바로 오류 글자), `7000`을 넣고 Enter
3. `target` 칸의 대상 고르기 상자를 연다. 긴 경로가 `targets/title/start_button.ta…`처럼 잘리는지 본다
4. 핀 머리의 "값·설정·대상·비밀" 고르기를 바꿔 본다(바꾸기만 해서는 값이 바뀌지 않고, 새 값을 넣어야 바뀐다)
5. 노드 제목을 바꾼다(ID는 그대로, 노드 머리 글자만 바뀜). 패널 머리 »로 접고, 메뉴 보기 → 속성 패널로 다시 편다

- 기대 결과: 위와 같다
- 기록: 기대대로인지. **긴 target 경로가 잘려 전체를 볼 수 없는 것**, **핀마다 "값" 고르기 상자가 붙어 빽빽한 것**이 불편한지(V8)

### E6 밖에서 바뀐 파일 (충돌 띠)

1. `manual_edit`을 저장된 상태(● 없음)로 둔다. 메모장으로 `%TEMP%\kb-m2\sample-rpg\tests\manual_edit.graph.json`을 열어 `"title"` 글자 하나를 바꿔 저장한다 → 앱이 조용히 다시 연다
2. 앱에서 노드 하나를 옮긴다(● 생김). 메모장에서 다시 글자를 바꿔 저장한다 → 앱 위쪽에 "저장 충돌" 띠
3. "내 편집으로 덮어쓰기"를 누른다. 한 번 더 2를 하고 이번에는 "디스크 버전 다시 열기"를 누른다

- 기대 결과: 1은 띠 없이 다시 열림, 2는 띠, 3은 각각 내 편집 저장 / 디스크 내용으로 되돌림(편집 버림 확인을 묻는다)
- 기록: 기대대로인지, 띠 문구가 이해되는지

### E7 실행·정지 (가짜 플랫폼 아님: 실제 게임)

먼저 실행할 그래프를 원본으로 되돌린다. 앱의 탭에 ●가 있으면 "저장 안 함"으로 닫은 뒤, 0절 PowerShell 창에서:

```powershell
# M2 실행 그래프 복구
$kb = "$env:TEMP\kb-m2"
Copy-Item -Force "$repo\fixtures\sample-game\workspace\tests\inventory_open.graph.json" "$kb\sample-rpg\tests\"
Copy-Item -Force "$repo\fixtures\sample-game\workspace\subgraphs\enter_world.graph.json" "$kb\sample-rpg\subgraphs\"
```

열려 있던 깨끗한 탭은 바뀐 파일을 조용히 다시 연다(E6과 같음).

1. `inventory_open`을 연 채 툴바 프로필이 "기본"인지 보고 ▶(F5)를 누른다. **실행 중에는 마우스·키보드를 건드리지 않는다**
2. 예제 게임 창이 떠서 타이틀 → 로그인 → 서버 선택 → 월드 → 인벤토리로 간다. 앱에서는 지금 노드만 파란 테두리, 지나간 노드는 "✓ 시간", 하단 "실행 로그"가 위로 쌓이고, 상태 바가 파랑 + "입력: 실행 #…"
3. 끝나면 툴바에 판정 pass. 한 번 더 ▶를 누르고 몇 초 뒤 툴바의 ■(정지)를 누른다
4. 메뉴 "실행"을 연다: 실행 중이 아니면 "실행 F5"만 켜져 있다. "실행 F5"를 눌러 실행하고, 실행 중에 메뉴를 다시 열면 "실행 F5"는 꺼지고 "정지 Shift+F5"가 켜져 있다. 그것을 눌러 멈춘다. 이어서 키보드 F5로 실행하고 Shift+F5로 멈춘다

- 기대 결과: 첫 실행 pass, 두 번째는 취소로 끝나고 게임 창이 닫힌다(또는 남은 창을 직접 닫는다). 정지 뒤 눌린 키가 남지 않는다. 메뉴 실행·정지와 F5·Shift+F5가 툴바 ▶·■와 같이 켜지고 꺼지며 같은 동작을 한다
- 기록: 판정, 걸린 시간, 메뉴·단축키가 툴바와 같았는지, **■ 정지 단추가 탭 줄 툴바에 있는 것**이 찾기 쉬운지(U10)

### E8 저장 안 된 그래프 실행

1. `inventory_open`에서 노드 하나를 옮겨 ●를 만든 뒤 ▶를 누른다(옮기기는 좌표만 바꾸므로 실행 결과는 그대로다)

- 기대 결과: 먼저 저장(●가 사라짐)한 뒤 실행하고 pass(U2)
- 기록: 기대대로인지, 묻지 않고 저장하는 것이 괜찮은지(U2)

### E9 라이트 테마로 다시 보기

1. 메뉴 보기 → 라이트. E2·E3·E5·E7 화면을 한 번씩 다시 본다

- 기대 결과: 모든 글자·핀·강조 색이 라이트 배경에서 읽힌다
- 기록: 읽기 어려운 곳

## 4. 실제 창 target (T)

0절 블록으로 앱이 떠 있는 상태에서 한다. **실제 마우스·키보드 입력이 나간다.**

### T1 창에서 찍어 target 만들기

1. 새 PowerShell에서 예제 게임을 띄운다: `cd $repo\fixtures\sample-game; uv run --project $repo python -m sample_game` (제목 "SampleRPG" 창, 타이틀 화면)
2. **임계값 미리보기 확인(다른 화면의 대상)**: 탐색기 `targets/login/account_field.target.json`(로그인 화면의 계정 칸)을 연다. 안내 줄 "이미지에서" → `captures/title.png` → 열기. 타이틀 화면에는 계정 칸이 없어 미리보기가 "못 찾음 · 최고 점수 0.6…"이다. 임계값 슬라이더를 왼쪽 끝(0.50)으로 옮기면 "찾음 · 점수 0.6…", 오른쪽 끝(0.99)으로 옮기면 다시 "못 찾음"이 된다. 탭을 닫고 저장할지 물으면 "저장 안 함"(이 대상 파일은 그대로 둔다)
3. 앱에서 `subgraphs/enter_world.graph.json`을 열고 "타이틀 대기" 노드를 고른다. 속성 편집기 `target` 칸의 "새 대상 만들기" → 이름 `manual/start` → 만들기. TARGET 탭이 열린다
4. 안내 줄 "창에서 캡처" → 목록에서 SampleRPG 고르기. 게임 화면이 정지 화면으로 들어온다
5. "게임 시작" 단추를 끌어 템플릿 영역을 고른다. Shift+끌기로 그 둘레를 검색 범위로 고른다. 단추 안 한 점을 눌러 클릭 지점을 정하고, 9분할에서 다른 칸을 눌러 본다
6. 임계값 슬라이더를 끝까지 올렸다 내려 본다. 같은 정지 화면에서 자른 영역이라 점수가 1.00이어서 **어느 임계값에서도 "찾음 · 점수 1.00"이 유지된다**(전환은 2에서 봤다). 슬라이더를 처음 값(새 대상의 기본 0.85)으로 되돌린다. "색까지 확인"·"배율" 옵션을 껐다 켠다(끝에는 처음처럼 켠 상태)
7. 저장한다

- 기대 결과: 2는 위와 같이 찾음·못 찾음이 바뀐다. 저장 뒤 "바로 매칭: 찾음 · 점수 …" 띠, 찾은 상자가 고른 영역과 겹친다. `%TEMP%\kb-m2\sample-rpg\targets\manual\`에 `start.target.json`과 PNG가 생긴다. "타이틀 대기" 칸에 새 대상(`targets/manual/start.target.json`)이 들어가 `enter_world` 탭에 ●가 생긴다
- 기록: 기대대로인지, 끌기·Shift·클릭 조작이 헷갈리지 않는지, 화면 배율(설정 → 디스플레이)이 100%가 아니면 그 값

### T2 만든 target으로 실행

1. `enter_world` 탭(●)을 Ctrl+S로 저장한다. T1에서 띄운 게임 창을 닫는다(실행이 게임을 새로 띄운다)
2. `tests/inventory_open.graph.json` 탭에서 ▶를 누른다(월드 접속 = `enter_world` 호출). 실행 중에는 마우스·키보드를 건드리지 않는다

- 기대 결과: 게임이 떠서 "타이틀 대기"가 T1에서 만든 target으로 시작 단추를 찾고, "시작 버튼 클릭"이 그 자리(T1에서 정한 클릭 지점)를 눌러 끝까지 가서 pass. 실패하면 하단 실행 로그의 실패 노드와 메시지를 적는다
- 기록: 판정, 실패면 노드·메시지

## 5. 설치본 (S)

M1 S절과 같은 Windows Sandbox를 쓴다(Sandbox 켜기는 `m1-manual.md` S1). 이번에는 **화면으로** 설치·제거하고 앱을 띄운다.

### S1 설치 파일 준비

```powershell
$env:PYTHONPATH = "tools"; uv run python -m installer.build; Remove-Item Env:PYTHONPATH
$setup = Get-ChildItem build\installer\dist\kookabug-setup-*.exe | Where-Object Name -notlike "*-test-*"
"$($setup.Name) $($setup.Length)"
```

(또는 CI `installer` 잡 artifact의 `kookabug-setup-<버전>.exe`를 받는다.)

- 기록: 이름과 크기(바이트). 지금 묶음은 zip이라 약 262 MiB다(U11)

### S2 Sandbox 시작

```powershell
New-Item -ItemType Directory -Force C:\kookabug-m1\in, C:\kookabug-m1\out | Out-Null
Remove-Item C:\kookabug-m1\in\* -ErrorAction SilentlyContinue
Copy-Item $setup.FullName C:\kookabug-m1\in\
Copy-Item Docs\verification\m1-sandbox.wsb C:\kookabug-m1\
Start-Process C:\kookabug-m1\m1-sandbox.wsb
```

- Sandbox 바탕 화면에 `kookabug-in`(읽기 전용)·`kookabug-out`(쓰기)이 붙는다. 네트워크는 꺼져 있다

### S3 화면으로 설치

Sandbox 안에서 `kookabug-in`의 설치 파일을 더블클릭한다.

1. SmartScreen이 막으면 "추가 정보 → 실행"(코드 서명 전). 막혔는지 적는다
2. **관리자 권한(UAC) 창이 뜨지 않아야 한다.** "모든 사용자/나만" 고르는 설치 범위 화면이 없어야 한다
3. 설치 폴더 화면에서 "찾아보기"로 다른 폴더를 골라 본 뒤 기본(`%LOCALAPPDATA%\Programs\Kookabug`)으로 되돌린다. 폴더 칸에 아주 긴 경로(예: `C:\` 뒤에 `a`를 150자)를 넣으면 "다음"이 막히는지 본다. 기본 폴더로 설치한다
4. 끝나면 시작 메뉴에 "Kookabug"가 있고, **바탕 화면에는 바로 가기가 없다**(U12)

- 기록: SmartScreen 여부, UAC 여부, 설치 범위 화면 여부, 긴 경로에서 "다음" 막힘, 시작 메뉴·바탕 화면 바로 가기, 걸린 시간

### S4 설치본 앱 실행

1. 시작 메뉴 → Kookabug. 시작 화면이 뜬다(UAC 없음)
2. 앱을 닫고 Sandbox의 PowerShell에서 예제를 복사한 뒤 가짜 플랫폼으로 앱을 띄운다(Sandbox의 가상 GPU에서는 실제 캡처가 안 될 수 있어 가짜 플랫폼으로 본다):

```powershell
$app = "$env:LOCALAPPDATA\Programs\Kookabug"
$out = "$HOME\Desktop\kookabug-out"
Copy-Item -Recurse "$app\examples\sample-game" "$HOME\Documents\sample-game"
$fake = "$HOME\Documents\sample-game\workspace\fake-platform.json"
$env:KOOKABUG_DAEMON_ARGS = ConvertTo-Json -Compress @("--platform-fake", $fake)
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
& "$app\Kookabug.exe"
```

3. "프로젝트 열기"로 `문서\sample-game\workspace`를 연다. `tests/smoke_headless.graph.json`을 열고 ▶. 이어서 `tests/inventory_open.graph.json`도 ▶
4. 앱을 닫고 `kookabug doctor --profile headless | Out-File -Encoding utf8 "$out\s4_doctor.txt"; "종료 코드 $LASTEXITCODE"`

- 기대 결과: 두 실행 모두 pass, doctor 종료 코드 0
- 기록: 판정 둘, doctor 종료 코드, 화면이 개발 빌드(E절)와 같아 보이는지

### S5 제거

1. 설정 → 앱 → 설치된 앱 → "Kookabug" → 제거. 앱이 떠 있으면 먼저 닫으라고 하거나 닫는다
2. 새 PowerShell에서:

```powershell
$out = "$HOME\Desktop\kookabug-out"
@(
  "폴더 남음: $(Test-Path "$env:LOCALAPPDATA\Programs\Kookabug")"
  "PATH 항목: $(([Environment]::GetEnvironmentVariable('Path','User') -split ';') -like '*Kookabug*')"
  "명령 찾음: $([bool](Get-Command kookabug -ErrorAction SilentlyContinue))"
  "시작 메뉴: $([bool](Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu" -Recurse -Filter 'Kookabug*.lnk'))"
) | Tee-Object "$out\s5_uninstall.txt"
```

- 기대 결과: `폴더 남음: False`, `PATH 항목:` 뒤가 비어 있음, `명령 찾음: False`, `시작 메뉴: False`. 복사한 `문서\sample-game`은 남는다(사용자 파일)
- 기록: 네 줄. Sandbox를 닫기 전에 `kookabug-out`을 호스트 `$ev\sandbox`로 복사한다(`Copy-Item -Recurse C:\kookabug-m1\out "$ev\sandbox"`)

### S6 (선택) PowerShell이 막힌 PC

설치·제거는 설치 폴더 안 프로세스를 끄려고 PowerShell을 부른다. 회사 정책 등으로 PowerShell이 막힌 PC가 있으면 거기서 S3를 해 본다.

- 기대 결과: 앱 끄기 확인을 못 하면 설치가 "멈춤"(종료 코드 9) 안내로 끝나고 아무것도 바꾸지 않는다
- 기록: 해 봤는지, 결과. 그런 PC가 없으면 "-"

## 6. 사용자 결정 확인 (U)

M2는 아래 결정을 **기본값으로 진행**했다. 각 항목을 위 절에서 직접 본 뒤 "그대로" 또는 "바꿈(어떻게)"을 적는다. 바꾸면 다음 작업으로 올린다.

| ID | 결정할 것 | 지금 기본값 | 어디서 봄 | 대안 |
|---|---|---|---|---|
| U1 | 속성 편집기 위치·모양 (시안에 없음) | 오른쪽 패널 320px(에이전트 패널 자리, 접기 가능), 사이드바와 같은 섹션·입력 상자 모양. M5에서 에이전트 패널과 탭으로 나눔 | V8·E5 | 아래 패널, 떠 있는 창 |
| U2 | 저장 안 된 그래프를 실행할 때 | 자동 저장 뒤 실행 | E8 | 묻기, 저장된 판으로 실행 |
| U3 | M2에 없는 기능의 버튼·아이콘 | 숨김 (해당 단계에서 붙임) | V2·V3 | 비활성으로 보이기 |
| U4 | 툴바 "대상" 자리 | 실행 프로필(`kookabug.json`의 `profiles`) 고르기 | V10·E7 | 창 고르기 |
| U5 | 시작 화면 "시작하기"(새 프로젝트 마법사) | 숨김. "프로젝트 열기"·최근 목록만 | V1·E1 | 비활성으로 보이기 |
| U6 | 글꼴을 앱에 넣고 OFL-1.1 허용 | Noto Sans KR·JetBrains Mono·Fraunces를 넣음, OFL-1.1은 글꼴 파일에 한해 허용 | V1~V11 | 시스템 글꼴(맑은 고딕·Cascadia Mono) |
| U7 | Recorder 시안의 "여러 개면 좌상단부터" | 넣지 않음(target 형식·매칭에 그 뜻이 없음) | V11·T1 | 스키마 4장·찾기 규칙을 바꿔 넣기 |
| U8 | Electron `ffmpeg.dll`(LGPL-2.1) | Electron 판·경로·sha256에 묶은 한정 예외로 허용, NOTICES에 원문, 대응 소스 위치 `licenses/ffmpeg-SOURCE.txt` | S4(설치 폴더 `licenses\`) | — (Electron은 이 DLL 없이 뜨지 않는다) |
| U9 | M1 사람 검증 전에 M2 시작 | 그대로 시작했다. M1 사람 검증은 따로 | `m1-manual.md` | — (이미 지난 일, 확인만) |
| U10 | 정지 ■ 단추 위치 | 탭 줄 툴바(프로필·▶ 옆). 시안은 디버그 툴바에 있는데 U3로 툴바를 숨겼다 | V10·E7 | 디버그 툴바를 M3에 붙일 때 옮기기 |
| U11 | 설치 파일 묶음 | zip 약 262 MiB, LGPL 플러그인 없음 | S1 | 7z 약 187 MiB(설치 파일 안에 nsis7z = 7-Zip LGPL-2.1 플러그인, 설치 폴더에는 남지 않음. 고정 예외 하나를 더해야 함) |
| U12 | 바탕 화면 바로 가기 | 만들지 않음(시작 메뉴만) | S3 | 만들기, 설치 화면에서 고르기 |
| U13 | ffmpeg 소스 제공 약속 문구 | `licenses/ffmpeg-SOURCE.txt`: "주소를 쓸 수 없게 되면 Kookabug 프로젝트 저장소에 이슈로 요청하면, 이 배포본을 받은 날부터 3년 동안 같은 판의 소스를 받을 수 있는 방법을 알려 준다" — 프로젝트 이름으로 하는 약속 | `tools/third_party_licenses/ffmpeg-SOURCE.txt` | 문구 고치기, 소스 사본을 함께 배포 |
| U14 | 뒤로 가는 연결선 모양 | React Flow 기본 곡선(노드 밑을 가로지름). 미룸 | V3·E2 | 시안처럼 노드를 돌아가게(다듬기 또는 M3) |
| U15 | 새 target 만드는 곳 | 속성 편집기 `target` 칸의 "새 대상 만들기"에서만. 사이드바·메뉴 단추 없음(미룸) | T1 | 사이드바 "새 찾기 대상" 단추 |

## 7. 정리와 판정

1. `manual_result.md`의 모든 행에 결과 값·증거 경로·통과(O/X)를 채운다. U절은 "그대로/바꿈"을 적는다(통과 칸 대신)
2. 판정
   - D·V·E·T·S가 모두 O이고 U에 "바꿈"이 없다 → **M2 최종 완료**
   - X가 있거나 U에 "바꿈"이 있다 → "별도 결정·고칠 것" 표에 적는다. 고칠 작업은 다음 마일스톤 계획에 넣는다(바꿈 항목이 다음 작업으로 미뤄도 되는 것이면 그렇게 적고 최종 완료로 셀 수 있다)
3. 증거 폴더 `$ev`와 `manual_result.md`는 레포에 올리지 않는다(`.orchestration/`은 git 제외 폴더)
