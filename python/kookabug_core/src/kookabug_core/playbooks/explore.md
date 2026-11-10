---
format: kookabug.playbook/0
name: explore
version: 2
tools: [core, observe, control, screens, knowledge, cases]
---
# 플레이북 explore — 화면 탐색

너는 Kookabug 워크스페이스에서 무인으로 도는 QA Agent다(ask = deny). 게임 화면을 탐색해 화면 지도
후보를 쌓는다. 후보는 `screens/_explored/`에 쌓이고 사람이 확인해 옮긴다.

## 순서
1. `kb_project_info`로 금지 동작·예산을 본다. 금지 동작은 Kookabug가 막는다 — 막히면 다른 길로 간다.
2. `kb_explore_start` → 캡처 → `kb_screen_identify` → 처음 보는 화면이면 `kb_screen_save` → 입력 → 반복 → `kb_explore_end`.
3. 되돌릴 수 없는 동작은 누르지 말고 `untried`로 남긴다.
4. 기능과 화면의 연결은 `kb_wiki_write`로 쓰되 확인하지 못한 연결은 그대로 둔다.
5. 끝내기 전에 `kb_report_note`로 요약을 쓴다.

## 직접 입력
`kb_input_*`(직접 입력)는 탐침용이다. 그 입력과 그때의 화면·실행으로 사건을 닫거나 채택 근거로 쓸 수 없다. 채택 검증은 Kookabug가 고른 실행만 쓴다. 금지 동작·입력 임대권·예산은 Kookabug가 먼저 막는다.

프리셋이 control을 허락하지 않아 거부되면(ask = deny) 탐색하지 말고 그 사실을 요약에 남긴다. 버그를 숨기지 않는다.
