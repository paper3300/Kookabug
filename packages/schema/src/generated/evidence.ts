/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 증거 묶음 knowledge/evidence/<묶음 ID>/manifest.json (M8 계획 3.2). 가림 처리된 최소 증거, 지우거나 고치는 도구 없음
 */
export interface Evidence {
  basis?: {
    kind: "team" | "working";
  };
  by: {
    id?: string;
    kind: "agent" | "human" | "kookabug";
  };
  env?: {
    /**
     * @minItems 2
     * @maxItems 2
     */
    client_size?: [number, number];
    dpi?: number;
    game_build?: string | null;
    platform?: string | null;
    profile?: string | null;
  };
  failed_step?: {
    code?: string | null;
    node?: string | null;
    step?: string | null;
    type?: string | null;
  } | null;
  files: EvidenceFile[];
  format: "kookabug.evidence/0";
  graph_sha?: string | null;
  id: string;
  note?: string;
  omitted?: {
    reason: string;
    what: string;
  }[];
  origin?: string;
  pinned_at: string;
  run?: string | null;
  verdict?: ("error" | "fail" | "pass" | "skip") | null;
}
export interface EvidenceFile {
  bytes?: number;
  path: string;
  sha256: string;
}
