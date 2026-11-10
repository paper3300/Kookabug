// 시안 비교 스크린샷: 캔버스 (M2 계획 T8 "시안 대비")
//   main-canvas-<테마>  1440×900  vs Main·MainLight 캔버스 (노드 모양·핀·연결선·미니맵·문제 패널)
// 그래프는 e2e/fixtures/sian-main.graph.json (시안 Main의 노드 배치를 실제 노드로 옮긴 것)
// 결과 build/ui-shots/main-canvas-<테마>.png → node tools/design-ref/compare.mjs main-canvas
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "../helpers/daemon";

const OUT = path.join(REPO_BUILD, "ui-shots");
const SIAN_MAIN = path.join(import.meta.dirname, "..", "fixtures", "sian-main.graph.json");
const GRAPH = "tests/enchant_loop.graph.json";

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

for (const theme of ["dark", "light"] as const) {
  test(`main-canvas-${theme}`, async () => {
    await setTheme(page, theme);
    await setContentSize(app, page, 1440, 900);
    workspace = copySampleWorkspace("sample-rpg");
    fs.copyFileSync(SIAN_MAIN, path.join(workspace, ...GRAPH.split("/")));
    await stubOpenDialog(app, workspace);
    await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
    await waitConnected(page);
    await page.getByRole("tree", { name: "워크스페이스 파일" }).locator(`[data-path="${GRAPH}"]`).click();
    await expect(page.locator(".react-flow__node")).toHaveCount(10);
    // 흐름 9 + 데이터 2 (배열 안 $link 둘)
    await expect(page.locator(".react-flow__edge")).toHaveCount(11);
    await page.getByRole("tab", { name: /문제/ }).click();
    await expect(page.getByRole("list", { name: "문제 목록" })).toBeVisible();
    await page.mouse.move(1, 1);
    await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
    await settle(page);
    const file = path.join(OUT, `main-canvas-${theme}.png`);
    await page.screenshot({ path: file });
    expect(fs.statSync(file).size).toBeGreaterThan(0);
  });
}
