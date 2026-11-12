// 에이전트 패널 세션 → 렌더러 알림 모양 (M5 계획 3.10). 주 프로세스·preload·렌더러가 타입만 같이 쓴다

/** 에이전트가 준 권한 선택지 그대로 (ACP PermissionOption) */
export interface AgentPermissionOption {
  id: string;
  name: string;
  /** allow_once·allow_always·reject_once·reject_always (모르는 값은 그대로) */
  kind: string;
}

/**
 * 에이전트가 알려 준 세션 설정 하나 (ACP session config option, 옛 models·modes도 이 모양으로).
 * category: model·mode·thought_level 등 (모르는 값은 그대로, 없으면 "")
 */
export interface AgentConfigOption {
  id: string;
  name: string;
  category: string;
  current: string;
  options: { value: string; name: string; description?: string }[];
  /** 바꿀 때 쓸 메서드: config = session/set_config_option, model = session/set_model, mode = session/set_mode */
  source: "config" | "model" | "mode";
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
  /** 세션 설정(모델·생각 수준 등)이 바뀜 — 통째로 */
  | { type: "config"; options: AgentConfigOption[] }
  | { type: "exit"; code: number | null; message: string };

export interface AgentSessionEvent {
  session: string;
  event: AgentEvent;
}

export interface AgentStartResult {
  session: string;
  agentId: string;
  name: string;
  /** session/new가 알려 준 세션 설정 (없으면 빈 배열) */
  config: AgentConfigOption[];
  /** 에이전트가 준 ACP 세션 ID (이전 대화에 남겨 session/load로 이어 간다, UX4) */
  acpSession: string;
  /** 요청한 지난 세션을 session/load로 불러 이어 가는가 (에이전트가 loadSession을 지원할 때만, UX4) */
  loaded: boolean;
}
