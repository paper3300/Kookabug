// 시안 비교 스크린샷: 팔레트·편집 (M2 계획 T9 "시안 대비")
//   main-palette-<테마>   1440×900  vs Main·MainLight 사이드바 "노드" 섹션 (분류 점·묶음·노드 줄), 저장 안 됨 탭 ●
//   palette-drag-<테마>   1440×900  팔레트 노드를 캔버스 위로 끄는 중 (시안 없음 → 시안 언어로 그림)
//   connect-drag-<테마>   1440×900  핀을 끌어 잇는 중의 호환 표시 (시안 없음)
//   close-confirm-<테마>  1440×900  저장 안 된 그래프가 있을 때 창 닫기 확인 대화 상자 (시안 없음)
// 결과 build/ui-shots/<id>-<테마>.png → node tools/design-ref/compare.mjs main-palette palette-drag connect-drag
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "../helpers/daemon";
import { dragNode, pin, settleCanvas } from "../helpers/editor";

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
  await expect(page.getByRole("tree", { name: "노드 팔레트" }).locator("[data-node-type]").first()).toBeVisible();
}

async function shot(id: string, theme: string): Promise<void> {
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await settle(page);
  const file = path.join(OUT, `${id}-${theme}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

for (const theme of ["dark", "light"] as const) {
  test(`main-palette-${theme}`, async () => {
    await openSian(theme);
    // 시안처럼 저장 안 됨 탭(●): 노드 하나를 옮겨 둔다
    await dragNode(page, "n_record", 0, 12);
    await expect(page.locator(`[role="tab"][data-path="${GRAPH}"]`)).toHaveAttribute("data-dirty", "true");
    await page.locator(".react-flow__pane").click({ position: { x: 20, y: 20 } });
    await page.mouse.move(1, 1);
    await shot("main-palette", theme);
  });

  test(`palette-drag-${theme}`, async () => {
    await openSian(theme);
    const item = page.locator('[data-node-type="core.input.key"]');
    await item.hover();
    // 끌기 중 상태: 팔레트 노드 형식의 dragover를 캔버스에 보낸다 (놓지 않음)
    await page.evaluate(() => {
      const flow = document.querySelector(".react-flow")!;
      const r = flow.getBoundingClientRect();
      const dt = new DataTransfer();
      dt.setData("application/x-kookabug-node", "core.input.key");
      for (const type of ["dragenter", "dragover"]) {
        flow.dispatchEvent(
          new DragEvent(type, { dataTransfer: dt, bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + 300 }),
        );
      }
    });
    await expect(page.locator('[data-part="drop-zone"]')).toBeVisible();
    await shot("palette-drag", theme);
  });

  test(`connect-drag-${theme}`, async () => {
    await openSian(theme);
    // 이미지 대기의 match 출력을 끄는 중: 이을 수 있는 핀은 강조, 아닌 핀은 흐리게
    const from = pin(page, "n_wait", "o:match");
    const box = (await from.boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + 120, box.y + 140, { steps: 8 });
    await expect(page.locator('[data-compat="ok"]').first()).toBeVisible();
    await shot("connect-drag", theme);
    await page.mouse.up();
  });

  test(`close-confirm-${theme}`, async () => {
    await openSian(theme);
    // 저장 안 된 그래프가 있을 때 창 X: 앱 안 저장 확인 대화 상자 (시안 없음)
    await dragNode(page, "n_record", 0, 12);
    await page.getByRole("button", { name: "닫기", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await page.mouse.move(1, 1);
    await shot("close-confirm", theme);
  });
}
