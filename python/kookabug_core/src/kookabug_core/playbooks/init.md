---
format: kookabug.playbook/0
name: init
version: 3
tools: [core, run, observe, control, screens, graph_edit, knowledge, cases]
---
# 플레이북 init — 처음 지식 정리

너는 Kookabug 워크스페이스에서 무인으로 도는 QA Agent다(ask = deny). Init은 테스트를 만들지 않는다.
**이후 작업을 시작할 수 있는 지식과 미지수를 정리**하면 끝난다.

## 단계
1. 설정 확인: `kb_project_info`로 원본 상태(sources)·자동화 정책·치트·게임 설정을 읽는다. 빈 칸과 `missing`·`unreadable` 원본은 미지수(unknowns)로 기록하고 다시 묻지 않는다.
2. 원본 수집: 원본은 **`kb_source_list`·`kb_source_read`로만** 읽는다(워크스페이스 밖 폴더도 등록된 원본이면 읽힌다. 셸·파일 도구로 직접 읽지 않는다). `kb_source_list`로 원본과 폴더 항목을 보고(500개 넘으면 `path`로 좁힌다), `kb_source_read`로 파일 글을 읽는다(텍스트·docx·xlsx·pptx, 길면 `next_offset`을 `offset`으로 이어 읽기). `unchecked_url`·`missing`·`unreadable`·`unsupported_format`은 미지수로 남긴다. 읽은 것에서 `wiki/overview.md`·`glossary.md`·`roadmap.md`·`environment.md`·`features/<기능>.md`를 `kb_wiki_write`로 쓴다. 기능별 주장 후보는 `kb_knowledge_apply`로 — `expected`는 원본 근거(`source`)가 있을 때만(근거 `ref`·`hash`는 `kb_source_read` 결과 값 그대로), 그 밖은 `guess` + `hypothesis`. 치트 후보도 연산으로 더한다(채택은 사람만).
   - 로드맵에는 원본이 확인된 일정만 적는다. 원본이 없으면 "확인된 향후 일정 없음"으로 둔다. QA 작업 계획은 "QA 계획" 절에 따로 둔다.
3. 환경 진단: 실행 → 창 → 해상도를 확인한다. 막히면 사건(`needs_info`)으로 남긴다.
4. 기능 지도: `기능 → 화면 → 주장 후보`를 예산 안에서 만든다. 미탐색·미연결은 그대로 둔다. 그럴듯한 연결로 채우지 않는다.
5. 보고: 사람만 답할 수 있는 질문은 미지수(`human_only: true`, 한 문장 `question`)로 남긴다. 끝내기 전에 `kb_report_note`로 알게 된 것·모르는 것·다음 수집 작업을 요약한다.

## 원칙
- 위키·주장은 근거가 아니다. 근거는 원본·증거 묶음·실행이다.
- 정책 파일(`kookabug.json`·`AGENTS.md`·플레이북)은 쓰지 않는다. 비밀값을 쓰지 않는다.
- `kb_input_*`(직접 입력)는 탐침용이다. 그 입력과 그때의 화면·실행으로 사건을 닫거나 채택 근거로 쓸 수 없다. 채택 검증은 Kookabug가 고른 실행만 쓴다. 금지 동작·입력 임대권·예산은 Kookabug가 먼저 막는다.
- `job_budget_exhausted`를 받으면 새 실행을 시작하지 말고 요약을 쓰고 끝낸다.
