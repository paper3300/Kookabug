# 설치 파일 (Windows)

Python이 없는 Windows에 Kookabug CLI를 설치하는 사용자별 설치 파일을 만든다 (구현 계획 4장, M1 2.12).
M2부터 데스크톱 앱 설치 파일(electron-builder NSIS)로 바뀌고 설치 폴더 구조는 그대로 간다.

| 파일 | 하는 일 |
|---|---|
| `pbs.toml` | 빌드 입력 고정: uv 판(실행기 구성요소 표의 기준), python-build-standalone(태그·파일·주소·크기·SHA256), 앱 로컬 VC++ 런타임 파일 |
| `build.py` | 스테이징 트리 만들기 → 빌드 입력 감사 → 제거 → compileall → 최종 트리 감사·NOTICES → `iscc` (제품 판, `--test-setup`이면 테스트 판도) |
| `kookabug.iss` | Inno Setup 6 스크립트 (사용자별 설치, 사용자 PATH, 제거 등록, 예제 `local.json`). AppId·이름·폴더는 판 정의로 받는다. UTF-8 BOM |
| `dllcheck.py` | 설치 트리의 모든 `.pyd`·`.dll`·`.exe` import를 그 파일 폴더·앱 폴더·등록 근거가 확인된 DLL 폴더·System32로만 풀어 본다 |
| `smoke.py` | 판 확인 → 무인 설치 → 최종 트리 감사 → Python 없는 환경 스모크 → 제거 → 제거 등록 원상 확인 |

설치 파일의 판은 둘이다. **제품 판**(`Kookabug`, 배포용)과 **테스트 판**(`Kookabug Test`: AppId·이름·기본
폴더 `Kookabug-Test`·제거 등록 이름이 모두 다름). 무인 설치 검사는 테스트 판만 설치하므로 이 PC에 실제
Kookabug가 설치돼 있어도 그 제거 등록·폴더·PATH를 건드리지 않는다. 두 판은 같은 스테이징 트리로 만든다.

실행기(`bin\kookabug.exe` 등)는 빌드에 쓴 uv의 실행기 스텁이라, 그 안에 정적으로 든 크레이트를
`tools/third_party_licenses/uv-trampoline-sbom.json`(uv 0.13.6 `crates/uv-trampoline/Cargo.lock`의 실행 시
의존성, 체크섬 포함)으로 적고 원문은 `fetch_crate_licenses.py --sbom`이 모은다. uv를 올리면 `pbs.toml`
`[uv]`, CI `UV_VERSION`, SBOM과 원문을 함께 다시 만든다 — 빌드는 다른 판의 uv로는 멈춘다.

제거할 파일 목록은 따로 두지 않고 `tools/native-licenses.toml`의 `[[strip]]`을 쓴다. 최종 트리 감사가 그
목록의 파일이 하나라도 남으면 실패시키므로, 빌드가 지우는 목록과 감사가 확인하는 목록이 같아야 한다.

## 설치 폴더 구조

```
%LOCALAPPDATA%\Programs\Kookabug\
├─ python\                 python-build-standalone + 런타임 의존성 + Kookabug 패키지 + VC++ 런타임(앱 로컬)
├─ bin\kookabug.exe        실행기 (사용자 PATH에 bin을 더한다)
├─ ocr-models\             OCR 모델·라이선스 근거 원문 (models.toml의 SHA256)
├─ examples\sample-game\   예제 게임·화면 PNG·장면 표·예제 워크스페이스 (.kookabug\local.json은 설치 때 쓴다)
├─ licenses\               LICENSE.txt, THIRD_PARTY_NOTICES.txt
├─ VERSION
└─ unins000.exe            제거 프로그램 (Inno Setup)
```

- 실행기는 uv가 만든 콘솔 실행기의 Python 경로 자원을 빌드 때 `..\python\python.exe` 상대 경로로 바꾼
  것이다. 실행기는 상대 경로를 자기 폴더 기준으로 풀므로 설치 뒤에 고치는 단계가 없다. `.cmd`는 Ctrl+C 때
  "일괄 작업을 끝내시겠습니까" 질문이 끼어들어 쓰지 않는다
- 설치 폴더 경로는 짧아야 한다. 가장 긴 상대 경로(약 150자)를 더해 260자(MAX_PATH)를 넘으면 설치 파일이
  복사 전에 사유를 알리고 멈춘다 (무인 설치 종료 코드 7)
- 제거는 위 하위 폴더를 통째로 지우고(예제 실행 기록 `runs\` 포함) 사용자 PATH에서 `bin`만 뺀다.
  설치 폴더가 비면 그것도 지운다

## 빌드

준비물: uv, Inno Setup 6(`winget install JRSoftware.InnoSetup`), Visual Studio의 VC++ 재배포 파일
(`VC\Redist\MSVC\<버전>\x64\Microsoft.VC143.CRT`, vswhere로 찾는다), OCR 모델(`uv run python
tools/fetch_ocr_models.py`).

```powershell
$env:PYTHONPATH = "tools"
uv run python -m installer.build                # build/installer/dist/kookabug-setup-<버전>.exe
uv run python -m installer.build --test-setup   # 테스트 판 kookabug-setup-test-<버전>.exe도
uv run python -m installer.build --no-setup     # 스테이징 트리와 감사까지만
```

PBS는 `build/installer-cache`에 한 번 받아 두고, 크기·SHA256을 확인한 바이트만 푼다. 결과 요약(크기·시간·
감사 수치·제거한 파일)은 `build/installer/build.json`.

## 스모크

```powershell
$env:PYTHONPATH = "tools"
uv run python -m installer.smoke --setup build/installer/dist/kookabug-setup-test-0.1.0.dev0.exe --json build/installer/smoke.json
uv run python -m installer.smoke --installed "$env:LOCALAPPDATA\Programs\Kookabug"   # 설치된 폴더에 스모크만
uv run python -m installer.dllcheck build/installer/stage
```

검사 `tools/tests/test_installer_e2e.py`가 같은 경로(`smoke.run_all`)를 쓴다. `run_all`은 기본으로 테스트
판만 받는다(설치 파일 버전 정보의 ProductName으로 가림). 제품 판은 `--variant product`로만, 그것도 제품
제거 등록이 없는 PC에서만 설치한다. 사용자 PATH에 테스트 폴더의 `bin`을 잠시 더하고, HKCU 제거 등록은
끝에 처음과 똑같은지 본다. CI `installer` 잡은 테스트 판을 `KOOKABUG_INSTALLER`로 넘긴다.

DLL 검사의 등록 DLL 폴더(`dllcheck.DLL_DIRECTORIES`)는 지금 numpy의 `numpy.libs` 하나다(delvewheel 패치가
`os.add_dll_directory`로 더한다). numpy 안 파일의 import에만 쓰고, `numpy/__init__.py`에 그 패치 글귀가
있을 때만 인정한다. 새 패키지가 이런 폴더를 쓰면 근거와 함께 이 표에 더한다.

## 사람 검증용 설치 절차 (초안)

깨끗한 Windows(Windows Sandbox 또는 VM)에서 한다. M1 사람 검증 절차서(`docs/verification/m1-manual.md`)의
설치 절로 옮긴다.

1. 설치 파일을 넣고 실행한다. 관리자 권한을 묻지 않아야 한다. SmartScreen 경고는 "추가 정보 → 실행"
   (코드 서명 전)
2. 새 터미널(PowerShell)을 연다. `where.exe python`이 아무것도 찾지 않는 것을 기록한다
3. `kookabug --version` → `kookabug <버전>`
4. `kookabug doctor --json > doctor.json` → `"ok": true` (desktop 프로필: 입력 데스크톱·WGC 캡처·정지
   화면 재사용·포그라운드까지). 실패하면 그 항목의 `detail`을 결과에 적는다
5. `cd "$env:LOCALAPPDATA\Programs\Kookabug\examples\sample-game\workspace"`, 비밀번호 환경 변수
   `$env:KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = "sample-pass-01"`, `kookabug run tests/inventory_open.graph.json`
   → 종료 코드 0 (예제 게임 창이 뜨고 캡처·OCR·입력으로 인벤토리까지). 실행 중 다른 창을 누르지 않는다
6. 설정 → 앱 → Kookabug 제거 → 설치 폴더가 없고, 새 터미널에서 `kookabug`를 찾지 못한다
7. 결과에 남길 것: 설치 파일 이름·크기, `doctor.json`, 5단계 실행 폴더(`runs\…`, 제거 전에 복사),
   Windows 판(`winver`)과 화면 배율
