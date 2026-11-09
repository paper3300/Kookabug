/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `Automation`'s JSON-Schema
 * via the `definition` "Forbidden".
 */
export type Forbidden = ForbiddenText | ForbiddenTarget | ForbiddenScreen;

/**
 * 자동화 정책 kookabug.json#automation (M8 계획 3.4). 사람 전용 쓰기. 빠진 키는 기본값
 */
export interface Automation {
  auto_repair?: AutoRepair;
  budget?: JobBudget;
  forbidden?: Forbidden[];
  format: "kookabug.automation/0";
}
export interface AutoRepair {
  enabled?: boolean;
  max_adoptions?: number;
  profiles?: string[] | null;
  scope?: string[];
}
export interface JobBudget {
  minutes?: number;
  runs?: number;
}
export interface ForbiddenText {
  kind: "text";
  value: string;
}
export interface ForbiddenTarget {
  kind: "target";
  path: string;
}
export interface ForbiddenScreen {
  id: string;
  kind: "screen";
}
