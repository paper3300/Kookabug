// 화면 지도 뷰어 (M7 계획 3.14·B5). 준비는 실제 탐색 결과(explore_world.py: 가짜 예제 게임 + 실제 MCP·daemon·
// runner로 가짜 탐색 에이전트 각본 → 사람 CLI 승격(title) → 다시 탐색(title 합치기 후보))다. 선작성·모킹 없음.
// 지도·간선·색·점선·선택 상세·보호로 스크린샷 없는 카드·승격 → 파일·실패 문구·합치기·버리기·탐색기 → 카드·
// 자리 기억·저장 안 한 그래프 탭 유지
import { showActivity } from "./helpers/app";
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { dragNode, filePath, nodeIds, openGraph, readBytes, tabOf } from "./helpers/editor";
import {
  candidate,
  card,
  closeMapApp,
  openMapApp,
  prepareWorld,
  removeWorld,
  showMap,
  type MapSession,
  type World,
} from "./helpers/screenmap";

let world: World | null = null;
let s: MapSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(600_000);
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

function w(): World {
  if (world === null) throw new Error("탐색 결과가 없다");
  return world;
}

const GRAPH = "tests/inventory_open.graph.json";

test("map shows explored cards, edges, source colors, selection and protected cards", async () => {
  test.setTimeout(180_000);
  s = await openMapApp(w());
  const { page } = s;
  const [first, second] = w().sessions;
  const map = await showMap(page);
  // 확정 1(title) + 1차 탐색 후보 6, 합치기 후보(title_again)는 카드가 아니라 배지
  await expect(map.locator('[data-part="map-card"]')).toHaveCount(7);
  await expect(card(page, "title").locator('[data-part="map-card-meta"]')).toContainText("탐색 추가 1");
  // 처음 보기: 화면에 맞춤 — 1440×900에서 카드 7개가 잘리지 않고 가로 스크롤이 없다 (B5 검수 Low 3)
  const canvas = map.locator('[data-part="map-canvas"]');
  const view = (await canvas.boundingBox())!;
  for (const box of await map.locator('[data-part="map-card"]').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().toJSON() as DOMRect))) {
    expect(box.right).toBeLessThanOrEqual(view.x + view.width + 1);
    expect(box.bottom).toBeLessThanOrEqual(view.y + view.height + 1);
  }
  expect(await canvas.evaluate((el) => el.scrollWidth <= el.clientWidth)).toBe(true);
  await expect(card(page, candidate(first, "lobby"))).toHaveAttribute("data-state", "explored");
  await expect(map.locator('[data-part="map-edge"]').first()).toBeAttached();
  expect(await map.locator('[data-part="map-edge"]').count()).toBeGreaterThanOrEqual(5);
  // 범례는 있는 출처만 (Agent 탐색), 점 색은 시안 보라
  await expect(map.locator('[data-part="map-legend"]')).toHaveCount(1);
  const dot = map.locator('[data-part="map-legend"][data-source="explored"] span').first();
  expect(await dot.evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(197, 179, 235)");
  // 후보는 점선 테두리
  expect(await card(page, candidate(first, "lobby")).evaluate((el) => getComputedStyle(el).borderTopStyle)).toBe("dashed");
  // 보호 중 저장된 후보(로딩·인벤토리): 스크린샷 없음 + 판정 조건 없음
  const loading = card(page, candidate(first, "loading"));
  await expect(loading.locator('[data-part="map-thumb"]')).toHaveAttribute("data-has-thumb", "false");
  await expect(loading).toContainText("보호로 스크린샷 없음");
  await expect(loading.locator('[data-part="map-card-meta"]')).toContainText("판정 조건 없음");
  // 썸네일 있는 카드는 편집기 캐시 PNG
  const thumb = card(page, candidate(first, "lobby")).locator("img");
  await expect(thumb).toHaveAttribute("src", /^kbimg:\/\/cache\/map_[0-9a-f]+\.png$/);
  await expect.poll(() => thumb.evaluate((img) => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0);
  // 선택: 파란 테두리, 걸린 간선은 파랑, 사이드바 상세
  await loading.click();
  await expect(loading).toHaveAttribute("data-selected", "true");
  const side = page.locator('[data-part="map-selected"]');
  await expect(side).toHaveAttribute("data-node", candidate(first, "loading"));
  await expect(side.locator('[data-part="map-detect-missing"]')).toBeVisible();
  await expect(side.locator('[data-part="map-selected-shot"]')).toContainText("보호로 스크린샷 없음");
  await card(page, candidate(first, "lobby")).click();
  await expect(side.locator('[data-part="map-detect"]')).toContainText(/image\(|text\(/);
  await expect(map.locator('[data-part="map-edge"][data-active="true"]').first()).toBeAttached();
  // 확인 전: 세션 두 개, 판정 조건 없는 후보는 옮기기 꺼짐, 합치기 후보
  await expect(page.locator(`[data-part="map-pending"][data-session="${first}"]`)).toBeVisible();
  await expect(page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "loading")}"] [data-part="map-promote"]`)).toBeDisabled();
  await expect(page.locator(`[data-part="map-merge"][data-node="${candidate(second, "title_again")}"]`)).toBeVisible();
  // 상태 바 (지도 탭 앞)
  await expect(page.locator('[data-part="map-counts"]')).toContainText("화면 7");
});

test("promote, merge, discard and failure keep files consistent", async () => {
  test.setTimeout(180_000);
  s = await openMapApp(w());
  const { page, workspace } = s;
  const [first, second] = w().sessions;
  await showMap(page);
  const dialog = page.locator('[data-part="promote-dialog"]');
  // 옮기기: lobby → screens/lobby.screen.json
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "lobby")}"] [data-part="map-promote"]`).click();
  await expect(dialog).toHaveAttribute("data-mode", "new");
  await expect(dialog.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  await dialog.locator('[data-part="promote-submit"]').click();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('[data-part="map-notice"]')).toContainText("옮겼어요");
  expect(fs.existsSync(filePath(workspace, "screens/lobby.screen.json"))).toBe(true);
  expect(fs.existsSync(filePath(workspace, `screens/_explored/${first}/lobby.screen.json`))).toBe(false);
  await expect(card(page, "lobby")).toHaveAttribute("data-selected", "true");
  // 합치기: title_again → title (이동 하나 더함)
  await page.locator(`[data-part="map-merge"][data-node="${candidate(second, "title_again")}"] [data-part="map-merge-open"]`).click();
  await expect(dialog).toHaveAttribute("data-mode", "merge");
  await expect(dialog.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  await dialog.locator('[data-part="promote-submit"]').click();
  await expect(dialog).toHaveCount(0);
  const title = JSON.parse(readBytes(workspace, "screens/title.screen.json").toString("utf8")) as { moves: { note?: string }[] };
  expect(title.moves.some((m) => m.note === "도움말 창")).toBe(true);
  await expect(page.locator(`[data-part="map-merge"]`)).toHaveCount(0);
  // 버리기: login_error 후보 파일이 사라진다
  const errorCard = `screens/_explored/${first}/login_error.screen.json`;
  expect(fs.existsSync(filePath(workspace, errorCard))).toBe(true);
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "login_error")}"] [data-part="map-discard"]`).click();
  await expect(card(page, candidate(first, "login_error"))).toHaveCount(0);
  expect(fs.existsSync(filePath(workspace, errorCard))).toBe(false);
  // 실패: 확인한 뒤 후보가 바뀌면 옮기지 않고 기존 파일은 그대로
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "world")}"] [data-part="map-promote"]`).click();
  await expect(dialog.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  const worldCard = filePath(workspace, `screens/_explored/${first}/world.screen.json`);
  fs.writeFileSync(worldCard, `${fs.readFileSync(worldCard, "utf8")}\n`);
  const before = fs.readFileSync(worldCard);
  await dialog.locator('[data-part="promote-submit"]').click();
  await expect(dialog.locator('[data-part="promote-failed"]')).toContainText("옮기지 못했어요. 기존 파일은 그대로예요.");
  expect(fs.existsSync(filePath(workspace, "screens/world.screen.json"))).toBe(false);
  expect(fs.readFileSync(worldCard).equals(before)).toBe(true);
});

test("explorer selects card, layout is remembered, unsaved graph tab stays", async () => {
  test.setTimeout(180_000);
  s = await openMapApp(w());
  const { page, workspace } = s;
  const [first] = w().sessions;
  // 저장 안 한 그래프 탭
  await openGraph(page, GRAPH);
  const graphBefore = readBytes(workspace, GRAPH);
  const [someNode] = await nodeIds(page);
  await dragNode(page, someNode!, 40, 20);
  await expect(tabOf(page, GRAPH)).toHaveAttribute("data-dirty", "true");
  // 탐색기 → 지도 탭에서 그 카드 선택
  await showActivity(page.getByRole("button", { name: "탐색기" }));
  const tree = page.locator('[role="tree"]');
  const dir = tree.locator('[data-path="screens"]');
  if ((await dir.getAttribute("aria-expanded")) === "false") await dir.click();
  await tree.locator('[data-path="screens/title.screen.json"]').click();
  await expect(page.locator('[data-part="tabs"] [role="tab"][aria-selected="true"]')).toHaveAttribute("data-kind", "MAP");
  await expect(card(page, "title")).toHaveAttribute("data-selected", "true");
  // 자리 기억: 카드를 끌면 .kookabug/screen-map.json에 남고, 탭을 닫았다 열어도 그 자리
  const lobby = card(page, candidate(first, "lobby"));
  const box = (await lobby.boundingBox())!;
  await page.mouse.move(box.x + 40, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + 140, box.y + box.height / 2 + 60, { steps: 8 });
  await page.mouse.up();
  const left = await lobby.evaluate((el) => (el as HTMLElement).style.left);
  expect(left).not.toBe("660px"); // 자동 배치 자리에서 옮겨졌다
  await expect
    .poll(() => {
      const file = filePath(workspace, ".kookabug/screen-map.json");
      return fs.existsSync(file) ? (JSON.parse(fs.readFileSync(file, "utf8")) as { layout: { positions: Record<string, unknown> } }).layout.positions[candidate(first, "lobby")] !== undefined : false;
    })
    .toBe(true);
  await page.locator('[role="tab"][data-kind="MAP"] button[aria-label="탭 닫기"]').click();
  await showActivity(page.locator('[data-part="activity-screens"]'));
  await page.locator('[data-part="map-row"]').first().click();
  await expect(card(page, candidate(first, "lobby"))).toHaveAttribute("style", new RegExp(`left: ${left}`));
  // 승격해도 열린 그래프 탭(저장 안 함)과 그 파일은 그대로
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "world")}"] [data-part="map-promote"]`).click();
  const dialog = page.locator('[data-part="promote-dialog"]');
  await expect(dialog.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  await dialog.locator('[data-part="promote-submit"]').click();
  await expect(dialog).toHaveCount(0);
  expect(fs.existsSync(filePath(workspace, "screens/world.screen.json"))).toBe(true);
  await expect(tabOf(page, GRAPH)).toHaveAttribute("data-dirty", "true");
  expect(readBytes(workspace, GRAPH).equals(graphBefore)).toBe(true);
});
