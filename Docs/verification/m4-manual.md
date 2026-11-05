# M4 사람 확인 절차서

M4(녹화) 완료도 두 단계다 ([[구현 계획 v0]] 1장 M4 행).

1. **자동 완료**: CI 자동 검사(가짜 각본 녹화 — 논리 증명), 인수 테스트(`python/kookabug_core/tests/acceptance/test_m4.py`, `apps/desktop/e2e/acceptance.m4.spec.ts`), 잠금 해제 개발자 PC의 실제 훅·실제 캡처 검사(`desktop_input`, 검사 표식 입력), 시안 비교 PNG 세트, 이 절차서·결과 양식
2. **최종 완료**: 이 절차서의 결과가 결과 양식(`m4-result-template.md`)에 기록되고 모든 항목이 통과 기준을 만족

> **사람 확인은 M7 끝에 몰아서 한다** (2026-11-05 사용자 결정, 속도 우선). M1~M3 절차서의 남은 항목과 같이 한다. 그 전까지 M4는 "자동 완료"로만 센다.

녹화의 핵심인 사람의 물리 입력은 프로그램으로 만들 수 없다(우리 프로세스가 보내는 입력은 전부 합성이고 녹화기는 합성을 버린다). 그래서 셋으로 나눈다 — 절차서를 쓴 것만으로 아래 H절을 완료로 적지 않는다.

| 증명 | 무엇 | 어디서 |
|---|---|---|
| 논리 | 변환·대기·자르기·재사용·비밀값 판정·커밋, 가짜 각본 녹화 → 재생 | CI (가짜 훅 원천·부품 합성 프레임) |
| 실제 장치 | 실제 훅 프로세스·실제 WGC·실제 SendInput, 검사 표식 입력(양성 대조) | 잠금 해제 개발자 PC (D절) |
| 사람 | 물리 마우스·키보드, IME 실제 조합, 원격 입력, 지연 체감, 화면 모양 | 사람 (H절) |

| 절 | 내용 | 시간 |
|---|---|---|
| D1~D3 | 잠금 해제 상태 자동 검사(실제 입력), 전체 자동 검사, 시안 비교 PNG | 약 1시간 (기다림) |
| H1~H6 | 실제 마우스·키보드로 녹화 | 약 1시간 30분 |
| U1~U16 | 기본값으로 진행한 사용자 결정 | 15분 |

결과 `manual_result.md`와 증거 폴더는 레포 밖 `.orchestration/M4/`(git 제외)에 둔다.

## 0. 준비

[[m3-manual]] 0절의 준비 블록을 `M3` → `M4`로 바꿔 붙여 넣는다(`$repo`, `$ev = "$repo\.orchestration\M4\manual_evidence"`, 결과 양식 `m4-result-template.md` 복사, 의존성·앱 빌드). 같은 절의 주의(검사 중 PC를 쓰지 않기, 화면 끄기·절전 "안 함", 실행 전 포그라운드)도 그대로다.

### 예제 워크스페이스 사본과 개발 빌드 앱 (H절에서 씀)

```powershell
# M4 사본 만들기 (예제 원본은 고치지 않는다)
$kb = "$env:TEMP\kb-m4"
Remove-Item -Recurse -Force $kb -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $kb | Out-Null
Copy-Item -Recurse "$repo\fixtures\sample-game\workspace" "$kb\sample-rpg"
Copy-Item -Recurse "$repo\fixtures\sample-game\frames" "$kb\frames"
New-Item -ItemType Directory -Force "$kb\sample-rpg\.kookabug" | Out-Null
$local = @{ format = "kookabug.local/0"; settings = @{ "game.cwd" = "$repo\fixtures\sample-game"; "game.executable" = "$repo\.venv\Scripts\python.exe" } }
[IO.File]::WriteAllText("$kb\sample-rpg\.kookabug\local.json", ($local | ConvertTo-Json))   # BOM 없는 UTF-8
```

```powershell
# M4 앱 띄우기 (실제 플랫폼)
$kb = "$env:TEMP\kb-m4"
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
$env:KOOKABUG_OCR_MODELS = "$repo\build\ocr-models"
pnpm --filter @kookabug/desktop exec electron .
```

- 시작 화면 "프로젝트 열기"로 `%TEMP%\kb-m4\sample-rpg`를 연다. 녹화는 액티비티 바의 "녹화"(빨간 점)

## 1. 잠금 해제 상태 자동 검사 (D)

### D1 실제 입력 녹화 검사

실제 예제 게임·실제 훅·실제 캡처. "사람" 입력은 검사 표식을 실은 SendInput이다. 다른 데스크톱 검사와 동시에 돌리지 않는다(전역 훅·임대권).

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"
uv run pytest -p no:cacheprovider python/kookabug_core/tests/acceptance/test_m4.py python/kookabug_daemon/tests/test_recorder_live.py python/kookabug_platform/tests/test_recorder_hook_live.py python/kookabug_platform/tests/test_recorder_live.py fixtures/sample-game/tests/test_fake_frame_parts.py 2>&1 | Tee-Object "$ev\d1_recorder_live.log"
Remove-Item Env:KOOKABUG_DESKTOP_TESTS, Env:KOOKABUG_DESKTOP_INPUT
```

- 기대 결과: 실패 0, 건너뜀 0 (인수 `test_recorded_login_live_replays_pass`·`test_pre_click_frame_live`·`test_live_kookabug_sendinput_not_recorded` 포함)

### D2 전체 자동 검사

[[m3-manual]] D5와 같은 명령(`require`·`INPUT`·`SOAK`·`MEDIA` + 전체 E2E). 증거 `d2_full.log`, `d2_e2e.log`.

### D3 시안 비교 PNG

```powershell
node tools/design-ref/render.mjs; node tools/design-ref/extract.mjs
pnpm --filter @kookabug/desktop shots
node tools/design-ref/compare.mjs target-ext recorder recorder-idle recorder-paused recorder-stopped recorder-error
New-Item -ItemType Directory -Force "$ev\ui-compare" | Out-Null
Copy-Item build\ui-compare\recorder*.png, build\ui-compare\target-ext*.png "$ev\ui-compare\"
(Get-ChildItem "$ev\ui-compare\*.png").Count
```

- 기대 결과: `shots` 실패 0, 마지막 줄 `8`(`recorder`·`target-ext` 다크·라이트, 녹화 전·일시정지·정지 뒤·오류 다크). H6의 재료. 편집기 기본 화면 `target`은 [[m2-manual]] V절이 본다

## 2. 실제 마우스·키보드로 녹화 (H)

### H1 로그인 녹화 → 새 테스트로 저장 → F5 pass, 녹화 데이터에 비밀번호 없음

1. "게임 띄워서 녹화" → 타이틀에서 시작 → 계정 칸 클릭·`qa_tester_01` → Tab → 비밀번호 `sample-pass-01`을 `sample-`까지 치고 3초 쉬었다 `pass-0`, 일부러 `9` → Backspace → `1` → 로그인 클릭 → 로비가 보이면 "화면 확인 삽입"으로 "서버 선택" 제목을 고른다 → 정지(`Ctrl+Shift+R`)
2. 비밀번호 스텝이 하나(● × 14)이고 비밀값 띠가 뜬다. 키 `accounts.qa_tester_01`을 고른 뒤 "새 테스트로 저장"(이름 `rec_h1`) → F5 → 새로 뜬 게임 창이 로비까지 가고 pass
3. **저장 직후, F5 전에** 녹화 데이터에서 원문을 찾는다. 재생 기록 `runs/`는 대상이 아니다 — 결정 D3(기본 가리지 않음)대로 재생 기록에는 원문 화면이 남을 수 있다

```powershell
$w = "$kb\sample-rpg"
Get-ChildItem -Recurse "$w\tests", "$w\targets", "$w\.kookabug\logs", "$w\.kookabug\cache\recorder" -ErrorAction SilentlyContinue |
  Where-Object { -not $_.PSIsContainer } | Select-String -SimpleMatch -Pattern "sample-pass-01", "pass-01" | Tee-Object "$ev\h1_grep.txt"
Get-ChildItem -Recurse "$w\targets" | Where-Object Name -match "pass" | Tee-Object -Append "$ev\h1_grep.txt"
```

- 기대 결과: 두 명령 모두 아무것도 찾지 못함. `targets\rec\rec_h1\`의 PNG를 열어 비밀번호 칸 글자가 보이는 그림이 없는지 눈으로 본다. `.kookabug\cache\recorder\`는 비어 있다

### H2 녹화 중 실행 거부·입력 지연

1. 녹화 중 다른 PowerShell 창에서 `cd $env:TEMP\kb-m4\sample-rpg; & "$repo\.venv\Scripts\kookabug.exe" run tests/inventory_open.graph.json` → `input_lease_busy`로 끝난다
2. 녹화 중 마우스 이동·클릭·키 입력이 평소보다 늦게 느껴지는지 (게이밍 마우스가 있으면 그것으로)

### H3 걸러 내는 입력

녹화 중 게임 창 밖 클릭, 다른 창으로 전환·Alt+Tab, 정지 단축키, 화상 키보드(`osk`)로 친 글자는 스텝에 들어가지 않는다(화상 키보드는 "다른 프로그램이 보낸 입력 N개" 경고). (선택) 원격 데스크톱으로 접속해 녹화하면 표식 없는 입력이라 녹화된다 — 판정 한계 확인만

### H4 한글·다른 자판

로그인 칸에 두벌식 한글(예: `한글테스트`)을 쳐 녹화 → 글자 스텝이 조합된 글자 + "확인하세요" 표시 → 재생에서 같은 글자. 영문 US 자판으로 바꿔 같은 녹화

### H5 마우스 올림 화면·DPI

- SuperTuxKart 메뉴(마우스를 올리면 바뀌는 단추)에서 녹화 → 재생. 게임 준비는 [[m1-manual]] G0 재사용
- DPI 150%에서 녹화 → 100%에서 재생 (D2 근거). 배율 바꾸기는 [[m1-manual]] D7·G2 재사용

### H6 찾기 대상 편집기 확장·녹화 화면 시안 대비

- 편집기: 민감 대상·색 허용치 저장, 같은 모양 N곳(점선 상자), 다른 배율 점수, Shift+드래그 검색 범위(M2 T1 남은 것), 판 크기(하단 패널 열림)가 충분한지
- D3의 PNG를 시안과 나란히 본다(다크·라이트). 사이드바 폭 311px, 재사용이 많은 각본에서 상태 바 수가 시안과 다른 것은 의도한 차이

## 3. 사용자 결정 확인 (U)

M4는 아래 결정을 기본값으로 진행했다. 위 절에서 본 뒤 "그대로" 또는 "바꿈(어떻게)"을 적는다.

| ID | 결정할 것 | 지금 기본값 | 어디서 봄 |
|---|---|---|---|
| U1 | 녹화 시작 화면 (시안에 없음) | 창 목록에서 고르기 또는 "게임 띄워서 녹화" + "녹화 시작" | H1 |
| U2 | 다른 프로그램이 보낸 입력 | 녹화하지 않고 개수만 알림. 표시 없는 입력(원격 데스크톱·KVM)은 녹화됨 | H3 |
| U3 | 비밀번호 칸 판정·글자 처리 | 칸마다 판정 + 사람 표시(`Ctrl+Shift+P`), 쉬었다 이어 쳐도 한 비밀값, 판정 못 하면 "확인 필요"로 저장 막음 | H1 |
| U4 | 검증 없이 저장한 녹화 | 새 테스트면 끝에 "통과" 노드 + 경고, 삽입이면 원래 다음 노드로 | H1 |
| U5 | 대기 변환 | "대기 + 클릭", 화면이 바뀌며 1초 넘게 기다렸으면 "나타날 때까지 대기" | H1 |
| U6 | "지나간 화면을 화면 지도에 추가" | 숨김 (M7) | H1 |
| U7 | 한글 입력 녹화 | 두벌식으로 조합 + "확인하세요", 다른 입력기는 키 사슬 | H4 |
| U8 | 녹화 단축키 | 정지 `Ctrl+Shift+R`, 비밀값 표시 `Ctrl+Shift+P`, 녹화 중에만 잡음 | H1·H3 |
| U9 | 녹화 중 앱 닫힘·연결 끊김 | 그 녹화는 버림, 써진 찾기 대상 파일은 남음 | (선택) |
| U10 | 녹화 찾기 대상 위치·이름 | `targets/rec/<테스트 이름>/<순번>_<글자>.target.json`, 같으면 재사용 | H1 |
| U11 | 끌기 끝점·휠 위치 | 픽셀 좌표 + "해상도가 바뀌면 다시 잡으세요" | (선택) |
| U12 | 상태 바·사이드바 문구 | 시안 그대로, 임대권 "입력: 녹화" | H6 |
| U13 | 게임이 앞에 없을 때 | 녹화하지 않고 "게임 창이 앞에 없어요" | H3 |
| U14 | 편집기에 더한 요소 | 민감 대상·색 허용치·같은 모양 N곳·다른 배율 점수·검색 범위 숫자·글자 읽기·"새 찾기 대상" 단추 | H6 |
| U15 | 게임이 띄운 팝업 창 입력 | 녹화하지 않고 알림 | (선택) |
| U16 | 시안의 비밀값 안내 문구 | 목록 메모는 "비밀값 선택 필요"만, 가림을 켰을 때만 "재생 때 이 스텝은 스크린샷 생략" | H1 |

## 4. 정리와 판정

1. `manual_result.md`의 모든 행을 채운다(선택 항목은 "-"와 이유)
2. D·H가 모두 O이고 U에 "바꿈"이 없으면 **M4 최종 완료**. X나 "바꿈"은 별도 결정으로 올린다
3. 증거 폴더와 결과는 레포에 올리지 않는다
