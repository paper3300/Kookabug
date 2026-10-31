// 시안 비교 스크린샷: 속성 편집기 (M2 계획 T10 "시안 대비"). 속성 편집기는 시안에 없는 화면이다(U1): 시안 Main의
// 에이전트 패널 자리(오른쪽)에 사이드바와 같은 섹션 머리·입력 상자 모양으로 그렸는지 나란히 본다
//   inspector-<테마>       1440×900  이미지 클릭 노드(대상 고르기·선택 상자·숫자 상자, 틀린 값 알림)
//   inspector-link-<테마>  1440×900  변수 저장 노드(안쪽 연결이 든 값·한 줄 상자)
// 결과 build/ui-shots/<id>-<테마>.png → node tools/design-ref/compare.mjs inspector inspector-link
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "../helpers/daemon";
import { selectOnly, settleCanvas } from "../helpers/editor";

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

async function openSian(theme: "dark" | "light"): Promise<void> {
  await setTheme(page, theme);
  await setContentSize(app, page, 1440, 900);
  workspace = copySampleWorkspace("sample-rpg");
  fs.copyFileSync(SIAN_MAIN, path.join(workspace, ...GRAPH.split("/")));
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  await page.getByRole("tree", { name: "워크스페이스 파일" }).locator(`[data-path="${GRAPH}"]`).click();
  await expect(page.locator(".react-flow__node")).toHaveCount(10);
  await settleCanvas(page);
}

async function shot(id: string, theme: string): Promise<void> {
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await settle(page);
  const file = path.join(OUT, `${id}-${theme}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

const body = () => page.locator('[data-part="inspector-body"]');

for (const theme of ["dark", "light"] as const) {
  test(`inspector-${theme}`, async () => {
    await openSian(theme);
    await selectOnly(page, "n_click");
    await expect(body()).toHaveAttribute("data-node", "n_click");
    // 틀린 값 알림 상태: 클릭 횟수 0 (최솟값 1)
    await body().getByRole("textbox", { name: "count", exact: true }).fill("0");
    await expect(body().locator('[data-part="field-error"]')).toBeVisible();
    await page.mouse.move(1, 1);
    await shot("inspector", theme);
  });

  test(`inspector-link-${theme}`, async () => {
    await openSian(theme);
    await selectOnly(page, "n_record");
    await expect(body()).toHaveAttribute("data-node", "n_record");
    await expect(body().locator('[data-part="linked-inside"]')).toBeVisible();
    await page.getByRole("tab", { name: "노드 결과" }).click();
    await page.mouse.move(1, 1);
    await shot("inspector-link", theme);
  });
}
