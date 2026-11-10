// 보안 경계 문구 (M8 계획 3.15 — 한 곳에서 쓴다). 마법사 5·7단계 안내와 보고함 머리가 이 글을 그대로 보인다
export const SECURITY_BOUNDARY =
  "Kookabug는 Kookabug 도구(MCP·KOOKABUG_AGENT CLI·agent-job) 안에서만 막습니다. Agent CLI가 자기 셸·파일 도구를 쓰면 막을 수 없습니다. 무인 실행은 Agent CLI 자체 권한 설정으로 셸·파일 쓰기를 끄세요.";

/** 7단계 "채택한 치트만 써요" 각주 (3.15, B6 인계 — 조율자 결정: 탐침 문장을 넣는다) */
export const CHEAT_FOOTNOTE =
  "채택한 치트만 쓰는 것은 qa_runner 제한 실행에서만 보장해요. 작업 안 curator Agent는 직접 입력(탐침)을 할 수 있어요 — 금지 동작은 Kookabug가 막아요.";
