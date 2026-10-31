// 역할 색 토큰 대조 (M2 계획 2.12). 브라우저를 띄우지 않는 순수 함수라 앱 vitest(tokens.test.ts)도
// 이 파일을 그대로 쓴다. extract.mjs가 시안에서 값을 뽑고, 이 파일이 tokens.css와 비교한다
export const THEMES = ["dark", "light"];

export class TokenError extends Error {
  name = "TokenError";
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
    throw new TokenError(`색으로 읽을 수 없다: ${css}`);
  }
  const hex = (n) => Number(n).toString(16).padStart(2, "0").toUpperCase();
  const rgb = `#${hex(m[1])}${hex(m[2])}${hex(m[3])}`;
  if (m[4] === undefined) return rgb;
  const a = m[4].endsWith("%") ? Number(m[4].slice(0, -1)) / 100 : Number(m[4]);
  return a >= 1 ? rgb : `${rgb}${hex(Math.round(a * 255))}`;
}

// tokens.css의 `:root[data-theme="dark"]`·`[data-theme="light"]` 블록에서 변수 값을 읽는다
export function parseThemeBlocks(cssText) {
  const out = { dark: {}, light: {} };
  const text = cssText.replace(/\/\*[\s\S]*?\*\//g, "");
  const blockRe = /([^{}]*)\{([^{}]*)\}/g;
  for (const m of text.matchAll(blockRe)) {
    const theme = m[1].match(/\[data-theme=["']?(dark|light)["']?\]/)?.[1];
    if (!theme) continue;
    for (const d of m[2].matchAll(/(--[\w-]+)\s*:\s*([^;]+);?/g)) out[theme][d[1]] = d[2].trim();
  }
  return out;
}

// 역할 색 토큰이 다크·라이트 시안 값과 같은지. 문제 목록을 돌려준다. themes로 한 테마만 볼 수 있다
export function checkRoleTokens(cssText, tokens, themes = THEMES) {
  const blocks = parseThemeBlocks(cssText);
  const problems = [];
  for (const [role, values] of Object.entries(tokens.colors)) {
    for (const theme of themes) {
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
