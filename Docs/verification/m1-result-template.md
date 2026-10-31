# M1 사람 검증 결과

> 이 양식을 레포 밖(`.orchestration/M1/manual_result.md`)으로 복사해 채운다. 절차는 `m1-manual.md`. 증거 경로는 증거 폴더(`manual_evidence/`) 기준 상대 경로로 적는다. 통과 칸은 O / X / -(해당 없음, 사유를 내용 칸에).

- 검증한 사람:
- 날짜:
- 레포 커밋(`git rev-parse --short HEAD`):
- 설치 파일 버전·이름:

## 기준 PC (G0)

| 항목 | 값 |
|---|---|
| CPU (이름·코어·논리 프로세서) | |
| RAM | |
| GPU·드라이버 | |
| 모니터 해상도 | |
| Windows 판 | |
| 입력 언어 | |

## 결과

| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |
|---|---|---|---|---|
| D1 | 데스크톱 탐지 4개 통과 | | `d1_probe.txt` | |
| D2 | M1 인수 테스트 (데스크톱 포함) 실패·건너뜀 0 | 통과 / 실패 / 건너뜀 / 시간: | `d2_acceptance.log` | |
| D3 | 캡처·장시간 안정성 | 통과 수: / 핸들·스레드·개인 바이트 증가: | `d3_capture.log` | |
| D4 | 실제 입력·강제 종료 키 해제 | 통과 수: | `d4_input.log` | |
| D5 | 노드·예제 워크스페이스 실기 | 통과 수: | `d5_nodes.log` | |
| D6 | 전체 자동 검사 (require·INPUT·SOAK) | 통과 / 실패 / 건너뜀 / 시간: | `d6_full.log` | |
| D7 | DPI 150%·200% 자동 검사 | 150%: 통과 / 실패, 200%: 통과 / 실패, 실제 배율: | `d7_dpi150.log`, `d7_dpi200.log` | |
| S1 | Windows Sandbox 켜기 | 환경(Sandbox / VM): | — | |
| S2 | 설치 파일 준비 | 이름·크기(바이트): | — | |
| S3 | 설치: UAC 없음, Python 없음, `--version` | UAC: / `where.exe python`: / 버전: / Windows 판: | `sandbox/s3_*.txt` | |
| S4 | `doctor --json` (desktop) `ok: true` | 종료 코드: / 실패 항목·detail: | `sandbox/doctor.json` | |
| S5 | 예제 게임 실제 실행 (캡처·OCR·입력) | 종료 코드: / 판정: / 시간: | `sandbox/s5_runs/` | |
| S6 | 제거: 폴더·PATH·명령 없음 | 폴더: / PATH: / 명령: | `sandbox/s6_uninstall.txt` | |
| G0 | 대상·장면 | 게임·판: / 기준 화면·버튼·확인 글자·돌아가기 키: / 입력 칸(보완 대상): / 100% 클라이언트 크기: | `g0_pc.txt` | |
| G1 | DPI 100% `dpi_check` pass | verdict·code: | `g1_dpi100/` | |
| G2 | DPI 150% `dpi_check` pass (100% target 그대로) | 배율: / verdict·code: / 클라이언트 크기: | `g2_dpi150/`, `g2_capture150/` | |
| G3 | DPI 200% `dpi_check` pass (100% target 그대로) | 배율: / verdict·code: / 클라이언트 크기: | `g3_dpi200/`, `g3_capture200/` | |
| G4 | 창 이동 뒤 클릭 정확 | verdict·code: | `g4_move/` | |
| G5 | 크기 변경: 재검증 또는 `stale_observation` | ①/②: / verdict·code·reason: / 수동 크기 변경 여부: | `g5_resize/` | |
| G6 | 포커스 잃음 → `window_not_foreground`, 다른 창 입력 없음 | verdict·code: / 메모장 글자: | `g6_focus/` | |
| G7 | 전체화면 전환 캡처 (창·테두리 없음·독점) | 창: / 테두리 없음: / 독점: / PNG 맞음: | `g7_*/` | |
| G8 | 한글 입력 3개 정확 | 1: / 2: / 3: / OCR 글자: / 쓴 게임: | `g8_1/`, `g8_2/`, `g8_3/` | |
| G9 | OCR 수치 (`ocr_bench --m1-real-game` 종료 코드 0) | 아래 표 | `ocr_bench.json`, `ocr_bench.txt`, `ocr-samples/` | |
| G10 | 강제 종료(Ctrl+C 두 번) 뒤 게임 안 키 떼어짐 | 게임: / 화상 키보드: / run.end code·input_recovery: / input.recovered by: | `g10_hold/` | |
| G11 | 한국어 자판 오른쪽 Ctrl·Alt를 게임이 받음 | rctrl → / ralt → / lctrl → / 물리 키 이름: | `g11_*/` | |
| G12 | 관리자 권한 게임 → `target_elevated`, 잠금 화면 → `input_desktop_unavailable` | 관리자: / 잠금: | `g12_elevated/`, `g12_locked/` | |

## OCR 수치 (G9)

| 값 | 결과 | 기준 | 통과 |
|---|---|---|---|
| 표본 수 (전체) | | ≥ 30 | |
| 한국어 표본 수 | | ≥ 15 | |
| 배율별 표본 수 (100% / 150% / 200%) | | ≥ 20 / ≥ 5 / ≥ 5 | |
| 문자 정확도 | | ≥ 0.95 | |
| 한국어 문자 정확도 | | ≥ 0.90 | |
| 영역 읽기 지연 중앙값 (ms) | | ≤ 200 | |
| 영역 읽기 지연 p95 (ms) | | ≤ 500 | |
| 추론 한 번 최댓값 (ms) | | (참고) | — |
| 실패 표본 | | (참고) | — |
| 기준 PC | 위 "기준 PC" 표 | | — |

## 별도 결정 (X인 항목)

| 항목 | 사유 | 제안 (지원 범위 축소·방식 추가 등) |
|---|---|---|
| | | |

## 판정

- [ ] 모든 항목 O → M1 최종 완료
- [ ] X 있음 → 위 "별도 결정"을 올린다 (최종 완료 아님)
