/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "SettingKey".
 */
export type SettingKey = string;

/**
 * 팀 공용 워크스페이스 설정 (kookabug.json)
 */
export interface Workspace {
  format: "kookabug.workspace/0";
  profiles?: {
    [k: string]: Profile | undefined;
  };
  record?: RecordPolicy;
  retention?: Retention;
  settings?: Settings;
}
/**
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Profile".
 */
export interface Profile {
  settings?: Settings;
}
/**
 * 설정 키 → 값. null은 사람마다 .kookabug/local.json에 넣어야 하는 값
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Settings".
 */
export interface Settings {
  [k: string]: unknown | undefined;
}
/**
 * 기록 정책. 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 켤 수 없다
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "RecordPolicy".
 */
export interface RecordPolicy {
  screenshots?: "off" | "on";
  video?: "failed_only" | "off" | "on";
}
/**
 * 실행 기록 보관
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Retention".
 */
export interface Retention {
  failed_days?: number;
  keep_last?: number;
  passed_days?: number;
}
