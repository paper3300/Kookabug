# Kookabug

**게임 QA 자동화를 노드로 그리는 오픈소스 데스크톱 툴**입니다. 게임 코드를 고치지 않고, 화면을 보고 누르는 방식으로 테스트를 만들고 실행합니다.

Windows · Apache-2.0 · 개발 중 (아직 공개 배포판은 없습니다)

MVP 기능(M0~M7)은 자동 검사까지 갖췄고, 사람 확인을 한 번에 하는 단계입니다([Docs/verification/mvp-human-check.md](Docs/verification/mvp-human-check.md)). 마지막 M7 화면 지도에서는 AI 에이전트가 MCP 도구로 게임을 둘러보며 화면과 이동을 `screens/_explored/`에 남기고, 사람이 화면 지도에서 확인해 `screens/`로 옮깁니다. 탐색 중 게임 클릭은 사람 승인("이 탐색 동안 허용")을 거치고, 비밀값을 입력한 창이나 민감한 화면의 이미지는 에이전트에게 보내지 않습니다.

M8 자기 진화 QA v1은 프로젝트 지식(기능별 주장·사건·증거 묶음·치트·미지수)을 워크스페이스 `knowledge/`·`wiki/`에 쌓고, `kookabug agent-job`이 Claude Code·Codex 같은 외부 Agent CLI를 무인으로 감독해 조사·수리·Init을 맡깁니다. 판정을 지키는 것은 Kookabug 도구입니다: UI가 바뀌어 버튼 위치만 달라진 경우는 정해진 조건을 모두 통과해야 자동으로 고치고(되돌리기 한 번), 버튼이 사라진 것 같은 버그를 Agent가 테스트를 고쳐 덮으려 해도 막고 보고함에 회귀 의심으로 올립니다. 첫 프로젝트 설정 마법사가 게임·Agent·원본·자동화 정책을 정하고 Init까지 이어 줍니다. 사람 확인 절차는 [Docs/verification/m8-manual.md](Docs/verification/m8-manual.md)입니다.

- 소개·기능·로드맵: [Docs/intro/README.md](Docs/intro/README.md)
- 기여: 구현 PR은 허용한 기여자만 받고, 버그는 재현 절차를 담은 이슈로 받습니다 → [CONTRIBUTING.md](CONTRIBUTING.md)
- 라이선스: [Apache-2.0](LICENSE)
