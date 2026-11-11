/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 작업 보고 knowledge/reports/<작업 ID>.json (M8 계획 3.11). 항목은 Kookabug가 작업의 구조화 기록에서 만들고 Agent 글은 notes 하나
 */
export interface Report {
  agent?: string | null;
  budget?: {
    /**
     * @minItems 2
     * @maxItems 2
     */
    minutes?: [number, number];
    /**
     * @minItems 2
     * @maxItems 2
     */
    runs?: [number, number];
  };
  ended_at?: string | null;
  format: "kookabug.report/0";
  groups: ReportGroup[];
  job: string;
  notes?: string | null;
  playbook: string;
  rendered?: string | null;
  /**
   * 생성 시점에 고정한 revision (렌더가 이 값을 쓴다 — 결정 뒤 다시 렌더해도 그대로)
   */
  revisions?: {
    claims: {
      [k: string]: number | undefined;
    };
  };
  started_at: string;
  state:
    | "budget_exhausted"
    | "cancelled"
    | "done"
    | "failed"
    | "interrupted"
    | "prep_failed"
    | "running";
  trigger: "ci" | "manual" | "schedule";
  unknowns?: string[];
}
export interface ReportGroup {
  cause: string;
  decision?: {
    at: string;
    by: "human";
    decision: "accept" | "reject";
  } | null;
  items: ReportItem[];
  key: string;
  title: string;
}
export interface ReportItem {
  adoption?: string;
  case?: string;
  change?: string;
  cheat?: string;
  checks?: string[];
  claims?: import("./claims.js").ClaimRef[];
  detail?: string;
  evidence?: string;
  kind:
    | "auto_adopted"
    | "budget"
    | "cheat_candidate"
    | "init_summary"
    | "prep_failed"
    | "regression_suspect"
    | "setting_change"
    | "stalled"
    | "undetermined"
    | "working_only";
  /**
   * UX2: 설정 바꾸기 제안 (Agent가 제안, 사람이 report.decide로 수락·거절). 팀 보고에는 ID·키·이유만 — 값·현재 값은 이 PC .kookabug/jobs/<작업>/proposals.json에만
   */
  setting?: {
    id: string;
    key:
      | "automation.forbidden.add"
      | "cheats.categories.add"
      | "game.args"
      | "game.cwd"
      | "game.executable"
      | "game.title"
      | "sources.add";
    reason: string;
  };
  summary?: {
    [k: string]: number | undefined;
  };
  unknowns?: string[];
}
