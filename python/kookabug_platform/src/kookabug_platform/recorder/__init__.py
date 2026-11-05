"""녹화의 사람 입력 잡기 (M4 계획 2.1): 저수준 훅 프로세스와 그 순수 해석·가짜 원천.

- `parse`: 훅 구조체 → 훅 이벤트 (순수)
- `hookproc`: 녹화 전용 자식 프로세스 (`python -m kookabug_platform.recorder.hookproc`) — 훅 콜백의
  상태(`HookCore`)와 진입점. ctypes·표준 라이브러리만 import한다
- `hookwin32`: 훅 스레드·관측 스레드·IME 표본 스레드·송신의 Win32 부분
- `fake`: 가짜 각본(JSONL)을 시각대로 흘리는 `FakeHookSource` (daemon 녹화 검사·E2E)
- `frames`·`geometry`: 캡처 링·클릭 이전 프레임 고르기·기하 세대 시간표 (M4 2.5, numpy를 쓴다 —
  훅 프로세스는 import하지 않는다)
- `scripted_frames`: 각본대로 테두리 있는 버퍼·기하를 내는 가짜 프레임 원천
"""
