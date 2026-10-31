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
import { checkRoleTokens, parseThemeBlocks, THEMES, tokenName, toHex } from "./tokens-check.mjs";

// 대조 함수는 tokens-check.mjs (브라우저 없이 앱 vitest도 쓴다)
export { checkRoleTokens, parseThemeBlocks, THEMES, tokenName, toHex };

const HERE = path.dirname(fileURLToPath(import.meta.url));
export function loadRoles() {
  return JSON.parse(fs.readFileSync(path.join(HERE, "roles.json"), "utf8"));
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
