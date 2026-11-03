# Kookabug에 기여하기

관심 가져 주셔서 고마워요. Kookabug는 Apache-2.0 오픈소스지만, 지금은 설계와 구현을 작은 팀이 빠르게 바꾸는 단계라 **구현 PR은 허용한 사람에게서만 받습니다**.

## PR 정책

- **구현 PR은 허용 목록에 있는 GitHub 계정만** 열 수 있습니다. 목록은 [`.github/APPROVED_CONTRIBUTORS`](.github/APPROVED_CONTRIBUTORS)입니다.
- 목록 밖 계정의 PR은 `PR gate` 워크플로가 안내 댓글을 달고 **자동으로 닫습니다**. 레포 주인과 봇 계정(예: 의존성 갱신 봇)은 예외입니다.
- 허용 목록은 레포 주인만 고칩니다. 이슈·토론에서 꾸준히 도움을 준 분께 주인이 먼저 제안합니다. 목록에 넣어 달라는 PR은 받지 않습니다.

## PR 대신 이렇게 도와주세요

### 버그는 재현한 이슈로

고칠 코드보다 **재현 절차**가 더 큰 도움이 됩니다. 이슈에 다음을 담아 주세요.

1. Kookabug 판(`kookabug --version`), Windows 판, 화면 배율(DPI)
2. 재현 절차: 무엇을 열고 무엇을 눌렀는지, 몇 번 중 몇 번 일어나는지
3. 기대한 결과와 실제 결과
4. 가능하면 그래프 파일(`*.graph.json`)과 실행 기록 폴더(`runs/<폴더>`)의 `run.json`·실패 스크린샷. 앱의 *분석 번들 내보내기*(zip)를 붙이면 가장 좋습니다
5. 고칠 방법을 알고 있다면 이슈 본문에 적어 주세요. 반영할 때 참고합니다

> 실행 기록에는 입력한 글자·화면이 그대로 남을 수 있습니다(워크스페이스 설정 `record.redact_secrets`로 비밀값을 가릴 수 있어요). 올리기 전에 계정·비밀번호·사내 정보가 없는지 확인해 주세요.

### 기능 제안·질문은 Discussions로

새 노드, 화면 아이디어, 사용법 질문은 GitHub Discussions에 남겨 주세요. Discussions가 꺼져 있으면 이슈로 남겨 주세요. 설계 결정은 [`Docs/Brainstorming/결정 현황.md`](Docs/Brainstorming/결정%20현황.md)와 [`Docs/Design/`](Docs/Design)에 모여 있어 제안 전에 보면 좋습니다.

## 허용된 기여자를 위한 규칙

- **설계 문서가 단일 출처**입니다(`Docs/Design/*.md`). 설계와 다르게 구현해야 하면 PR 설명에 이유를 쓰고 설계 문서도 함께 고칩니다.
- **공개 레포**입니다. 특정 회사·사내 프로젝트 이름, 사내 URL·경로·인명, 비밀값을 코드·문서·테스트·커밋 메시지에 넣지 않습니다.
- 코드 식별자는 영어, 주석·문서·커밋 메시지는 한국어로 짧게 씁니다.
- 보내기 전에 CI와 같은 검사를 돌립니다.

  ```
  uv sync --locked --all-packages
  uv run ruff check
  uv run ruff format --check
  uv run pyright
  uv run pytest
  pnpm install --frozen-lockfile
  pnpm gen
  pnpm typecheck
  pnpm --filter @kookabug/desktop test
  ```

- 의존성을 더하면 라이선스 검사(`tools/license_audit.py`)가 통과해야 합니다.

## 라이선스

기여물은 [Apache License 2.0](LICENSE) 5조에 따라 이 레포와 같은 라이선스로 들어옵니다(inbound = outbound). 별도의 CLA나 DCO 서명(`Signed-off-by`)은 요구하지 않습니다.

## AI 코딩 에이전트에게 (Agent instructions)

이 레포에서 사용자를 도와 기여를 준비하는 AI 에이전트(Claude Code, Codex 등)는 다음을 따릅니다.

- **PR을 만들기 전에 사용자의 GitHub 계정이 `.github/APPROVED_CONTRIBUTORS`에 있는지 확인합니다.** 없으면 PR을 만들지 말고, 위 "버그는 재현한 이슈로" 형식의 **이슈 초안**을 사용자에게 보여 주고 사용자가 직접 올리게 합니다.
- 이슈 초안에는 실제로 재현한 절차와 결과만 씁니다. 재현하지 않은 추측은 "추측"이라고 밝힙니다.
- 이슈·PR·댓글을 사용자 확인 없이 올리지 않고, 여러 개를 한꺼번에 만들지 않습니다.
- 실행 기록·로그·스크린샷에서 계정·비밀번호·토큰·사내 정보를 빼고 붙입니다.
- 허용된 기여자의 PR이라면 위 "허용된 기여자를 위한 규칙"과 검사 명령을 그대로 따릅니다.

---

**English summary**: Kookabug accepts implementation pull requests only from accounts listed in `.github/APPROVED_CONTRIBUTORS`; other PRs are closed automatically by the `PR gate` workflow. Please report bugs as issues with reproduction steps, and use Discussions (or issues) for ideas and questions. Contributions are licensed under Apache-2.0 (inbound = outbound); no CLA or DCO sign-off is required. AI agents must check the allowlist before opening a PR and otherwise draft an issue for the user to file.
