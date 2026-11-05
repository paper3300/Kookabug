; installer.nsh가 기본 스크립트의 설치 범위 화면 매크로(PAGE_INSTALL_MODE) 대신 넣는다: 페이지를 만들지 않는다.
; 머리 파일이 KB_PAGE_MARKER를 정하면 펼쳐질 때마다(설치·제거 프로그램 컴파일 각각) 그 파일에 한 줄을 남긴다.
; tools/installer/build.py가 빌드 뒤 두 줄이 다 있는지 본다 (기본 스크립트가 바뀌어 이 매크로를 안 거치면 빌드 실패)
; 이 파일은 UTF-8이다
!macro PAGE_INSTALL_MODE
  !ifdef KB_PAGE_MARKER
    !ifdef BUILD_UNINSTALLER
      !appendfile "${KB_PAGE_MARKER}" "uninstaller: no install mode page$\n"
    !else
      !appendfile "${KB_PAGE_MARKER}" "installer: no install mode page$\n"
    !endif
  !endif
!macroend
