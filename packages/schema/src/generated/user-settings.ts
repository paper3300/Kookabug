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
  format: "kookabug.user-settings/0";
  permissions?: Permissions;
}
/**
 * 에이전트 권한 (사용자 계층). 모든 워크스페이스에 적용되고, 프로젝트 계층 값이 먼저다
 *
 * This interface was referenced by `UserSettings`'s JSON-Schema
 * via the `definition` "Permissions".
 */
export interface Permissions {
  preset?: "full" | "graph_author" | "read_only" | "runner";
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
