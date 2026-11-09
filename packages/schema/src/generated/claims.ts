/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 기능별 주장 파일 knowledge/features/<기능>.json (M8 계획 3.2). history는 옛 rev 항목
 */
export interface Claims {
  claims: Claim[];
  feature: string;
  format: "kookabug.claims/0";
  history?: Claim[];
  revision: number;
}
/**
 * 주장 하나 (KB문서 6장)
 *
 * This interface was referenced by `Claims`'s JSON-Schema
 * via the `definition` "Claim".
 */
export interface Claim {
  basis: Basis[];
  conflicts_with?: ClaimRef[];
  id: string;
  kind: "expected" | "guess" | "observed";
  preconditions?: string[];
  property?: string;
  rev: number;
  scope?: ClaimScope;
  statement: string;
  status: "conflicted" | "hypothesis" | "superseded" | "supported" | "unverifiable";
  subject?: string;
  superseded_by?: ClaimRef;
  supersedes?: ClaimRef | null;
  unit?: string;
  /**
   * 명제의 값 (JSON 값 무엇이든)
   */
  value?: {
    [k: string]: unknown | undefined;
  };
  verified_by?: ClaimVerifier[];
}
/**
 * 근거 하나. source = sources:<원본 ID>#<위치>, evidence = 증거 묶음 ID, run = 실행 ID, human = 사람 답(u-…)·사람 연산. 위키·주장 근거 형식은 없다(자기 인용 차단). source의 hash·verified는 서비스가 계산해 넣는다(URL 등 확인 못 한 원본은 verified: false — 그것만으로 expected를 supported로 못 올린다, 계획 9장 R5)
 *
 * This interface was referenced by `Claims`'s JSON-Schema
 * via the `definition` "Basis".
 */
export interface Basis {
  hash?: string;
  note?: string;
  ref: string;
  seen_at?: string;
  type: "evidence" | "human" | "run" | "source";
  verified?: boolean;
}
/**
 * This interface was referenced by `Claims`'s JSON-Schema
 * via the `definition` "ClaimRef".
 */
export interface ClaimRef {
  id: string;
  rev: number;
}
/**
 * 적용 범위. null·빠짐 = 제한 없음
 *
 * This interface was referenced by `Claims`'s JSON-Schema
 * via the `definition` "ClaimScope".
 */
export interface ClaimScope {
  builds?: {
    from?: string | null;
    to?: string | null;
  } | null;
  data_rev?: string | null;
  locale?: string | null;
  profiles?: string[] | null;
}
export interface ClaimVerifier {
  graph: string;
  node: string;
}
