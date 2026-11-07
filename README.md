# Kookabug

**게임 QA 자동화를 노드로 그리는 오픈소스 데스크톱 툴**입니다. 게임 코드를 고치지 않고, 화면을 보고 누르는 방식으로 테스트를 만들고 실행합니다.

Windows · Apache-2.0 · 개발 중 (아직 공개 배포판은 없습니다)

MVP 기능(M0~M7)은 자동 검사까지 갖췄고, 사람 확인을 한 번에 하는 단계입니다([Docs/verification/mvp-human-check.md](Docs/verification/mvp-human-check.md)). 마지막 M7 화면 지도에서는 AI 에이전트가 MCP 도구로 게임을 둘러보며 화면과 이동을 `screens/_explored/`에 남기고, 사람이 화면 지도에서 확인해 `screens/`로 옮깁니다. 탐색 중 게임 클릭은 사람 승인("이 탐색 동안 허용")을 거치고, 비밀값을 입력한 창이나 민감한 화면의 이미지는 에이전트에게 보내지 않습니다.

- 소개·기능·로드맵: [Docs/intro/README.md](Docs/intro/README.md)
- 기여: 구현 PR은 허용한 기여자만 받고, 버그는 재현 절차를 담은 이슈로 받습니다 → [CONTRIBUTING.md](CONTRIBUTING.md)
- 라이선스: [Apache-2.0](LICENSE)
