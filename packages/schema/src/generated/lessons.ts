/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 경험칙 knowledge/lessons.json (M8 계획 3.2). 저장·근거·활성만
 */
export interface Lessons {
  format: "kookabug.lessons/0";
  history?: Lesson[];
  lessons: Lesson[];
  revision: number;
}
/**
 * This interface was referenced by `Lessons`'s JSON-Schema
 * via the `definition` "Lesson".
 */
export interface Lesson {
  active: boolean;
  advice: string;
  applies?: {
    builds?: string[];
    profiles?: string[];
    screens?: string[];
  };
  basis: import("./claims.js").Basis[];
  id: string;
  rev: number;
}
