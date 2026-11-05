# 설치 파일 (Windows)

Python이 없는 Windows에 Kookabug 데스크톱 앱과 CLI를 설치하는 사용자별 설치 파일을 만든다 (구현 계획 4장,
M1 2.12, M2 2.14). M2부터 electron-builder(고정판 `apps/desktop/package.json`) NSIS 설치 파일이다. 설치 폴더
구조는 M1 그대로에 데스크톱 앱을 더했다.

| 파일 | 하는 일 |
|---|---|
| `pbs.toml` | 빌드 입력 고정: uv 판(실행기 구성요소 표의 기준), python-build-standalone(태그·파일·주소·크기·SHA256), 앱 로컬 VC++ 런타임 파일 |
| `build.py` | 스테이징 트리(M1 구조) → 빌드 입력 감사 → 제거 → compileall → 데스크톱 앱 배포 빌드 → electron-builder `--dir`(최종 트리) → 최종 트리 감사·NOTICES → 판마다 `--prepackaged` NSIS (제품 판, `--test-setup`이면 테스트 판도) |
| `../../apps/desktop/electron-builder.yml` | electron-builder 기본 설정 (사용자별 설치, 실행 파일 이름, zip 묶음). 판·경로는 build.py가 extends 하는 설정으로 넣는다 |
| `../../apps/desktop/packaging/installer.nsh` | NSIS 조각: 설치 범위 화면을 넣지 않음(`no-install-mode-page.nsh`, build.py가 컴파일 표식 확인), 폴더 길이 제한, 설치 폴더 경계 안 프로세스만 끄기(확인 못 하면 멈춤), 예제 `local.json`(UTF-8), 제거 범위, StdUtils(LGPL) 대신 System 플러그인 |
| `../../apps/desktop/packaging/user-path.nsh` | 사용자 PATH 더하기·빼기: 형식·크기를 먼저 읽고, 못 읽거나 한도면 고치지 않음. 이 설치가 더한 항목과 구분자만 뺌 (`tools/tests/test_installer_user_path.py`가 임시 키로 실제 NSIS 실행) |
| `dllcheck.py` | 설치 트리의 모든 `.pyd`·`.dll`·`.exe` import를 그 파일 폴더·앱 폴더·등록 근거가 확인된 DLL 폴더·System32로만 풀어 본다 |
| `smoke.py` | 판 확인 → 무인 설치 → 최종 트리 감사·앱 번들 검사 → Python 없는 환경 CLI 스모크 → 앱 스모크(`Kookabug.exe --smoke`) → DLL 검사 → 제거 → 설치 흔적 원상 확인 |

설치 파일의 판은 둘이다. **제품 판**(`Kookabug`, 배포용)과 **테스트 판**(`Kookabug Test`: appId·이름·GUID(제거
등록 키)·기본 폴더·실행 파일 이름 `KookabugTest.exe`가 모두 다름). 무인 설치 검사는 테스트 판만 설치하므로 이
PC에 실제 Kookabug가 설치돼 있거나 실행 중이어도 그 제거 등록·폴더·PATH·앱을 건드리지 않는다. 실행 파일
이름이 달라 최종 트리는 판마다 만든다(같은 스테이징 트리).

설치 파일은 **감사한 트리 그대로**를 묶는다: build.py가 electron-builder `--dir`로 만든 `win-unpacked`를
감사하고 NOTICES를 쓴 뒤, 같은 폴더로 `--prepackaged` NSIS를 만든다. 스모크는 설치된 트리에 같은 감사를 다시
건다.

실행기(`bin\kookabug.exe` 등)는 빌드에 쓴 uv의 실행기 스텁이라, 그 안에 정적으로 든 크레이트를
`tools/third_party_licenses/uv-trampoline-sbom.json`(uv 0.13.6 `crates/uv-trampoline/Cargo.lock`의 실행 시
의존성, 체크섬 포함)으로 적고 원문은 `fetch_crate_licenses.py --sbom`이 모은다. uv를 올리면 `pbs.toml`
`[uv]`, CI `UV_VERSION`, SBOM과 원문을 함께 다시 만든다 — 빌드는 다른 판의 uv로는 멈춘다.

제거할 파일 목록은 따로 두지 않고 `tools/native-licenses.toml`의 `[[strip]]`을 쓴다. 최종 트리 감사가 그
목록의 파일이 하나라도 남으면 실패시키므로, 빌드가 지우는 목록과 감사가 확인하는 목록이 같아야 한다.

## 설치 폴더 구조

```
%LOCALAPPDATA%\Programs\Kookabug\
├─ Kookabug.exe            데스크톱 앱 (Electron 44.8.0의 electron.exe, 확정 아이콘 A1. 테스트 판은 KookabugTest.exe)
├─ resources\app.asar      앱 배포 빌드 (main·preload·렌더러, E2E 검사 훅 없음)
├─ ffmpeg.dll, *.pak, …    Electron 배포물 (기본 앱 default_app.asar·판 파일 version은 뺀다)
├─ LICENSE.electron.txt, LICENSES.chromium.html
├─ python\                 python-build-standalone + 런타임 의존성 + Kookabug 패키지(kookabug-platform 포함)
│                          + VC++ 런타임(앱 로컬)
├─ bin\kookabug.exe        실행기 (사용자 PATH에 bin을 더한다. 앱이 daemon을 띄울 때 쓰는 CLI)
├─ ocr-models\             OCR 모델·라이선스 근거 원문 (models.toml의 SHA256)
├─ examples\sample-game\   예제 게임·화면 PNG·장면 표·예제 워크스페이스 (.kookabug\local.json은 설치 때 쓴다)
├─ licenses\               LICENSE.txt, THIRD_PARTY_NOTICES.txt, ffmpeg-SOURCE.txt
├─ VERSION
└─ Uninstall Kookabug.exe  제거 프로그램 (NSIS)
```

- 실행기는 uv가 만든 콘솔 실행기의 Python 경로 자원을 빌드 때 `..\python\python.exe` 상대 경로로 바꾼
  것이다. 실행기는 상대 경로를 자기 폴더 기준으로 풀므로 설치 뒤에 고치는 단계가 없다
- 설치 폴더 경로는 짧아야 한다. 가장 긴 상대 경로(약 150자)를 더해 260자(MAX_PATH)를 넘으면 설치 파일이
  풀기 전에 사유를 알리고 멈춘다 (무인 설치 종료 코드 7). 폴더 고르기 화면은 다음 단추를 막는다
- 시작 메뉴 바로 가기를 만든다. 바탕 화면 바로 가기는 만들지 않는다
- 사용자 PATH는 형식·크기를 먼저 읽고, 못 읽거나 NSIS 문자열 한도(8,190자)에 닿으면 고치지 않고 안내만
  한다(설치는 계속). 더할 때는 끝에 `;bin`만 붙이고 원래 형식 그대로 쓴다
- 설치·제거는 설치 폴더 + `\`로 시작하는 실행 파일의 프로세스만 끈다. 확인할 수 없으면(PowerShell 조회
  실패) 아무것도 끄지 않고 멈춘다(무인 종료 코드 9)
- 제거는 설치한 맨 위 항목을 통째로 지우고(예제 실행 기록 `runs\` 포함) 사용자 PATH에서 이 설치가 더한
  `bin` 항목과 그 구분자만 뺀다(다른 항목·빈 항목·형식은 그대로).
  설치 폴더가 비면 그것도 지운다
- `ffmpeg.dll`(LGPL-2.1)은 `license-allowlist.toml` `[[pinned_binary]]`의 Electron 판·경로·sha256 묶음
  예외로만 허용한다. 대응 소스·패치·빌드 정보는 `licenses\ffmpeg-SOURCE.txt`
  (`tools/third_party_licenses/ffmpeg-SOURCE.txt`). Electron을 올리면 이 예외·파일을 새로 만든다
- 앱 묶음은 zip이다(nsisunz 플러그인). 7z 묶음은 nsis7z(7-Zip, LGPL-2.1) 플러그인이 설치 파일에 들어간다

## 빌드

준비물: uv, Node 24·pnpm(`pnpm install` 뒤 `pnpm --filter @kookabug/desktop exec install-electron`),
Visual Studio의 VC++ 재배포 파일(`VC\Redist\MSVC\<버전>\x64\Microsoft.VC143.CRT`, vswhere로 찾는다), OCR
모델(`uv run python tools/fetch_ocr_models.py`). NSIS는 electron-builder가 처음 한 번 받는다.

```powershell
$env:PYTHONPATH = "tools"
uv run python -m installer.build                # build/installer/dist/kookabug-setup-<버전>.exe
uv run python -m installer.build --test-setup   # 테스트 판 kookabug-setup-test-<버전>.exe도
uv run python -m installer.build --no-setup     # 제품 판 최종 트리(build/installer/electron-product/win-unpacked)와 감사까지만
uv run python -m installer.build --check-artifacts   # CI 필수 artifact가 다 있는지만 (빌드 안 함)
```

PBS는 `build/installer-cache`에 한 번 받아 두고, 크기·SHA256을 확인한 바이트만 푼다. 결과 요약(크기·시간·
감사 수치·제거한 파일·고정 바이너리 예외)은 `build/installer/build.json`, electron-builder 로그는
`build/installer/work/eb-*.log`.

## 스모크

```powershell
$env:PYTHONPATH = "tools"
uv run python -m installer.smoke --setup build/installer/dist/kookabug-setup-test-0.1.0.dev0.exe --json build/installer/smoke.json
uv run python -m installer.smoke --installed "$env:LOCALAPPDATA\Programs\Kookabug"   # 설치된 폴더에 스모크만
uv run python -m installer.dllcheck build/installer/electron-product/win-unpacked   # 테스트 판은 electron-test
```

검사 `tools/tests/test_installer_e2e.py`가 같은 경로(`smoke.run_all`)를 쓴다. `run_all`은 기본으로 테스트
판만 받는다(설치 파일 버전 정보의 ProductName으로 가림). 제품 판은 `--variant product`로만, 그것도 제품
제거 등록이 없는 PC에서만 설치한다. 사용자 PATH에 테스트 폴더의 `bin`을 잠시 더하고, 설치 흔적(HKCU 제거
등록 전체, `HKCU\Software\<GUID>`, 시작 메뉴 바로 가기, `%LOCALAPPDATA%\<판 이름>-updater`, 사용자 PATH의
값·형식·존재)은 끝에 처음과 똑같은지 본다. 사용자 PATH는 따로 백업해 두고 다르면 되돌린다(`UserPathGuard`).
제품 판 이름(`Kookabug.exe`)의 대역 프로세스를 `<설치 폴더>2\`에 띄워 두고 설치·제거 뒤에도 살아 있는지
보고, 제거는 그 판의 등록·바로 가기 정리까지 끝날 때까지 기다린다. 앱 스모크는 예제 워크스페이스 사본과 임시 사용자 데이터 폴더(`--user-data-dir`)를
써서 사용자 프로필에 남기지 않고, 끝난 뒤 설치 폴더의 프로세스(daemon)가 남지 않는지 본다. CI `installer`
잡은 테스트 판을 `KOOKABUG_INSTALLER`로 넘긴다.

DLL 검사의 등록 DLL 폴더(`dllcheck.DLL_DIRECTORIES`)는 지금 numpy의 `numpy.libs` 하나다(delvewheel 패치가
`os.add_dll_directory`로 더한다). numpy 안 파일의 import에만 쓰고, `numpy/__init__.py`에 그 패치 글귀가
있을 때만 인정한다. 새 패키지가 이런 폴더를 쓰면 근거와 함께 이 표에 더한다.

## 사람 검증용 설치 절차

깨끗한 Windows(Windows Sandbox 또는 VM)에서 설치 → `doctor` → 예제 게임 실제 실행 → 제거를 하는 절차는
M1 사람 검증 절차서 `Docs/verification/m1-manual.md`의 S절(S1~S6)에 있다. 데스크톱 앱 설치본 확인은 M2 사람
확인 목록(T14)에 더한다. Sandbox 설정은 `Docs/verification/m1-sandbox.wsb`(설치 파일 폴더 읽기 전용,
네트워크 끔).
