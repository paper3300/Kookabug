# M2 사람 검증 결과

> 이 양식을 레포 밖(`.orchestration/M2/manual_result.md`)으로 복사해 채운다. 절차는 `m2-manual.md`. 증거 경로는 증거 폴더(`manual_evidence/`) 기준 상대 경로로 적는다. 통과 칸은 O / X / -(해당 없음, 사유를 결과 칸에). U절은 통과 칸 대신 "그대로" / "바꿈"을 적는다.

- 검증한 사람:
- 날짜:
- 레포 커밋(`git rev-parse --short HEAD`):
- 설치 파일 이름·크기:
- 화면 배율(설정 → 디스플레이):

## 결과

| 항목 | 내용 | 결과 값 | 증거 경로 | 통과 |
|---|---|---|---|---|
| D1 | 데스크톱 탐지 4개 통과 | | `d1_probe.txt` | |
| D2 | M2 Python 인수 (실제 창 포함) 17 passed | 통과 / 실패 / 건너뜀 / 시간: | `d2_acceptance.log` | |
| D3 | daemon 실제 창·창 목록·프레임 | 통과 수: / 실패 이름: | `d3_daemon_live.log` | |
| D4 | 앱 인수 + 실제 창 target (Electron) 5 passed | 통과 / 실패: | `d4_app.log` | |
| D5 | 전체 자동 검사 (require·INPUT·SOAK) + 전체 E2E | pytest 통과 / 실패 / 건너뜀 / 시간: · E2E 통과 / 실패: | `d5_full.log`, `d5_e2e.log` | |
| D6 | 비교 PNG 22장 | PNG 수: | `ui-compare/` | |
| V1 | 시작 화면 (`welcome`) | 의도 밖 차이: | `ui-compare/welcome-*.png` | |
| V2 | 앱 틀 (`shell-empty`) | 의도 밖 차이: | `ui-compare/shell-empty-*.png` | |
| V3 | 캔버스 (`main-canvas`) | 의도 밖 차이: | `ui-compare/main-canvas-*.png` | |
| V4 | 팔레트 (`main-palette`) | 의도 밖 차이: | `ui-compare/main-palette-*.png` | |
| V5 | 끌어 놓기 중 (`palette-drag`) | 의도 밖 차이: | `ui-compare/palette-drag-*.png` | |
| V6 | 핀 잇기 중 (`connect-drag`) | 의도 밖 차이: | `ui-compare/connect-drag-*.png` | |
| V7 | 닫기 확인 (`close-confirm`) | 의도 밖 차이: | `ui-compare/close-confirm-*.png` | |
| V8 | 속성 편집기 (`inspector`) | 의도 밖 차이: | `ui-compare/inspector-*.png` | |
| V9 | 속성 편집기 연결 핀 (`inspector-link`) | 의도 밖 차이: | `ui-compare/inspector-link-*.png` | |
| V10 | 실행 중 (`main-running`) | 의도 밖 차이: | `ui-compare/main-running-*.png` | |
| V11 | target 편집기 (`target`) | 의도 밖 차이: | `ui-compare/target-*.png` | |
| E1 | 시작 화면·프로젝트 열기·테마 | 기대대로: / 느낌: | — | |
| E2 | 그래프 보기 (확대·이동·미니맵) | 기대대로: / 뒤로 가는 연결선 방해: | — | |
| E3 | 노드 더하기·옮기기·잇기·지우기 | 기대대로: / 숨은 핀이 나타나 겹침 거슬림: | — | |
| E4 | 실행 취소·저장·닫기 확인·새 테스트 | 기대대로: | — | |
| E5 | 속성 편집기 | 기대대로: / 긴 경로 잘림 불편: / "값" 고르기 빽빽함: | — | |
| E6 | 밖에서 바뀐 파일 (충돌 띠) | 기대대로: / 문구 이해: | — | |
| E7 | 실행·정지 (실제 게임) | 판정: / 시간: / 메뉴 실행·정지와 F5·Shift+F5가 툴바와 같음: / 정지 단추 찾기: | — | |
| E8 | 저장 안 된 그래프 실행 → 자동 저장 | 기대대로: | — | |
| E9 | 라이트 테마로 다시 보기 | 읽기 어려운 곳: | — | |
| T1 | 창에서 찍어 target 만들기 → 바로 매칭 | 임계값 전환(계정 칸, 0.50 찾음·0.99 못 찾음): / 같은 화면 자르기 1.00 유지: / 기대대로: / 조작 헷갈림: / 배율: | `targets/manual/` 사본 | |
| T2 | 만든 target으로 실제 실행 | 판정: / 실패 노드·메시지: | — | |
| S1 | 설치 파일 | 이름·크기(바이트): | — | |
| S2 | Sandbox 시작 | 환경(Sandbox / VM): | — | |
| S3 | 화면으로 설치 | SmartScreen: / UAC: / 설치 범위 화면: / 긴 경로 "다음" 막힘: / 시작 메뉴: / 바탕 화면: / 시간: | — | |
| S4 | 설치본 앱 실행 (가짜 플랫폼) + doctor headless | smoke_headless: / inventory_open: / doctor 종료 코드: / 개발 빌드와 같아 보임: | `sandbox/s4_doctor.txt` | |
| S5 | 제거: 폴더·PATH·명령·시작 메뉴 없음 | 폴더: / PATH: / 명령: / 시작 메뉴: | `sandbox/s5_uninstall.txt` | |
| S6 | (선택) PowerShell 막힌 PC | 결과: | — | |

## 사용자 결정 (U)

| 항목 | 지금 기본값 | 그대로 / 바꿈 | 바꾼다면 어떻게 |
|---|---|---|---|
| U1 | 속성 편집기 = 오른쪽 패널 320px | | |
| U2 | 저장 안 된 그래프 실행 = 자동 저장 뒤 실행 | | |
| U3 | M2에 없는 기능 버튼 숨김 | | |
| U4 | 툴바 "대상" = 실행 프로필 | | |
| U5 | 시작 화면 "시작하기" 숨김 | | |
| U6 | 글꼴 앱에 넣음, OFL-1.1 글꼴 한정 허용 | | |
| U7 | "여러 개면 좌상단부터" 없음 | | |
| U8 | ffmpeg.dll 한정 예외 허용 | | |
| U9 | M1 사람 검증 전에 M2 시작 | | |
| U10 | 정지 ■ = 탭 줄 툴바 | | |
| U11 | 설치 파일 zip (약 262 MiB) | | |
| U12 | 바탕 화면 바로 가기 없음 | | |
| U13 | ffmpeg 소스 제공 약속 문구 | | |
| U14 | 뒤로 가는 연결선 기본 곡선 (미룸) | | |
| U15 | 새 target은 속성 편집기에서만 | | |

## 별도 결정·고칠 것 (X 항목, U "바꿈", V의 의도 밖 차이)

| 항목 | 내용 | 제안 (고칠 작업·범위 조정·다음 단계로 미룸) |
|---|---|---|
| | | |

## 판정

- [ ] D·V·E·T·S 모두 O이고 U에 "바꿈"이 없음 → M2 최종 완료
- [ ] X 또는 "바꿈" 있음 → 위 표를 올린다 (다음 단계로 미뤄도 되는 "바꿈"만 있으면 그렇게 적고 최종 완료로 셀 수 있다)
