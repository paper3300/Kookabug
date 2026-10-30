# kookabug-platform

Kookabug의 Windows 플랫폼 구현: 창·프로세스·DPI, WGC 캡처, SendInput, 이미지 매칭, OCR.

런타임 의존성은 Windows에서만 설치된다 (`numpy`, `opencv-python`, `windows-capture`, `onnxruntime`,
`pyclipper`). `kookabug-core`는 이 패키지 없이도 돈다 — `platform.kind`가 `windows`일 때만 불러온다.

배포물에 들어가는 네이티브 파일(DLL·pyd)의 구성요소별 라이선스는 `tools/native-licenses.toml`이
단일 출처다.
