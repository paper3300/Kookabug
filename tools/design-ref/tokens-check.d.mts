// tokens-check.mjs 타입 (앱 vitest tokens.test.ts가 쓴다)
export declare const THEMES: readonly ["dark", "light"];
export type Theme = (typeof THEMES)[number];

export interface RoleTokens {
  colors: Record<string, Record<Theme, string>>;
  metrics: Record<string, number>;
}

export declare class TokenError extends Error {}
export declare function tokenName(role: string): string;
export declare function toHex(css: string): string;
export declare function parseThemeBlocks(cssText: string): Record<Theme, Record<string, string>>;
export declare function checkRoleTokens(cssText: string, tokens: RoleTokens, themes?: readonly Theme[]): string[];
