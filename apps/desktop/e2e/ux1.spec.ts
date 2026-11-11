// UX1 (사람 첫 툴 테스트 개선 묶음) E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) — 실제 게임 입력·네트워크·실제 Agent CLI 없음
// - T1 2단계 창 목록: 6개 넘게 모두 보이고 스크롤, 탭을 "떠 있는 창 고르기"로 바꾸면·"다시 찾기"를 누르면 다시 읽는다
// - T2 "실행 파일로 띄우기": 띄우기 → (가짜 플랫폼 launch_fake) 그 프로세스의 창을 자동으로 잡음 → "연결". 인자는 큰따옴표 묶음
// - U4 6단계 원본 칸 두 줄 저장 → 다시 열면 두 줄 그대로
// - U2 기본 에이전트가 있으면 프로젝트를 연 뒤 패널이 자동 연결, 사람이 끊으면 다시 붙지 않는다
// - U3 진행 중 작업의 활동 목록 (가짜 QA 에이전트 각본)
// 샷: 바뀐 마법사 2·6·9단계와 보고함 진행 중 → build/e2e/ux1-shots
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, stubOpenDialog } from "./helpers/app";
import { agentLog, closeAgentApp, openAgentApp, PANEL_AGENT, showAgentTab, type AgentSession } from "./helpers/agent";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./helpers/daemon";
import { cleanupShopWorld, prepareShopWorld, runAgentJob, type ShopWorld } from "./helpers/reports";
import {
  cleanupWorld,
  closeWizardApp,
  expectStep,
  launchWizardApp,
  nextButton,
  openProject,
  prepareWizardWorld,
  pressNext,
  writeWizardProgress,
  type WizardSession,
  type WizardWorld,
} from "./helpers/wizard";

const SHOTS = path.join(REPO_BUILD, "e2e", "ux1-shots");

let s: WizardSession | null = null;
let world: WizardWorld | null = null;
let agentSession: AgentSession | null = null;
let shop: ShopWorld | null = null;
let shopApp: Awaited<ReturnType<typeof launchApp>>["app"] | null = null;
let roots: string[] = [];

test.afterEach(async () => {
  await closeWizardApp(s);
  s = null;
  await cleanupWorld(world, roots);
  world = null;
  roots = [];
  await closeAgentApp(agentSession);
  agentSession = null;
  await closeApp(shopApp ?? undefined);
  shopApp = null;
  if (shop !== null) await cleanupWorkspace(shop.root);
  cleanupShopWorld(shop);
  shop = null;
});

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

/** 가짜 플랫폼에 launch_fake를 켠 마법사 세계 (running: 처음부터 떠 있는 게임이 있나) */
function launchWorld(running: boolean): WizardWorld {
  const w = prepareWizardWorld();
  const spec = JSON.parse(fs.readFileSync(w.platform, "utf8")) as { scenario: string };
  const table = JSON.parse(fs.readFileSync(spec.scenario, "utf8")) as Record<string, unknown>;
  table.running = running;
  fs.writeFileSync(spec.scenario, JSON.stringify(table));
  fs.writeFileSync(w.platform, JSON.stringify({ ...spec, launch_fake: true }));
  return w;
}

/** 마법사 진행을 `step`에 둔 예제 프로젝트 */
function projectAt(name: string, step: number, done: number[], skipped: number[] = []): string {
  const root = copySampleWorkspace(name);
  roots.push(root);
  writeWizardProgress(root, { step, done, skipped });
  return root;
}

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
}

function setLocalSettings(root: string, settings: Record<string, unknown>): void {
  const file = path.join(root, ".kookabug", "local.json");
  const body = fs.existsSync(file) ? readJson(file) : { format: "kookabug.local/0" };
  fs.writeFileSync(file, JSON.stringify({ ...body, settings: { ...((body.settings as object) ?? {}), ...settings } }, null, 2));
}

async function rpc(page: Page, method: string, params: unknown): Promise<unknown> {
  return page.evaluate(
    ([m, p]) => (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<unknown> } }).kookabug.rpc(m, p),
    [method, params] as const,
  );
}

test("T1: 2단계 창 목록은 6개가 넘어도 모두 보이고 스크롤, 탭 바꾸기·다시 찾기로 다시 읽는다", async () => {
  test.setTimeout(180_000);
  world = launchWorld(true);
  const root = projectAt("t1", 2, [1]);
  setLocalSettings(root, { "game.executable": "C:\\Games\\Sample\\Game.exe" });
  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 2, 30_000);
  const rows = page.locator('[data-part="window-list"] label');
  await expect(rows).toHaveCount(1, { timeout: 15_000 }); // 처음부터 떠 있는 게임 하나
  // 가짜 게임 7개를 더 띄운다 (화면은 아직 모른다)
  for (let i = 0; i < 7; i++) await rpc(page, "app.launch", {});
  await expect(rows).toHaveCount(1);
  await page.locator('[data-part="window-reload"]').click();
  await expect(rows).toHaveCount(8, { timeout: 15_000 }); // 예전에는 위 6개만 보였다
  const list = page.locator('[data-part="window-list"]');
  expect(await list.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
  // 탭을 "떠 있는 창 고르기"로 바꾸면 다시 읽는다
  await rpc(page, "app.launch", {});
  await page.locator('[data-part="tab-launch"]').click();
  await page.locator('[data-part="tab-window"]').click();
  await expect(rows).toHaveCount(9, { timeout: 15_000 });
  await expect(page.locator('[data-part="window-reload"]')).toBeVisible(); // 목록 아래에 늘 "다시 찾기"
});

test("T2: 실행 파일로 띄우기 → 그 창을 자동으로 잡고 연결, 큰따옴표 인자는 하나·작업 폴더는 실행 파일 폴더", async () => {
  test.setTimeout(180_000);
  world = launchWorld(false);
  const root = projectAt("t2", 2, [1]);
  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 2, 30_000);
  await expect(page.locator('[data-part="window-list"]')).toContainText("떠 있는 창이 없어요", { timeout: 15_000 });
  await page.locator('[data-part="tab-launch"]').click();
  const launch = page.locator('[data-part="launch"]');
  await expect(launch).toBeDisabled(); // 경로가 비면 띄울 수 없다
  await page.getByLabel("실행 파일", { exact: true }).fill("C:\\Games\\Sample Game\\Game.exe");
  await page.getByLabel("인자", { exact: true }).fill('-windowed -config "C:\\My Game\\user.ini"');
  await expect(nextButton(page)).toBeDisabled();
  await launch.click();
  // 창이 뜨면 자동으로 골라 한 번 잡는다 → "연결"이 켜진다
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 60_000 });
  await expect(nextButton(page)).toBeEnabled();
  await shot(page, "wizard-step2-launch");
  const local = readJson(path.join(root, ".kookabug", "local.json")).settings as Record<string, unknown>;
  expect(local["game.executable"]).toBe("C:\\Games\\Sample Game\\Game.exe");
  expect(local["game.args"]).toEqual(["-windowed", "-config", "C:\\My Game\\user.ini"]);
  expect(local["game.cwd"]).toBe("C:\\Games\\Sample Game");
  await pressNext(page, 3);
  const team = readJson(path.join(root, "kookabug.json")).settings as Record<string, unknown>;
  expect(team["game.title"]).toBeTruthy();
});

test("T2 검수: 무인 작업 중 띄우기는 실패 문구, 고치지 않은 저장 인자(따옴표 JSON·빈 인자·끝 백슬래시)는 그대로", async () => {
  test.setTimeout(300_000);
  world = launchWorld(false);
  const root = projectAt("t2b", 2, [1]);
  const storedArgs = ['--payload={"mode":"qa"}', "", "C:\\My Game\\"];
  // 작업 폴더는 사람이 실행 파일 폴더와 다르게 정해 둔 값 (UX1 검수 H3)
  setLocalSettings(root, { "game.executable": "C:\\Games\\Sample Game\\Game.exe", "game.args": storedArgs, "game.cwd": "D:\\RuntimeData" });
  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 2, 30_000);
  await page.locator('[data-part="tab-launch"]').click();
  // 저장된 인자는 Windows 인자 규칙으로 칸에 채운다 (따옴표·빈 인자·끝 백슬래시가 남는다)
  await expect(page.getByLabel("인자", { exact: true })).toHaveValue('"--payload={\\"mode\\":\\"qa\\"}" "" "C:\\My Game\\\\"', { timeout: 15_000 });
  // 무인 작업을 띄운다 (가짜 QA CLI 각본 — 오래 쉰다)
  const running = runAgentJob({ dir: world.dir, root, platform: world.platform, env: world.env }, path.join(import.meta.dirname, "fixtures", "qa-init-activity.json"), "init");
  let jobId = "";
  await expect
    .poll(
      async () => {
        const jobs = ((await rpc(page, "jobs.list", {})) as { jobs: { job: string; state: string }[] }).jobs;
        jobId = jobs.find((j) => j.state === "running")?.job ?? "";
        return jobId;
      },
      { timeout: 60_000 },
    )
    .not.toBe("");
  await page.locator('[data-part="launch"]').click();
  await expect(page.getByRole("alert")).toHaveText("무인 작업이 도는 중이라 띄우지 않았어요", { timeout: 30_000 });
  await expect(page.locator('[data-part="game-preview"]')).toHaveCount(0);
  // 칸을 고치지 않았으니 저장된 배열이 그대로다
  const settings = () => readJson(path.join(root, ".kookabug", "local.json")).settings as Record<string, unknown>;
  expect(settings()["game.args"]).toEqual(storedArgs);
  // 작업을 끝내면 띄운다 (여전히 저장된 배열 그대로)
  await rpc(page, "job.end", { job: jobId, reason: "cancelled" });
  const job = await running;
  expect(job.json.state).toBe("cancelled");
  await page.locator('[data-part="launch"]').click();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 60_000 });
  expect(settings()["game.args"]).toEqual(storedArgs);
  expect(settings()["game.executable"]).toBe("C:\\Games\\Sample Game\\Game.exe");
  expect(settings()["game.cwd"]).toBe("D:\\RuntimeData");
  // 인자만 고쳐 띄우면 game.args만 쓴다 — 손으로 정한 작업 폴더는 파일·RPC 모두 그대로 (UX1 검수 H3)
  await page.getByLabel("인자", { exact: true }).fill("-new");
  await page.locator('[data-part="launch"]').click();
  await expect.poll(() => settings()["game.args"], { timeout: 30_000 }).toEqual(["-new"]);
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 60_000 });
  expect(settings()["game.cwd"]).toBe("D:\\RuntimeData");
  expect(settings()["game.executable"]).toBe("C:\\Games\\Sample Game\\Game.exe");
  const game = ((await rpc(page, "wizard.get", {})) as { game: Record<string, unknown> }).game;
  expect(game).toMatchObject({ executable: "C:\\Games\\Sample Game\\Game.exe", args: ["-new"], cwd: "D:\\RuntimeData" });
});

test("U4: 6단계 기획 문서 칸에 두 줄 저장 → 다시 열면 두 줄 그대로", async () => {
  test.setTimeout(420_000);
  world = prepareWizardWorld();
  const root = projectAt("u4", 6, [1, 2, 3], [4, 5]);
  const docs = path.join(world.dir, "planning", "more");
  fs.mkdirSync(docs, { recursive: true });
  s = await launchWizardApp(world);
  const userData = s.userData;
  await openProject(s, root);
  let page = s.page;
  await expectStep(page, 6, 30_000);
  const slot = page.locator('[data-slot="design_doc"]');
  await expect(nextButton(page)).toBeEnabled({ timeout: 15_000 });
  await slot.locator('[data-part="source-add"]').click();
  await expect(slot.locator("[data-source]")).toHaveCount(2);
  // 더한 줄 ID는 <칸>_<무작위 6자 hex> (UX1 검수 M1)
  const added = (await slot.locator("[data-source]").nth(1).getAttribute("data-source")) ?? "";
  expect(added).toMatch(/^design_doc_[0-9a-f]{6}$/);
  const addedTitle = `기획 문서 ${added.slice("design_doc_".length)}`;
  await page.getByLabel("기획 문서", { exact: true }).fill("sources");
  await page.getByLabel(addedTitle, { exact: true }).fill(docs);
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  await expect(slot.locator(`[data-source="${added}"]`)).toHaveAttribute("data-state", "ok");
  await shot(page, "wizard-step6-sources");
  const sources = readJson(path.join(root, "kookabug.json")).sources as Record<string, unknown>[];
  expect(sources).toContainEqual({ id: "design_doc", kind: "design_doc", title: "기획 문서", path: "sources" });
  expect(sources).toContainEqual({ id: added, kind: "design_doc", title: addedTitle, local: true });
  const localSources = readJson(path.join(root, ".kookabug", "local.json")).sources as Record<string, { path: string }>;
  expect(localSources[added].path).toBe(docs);
  await closeWizardApp(s);
  s = null;
  // 다시 열면 두 줄 그대로 (팀 경로 + 이 PC 경로)
  s = await launchWizardApp(world, { userData });
  await openProject(s, root);
  page = s.page;
  await expectStep(page, 6, 30_000);
  await expect(page.getByLabel("기획 문서", { exact: true })).toHaveValue("sources", { timeout: 15_000 });
  await expect(page.getByLabel(addedTitle, { exact: true })).toHaveValue(docs);
  // 첫 줄을 지워도 남은 줄의 ID는 그대로 (이 PC 경로 연결이 깨지지 않는다)
  await page.locator('[data-source="design_doc"] [data-part="source-remove"]').click();
  await expect(page.locator('[data-slot="design_doc"] [data-source]')).toHaveCount(1);
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  const after = readJson(path.join(root, "kookabug.json")).sources as { id: string }[];
  expect(after.filter((x) => x.id.startsWith("design_doc")).map((x) => x.id)).toEqual([added]);
  expect((readJson(path.join(root, ".kookabug", "local.json")).sources as Record<string, unknown>)[added]).toEqual({ path: docs });
  // 가장 큰(마지막) 줄을 지워 저장한 뒤 다시 열고 추가해도 지운 ID를 다시 쓰지 않는다 (UX1 검수 M1)
  await closeWizardApp(s);
  s = null;
  s = await launchWizardApp(world, { userData });
  await openProject(s, root);
  page = s.page;
  await expectStep(page, 6, 30_000);
  await expect(page.getByLabel(addedTitle, { exact: true })).toHaveValue(docs, { timeout: 15_000 });
  await page.locator(`[data-source="${added}"] [data-part="source-remove"]`).click();
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  const cleared = readJson(path.join(root, "kookabug.json")).sources as { id: string }[];
  expect(cleared.filter((x) => x.id.startsWith("design_doc"))).toEqual([]);
  await closeWizardApp(s);
  s = null;
  s = await launchWizardApp(world, { userData });
  await openProject(s, root);
  page = s.page;
  await expectStep(page, 6, 30_000);
  const reopened = page.locator('[data-slot="design_doc"]');
  await expect(nextButton(page)).toBeEnabled({ timeout: 15_000 });
  await reopened.locator('[data-part="source-add"]').click();
  await expect(reopened.locator("[data-source]")).toHaveCount(2);
  const again = (await reopened.locator("[data-source]").nth(1).getAttribute("data-source")) ?? "";
  expect(again).toMatch(/^design_doc_[0-9a-f]{6}$/);
  expect(again).not.toBe(added);
});

test("9단계 샷: Agent 없이 끝내는 화면", async () => {
  test.setTimeout(120_000);
  world = prepareWizardWorld();
  const root = projectAt("s9", 9, [1, 2, 3, 6, 7, 8], [4, 5]);
  s = await launchWizardApp(world);
  await openProject(s, root);
  await expectStep(s.page, 9, 30_000);
  await expect(s.page.locator('[data-part="wizard-summary"]')).toBeVisible();
  await shot(s.page, "wizard-step9-done");
});

test("U2: 기본 에이전트가 있으면 프로젝트를 연 뒤 패널이 자동 연결, 사람이 끊으면 다시 붙지 않는다", async () => {
  test.setTimeout(180_000);
  agentSession = await openAgentApp({
    settings: { format: "kookabug.user-settings/0", agents: [PANEL_AGENT], default_agent: PANEL_AGENT.id },
  });
  const { page } = agentSession;
  const panel = await showAgentTab(page);
  // 연결 단추를 누르지 않았다
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 60_000 });
  expect(agentLog(agentSession).length).toBeGreaterThan(0);
  await panel.getByRole("button", { name: "에이전트 연결 끊기" }).click();
  await expect(panel.locator('[data-part="agent-connect"]')).toBeVisible();
  await page.waitForTimeout(3000);
  await expect(panel.locator('[data-part="agent-connect"]')).toBeVisible();
  await expect(panel.locator('[data-part="agent-connecting"]')).toHaveCount(0);
});

test("U2 음성: 기본 에이전트가 없으면 자동 연결하지 않는다", async () => {
  test.setTimeout(120_000);
  agentSession = await openAgentApp();
  const panel = await showAgentTab(agentSession.page);
  await expect(panel.locator('[data-part="agent-connect"]')).toBeVisible({ timeout: 30_000 });
  await agentSession.page.waitForTimeout(3000);
  await expect(panel.locator('[data-part="agent-connect"]')).toBeVisible();
  expect(agentLog(agentSession)).toEqual([]);
});

test("U3: 진행 중 작업의 활동 목록 — Kookabug 도구 호출·머리 요약·Agent 출력 꼬리", async () => {
  test.setTimeout(300_000);
  shop = prepareShopWorld("moved");
  const launched = await launchApp({ env: shop.env, scaleFactor: 1 });
  shopApp = launched.app;
  const page = await shopApp.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(shopApp, page, 1440, 900);
  await stubOpenDialog(shopApp, shop.root);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(page);
  const script = path.join(import.meta.dirname, "fixtures", "qa-init-activity.json");
  const running = runAgentJob(shop, script, "init");
  await page.locator('[data-part="status-reports"]').click();
  const row = page.locator('[data-part="report-list"] li[data-state="running"]');
  await expect(row).toHaveCount(1, { timeout: 60_000 });
  await expect(page.locator('[data-part="status-reports"] [data-part="spinner"]')).toBeVisible();
  await row.locator("button").first().click();
  const activity = page.locator('[data-part="job-activity"]');
  await expect(activity).toHaveAttribute("data-live", "true");
  const list = activity.locator('[data-part="activity-list"]');
  await expect(list).toContainText("설정 확인", { timeout: 60_000 });
  await expect(list).toContainText("지식 읽기: unknowns", { timeout: 60_000 });
  await expect(activity.locator('[data-part="activity-head"]')).toContainText(/도구 호출 \d+/);
  const tail = activity.locator('[data-part="agent-log-tail"]');
  await tail.locator("summary").click();
  await expect(tail.locator("pre")).toContainText("ux1-activity: 원본을 읽는 중", { timeout: 30_000 });
  await shot(page, "reports-running-activity");
  // 정리: 작업 취소
  await row.locator('[data-part="cancel"]').click();
  const job = await running;
  expect(job.json.state).toBe("cancelled");
});
