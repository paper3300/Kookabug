/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

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
  settings?: Settings;
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
