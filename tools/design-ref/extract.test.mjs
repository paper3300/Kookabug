// 역할 색·치수 추출 검사 (M2 계획 T1, 검수 M10)
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { checkRoleTokens, extractRoles, loadRoles, THEMES, tokenName, toHex } from "./extract.mjs";
import { launchBrowser } from "./render.mjs";

let browser;
let tokens;
before(async () => {
  browser = await launchBrowser();
  tokens = await extractRoles(browser);
});
after(async () => {
  await browser?.close();
});

// 추출값으로 만든 tokens.css (T7이 만들 파일의 모양)
function tokensCss(colors) {
  return THEMES.map(
    (theme) =>
      `:root[data-theme="${theme}"] {\n` +
      Object.entries(colors)
        .map(([role, v]) => `  ${tokenName(role)}: ${v[theme].toLowerCase()};`)
        .join("\n") +
      "\n}",
  ).join("\n");
}

test("test_role_colors_dark_and_light", () => {
  const roles = loadRoles();
  assert.deepEqual(Object.keys(tokens.colors).sort(), Object.keys(roles.colors).sort());
  for (const [role, v] of Object.entries(tokens.colors)) {
    for (const theme of THEMES) assert.match(v[theme], /^#[0-9A-F]{6}([0-9A-F]{2})?$/, `${role} ${theme}`);
  }
  // 시안에서 직접 읽은 값 몇 개: 역할이 엉뚱한 요소를 가리키면 여기서 드러난다
  assert.deepEqual(tokens.colors["bg"], { dark: "#1F1F1F", light: "#FFFFFF" });
  assert.deepEqual(tokens.colors["fg"], { dark: "#CCCCCC", light: "#3B3B3B" });
  assert.deepEqual(tokens.colors["titlebar.bg"], { dark: "#181818", light: "#F8F8F8" });
  assert.deepEqual(tokens.colors["accent"], { dark: "#0078D4", light: "#005FB8" });
  assert.deepEqual(tokens.colors["statusbar.running.bg"], { dark: "#005FB8", light: "#005FB8" });
  assert.equal(tokens.colors["status.ok"].dark, "#89D185");
  assert.equal(tokens.colors["status.fail"].dark, "#F0883E");
  // 배경과 글자는 테마마다 다르다
  for (const role of ["bg", "fg", "sidebar.bg", "tab.active.fg", "welcome.bg"]) {
    assert.notEqual(tokens.colors[role].dark, tokens.colors[role].light, role);
  }
  // 앱 틀 치수 (다크 시안 기준, 테두리 포함 px). 타이틀 바는 min-height 35지만 명령 검색 상자
  // (24 + 위아래 여백 5 + 테두리)로 36이 되고 아래 테두리 1을 더한다
  assert.equal(tokens.metrics["titlebar.height"], 37);
  assert.equal(tokens.metrics["statusbar.height"], 22);
  assert.equal(tokens.metrics["activitybar.width"], 49);
  assert.equal(tokens.metrics["node.header.height"], 32);
  // 에디터 탭: 시안 탭 줄이 선언한 높이 (1440 판에서 툴바 줄바꿈으로 눌린 20px가 아님)
  assert.equal(tokens.metrics["tab.height"], 35);
  assert.equal(tokens.metrics["sidebar.header.height"], 35);
  assert.equal(tokens.metrics["font.size"], 13);
  for (const [k, v] of Object.entries(tokens.metrics)) assert.ok(v > 0, k);
});

test("test_swapped_tokens_fail_role_check", () => {
  const good = tokensCss(tokens.colors);
  assert.deepEqual(checkRoleTokens(good, tokens), []);

  // 배경과 글자를 맞바꾼 사본: 두 값이 모두 시안 집합 안에 있어도 역할이 틀리면 실패
  const swapped = structuredClone(tokens.colors);
  [swapped.bg, swapped.fg] = [swapped.fg, swapped.bg];
  const problems = checkRoleTokens(tokensCss(swapped), tokens);
  assert.ok(problems.some((p) => p.startsWith(`dark ${tokenName("bg")}: #CCCCCC`)), JSON.stringify(problems));
  assert.ok(problems.some((p) => p.startsWith(`light ${tokenName("fg")}: #FFFFFF`)), JSON.stringify(problems));

  // 라이트 값만 다크에 넣은 사본
  const oneTheme = structuredClone(tokens.colors);
  oneTheme["sidebar.bg"].dark = oneTheme["sidebar.bg"].light;
  assert.deepEqual(checkRoleTokens(tokensCss(oneTheme), tokens), [
    `dark ${tokenName("sidebar.bg")}: #F8F8F8, 시안 #181818`,
  ]);

  // 토큰이 빠진 사본
  const missing = good.replace(new RegExp(`\\s*${tokenName("accent")}:[^;]+;`, "g"), "");
  assert.deepEqual(checkRoleTokens(missing, tokens), [
    `dark ${tokenName("accent")}: 없다`,
    `light ${tokenName("accent")}: 없다`,
  ]);
});

test("toHex reads computed colors", () => {
  assert.equal(toHex("rgb(31, 31, 31)"), "#1F1F1F");
  assert.equal(toHex("rgba(0, 120, 212, 0.25)"), "#0078D440");
  assert.equal(toHex("rgba(0, 0, 0, 1)"), "#000000");
  assert.equal(toHex("#abcdef"), "#ABCDEF");
  assert.throws(() => toHex("red"));
});
