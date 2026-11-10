# M8 사람 확인 결과

> 이 양식을 레포 밖(`.orchestration/M8/manual_result.md`)으로 복사해 채운다. 절차는 `m8-manual.md`(순서는 `mvp-human-check.md`). 통과 칸은 O / X / -(못 함, 사유를 결과 칸에). U절은 "그대로" / "바꿈"을 적는다.

- 확인한 사람:
- 날짜:
- 레포 커밋(`git rev-parse --short HEAD`):
- Agent CLI·판 (claude / codex):

## 결과

| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |
|---|---|---|---|---|
| D1 | 전체 자동 검사 + 전체 E2E + 샷 | pytest: · E2E: | `d1_full.log`, `d1_e2e.log` | |
| D2 | 설치본 스모크 QA 단계 (`cli.qa`) | 플레이북: / workspace new: / 다시 만들기: | `d2_smoke.json` | |
| H1 | 실제 Agent CLI 정상 수리 (claude·codex) | 상태: / 항목: / 채택 실패 조건: | — | |
| H2 | 실제 Agent CLI 버그 은폐 방지 (claude·codex) | 팀 파일 동일: / 채택 0: / 시도와 오류 코드: | — | |
| H3 | 실제 Agent CLI Init | 질문 수: / 답하기: / 위키 쪽: | — | |
| H4 | `agent-job probe` 플래그 실측 | claude 판·결과: / codex 판·결과: | — | |
| H5 | 실제 `schtasks` 예약 등록·해제·dry-run 비교 | XML 같음: / 회차 보고: / 제거: | `h5_dry.json` | |
| H6 | 마법사 0→9 실제 화면·팀원 짧은 마법사 | 시안 차이: / 짧은 마법사 단계: | — | |
| H7 | 보고함 되돌리기·수락·거절 | 되돌리기: / 수락: / 거절: | — | |

## 사용자 결정 (U)

| ID | 그대로 / 바꿈 | 바꾼다면 어떻게 |
|---|---|---|
| U1 | | |
| U2 | | |
| U3 | | |
| U4 | | |
| U5 | | |
| U6 | | |
| U7 | | |
| U8 | | |
| U9 | | |
| U10 | | |
| U11 | | |
| U12 | | |
| U13 | | |
| U14 | | |
| U15 | | |

## 별도 결정·고칠 것

| 항목 | 내용 | 다음 작업 |
|---|---|---|
| | | |
