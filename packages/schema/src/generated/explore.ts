/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 에이전트 탐색 세션 기록 (screens/_explored/<세션 ID>/explore.json, M7)
 */
export interface Explore {
  agent: {
    client?: string;
    id: string;
  };
  approvals?: ExploreApproval[];
  /**
   * UTC ISO 8601
   */
  ended_at?: string | null;
  format: "kookabug.explore/0";
  goal?: string;
  id: string;
  max_steps: number;
  /**
   * 승격한 후보 키 → 확정 화면 ID
   */
  promoted?: {
    [k: string]: string | undefined;
  };
  /**
   * UTC ISO 8601
   */
  started_at: string;
  status: "active" | "ended" | "interrupted";
  steps: number;
  title: string;
  window?: string;
}
/**
 * "이 탐색 동안 허용" 감사 기록 하나 (값 없음)
 *
 * This interface was referenced by `Explore`'s JSON-Schema
 * via the `definition` "ExploreApproval".
 */
export interface ExploreApproval {
  /**
   * 권한 인자 (control은 창 제목)
   */
  arg?: string;
  /**
   * UTC ISO 8601
   */
  at: string;
  scope: "session";
  tool: string;
}
