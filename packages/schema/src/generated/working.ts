/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 작업 기준 변경 knowledge/working/<변경 ID>/change.json (M8 계획 3.2). 경로는 tests/·subgraphs/·targets/만
 */
export interface WorkingChange {
  case?: string | null;
  created: {
    agent?: string;
    at: string;
    job?: string | null;
  };
  files: WorkingFile[];
  format: "kookabug.working/0";
  group?: string | null;
  id: string;
  kind: "claim_expected" | "graph" | "locator_repair" | "other" | "screen_flow" | "target";
  state: "accepted" | "active" | "adopted" | "rejected" | "reverted" | "stale";
}
export interface WorkingFile {
  after_sha256: string;
  base_sha256: string | null;
  copy: string;
  path: string;
}
