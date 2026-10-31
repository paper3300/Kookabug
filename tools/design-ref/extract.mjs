// 시안에서 역할별 색과 앱 틀 치수를 뽑는다 (M2 계획 2.12 "토큰·치수 추출").
//
//   node tools/design-ref/extract.mjs   → build/design-ref/tokens.json
//
// 역할 표는 roles.json이다. 앱의 tokens.css(T7)는 checkRoleTokens로 이 값과 같은지 본다.
// 집합 포함이 아니라 역할마다 같은 값이어야 한다 (검수 M10: 배경·글자를 바꿔 넣으면 실패)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { launchBrowser, openReference, OUT_DIR, REPO_ROOT, TemplateError } from "./render.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const THEMES = ["dark", "light"];

export function loadRoles() {
  return JSON.parse(fs.readFileSync(path.join(HERE, "roles.json"), "utf8"));
}

// CSS 변수 이름: "tab.active.bg" → "--kb-tab-active-bg"
export function tokenName(role) {
  return `--kb-${role.replaceAll(".", "-")}`;
}

// 계산된 색 → #RRGGBB (불투명) 또는 #RRGGBBAA
export function toHex(css) {
  const m = css.match(/^rgba?\(\s*(\d+)[,\s]+(\d+)[,\s]+(\d+)(?:[,\s/]+([\d.]+%?))?\s*\)$/);
  if (!m) {
    if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(css)) return css.toUpperCase();
    throw new TemplateError(`색으로 읽을 수 없다: ${css}`);
  }
  const hex = (n) => Number(n).toString(16).padStart(2, "0").toUpperCase();
  const rgb = `#${hex(m[1])}${hex(m[2])}${hex(m[3])}`;
  if (m[4] === undefined) return rgb;
  const a = m[4].endsWith("%") ? Number(m[4].slice(0, -1)) / 100 : Number(m[4]);
  return a >= 1 ? rgb : `${rgb}${hex(Math.round(a * 255))}`;
}

// 페이지 안에서 돈다: 규칙마다 요소를 찾아 계산된 값을 돌려준다
function readInPage(rules) {
  const ownText = (el) =>
    [...el.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => n.data)
      .join("")
      .trim();
  const out = {};
  for (const [role, rule] of Object.entries(rules)) {
    let el = [...document.querySelectorAll(rule.selector)].find(
      (e) => rule.text === undefined || ownText(e).includes(rule.text),
    );
    for (let i = 0; el && i < (rule.up ?? 0); i++) el = el.parentElement;
    if (!el) {
      out[role] = { error: `요소를 찾지 못했다: ${rule.selector} ${rule.text ?? ""}` };
      continue;
    }
    // 치수는 테두리까지 든 배치 크기다 (content-box 계산값이 아니고, 캔버스 확대 같은 변환은 빼고)
    const value =
      rule.prop === "width" ? `${el.offsetWidth}px` : rule.prop === "height" ? `${el.offsetHeight}px` : null;
    out[role] = { value: value ?? getComputedStyle(el).getPropertyValue(rule.prop) };
  }
  return out;
}

async function readScreen(browser, name, rules) {
  const ref = await openReference(browser, name);
  try {
    return await ref.page.evaluate(readInPage, rules);
  } finally {
    await ref.context.close();
  }
}

/**
 * 역할 → {dark, light} 색과 치수(다크 시안 기준, px 숫자)를 뽑는다.
 * 요소가 없거나 색이 투명하면(선택자가 엉뚱한 요소를 가리킴) 던진다
 */
export async function extractRoles(browser, roles = loadRoles()) {
  const colors = {};
  const metrics = {};
  for (const [screenKey, pair] of Object.entries(roles.screens)) {
    const colorRules = Object.fromEntries(
      Object.entries(roles.colors).filter(([, r]) => r.screen === screenKey),
    );
    for (const theme of THEMES) {
      const got = await readScreen(browser, pair[theme], colorRules);
      for (const [role, res] of Object.entries(got)) {
        if (res.error) throw new TemplateError(`${role} (${pair[theme]}): ${res.error}`);
        const hex = toHex(res.value);
        if (hex.length === 9 && hex.endsWith("00")) {
          throw new TemplateError(`${role} (${pair[theme]}): 투명색이다. 선택자를 확인한다`);
        }
        (colors[role] ??= {})[theme] = hex;
      }
    }
    const metricRules = Object.fromEntries(
      Object.entries(roles.metrics).filter(([, r]) => r.screen === screenKey),
    );
    if (Object.keys(metricRules).length === 0) continue;
    const got = await readScreen(browser, pair.dark, metricRules);
    for (const [role, res] of Object.entries(got)) {
      if (res.error) throw new TemplateError(`${role}: ${res.error}`);
      const px = Number.parseFloat(res.value);
      if (!Number.isFinite(px)) throw new TemplateError(`${role}: 치수가 아니다: ${res.value}`);
      metrics[role] = px;
    }
  }
  return { colors, metrics };
}

// tokens.css의 `:root[data-theme="dark"]`·`[data-theme="light"]` 블록에서 변수 값을 읽는다
export function parseThemeBlocks(cssText) {
  const out = { dark: {}, light: {} };
  const blockRe = /([^{}]*)\{([^{}]*)\}/g;
  for (const m of cssText.matchAll(blockRe)) {
    const theme = m[1].match(/\[data-theme=["']?(dark|light)["']?\]/)?.[1];
    if (!theme) continue;
    for (const d of m[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);?/g)) out[theme][d[1]] = d[2].trim();
  }
  return out;
}

// 역할 색 토큰이 다크·라이트 시안 값과 같은지. 문제 목록을 돌려준다
export function checkRoleTokens(cssText, tokens) {
  const blocks = parseThemeBlocks(cssText);
  const problems = [];
  for (const [role, values] of Object.entries(tokens.colors)) {
    for (const theme of THEMES) {
      const name = tokenName(role);
      const got = blocks[theme][name];
      if (got === undefined) {
        problems.push(`${theme} ${name}: 없다`);
        continue;
      }
      let hex;
      try {
        hex = toHex(got.toUpperCase().startsWith("#") ? got : got.toLowerCase());
      } catch {
        problems.push(`${theme} ${name}: 색이 아니다 (${got})`);
        continue;
      }
      if (hex !== values[theme]) problems.push(`${theme} ${name}: ${hex}, 시안 ${values[theme]}`);
    }
  }
  return problems;
}

async function main() {
  const browser = await launchBrowser();
  try {
    const tokens = await extractRoles(browser);
    fs.mkdirSync(OUT_DIR, { recursive: true });
    const file = path.join(OUT_DIR, "tokens.json");
    fs.writeFileSync(file, JSON.stringify(tokens, null, 2) + "\n");
    console.log(
      `${path.relative(REPO_ROOT, file)}  색 역할 ${Object.keys(tokens.colors).length}개, 치수 ${Object.keys(tokens.metrics).length}개`,
    );
  } finally {
    await browser.close();
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main().catch((err) => {
    console.error(err.message ?? err);
    process.exit(1);
  });
}
