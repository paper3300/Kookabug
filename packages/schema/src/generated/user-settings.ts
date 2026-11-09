/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "PermissionVerdict".
 */
export type PermissionVerdict = "allow" | "ask" | "deny";

/**
 * 사용자 설정 (%APPDATA%\Kookabug\settings.json, 워크스페이스 밖)
 */
export interface UserSettings {
  agents?: Agent[];
  /**
   * 판단 노드의 agent가 null일 때 쓰는 에이전트 ID
   */
  default_agent?: string;
  format: "kookabug.user-settings/0";
  permissions?: Permissions;
}
/**
 * 판단 노드·에이전트 패널이 띄우는 ACP 에이전트 하나. env의 비밀값은 {"$secret": 키}로만 쓴다 (실행 때 찾음)
 *
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "Agent".
 */
export interface Agent {
  args?: string[];
  command: string;
  env?: {
    [k: string]: string | SecretRef | undefined;
  };
  id: string;
  name: string;
}
/**
 * 비밀값 저장소의 키 (값은 실행 때 찾는다)
 *
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "SecretRef".
 */
export interface SecretRef {
  $secret: string;
}
/**
 * 에이전트 권한 (사용자 계층). 모든 워크스페이스에 적용되고, 프로젝트 계층 값이 먼저다
 *
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "Permissions".
 */
export interface Permissions {
  preset?: "curator" | "explorer" | "full" | "graph_author" | "qa_runner" | "read_only" | "runner";
  rules?: PermissionRule[];
  toolsets?: {
    [k: string]: PermissionVerdict | undefined;
  };
}
/**
 * 권한 규칙 하나. rule은 "도구" 또는 "도구(인자 패턴)". 도구·인자 모두 glob(*, ?), 대소문자 구분
 *
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "PermissionRule".
 */
export interface PermissionRule {
  rule: string;
  verdict: PermissionVerdict;
}
