// 보고함 E2E (M8 계획 3.11·3.17·B7): B6 실제 흐름(예제 상점 가짜 게임 + 앱이 띄운 daemon + 실제 `agent-job run` →
// 가짜 QA CLI 각본 shop_moved·shop_missing)으로 만든 보고를 앱에서 본다. 되돌리기 한 번(두 번째는 막힘), 묶음 수락·거절,
// 증거 묶음 열기, 작업 취소(두 번 누르기). 결정은 모두 렌더러의 사람 경로(ui 연결)로 간다
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { closeApp, launchApp, setContentSize, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, waitConnected } from "./helpers/daemon";
import { cleanupShopWorld, prepareShopWorld, readBytes, runAgentJob, runCli, type ShopWorld } from "./helpers/reports";
import type { ElectronApplication } from "@playwright/test";

const TARGET = "targets/shop/buy.target.json";
const IMAGE = "targets/shop/buy.png";
const GRAPH = "tests/shop/buy_potion.graph.json";

let app: ElectronApplication | null = null;
let world: ShopWorld | null = null;

test.afterEach(async () => {
  await closeApp(app ?? undefined);
  app = null;
  // UI를 꺼도 daemon은 남는다: 끄고 사본을 지운다
  if (world !== null) await cleanupWorkspace(world.root);
  cleanupShopWorld(world);
  world = null;
});

async function openShop(w: ShopWorld): Promise<Page> {
  const launched = await launchApp({ env: w.env, scaleFactor: 1 });
  app = launched.app;
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, w.root);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  return page;
}

async function openInbox(page: Page): Promise<void> {
  await page.locator('[data-part="status-reports"]').click();
  await expect(page.locator('[data-part="reports-tab"]')).toBeVisible();
  await expect(page.locator('[data-part="security-boundary"]')).toContainText("Agent CLI가 자기 셸·파일 도구를 쓰면 막을 수 없습니다");
}

test("정상 수리 보고: 자동 수리 되돌리기 한 번 → 원래 바이트, 두 번째는 막힘", async () => {
  test.setTimeout(420_000);
  world = prepareShopWorld("moved");
  const page = await openShop(world);
  const team = readBytes(world, TARGET);
  const teamImage = readBytes(world, IMAGE);
  const job = await runAgentJob(world, "shop_moved");
  test.info().annotations.push({ type: "agent-job ms", description: String(job.ms) });
  expect(job.code, JSON.stringify(job.json)).toBe(0);
  expect(job.json.state).toBe("done");
  // 양성 대조: 채택으로 팀 target이 실제로 바뀌었다
  expect(readBytes(world, TARGET).equals(team)).toBe(false);
  await expect(page.locator('[data-part="status-reports"]')).toBeVisible();
  await openInbox(page);
  const row = page.locator(`[data-part="report-list"] li[data-job="${String(job.json.job)}"]`);
  await expect(row).toHaveAttribute("data-state", "done", { timeout: 30_000 });
  await row.locator("button").first().click();
  const detail = page.locator(`[data-part="report-detail"][data-job="${String(job.json.job)}"]`);
  const item = detail.locator('li[data-kind="auto_adopted"]');
  await expect(item).toHaveCount(1, { timeout: 30_000 });
  await expect(item).toContainText("negative:1");
  const revert = item.locator('[data-part="revert"]');
  await expect(revert).toBeEnabled();
  await revert.click();
  await expect(item.locator('[data-part="action-message"]')).toContainText("되돌렸어요", { timeout: 60_000 });
  await expect(item.locator('[data-part="revert"]')).toHaveCount(0); // 한 번만
  expect(readBytes(world, TARGET).equals(team)).toBe(true);
  expect(readBytes(world, IMAGE).equals(teamImage)).toBe(true);
  // 두 번째 되돌리기는 daemon이 막는다 (렌더러 사람 경로로 직접 불러도)
  const adoption = await page.evaluate(async () => {
    const list = (await (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<{ adoptions: { id: string }[] }> } }).kookabug.rpc(
      "adoptions.list",
      {},
    )) as { adoptions: { id: string }[] };
    return list.adoptions[0].id;
  });
  const second = await page.evaluate(async (id) => {
    try {
      await (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<unknown> } }).kookabug.rpc("adopt.revert", { adoption: id });
      return "ok";
    } catch (err) {
      return String((err as { data?: { code?: string } }).data?.code);
    }
  }, adoption);
  expect(second).toBe("already_reverted");
  expect(readBytes(world, TARGET).equals(team)).toBe(true);
});

test("회귀 의심 보고: 증거 묶음 열기, 묶음 수락은 팀 반영·거절은 그대로", async () => {
  test.setTimeout(420_000);
  world = prepareShopWorld("missing");
  const page = await openShop(world);
  // 사람이 준비한 팀 기준 (B6 인계): give_gold 채택
  const adopt = await runCli(world, ["cheat", "adopt", "give_gold", "--rev", "1", "--category", "dev_safe", "--workspace", world.root, "--json"]);
  expect(adopt.code, JSON.stringify(adopt.json)).toBe(0);
  const teamTarget = readBytes(world, TARGET);
  const teamGraph = readBytes(world, GRAPH);
  const job = await runAgentJob(world, "shop_missing");
  test.info().annotations.push({ type: "agent-job ms", description: String(job.ms) });
  expect(job.code, JSON.stringify(job.json)).toBe(0);
  // 은폐 시도가 막혀 팀 파일은 그대로 (보고함에서 결정하기 전)
  expect(readBytes(world, TARGET).equals(teamTarget)).toBe(true);
  expect(readBytes(world, GRAPH).equals(teamGraph)).toBe(true);
  await openInbox(page);
  const row = page.locator(`[data-part="report-list"] li[data-job="${String(job.json.job)}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator("button").first().click();
  const detail = page.locator(`[data-part="report-detail"][data-job="${String(job.json.job)}"]`);
  await expect(detail.locator('li[data-kind="regression_suspect"]')).toHaveCount(1, { timeout: 30_000 });
  await expect(detail.locator('li[data-kind="auto_adopted"]')).toHaveCount(0);
  // 증거 묶음 열기 → 보기 탭 (knowledge/evidence/<e>/manifest.json, 읽기 전용)
  await detail.locator('[data-part="open-evidence"]').click();
  const tab = page.locator('[role="tab"][data-path^="knowledge/evidence/"]');
  await expect(tab).toHaveCount(1);
  await expect(page.getByText('"format": "kookabug.evidence/0"').first()).toBeVisible({ timeout: 15_000 });
  await page.locator('[role="tab"][data-path="reports:inbox"] button').first().click();
  // 작업 기준에만 있는 변경 두 묶음: target은 거절, 그래프는 수락
  const targetGroup = detail.locator(`section[data-group*="${TARGET}"]`).filter({ has: page.locator('li[data-kind="working_only"]') });
  const graphGroup = detail.locator(`section[data-group*="${GRAPH}"]`).filter({ has: page.locator('li[data-kind="working_only"]') });
  await expect(targetGroup).toHaveCount(1);
  await expect(graphGroup).toHaveCount(1);
  // 양성 대조: 결정 전에는 상태 바 보고함 수가 0이 아니다
  await expect(page.locator('[data-part="status-reports"]')).not.toHaveAttribute("data-count", "0");
  await targetGroup.locator('[data-part="reject"]').click();
  await expect(targetGroup).toHaveAttribute("data-decided", "true", { timeout: 60_000 });
  await expect(targetGroup.locator('[data-part="accept"]')).toHaveCount(0);
  expect(readBytes(world, TARGET).equals(teamTarget)).toBe(true);
  await graphGroup.locator('[data-part="accept"]').click();
  await expect(graphGroup).toHaveAttribute("data-decided", "true", { timeout: 60_000 });
  // 양성: 수락한 그래프는 팀에 반영됐다 (작업 사본 바이트)
  expect(readBytes(world, GRAPH).equals(teamGraph)).toBe(false);
  await expect(page.locator('[data-part="status-reports"]')).toHaveAttribute("data-count", "0");
});

test("작업 취소: 진행 중 → 취소 두 번 눌러도 한 번만, 끝나면 취소됨", async () => {
  test.setTimeout(300_000);
  world = prepareShopWorld("moved");
  const page = await openShop(world);
  const script = path.join(world.dir, "sleep.json");
  (await import("node:fs")).writeFileSync(script, JSON.stringify({ steps: [{ tool: "kb_project_info", expect: "ok" }, { sleep: 120 }] }));
  const running = runAgentJob(world, script);
  await openInbox(page);
  const row = page.locator('[data-part="report-list"] li[data-state="running"]');
  await expect(row).toHaveCount(1, { timeout: 60_000 });
  const cancel = row.locator('[data-part="cancel"]');
  await expect(cancel).toBeEnabled();
  await cancel.dblclick();
  const job = await running;
  expect(job.json.state).toBe("cancelled");
  const done = page.locator(`[data-part="report-list"] li[data-job="${String(job.json.job)}"]`);
  await expect(done).toHaveAttribute("data-state", "cancelled", { timeout: 60_000 });
  await expect(done.locator('[data-part="cancel"]')).toHaveCount(0);
  // 두 번째 누름은 보내지 않았다: 오류 글이 없다
  await expect(page.locator('[role="alert"]')).toHaveCount(0);
});
