// 패널 배치: 왼쪽 사이드바·오른쪽 패널 폭 끌기·두 번 눌러 기본 폭·좁게 끌어 접기, 액티비티 아이콘·Ctrl+B 접기,
// 다시 띄워도 배치 기억 (Resizer.tsx, store/ui.ts, 앱 설정 settings.json의 layout)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { closeApp } from "./helpers/app";
import { openGraph } from "./helpers/editor";
import { closeRunApp, INVENTORY, openRunApp, prepareRunWorkspace, type RunSession } from "./helpers/run";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

async function width(el: Locator): Promise<number> {
  return Math.round((await el.boundingBox())?.width ?? 0);
}

async function dragBy(page: Page, handle: Locator, dx: number): Promise<void> {
  const box = await handle.boundingBox();
  if (box === null) throw new Error("손잡이가 안 보인다");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx / 2, y, { steps: 4 });
  await page.mouse.move(x + dx, y, { steps: 4 });
  await page.mouse.up();
}

test("sidebar and right panel resize, reset, collapse and remember layout", async () => {
  s = await openRunApp(prepareRunWorkspace());
  const { page } = s;
  // 프로젝트를 열자마자(탭 없음) 오른쪽 패널이 보인다
  await expect(page.locator('[data-part="inspector"][data-open="true"]')).toBeVisible();
  await openGraph(page, INVENTORY);
  const sidebar = page.locator('[data-part="sidebar-box"]');
  const inspector = page.locator('[data-part="inspector"][data-open="true"]');
  const sideHandle = sidebar.getByRole("separator", { name: "사이드바 폭" });
  const rightHandle = inspector.getByRole("separator", { name: "오른쪽 패널 폭" });
  expect(await width(sidebar)).toBe(250);
  expect(await width(inspector)).toBe(321);

  // 끌어서 넓히기 → 두 번 눌러 기본 폭
  await dragBy(page, sideHandle, 100);
  expect(await width(sidebar)).toBe(350);
  await dragBy(page, rightHandle, -80);
  expect(await width(inspector)).toBe(401);
  await sideHandle.dblclick();
  expect(await width(sidebar)).toBe(250);

  // 액티비티 아이콘: 지금 보기를 다시 누르면 접고, 다시 누르면 펼친다. Ctrl+B도 같다
  const explorer = page.getByRole("button", { name: "탐색기" });
  await explorer.click();
  await expect(sidebar).toHaveCount(0);
  await expect(explorer).toHaveAttribute("aria-pressed", "false");
  await explorer.click();
  await expect(sidebar).toBeVisible();
  await page.locator('[data-part="canvas"]').click({ position: { x: 20, y: 20 } });
  await page.keyboard.press("Control+b");
  await expect(sidebar).toHaveCount(0);
  await page.keyboard.press("Control+b");
  await expect(sidebar).toBeVisible();

  // 최소 폭의 절반보다 좁게 끌어 놓으면 접힌다 (오른쪽 패널은 접힌 띠로)
  await dragBy(page, rightHandle, 400);
  await expect(page.locator('[data-part="inspector"][data-open="false"]')).toBeVisible();
  await page.getByRole("button", { name: "속성 패널 펼치기" }).click();
  expect(await width(inspector)).toBe(401);

  // 다시 띄워도 배치가 남는다
  const userData = s.userData;
  const ws = s.ws;
  const settingsFile = path.join(userData, "settings.json");
  await expect
    .poll(() => (fs.existsSync(settingsFile) ? (JSON.parse(fs.readFileSync(settingsFile, "utf8")) as { layout?: { inspectorWidth?: number } }).layout?.inspectorWidth : null))
    .toBe(400);
  await closeApp(s.app); // userData·워크스페이스는 남긴다
  s = await openRunApp(ws, { userData });
  await openGraph(s.page, INVENTORY);
  expect(await width(s.page.locator('[data-part="inspector"][data-open="true"]'))).toBe(401);
  expect(await width(s.page.locator('[data-part="sidebar-box"]'))).toBe(250);
});
