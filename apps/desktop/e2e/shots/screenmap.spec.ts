// 화면 지도 스크린샷 (M7 B5, 시안 ScreenMap). 준비는 실제 탐색 결과(explore_world.py)
//   screenmap-<테마>          사이드바(화면 목록·선택·확인 전)·지도 탭(카드·간선·범례·확대)·상태 바
//   screenmap-promote-dark   승격 대화 상자 (확인 결과)
//   screenmap-protected-dark 보호로 스크린샷 없는 후보 선택 (판정 조건 없음 안내)
// 결과 build/ui-shots/<이름>.png → node tools/design-ref/compare.mjs screenmap, 사본 .orchestration/M7/shots/B5/
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, REPO_ROOT, setTheme, settle } from "../helpers/app";
import { candidate, card, closeMapApp, openMapApp, prepareWorld, removeWorld, showMap, type MapSession, type World } from "../helpers/screenmap";

const OUT = path.join(REPO_BUILD, "ui-shots");
const COPY = path.join(REPO_ROOT, ".orchestration", "M7", "shots", "B5");

let world: World | null = null;
let s: MapSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(() => {
  test.setTimeout(600_000);
  fs.mkdirSync(OUT, { recursive: true });
  fs.mkdirSync(COPY, { recursive: true });
  world = prepareWorld();
});

test.afterAll(() => {
  removeWorld(world);
  world = null;
});

test.afterEach(async () => {
  await closeMapApp(s);
  s = null;
});

async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  await page.mouse.move(2, 600);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  fs.copyFileSync(file, path.join(COPY, `${name}.png`));
}

for (const theme of ["dark", "light"] as const) {
  test(`screenmap ${theme}`, async () => {
    test.setTimeout(180_000);
    s = await openMapApp(world!);
    const { page } = s;
    await setTheme(page, theme);
    await showMap(page);
    const [first] = world!.sessions;
    await card(page, candidate(first, "lobby")).click();
    await expect(page.locator('[data-part="map-selected"]')).toBeVisible();
    await shot(page, `screenmap-${theme}`);
  });
}

test("screenmap promote dialog and protected card", async () => {
  test.setTimeout(180_000);
  s = await openMapApp(world!);
  const { page } = s;
  await showMap(page);
  const [first] = world!.sessions;
  await card(page, candidate(first, "loading")).click();
  await expect(page.locator('[data-part="map-detect-missing"]')).toBeVisible();
  await shot(page, "screenmap-protected-dark");
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "lobby")}"] [data-part="map-promote"]`).click();
  await expect(page.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  await shot(page, "screenmap-promote-dark");
});
