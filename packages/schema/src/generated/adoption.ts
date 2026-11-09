/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 채택 기록 knowledge/adoptions/<채택 ID>.json (M8 계획 3.8): 자동 채택·묶음 수락·되돌리기
 */
export interface Adoption {
  at: string;
  by?: {
    id?: string;
    kind: "human" | "kookabug";
  };
  case?: string | null;
  change?: string | null;
  changes?: string[];
  files: AdoptionFile[];
  format: "kookabug.adoption/0";
  id: string;
  kind: "accept" | "auto" | "revert";
  negatives?: {
    frame: string;
    note?: string;
    source?: string;
  }[];
  policy_sha?: string | null;
  reverted?: {
    adoption: string;
    at: string;
  } | null;
  runs?: string[];
}
export interface AdoptionFile {
  after_sha256: string | null;
  before_sha256: string | null;
  path: string;
}
