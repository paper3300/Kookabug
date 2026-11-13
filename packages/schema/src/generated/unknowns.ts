/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 미지수 knowledge/unknowns.json (M8 계획 3.2). 답은 사람 전용 unknowns.answer만
 */
export interface Unknowns {
  format: "kookabug.unknowns/0";
  history?: Unknown[];
  revision: number;
  unknowns: Unknown[];
}
/**
 * This interface was referenced by `Unknowns`'s JSON-Schema
 * via the `definition` "Unknown".
 */
export interface Unknown {
  answer?: UnknownAnswer | null;
  blocks?: string[];
  how?: string;
  human_only: boolean;
  id: string;
  /**
   * UX5: 질문 종류. credential = 테스트 계정이 필요함 (글 답 없이 사람이 비밀값을 등록한다, 값은 남지 않는다). 없으면 question
   */
  kind?: "question" | "credential";
  /**
   * @maxItems 20
   */
  options?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string, string]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ]
    | [
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string,
        string
      ];
  question: string;
  rev: number;
  /**
   * UX5 credential: Agent가 쓸 비밀값 키 이름 제안 ({"$secret": 키}). 값이 아니다
   *
   * @maxItems 10
   */
  secret_keys?:
    | []
    | [string]
    | [string, string]
    | [string, string, string]
    | [string, string, string, string]
    | [string, string, string, string, string]
    | [string, string, string, string, string, string]
    | [string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string]
    | [string, string, string, string, string, string, string, string, string, string];
  source?: string | null;
  state: "answered" | "dropped" | "open";
}
export interface UnknownAnswer {
  at: string;
  by: "human";
  text: string;
}
