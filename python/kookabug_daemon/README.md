# kookabug-daemon

워크스페이스당 하나 도는 Kookabug daemon. 데스크톱 앱(UI)과 에이전트가 127.0.0.1 WebSocket +
JSON-RPC 2.0으로 붙는다. 메시지 형식의 단일 출처는 `packages/schema/daemon-rpc.schema.json`이다.

    kookabug daemon --workspace <루트> [--idle-timeout-s 600] [--json] [--log-level info]

- `.kookabug/daemon.lock`을 살아 있는 동안 쥐고, 접속 정보(포트·토큰)를 `.kookabug/session.json`에 쓴다
- 첫 메시지는 5초 안의 `session.hello {token, protocol, client}`다. 연결마다 주체 하나가 정해지고,
  권한 판정은 코어 `WorkspaceService.require`가 한다
- 연결도 진행 중인 실행도 없는 상태가 유휴 시간 동안 이어지면 스스로 끝난다

라이선스: Apache-2.0
