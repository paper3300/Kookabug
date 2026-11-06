# 에이전트 안내

예제 게임 SampleRPG의 Kookabug 워크스페이스다. 아래 표시 밖은 사람이 자유롭게 고친다.

<!-- kookabug:begin -->
## Kookabug 워크스페이스 규칙 (자동 관리 구간 — 이 표시 사이는 Kookabug가 다시 쓴다)

- 폴더: `tests/` 테스트 그래프, `subgraphs/` 서브그래프, `targets/` 찾기 대상(`*.target.json` +
  PNG), `screens/` 화면 지도, `runs/` 실행 기록(읽기 전용), `.kookabug/` 개인 설정·캐시(Git 제외)
- 파일 형식은 Kookabug 저장소의 `Docs/Design/그래프 JSON 스키마 v0.md`·`워크스페이스 구조.md`
- 그래프는 Kookabug MCP 도구(`kb_graph_create`·`kb_graph_patch`)로 고친다. 노드 ID를 바꾸지 않는다
- 도구는 `kb_toolset_enable`로 툴셋(graph_edit·run·observe·control·screens)을 켠 뒤 쓴다
- 실패 분석은 `kb_run_status`(실패 요약)·`kb_run_events`부터 본다. 그다음 `kb_run_artifact_get`
  (스크린샷)·`kb_run_compare`(지난 성공과 비교)
- 비밀값(비밀번호·토큰)을 파일·그래프에 쓰지 않는다. 그래프에서는 `{"$secret": "키"}`로 가리킨다
<!-- kookabug:end -->
