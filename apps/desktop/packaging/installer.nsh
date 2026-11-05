; Kookabug NSIS 조각 (구현 계획 M2 2.14). electron-builder 기본 스크립트(app-builder-lib templates/nsis)의
; 훅에 끼운다. 직접 include 하지 않는다: tools/installer/build.py가 판마다 만든 머리 파일이 아래 값을 정한
; 뒤 이 파일을 include 한다.
;   KB_MAX_REL_PATH   설치 폴더 기준 가장 긴 상대 경로 길이
;   kbRemoveTree      설치 트리의 맨 위 항목을 지우는 매크로 (감사한 트리에서 만든다)
;
; - 사용자별 설치만 한다 (M1 U2). 설치 범위(모든 사용자/나만) 고르기 화면을 넣지 않는다 (no-install-mode-page.nsh)
; - 사용자 PATH에 bin을 더하고 제거할 때 그 항목만 뺀다. 다른 항목·구분자·값 형식은 그대로 둔다. 읽지 못하거나
;   너무 길면 고치지 않고 안내만 한다 (user-path.nsh)
; - 실행 중인 앱을 끌 때는 설치 폴더 안(경계 \ 포함)의 실행 파일로 돈 프로세스만 본다. 확인할 수 없으면 아무것도
;   끄지 않고 멈춘다 (다른 판·다른 폴더의 Kookabug를 끄지 않는다)
; - 예제 워크스페이스의 local.json(예제 게임을 띄울 동봉 Python)을 UTF-8로 쓴다
; - 제거는 설치한 항목만 지우고 설치 폴더가 비면 그것도 지운다 (폴더 통째 RMDir /r 대신)
; - StdUtils 플러그인(LGPL-2.1)을 쓰지 않는다: 기본 스크립트가 부르는 StdUtils 함수 셋을 System
;   플러그인·NSIS 명령으로 바꿔 정의한다. 플러그인을 부르는 코드가 없으면 설치·제거 프로그램에 넣지
;   않는다 (tools/tests/test_installer_electron.py가 설치 파일 목록으로 확인)
; 이 파일은 UTF-8이다 (electron-builder가 makensis에 -INPUTCHARSET UTF8을 준다)

!ifndef KB_MAX_REL_PATH
  !error "KB_MAX_REL_PATH가 없다. tools/installer/build.py로 빌드한다"
!endif
!ifmacrondef kbRemoveTree
  !error "kbRemoveTree가 없다. tools/installer/build.py로 빌드한다"
!endif

!include LogicLib.nsh
!include FileFunc.nsh
!include WinMessages.nsh
!include "${__FILEDIR__}\user-path.nsh"

; 이 폴더 (매크로가 펼쳐지는 곳에서는 __FILEDIR__가 그 파일을 가리킨다)
!define KB_PACKAGING_DIR "${__FILEDIR__}"

; Windows 경로 한도 (MAX_PATH 260, 끝 NUL 제외)
!define KB_PATH_LIMIT 259

; 설치 폴더 이름 = 판 이름 (기본값은 실행 파일 이름 executableName)
!undef APP_FILENAME
!define APP_FILENAME "${PRODUCT_NAME}"
; 기본 스크립트는 차등 업데이트용으로 설치 파일 사본을 %LOCALAPPDATA%에 둔다. 자동 업데이트는 보류(H5)라
; 설치 끝에 지운다. 판마다 다른 이름이라 다른 판의 사본을 건드리지 않는다
!ifdef APP_INSTALLER_STORE_FILE
  !undef APP_INSTALLER_STORE_FILE
  !define APP_INSTALLER_STORE_FILE "${APP_FILENAME}-updater\installer.exe"
!endif

; ---------------------------------------------------------------- StdUtils 대신

!undef StdUtils.TestParameter
!define StdUtils.TestParameter '!insertmacro kbTestParameter'
!undef StdUtils.GetAllParameters
!define StdUtils.GetAllParameters '!insertmacro kbGetAllParameters'
!undef StdUtils.GetParentPath
!define StdUtils.GetParentPath '!insertmacro kbGetParentPath'
!undef StdUtils.ExecShellAsUser
!define StdUtils.ExecShellAsUser '!insertmacro kbExecShellAsUser'

; 명령줄에 /<name>(또는 /<name>=값)이 있으면 "true", 없으면 "false" (대소문자 무시).
; LogicLib 조건 매크로(${isUpdated} 등) 안에서 불리므로 LogicLib 블록을 쓰지 않는다
!macro kbTestParameter out name
  Push $0
  Push $1
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 `/${name}` $1
  StrCpy $0 "true"
  IfErrors 0 +2
  StrCpy $0 "false"
  Pop $1
  Exch $0
  Pop ${out}
!macroend

; 실행 파일 이름을 뺀 전체 명령줄 (/D= 포함). NSIS의 $CMDLINE은 /D= 앞에서 잘린다
!macro kbGetAllParameters out truncate
  Push $0
  Push $1
  Push $2
  System::Call 'kernel32::GetCommandLineW() w .r0'
  StrCpy $1 $0 1
  ${If} $1 == '"'
    StrCpy $2 1
    ${Do}
      StrCpy $1 $0 1 $2
      IntOp $2 $2 + 1
      ${IfThen} $1 == "" ${|} ${ExitDo} ${|}
      ${IfThen} $1 == '"' ${|} ${ExitDo} ${|}
    ${Loop}
  ${Else}
    StrCpy $2 0
    ${Do}
      StrCpy $1 $0 1 $2
      ${IfThen} $1 == "" ${|} ${ExitDo} ${|}
      ${IfThen} $1 == " " ${|} ${ExitDo} ${|}
      IntOp $2 $2 + 1
    ${Loop}
  ${EndIf}
  StrCpy $0 $0 "" $2
  ${Do}
    StrCpy $1 $0 1
    ${IfThen} $1 != " " ${|} ${ExitDo} ${|}
    StrCpy $0 $0 "" 1
  ${Loop}
  Pop $2
  Pop $1
  Exch $0
  Pop ${out}
!macroend

; 마지막 경로 구성요소를 뺀 부모 경로
!macro kbGetParentPath out path
  Push $0
  Push $1
  Push $2
  StrCpy $0 `${path}`
  StrLen $2 $0
  ${Do}
    IntOp $2 $2 - 1
    ${IfThen} $2 < 0 ${|} ${ExitDo} ${|}
    StrCpy $1 $0 1 $2
    ${IfThen} $1 == "\" ${|} ${ExitDo} ${|}
    ${IfThen} $1 == "/" ${|} ${ExitDo} ${|}
  ${Loop}
  ${If} $2 < 0
    StrCpy $0 ""
  ${Else}
    StrCpy $0 $0 $2
  ${EndIf}
  Pop $2
  Pop $1
  Exch $0
  Pop ${out}
!macroend

; 사용자별 설치라 설치 프로그램이 권한을 올리지 않는다: 그대로 연다
!macro kbExecShellAsUser out file verb args
  ExecShell `${verb}` `${file}` `${args}`
  StrCpy ${out} "ok"
!macroend

; ---------------------------------------------------------------- 설치 범위·폴더 길이

; 기본 스크립트는 perMachine: false여도 설치 범위(모든 사용자/나만) 화면을 페이지 목록에 넣고, 그 화면의 앞 함수에서
; customInstallMode로 건너뛴다. 그 건너뛰기에 기대지 않는다: Windows Sandbox(관리자·UAC 꺼짐)에서 그 화면이 떴고
; (M2 사람 확인 S3), 건너뛴 화면이 첫 화면(폴더 고르기)의 "뒤로"로 남아 누르면 설치 프로그램이 그냥 끝났다.
; 그래서 그 페이지를 아예 넣지 않는다: 기본 스크립트가 PAGE_INSTALL_MODE를 넣기 직전 훅에서 그 매크로를 빈
; 것(no-install-mode-page.nsh)으로 바꾼다. 설치 모드는 .onInit(initMultiUser)이 사용자별로 정한다 (무인 설치와 같은 길)
!macro kbDropInstallModePage
  !macroundef PAGE_INSTALL_MODE
  !include "${KB_PACKAGING_DIR}\no-install-mode-page.nsh"
!macroend

!macro customWelcomePage
  !insertmacro kbDropInstallModePage
!macroend

!macro customUnWelcomePage
  !insertmacro MUI_UNPAGE_WELCOME
  !insertmacro kbDropInstallModePage
!macroend

; 기본 스크립트(multiUserUi.nsh)가 맨 위에 선언한 그 화면의 변수. 화면이 없으면 아무도 쓰지 않아 makensis가 경고(6001,
; warningsAsErrors라 빌드 실패)를 낸다. 초기화 함수에서 비워 둔다
!macro kbInstallModePageVars
  StrCpy $HasTwoAvailableOptions ""
  StrCpy $RadioButtonLabel1 ""
  StrCpy $isForceMachineInstall "0"
  StrCpy $isForceCurrentInstall "1"
!macroend

!macro customUnInit
  !insertmacro kbInstallModePageVars
!macroend

; 설치 폴더 + 가장 긴 상대 경로가 MAX_PATH를 넘으면 파일을 푸는 중에 실패한다. 무인 설치(/D=)는 시작할 때
; 사유를 남기고 종료 코드 7로 끝난다
!macro customInit
  !insertmacro kbInstallModePageVars
  StrLen $0 $INSTDIR
  IntOp $1 ${KB_PATH_LIMIT} - ${KB_MAX_REL_PATH}
  IntOp $1 $1 - 1
  ${If} $0 > $1
    MessageBox MB_OK|MB_ICONSTOP "설치 폴더 경로가 너무 길다 ($0자, 최대 $1자). 더 짧은 폴더를 고른다.$\r$\n$INSTDIR" /SD IDOK
    SetErrorLevel 7
    Quit
  ${EndIf}
!macroend

!ifndef BUILD_UNINSTALLER
  ; 폴더 고르기 화면: 너무 길면 다음 단추를 막는다. 기본 스크립트가 폴더 이름(\판 이름)을 덧붙일 수 있어
  ; 그 길이만큼 여유를 둔다
  Function .onVerifyInstDir
    StrLen $0 $INSTDIR
    StrLen $1 "\${APP_FILENAME}"
    IntOp $0 $0 + $1
    IntOp $1 ${KB_PATH_LIMIT} - ${KB_MAX_REL_PATH}
    IntOp $1 $1 - 1
    ${If} $0 > $1
      Abort
    ${EndIf}
  FunctionEnd
!endif

; ---------------------------------------------------------------- 실행 중인 앱 끄기

; 기본 스크립트의 확인(allowOnlyOneInstallerInstance.nsh _CHECK_APP_RUNNING)은 PowerShell을 못 쓰면 실행 파일
; 이름만으로 taskkill /IM 하고, PowerShell 분기도 설치 폴더 경계(\) 없이 앞부분만 비교한다. 그러면 다른 판·다른
; 폴더의 Kookabug(저장 안 한 편집 포함)를 끌 수 있다 (T13 검수 1차 High). 여기서는:
; - 설치 폴더 + "\"로 시작하는 실행 파일 경로의 프로세스만 찾는다 (경로는 환경 변수로 넘겨 따옴표 문제가 없다)
; - 제거 프로그램 자신은 뺀다 (임시 폴더로 자신을 복사해 다시 띄우는 동안 원본이 남아 있을 수 있다)
; - 확인할 수 없으면(PowerShell 없음·조회 실패) 아무것도 끄지 않고 멈춘다
; PowerShell 종료 코드: 0 = 있음, 1 = 없음, 3 = 확인 실패
!define KB_PS_FILTER "$$d = $$env:KOOKABUG_INSTALL_DIR; $$skip = $$env:KOOKABUG_SKIP_EXE; if (-not $$d) { exit 3 }; $$p = @(Get-CimInstance -ClassName Win32_Process -ErrorAction Stop | Where-Object { $$_.ExecutablePath -and $$_.ExecutablePath.StartsWith($$d, [System.StringComparison]::OrdinalIgnoreCase) -and -not [string]::Equals($$_.ExecutablePath, $$skip, [System.StringComparison]::OrdinalIgnoreCase) })"

!macro kbInstallProcesses action out
  System::Call 'kernel32::SetEnvironmentVariableW(w "KOOKABUG_INSTALL_DIR", w "$INSTDIR\")'
  System::Call 'kernel32::SetEnvironmentVariableW(w "KOOKABUG_SKIP_EXE", w "$INSTDIR\${UNINSTALL_FILENAME}")'
  !if "${action}" == "find"
    nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "try { ${KB_PS_FILTER}; if ($$p.Count -gt 0) { exit 0 } else { exit 1 } } catch { exit 3 }"`
  !else
    nsExec::Exec `"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -Command "try { ${KB_PS_FILTER}; $$p | ForEach-Object { Stop-Process -Id $$_.ProcessId -Force -ErrorAction SilentlyContinue }; exit 0 } catch { exit 3 }"`
  !endif
  Pop ${out}
!macroend

!macro customCheckAppRunning
  !insertmacro kbInstallProcesses find $R0
  ${If} $R0 == 0
    ${If} ${isUpdated}
      Sleep 1000
    ${Else}
      MessageBox MB_OKCANCEL|MB_ICONEXCLAMATION "$(appRunning)" /SD IDOK IDOK +2
      Quit
    ${EndIf}
    DetailPrint "$(appClosing)"
    StrCpy $R1 0
    ${Do}
      IntOp $R1 $R1 + 1
      !insertmacro kbInstallProcesses stop $R0
      Sleep 1500
      !insertmacro kbInstallProcesses find $R0
      ${IfThen} $R0 != 0 ${|} ${ExitDo} ${|}
      ${IfThen} $R1 >= 5 ${|} ${ExitDo} ${|}
    ${Loop}
    ${If} $R0 == 0
      MessageBox MB_OK|MB_ICONSTOP "$(appCannotBeClosed)" /SD IDOK
      SetErrorLevel 8
      Quit
    ${EndIf}
  ${EndIf}
  ${If} $R0 != 0
  ${AndIf} $R0 != 1
    MessageBox MB_OK|MB_ICONSTOP "설치 폴더에서 실행 중인 Kookabug가 있는지 확인할 수 없다 (PowerShell 조회 실패: $R0). 다른 프로그램을 끄지 않도록 멈춘다. Kookabug를 모두 닫고 다시 실행한다.$\r$\n$INSTDIR" /SD IDOK
    SetErrorLevel 9
    Quit
  ${EndIf}
!macroend

; ---------------------------------------------------------------- 예제 local.json

; ${out} = ${path}의 \를 /로 바꾼 값 (JSON에 그대로 넣을 수 있게)
!macro kbSlashes out path
  Push $0
  Push $1
  Push $2
  Push $3
  StrCpy $0 `${path}`
  StrCpy $3 ""
  StrCpy $2 0
  ${Do}
    StrCpy $1 $0 1 $2
    ${IfThen} $1 == "" ${|} ${ExitDo} ${|}
    ${IfThen} $1 == "\" ${|} StrCpy $1 "/" ${|}
    StrCpy $3 "$3$1"
    IntOp $2 $2 + 1
  ${Loop}
  StrCpy $0 $3
  Pop $3
  Pop $2
  Pop $1
  Exch $0
  Pop ${out}
!macroend

; 예제 워크스페이스의 사람마다 다른 설정: 예제 게임을 띄울 Python = 동봉 Python. UTF-8(BOM 없음)로 쓴다
; (설치 폴더에 한글이 있을 수 있다. FileWrite는 시스템 코드 페이지로 쓴다)
!macro kbWriteExampleLocal
  StrCpy $1 "$INSTDIR\examples\sample-game\workspace\.kookabug"
  CreateDirectory $1
  !insertmacro kbSlashes $2 "$INSTDIR\examples\sample-game"
  !insertmacro kbSlashes $3 "$INSTDIR\python\python.exe"
  StrCpy $4 '{$\n  "format": "kookabug.local/0",$\n  "settings": {$\n    "game.cwd": "$2",$\n    "game.executable": "$3"$\n  }$\n}$\n'
  ClearErrors
  FileOpen $5 "$1\local.json" w
  ${IfNot} ${Errors}
    System::Call 'kernel32::WideCharToMultiByte(i 65001, i 0, w r4, i -1, p 0, i 0, p 0, p 0) i .r6'
    ${If} $6 > 1
      System::Alloc $6
      Pop $7
      System::Call 'kernel32::WideCharToMultiByte(i 65001, i 0, w r4, i -1, p r7, i r6, p 0, p 0) i .r6'
      IntOp $6 $6 - 1
      System::Call 'kernel32::WriteFile(p r5, p r7, i r6, *i 0, p 0) i'
      System::Free $7
    ${EndIf}
    FileClose $5
  ${EndIf}
!macroend

; ---------------------------------------------------------------- 설치·제거 훅

!macro customInstall
  !insertmacro kbAddToUserPath "$INSTDIR\bin" "${INSTALL_REGISTRY_KEY}"
  !insertmacro kbWriteExampleLocal
  !ifdef APP_INSTALLER_STORE_FILE
    Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    !insertmacro kbGetParentPath $0 "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    RMDir $0
  !endif
!macroend

!macro customUnInstall
  !insertmacro kbRemoveFromUserPath "${INSTALL_REGISTRY_KEY}"
  !ifdef APP_INSTALLER_STORE_FILE
    Delete "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    !insertmacro kbGetParentPath $0 "$LOCALAPPDATA\${APP_INSTALLER_STORE_FILE}"
    RMDir $0
  !endif
!macroend

; 설치한 맨 위 항목(감사한 트리 그대로)과 설치 뒤 생기는 파일(예제 실행 기록 runs\·.kookabug\, Python이
; 다시 쓰는 __pycache__)을 지운다. 사용자가 고른 폴더에 다른 파일이 있으면 남긴다
!macro customRemoveFiles
  SetOutPath $TEMP
  !insertmacro kbRemoveTree
  Delete "$INSTDIR\${UNINSTALL_FILENAME}"
  RMDir $INSTDIR
!macroend
