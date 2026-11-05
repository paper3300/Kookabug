# M1 사람 검증 절차서

M1(비전·입력·배포) 완료는 두 단계다 ([[구현 계획 v0]] 1장).

1. **자동 완료**: 자동 테스트(CI + 개발자 PC 데스크톱 자동 검사), 설치 파일 CI, 이 절차서·결과 양식·표본 계산 스크립트
2. **최종 완료**: 이 절차서의 **결과**가 결과 양식에 기록되고 모든 항목이 통과 기준을 만족. 절차서를 쓴 것만으로는 최종 완료가 아니다. 한 항목이라도 실패하면 그 항목은 별도 결정(지원 범위 축소·추가 작업)으로 올리고 최종 완료로 세지 않는다

절은 셋이다. 순서대로 하면 D(약 1시간, 대부분 기다림) → S(약 30분) → G(반나절)다.

| 절 | 내용 | 어디서 |
|---|---|---|
| D1~D7 | 개발자 PC 데스크톱 자동 검사 (잠금 해제 상태에서만 도는 검사) | 레포가 있는 PC |
| S1~S6 | 깨끗한 Windows 설치 → `doctor` → 예제 게임 실제 실행 → 제거 | Windows Sandbox |
| G0~G12 | 실제 GPU 게임: DPI·창·포커스·전체화면·한글 입력·OCR 수치·키 해제·권한·잠금 | 레포가 있는 PC |

**레포에 두는 것과 두지 않는 것**

- 레포(공개): 이 절차서, 결과 양식 `m1-result-template.md`, Sandbox 설정 `m1-sandbox.wsb`, 실제 게임 검증 워크스페이스 틀 `m1-real-game/`, 표본 계산 `tools/ocr_bench.py`
- 레포 밖(올리지 않음): 결과 `manual_result.md`, 증거 폴더(실행 폴더·`doctor --json`·스크린샷·OCR 표본·`ocr_bench` 출력), 실제 게임 워크스페이스 사본(target 이미지가 게임 화면이다). 게임 화면은 그 게임의 저작물이므로 레포에 넣지 않는다. 이 절차서는 공개 게임(기본 SuperTuxKart)을 기준으로 쓴다. 그 밖의 게임으로 더 확인하더라도 그 이름·화면은 레포 밖 결과에만 적는다

## 0. 준비 (공통)

PowerShell을 하나 열고 아래를 붙여 넣는다. `$repo`만 자기 레포 위치로 바꾼다. 이 창을 끝까지 쓴다(창을 새로 열면 이 블록을 다시 붙여 넣는다).

```powershell
$repo = "C:\src\Kookabug"                       # 레포 위치로 바꾼다
$ev   = "$repo\.orchestration\M1\manual_evidence" # 증거 폴더 (git에 올리지 않는 폴더)
[Console]::OutputEncoding = [Text.Encoding]::UTF8
New-Item -ItemType Directory -Force $ev | Out-Null
if (-not (Test-Path "$repo\.orchestration\M1\manual_result.md")) {
  Copy-Item "$repo\Docs\verification\m1-result-template.md" "$repo\.orchestration\M1\manual_result.md"
}
function kb { uv run --project $repo kookabug @args }
function Last-Run { (Get-ChildItem runs -Directory | Sort-Object LastWriteTime | Select-Object -Last 1).FullName }
function Keep-Run($name) { Copy-Item -Recurse (Last-Run) "$ev\$name"; "증거: $ev\$name" }
cd $repo; uv sync --locked --all-packages; uv run python tools/fetch_ocr_models.py
```

- 결과는 `$repo\.orchestration\M1\manual_result.md`(결과 양식 사본)에 항목 ID(D1, S3, G8 …)별로 적는다
- **검사 중에는 PC를 쓰지 않는다.** 실제 마우스·키보드 입력을 보내는 검사가 있다. 잠금·절전이 끼어들지 않게 설정 → 시스템 → 전원 → "화면 끄기"·"절전"을 검사하는 동안 "안 함"으로 둔다
- `kb run … --json | ConvertFrom-Json`은 실행 결과 한 개(JSON)를 객체로 읽는다. 기록할 값은 `verdict`(pass·fail·error·skipped·cancelled), `code`, `reason`, `failure_titles`, `run_dir`이다

## 1. 개발자 PC 데스크톱 자동 검사 (D)

화면 잠금이 풀린 상태에서만 도는 검사다(창·WGC 캡처·실제 SendInput). 잠긴 세션에서 돌리면 탐지가 실패해 `require`에서는 실패, `auto`에서는 건너뛴다. 레포 루트(`cd $repo`)에서 한다.

### D1 데스크톱 탐지

```powershell
$env:PYTHONPATH = "tools"; uv run python -m kb_testing.desktop | Tee-Object "$ev\d1_probe.txt"; Remove-Item Env:PYTHONPATH
```

- 기대 결과: `결과: **통과**`, 표의 4개(`window_station`·`input_desktop`·`wgc_frame`·`foreground`) 모두 통과
- 기록: 결과, 실패한 항목의 내용 칸

### D2 M1 인수 테스트 (데스크톱 포함)

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"
uv run pytest python/kookabug_core/tests/acceptance/test_m1.py -v 2>&1 | Tee-Object "$ev\d2_acceptance.log"
```

- 기대 결과: 마지막 줄 `N passed`(실패·건너뜀 0). 설치 파일 검사(`test_installed_cli_runs_capture_and_ocr_without_python`)는 Node·pnpm(`pnpm install`, `pnpm --filter @kookabug/desktop exec install-electron`)·Visual Studio(VC++ 재배포 파일)가 있으면 설치 파일을 빌드해서 돈다(수 분, M2부터 NSIS 설치 파일). 없으면 그 한 개는 실패하므로 CI `installer` 잡 결과로 대신하고 그렇게 적는다
- 기록: 통과·실패·건너뜀 수, 걸린 시간(마지막 줄)

### D3 캡처·장시간 안정성

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"; $env:KOOKABUG_SOAK = "1"
uv run pytest python/kookabug_platform/tests/test_capture.py python/kookabug_platform/tests/test_capture_soak.py -s 2>&1 | Tee-Object "$ev\d3_capture.log"
```

- 기대 결과: 전부 통과. `test_capture_soak`이 세션 200회·크기 변경 500회·캡처 10,000회 뒤 핸들·스레드·메모리 증가를 출력한다. `test_resize_waits_matching_frame`(크기 바꾼 뒤 다 그린 프레임)도 여기 들어 있다
- 기록: 통과 수, soak 출력의 증가 수치(핸들·스레드·개인 바이트)

### D4 실제 입력·강제 종료 키 해제

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"
uv run pytest python/kookabug_platform/tests/test_sendinput_live.py python/kookabug_core/tests/supervisor/test_real_key_release.py -v 2>&1 | Tee-Object "$ev\d4_input.log"
```

- 기대 결과: 전부 통과(창 이동 뒤 클릭, 한글 `type_text`, 포그라운드·소유 팝업 판정, 누른 채 runner 강제 종료 → 감독자가 실제 SendInput으로 해제, 이중 고장 대조)
- 기록: 통과 수. 실패하면 검사 이름과 마지막 `AssertionError` 줄

### D5 노드·예제 워크스페이스 실기

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"
uv run pytest python/kookabug_nodes/tests/test_nodes_live.py fixtures/sample-game/tests/test_workspace_live.py python/kookabug_core/tests/runner/test_windows_platform.py -v 2>&1 | Tee-Object "$ev\d5_nodes.log"
```

- 기대 결과: 전부 통과 (실제 WGC·SendInput으로 예제 게임 `inventory_open`까지)
- 기록: 통과 수

### D6 전체 자동 검사

M1 자동 완료 기준의 수치다. 수십 분 걸린다.

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"; $env:KOOKABUG_SOAK = "1"
uv run pytest 2>&1 | Tee-Object "$ev\d6_full.log"
Remove-Item Env:KOOKABUG_DESKTOP_TESTS, Env:KOOKABUG_DESKTOP_INPUT, Env:KOOKABUG_SOAK
```

- 기대 결과: 실패 0. 끝의 "데스크톱 검사" 요약에 `탐지: 통과`, 건너뜀 줄 없음
- 기록: 통과·실패·건너뜀 수와 시간(마지막 줄), 데스크톱 요약

### D7 DPI 150%·200% 자동 검사

이 PC의 화면 배율을 바꿔 창·캡처·입력 검사를 다시 돌린다(100%에서만 확인된 unaware 창 크기 계산·물리 픽셀 좌표를 본다).

1. 설정 → 시스템 → 디스플레이 → "배율"을 **150%** 로 바꾼다. 목록에 없으면 "사용자 지정 배율"에 150을 넣고 로그아웃했다가 들어온다
2. PowerShell을 새로 열고 0절 블록을 붙여 넣은 뒤:

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"
uv run pytest python/kookabug_platform/tests/test_windows.py python/kookabug_platform/tests/test_capture.py python/kookabug_platform/tests/test_sendinput_live.py python/kookabug_core/tests/acceptance/test_m1.py -v 2>&1 | Tee-Object "$ev\d7_dpi150.log"
```

3. **200%** 로 바꿔 같은 명령을 `d7_dpi200.log`로 다시 돌린다. 끝나면 원래 배율로 돌린다

- 기대 결과: 두 배율 모두 실패 0 (`test_client_rect_physical_pixels[unaware·system]`·`test_set_client_size_unaware_window[unaware·system]` 포함). 로그아웃 없이 바꾼 배율(시스템 DPI는 로그온 값)과 로그온 때부터의 배율 모두 같은 기대 결과다
- 기록: 배율별 통과·실패 수, 실제로 쓴 배율 값(사용자 지정이면 그렇게)

## 2. 깨끗한 Windows 설치 (S)

Python이 없는 깨끗한 Windows에서 설치 → CLI·캡처·OCR·입력 → 제거를 본다. **Windows Sandbox**(Windows 11 Pro·Enterprise의 일회용 가상 PC)를 쓴다. 닫으면 안의 내용이 모두 사라진다.

### S1 Windows Sandbox 켜기 (한 번)

1. 관리자 PowerShell(시작 → "PowerShell" 오른쪽 클릭 → 관리자 권한으로 실행)에서:

```powershell
Enable-WindowsOptionalFeature -Online -FeatureName "Containers-DisposableClientVM" -All
```

2. 다시 시작하라고 하면 다시 시작한다. 시작 메뉴에 "Windows Sandbox"가 생긴다
3. 켜지지 않으면(가상화 꺼짐 등) 작업 관리자 → 성능 → CPU의 "가상화: 사용"을 확인한다. BIOS에서 켜야 하면 그렇게 적고, 대신 Hyper-V VM(새로 설치한 Windows 11)으로 S2~S6을 한다

- 기록: 켜졌는지, 쓴 환경(Sandbox / VM)

### S2 설치 파일 준비·Sandbox 시작

1. 제품 판 설치 파일을 만든다(또는 CI `installer` 잡 artifact의 `kookabug-setup-<버전>.exe`를 받는다):

```powershell
$env:PYTHONPATH = "tools"; uv run python -m installer.build; Remove-Item Env:PYTHONPATH
Get-ChildItem build\installer\dist\kookabug-setup-*.exe | Where-Object Name -notlike "*-test-*"
```

2. 호스트 폴더를 만들고 설치 파일과 Sandbox 설정을 넣은 뒤 Sandbox를 띄운다:

```powershell
New-Item -ItemType Directory -Force C:\kookabug-m1\in, C:\kookabug-m1\out | Out-Null
Copy-Item (Get-ChildItem build\installer\dist\kookabug-setup-*.exe | Where-Object Name -notlike "*-test-*").FullName C:\kookabug-m1\in\
Copy-Item Docs\verification\m1-sandbox.wsb C:\kookabug-m1\
Start-Process C:\kookabug-m1\m1-sandbox.wsb
```

`m1-sandbox.wsb`는 `C:\kookabug-m1\in`을 Sandbox 바탕 화면 `kookabug-in`(읽기 전용)으로, `C:\kookabug-m1\out`을 `kookabug-out`(쓰기)으로 붙이고 **네트워크를 끈다**(설치·실행·OCR이 내려받기 없이 되는지도 본다).

- 기록: 설치 파일 이름·크기(`(Get-Item C:\kookabug-m1\in\*.exe).Length`)

### S3 설치

Sandbox 안에서:

1. 바탕 화면 `kookabug-in`의 `kookabug-setup-<버전>.exe`를 더블클릭한다. SmartScreen이 막으면 "추가 정보 → 실행"(코드 서명 전). **관리자 권한(UAC)을 묻지 않아야 한다.** 기본 폴더 그대로 설치한다
2. 시작 → "Windows PowerShell"을 새로 열고:

```powershell
$out = "$HOME\Desktop\kookabug-out"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
where.exe python 2>&1 | Tee-Object "$out\s3_where_python.txt"
kookabug --version | Tee-Object "$out\s3_version.txt"
Get-ComputerInfo -Property OsName, OsVersion, OsBuildNumber | Out-File -Encoding utf8 "$out\s3_os.txt"
```

- 기대 결과: UAC 창 없음. `where.exe python`이 아무것도 못 찾거나 `WindowsApps\python.exe`(스토어 바로 가기, 실제 Python 아님)만 찾는다. `kookabug --version` → `kookabug <버전>`
- 기록: UAC 여부, `where.exe` 출력, 버전, Windows 판

### S4 doctor

```powershell
kookabug doctor --json | Out-File -Encoding utf8 "$out\doctor.json"; "종료 코드 $LASTEXITCODE"
```

- 기대 결과: 종료 코드 0, `doctor.json`의 `"ok": true` (desktop 프로필: 의존성·DLL·OCR 모델·DPI·가짜 플랫폼 스모크·입력 데스크톱·WGC 캡처·포그라운드)
- 실패하면: 그 항목의 `detail`을 적는다. Sandbox의 가상 GPU에서 WGC가 안 되면 `wgc` 항목이 실패할 수 있다 — 그러면 S5도 실패하므로 Hyper-V VM으로 S3~S6을 다시 하고 둘 다 적는다
- 기록: 종료 코드, 실패 항목과 `detail`

### S5 예제 게임 실제 실행 (캡처·OCR·입력)

```powershell
cd "$env:LOCALAPPDATA\Programs\Kookabug\examples\sample-game\workspace"
$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"
kookabug run tests/inventory_open.graph.json; "종료 코드 $LASTEXITCODE"
Copy-Item -Recurse runs "$out\s5_runs"
```

- 실행 중에는 마우스·키보드를 건드리지 않는다. 예제 게임 창이 떠서 타이틀 → 로그인 → 서버 선택(OCR) → 월드 → 인벤토리까지 간다
- 기대 결과: 종료 코드 0, 판정 pass
- 기록: 종료 코드, 판정, 걸린 시간, `s5_runs` 폴더

### S6 제거

1. 설정 → 앱 → 설치된 앱 → "Kookabug" → 제거 (또는 `& "$env:LOCALAPPDATA\Programs\Kookabug\Uninstall Kookabug.exe"`, M2부터 NSIS 제거 프로그램)
2. 새 PowerShell에서:

```powershell
$out = "$HOME\Desktop\kookabug-out"
@(
  "폴더 남음: $(Test-Path "$env:LOCALAPPDATA\Programs\Kookabug")"
  "PATH 항목: $(([Environment]::GetEnvironmentVariable('Path','User') -split ';') -like '*Kookabug*')"
  "명령 찾음: $([bool](Get-Command kookabug -ErrorAction SilentlyContinue))"
) | Tee-Object "$out\s6_uninstall.txt"
```

- 기대 결과: `폴더 남음: False`, `PATH 항목:` 뒤가 비어 있음, `명령 찾음: False`
- 기록: 세 줄. 그 뒤 Sandbox를 닫는다. 호스트 `C:\kookabug-m1\out`을 `$ev\sandbox`로 복사한다(`Copy-Item -Recurse C:\kookabug-m1\out "$ev\sandbox"`)

## 3. 실제 GPU 게임 (G)

공개 GPU 게임 하나로 한다. 기본은 **SuperTuxKart**(오픈 소스, supertuxkart.net에서 받는다). 검증 워크스페이스 틀 `Docs/verification/m1-real-game/`의 그래프를 설정값만 바꿔 쓴다.

| 그래프 | 하는 일 | 쓰는 절 |
|---|---|---|
| `tests/capture.graph.json` | (`capture.delay_ms` 기다림 →) 클라이언트 영역을 `steps/<스텝>_screen.png`로 | G0·G7·G9 |
| `tests/dpi_check.graph.json` | 붙기 → 기준 버튼 대기 → 클릭 → 확인 글자 OCR → 돌아가기 키 → 기준 버튼 다시 대기 | G1~G3·G12 |
| `tests/move_click.graph.json` | 기준 버튼 찾음 → 기다리는 동안 사람이 창 이동 → 찾은 결과로 클릭 → 확인 글자 | G4 |
| `tests/resize_click.graph.json` | 기준 버튼 찾음 → 창 크기 바꿈(`resize.size`) → 찾은 결과로 클릭 → 확인 글자 | G5 |
| `tests/focus_loss.graph.json` | 기다리는 동안 사람이 다른 창 클릭 → 글자 입력 | G6·G12 |
| `tests/korean_input.graph.json` | 입력 칸 클릭 → `korean.text` 입력 → 찍기 → 영역 OCR | G8 |
| `tests/hold_key.graph.json` | `hold.delay_ms` 기다림 → `hold.key`를 `hold.ms` 동안 누름 | G10·G11 |

### G0 대상·장면 정하기와 준비

1. **장면을 정한다** (결과에 적는다)
   - ① **기준 화면**: 한국어 UI 글자가 보이는 메뉴 화면(게임 언어를 한국어로). 그 화면의 버튼 하나(**기준 버튼**)를 누르면 다른 화면으로 가고, 그 화면에 늘 같은 글자(**확인 글자**, 예: 화면 제목)가 보이고, 키 하나(**돌아가기 키**, 보통 Esc)로 기준 화면에 돌아오는 조합을 고른다
   - ② **입력 칸**: 한글을 입력하고 화면에서 확인할 수 있는 칸(예: 플레이어 이름 입력). 없거나 그 게임이 한글을 받지 못하면 한글 입력 칸이 있는 다른 공개 GPU 게임·엔진 데모를 **보완 대상**으로 골라 G8만 그것으로 한다
2. 게임을 **창 모드**로 띄우고 화면 배율을 **100%** 로 둔다(설정 → 시스템 → 디스플레이)
3. 워크스페이스 틀을 레포 밖으로 복사하고 사람마다 다른 설정을 적는다:

```powershell
$ws = "$env:USERPROFILE\kookabug-m1\real-game"
Copy-Item -Recurse "$repo\Docs\verification\m1-real-game" $ws
cd $ws
New-Item -ItemType Directory -Force .kookabug, targets | Out-Null
New-Item -ItemType File -Force .kookabug\local.json | Out-Null
notepad .kookabug\local.json
```

메모장에 아래를 넣고 값을 바꿔 **UTF-8로 저장**한다(`game.title`은 게임 창 제목의 일부, `check.text`는 확인 글자의 일부, `korean.region`은 G8에서 정하므로 일단 그대로 둔다).

```json
{
  "format": "kookabug.local/0",
  "settings": {
    "check.text": "옵션",
    "game.title": "SuperTuxKart",
    "korean.region": [0, 0, 100, 40]
  }
}
```

4. **target 세 개를 만든다** (기준 버튼 `anchor`, 확인 글자 `label`, 입력 칸 `field`)
   1. 게임을 기준 화면에 두고 `kb run tests/capture.graph.json`. 끝나면 `explorer (Join-Path (Last-Run) steps)` → `…_screen.png`
   2. 그 PNG를 그림판으로 열어 기준 버튼만 "선택 → 자르기" → `targets\anchor.png`로 저장(다른 이름으로 저장 → PNG). 그림판 아래 상태 표시줄의 원래 이미지 크기 `W × H`(자르기 전)를 적어 둔다
   3. 확인 글자 화면에서 같은 방법으로 `targets\label.png`(글자 줄만), 입력 칸이 빈 화면에서 `targets\field.png`
   4. target 파일 세 개를 만든다. `recorded.client_size`는 2에서 적은 `W, H`(배율 100%의 클라이언트 크기)다 — 150·200%에서 기대 배율을 이 값으로 계산한다

```powershell
$W = 1280; $H = 720   # 2에서 적어 둔 W, H로 바꾼다
foreach ($n in "anchor", "label", "field") {
  $body = '{{"format":"kookabug.target/0","image":"{0}.png","recorded":{{"client_size":[{1},{2}],"dpi":96}}}}' -f $n, $W, $H
  [IO.File]::WriteAllText("$ws\targets\$n.target.json", $body)
}
kb target test targets\anchor.target.json --window "SuperTuxKart"; "종료 코드 $LASTEXITCODE"
```

`kb target test`가 종료 코드 0(찾음)이고 미리보기 PNG의 상자가 기준 버튼 위면 된다. `label`·`field`도 그 화면에서 같은 명령으로 확인한다.

5. **기준 PC를 적는다**:

```powershell
Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors | Out-File -Encoding utf8 "$ev\g0_pc.txt"
"RAM GB: $([math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1))" | Out-File -Append -Encoding utf8 "$ev\g0_pc.txt"
Get-CimInstance Win32_VideoController | Select-Object Name, DriverVersion, CurrentHorizontalResolution, CurrentVerticalResolution | Out-File -Append -Encoding utf8 "$ev\g0_pc.txt"
```

- 기록: 게임 이름·판, 기준 화면·기준 버튼·확인 글자·돌아가기 키, 입력 칸(보완 대상이면 그 게임), 100% 클라이언트 크기, 기준 PC

### G1 DPI 100%

게임을 기준 화면에 두고(창 모드, 배율 100%):

```powershell
$r = kb run tests/dpi_check.graph.json --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason, failure_titles; Keep-Run g1_dpi100
```

- 기대 결과: `verdict` = `pass` (붙기 → 이미지 대기 → 클릭 → OCR → 키 → 기준 화면 복귀)
- 실패하면: `kb target test targets\anchor.target.json --window "<제목>" --all-scales`의 점수·배율과 실패 스텝을 적는다
- 기록: verdict·code, 증거 폴더

### G2 DPI 150%

1. 배율을 **150%** 로 바꾼다(없으면 사용자 지정 150 → 로그아웃·로그인). 게임을 다시 시작하고 창 모드·기준 화면으로
2. G1과 같은 명령, `Keep-Run g2_dpi150`. **target은 G0에서 100%로 만든 것을 그대로** 쓴다(멀티스케일 매칭 확인)
3. `kb run tests/capture.graph.json; Keep-Run g2_capture150` — 이 배율의 클라이언트 크기와 G9 표본용 화면

- 기대 결과: `pass`
- 기록: 실제 배율, verdict·code, 클라이언트 크기(`g2_capture150`의 PNG 크기)

### G3 DPI 200%

G2를 **200%** 로 (`g3_dpi200`, `g3_capture200`). 모니터 해상도 때문에 200%가 목록에 없으면 사용자 지정 200을 쓴다. 끝나면 **100%로 돌린다**.

- 기대 결과: `pass`
- 기록: G2와 같다

### G4 창 이동

배율 100%, 기준 화면. 실행하면 기준 버튼을 찾은 뒤 10초(`manual.delay_ms`) 기다린다. 그동안 **게임 창 제목 표시줄을 끌어 다른 곳으로 옮기고 손을 뗀다**(5초 안에 끝내고 창이 화면 안에 다 보이게, 다른 창으로 가리지 않게).

```powershell
$r = kb run tests/move_click.graph.json --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason, failure_titles; Keep-Run g4_move
```

- 기대 결과: `pass` — 옮기기 전에 찾은 결과(클라이언트 좌표)로 옮긴 뒤 정확한 자리를 눌러 확인 글자가 보였다
- 기록: verdict·code

### G5 크기 변경

기준 화면에서. 그래프가 기준 버튼을 찾은 뒤 클라이언트 영역을 `resize.size`(기본 1280×720)로 바꾸고, **크기가 바뀌기 전에 찾은 결과**로 누른다. G0의 100% 클라이언트 크기가 1280×720이면 다른 크기를 준다.

```powershell
$r = kb run tests/resize_click.graph.json --set "resize.size=[1600,900]" --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason, failure_titles; Keep-Run g5_resize
# G5 판정
$events = Get-Content -Encoding UTF8 (Join-Path $r.run_dir "events.jsonl") | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json }
$rematch = @($events | Where-Object { $_.event -eq "log" -and "$($_.message)" -like "*다시 찾아*" })
$stale = @($events | Where-Object { $_.event -eq "step.end" -and $_.step -eq $r.failure_step -and "$($_.message)" -like "stale_observation:*" })
if ($r.verdict -eq "pass" -and $rematch.Count -gt 0) { "G5 통과 ① 재검증: $($rematch[0].message)" }
elseif ($r.verdict -eq "fail" -and $r.code -eq "unhandled_fail" -and $stale.Count -gt 0) { "G5 통과 ② stale_observation: $($stale[0].message)" }
else { "G5 실패: verdict=$($r.verdict) code=$($r.code) reason=$($r.reason)" }
```

- 기대 결과: 마지막 줄이 `G5 통과 ①`(pass이고 실행 기록에 "찾은 뒤 창이 바뀌었다 … 다시 찾아 … 입력한다" `log` — 재검증) 또는 `G5 통과 ②`(fail·`unhandled_fail`이고 **실패 스텝의 `step.end` 메시지**가 `stale_observation:`으로 시작 — 다시 찾지 못해 입력하지 않음). 최상위 `reason`은 "처리되지 않은 fail: 찾은 뒤 창이 바뀌었다 …"이고 `stale_observation` 낱말은 스텝 메시지에만 있다. `G5 실패`(엉뚱한 곳 클릭, 다른 오류)는 실패
- 게임이 창 크기 바꾸기를 거부하면 `창 크기 바꾸기` 스텝이 "맞추지 못했다"로 끝난다. 그러면 `move_click` 그래프로 G4처럼 실행하고 기다리는 동안 **창 테두리를 끌어 크기를 바꾼다**. 그렇게 했다고 적는다
- 기록: 결과 ①/②, verdict·code·reason

### G6 포커스 잃음

1. `notepad`로 메모장을 열어 게임 옆에 둔다(겹치지 않게)
2. 실행하고 10초 안에 **메모장 안을 클릭**한다:

```powershell
$r = kb run tests/focus_loss.graph.json --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason, failure_titles; Keep-Run g6_focus
```

- 기대 결과: `verdict` = `error`, `code` = `window_not_foreground`. 메모장에 아무 글자도 들어가지 않았고 게임에도 입력이 없다. 게임 창이 저절로 앞으로 오지 않는다
- 기록: verdict·code, 메모장에 글자가 들어갔는지

### G7 전체화면 전환

게임 영상 설정에서 화면 모드를 바꿔 가며 화면 찍기를 한다. 각 모드에서 실행 → 10초 안에 게임으로 돌아간다(Alt+Tab, 터미널이 게임을 가리지 않게):

```powershell
$r = kb run tests/capture.graph.json --set capture.delay_ms=10000 --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason; Keep-Run g7_windowed
```

| 모드 | 증거 이름 |
|---|---|
| 창 모드 | `g7_windowed` |
| 테두리 없는 전체화면 (borderless) | `g7_borderless` |
| 독점 전체화면 (exclusive) | `g7_exclusive` |

- 기대 결과: 모드마다 ① `pass`이고 `steps\…_screen.png`가 그 순간 게임 화면 그대로(검은 화면·이전 화면이 아님), 또는 ② `error`이고 `code`가 `capture_timeout`·`capture_unsupported`·`window_minimized` 중 하나(정확한 사유로 끝남). **`pass`인데 PNG가 검거나 엉뚱하면 실패**다
- 게임에 테두리 없는 모드가 없으면 "없음"으로 적는다. 테두리 없는 모드에서는 `dpi_check`도 한 번 돌려(`g7_borderless_dpi`) 입력까지 되는지 적는다
- 기록: 모드별 verdict·code, PNG가 맞는지

### G8 한글 입력

1. 입력 칸이 보이는 화면에서 `kb run tests/capture.graph.json`(`Keep-Run g8_before`). 그 PNG를 그림판으로 열어 **입력한 글자가 들어갈 영역**의 왼쪽 위 좌표(상태 표시줄)와 너비·높이를 재고 `local.json`의 `korean.region`을 `[x, y, w, h]`로 고친다
2. 정해 둔 문자열 세 개를 차례로 넣는다. **매번 실행 전에 입력 칸을 비운다**(게임에서 직접 지운다):

```powershell
$texts = "가나다라마바사", "값싼 닭볶음 밟기", "Kookabug 한글 Test 123"   # 완성형, 받침·겹받침, 영문·숫자 섞임
for ($i = 0; $i -lt $texts.Count; $i++) {
  Read-Host "입력 칸을 비우고 Enter ($($texts[$i]))" | Out-Null
  $r = kb run tests/korean_input.graph.json --set "korean.text=$($texts[$i])" --json | ConvertFrom-Json
  "$($texts[$i]) → $($r.verdict) $($r.code)"; Keep-Run "g8_$($i + 1)"
}
```

3. 각 증거 폴더의 `steps\…_typed.png`(입력 뒤 화면)와 `steps\…_ocr.txt`(그 영역 OCR)를 연다

- 통과 기준: **세 개 모두 화면에 정해 둔 문자열이 정확히 보인다**(스크린샷으로 사람이 판정). OCR 글자는 참고로 적는다(OCR 오독은 G9에서 따로 잰다)
- 게임이 한글을 받지 못하면(빈칸·물음표·깨짐) 그대로 적고, 보완 대상 게임으로 1~3을 다시 한다. 보완 대상도 못 받으면 실패 — IME 조합 입력 등 방식 추가를 별도 결정으로 올린다
- 기록: 문자열별 화면 결과(정확/다름 — 어떻게), OCR 글자, 쓴 게임

### G9 OCR 수치

1. 표본 폴더를 만든다: `New-Item -ItemType Directory -Force "$ev\ocr-samples" | Out-Null`
2. 화면 PNG를 모은다: 배율 100%에서 글자가 있는 여러 화면을 `kb run tests/capture.graph.json`으로 찍어 `steps\…_screen.png`를 `$ev\ocr-samples\`에 `d100_<번호>.png` 이름으로 복사한다. 150%·200%는 G2·G3에서 찍은 것과 그 배율에서 더 찍은 것을 `d150_<번호>.png`·`d200_<번호>.png`로
3. `$ev\ocr-samples\truth.jsonl`을 메모장으로 만들고(UTF-8) 표본마다 한 줄을 쓴다. `region`은 그림판에서 잰 글자 줄 하나의 `[x, y, w, h]`, `text`는 **사람이 화면을 보고 적은 정답**, `tags`는 배율:

```jsonl
{"id": "d100-01", "image": "d100_01.png", "region": [120, 40, 300, 36], "text": "게임 시작", "tags": ["dpi100"]}
{"id": "d150-01", "image": "d150_01.png", "region": [180, 60, 450, 54], "text": "Options", "tags": ["dpi150"]}
```

표본 구성: **전체 30개 이상**, 그중 **배율 100% 20개 이상**·**150% 5개 이상**·**200% 5개 이상**, **한국어(한글이 든 정답) 15개 이상**. 한 PNG에서 여러 줄을 표본으로 써도 된다(줄마다 `id`가 다르게).

4. 계산한다:

```powershell
Push-Location $repo   # 계산만 레포에서 하고 실제 게임 워크스페이스($ws)로 돌아간다 (G10부터 다시 $ws의 그래프를 쓴다)
try {
  uv run python tools/ocr_bench.py "$ev\ocr-samples" --m1-real-game --json-out "$ev\ocr_bench.json" 2>&1 | Tee-Object "$ev\ocr_bench.txt"; "종료 코드 $LASTEXITCODE"
} finally { Pop-Location }
Get-Location   # $ws여야 한다
```

- `--m1-real-game` = 문자 정확도 ≥ 0.95, 한국어 표본만 ≥ 0.90, 영역 읽기 지연 중앙값 ≤ 200 ms·p95 ≤ 500 ms, 그리고 위 표본 구성과 모든 표본에 `region`이 있는지
- 통과 기준: 종료 코드 0. 1이면 `기준 미달:` 줄이 사유다. 표본 형식 오류는 2(줄 번호가 나온다)
- 실패 표본(`✗`)은 정답·region을 다시 보고, 사람이 잘못 적은 것만 고친다(정답을 OCR 결과에 맞추지 않는다). 미달이면 모델·전처리 개선이나 지원 범위 결정을 올린다
- 기록: 표본 수(전체·한국어·배율별), 문자 정확도, 한국어 정확도, 지연 중앙값·p95, 추론 최댓값, 실패 표본 목록, 기준 PC(G0)

### G10 강제 종료 키 해제

누른 키가 runner 강제 종료 뒤에도 떼어지는지 실제 게임에서 본다.

1. 게임에서 주행을 시작한다(SuperTuxKart: 아무 트랙 1인 연습). `hold.key`는 기본 `up`(가속)이다. 화상 키보드(`osk`)를 띄워 두면 눌린 키가 표시된다
2. 실행한다. 2초 뒤 가속 키를 60초 동안 누르고 있는다:

```powershell
kb run tests/hold_key.graph.json
```

3. 카트가 가속하는 것을 본 뒤 **PowerShell 창을 클릭하고 Ctrl+C를 두 번** 누른다(첫 번째 = 취소 요청, 두 번째 = runner를 바로 끝냄)
4. 끝나면 `Keep-Run g10_hold`, 게임 창을 다시 클릭한다

```powershell
Select-String -Encoding UTF8 -Path (Join-Path "$ev\g10_hold" events.jsonl) -Pattern '"run.end"|"input.recovered"'
```

- 기대 결과: 게임으로 돌아갔을 때 카트가 더 가속하지 않는다(키가 눌린 채 남지 않음). 화상 키보드에도 눌린 키가 없다. `run.end`가 있고 `input.recovered`(누가 뗐는지 `by`)가 있다
- `hold.key=shift`로 한 번 더 하면 화상 키보드의 Shift 표시로 OS 상태를 더 분명히 볼 수 있다(`--set hold.key=shift`, `g10_shift`)
- 기록: 게임에서 키가 떼어졌는지, 화상 키보드, `run.end`의 `code`·`input_recovery`, `input.recovered`의 `by`

### G11 한국어 자판 오른쪽 Ctrl·Alt

Kookabug은 `rctrl`·`ralt`를 가상 키 코드로만 보낸다(한국어 자판에서 그 자리 물리 키는 한자·한/영이라 스캔 코드를 쓰지 않음). DirectInput·Raw Input으로 키를 읽는 게임이 이것을 받는지 게임의 **키 설정 화면**으로 본다.

1. Windows 입력 언어가 **한국어(Microsoft 입력기)** 인지 확인한다(작업 표시줄 오른쪽 `가`/`A`)
2. 게임 설정 → 조작(키보드) 화면을 연다
3. 실행하고 8초 안에 바꿀 동작 하나(예: 아이템 쓰기)를 눌러 **"키를 누르세요" 상태**로 둔다. 8초 뒤 그래프가 그 키를 0.5초 누른다:

```powershell
kb run tests/hold_key.graph.json --set hold.key=rctrl --set hold.ms=500 --set hold.delay_ms=8000; Keep-Run g11_rctrl
kb run tests/hold_key.graph.json --set hold.key=ralt --set hold.ms=500 --set hold.delay_ms=8000; Keep-Run g11_ralt
kb run tests/hold_key.graph.json --set hold.key=lctrl --set hold.ms=500 --set hold.delay_ms=8000; Keep-Run g11_lctrl
```

4. 비교용으로 사람이 같은 화면에서 물리 키(오른쪽 Ctrl 자리, 오른쪽 Alt 자리, 왼쪽 Ctrl)를 눌렀을 때 게임이 보여 주는 이름도 적는다
5. 키 설정을 원래대로 돌린다

- 통과 기준: **오른쪽 Ctrl·오른쪽 Alt** 둘 다 게임이 키 하나로 받는다(설정 칸에 키 이름이 들어감). 아무것도 안 들어가면 실패 — 미국 자판 스캔 코드로 보내는 선택을 별도 결정으로 올린다
- 기록: `rctrl`·`ralt`·`lctrl`이 들어간 키 이름, 물리 키의 이름

### G12 관리자 권한·잠금 화면

1. **관리자 권한 게임**: 게임을 닫고 게임 실행 파일을 오른쪽 클릭 → "관리자 권한으로 실행". 기준 화면에서, **보통 PowerShell**(관리자 아님)로:

```powershell
$r = kb run tests/dpi_check.graph.json --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason; Keep-Run g12_elevated
```

기대 결과: `error`, `code` = `target_elevated`(입력을 보내기 전에 끝남). 끝나면 게임을 보통 권한으로 다시 띄운다.

2. **잠금 화면**: 실행하고 곧바로 **Win+L**로 잠근다. 15초 뒤 잠금을 푼다:

```powershell
$r = kb run tests/focus_loss.graph.json --json | ConvertFrom-Json; $r | Select-Object verdict, code, reason; Keep-Run g12_locked
```

기대 결과: `error`, `code` = `input_desktop_unavailable`.

- 기록: 두 경우의 verdict·code. 관리자 권한이 아닌 게임에서 `target_elevated`가 나오면 그것도 적는다(무결성 판정 규칙을 다시 본다)

## 4. 정리와 판정

1. `manual_result.md`의 모든 행에 결과 값·증거 경로·통과(O/X)를 채운다. 수치 칸(G9)과 기준 PC(G0)를 빠뜨리지 않는다
2. 판정
   - 모든 행이 O → **M1 최종 완료**
   - X가 있으면 → "별도 결정" 표에 그 항목·사유·제안(지원 범위 축소, 방식 추가 등)을 적는다. M1은 최종 완료가 아니다
3. 증거 폴더 `$ev`와 `manual_result.md`는 레포에 올리지 않는다(`.orchestration/`은 git 제외 폴더)
