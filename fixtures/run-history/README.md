# 예전 실행 기록 (M3 전)

M3 계약(디버거·영상·증거 필드)을 넣기 **전** 코드로 만든 실행 기록이다. 폴더마다 실행 폴더의 `events.jsonl`과 `run.json`만 그대로 옮겼다(스냅샷·스크린샷·로그는 뺐다). M3에서 더한 필드는 모두 선택이므로 이 기록이 새 메타스키마로 그대로 통과해야 한다(`python/kookabug_core/tests/schema/test_m3_contracts.py`). 고치지 않는다.

| 폴더 | 만든 방법 | 들어 있는 것 |
|---|---|---|
| `m0b-pause-resume` | runner 검사 `test_pause.py::test_resume_continues` | M0b 경계 멈춤 `debug.pause`·`debug.resume`(필드는 `step`만), 워커 시작·종료 |
| `m0b-pause-cancel` | `test_pause.py::test_cancel_while_paused` | 멈춘 채 취소 (`cancel.requested`, `run.end.cancel_reason`) |
| `m0b-runner-died-key-down` | `test_runner_death.py::test_runner_killed_with_key_down_supervisor_releases` | runner 사망 뒤 감독자 마무리 (`input.down`·`input.recovered`, `runner_died`, `run_json_repaired`) |
| `m0b-runner-died-truncated` | `test_runner_death.py::test_runner_killed_mid_line_truncated_then_finalized` | 잘린 끝 줄을 잘라 낸 감독자 마무리 (`truncated_bytes`) |
| `m2-inventory-pass` | 예제 워크스페이스 `kookabug run tests/inventory_open.graph.json --platform-fake fake-platform.json` | 서브그래프 호출·대기·입력·검증 통과 |
| `m2-login-fail` | 같은 명령 `--profile login_fail` | 서브그래프 fail 출구, 호출 스텝의 실패 증거(`_fail.png`), OCR 글자(`_ocr.txt`) |
| `m2-maintenance-skip` | 같은 명령 `--profile maintenance` | `test.skip` 판정 |
| `m2-swapped-target-timeout` | `kookabug run tests/broken/swapped_target.graph.json --platform-fake fake-platform.json` | 대기 시간 초과 fail (노드 artifact `_timeout.png`와 실패 증거) |

예제 워크스페이스 실행은 `.kookabug/local.json`에 가짜 `game.cwd`·`game.executable`(`C:/game`)을 넣고 비밀번호 환경 변수를 준 복사본에서 돌렸다(가짜 플랫폼이라 게임을 띄우지 않는다).
