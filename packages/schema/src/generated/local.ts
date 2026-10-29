/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "PermissionVerdict".
 */
export type PermissionVerdict = "allow" | "ask" | "deny";
/**
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "SettingKey".
 */
export type SettingKey = string;

/**
 * 개인 설정 (.kookabug/local.json, Git 제외)
 */
export interface Local {
  format: "kookabug.local/0";
  permissions?: Permissions;
  settings?: Settings;
}
/**
 * 에이전트 권한 (프로젝트 계층). 툴셋·프리셋 값이 사용자 설정보다 먼저다
 *
 * This interface was referenced by `Local`'s JSON-Schema
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
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "PermissionRule".
 */
export interface PermissionRule {
  rule: string;
  verdict: PermissionVerdict;
}
/**
 * 설정 키 → 값. 여기 있는 키는 프로필·기본값보다 먼저 쓴다 (null도 선택된 값)
 *
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "Settings".
 */
export interface Settings {
  [k: string]: unknown | undefined;
}
