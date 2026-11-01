; 사용자 PATH에 설치 폴더 bin을 더하고 빼는 NSIS 매크로 (구현 계획 M2 2.14). installer.nsh가 include 한다.
; 검사(tools/tests/test_installer_user_path.py)는 KB_ENV_KEY를 검사 전용 임시 키로 정하고 같은 매크로를 컴파일한다.
;
; 사용자 PC 설정을 망가뜨리지 않는 것이 먼저다 (T13 검수 1차 High·Mid):
; - 레지스트리 값을 RegGetValueW로 먼저 본다: 없음·형식(REG_SZ/REG_EXPAND_SZ)·바이트 크기. 읽기 실패, 다른 형식,
;   NSIS 문자열 한도(NSIS_MAX_STRLEN)에 닿는 길이, 끝까지 읽히지 않은 값(중간 NUL)이면 **고치지 않고** 안내만 한다
; - 더할 때는 기존 문자열 끝에 ";<bin>"(값이 비었으면 "<bin>")만 붙이고, 붙인 결과의 길이도 쓰기 전에 본다
; - 원래 형식으로 쓴다. 값이 없었으면 REG_EXPAND_SZ로 만들고, 그 사실을 설치 정보 키(statekey)에 남긴다
; - 뺄 때는 이 설치가 더한 경우(statekey의 PathEntry)에만, 그 항목과 붙인 구분자 하나만 지운다. 다른 항목·빈 항목·
;   구분자·형식은 그대로다. 값이 없던 것을 만들었고 남는 것이 없으면 값을 지운다
; - 이미 같은 폴더가 PATH에 있으면 더하지 않고, 그러면 제거 때도 빼지 않는다
;
; 레지스터: $0 값, $1·$2 찾은 항목 시작·길이, $3·$4·$7·$8·$9 임시, $5 읽기 상태, $6 형식, $R0·$R1 제거 때 기록

!ifndef KB_ENV_KEY
  !define KB_ENV_KEY "Environment"
!endif
; 이 길이(글자) 이상인 PATH는 다루지 않는다. NSIS 변수는 NSIS_MAX_STRLEN - 1 글자까지만 담는다
!define /math KB_PATH_MAX ${NSIS_MAX_STRLEN} - 2

!macro kbNotify msg
  DetailPrint `${msg}`
  MessageBox MB_OK|MB_ICONINFORMATION `${msg}` /SD IDOK
!macroend

; 사용자 PATH 읽기 → $5 = ok | absent | error | toolong, $0 = 값(ok일 때), $6 = 형식(1 REG_SZ, 2 REG_EXPAND_SZ)
!macro kbReadUserPath
  StrCpy $0 ""
  StrCpy $6 0
  StrCpy $7 0
  ; HKEY_CURRENT_USER, RRF_RT_REG_SZ | RRF_RT_REG_EXPAND_SZ | RRF_NOEXPAND (다른 형식은 ERROR_UNSUPPORTED_TYPE)
  System::Call 'advapi32::RegGetValueW(p 0x80000001, w "${KB_ENV_KEY}", w "Path", i 0x10000006, *i .r6, p 0, *i .r7) i .r5'
  ${If} $5 == 2
    StrCpy $5 "absent"
  ${ElseIf} $5 != 0
    StrCpy $5 "error"
  ${Else}
    ; 바이트 → UTF-16 글자 수 (끝 NUL 포함)
    IntOp $7 $7 / 2
    ${If} $7 > ${KB_PATH_MAX}
      StrCpy $5 "toolong"
    ${Else}
      ClearErrors
      ReadRegStr $0 HKCU "${KB_ENV_KEY}" "Path"
      ${If} ${Errors}
        StrCpy $5 "error"
        StrCpy $0 ""
      ${Else}
        ; 끝 NUL을 빼고 다 읽혔는가 (값 중간에 NUL이 있으면 문자열이 거기서 끊긴다)
        StrLen $8 $0
        IntOp $8 $8 + 2
        ${If} $8 < $7
          StrCpy $5 "error"
          StrCpy $0 ""
        ${Else}
          StrCpy $5 "ok"
        ${EndIf}
      ${EndIf}
    ${EndIf}
  ${EndIf}
!macroend

; $0에서 ";"로 나뉜 항목 중 ${dir}(slash가 1이면 끝에 \ 붙은 것도)과 같은 첫 항목 → $1 시작(없으면 -1), $2 길이.
; 대소문자 무시(StrCmp)
!macro kbFindPathToken dir slash
  StrCpy $1 -1
  StrCpy $2 0
  StrCpy $3 0
  StrLen $9 $0
  ${Do}
    ${IfThen} $3 > $9 ${|} ${ExitDo} ${|}
    StrCpy $4 $3
    ${Do}
      ${IfThen} $4 >= $9 ${|} ${ExitDo} ${|}
      StrCpy $8 $0 1 $4
      ${IfThen} $8 == ";" ${|} ${ExitDo} ${|}
      IntOp $4 $4 + 1
    ${Loop}
    IntOp $7 $4 - $3
    ${If} $7 > 0
      StrCpy $8 $0 $7 $3
    ${Else}
      StrCpy $8 ""
    ${EndIf}
    StrCpy $7 0
    ${If} $8 == `${dir}`
      StrCpy $7 1
    ${ElseIf} ${slash} == 1
    ${AndIf} $8 == `${dir}\`
      StrCpy $7 1
    ${EndIf}
    ${If} $7 == 1
      StrCpy $1 $3
      StrLen $2 $8
      ${ExitDo}
    ${EndIf}
    IntOp $3 $4 + 1
  ${Loop}
!macroend

!macro kbBroadcastEnvironment
  !ifndef KB_NO_BROADCAST
    SendMessage ${HWND_BROADCAST} ${WM_SETTINGCHANGE} 0 "STR:Environment" /TIMEOUT=500
  !endif
!macroend

; 설치: ${dir}을 사용자 PATH 끝에 더하고, 더했으면 ${statekey}(HKCU)에 PathEntry·PathCreated를 남긴다
!macro kbAddToUserPath dir statekey
  DeleteRegValue HKCU "${statekey}" "PathEntry"
  DeleteRegValue HKCU "${statekey}" "PathCreated"
  !insertmacro kbReadUserPath
  ${If} $5 == "absent"
    StrCpy $0 ""
    StrCpy $6 2
  ${EndIf}
  ${If} $5 == "ok"
  ${OrIf} $5 == "absent"
    !insertmacro kbFindPathToken `${dir}` 1
    ${If} $1 < 0
      ${If} $0 == ""
        StrCpy $0 `${dir}`
      ${Else}
        StrCpy $0 "$0;${dir}"
      ${EndIf}
      StrLen $8 $0
      ${If} $8 >= ${KB_PATH_MAX}
        !insertmacro kbNotify "사용자 PATH가 너무 길어 고치지 않았다. 명령줄에서 쓰려면 ${dir}를 PATH에 직접 더한다"
      ${Else}
        ClearErrors
        ${If} $6 == 1
          WriteRegStr HKCU "${KB_ENV_KEY}" "Path" $0
        ${Else}
          WriteRegExpandStr HKCU "${KB_ENV_KEY}" "Path" $0
        ${EndIf}
        ${If} ${Errors}
          !insertmacro kbNotify "사용자 PATH를 쓰지 못했다. 명령줄에서 쓰려면 ${dir}를 PATH에 직접 더한다"
        ${Else}
          WriteRegStr HKCU "${statekey}" "PathEntry" `${dir}`
          ${If} $5 == "absent"
            WriteRegStr HKCU "${statekey}" "PathCreated" "1"
          ${Else}
            WriteRegStr HKCU "${statekey}" "PathCreated" "0"
          ${EndIf}
          !insertmacro kbBroadcastEnvironment
        ${EndIf}
      ${EndIf}
    ${EndIf}
  ${ElseIf} $5 == "toolong"
    !insertmacro kbNotify "사용자 PATH가 너무 길어 고치지 않았다. 명령줄에서 쓰려면 ${dir}를 PATH에 직접 더한다"
  ${Else}
    !insertmacro kbNotify "사용자 PATH를 읽지 못해 고치지 않았다. 명령줄에서 쓰려면 ${dir}를 PATH에 직접 더한다"
  ${EndIf}
!macroend

; 제거: 이 설치가 더한 항목(${statekey}의 PathEntry)과 그때 붙인 구분자 하나만 뺀다
!macro kbRemoveFromUserPath statekey
  ClearErrors
  ReadRegStr $R0 HKCU "${statekey}" "PathEntry"
  ${IfNot} ${Errors}
  ${AndIf} $R0 != ""
    ReadRegStr $R1 HKCU "${statekey}" "PathCreated"
    !insertmacro kbReadUserPath
    ${If} $5 == "ok"
      !insertmacro kbFindPathToken $R0 0
      ${If} $1 >= 0
        StrLen $9 $0
        IntOp $4 $1 + $2
        ${If} $1 > 0
          ; 앞 구분자와 함께 뺀다 (더할 때 ";<bin>"을 붙였다)
          IntOp $7 $1 - 1
          ${If} $7 > 0
            StrCpy $3 $0 $7
          ${Else}
            StrCpy $3 ""
          ${EndIf}
          StrCpy $8 $0 "" $4
          StrCpy $0 "$3$8"
        ${ElseIf} $4 < $9
          ; 맨 앞 항목이면 뒤 구분자와 함께 뺀다
          IntOp $4 $4 + 1
          StrCpy $0 $0 "" $4
        ${Else}
          StrCpy $0 ""
        ${EndIf}
        ClearErrors
        ${If} $0 == ""
        ${AndIf} $R1 == "1"
          DeleteRegValue HKCU "${KB_ENV_KEY}" "Path"
        ${ElseIf} $6 == 1
          WriteRegStr HKCU "${KB_ENV_KEY}" "Path" $0
        ${Else}
          WriteRegExpandStr HKCU "${KB_ENV_KEY}" "Path" $0
        ${EndIf}
        ${If} ${Errors}
          !insertmacro kbNotify "사용자 PATH에서 $R0를 빼지 못했다. 직접 뺀다"
        ${Else}
          !insertmacro kbBroadcastEnvironment
        ${EndIf}
      ${EndIf}
    ${ElseIf} $5 != "absent"
      !insertmacro kbNotify "사용자 PATH를 읽지 못해 고치지 않았다. $R0가 남아 있으면 직접 뺀다"
    ${EndIf}
  ${EndIf}
!macroend
