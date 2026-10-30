# kookabug-platform

Kookabug의 Windows 플랫폼 구현: 창·프로세스·DPI, WGC 캡처, SendInput, 이미지 매칭, OCR.

런타임 의존성은 Windows에서만 설치된다 (`numpy`, `opencv-python`, `windows-capture`, `onnxruntime`,
`pyclipper`). `kookabug-core`는 이 패키지 없이도 돈다 — `platform.kind`가 `windows`일 때만 불러온다.
의존 방향은 한쪽이다: 이 패키지가 `kookabug-core`(오류 `EngineError`·실행 Job·프로세스 식별)를 쓴다.

| 모듈 | 내용 |
|---|---|
| `win32/` | ctypes 바인딩(DLL별)과 판정용 호출 묶음 `api.WindowApi`(검사에서 바꿔 끼움) |
| `errors.py` | 오류 코드와 `PlatformError` |
| `dpi.py` | Per-Monitor V2 확인, 스레드 단위 PMv2, 클라이언트 물리 픽셀 좌표 변환 |
| `windows.py` | 창 찾기·`WindowInfo`·포그라운드·점 아래 창·무결성·입력 데스크톱 판정, 활성화·크기 맞춤 |
| `tracker.py` | 창 수명 추적기(파괴 이벤트 스레드)와 바인딩 |
| `process.py` | 게임 띄우기(실행 Job 안)·닫기·Job 안 프로세스의 창 찾기 |

배포물에 들어가는 네이티브 파일(DLL·pyd)의 구성요소별 라이선스는 `tools/native-licenses.toml`이
단일 출처다.
