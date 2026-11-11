// UX2 (Init 질문 답 이후 흐름) E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) → 실제 `kookabug agent-job run`(가짜 QA CLI 각본).
// 실제 게임 입력·네트워크·실제 Agent CLI 없음. 샘플 게임 워크스페이스만 쓴다
// - A: 워크스페이스 **밖** 임시 폴더를 원본으로 등록하고 Init이 kb_source_list·kb_source_read로 읽는다 (그 ref·hash로 expected 주장)
// - B: 보고함 질문 두 개에 글을 넣고 "답 보내기" 한 번 → 둘 다 answered
// - D: "이어서 진행" → followup 무인 작업 (도는 동안 단추 꺼짐·이유), 답을 읽어 설정 제안
// - C: followup 보고의 "설정 바꾸기 제안" 카드(현재 값 → 제안 값) 수락 → kookabug.json에 반영
// 샷: build/e2e/ux2-shots
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, DEFAULT_TEST_AGENT, launchApp, REPO_BUILD, setContentSize, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./helpers/daemon";
import { runAgentJob } from "./helpers/reports";
import { cleanupWorld, prepareWizardWorld, type WizardWorld } from "./helpers/wizard";

const SCRIPT = path.join(import.meta.dirname, "fixtures", "qa-ux2.json");
const SHOTS = path.join(REPO_BUILD, "e2e", "ux2-shots");
const TITLE_ANSWER = "SampleRPG Remastered";

let app: ElectronApplication | null = null;
let world: WizardWorld | null = null;
let roots: string[] = [];

test.afterEach(async () => {
  await closeApp(app ?? undefined);
  app = null;
  for (const r of roots) await cleanupWorkspace(r);
  await cleanupWorld(world, []);
  world = null;
  roots = [];
});

type Json = Record<string, unknown>;

function readJson(file: string): Json {
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^﻿/, "")) as Json;
}

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

async function rpc(page: Page, method: string, params: unknown): Promise<unknown> {
  return page.evaluate(
    ([m, p]) => (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<unknown> } }).kookabug.rpc(m, p),
    [method, params] as const,
  );
}

/** 샘플 워크스페이스 + 밖 원본 폴더(`plans`, 이 PC 경로) + 기본 Agent가 있는 사용자 설정 */
function prepare(): { root: string; outside: string } {
  world = prepareWizardWorld(SCRIPT);
  const root = copySampleWorkspace("ux2");
  roots.push(root);
  const outside = path.join(world.dir, "outside_plans");
  fs.mkdirSync(path.join(outside, "plan"), { recursive: true });
  fs.writeFileSync(path.join(outside, "plan", "shop.md"), "# 상점\n체력 물약 100골드\n");
  fs.writeFileSync(path.join(world.dir, "secret.txt"), "밖 파일");
  const configFile = path.join(root, "kookabug.json");
  const config = readJson(configFile);
  config.sources = [...((config.sources as unknown[]) ?? []), { id: "plans", kind: "design_doc", title: "기획 문서", local: true }];
  fs.writeFileSync(configFile, JSON.stringify(config, null, 2));
  fs.mkdirSync(path.join(root, ".kookabug"), { recursive: true });
  fs.writeFileSync(
    path.join(root, ".kookabug", "local.json"),
    JSON.stringify({ format: "kookabug.local/0", permissions: { preset: "curator" }, sources: { plans: { path: outside } } }, null, 2),
  );
  fs.writeFileSync(
    path.join(world.env.KOOKABUG_USER_CONFIG_DIR, "settings.json"),
    JSON.stringify({ format: "kookabug.user-settings/0", agents: [DEFAULT_TEST_AGENT], default_agent: DEFAULT_TEST_AGENT.id }),
  );
  return { root, outside };
}

test("Init이 밖 원본을 읽고 → 질문 일괄 답 → 이어서 진행 → 설정 제안 수락", async () => {
  test.setTimeout(600_000);
  const { root, outside } = prepare();
  const w = world!;
  const launched = await launchApp({ env: w.env, scaleFactor: 1 });
  app = launched.app;
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, root);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(page);

  // A: Init (9단계와 같은 agent-job run, 가짜 QA CLI) — 각본이 원본 목록·읽기·경계 거부·근거 확인을 단언한다
  const init = await runAgentJob({ dir: w.dir, root, platform: w.platform, env: w.env }, SCRIPT, "init");
  expect(init.code, JSON.stringify(init.json)).toBe(0);
  expect(init.json.state).toBe("done");
  const initJob = String(init.json.job);
  const fake = readJson(path.join(root, ".kookabug", "jobs", initJob, "fake.json"));
  expect(fake.failed, JSON.stringify(fake)).toBeUndefined();
  const claims = readJson(path.join(root, "knowledge", "features", "planshop.json")).claims as Json[];
  const basis = (claims[0].basis as Json[])[0];
  expect(basis).toMatchObject({ type: "source", ref: "sources:plans#plan/shop.md", verified: true });
  expect(outside.startsWith(root)).toBe(false); // 원본은 워크스페이스 밖
  const activity = fs
    .readFileSync(path.join(root, ".kookabug", "jobs", initJob, "activity.jsonl"), "utf8")
    .trim()
    .split(/\r?\n/)
    .map((l) => JSON.parse(l) as Json);
  expect(activity.some((e) => e.tool === "kb_source_read" && e.target === "plans:plan/shop.md")).toBe(true);

  // B: 보고함 질문 둘 → "답 보내기" 한 번
  await page.locator('[data-part="status-reports"]').click();
  const row = page.locator(`[data-part="report-list"] li[data-job="${initJob}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator("button").first().click();
  const detail = page.locator(`[data-part="report-detail"][data-job="${initJob}"]`);
  const questions = detail.locator('[data-part="questions"]');
  await expect(questions.locator("li[data-unknown]")).toHaveCount(2, { timeout: 30_000 });
  // 질문마다 단추는 없고 묶음 아래 "답 보내기" 하나
  await expect(questions.getByRole("button")).toHaveCount(1);
  const send = questions.locator('[data-part="send-answers"]');
  await expect(send).toBeDisabled(); // 빈 칸뿐
  await expect(detail.locator('[data-part="followup-remaining"]')).toContainText("2개");
  await questions.getByLabel("답: 게임 창 제목은 무엇인가요").fill(TITLE_ANSWER);
  await questions.getByLabel("답: 상점 기획 문서의 최신 판은 어디인가요").fill("plans 폴더의 plan/shop.md가 최신");
  await shot(page, "reports-ux2-questions");
  await expect(send).toHaveText("답 보내기 (2)");
  await send.click();
  await expect(detail.locator('[data-part="questions"]')).toHaveCount(0, { timeout: 30_000 }); // 둘 다 답해 질문이 사라진다
  await expect(detail.locator('[data-part="action-message"]').filter({ hasText: "답 2개를 보냈어요" })).toBeVisible();
  const unknowns = (readJson(path.join(root, "knowledge", "unknowns.json")).unknowns as Json[]).filter((u) => u.human_only === true);
  expect(unknowns.map((u) => u.state)).toEqual(["answered", "answered"]);
  expect(unknowns.map((u) => (u.answer as Json).text)).toContain(TITLE_ANSWER);
  await expect(detail.locator('[data-part="followup-remaining"]')).toHaveText("남은 질문 없음");

  // D: "이어서 진행" → followup 무인 작업 (주 프로세스 agentJobRun, E2E 훅의 가짜 CLI)
  const followup = detail.locator('[data-part="followup"]');
  await expect(followup).toBeEnabled();
  await followup.click();
  let followJob = "";
  await expect
    .poll(
      async () => {
        const jobs = ((await rpc(page, "jobs.list", {})) as { jobs: { job: string; playbook: string; state: string }[] }).jobs;
        const found = jobs.find((j) => j.playbook === "followup");
        followJob = found?.job ?? "";
        return found?.state ?? "";
      },
      { timeout: 120_000 },
    )
    .toMatch(/running|done/);
  // 도는 동안에는 다른 보고의 "이어서 진행"도 꺼지고 이유가 보인다 (각본이 잠깐 머문다)
  await page.locator(`[data-part="report-list"] li[data-job="${initJob}"] button`).first().click();
  const again = page.locator(`[data-part="report-detail"][data-job="${initJob}"]`);
  const blocked = again.locator('[data-part="followup-blocked"]');
  if ((await rpc(page, "jobs.list", {}).then((r) => (r as { jobs: { job: string; state: string }[] }).jobs.find((j) => j.job === followJob)?.state)) === "running") {
    await expect(again.locator('[data-part="followup"]')).toBeDisabled({ timeout: 10_000 });
    await expect(blocked).toContainText("무인 작업이 도는 중");
  }
  await expect
    .poll(async () => ((await rpc(page, "jobs.list", {})) as { jobs: { job: string; state: string }[] }).jobs.find((j) => j.job === followJob)?.state, {
      timeout: 180_000,
    })
    .toBe("done");
  const followFake = readJson(path.join(root, ".kookabug", "jobs", followJob, "fake.json"));
  expect(followFake.failed, JSON.stringify(followFake)).toBeUndefined();

  // C: 설정 바꾸기 제안 카드 → 수락 → kookabug.json 반영. 팀 보고 파일에는 제안 값이 없다(이 PC proposals.json에만, 검수 1 H1)
  const teamReport = fs.readFileSync(path.join(root, "knowledge", "reports", `${followJob}.json`), "utf8");
  expect(teamReport).not.toContain(TITLE_ANSWER);
  const teamSettings = ((JSON.parse(teamReport) as Json).groups as Json[]).flatMap((g) => (g.items as Json[]).map((i) => i.setting)).filter(Boolean);
  expect(teamSettings).toEqual([expect.objectContaining({ key: "game.title" })]);
  expect(Object.keys(teamSettings[0] as Json).sort()).toEqual(["id", "key", "reason"]);
  const before = readJson(path.join(root, "kookabug.json")).settings as Json;
  expect(before["game.title"]).toBe("SampleRPG"); // 제안만으로는 바뀌지 않았다
  await page.locator(`[data-part="report-list"] li[data-job="${followJob}"] button`).first().click();
  const fdetail = page.locator(`[data-part="report-detail"][data-job="${followJob}"]`);
  const card = fdetail.locator('[data-part="setting-change"][data-key="game.title"]');
  await expect(card).toBeVisible({ timeout: 30_000 });
  await expect(card.locator('[data-part="setting-current"]')).toHaveText("SampleRPG");
  await expect(card.locator('[data-part="setting-proposed"]')).toHaveText(TITLE_ANSWER);
  await expect(card).toContainText("게임 창 제목");
  const group = fdetail.locator("section[data-group]").filter({ has: page.locator('[data-part="setting-change"][data-key="game.title"]') });
  await shot(page, "reports-ux2-setting");
  await group.locator('[data-part="accept"]').click();
  await expect(group.locator('[data-part="action-message"]')).toContainText("설정에 반영했어요", { timeout: 30_000 });
  await expect(group.locator('[data-part="accept"]')).toHaveCount(0);
  await expect(group).toHaveAttribute("data-decided", "true");
  expect((readJson(path.join(root, "kookabug.json")).settings as Json)["game.title"]).toBe(TITLE_ANSWER);
  const log = fs
    .readFileSync(path.join(root, "knowledge", "log.jsonl"), "utf8")
    .trim()
    .split(/\r?\n/)
    .map((l) => JSON.parse(l) as Json);
  expect(log.some((l) => l.op === "setting_accept")).toBe(true);
});
