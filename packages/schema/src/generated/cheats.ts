/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `Cheats`'s JSON-Schema
 * via the `definition` "CheatArg".
 */
export type CheatArg = CheatArgInteger | CheatArgEnum | CheatArgId;
/**
 * This interface was referenced by `Cheats`'s JSON-Schema
 * via the `definition` "CheatImpl".
 */
export type CheatImpl = CheatImplConsole | CheatImplPlugin;

/**
 * 치트 정의 knowledge/cheats.json (M8 계획 3.2). adoption은 사람 전용
 */
export interface Cheats {
  cheats: Cheat[];
  format: "kookabug.cheats/0";
  history?: Cheat[];
  revision: number;
}
/**
 * This interface was referenced by `Cheats`'s JSON-Schema
 * via the `definition` "Cheat".
 */
export interface Cheat {
  adoption?: CheatAdoption | null;
  args: {
    [k: string]: CheatArg | undefined;
  };
  effect: string;
  env?: {
    profiles?: string[];
  };
  id: string;
  impl: CheatImpl;
  origin?: {
    basis?: import("./claims.js").Basis[];
    job?: string;
    kind: "agent" | "human";
  };
  preconditions?: string[];
  rev: number;
  title: string;
}
export interface CheatAdoption {
  at: string;
  by: "human";
  category: string;
  digest: string;
}
export interface CheatArgInteger {
  max: number;
  min: number;
  type: "integer";
}
export interface CheatArgEnum {
  type: "enum";
  /**
   * @minItems 1
   */
  values: [string, ...string[]];
}
export interface CheatArgId {
  type: "id";
}
export interface CheatImplConsole {
  graph: string;
  kind: "console";
  template: string;
}
export interface CheatImplPlugin {
  kind: "plugin";
  node: string;
}
