// 앱 창 닫기 확인 (`app.closeRequested`, 주 프로세스 close-guard.ts의 답)
import { flushConversation } from "../agent/agentStore";
import { confirmLeaveDirty } from "../store/editing";

/**
 * 저장 안 된 그래프를 묻고, 닫기로 했으면 에이전트 패널 대화의 마지막 저장을 한다. 그 저장은 최대 `FLUSH_LIMIT_MS`(1.5초)만
 * 기다린다 — 응답이 없어도 닫기를 막지 않는다 (UX4 검수 2 H2)
 */
export async function confirmClose(): Promise<boolean> {
  const ok = await confirmLeaveDirty();
  if (ok) await flushConversation();
  return ok;
}
