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
  plugin_index?: PluginIndex;
  plugin_trust?: PluginTrust;
  settings?: Settings;
  /**
   * M8: 이 PC의 원본 경로 (kookabug.json sources[].local: true인 원본)
   */
  sources?: {
    [k: string]: LocalSource | undefined;
  };
}
/**
 * 에이전트 권한 (프로젝트 계층). 툴셋·프리셋 값이 사용자 설정보다 먼저다
 *
 * This interface was referenced by `Local`'s JSON-Schema
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
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "PermissionRule".
 */
export interface PermissionRule {
  rule: string;
  verdict: PermissionVerdict;
}
/**
 * M6: 플러그인 의존성 인덱스. kookabug.json은 팀 공용, .kookabug/local.json의 같은 키가 개인 덮어쓰기. URL의 사용자 정보는 잠금·로그·화면에 남기지 않는다
 *
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "PluginIndex".
 */
export interface PluginIndex {
  find_links?: string[];
  url?: string;
}
/**
 * M6: 이 PC에서 사람이 신뢰 확인한 kookabug.lock의 정규 잠금 해시들 (같은 잠금이면 다시 묻지 않는다, 오래된 것부터 버림)
 *
 * This interface was referenced by `Local`'s JSON-Schema
 * via the `definition` "PluginTrust".
 */
export interface PluginTrust {
  /**
   * @maxItems 20
   */
  locks?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ];
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
export interface LocalSource {
  path: string;
}
