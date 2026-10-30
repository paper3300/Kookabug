"""Win32 ctypes 바인딩 (user32·dwmapi·kernel32·advapi32·wtsapi32·shcore·ole32). pywin32를 쓰지
않는다.

DLL마다 모듈 하나에 함수 서명과 상수만 둔다. 판정 코드는 이것을 직접 부르지 않고 `api.Win32Api`를
거친다 — 검사에서 바꿔 끼울 수 있게(`api.WindowApi` 프로토콜). 창 DPI는 `GetDpiForWindow`(user32,
DPI를 모르는 창은 늘 96), 모니터의 실제 배율은 `GetDpiForMonitor`(shcore)로 읽는다.
"""
