// 플러그인 위젯 스크린샷 (M6 계획 B6 — 확정 시안 없음, 인스펙터 언어로 그림)
//   inspector-plugin-widget-<테마>     예제 플러그인 색 위젯이 인스펙터 설정 칸에 뜬 모습
//   inspector-widget-fallback-dark     위젯 세션이 끝나(재적재) 기본 편집기로 돌아간 모습
// 결과 build/ui-shots/<이름>.png (비교할 시안 PNG 없음 — 사람이 본다)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { closeApp, REPO_BUILD, setTheme, settle } from "../helpers/app";
import { cleanupWorkspace } from "../helpers/daemon";
import { openPluginApp, startWorld, stopWorld, type PluginSession, type PluginWorld } from "../helpers/plugins";
import { configField, openWidgetNode, PROBE_GRAPH, widgetBox, widgetFrame, widgetWorkspace, type WidgetWorkspace } from "../helpers/widgets";

const OUT = path.join(REPO_BUILD, "ui-shots");

let world: PluginWorld | null = null;
let wws: WidgetWorkspace | null = null;
let s: PluginSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(600_000);
  fs.mkdirSync(OUT, { recursive: true });
  world = await startWorld();
  wws = widgetWorkspace(world);
});

test.afterAll(async () => {
  if (wws !== null) await cleanupWorkspace(wws.ws);
  await stopWorld(world);
  world = null;
});

test.afterEach(async () => {
  if (s !== null) {
    await closeApp(s.app);
    fs.rmSync(s.userData, { recursive: true, force: true });
  }
  s = null;
});

async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  await page.mouse.move(2, 600);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test("widget in inspector", async () => {
  test.setTimeout(180_000);
  s = await openPluginApp(world!, wws!.ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await openWidgetNode(page, "n_color");
  await expect(widgetBox(page, "sample.color")).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(widgetFrame(page, "sample.color").getByRole("textbox", { name: "색 코드" })).toHaveValue("#3366ff");
  await shot(page, "inspector-plugin-widget-dark");
  await setTheme(page, "light");
  await page.waitForTimeout(300);
  await shot(page, "inspector-plugin-widget-light");
});

test("widget fallback", async () => {
  test.setTimeout(180_000);
  s = await openPluginApp(world!, wws!.ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await openWidgetNode(page, "n_nav", PROBE_GRAPH);
  await expect(configField(page, "result").locator('[data-part="widget-fallback"]')).toHaveAttribute("data-reason", "reloaded", {
    timeout: 20_000,
  });
  await shot(page, "inspector-widget-fallback-dark");
});
