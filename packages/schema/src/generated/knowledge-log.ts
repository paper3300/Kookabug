/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 지식 감사 이력 knowledge/log.jsonl 한 줄 (M8 계획 3.2). 값 대신 바뀐 필드 이름만
 */
export interface KnowledgeLogLine {
  agent: KnowledgeActor;
  at: string;
  base_rev?: number | null;
  basis?: {
    ref: string;
    type: string;
  }[];
  code?: string;
  fields?: string[];
  file: string;
  format: "kookabug.knowledge-log/0";
  id?: string | null;
  job?: string | null;
  new_rev?: number | null;
  op: string;
  request_id?: string | null;
  result: "applied" | "conflict" | "refused";
  seq: number;
}
export interface KnowledgeActor {
  client?: string | null;
  id?: string | null;
  kind: "agent" | "human" | "kookabug";
  model?: string | null;
}
