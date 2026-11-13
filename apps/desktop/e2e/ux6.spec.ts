// UX6 E2E: 고른 것의 정보·동작은 모든 경우 오른쪽 속성 탭. 실제 앱 + 실제 daemon(가짜 플랫폼·예제 장면).
// - RUN 스텝 → 속성 탭 스크린샷·크게 보기, 그래프 노드 → "마지막 실행 결과", 폭은 탭 종류별로 기억·창 폭 50% 상한
// - target 영역 → 속성 탭 (매칭 미리보기·클릭 지점)
// - 녹화 스텝 → 속성 탭 비밀값/일반 전환
// - 보고함 작업 → 속성 탭 수락
// 모두 접힌 속성 창에서 시작해 고르면 펴지는지 본다. 샷: build/e2e/ux6-shots (사용자가 본다)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, waitConnected } from "./helpers/daemon";
import { openGraph, tabOf } from "./helpers/editor";
import { clickRun, closeRunApp, openRunApp, prepareRunWorkspace, runNode, toolbar, waitEnded, type RunSession } from "./helpers/run";
import { runEnd, runItem, runTab, showRunList, timelineRow, VIEWER_FAIL, writeViewerGraphs } from "./helpers/runs";
import { openRecorderApp, prepareRecorderWorkspace, startLaunch, stopRecording, waitLoginRecorded } from "./helpers/recorder";
import { cleanupShopWorld, prepareShopWorld, readBytes, runAgentJob, runCli, type ShopWorld } from "./helpers/reports";
import { addCapture, editorOf, loadFrame, openTarget, selectRect, START_BUTTON } from "./helpers/target";
import type { ElectronApplication } from "@playwright/test";

const SHOTS = path.join(REPO_BUILD, "e2e", "ux6-shots");

let s: RunSession | null = null;
let app: ElectronApplication | null = null;
let world: ShopWorld | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
  await closeApp(app ?? undefined);
  app = null;
  if (world !== null) await cleanupWorkspace(world.root);
  cleanupShopWorld(world);
  world = null;
});

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

function inspector(page: Page): Locator {
  return page.locator('[data-part="inspector"]');
}

/** 속성 창을 접어 두고 시작한다 (고르면 펴져야 한다) */
async function collapse(page: Page): Promise<void> {
  await page.getByRole("button", { name: "속성 패널 접기" }).click();
  await expect(inspector(page)).toHaveAttribute("data-open", "false");
}

async function expectPropsOpen(page: Page): Promise<void> {
  await expect(inspector(page)).toHaveAttribute("data-open", "true");
  await expect(inspector(page)).toHaveAttribute("data-tab", "props");
}

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

test("RUN 스텝 → 속성 탭 스크린샷·크게 보기 · 노드 → 마지막 실행 결과 · 폭 탭별 기억", async () => {
  test.setTimeout(300_000);
  const ws = prepareRunWorkspace();
  writeViewerGraphs(ws);
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, VIEWER_FAIL);
  await clickRun(page);
  await waitEnded(page, "fail", 120_000);
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;

  // 노드 → 속성 탭 "마지막 실행 결과" (하단 패널 "노드 결과" 탭은 없다)
  await collapse(page);
  await runNode(page, "n_call").click();
  await expectPropsOpen(page);
  const result = inspector(page).locator('[data-part="node-last-result"] [data-part="node-result"][data-node="n_call"]');
  await expect(result.locator('[data-part="node-result-status"]')).toHaveAttribute("data-status", "fail");
  await expect(page.getByRole("tab", { name: "노드 결과" })).toHaveCount(0);

  // RUN 탭: 타임라인만, 스텝을 고르면 접힌 속성 창이 펴지고 증거가 속성 탭에
  await collapse(page);
  await showRunList(page);
  await runItem(page, runId).click();
  await expect(runTab(page, runId)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
  const failure = runEnd(ws, runId).failure_step as string;
  await timelineRow(page, failure).click();
  await expectPropsOpen(page);
  const evidence = inspector(page).locator(`[data-part="evidence"][data-step="${failure}"]`);
  const image = evidence.locator('[data-part="shot-image"]').first();
  await expect(image).toHaveJSProperty("complete", true, { timeout: 30_000 });
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('[data-part="run-tab"] [data-part="evidence"]')).toHaveCount(0);
  // 스크린샷은 패널 폭에 맞춘다
  expect(await width(image)).toBeLessThanOrEqual(await width(inspector(page)));
  await shot(page, "run");

  // 크게 보기: 앱 안 큰 보기 → Esc로 닫기
  await evidence.locator('[data-part="shot-zoom"]').first().click();
  const big = page.locator('[data-part="media-big"]');
  await expect(big).toBeVisible();
  const bigImage = big.locator('[data-part="shot-image"]');
  await expect(bigImage).toHaveJSProperty("complete", true);
  expect(await width(bigImage)).toBeGreaterThan(await width(inspector(page)));
  await shot(page, "run-big");
  await page.keyboard.press("Escape");
  await expect(big).toHaveCount(0);

  // 폭: RUN 탭에서 넓힌 폭은 RUN 탭에만, 그래프 탭은 기본 폭. 최대는 창 폭의 50%
  const handle = inspector(page).getByRole("separator", { name: "오른쪽 패널 폭" });
  await dragBy(page, handle, -300);
  expect(await width(inspector(page))).toBe(621);
  await tabOf(page, VIEWER_FAIL).click();
  expect(await width(inspector(page))).toBe(321);
  await page.locator(`[role="tab"][data-path="run:${runId}"]`).click();
  expect(await width(inspector(page))).toBe(621);
  await dragBy(page, handle, -1000);
  const viewport = await page.evaluate(() => window.innerWidth);
  expect(await width(inspector(page))).toBe(Math.round(viewport * 0.5) + 1);
  // 창을 줄이면 그리는 폭도 창 폭의 50% 안으로 (기억한 폭은 그대로 — 다시 넓히면 돌아온다, 검수 M4)
  await setContentSize(s.app, page, 1000, 800);
  await expect.poll(() => width(inspector(page))).toBeLessThanOrEqual(501);
  await setContentSize(s.app, page, 1440, 900);
  await expect.poll(() => width(inspector(page))).toBe(Math.round(viewport * 0.5) + 1);
});

test("target 영역 → 속성 탭 매칭 미리보기·클릭 지점", async () => {
  test.setTimeout(180_000);
  const ws = prepareRunWorkspace();
  addCapture(ws.root, "title.png");
  s = await openRunApp(ws);
  const { page } = s;
  const rel = "targets/login/account_field.target.json";
  await openTarget(page, rel);
  // TARGET 탭에서도 속성 창이 보인다 (UX6 전에는 숨었다)
  await expect(inspector(page)).toBeVisible();
  await collapse(page);
  await loadFrame(page, "captures/title.png");
  await selectRect(page, START_BUTTON);
  await expectPropsOpen(page);
  const props = inspector(page).locator(`[data-part="target-props"][data-path="${rel}"]`);
  await expect(props.locator('[data-part="preview-panel"]')).toBeVisible();
  await expect(props.locator('[data-part="click-panel"]')).toBeVisible();
  await expect(props.locator('[data-part="preview-result"]')).toHaveAttribute("data-found", "true", { timeout: 30_000 });
  await expect(editorOf(page, rel).locator('[data-part="preview-panel"]')).toHaveCount(0);
  await shot(page, "target");
});

test("녹화 스텝 → 속성 탭 비밀값/일반 전환", async () => {
  test.setTimeout(240_000);
  s = await openRecorderApp(prepareRecorderWorkspace());
  const { page } = s;
  await startLaunch(page);
  await waitLoginRecorded(page);
  await stopRecording(page);
  await collapse(page);
  const account = page.locator('[data-part="rec-step"][data-text-state="ordinary"]');
  const id = (await account.getAttribute("data-step")) ?? "";
  await account.click();
  await expectPropsOpen(page);
  // 행 안에는 펼치지 않는다
  await expect(account.locator('[data-part="rec-mark-secret"]')).toHaveCount(0);
  const props = inspector(page).locator(`[data-part="rec-props"][data-step="${id}"]`);
  await expect(props).toBeVisible();
  // REC 탭(정지 화면)과 속성 창이 같이 보인다
  await expect(page.locator('[data-part="rec-tab"]')).toBeVisible();
  await shot(page, "rec");
  await props.locator('[data-part="rec-mark-secret"]').click();
  await expect(page.locator(`[data-part="rec-step"][data-step="${id}"]`)).toHaveAttribute("data-text-state", "secret", { timeout: 15_000 });
  await expect(props.locator('[data-part="rec-mark-ordinary"]')).toBeVisible();
});

test("보고함 작업 → 속성 탭 수락", async () => {
  test.setTimeout(420_000);
  // reports.spec와 같은 순서: 앱으로 프로젝트를 연 뒤 팀 기준을 준비한다
  world = prepareShopWorld("missing");
  const graph = "tests/shop/buy_potion.graph.json";
  const launched = await launchApp({ env: world.env, scaleFactor: 1 });
  app = launched.app;
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, world.root);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(page);
  const adopt = await runCli(world, ["cheat", "adopt", "give_gold", "--rev", "1", "--category", "dev_safe", "--workspace", world.root, "--json"]);
  expect(adopt.code, JSON.stringify(adopt.json)).toBe(0);
  const teamGraph = readBytes(world, graph);
  const job = await runAgentJob(world, "shop_missing");
  expect(job.code, JSON.stringify(job.json)).toBe(0);
  await page.locator('[data-part="status-reports"]').click();
  await expect(page.locator('[data-part="reports-tab"]')).toBeVisible();
  await collapse(page);
  const row = page.locator(`[data-part="report-list"] li[data-job="${String(job.json.job)}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator("button").first().click();
  await expectPropsOpen(page);
  const detail = inspector(page).locator(`[data-part="report-detail"][data-job="${String(job.json.job)}"]`);
  await expect(detail.locator('li[data-kind="working_only"]').first()).toBeVisible({ timeout: 30_000 });
  // 보고함 탭은 작업 목록만
  await expect(page.locator('[data-part="reports-tab"] [data-part="report-detail"]')).toHaveCount(0);
  await shot(page, "reports");
  const graphGroup = detail.locator(`section[data-group*="${graph}"]`).filter({ has: page.locator('li[data-kind="working_only"]') });
  await graphGroup.locator('[data-part="accept"]').click();
  await expect(graphGroup).toHaveAttribute("data-decided", "true", { timeout: 60_000 });
  expect(readBytes(world, graph).equals(teamGraph)).toBe(false);
});
