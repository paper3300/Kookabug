/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 작업 기준 주장 덧씌움 knowledge/working/claims/<기능>.json (계획 9장 R4). Agent가 기존 expected 주장에 한 revise·supersede·set_status·mark_conflicted는 팀 파일 대신 여기 쌓이고 보고함 수락 때 팀에 반영된다. base_rev = 바탕이 된 팀 주장 rev, claim.rev = 작업 revision
 */
export interface WorkingClaims {
  claims: WorkingClaim[];
  feature: string;
  format: "kookabug.working-claims/0";
  revision: number;
}
export interface WorkingClaim {
  at: string;
  base_rev: number;
  by?: {
    agent?: string | null;
    job?: string | null;
  };
  claim: import("./claims.js").Claim;
  ops: ("mark_conflicted" | "revise" | "set_status" | "supersede")[];
}
