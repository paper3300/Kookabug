# kookabug-mcp

에이전트 CLI가 Kookabug 워크스페이스를 다루게 하는 MCP 서버. 에이전트 설정에 stdio 서버로 등록한다.

    kookabug mcp [--workspace <루트>] [--agent-id <id>] [--unattended] [--client <이름>]

- 얇은 shim이다. 권한 판정·상태는 전부 워크스페이스 daemon에 있다. shim은 daemon에 agent 연결로
  붙고(없으면 띄운다), MCP 도구 호출을 daemon 메서드로 옮기고, 결과를 MCP 내용으로 바꾼다
- stdout은 MCP 프로토콜 전용(줄 하나 = JSON-RPC 메시지 하나), 로그는 stderr
- 처음에는 `core` 툴셋만 켜져 있다. `kb_toolset_enable`로 `graph_edit`·`run`·`observe`·`control`·
  `screens`를 켠다. 켜도 도구마다의 권한(`kookabug.json`·`.kookabug/local.json`·사용자 설정)은 그대로다
- 기본은 사람이 지켜보는 연결(attended)이다. CI·야간처럼 사람이 없으면 `--unattended` — 확인이
  필요한 도구는 거부된다
- 권한·도구 거부는 JSON-RPC 오류가 아니라 `isError: true` 결과(`"<코드>: <메시지>"`)로 답한다
