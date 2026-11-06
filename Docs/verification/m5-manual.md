# M5 사람 확인 절차서

M5(Agent) 완료도 두 단계다 ([[구현 계획 v0]] 1장 M5 행).

1. **자동 완료**: CI 자동 검사(가짜 MCP 클라이언트·가짜 ACP 에이전트 `tools/kb_testing/fake_acp_agent.py`·가짜 모델 API `tools/kb_testing/fake_model_api.py`), 인수 테스트(`python/kookabug_core/tests/acceptance/test_m5.py`, `apps/desktop/e2e/acceptance.m5.spec.ts`), 잠금 해제 개발자 PC의 MCP 게임 조작 검사(`desktop_input`, D1), 시안 비교 PNG, 설치본 스모크의 MCP 단계(`cli.mcp`), 이 절차서·결과 양식
2. **최종 완료**: 이 절차서의 결과가 결과 양식(`m5-result-template.md`)에 기록되고 모든 항목이 통과 기준을 만족

> **사람 확인은 M7 끝에 몰아서 한다** (2026-11-05 사용자 결정, 속도 우선). 그 전까지 M5는 "자동 완료"로만 센다. 실제 에이전트 CLI·실제 모델 API는 CI에서 부르지 않는다 — 실제 서비스와 맞는지는 여기서만 본다.

| 절 | 내용 | 누가 | 시간 |
|---|---|---|---|
| D1 | 실제 게임 창 MCP 클릭 (`desktop_input`) | 조율자 (실제 입력 실행) | 5분 |
| D2·D3 | 전체 자동 검사·E2E, 시안 비교 PNG | 조율자 | 약 1시간 (기다림) |
| H1~H7 | 실제 에이전트 CLI·실제 키·조작감·시안 대비 | 사람 | 약 1시간 30분 |
| U1~U11 | 기본값으로 진행한 사용자 결정 | 사람 | 15분 |

결과 `manual_result.md`와 증거 폴더는 레포 밖 `.orchestration/M5/`(git 제외)에 둔다.

## 0. 준비

[[m4-manual]] 0절의 준비를 `M4` → `M5`로 바꿔 쓴다(`$ev = "$repo\.orchestration\M5\manual_evidence"`, 결과 양식 `m5-result-template.md` 복사, 예제 워크스페이스 사본 `%TEMP%\kb-m5\sample-rpg`, 개발 빌드 앱 띄우기).

- 실제 에이전트 CLI를 미리 설치·로그인해 둔다. Kookabug는 설치하지 않고 PATH에서 찾기만 한다. 감지 표(`kookabug_core/agents/detect.py`)의 명령 후보: `claude-code-acp`(Claude Code ACP 어댑터), `codex-acp`(Codex CLI ACP 어댑터), `gemini --experimental-acp`(Gemini CLI). 이름이 바뀌었으면 결과 양식 "별도 결정"에 적는다
- 실제 모델 API 키 하나(Anthropic 또는 OpenAI 호환). 자격 증명 관리자나 환경 변수 `KOOKABUG_SECRET_<키>`로만 넣는다 — 파일에 쓰지 않는다

## 1. 조율자 자동 검사 (D)

### D1 실제 게임 창 MCP 클릭 (실제 입력)

실제 예제 게임 창을 `kookabug mcp` → `control.click` → 제어 실행(runner·SendInput)으로 누른다. 다른 데스크톱 검사와 동시에 돌리지 않는다(입력 임대권).

```powershell
$env:KOOKABUG_DESKTOP_TESTS = "require"; $env:KOOKABUG_DESKTOP_INPUT = "1"; $env:KOOKABUG_TEST_DISPLAY = "left"
uv run pytest -p no:cacheprovider python/kookabug_mcp/tests/test_control_live.py 2>&1 | Tee-Object "$ev\d1_control_live.log"
Remove-Item Env:KOOKABUG_DESKTOP_TESTS, Env:KOOKABUG_DESKTOP_INPUT
```

- 기대 결과: 실패 0, 건너뜀 0. 게임이 타이틀에서 로그인 화면으로 넘어간다

### D2 전체 자동 검사

[[m4-manual]] D2와 같은 명령(`require`·`INPUT`·`SOAK`·`MEDIA` + 전체 E2E). 인수 `test_m5.py`·`acceptance.m5.spec.ts`가 포함된다. 증거 `d2_full.log`, `d2_e2e.log`.

### D3 시안 비교 PNG

```powershell
node tools/design-ref/render.mjs; node tools/design-ref/extract.mjs
pnpm --filter @kookabug/desktop shots
node tools/design-ref/compare.mjs panel-empty panel-chat panel-approval panel-acp-permission agent-judge runviewer-analyze
New-Item -ItemType Directory -Force "$ev\ui-compare" | Out-Null
Copy-Item build\ui-compare\panel-*.png, build\ui-compare\agent-judge*.png, build\ui-compare\runviewer-analyze*.png, build\ui-shots\permissions-*.png "$ev\ui-compare\"
(Get-ChildItem "$ev\ui-compare\*.png").Count
```

- 기대 결과: `shots` 실패 0, 마지막 줄 `8`(비교 6장 — 패널 연결 화면·대화·승인 카드·ACP 권한 카드, 판단 노드, RUN 탭 분석 단추 — 다크, 그리고 권한 설정 앱 화면 다크·라이트). 권한 설정은 렌더러가 시안 `Permissions.dc.html`을 아직 못 그려 비교 PNG 없이 시안 원본과 나란히 본다. H7의 재료

## 2. 실제 에이전트 (H)

### H1 실제 에이전트 CLI 2종 이상을 패널로 연결

1. 오른쪽 패널 "에이전트" 탭 → 빈 화면에 감지 목록. 설치한 것은 "연결"이 보인다
2. 하나는 감지 목록에서, 하나는 "직접 입력"(이름·명령줄)으로 연결한다. npm `.cmd` 런처도 뜨는지(패널은 `kookabug agent-host` 도우미로 띄운다)
3. 바닥 줄 "<에이전트> · ACP · 권한: <프리셋> · MCP 툴셋 1", 상태 바 "에이전트 1"
4. 앱을 닫으면 에이전트·`kookabug mcp` 프로세스가 남지 않는다(작업 관리자)

- 기대 결과: 2종 모두 `ready`. 실패하면 받은 오류 줄과 그 에이전트의 `session/new`가 `mcpServers`를 받는지 적는다

### H2 실제 에이전트가 MCP로 만들고 실행하고 실패 분석

프리셋 `runner`(그래프 편집 = 확인, 실행 = 허용)에서 패널에 "예제 게임 로그인 뒤 인벤토리를 여는 테스트를 만들어 돌리고, 실패하면 원인을 알려 줘", 이어서 "`tests/broken/swapped_target.graph.json`을 돌리고 왜 실패했는지 설명해 줘".

- 기대 결과: 에이전트가 `kb_toolset_enable`로 툴셋을 켜고 `kb_graph_create`/`kb_graph_patch`(승인 카드) → `kb_run_start` → `kb_run_status` → `kb_run_events`·`kb_run_artifact_get`·`kb_run_compare`로 실패 위치("월드 접속 > 타이틀 대기")를 말한다. 비밀번호 원문(`sample-pass-01`)이 대화·도구 결과 어디에도 없다
- 도구 결과가 `tool_call_update.content`로 오는지(오지 않으면 H5의 임대권 띠가 안 뜬다), `list_changed`를 받는지(못 받으면 켠 뒤 도구가 안 보임) 적는다

### H3 승인 카드 조작감

"한 번 허용"·"항상 허용"(카드의 규칙 글자 → `.kookabug/local.json`에 그 한 줄)·"캔버스에서 보기"(읽기 전용 미리보기 탭)·"거부"를 한 번씩. 카드를 120초 그대로 두면 거부로 닫힌다.

- 기대 결과: 거부·시간 초과에 파일이 그대로. **에이전트 쪽 도구 호출 기한이 120초보다 짧은지** 적는다(짧으면 기본 대기를 줄이는 결정 필요)

### H4 외부 터미널 에이전트

에이전트 CLI의 MCP 설정에 `kookabug mcp --workspace <사본>`을 등록하고 터미널에서 H2와 같은 요청.

- 앱이 열려 있으면 승인 카드가 패널 맨 위 "외부 에이전트"로 뜬다
- 앱을 닫고 같은 그래프 편집을 시키면 `approval_required: no_approver`(앱을 대신 띄우지 않음)
- `--unattended`로 등록하면 확인이 필요한 도구가 `permission_denied`(`unattended_ask`)

### H5 실제 게임 창 MCP 조작

프리셋 `full`(또는 게임 조작 허용)에서 패널 에이전트에게 "SampleRPG 창의 시작 단추를 눌러 줘".

- 기대 결과: 게임이 넘어가고 기록 목록에 "에이전트 제어" 배지 실행이 생긴다
- 같은 앱에서 실행(F5) 중에 다시 시키면 `run_busy`, 녹화 중이면 `recording_active`로 거부된다(도구 결과 글자로 확인, 띠는 뜨지 않는다)
- 임대권 띠: 다른 워크스페이스 사본을 다른 앱 창(다른 daemon)으로 열어 F5로 돌리는 동안 이 패널 에이전트에게 다시 시키면 `input_lease_busy`로 거부되고 패널에 "에이전트의 게임 조작을 막았어요" 띠

### H6 판단 노드 실제 에이전트·실제 키

`core.agent.cli_judge`(H1에서 연결한 에이전트)와 `core.agent.api_judge`(실제 키 `$secret`) 노드를 예제 게임 화면 캡처 뒤에 하나씩 놓고 선택지 `title`·`loading`으로 F5.

- 기대 결과: 둘 다 선택지 출구로 이어진다. cli는 `promptCapabilities.image`가 없으면 `agent_protocol_error`, 첫 실행(패키지 내려받기)이 기본 60초를 넘으면 `agent_timeout` — 그 경우를 적는다. `steps/<스텝>_judge.json`에 키 원문이 없다

### H7 화면 시안 대비

D3 PNG와 실제 앱으로 패널(대화·카드·빈 화면·바닥 줄)·권한 설정(사용자·프로젝트·팀 잠김, 프리셋, 툴셋 6줄, 세부 규칙)·RUN 탭 "에이전트에게 분석 요청"을 시안 `Main.dc.html`·`Permissions.dc.html`·`Setup5Agent.dc.html`과 다크·라이트로 비교한다. 의도된 차이는 [[UX 시안 v0.1]] "M5 구현" 표.

## 3. 기본값으로 진행한 사용자 결정 (U)

M5 계획 7장. 그대로 둘지 바꿀지 적는다.

| ID | 기본값 |
|---|---|
| U1 | 에이전트에게 주는 실행 기록은 실행 때 분류로 비밀값을 가림(필드 `***`, 비밀 스텝 화면·글자 안 줌, 분류 없는 옛 기록은 판정·노드·오류 코드·시각만). 사람이 보는 기록은 그대로 |
| U2 | 게임 직접 조작은 프리셋 표대로(`full`·명시 allow면 묻지 않음), 게임 조작 카드에 "항상 허용" 없음 |
| U3 | 승인 대기 120초 뒤 거부, 앱이 안 열려 있으면 기다리지 않고 "승인할 사람 없음" |
| U4 | 에이전트의 게임 조작은 실행 기록에 "에이전트 제어" 배지로 남김 |
| U5 | 툴셋 표시 이름: 기본·그래프 편집·실행·화면 보기·게임 조작·화면 지도 |
| U6 | 상태 바 "MCP :7317" 대신 "에이전트 N" |
| U7 | 첫 실행 마법사 5단계 대신 패널 빈 화면에서 연결(감지·직접 입력·프리셋) |
| U8 | API 판단 노드 공급자 Anthropic·OpenAI 호환 두 가지, 키는 비밀값 |
| U9 | 선택지 밖·읽을 수 없는 답 = `unsure`, 시간 초과(60초)·시작 실패 = `error` |
| U10 | "캔버스에서 보기" = 읽기 전용 미리보기 탭 |
| U11 | 판단 노드 에이전트는 패널과 같은 목록에서 고르되 매번 따로·도구 없이. 다른 PC는 같은 ID가 사용자 설정에 있어야 함 |
