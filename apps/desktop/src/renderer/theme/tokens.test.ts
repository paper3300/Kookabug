// 색 토큰 = 시안 역할 색 (M2 계획 2.12, 검수 M10). 기준은 tools/design-ref/extract.mjs가 시안에서 뽑은
// build/design-ref/tokens.json이다 (CI desktop 잡은 이 검사 전에 extract를 돌린다)
import fs from "node:fs";
import path from "node:path";
import { describe, expect, test } from "vitest";
import {
  checkRoleTokens,
  parseThemeBlocks,
  tokenName,
  type RoleTokens,
} from "../../../../../tools/design-ref/tokens-check.mjs";

const APP_DIR = path.resolve(import.meta.dirname, "..", "..", "..");
const REPO = path.resolve(APP_DIR, "..", "..");
const RENDERER = path.join(APP_DIR, "src", "renderer");
const TOKENS_CSS = path.join(RENDERER, "theme", "tokens.css");
const TOKENS_JSON = path.join(REPO, "build", "design-ref", "tokens.json");
const ROLES_JSON = path.join(REPO, "tools", "design-ref", "roles.json");

/** 색을 직접 써도 되는 파일: 토큰 표, 핀 색 표(T8, 2.7) */
const COLOR_FILES = new Set([TOKENS_CSS, path.join(RENDERER, "graph", "pinColors.ts")]);
/** 게임 화면 같은 내용 색 예외 (파일 → 이유). 지금은 없다 */
const CONTENT_COLOR_EXCEPTIONS = new Map<string, string>();

function sianTokens(): RoleTokens {
  if (!fs.existsSync(TOKENS_JSON)) {
    throw new Error(`${TOKENS_JSON} 이 없다. node tools/design-ref/extract.mjs 를 먼저 돌린다`);
  }
  return JSON.parse(fs.readFileSync(TOKENS_JSON, "utf8")) as RoleTokens;
}

const css = fs.readFileSync(TOKENS_CSS, "utf8");

const RAW_COLOR = /#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\(/;

/** 주석·문자열 밖 색 값만 찾지 않고 줄 전체를 본다: 주석에 색을 적는 것도 막아 단순하게 둔다 */
function rawColors(text: string): string[] {
  return text
    .split("\n")
    .map((line, i) => [i + 1, line] as const)
    .filter(([, line]) => RAW_COLOR.test(line))
    .map(([n, line]) => `${n}: ${line.trim()}`);
}

function walk(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const p = path.join(dir, e.name);
    return e.isDirectory() ? walk(p) : [p];
  });
}

describe("역할 토큰", () => {
  test("tokens.json이 roles.json의 역할을 모두 담는다 (오래된 추출 결과가 아님)", () => {
    const roles = JSON.parse(fs.readFileSync(ROLES_JSON, "utf8")) as { colors: Record<string, unknown> };
    expect(Object.keys(sianTokens().colors).sort()).toEqual(Object.keys(roles.colors).sort());
  });

  test("test_dark_role_tokens_equal_main_sian", () => {
    expect(checkRoleTokens(css, sianTokens(), ["dark"])).toEqual([]);
  });

  test("test_light_role_tokens_equal_mainlight_sian", () => {
    expect(checkRoleTokens(css, sianTokens(), ["light"])).toEqual([]);
  });

  test("토큰 두 개를 맞바꾸면 실패한다 (일부러 깨뜨림)", () => {
    const blocks = parseThemeBlocks(css);
    const bg = blocks.dark[tokenName("bg")];
    const fg = blocks.dark[tokenName("fg")];
    const swapped = css
      .replace(`${tokenName("bg")}: ${bg};`, `${tokenName("bg")}: ${fg};`)
      .replace(`${tokenName("fg")}: ${fg};`, `${tokenName("fg")}: ${bg};`);
    expect(swapped).not.toBe(css);
    const problems = checkRoleTokens(swapped, sianTokens(), ["dark"]);
    expect(problems.some((p) => p.includes(tokenName("bg")))).toBe(true);
    expect(problems.some((p) => p.includes(tokenName("fg")))).toBe(true);
  });

  test("다크·라이트가 같은 이름 집합을 갖는다", () => {
    const blocks = parseThemeBlocks(css);
    expect(Object.keys(blocks.light).sort()).toEqual(Object.keys(blocks.dark).sort());
  });
});

describe("색은 토큰으로만", () => {
  test("test_no_raw_colors_outside_tokens", () => {
    const files = walk(RENDERER).filter(
      (f) => /\.(css|tsx|ts)$/.test(f) && !/\.test\.tsx?$/.test(f) && !COLOR_FILES.has(f),
    );
    expect(files.length).toBeGreaterThan(10);
    const found: string[] = [];
    for (const file of files) {
      if (CONTENT_COLOR_EXCEPTIONS.has(file)) continue;
      for (const hit of rawColors(fs.readFileSync(file, "utf8"))) found.push(`${path.relative(RENDERER, file)}:${hit}`);
    }
    expect(found).toEqual([]);
  });

  test("검사가 실제로 색을 찾는다", () => {
    expect(rawColors("a { color: #fff; }\nb { color: var(--kb-fg); }")).toEqual(["1: a { color: #fff; }"]);
    expect(rawColors("box-shadow: 0 0 0 4px rgba(0,120,212,.25)")).toHaveLength(1);
    expect(rawColors("background: rgb(1 2 3)")).toHaveLength(1);
    expect(rawColors('<div id="root"> #root {}')).toEqual([]);
  });
});
