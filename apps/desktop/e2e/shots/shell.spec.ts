// 시안 비교 스크린샷 (M2 계획 2.12 "앱 스크린샷"): 시안과 같은 viewport·배율 1·테마로 찍는다.
//   welcome-<테마>      1120×720  vs Setup0Welcome(·Light)
//   shell-empty-<테마>  1440×900  vs Main·MainLight (캔버스 내용 제외 틀)
// 결과 build/ui-shots/<id>-<테마>.png → node tools/design-ref/compare.mjs welcome shell-empty
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "../helpers/daemon";

const OUT = path.join(REPO_BUILD, "ui-shots");

let app: ElectronApplication;
let page: Page;
let userData: string;
let workspace: string | null = null;

test.beforeEach(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  ({ app, userData } = await launchApp({ scaleFactor: 1 }));
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
});

test.afterEach(async () => {
  await closeApp(app);
  if (workspace !== null) await cleanupWorkspace(workspace);
  workspace = null;
  fs.rmSync(userData, { recursive: true, force: true });
});

async function shoot(id: string): Promise<void> {
  // 커서·깜빡이는 캐럿이 비교를 흐리지 않게
  await page.mouse.move(1, 1);
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await settle(page);
  const file = path.join(OUT, `${id}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

for (const theme of ["dark", "light"] as const) {
  test(`welcome-${theme}`, async () => {
    await setTheme(page, theme);
    await setContentSize(app, page, 1120, 720);
    await expect(page.locator('[data-screen="welcome"]')).toBeVisible();
    await shoot(`welcome-${theme}`);
  });

  test(`shell-empty-${theme}`, async () => {
    await setTheme(page, theme);
    await setContentSize(app, page, 1440, 900);
    workspace = copySampleWorkspace("sample-rpg");
    await stubOpenDialog(app, workspace);
    await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
    await waitConnected(page);
    const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
    // 시안 Main처럼 tests를 펼치고 테스트 하나를 탭으로 연다
    await tree.locator('[data-path="tests/broken"]').click();
    await tree.locator('[data-path="tests/inventory_open.graph.json"]').click();
    await expect(page.locator('[data-part="tabs"] [role="tab"]')).toHaveCount(1);
    await expect(page.locator('[data-part="statusbar"]')).toContainText("Python");
    await shoot(`shell-empty-${theme}`);
  });
}
