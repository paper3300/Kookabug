# M3 사람 확인 절차서

M3(기록·디버거) 완료도 M1·M2처럼 두 단계다 ([[구현 계획 v0]] 1장 M3 행).

1. **자동 완료**: 자동 테스트(CI + 잠긴 PC에서도 도는 Electron E2E·가짜 인코더 영상 검사), 인수 테스트(`python/kookabug_core/tests/acceptance/test_m3.py`, `apps/desktop/e2e/acceptance.m3.spec.ts`), 시안 비교 PNG 세트, 이 절차서·결과 양식
2. **최종 완료**: 이 절차서의 **결과**가 결과 양식(`m3-result-template.md`)에 기록되고 모든 항목이 통과 기준을 만족. 한 항목이라도 실패하면 그 항목은 별도 결정(고칠 작업·범위 조정)으로 올리고 최종 완료로 세지 않는다

M1·M2 사람 검증(`m1-manual.md`, `m2-manual.md`)이 아직 끝나지 않았다면 그것도 따로 한다. 항목은 겹치지 않는다(D5만 M2 D5와 같은 명령에 영상 조건 하나를 더한 것이라 한 번만 돌리면 된다).

절은 일곱이다. 순서대로 하면 D(약 1시간, 대부분 기다림) → V(20분) → R(30분) → B(30분) → W(20분) → S(40분) → P(30분) → U(15분)다.

| 절 | 내용 | 어디서 |
|---|---|---|
| D1~D6 | 잠금 해제 상태에서만 도는 자동 검사(실제 창 녹화·실제 MP4 포함), 시안 비교 PNG 만들기 | 레포가 있는 PC |
| V1~V6 | 디버그 툴바·기록 뷰어 시안 비교 PNG 보기 (다크·라이트) | 레포가 있는 PC |
| R1~R4 | 실제 창 영상: 실패 실행 재생, 기록 끈 구간 비어 있음·비밀값 가림 설정, 성공 실행 영상 지워짐, SuperTuxKart | 레포가 있는 PC |
| B1~B5 | 디버거 조작감: 브레이크포인트·Step·일시정지·계속, 멈춘 동안 창 옮기기·화면 바꾸기 뒤 재개 | 레포가 있는 PC |
| W1~W4 | 기록 뷰어: 실패 노드로 이동, 비교 상자, 회차 변곡 문구, 라이트 테마 | 레포가 있는 PC |
| S1~S5 | 설치본(NSIS)에서 영상 녹화·재생(FFmpeg DLL 없는 트리), 영상 사용 불가 주입, Windows N 판 | Windows Sandbox (+ 구할 수 있으면 N 판 PC) |
| P1 | 앞 단계에서 아직 돌리지 않은 사람 확인 (M1 D7 DPI 150·200%) | 레포가 있는 PC |
| U1~U13 | 기본값으로 진행한 사용자 결정 확인 | 어디서든 |

**레포에 두는 것과 두지 않는 것**: 이 절차서와 결과 양식은 레포(공개)에 있다. 결과 `manual_result.md`와 증거 폴더(로그·스크린샷·비교 PNG 사본·영상 사본)는 레포 밖 `.orchestration/M3/`(git 제외)에 둔다.

## 0. 준비 (공통)

PowerShell을 하나 열고 아래를 붙여 넣는다. `$repo`만 자기 레포 위치로 바꾼다. 이 창을 끝까지 쓴다(새 창이면 이 블록을 다시 붙여 넣는다).

```powershell
$repo = "C:\src\Kookabug"                       # 레포 위치로 바꾼다
$ev   = "$repo\.orchestration\M3\manual_evidence" # 증거 폴더 (git에 올리지 않는 폴더)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
New-Item -ItemType Directory -Force $ev | Out-Null
if (-not (Test-Path "$repo\.orchestration\M3\manual_result.md")) {
  Copy-Item "$repo\Docs\verification\m3-result-template.md" "$repo\.orchestration\M3\manual_result.md"
}
cd $repo
uv sync --locked --all-packages; uv run python tools/fetch_ocr_models.py
pnpm install --frozen-lockfile; pnpm --filter @kookabug/desktop exec install-electron
pnpm --filter @kookabug/desktop build
```

- 결과는 `$repo\.orchestration\M3\manual_result.md`에 항목 ID(D1, V3, R2 …)별로 적는다
- **D·R·B절 동안에는 PC를 쓰지 않는다**(B절은 적힌 조작만 한다). 실제 마우스·키보드 입력을 보내는 검사가 있다. 설정 → 시스템 → 전원의 "화면 끄기"·"절전"을 검사하는 동안 "안 함"으로 둔다
- **실행 전 포그라운드**: 다른 프로그램(보안·근태·원격 관리 프로그램 등, 보이지 않는 창일 수 있다)이 포그라운드를 쥐고 있으면 Kookabug가 띄운 게임 창이 앞으로 오지 않고, 입력 노드가 `window_not_foreground`로 실패한다(사용자 결정: 포커스를 잃으면 다시 가져오지 않는다). 검사·실행을 시작하기 직전에 이 PowerShell 창(또는 앱 창)을 한 번 클릭해 포그라운드를 가져온다. D1의 `foreground` 항목이 실패하면 그런 프로그램을 끄거나 최소화한 뒤 다시 한다. 실패 이유가 `window_not_foreground`면 "환경 사유"로 적고 포그라운드를 가져온 뒤 그 항목만 다시 돌린다

### 예제 워크스페이스 사본과 개발 빌드 앱 (R·B·W절에서 씀)

레포의 예제를 직접 고치지 않도록 임시 사본을 연다. 첫 블록은 사본을 만든다(게임 실행 설정 `local.json`, 영상 정책 `failed_only` — 예제 원본은 영상 `off`다). 두 번째 블록은 비밀값·OCR 모델 위치를 넣고 개발 빌드 앱을 **실제 플랫폼**(실제 창·캡처·입력)으로 띄운다. 앱을 다시 띄울 때는 두 번째 블록만 붙여 넣는다.

```powershell
# M3 사본 만들기
$kb = "$env:TEMP\kb-m3"
Remove-Item -Recurse -Force $kb -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $kb | Out-Null
Copy-Item -Recurse "$repo\fixtures\sample-game\workspace" "$kb\sample-rpg"
Copy-Item -Recurse "$repo\fixtures\sample-game\frames" "$kb\frames"
New-Item -ItemType Directory -Force "$kb\sample-rpg\.kookabug" | Out-Null
$local = @{ format = "kookabug.local/0"; settings = @{ "game.cwd" = "$repo\fixtures\sample-game"; "game.executable" = "$repo\.venv\Scripts\python.exe" } }
[IO.File]::WriteAllText("$kb\sample-rpg\.kookabug\local.json", ($local | ConvertTo-Json))   # BOM 없는 UTF-8
$ws = Get-Content -Raw -Encoding UTF8 "$kb\sample-rpg\kookabug.json" | ConvertFrom-Json
$ws.record.video = "failed_only"
[IO.File]::WriteAllText("$kb\sample-rpg\kookabug.json", ($ws | ConvertTo-Json -Depth 10))
```

```powershell
# M3 앱 띄우기
$kb = "$env:TEMP\kb-m3"
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
$env:KOOKABUG_OCR_MODELS = "$repo\build\ocr-models"
pnpm --filter @kookabug/desktop exec electron .
```

- 앱이 뜨면 시작 화면의 "프로젝트 열기"로 `%TEMP%\kb-m3\sample-rpg`를 고른다
- 실행 기록은 액티비티 바의 시계 아이콘("실행 기록")에서 연다. RUN 탭 스크린샷 줄 머리의 "스크린샷 | 영상" 전환이 영상 보기다(U8)
- 앱을 닫아도 daemon은 남는다(정상). 연결·실행이 없으면 10분 뒤 스스로 끝난다

## 1. 잠금 해제 상태 자동 검사 (D)

화면 잠금이 풀린 상태에서만 도는 검사다(창·WGC 캡처·실제 SendInput·실제 Media Foundation 인코딩). 잠긴 세션이면 탐지가 실패해 `require`에서는 실패, `auto`(기본)에서는 건너뛴다. 레포 루트(`cd $repo`)에서 한다.

### D1 데스크톱 탐지

```powershell
$env:PYTHONPATH = "tools"; uv run python -m kb_testing.desktop | Tee-Object "$ev\d1_probe.txt"; Remove-Item Env:PYTHONPATH
```

- 기대 결과: `결과: **통과**`, 표의 4개(`window_station`·`input_desktop`·`wgc_frame`·`foreground`) 모두 통과
- 기록: 결과, 실패한 항목의 내용 칸

### D2 M3 인수 테스트 (Python, 실제 MP4 포함)

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_MEDIA_TESTS = "require"
uv run pytest python/kookabug_core/tests/acceptance/test_m3.py -v 2>&1 | Tee-Object "$ev\d2_acceptance.log"
```

- 기대 결과: 마지막 줄 `22 passed`(실패·건너뜀 0). `media` 표시 검사 셋(`test_failed_only_real_mp4_deleted_on_pass_kept_on_fail` 둘, `test_record_off_and_secret_spans_absent_from_decoded_mp4`)이 실제 H.264 조각을 쓰고 디코드한다. 비밀값 구간 검사는 임시 워크스페이스에 `record.redact_secrets: true`를 켜고 돈다(기본은 가리지 않는다, 2026-11-03 사용자 결정 D3)
- 기록: 통과·실패·건너뜀 수, 시간

### D3 실제 창 녹화·실제 MP4

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_MEDIA_TESTS = "require"
uv run pytest python/kookabug_platform/tests/test_video_live.py python/kookabug_core/tests/record/test_video_msmf.py python/kookabug_core/tests/record/test_video_unavailable.py -v 2>&1 | Tee-Object "$ev\d3_video.log"
```

- 기대 결과: 전부 통과. `test_video_live.py`는 예제 게임 창을 WGC로 2초 녹화해 Media Foundation H.264 조각을 쓰고 다시 읽는다(입력은 보내지 않는다). `test_video_msmf.py`는 FFmpeg 플러그인을 찾을 수 없는 프로세스에서 쓰고, 격자로 이동한 칸이 그 스텝의 장면인지 본다
- 기록: 통과 수, 실패 이름과 마지막 `AssertionError` 줄

### D4 앱 인수·뷰어 (Electron, 실제 MSMF 녹화 포함)

```powershell
$env:KOOKABUG_MEDIA_TESTS = "require"
pnpm --filter @kookabug/desktop exec playwright test --project=e2e e2e/acceptance.m3.spec.ts e2e/debug.spec.ts e2e/runviewer.spec.ts e2e/runviewer2.spec.ts 2>&1 | Tee-Object "$ev\d4_app.log"
```

- 기대 결과: 실패 0. `acceptance.m3.spec.ts` 5개, `runviewer2.spec.ts`의 `test_video_tab_seeks_to_step_and_shows_gap_reason`은 이 PC의 실제 MSMF 조각 안에서 스텝 시각으로 탐색한다
- 기록: 통과·실패 수

### D5 전체 자동 검사

M2 D5와 같은 명령에 `KOOKABUG_MEDIA_TESTS=require`를 더했다. 수십 분 걸린다.

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"; $env:KOOKABUG_SOAK = "1"; $env:KOOKABUG_MEDIA_TESTS = "require"
uv run pytest 2>&1 | Tee-Object "$ev\d5_full.log"
pnpm --filter @kookabug/desktop e2e 2>&1 | Tee-Object "$ev\d5_e2e.log"
Remove-Item Env:KOOKABUG_DESKTOP_TESTS, Env:KOOKABUG_DESKTOP_INPUT, Env:KOOKABUG_SOAK, Env:KOOKABUG_MEDIA_TESTS
```

- 기대 결과: pytest 실패 0, 끝의 "데스크톱 검사" 요약에 `탐지: 통과`·건너뜀 줄 없음, `media` 건너뜀 없음. E2E 실패 0
- 기록: pytest 통과·실패·건너뜀 수와 시간, E2E 통과·실패 수

### D6 시안 비교 PNG 만들기

```powershell
node tools/design-ref/render.mjs; node tools/design-ref/extract.mjs
pnpm --filter @kookabug/desktop shots
node tools/design-ref/compare.mjs main-debug main-debug-paused runviewer runviewer-compare runviewer-stats runviewer-comparetab
New-Item -ItemType Directory -Force "$ev\ui-compare" | Out-Null
Copy-Item build\ui-compare\main-debug*.png, build\ui-compare\runviewer*.png "$ev\ui-compare\"
(Get-ChildItem "$ev\ui-compare\*.png").Count
```

- 기대 결과: 마지막 줄 `12`(화면 6개 × 다크·라이트). `shots`에서 실패 0. M2 화면 11개는 M2 D6이 맡는다(같은 `shots` 실행에서 나온다)
- 기록: PNG 수. 이 PNG가 V절의 재료다

## 2. 시안 대비 화면 (V)

`$ev\ui-compare\<화면>-<테마>.png`를 연다. 왼쪽이 시안(UX 시안 v0.1을 렌더한 것), 오른쪽이 앱이다. 픽셀 일치는 보지 않는다(내용이 다르다). **색·글꼴·크기·자리·모양**이 시안 언어와 같은지, 아래 "의도한 차이" 밖의 차이가 있는지 본다. **기록 뷰어 시안(RunViewer)은 다크뿐이다**: 라이트 앱 화면은 다크 시안과 나란히 놓였으니 라이트는 "M2 라이트 화면들과 같은 토큰 언어인가"(글자·테두리·강조 색이 라이트 테마답게 바뀌었는가)만 본다.

공통 의도한 차이(어느 화면이든 차이로 세지 않음):

- 에이전트 패널·"에이전트에게 분석 요청"·"수집 데이터" 탭 숨김(U11, M5). 녹화 툴바·입력 차단 카드 숨김(M4)
- 실행 번호는 `#<실행 ID 앞 4자>`(시안은 순번 `#128`)
- 예제 워크스페이스·가짜 플랫폼 실행이라 시안의 2,981회차·12.4 GB 같은 숫자와 이름이 다르다

| ID | 화면 (`<id>`) | 시안 | 볼 것 | 이 화면의 의도한 차이·남은 차이 |
|---|---|---|---|---|
| V1 | 디버그 툴바 (`main-debug`) | Main(·Light) "실행 제어" | 캔버스 위 가운데 떠 있는 상자(위 8px·모서리 4px·그림자), 끌기 손잡이 `⋮⋮`, 일시정지·다음 노드·들어가기·나오기·다시 시작(초록)·정지(빨강), 단추 28px, 탭 줄에 정지 단추 없음 | 브레이크포인트 빨간 점(U1, 시안에 없음) |
| V2 | 멈춘 디버그 툴바 (`main-debug-paused`) | Main(·Light) | "계속 ▶"이 일시정지 자리에, Step 단추 켜짐 | 멈춘 노드 노란 테두리·"⏸ 멈춤"·멈춤 띠·상태 바 "⏸ 멈춤 · 노드"(U2, 시안에 없음). **남은 차이**: 멈춤 띠만큼 캔버스가 줄어든다(18px 한 줄, 재개 경고가 있으면 두 줄) |
| V3 | 기록 뷰어 (`runviewer`) | RunViewer | 액티비티 바 시계 아이콘, "실행 기록" 날짜 묶음·결과 색 점·배지 색(검증 없음 빨강·불안정 노랑·디버거 개입 보라), RUN 탭 머리(제목·결과·회색 메타), 하위 탭 밑줄, 스크린샷 4열·후보 점선 상자·점수, 후보 표(1위 주황) | 스텝 타임라인은 호출 트리(반복 줄을 펼치면 회차 막대). 목록 검색·필터 숨김. **남은 차이**: 목록 줄 이름이 테스트 파일 이름(`viewer_fail`, 시안은 테스트 제목), 머리 메타에 러너(PC) 이름 자리 없음 |
| V4 | 비교 상자·회차 막대 (`runviewer-compare`) | RunViewer | "#<기준> (성공) 과 차이" 상자(화면·그래프·환경·시간 4줄, 다른 줄 강조색), 회차 막대(늦은 회차 주황), 머리 오른쪽 "에디터에서 재현"·"분석 번들 내보내기" | "스크린샷 \| 영상" 전환(U8). **남은 차이**: 하단 출력 패널 때문에 회차 막대와 비교 상자가 한 화면에 같이 안 보일 수 있다. 상태 바 용량이 실행 직후 "0 B"(daemon 1분 캐시) |
| V5 | 노드별 통계 (`runviewer-stats`) | RunViewer (탭 이름만 있음) | 표가 시안 표 언어(머리 줄·숫자 오른쪽 정렬·줄 높이)인지 | 내용은 앱이 정함(시안에 없음) |
| V6 | 비교 탭 (`runviewer-comparetab`) | RunViewer (탭 이름만 있음) | 기준 고르기, 두 화면 나란히·차이 영역 상자 색 | 내용은 앱이 정함(시안에 없음) |

- 기록: 화면마다 "의도한 차이 밖의 차이" 목록(없으면 "없음")과 통과(O/X). 고치고 싶은 차이는 결과 양식의 "고칠 것" 표에 적는다

## 3. 실제 창 영상 (R)

개발 빌드 앱(실제 플랫폼)을 0절 "M3 앱 띄우기"로 띄우고 `%TEMP%\kb-m3\sample-rpg`를 연다. 사본의 영상 정책은 `failed_only`(실패한 실행만 영상을 남긴다)다. 실행을 시작하기 전에 앱 창을 한 번 클릭한다(0절 "실행 전 포그라운드").

### R1 실패 실행의 영상이 재생됨

1. `tests/broken/swapped_target.graph.json`을 열고 ▶. 바꿔치기한 target 때문에 **"월드 접속 > 타이틀 대기"**(호출한 서브그래프 `subgraphs/broken/enter_world_swapped_target.graph.json`의 `n_wait_title`, 기다림 3초)에서 실패한다(그래프 설명과 같다). 로그인 화면까지 가지 않는다
2. "실행 기록"에서 그 실행을 한 번 누른다. 실패 스텝(호출 안의 "타이틀 대기")이 골라진다
3. 스크린샷 줄 머리의 "영상"을 누른다. 실패 스텝 시각으로 옮겨 멈춘 영상이 보인다. ▶로 재생하고, 타임라인에서 앞 스텝(호출 안의 "게임 실행" `n_launch`)을 누르면 그 시각으로 옮겨지는지 본다
4. 실행 폴더 `runs\<…>\video\`를 탐색기로 열어 `seg-0001.mp4`를 Windows 미디어 플레이어로도 재생해 본다. 증거로 `video` 폴더를 `$ev\r1_video`로 복사한다

- 기대 결과: 앱 안에서 재생·탐색이 되고 영상 화면이 실제 게임 창(타이틀 화면)이다. 실패 구간이 서브그래프 호출 안이어도 영상이 있다(기본은 비밀값을 가리지 않아 "비밀값 입력" 빈 구간이 없다). "이 PC에서 재생할 수 없음"이 뜨지 않는다
- 기록: 재생됨(O/X), 탐색이 스텝 시각과 맞는지(대략 0.2초 안), 조각 수·크기

### R2 기록 끈 구간이 영상에 없음 · 비밀값 가림 설정

기본은 비밀값을 가리지 않는다(2026-11-03 사용자 결정 D3: 개발 환경 전용 도구라 로그인 입력 구간이 영상에 남아도 된다). 그래서 로그인 서브그래프 호출도 영상에 남고, 빈 구간은 노드에 영상 끄기를 쓴 곳만이다. 워크스페이스 `record.redact_secrets: true`를 켜면 예전처럼 비밀값을 받는 호출 전체가 빈 구간이 된다. R1 실행은 로그인 전에 실패하므로 로그인·I 키까지 간 뒤 실패하는 그래프를 사본에 만든다.

1. 아래 첫 블록으로 사본에 `tests/m3_r2_video.graph.json`을 만든다. `inventory_open`과 같고, `n_press_i`(I 키)에 영상 끄기(`"record": {"video": "off"}`, 속성 편집기에는 기록 정책 칸이 없다)를 넣고 마지막 검증 `n_check_inventory`가 월드 화면에 없는 로그인 단추를 3초 기다려 실패하게 바꾼 것이다. 탐색기에 나타나면 열고 ▶ (마지막 검증에서 실패)
2. "실행 기록"에서 그 실행 → "영상". 로그인 서브그래프 호출(`n_enter_world`) 구간을 타임라인에서 눌러 본다: 타이틀·로그인·로비·로딩 화면이 영상에 있고, 계정을 치고 비밀번호 칸이 채워지는(게임이 `●`로 그린다) 로그인 화면이 보인다. "영상 없음 · 비밀값 입력" 빈 구간은 **없다**
3. `n_press_i` 구간(I 키를 누르는 순간)이 "영상 없음 · 기록 끔"인지 본다
4. 둘째 블록으로 사본 `kookabug.json`에 `record.redact_secrets: true`를 켜고(다음 실행부터 적용) `tests/m3_r2_video.graph.json`을 다시 ▶. 새 실패 실행의 영상에서 로그인 호출 **전체**가 "영상 없음 · 비밀값 입력"이고, `n_press_i`는 그대로 "기록 끔"인지 본다. 끝나면 셋째 블록으로 설정을 되돌린다(만든 그래프는 두어도 된다)

```powershell
# M3 R2 그래프 만들기
$t = "$env:TEMP\kb-m3\sample-rpg\tests"
$v = Get-Content -Raw -Encoding UTF8 "$t\inventory_open.graph.json" | ConvertFrom-Json
$v.nodes.n_press_i | Add-Member -NotePropertyName record -NotePropertyValue @{ video = "off" } -Force
$v.nodes.n_check_inventory.in.target.'$target' = "targets/login/login_button.target.json"
$v.nodes.n_check_inventory.in.timeout_ms = 3000
[IO.File]::WriteAllText("$t\m3_r2_video.graph.json", ($v | ConvertTo-Json -Depth 20))
```

```powershell
# M3 R2 가림 켜기
$c = "$env:TEMP\kb-m3\sample-rpg\kookabug.json"
Copy-Item $c "$c.bak"
$ws = Get-Content -Raw -Encoding UTF8 $c | ConvertFrom-Json
$ws.record | Add-Member -NotePropertyName redact_secrets -NotePropertyValue $true -Force
[IO.File]::WriteAllText($c, ($ws | ConvertTo-Json -Depth 10))
```

```powershell
# M3 R2 가림 되돌리기
$c = "$env:TEMP\kb-m3\sample-rpg\kookabug.json"
Move-Item -Force "$c.bak" $c
```

- 기대 결과: 기본 설정 실행은 로그인 화면(비밀번호 칸 포함)이 영상에 남고 빈 구간은 `n_press_i`의 "기록 끔" 하나다. 가림을 켠 실행은 로그인 호출 전체가 "비밀값 입력" 빈 구간이고 그 바로 앞뒤 프레임에 로그인 화면·비밀번호 칸이 보이지 않는다. 두 실행 모두 `n_press_i` 구간에 영상 프레임이 없다
- 기록: 기본 실행의 로그인 화면 보임(O/X)·빈 구간 이유 목록, 가림 실행의 빈 구간 이유 목록·앞뒤 프레임 장면. 참고: 가림을 켜도 비밀값 입력 스텝 **다음** 노드 화면에 입력한 값이 보일 수 있다(스키마 6장 경고) — 로그인은 구간 끄기를 쓴다

### R3 성공 실행의 영상은 지워짐

1. `tests/inventory_open.graph.json`을 ▶ (통과)
2. 그 실행 폴더 `runs\<…>\video\`를 연다

- 기대 결과: `seg-*.mp4`가 없고 `index.json`의 `deleted`에 지운 조각과 이유 `run_pass`가 있다. 뷰어에는 "영상" 전환 없이 "영상 없음 · 실패하지 않은 실행이라 지움"이 보인다
- 기록: 남은 `seg-*` 수, `index.json`의 `status`·`deleted` 수

### R4 SuperTuxKart 실패 실행 영상

M1 절차서 G절(G0)에서 만든 SuperTuxKart 워크스페이스·그래프가 있으면 한다(없으면 "-"). 그 워크스페이스 `kookabug.json`의 `record.video`를 `failed_only`로 두고, 일부러 실패하는 그래프(예: 없는 target을 기다리는 마지막 노드)를 앱에서 실행한다.

- 기대 결과: 실제 GPU 게임 창의 실패 실행 영상이 앱에서 재생되고, 게임 화면이 검게 나오지 않는다. 창 크기를 바꾼 구간이 있으면 새 조각으로 이어진다
- 기록: 재생됨(O/X), 검은 화면 여부, 조각 수

## 4. 디버거 조작감 (B)

개발 빌드 앱(실제 플랫폼)으로 `%TEMP%\kb-m3\sample-rpg`의 `tests/inventory_open.graph.json`을 연다. 단축키는 VS Code와 같다: F5 실행·계속, Shift+F5 정지, Ctrl+Shift+F5 다시 시작, F6 일시정지, F9 브레이크포인트, F10 다음 노드, F11 서브그래프로 들어가기, Shift+F11 서브그래프에서 나오기.

### B1 브레이크포인트·계속

1. `n_press_i`(I 키)를 고르고 F9. 노드 머리 왼쪽에 빨간 점이 생긴다. 점 자리 클릭·오른쪽 클릭 메뉴로도 끄고 켜 본다
2. F5. 게임이 뜨고 로그인·월드까지 간 뒤 `n_press_i`에서 멈춘다(노란 테두리·"⏸ 멈춤", 멈춤 띠, 상태 바 "⏸ 멈춤 · I 키", 툴바 "계속")
3. F5로 계속 → 통과

- 기대 결과: 위 표시가 보이고 통과한다. 멈춘 동안 게임 창은 그대로이고 키가 눌린 채로 있지 않다
- 기록: O/X, 어색한 점

### B2 Step Into/Over/Out

1. 브레이크포인트를 `n_enter_world`(로그인 호출)로 옮기고 F5
2. 멈추면 F11 → 서브그래프 첫 동작 노드(게임 실행)에서 멈춘다. 서브그래프 탭을 열면 안쪽 노드에도 표시된다
3. F10을 두세 번 → 같은 서브그래프의 다음 노드로 한 칸씩
4. Shift+F11 → 호출이 끝난 뒤 루트의 다음 노드(`n_use_window`)에서 멈춘다
5. F10 두 번 → `n_press_i` → `n_check_inventory`, F5로 끝까지

- 기대 결과: 매번 표시가 그 노드로 옮겨 가고 화면(게임)이 그 순서대로 진행한다. 한 단계씩 넘길 때도 화면 값은 무효가 된다(U4) — "OCR 읽기 → 분기" 사이에서 넘기면 그 분기가 실패한다는 경고 띠가 먼저 보인다
- 기록: O/X, 단축키·단추 중 안 먹은 것, 어색한 점

### B3 기다리는 중 일시정지

1. 브레이크포인트를 모두 끄고 F5. 로딩 화면(월드 대기)에서 F6
2. 0.1초 안쪽으로 멈춘다(대기 노드 안). 30초쯤 둔 뒤 F5

- 기대 결과: 바로 멈추고, 재개 뒤 통과한다. 멈춘 30초는 노드 시간 초과·전체 기한에서 빠진다(시간 초과로 실패하지 않는다)
- 기록: O/X, 멈출 때까지 걸린 느낌

### B4 멈춘 동안 게임 창을 옮긴 뒤 재개 → 새 자리로 입력

1. `n_click_start`(서브그래프 `subgraphs/enter_world.graph.json`의 "시작" 클릭)에 브레이크포인트를 걸고 `tests/inventory_open.graph.json`을 F5
2. 멈추면 게임 창 제목 줄을 끌어 화면의 다른 곳으로 옮긴다
3. F5

- 기대 결과: 재개하면 입력 서비스가 대상(시작 단추)을 새 화면에서 다시 찾아 **옮긴 자리**를 누르고 로그인 화면으로 넘어간다. 실행 폴더 `events.jsonl`의 그 스텝 `log` 줄에 "디버거 재개 전 관측이다 … 다시 찾아 … 입력한다"가 있다(창 안 좌표는 같으므로 원래 점과 같은 값이 찍힌다 — 화면 좌표는 옮긴 자리다)
- 기록: O/X, 누른 자리가 맞았는지

### B5 멈춘 동안 화면이 바뀐 뒤 재개 → 입력이 나가지 않음

1. B4처럼 `n_click_start`에서 멈춘다
2. 게임 창을 클릭해 앞으로 가져온 뒤 **게임 안에서 시작 단추를 직접 눌러** 로그인 화면으로 넘긴다(대상이 사라진 화면). 앱 창을 다시 클릭해 앞으로 가져온다
3. F5

- 기대 결과: 그 노드가 입력 없이 실패한다(`stale_observation`, 노드 빨강). 게임 화면은 로그인 화면 그대로이고 엉뚱한 곳을 누르지 않는다. 기록 뷰어에서 그 실행을 한 번 누르면 그 노드가 골라지고 이유에 `stale_observation`이 보인다
- 기록: O/X, 입력이 나갔는지(게임 화면 변화)

## 5. 기록 뷰어 (W)

R·B절에서 만든 실행들을 쓴다.

### W1 실패 노드로 한 번에

1. "실행 기록"에서 R1의 실패 실행을 한 번 누른다
2. "그래프에서 보기"를 누른다

- 기대 결과: 목록 한 번으로 실패 스텝이 골라지고 증거(처음·중간·마지막 스크린샷, 후보 표)가 보인다. "그래프에서 보기"가 그 그래프 탭을 열고 실패 노드를 고른다(실행 뒤 그래프가 바뀌었으면 스냅샷 읽기 전용 탭)
- 기록: O/X, 몇 번 눌렀는지

### W2 비교 상자

1. R3의 통과 실행 뒤 R1의 실패 실행을 연다(같은 테스트가 아니면 `inventory_open` 실패를 하나 만든다: 실행 중 게임 창을 닫는 등)
2. 스텝 타임라인 아래 "#<기준> (성공) 과 차이" 상자와 "#<기준> 과 비교" 탭을 본다

- 기대 결과: 기준이 같은 테스트·같은 프로필·통과·디버거 개입 아님 중 가장 최근이다(U10). 화면 차이 상자가 실제로 다른 곳을 가리키고, 실제 게임 화면의 움직이는 배경·글자 깜박임 때문에 상자가 쓸데없이 많지 않다(문턱값: 밝기 40, 최소 덩어리 0.1%는 가짜 장면 기준으로 정했다)
- 기록: O/X, 상자 수와 쓸모, 고를 수 있는 다른 기준

### W3 회차 변곡 문구

1. 반복이 있는 그래프를 둘 실행한다: 예제 사본의 `tests/`에 반복 그래프가 없으면 시안 Main 그래프(앱 E2E의 `e2e/fixtures/sian-main.graph.json`)처럼 `core.flow.repeat` 안에 대기가 있는 그래프를 만들고, 두 번째 실행 중에 게임 화면을 일부러 늦게 바꾸게(예: 대기 대상이 늦게 나타나게) 한다
2. 늦은 실행의 비교 상자 "시간" 줄을 본다

- 기대 결과: "N회차부터 대기 평균 a → b" 같은 문구가 늦어진 회차를 가리킨다. 한계: 앞 1/4 안에서 시작한 늦어짐은 잡지 못한다(규칙: 앞 절반 중앙값의 2배가 넘게 이어지는 첫 회차)
- 기록: 문구, 쓸 만한지(O/X). 만들기 어려우면 "-"와 이유

### W4 라이트 테마

메뉴 보기 → 라이트로 바꾸고 W1·W2 화면(영상 재생기 포함)을 다시 본다.

- 기대 결과: 글자·테두리·결과 색 점·배지·차이 상자 색이 라이트 테마 토큰으로 바뀌고 읽기 어려운 곳이 없다(시안 RunViewer는 다크뿐)
- 기록: O/X, 읽기 어려운 곳

## 6. 설치본 (S)

M2 S절과 같은 Windows Sandbox를 쓴다(Sandbox 켜기는 `m1-manual.md` S1, 설치·제거 순서는 `m2-manual.md` S1~S5). 이번에 더 보는 것은 **FFmpeg DLL이 없는 설치 트리에서의 영상**이다.

### S1 설치 파일 준비·설치

M2 절차서 S1~S3대로 설치 파일을 만들고 Sandbox에서 화면으로 설치한다.

- 기록: 설치 파일 이름·크기, 설치 성공(O/X)

### S2 설치본 영상 녹화·재생

Sandbox의 PowerShell에서 예제를 복사하고 영상 정책을 `failed_only`로 바꾼 뒤 가짜 플랫폼으로 앱을 띄운다(Sandbox의 가상 GPU에서는 실제 캡처가 안 될 수 있어 가짜 플랫폼으로 본다 — 영상 인코딩은 OS Media Foundation이 실제로 한다):

```powershell
# M3 S2 설치본 사본
$app = "$env:LOCALAPPDATA\Programs\Kookabug"
$out = "$HOME\Desktop\kookabug-out"
Copy-Item -Recurse "$app\examples\sample-game" "$HOME\Documents\sample-game"
$wsFile = "$HOME\Documents\sample-game\workspace\kookabug.json"
$ws = Get-Content -Raw -Encoding UTF8 $wsFile | ConvertFrom-Json
$ws.record.video = "failed_only"
[IO.File]::WriteAllText($wsFile, ($ws | ConvertTo-Json -Depth 10))
$fake = "$HOME\Documents\sample-game\workspace\fake-platform.json"
$env:KOOKABUG_DAEMON_ARGS = ConvertTo-Json -Compress @("--platform-fake", $fake)
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
& "$app\Kookabug.exe"
```

1. `문서\sample-game\workspace`를 열고 `tests/broken/swapped_target.graph.json`을 ▶ (실패)
2. 실행 기록에서 그 실행 → "영상". 재생·탐색해 본다
3. `Get-ChildItem "$app\python\Lib\site-packages\cv2\opencv_videoio_ffmpeg*.dll"`이 아무것도 내지 않는지 본다
4. 앱을 닫고 `kookabug doctor --profile headless | Out-File -Encoding utf8 "$out\s2_doctor.txt"`. "영상 인코더" 줄을 본다

- 기대 결과: 앱에서 영상이 재생된다(가짜 장면 화면), FFmpeg DLL 없음, doctor "영상 인코더"가 사용 가능
- 기록: 재생됨(O/X), FFmpeg DLL 파일 수, doctor 영상 줄

### S3 영상 사용 불가 주입 (검수 M9)

같은 Sandbox 설치본에서 영상 인코더를 쓸 수 없는 상태를 숨은 검사 설정으로 넣는다(Media Foundation DLL을 없는 이름으로).

**새 사본 폴더로 한다.** 앱을 닫아도 그 워크스페이스의 daemon은 남고(연결이 없으면 10분 뒤 끝남), 앱을 다시 열면 그 daemon에 다시 붙는다. 실행(runner)은 daemon이 띄우므로 S2의 `sample-game`을 다시 열면 이 설정이 실행에 들어가지 않는다(doctor만 주입된 상태를 보고 앱 실행은 영상을 쓴다). 새 폴더 `sample-game-novideo`는 처음 여는 워크스페이스라 앱이 이 설정을 가진 새 daemon을 띄운다:

```powershell
# M3 S3 영상 사용 불가 사본
$app = "$env:LOCALAPPDATA\Programs\Kookabug"
$out = "$HOME\Desktop\kookabug-out"
Copy-Item -Recurse "$app\examples\sample-game" "$HOME\Documents\sample-game-novideo"
$wsFile = "$HOME\Documents\sample-game-novideo\workspace\kookabug.json"
$ws = Get-Content -Raw -Encoding UTF8 $wsFile | ConvertFrom-Json
$ws.record.video = "failed_only"
[IO.File]::WriteAllText($wsFile, ($ws | ConvertTo-Json -Depth 10))
$fake = "$HOME\Documents\sample-game-novideo\workspace\fake-platform.json"
$env:KOOKABUG_DAEMON_ARGS = ConvertTo-Json -Compress @("--platform-fake", $fake)
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
$env:KOOKABUG_VIDEO_TEST = '{"encoder": "msmf", "msmf": {"mf_dlls": ["kb-missing-mfplat.dll"]}}'
kookabug doctor --profile headless | Out-File -Encoding utf8 "$out\s3_doctor.txt"; "종료 코드 $LASTEXITCODE"
& "$app\Kookabug.exe"
```

1. 앱에서 **`문서\sample-game-novideo\workspace`** 를 연다(S2의 `sample-game`이 아니다). 앱이 뜨는지, `tests/broken/swapped_target.graph.json` ▶가 평소처럼 실패로 끝나는지(영상 때문에 오류가 나지 않는지) 본다
2. 그 실행의 RUN 탭 스크린샷 줄 머리에 "영상 없음 · 이 PC에서 영상 인코더를 쓸 수 없음"이 보이는지 본다. "영상" 전환이 보이면 이전 daemon에 붙은 것이다 — 앱을 닫고 작업 관리자에서 `kookabug.exe daemon`을 모두 끝낸 뒤 다시 한다
3. 끝나면 `Remove-Item Env:KOOKABUG_VIDEO_TEST`. 이미 뜬 `sample-game-novideo`의 daemon은 그 뒤에도 주입된 환경 그대로다 — 이 사본은 다시 쓰지 않는다(다시 쓰려면 그 daemon을 먼저 끝낸다)

- 기대 결과: doctor 종료 코드 0이고 "영상 사용 불가 (mf_missing)" 줄, 앱 기동·실행 정상, 이유 표시
- 기록: doctor 종료 코드·영상 줄, 실행 판정, 뷰어 문구

### S4 제거

M2 S5대로 제거하고 네 줄을 확인한다. `kookabug-out`을 호스트 `$ev\sandbox`로 복사한다.

- 기록: 네 줄

### S5 (구할 수 있으면) Windows N 판

미디어 기능 팩이 없는 Windows N·KN 판 PC(또는 VM)를 구할 수 있으면 같은 설치 파일로 설치 → 앱 기동 → `tests/smoke_headless.graph.json`·`tests/broken/swapped_target.graph.json` 실행 → doctor를 한다. 자동 검사로는 만들 수 없는 환경이다(S3은 흉내). 구하지 못하면 "-"와 "미실행"을 적는다.

- 기대 결과: 설치·앱 기동·실행이 영상 없이 된다. doctor "영상 사용 불가 (mf_missing 또는 encoder_open_failed)", 실행 판정은 영상과 무관
- 기록: 판(에디션), 결과, 못 했으면 그 사실

## 7. 앞 단계에서 남은 사람 확인 (P)

### P1 M1 D7 DPI 150%·200% (미실행)

M1 D7(`m1-manual.md` D7, DPI 150%·200%에서 창·캡처·입력 자동 검사)은 M3까지 **한 번도 실행하지 않았다**(배율을 바꾸는 것은 사람이 해야 한다). M1 결과 양식에 결과가 없으면 지금 한다. M3 영상은 창 클라이언트 크기를 물리 픽셀로 쓰므로, 배율을 바꾼 상태에서 R1을 한 번 더 해 보면 좋다(선택).

- 기록: M1 D7을 했는지, 배율별 통과·실패 수(M1 결과 양식에도 적는다), 선택으로 한 R1 결과

## 8. 사용자 결정 확인 (U)

M3는 아래 결정을 **기본값으로 진행**했다. 각 항목을 위 절에서 직접 본 뒤 "그대로" 또는 "바꿈(어떻게)"을 적는다. 바꾸면 다음 작업으로 올린다.

| ID | 결정할 것 | 지금 기본값 | 어디서 봄 | 대안 |
|---|---|---|---|---|
| U1 | 브레이크포인트 표시 (시안에 없음) | 노드 머리 왼쪽 빨간 점, F9·점 자리 클릭·오른쪽 클릭 메뉴로 토글, 목록 창 없음 | V1·B1 | 노드 테두리 표시, 브레이크포인트 목록 창 |
| U2 | 멈춘 노드 표시 (시안에 없음) | 노란 테두리 2px + "⏸ 멈춤 · 이유", 상태 바는 파랑 그대로 "⏸ 멈춤" | V2·B1 | 다른 색, 상태 바 색 바꾸기 |
| U3 | 툴바의 "서브그래프에서 나오기" | 넣음(Shift+F11) | V1·B2 | 빼기 |
| U4 | 한 단계씩 넘길 때도 화면 값 무효 | 재개마다(Step 포함) 무효. "OCR 읽기 → 분기" 사이에서 넘기면 그 분기는 실패, 멈춤 띠에 미리 경고 | B2 | Step은 무효화하지 않고 "계속"만, 멈춘 시간이 짧으면 유지 |
| U5 | 실패 시 영상 보관의 "실패" | `fail`·`error`(기한 초과·runner 사망 포함)는 보관, `pass`·`skipped`·사용자 취소는 삭제 | R1·R3 | 사용자 취소도 보관 |
| U6 | 영상 형식·화질 | H.264 MP4(Windows 내장 인코더), 초당 5장, 긴 변 1920 이하, 1분 조각. 미디어 기능이 없는 Windows(N 판 등)는 영상 없이 실행하고 이유를 남김 | R1·S2·S5 | 초당 장 수·크기 바꾸기 |
| U7 | 멈춘 동안 영상 | 녹화하지 않음(빈 구간 "멈춤") | B1·R1 | 계속 녹화 |
| U8 | 영상 보는 자리 (시안에 없음) | 스크린샷 줄 머리의 "스크린샷 \| 영상" 전환, 고른 스텝 시각으로 이동 | R1·V4 | 별도 탭, 늘 보이는 재생기 |
| U9 | 스텝 썸네일 기본 저장 | 캡처한 스텝마다 작은 JPEG(긴 변 480), 반복은 첫 회차와 마지막 두 회차만. 스크린샷 정책을 따름 | W2 | 저장하지 않기(화면 비교 불가), 실패 스텝만 |
| U10 | "지난 성공" 기준 | 같은 테스트·같은 프로필·판정 pass·디버거 개입 아님 중 가장 최근, 사용자가 바꿀 수 있음 | W2 | 고정한 기준 실행 |
| U11 | RUN 탭의 "에이전트에게 분석 요청"·"수집 데이터"·"에디터에서 재현" | 앞의 둘은 숨김(M5·뜻 미정). "에디터에서 재현"은 그래프 열기 + 실패 노드 브레이크포인트 + 같은 프로필 선택까지, 실행은 사용자가 F5 | V3·W1 | 재현 단추가 바로 실행 |
| U12 | 브레이크포인트 적용 범위 | 사람이 앱에서 시작한 실행만. 에이전트·CLI 실행은 무시 | B1 | CLI에도 적용(`--break`) |
| U13 | 앱을 끈 채 멈춘 실행 | UI 연결 없이 10분 멈춰 있으면 취소 | (B1에서 멈춘 채 앱을 닫고 10분 기다려 보면 된다, 선택) | 시간 바꾸기, 취소하지 않기 |

함께 볼 것(결정은 아니지만 기본값의 결과):

- 워크스페이스가 `record.video`를 정하지 않으면 `failed_only`다. 테스트·노드에 `video: on`을 써도 아래 층은 더 세게만 바꿀 수 있어 효과가 없다. 성공 실행 영상도 남기려면 워크스페이스에서 `on`을 쓴다
- 비밀값 기록은 기본이 **가리지 않음**이다(2026-11-03 사용자 결정 D3). 예제의 로그인 호출도 비밀번호 입력 화면까지 영상·스크린샷에 남는다(R1·R2). 워크스페이스 `record.redact_secrets: true`면 비밀값을 받는 호출 전체가 영상에 없고 빈 구간 "비밀값 입력"이 된다(R2 4번)

## 9. 정리와 판정

1. `manual_result.md`의 모든 행에 결과 값·증거 경로·통과(O/X)를 채운다. U절은 "그대로/바꿈"을 적는다(통과 칸 대신). 해 볼 수 없었던 선택 항목(R4·S5·W3)은 "-"와 이유
2. 판정
   - D·V·R·B·W·S·P가 모두 O(선택 항목은 "-" 허용)이고 U에 "바꿈"이 없다 → **M3 최종 완료**
   - X가 있거나 U에 "바꿈"이 있다 → "별도 결정·고칠 것" 표에 적는다. 고칠 작업은 다음 마일스톤 계획에 넣는다(바꿈 항목이 다음 작업으로 미뤄도 되는 것이면 그렇게 적고 최종 완료로 셀 수 있다)
3. 증거 폴더 `$ev`와 `manual_result.md`는 레포에 올리지 않는다(`.orchestration/`은 git 제외 폴더)
