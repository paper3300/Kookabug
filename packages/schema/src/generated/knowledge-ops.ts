/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `KnowledgeOps`'s JSON-Schema
 * via the `definition` "KnowledgeOp".
 */
export type KnowledgeOp =
  OpAdd | OpRevise | OpSupersede | OpMarkConflicted | OpAttachEvidence | OpSetStatus;

/**
 * 제한 지식 변경 요청 kb_knowledge_apply (M8 계획 3.3). 한 요청 전부 적용 또는 전부 거부
 */
export interface KnowledgeOps {
  format?: "kookabug.knowledge-ops/0";
  /**
   * @minItems 1
   * @maxItems 200
   */
  ops: [KnowledgeOp, ...KnowledgeOp[]];
  request_id: string;
}
export interface OpAdd {
  base_revision: number;
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  item: {
    [k: string]: unknown | undefined;
  };
  op: "add";
}
export interface OpRevise {
  base_rev: number;
  changes: {
    [k: string]: unknown | undefined;
  };
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  id: string;
  op: "revise";
}
export interface OpSupersede {
  base_rev: number;
  by: import("./claims.js").ClaimRef;
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  id: string;
  op: "supersede";
}
export interface OpMarkConflicted {
  base_rev: number;
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  id: string;
  op: "mark_conflicted";
  /**
   * @minItems 1
   */
  with: [import("./claims.js").ClaimRef, ...import("./claims.js").ClaimRef[]];
}
export interface OpAttachEvidence {
  base_rev: number;
  basis: import("./claims.js").Basis;
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  id: string;
  op: "attach_evidence";
}
export interface OpSetStatus {
  base_rev: number;
  /**
   * features/<기능>·lessons·cheats·unknowns (사건은 cases 도구로만)
   */
  file: string;
  id: string;
  op: "set_status";
  status: string;
}
