// 앱 틀 치수·역할 색·글꼴이 시안과 같은지 (M2 계획 2.12, 검수 M10). 기준은 시안에서 뽑은
// build/design-ref/tokens.json (node tools/design-ref/extract.mjs)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { tokenName, toHex, type RoleTokens } from "../../../tools/design-ref/tokens-check.mjs";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./helpers/daemon";

const TOKENS_JSON = path.join(REPO_BUILD, "design-ref", "tokens.json");

function sian(): RoleTokens {
  if (!fs.existsSync(TOKENS_JSON)) throw new Error(`${TOKENS_JSON} 이 없다 (node tools/design-ref/extract.mjs)`);
  return JSON.parse(fs.readFileSync(TOKENS_JSON, "utf8")) as RoleTokens;
}

interface Rule {
  selector: string;
  /** 자기 글자에 이 글자가 든 첫 요소 */
  text?: string;
  prop: string;
}

/** 역할 → 앱 요소. 시안 roles.json의 같은 역할을 앱에서 찾는 표 */
const WELCOME_ROLES: Record<string, Rule> = {
  "welcome.bg": { selector: '[data-screen="welcome"]', prop: "background-color" },
  "welcome.title.fg": { selector: '[data-screen="welcome"] h1', prop: "color" },
  "welcome.text.fg": { selector: '[data-screen="welcome"] p', prop: "color" },
  "welcome.toggle.bg": { selector: '[role="group"][aria-label="테마"]', prop: "background-color" },
  "welcome.toggle.fg": { selector: '[aria-label="테마"] button[aria-pressed="false"]', prop: "color" },
  "welcome.toggle.active.bg": { selector: '[aria-label="테마"] button[aria-pressed="true"]', prop: "background-color" },
  "welcome.toggle.active.fg": { selector: '[aria-label="테마"] button[aria-pressed="true"]', prop: "color" },
  "button.primary.bg": { selector: "button", text: "프로젝트 열기", prop: "background-color" },
  "button.primary.fg": { selector: "button", text: "프로젝트 열기", prop: "color" },
  "chip.graph.bg": { selector: "span", text: "노드 그래프", prop: "background-color" },
  "chip.graph.fg": { selector: "span", text: "노드 그래프", prop: "color" },
  "chip.record.bg": { selector: "span", text: "녹화", prop: "background-color" },
  "chip.record.fg": { selector: "span", text: "녹화", prop: "color" },
  "chip.agent.bg": { selector: "span", text: "에이전트", prop: "background-color" },
  "chip.agent.fg": { selector: "span", text: "에이전트", prop: "color" },
};

const SHELL_ROLES: Record<string, Rule> = {
  bg: { selector: '[data-screen="shell"]', prop: "background-color" },
  fg: { selector: '[data-screen="shell"]', prop: "color" },
  "fg.muted": { selector: '[data-part="panel-tabs"] [aria-selected="false"]', prop: "color" },
  border: { selector: '[data-part="titlebar"]', prop: "border-bottom-color" },
  accent: { selector: 'nav[aria-label="작업 영역"] button[aria-pressed="true"]', prop: "border-left-color" },
  "titlebar.bg": { selector: '[data-part="titlebar"]', prop: "background-color" },
  "titlebar.fg": { selector: 'nav[aria-label="메뉴"] button', prop: "color" },
  "titlebar.search.bg": { selector: '[data-part="titlebar"] button[aria-label="파일 빠른 열기"]', prop: "background-color" },
  "activitybar.bg": { selector: 'nav[aria-label="작업 영역"]', prop: "background-color" },
  "activitybar.active.fg": { selector: 'nav[aria-label="작업 영역"] button[aria-pressed="true"]', prop: "color" },
  "sidebar.bg": { selector: 'aside[aria-label="사이드바"]', prop: "background-color" },
  "sidebar.fg": { selector: '[data-part="sidebar-header"]', prop: "color" },
  "input.bg": { selector: 'section[aria-label="노드"] label', prop: "background-color" },
  "input.border": { selector: 'section[aria-label="노드"] label', prop: "border-top-color" },
  "tabs.bg": { selector: '[data-part="tabs"]', prop: "background-color" },
  "tab.active.bg": { selector: '[data-part="tabs"] [role="tab"][aria-selected="true"]', prop: "background-color" },
  "tab.active.fg": { selector: '[data-part="tabs"] [role="tab"][aria-selected="true"]', prop: "color" },
  "tab.inactive.fg": { selector: '[data-part="tabs"] [role="tab"][aria-selected="false"]', prop: "color" },
  "editor.bg": { selector: '[data-part="canvas"]', prop: "background-color" },
  "node.bg": { selector: '[data-part="node"]', prop: "background-color" },
  "panel.bg": { selector: 'section[aria-label="하단 패널"]', prop: "background-color" },
  "list.active.bg": { selector: '[role="treeitem"][aria-selected="true"]', prop: "background-color" },
  "list.active.fg": { selector: '[role="treeitem"][aria-selected="true"]', prop: "color" },
  "kind.test": { selector: '[data-part="tabs"] span', text: "TEST", prop: "color" },
  "kind.target": { selector: '[data-part="tabs"] span', text: "TARGET", prop: "color" },
};

function readRules(rules: Record<string, Rule>): Record<string, string | null> {
  const ownText = (el: Element) =>
    [...el.childNodes]
      .filter((n) => n.nodeType === Node.TEXT_NODE)
      .map((n) => (n as Text).data)
      .join("")
      .trim();
  const out: Record<string, string | null> = {};
  for (const [role, rule] of Object.entries(rules)) {
    const el = [...document.querySelectorAll(rule.selector)].find(
      (e) => rule.text === undefined || ownText(e).includes(rule.text),
    );
    out[role] = el ? getComputedStyle(el).getPropertyValue(rule.prop) : null;
  }
  return out;
}

async function colorsOf(page: Page, rules: Record<string, Rule>): Promise<Record<string, string>> {
  const raw = await page.evaluate(readRules, rules);
  return Object.fromEntries(
    Object.entries(raw).map(([role, v]) => {
      if (v === null) throw new Error(`앱에서 역할 요소를 찾지 못했다: ${role} (${rules[role].selector})`);
      return [role, toHex(v)];
    }),
  );
}

let app: ElectronApplication;
let page: Page;
let userData: string;
let workspace: string | null = null;

test.afterEach(async () => {
  await closeApp(app);
  if (workspace !== null) await cleanupWorkspace(workspace);
  workspace = null;
  if (userData) fs.rmSync(userData, { recursive: true, force: true });
});

async function start(): Promise<void> {
  ({ app, userData } = await launchApp({ scaleFactor: 1 }));
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
}

/** 워크스페이스를 열고 시안처럼 탭 둘(테스트·target)과 고른 줄을 만든다 */
async function openShell(): Promise<void> {
  workspace = copySampleWorkspace();
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  await tree.locator('[data-path="targets"]').click();
  await tree.locator('[data-path="targets/title"]').click();
  await tree.locator('[data-path="targets/title/start_button.target.json"]').click();
  await tree.locator('[data-path="tests/inventory_open.graph.json"]').click();
  await expect(page.locator('[data-part="tabs"] [role="tab"]')).toHaveCount(2);
}

test("test_shell_metrics_match_sian", async () => {
  const metrics = sian().metrics;
  await start();
  await setContentSize(app, page, 1440, 900);
  await openShell();
  await expect(page.locator('[data-part="node-head"]').first()).toBeVisible();
  await settle(page);
  const got = await page.evaluate(() => {
    const el = (s: string) => document.querySelector(s) as HTMLElement;
    const px = (s: string, prop: string) => Number.parseFloat(getComputedStyle(el(s)).getPropertyValue(prop));
    return {
      "titlebar.height": el('[data-part="titlebar"]').offsetHeight,
      "breadcrumb.height": el('[data-part="breadcrumb"]').offsetHeight,
      "statusbar.height": el('[data-part="statusbar"]').offsetHeight,
      "activitybar.width": el('nav[aria-label="작업 영역"]').offsetWidth,
      "sidebar.width": el('[data-part="sidebar"]').offsetWidth,
      "sidebar.header.height": el('[data-part="sidebar-header"]').offsetHeight,
      "panel.tabs.height": el('[data-part="panel-tabs"]').offsetHeight,
      // 에디터 탭 하나의 높이 (탭 줄 아래 테두리 제외). 시안 값은 탭 줄이 선언한 높이 (roles.json 설명)
      "tab.height": el('[data-part="tabs"] [role="tab"]').offsetHeight,
      "font.size": px('[data-screen="shell"]', "font-size"),
      "font.size.small": px('[data-part="sidebar-header"]', "font-size"),
      // 캔버스 노드 머리 (T8). 화면 배율과 무관한 배치 크기
      "node.header.height": el('[data-part="node-head"]').offsetHeight,
    };
  });
  // 시안 치수 역할을 빠짐없이 잰다
  expect(Object.keys(got).sort()).toEqual(Object.keys(metrics).sort());
  for (const [role, value] of Object.entries(got)) {
    expect(metrics[role], role).toBeDefined();
    expect(Math.abs(value - metrics[role]), `${role}: 앱 ${value}, 시안 ${metrics[role]}`).toBeLessThanOrEqual(1);
  }
});

for (const theme of ["dark", "light"] as const) {
  test(`test_computed_role_colors_match_sian[${theme}]`, async () => {
    const tokens = sian();
    const want = (role: string) => tokens.colors[role][theme];
    await start();
    await setTheme(page, theme);
    await settle(page);
    const checked = new Set<string>();
    const welcome = await colorsOf(page, WELCOME_ROLES);
    for (const [role, hex] of Object.entries(welcome)) {
      expect(hex, `${theme} ${role}`).toBe(want(role));
      checked.add(role);
    }
    await openShell();
    await settle(page);
    const shell = await colorsOf(page, SHELL_ROLES);
    for (const [role, hex] of Object.entries(shell)) {
      expect(hex, `${theme} ${role}`).toBe(want(role));
      checked.add(role);
    }
    // T7 화면에 아직 요소가 없는 역할(실행 상태 바·노드·실행 로그 색·링크)은 계산된 변수 값으로 본다
    const rest = Object.keys(tokens.colors).filter((r) => !checked.has(r));
    expect(rest.length).toBeLessThan(Object.keys(tokens.colors).length / 2);
    // 변수를 실제 요소 색으로 칠해 계산된 값으로 읽는다 (변수 원문 표기와 무관하게)
    const vars = await page.evaluate((names) => {
      const probe = document.createElement("span");
      document.body.append(probe);
      const out = names.map((n) => {
        probe.style.color = `var(${n})`;
        return getComputedStyle(probe).color;
      });
      probe.remove();
      return out;
    }, rest.map(tokenName));
    rest.forEach((role, i) => expect(toHex(vars[i]), `${theme} ${role}`).toBe(want(role)));
  });
}

test("test_fonts_loaded_and_used", async () => {
  await start();
  await settle(page);
  const fontInfo = (selector: string, text?: string) =>
    page.evaluate(
      async ([sel, txt]) => {
        const el = [...document.querySelectorAll(sel)].find((e) => txt === undefined || e.textContent?.includes(txt));
        if (!el) return null;
        const style = getComputedStyle(el);
        const first = style.fontFamily.split(",")[0].trim().replace(/^["']|["']$/g, "");
        await document.fonts.load(`${style.fontWeight} ${style.fontSize} "${first}"`, el.textContent ?? "가A");
        const loaded = [...document.fonts].some((f) => f.family.replace(/["']/g, "") === first && f.status === "loaded");
        return { first, loaded };
      },
      [selector, text] as const,
    );
  // 시작 화면 워드마크 = Fraunces, 본문 = Noto Sans KR
  expect(await fontInfo('[data-screen="welcome"] span', "Kookabug")).toEqual({ first: "Fraunces", loaded: true });
  expect(await fontInfo('[data-screen="welcome"] h1')).toEqual({ first: "Noto Sans KR", loaded: true });
  await openShell();
  await settle(page);
  expect(await fontInfo('[data-screen="shell"] [data-part="sidebar-header"]')).toEqual({
    first: "Noto Sans KR",
    loaded: true,
  });
  // 고정폭 = JetBrains Mono (출력 패널)
  expect(await fontInfo('[role="tabpanel"][aria-label="출력"] span', "daemon")).toEqual({
    first: "JetBrains Mono",
    loaded: true,
  });
  // 앱이 인터넷에서 글꼴을 받지 않는다: 모든 @font-face 출처가 앱 안 상대 경로(app://)
  const sources = await page.evaluate(() =>
    [...document.styleSheets].flatMap((sheet) =>
      [...sheet.cssRules]
        .filter((r): r is CSSFontFaceRule => r instanceof CSSFontFaceRule)
        .map((r) => new URL(/url\("?([^")]+)"?\)/.exec(r.style.getPropertyValue("src"))![1], sheet.href ?? location.href).href),
    ),
  );
  expect(sources.length).toBeGreaterThan(0);
  for (const s of sources) expect(s.startsWith("app://app/")).toBe(true);
});
