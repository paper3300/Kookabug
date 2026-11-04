"""녹화의 사람 입력 잡기 (M4 계획 2.1): 저수준 훅 프로세스와 그 순수 해석·가짜 원천.

- `parse`: 훅 구조체 → 훅 이벤트 (순수)
- `hookproc`: 녹화 전용 자식 프로세스 (`python -m kookabug_platform.recorder.hookproc`) — 훅 콜백의
  상태(`HookCore`)와 진입점. ctypes·표준 라이브러리만 import한다
- `hookwin32`: 훅 스레드·관측 스레드·IME 표본 스레드·송신의 Win32 부분
- `fake`: 가짜 각본(JSONL)을 시각대로 흘리는 `FakeHookSource` (daemon 녹화 검사·E2E)
"""
