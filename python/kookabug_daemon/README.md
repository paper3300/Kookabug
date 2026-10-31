# kookabug-daemon

워크스페이스당 하나 도는 Kookabug daemon. 데스크톱 앱(UI)과 에이전트가 127.0.0.1 WebSocket +
JSON-RPC 2.0으로 붙는다. 메시지 형식의 단일 출처는 `packages/schema/daemon-rpc.schema.json`이다.

    kookabug daemon --workspace <루트> [--idle-timeout-s 600] [--json] [--log-level info]

- `.kookabug/daemon.lock`을 살아 있는 동안 쥐고, 접속 정보(포트·토큰)를 `.kookabug/session.json`에 쓴다
- 첫 메시지는 5초 안의 `session.hello {token, protocol, client}`다. 연결마다 주체 하나가 정해지고,
  권한 판정은 코어 `WorkspaceService.require`가 한다
- 그래프 문서는 경로당 하나다(연결과 무관). 저장은 원문을 보존하고, 값이 같으면 쓰지 않는다.
  워크스페이스 파일은 1초 폴링으로 보고 `workspace.changed`·`graph.changed`를 알린다
- daemon이 실행의 감독자다. 실행은 워크스페이스에서 한 번에 하나이고, 시작은 중복 방지 키 → 권한 →
  실행 중 확인 → 사전 검증 → 시작 순서를 한 잠금 안에서 한다. UI가 끊겨도 실행은 계속된다
- 실행 이벤트는 `events.jsonl`을 따라 읽어 `run.event`로 보낸다. 다시 붙으면 클라이언트가 적용한
  마지막 seq 다음부터 받는다(빈틈·중복 없음). 입력 임대권 소유자는 `lease.changed`로 알린다
- 연결도 진행 중인 실행도 없는 상태가 유휴 시간 동안 이어지면 스스로 끝난다

라이선스: Apache-2.0
