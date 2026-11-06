// 에이전트 패널 세션 → 렌더러 알림 모양 (M5 계획 3.10). 주 프로세스·preload·렌더러가 타입만 같이 쓴다

/** 에이전트가 준 권한 선택지 그대로 (ACP PermissionOption) */
export interface AgentPermissionOption {
  id: string;
  name: string;
  /** allow_once·allow_always·reject_once·reject_always (모르는 값은 그대로) */
  kind: string;
}

export type AgentSessionStatus = "starting" | "ready" | "busy" | "ended" | "error";

export type AgentEvent =
  | { type: "status"; status: AgentSessionStatus; message?: string }
  /** agent_message_chunk 글자 조각 (이어 붙인다) */
  | { type: "message"; text: string }
  /** 내 말 (prompt를 보낸 순간 — 렌더러가 그린다) */
  | { type: "tool"; id: string; title: string; status: string; kind: string; failed: boolean; text: string }
  /** 생각·계획 등 화면에 내지 않는 갱신 (접힌 줄 개수만) */
  | { type: "hidden"; kind: string }
  /** session/request_permission: 카드 (답은 agentPermission). 자동 허용 없음 */
  | { type: "permission"; id: string; title: string; options: AgentPermissionOption[] }
  /** 카드가 닫힘: 사람이 골랐거나 세션 중지·끝으로 cancelled */
  | { type: "permission_closed"; id: string; outcome: "selected" | "cancelled"; optionId?: string }
  | { type: "turn_end"; stopReason: string }
  | { type: "exit"; code: number | null; message: string };

export interface AgentSessionEvent {
  session: string;
  event: AgentEvent;
}

export interface AgentStartResult {
  session: string;
  agentId: string;
  name: string;
}
