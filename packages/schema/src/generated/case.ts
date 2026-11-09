/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 조사 사건 knowledge/cases/<사건 ID>.json (M8 계획 3.2). resolved·closed는 Kookabug만
 */
export interface Case {
  actions?: ("baseline_change" | "reobserve" | "repair_candidate" | "rerun")[];
  format: "kookabug.case/0";
  hypotheses?: CaseHypothesis[];
  id: string;
  links?: {
    adoption?: string | null;
    claims?: import("./claims.js").ClaimRef[];
    reports?: string[];
    working?: string[];
  };
  needs?: CaseNeed[];
  original: CaseOriginal;
  recheck?: {
    on?: ("new_build" | "new_evidence" | "new_source")[];
    until?: string | null;
  };
  resolution?: CaseResolution | null;
  revision: number;
  runs?: {
    at: string;
    evidence?: string | null;
    run: string;
  }[];
  signature: string;
  state: "closed" | "needs_info" | "open" | "resolved" | "watching";
  symptom: CaseSymptom;
  title: string;
}
export interface CaseHypothesis {
  cause:
    | "environment"
    | "flow_change"
    | "intended_change"
    | "intermittent"
    | "product_regression"
    | "test_defect"
    | "ui_change";
  note?: string;
  state: "confirmed" | "open" | "refuted" | "supported";
  support?: import("./claims.js").Basis[];
}
export interface CaseNeed {
  how?: string;
  human_only?: boolean;
  observation?: string;
  permission?: string;
  splits?: string;
  unknown: string;
}
export interface CaseOriginal {
  basis?: {
    kind: "team" | "working";
  };
  claims?: import("./claims.js").ClaimRef[];
  evidence?: string | null;
  graph_sha?: string | null;
  run: string;
}
export interface CaseResolution {
  adoption?: string;
  at?: string;
  by: "adoption" | "human";
  note?: string;
}
export interface CaseSymptom {
  code?: string | null;
  kind:
    | "launch_failed"
    | "node_error"
    | "stalled"
    | "target_missing"
    | "unexpected_screen"
    | "value_mismatch";
  node?: string | null;
  test?: string | null;
}
