"""`kookabug agent-job` — 외부 Agent CLI 무인 감독 (M8 계획 3.9·3.11, 9장 R8·R9).

- `jobdir`: `.kookabug/jobs/<작업>/` 폴더·`job.json`·`jobs.lock`(워크스페이스당 작업 하나)
- `profiles`: 외부 CLI 명령줄(claude·codex·custom)·자식 환경 허용 목록·`mcp.json`·프롬프트
- `runner`: 감독 본체(준비 → 띄우기 → 예산·취소·유실 → 끝)와 `agent.log` 가림
- `report`: 작업 기록에서 보고(`kookabug.report/0`) 만들기·묶기·렌더·결정
- `schedule`: Windows 작업 스케줄러 XML·`schtasks` 명령
"""

SECURITY_NOTE = (
    "Kookabug는 Kookabug 도구(MCP·KOOKABUG_AGENT CLI·agent-job) 안에서만 막습니다. "
    "Agent CLI가 자기 셸·파일 도구를 쓰면 막을 수 없습니다. "
    "무인 실행은 Agent CLI 자체 권한 설정으로 셸·파일 쓰기를 끄세요."
)
"""보안 경계 문구 (3.15, 한 곳에서 쓴다)."""
