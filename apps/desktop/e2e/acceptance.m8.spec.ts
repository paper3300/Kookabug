// M8 인수 E2E (계획 5장): 보고함의 자동 수리 되돌리기, 회귀 의심 보고와 묶음 수락·거절, 마법사 0→9 → Init → 보고함(질문 답하기),
// 마법사 필수 단계 잠금·건너뛰기·이어서·팀원 짧은 마법사.
// 준비는 B6·B7 도우미(helpers/reports.ts·reports_world.py·helpers/wizard.ts)와 실제 `kookabug agent-job run`(가짜 QA CLI 각본)이다.
// 보고 JSON을 손으로 쓰지 않는다. 다른 spec을 import하지 않는다. 실제 입력·실제 Agent CLI는 쓰지 않는다
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, setContentSize, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./helpers/daemon";
import { cleanupShopWorld, prepareShopWorld, readBytes, runAgentJob, runCli, type ShopWorld } from "./helpers/reports";
import {
  cleanupWorld,
  closeWizardApp,
  expectStep,
  launchWizardApp,
  nextButton,
  openProject,
  overlay,
  prepareWizardWorld,
  pressNext,
  readWizardFile,
  skipStep,
  writeWizardProgress,
  type WizardSession,
  type WizardWorld,
} from "./helpers/wizard";

const TARGET = "targets/shop/buy.target.json";
const IMAGE = "targets/shop/buy.png";
const GRAPH = "tests/shop/buy_potion.graph.json";
const INIT_SCRIPT = path.join(import.meta.dirname, "fixtures", "qa-init-unknowns.json");

let app: ElectronApplication | null = null;
let shop: ShopWorld | null = null;
let s: WizardSession | null = null;
let wiz: WizardWorld | null = null;
let roots: string[] = [];

test.afterEach(async () => {
  await closeApp(app ?? undefined);
  app = null;
  if (shop !== null) await cleanupWorkspace(shop.root);
  cleanupShopWorld(shop);
  shop = null;
  await closeWizardApp(s);
  s = null;
  await cleanupWorld(wiz, roots);
  for (const r of roots.filter((x) => !wiz || !x.startsWith(wiz.dir))) await cleanupWorkspace(r);
  wiz = null;
  roots = [];
});

type Json = Record<string, unknown>;

function readJson(file: string): Json {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Json;
}

function knowledgeFiles(root: string, dir: string): Json[] {
  const base = path.join(root, "knowledge", dir);
  if (!fs.existsSync(base)) return [];
  return fs
    .readdirSync(base)
    .filter((n) => n.endsWith(".json"))
    .map((n) => readJson(path.join(base, n)));
}

function changes(root: string): Json[] {
  const base = path.join(root, "knowledge", "working");
  if (!fs.existsSync(base)) return [];
  return fs
    .readdirSync(base)
    .filter((n) => fs.existsSync(path.join(base, n, "change.json")))
    .map((n) => readJson(path.join(base, n, "change.json")));
}

async function openShopApp(w: ShopWorld): Promise<Page> {
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

async function openReport(page: Page, job: string): Promise<ReturnType<Page["locator"]>> {
  await page.locator('[data-part="status-reports"]').click();
  await expect(page.locator('[data-part="reports-tab"]')).toBeVisible();
  await expect(page.locator('[data-part="security-boundary"]')).toContainText("Agent CLI가 자기 셸·파일 도구를 쓰면 막을 수 없습니다");
  const row = page.locator(`[data-part="report-list"] li[data-job="${job}"]`);
  await expect(row).toBeVisible({ timeout: 30_000 });
  await row.locator("button").first().click();
  return page.locator(`[data-part="report-detail"][data-job="${job}"]`);
}

test("test_report_shows_adoption_and_revert", async () => {
  test.setTimeout(480_000);
  shop = prepareShopWorld("moved");
  const page = await openShopApp(shop);
  const team = readBytes(shop, TARGET);
  const teamImage = readBytes(shop, IMAGE);
  const teamGraph = readBytes(shop, GRAPH);
  const job = await runAgentJob(shop, "shop_moved");
  test.info().annotations.push({ type: "agent-job ms", description: String(job.ms) });
  expect(job.code, JSON.stringify(job.json)).toBe(0);
  expect(job.json.state).toBe("done");
  // 양성 대조: 자동 채택으로 팀 target이 바뀌었고 그래프는 그대로, 사건은 resolved
  const adopted = readBytes(shop, TARGET);
  expect(adopted.equals(team)).toBe(false);
  expect(readBytes(shop, GRAPH).equals(teamGraph)).toBe(true);
  const [record] = knowledgeFiles(shop.root, "adoptions").filter((a) => a.kind === "auto");
  expect(record.reverted).toBeNull();
  const caseId = String(record.case);
  const caseFile = path.join(shop.root, "knowledge", "cases", `${caseId}.json`);
  expect(readJson(caseFile).state).toBe("resolved");

  const detail = await openReport(page, String(job.json.job));
  const item = detail.locator('li[data-kind="auto_adopted"]');
  await expect(item).toHaveCount(1, { timeout: 30_000 });
  for (const check of ["oracle", "negative:1", "affected:1"]) await expect(item).toContainText(check);
  // 위키 보고(Kookabug 렌더)도 열 수 있다
  await expect(detail.locator('[data-part="open-rendered"]')).toBeVisible();
  const revert = item.locator('[data-part="revert"]');
  await expect(revert).toBeEnabled(); // 꺼진 단추를 누른 것으로 통과하지 않게
  await revert.click();
  await expect(item.locator('[data-part="action-message"]')).toContainText("되돌렸어요", { timeout: 60_000 });
  await expect(item.locator('[data-part="action-message"]')).toContainText("게임 계정·서버 상태는 되돌리지 않아요");
  await expect(item.locator('[data-part="revert"]')).toHaveCount(0); // 한 번만
  // 원래 바이트로 돌아왔고 기록·사건이 따라 바뀐다
  expect(readBytes(shop, TARGET).equals(team)).toBe(true);
  expect(readBytes(shop, IMAGE).equals(teamImage)).toBe(true);
  expect(readBytes(shop, GRAPH).equals(teamGraph)).toBe(true);
  const after = knowledgeFiles(shop.root, "adoptions");
  expect(after.find((a) => a.id === record.id)?.reverted).not.toBeNull();
  expect(after.filter((a) => a.kind === "revert")).toHaveLength(1);
  expect(readJson(caseFile).state).toBe("open");

  // 두 번째 되돌리기는 daemon이 막는다 (렌더러 사람 경로로 직접 불러도) — 파일은 그대로
  const second = await page.evaluate(async (id) => {
    try {
      await (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<unknown> } }).kookabug.rpc("adopt.revert", { adoption: id });
      return "ok";
    } catch (err) {
      return String((err as { data?: { code?: string } }).data?.code);
    }
  }, String(record.id));
  expect(second).toBe("already_reverted");
  expect(readBytes(shop, TARGET).equals(team)).toBe(true);
  expect(knowledgeFiles(shop.root, "adoptions").filter((a) => a.kind === "revert")).toHaveLength(1);
});

test("test_report_regression_and_batch_reject", async () => {
  test.setTimeout(480_000);
  shop = prepareShopWorld("missing");
  const page = await openShopApp(shop);
  // 사람이 준비한 팀 기준 (B6): give_gold 채택
  const adopt = await runCli(shop, ["cheat", "adopt", "give_gold", "--rev", "1", "--category", "dev_safe", "--workspace", shop.root, "--json"]);
  expect(adopt.code, JSON.stringify(adopt.json)).toBe(0);
  const teamTarget = readBytes(shop, TARGET);
  const teamGraph = readBytes(shop, GRAPH);
  const job = await runAgentJob(shop, "shop_missing");
  test.info().annotations.push({ type: "agent-job ms", description: String(job.ms) });
  expect(job.code, JSON.stringify(job.json)).toBe(0);
  // 은폐 시도가 막혀 팀 파일은 그대로, 채택 기록 없음, 사건은 열린 채
  expect(readBytes(shop, TARGET).equals(teamTarget)).toBe(true);
  expect(readBytes(shop, GRAPH).equals(teamGraph)).toBe(true);
  expect(knowledgeFiles(shop.root, "adoptions")).toHaveLength(0);
  const cases = knowledgeFiles(shop.root, "cases");
  expect(cases.length).toBeGreaterThan(0);
  expect(cases.every((c) => c.state !== "resolved" && c.state !== "closed")).toBe(true);
  // 양성 대조: 작업 기준에는 변경이 실제로 남아 있다 (target·그래프)
  const active = changes(shop.root).filter((c) => c.state === "active");
  const targetChange = active.find((c) => (c.files as { path: string }[]).some((f) => f.path === TARGET));
  const graphChange = active.find((c) => (c.files as { path: string }[]).some((f) => f.path === GRAPH));
  expect(targetChange).toBeTruthy();
  expect(graphChange).toBeTruthy();

  const detail = await openReport(page, String(job.json.job));
  const suspect = detail.locator('li[data-kind="regression_suspect"]');
  await expect(suspect).toHaveCount(1, { timeout: 30_000 });
  // 같은 상세가 그려진 뒤의 "없음" (위 양성과 같은 화면)
  await expect(detail.locator('li[data-kind="auto_adopted"]')).toHaveCount(0);
  await expect(suspect.locator('[data-part="open-evidence"]')).toBeVisible();
  const targetGroup = detail.locator(`section[data-group*="${TARGET}"]`).filter({ has: page.locator('li[data-kind="working_only"]') });
  const graphGroup = detail.locator(`section[data-group*="${GRAPH}"]`).filter({ has: page.locator('li[data-kind="working_only"]') });
  await expect(targetGroup).toHaveCount(1);
  await expect(graphGroup).toHaveCount(1);
  await expect(page.locator('[data-part="status-reports"]')).not.toHaveAttribute("data-count", "0");

  // 거절: 덧씌움에서 빠지고 팀 파일 그대로
  const reject = targetGroup.locator('[data-part="reject"]');
  await expect(reject).toBeEnabled();
  await reject.click();
  await expect(targetGroup).toHaveAttribute("data-decided", "true", { timeout: 60_000 });
  await expect(targetGroup.locator('[data-part="accept"]')).toHaveCount(0);
  expect(readBytes(shop, TARGET).equals(teamTarget)).toBe(true);
  expect(changes(shop.root).find((c) => c.id === targetChange?.id)?.state).toBe("rejected");
  // 양성 대조: 수락은 팀에 반영된다 (작업 사본 바이트)
  const accept = graphGroup.locator('[data-part="accept"]');
  await expect(accept).toBeEnabled();
  await accept.click();
  await expect(graphGroup).toHaveAttribute("data-decided", "true", { timeout: 60_000 });
  expect(readBytes(shop, GRAPH).equals(teamGraph)).toBe(false);
  expect(changes(shop.root).find((c) => c.id === graphChange?.id)?.state).toBe("accepted");
  expect(knowledgeFiles(shop.root, "adoptions").filter((a) => a.kind === "accept")).toHaveLength(1);
  await expect(page.locator('[data-part="status-reports"]')).toHaveAttribute("data-count", "0");
});

test("test_wizard_to_init", async () => {
  test.setTimeout(600_000);
  // 주 프로세스 E2E 훅의 가짜 QA CLI: 연결 시험(probe)이면 kb_project_info 한 번, Init이면 미지수 각본
  wiz = prepareWizardWorld(INIT_SCRIPT);
  s = await launchWizardApp(wiz);
  const { page } = s;
  // 0 시작 → 1 프로젝트 (실제 `kookabug workspace new`)
  await page.getByRole("button", { name: "새 프로젝트 만들기" }).click();
  await expectStep(page, 1);
  await stubOpenDialog(s.app, wiz.parent);
  await page.getByRole("button", { name: "찾아보기" }).click();
  await page.getByLabel("프로젝트 이름").fill("init-game");
  await pressNext(page, 2, 90_000);
  const root = path.join(wiz.parent, "init-game");
  roots.push(root);
  for (const rel of ["kookabug.json", "AGENTS.md", ".gitignore", path.join("wiki", "index.md")]) {
    expect(fs.existsSync(path.join(root, rel)), rel).toBe(true);
  }
  // 2 게임 → 3 점검 → 4 계정(건너뜀) → 5 Agent (직접 입력 + 연결 시험 = 실제 agent-job probe)
  await page.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  await pressNext(page, 3);
  await expect(page.locator('[data-part="check-list"] [data-check]').first()).toBeVisible({ timeout: 120_000 });
  await pressNext(page, 4, 120_000);
  await skipStep(page, 5);
  await expect(nextButton(page)).toBeDisabled(); // 시험 전
  await page.getByRole("radio", { name: /직접 입력/ }).check();
  await page.getByLabel("Agent 이름").fill("fakeqa");
  await page.getByLabel("Agent 명령줄").fill("fake-qa-agent");
  await page.getByRole("button", { name: "추가·시험" }).click();
  await expect(page.locator('[data-part="probe-card"]')).toHaveAttribute("data-state", "ok", { timeout: 120_000 });
  await pressNext(page, 6);
  const page2 = page;
  // 6 원본: 없는 경로 (Init이 미지수로 남긴다) → 7 → 8 → 9
  await page2.getByLabel("데이터 테이블").fill(path.join(wiz.dir, "no-such-table.csv"));
  await nextButton(page2).click();
  await expect(page2.locator('[data-source="data_table"]')).toHaveAttribute("data-state", "missing", { timeout: 30_000 });
  await pressNext(page2, 7);
  await pressNext(page2, 8);
  await pressNext(page2, 9);
  // 9 완료: Agent가 연결돼 Init이 켜져 있고 기본 선택
  const init = page2.locator('[data-first="init"] input');
  await expect(init).toBeEnabled();
  await expect(init).toBeChecked();
  await expect(nextButton(page2)).toHaveText(/Init 시작/);
  await nextButton(page2).click();

  // 보고함이 열리고 작업이 진행 중 → 끝난다 (실제 agent-job run --playbook init → 가짜 QA CLI)
  await expect(overlay(page2)).toHaveCount(0, { timeout: 30_000 });
  await expect(page2.locator('[data-part="reports-tab"]')).toBeVisible();
  await expect(page2.locator('[data-part="report-list"] li[data-state="running"]')).toHaveCount(1, { timeout: 60_000 });
  const row = page2.locator('[data-part="report-list"] li[data-job]').first();
  await expect(row).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  const detail = page2.locator('[data-part="report-detail"]');
  await expect(detail.locator('[data-kind="init_summary"]').first()).toBeVisible({ timeout: 30_000 });
  const job = readJson(path.join(root, "knowledge", "reports", `${await row.getAttribute("data-job")}.json`));
  expect(job).toMatchObject({ format: "kookabug.report/0", playbook: "init", state: "done" });

  // 질문(사람만 답할 수 있는 것만) — Agent가 더 알아볼 미지수는 질문으로 나오지 않는다
  const unknownsFile = path.join(root, "knowledge", "unknowns.json");
  const before = (readJson(unknownsFile).unknowns as Json[]).map((u) => [u.human_only, u.state]);
  expect(before).toEqual(expect.arrayContaining([[true, "open"], [false, "open"]]));
  const questions = detail.locator('[data-part="questions"] li[data-unknown]');
  await expect(questions).toHaveCount(1);
  await expect(questions).toContainText("데이터 테이블(data_table)은 어디에 있나요?");
  await expect(detail.getByText("상점 화면이 몇 개인가")).toHaveCount(0);
  // 답하기 (unknowns.answer, 사람 전용)
  const answer = questions.getByRole("button", { name: "답하기" });
  await expect(answer).toBeDisabled(); // 빈 답
  await questions.getByRole("textbox").fill("공유 폴더로 옮겼다");
  await expect(answer).toBeEnabled();
  await answer.click();
  await expect.poll(() => (readJson(unknownsFile).unknowns as Json[]).find((u) => u.human_only === true)?.state, { timeout: 30_000 }).toBe("answered");
  const answered = (readJson(unknownsFile).unknowns as Json[]).find((u) => u.human_only === true) as Json;
  expect(answered.answer).toMatchObject({ text: "공유 폴더로 옮겼다", by: "human" });
  expect((readJson(unknownsFile).unknowns as Json[]).find((u) => u.human_only === false)?.state).toBe("open");
  await expect(detail.locator('[data-part="questions"]')).toHaveCount(0, { timeout: 30_000 });
  const progress = readWizardFile(root);
  expect(progress.done).toEqual(expect.arrayContaining([1, 2, 3, 5, 6, 7, 8, 9]));
  expect(progress.skipped).toEqual([4]);
});

test("test_wizard_required_skip_resume_short", async () => {
  test.setTimeout(480_000);
  wiz = prepareWizardWorld();
  // 이어서: 3단계까지 마친 진행이 남아 있는 프로젝트 → 4단계부터
  const resumed = copySampleWorkspace("m8-resume");
  roots.push(resumed);
  writeWizardProgress(resumed, { step: 4, done: [1, 2, 3], skipped: [] });
  // 짧은 마법사 양성(팀 첫 설정을 마친 프로젝트)·음성(마치지 않은 프로젝트)
  const team = copySampleWorkspace("m8-team");
  const plain = copySampleWorkspace("m8-plain");
  roots.push(team, plain);
  fs.mkdirSync(path.join(team, "wiki"), { recursive: true });
  fs.writeFileSync(path.join(team, "wiki", "index.md"), "# 위키\n");

  // ── 필수 단계 잠금 (새 프로젝트 1단계: 건너뛰기 없음·만들기 꺼짐)
  s = await launchWizardApp(wiz, { width: 1440, height: 900 });
  await s.page.getByRole("button", { name: "새 프로젝트 만들기" }).click();
  await expectStep(s.page, 1);
  await expect(s.page.locator('[data-part="wizard-crumb"]')).toContainText("필수");
  await expect(nextButton(s.page)).toBeDisabled();
  await expect(overlay(s.page).getByRole("button", { name: "건너뛰기" })).toHaveCount(0);
  await s.page.locator('[data-part="wizard-close"]').click();
  await expect(overlay(s.page)).toHaveCount(0);

  // ── 이어서 + 건너뛰기 + Agent 없으면 녹화 기본
  await openProject(s, resumed);
  const page = s.page;
  await expectStep(page, 4, 30_000);
  await expect(overlay(page)).toHaveAttribute("data-mode", "new");
  // 4 계정: 선택 단계 — 키가 없으면 "다음" 꺼짐, 건너뛰기 있음
  await expect(page.locator('[data-part="wizard-crumb"]')).toContainText("선택");
  await expect(nextButton(page)).toBeDisabled();
  await skipStep(page, 5);
  // 5 Agent: 시험 전에는 "다음" 꺼짐 → 건너뛰기
  await expect(nextButton(page)).toBeDisabled();
  await skipStep(page, 6);
  // 양성 대조: 같은 "다음" 단추가 켜질 수 있는 단계 (6 원본 확인)
  await expect(nextButton(page)).toBeEnabled({ timeout: 30_000 });
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  await pressNext(page, 7);
  await pressNext(page, 8);
  await pressNext(page, 9);
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="4"]')).toHaveAttribute("data-skipped", "true");
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="5"]')).toHaveAttribute("data-skipped", "true");
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="6"]')).not.toHaveAttribute("data-skipped", "true");
  await expect(page.locator('[data-first="init"] input')).toBeDisabled();
  await expect(page.locator('[data-first="record"] input')).toBeChecked();
  await expect(page.locator('[data-part="connect-now"]')).toBeVisible();
  await nextButton(page).click();
  await expect(overlay(page)).toHaveCount(0);
  expect(readWizardFile(resumed)).toMatchObject({ skipped: [4, 5] });
  expect(readWizardFile(resumed).done).toEqual(expect.arrayContaining([1, 2, 3, 6, 7, 8, 9]));
  const userData = s.userData;
  await closeWizardApp(s);
  s = null;

  // ── 팀원 짧은 마법사: 음성(팀 첫 설정 전)은 띄우지 않는다
  s = await launchWizardApp(wiz, { userData, width: 1440, height: 900 });
  await openProject(s, plain);
  await expect(s.page.locator('[data-part="status-reports"]')).toBeVisible({ timeout: 30_000 });
  await s.page.waitForTimeout(2000);
  await expect(overlay(s.page)).toHaveCount(0);
  expect(fs.existsSync(path.join(plain, ".kookabug", "wizard.json"))).toBe(false);
  await closeWizardApp(s);
  s = null;
  // 양성: 팀 프로젝트는 빈 이 PC 단계(2·3·4·5)만, 6~8은 묻지 않는다
  s = await launchWizardApp(wiz, { userData, width: 1440, height: 900 });
  await openProject(s, team);
  const p2 = s.page;
  await expectStep(p2, 2, 30_000);
  await expect(overlay(p2)).toHaveAttribute("data-mode", "short");
  await expect(nextButton(p2)).toBeDisabled(); // 2 게임: 창을 잡기 전
  await p2.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(p2.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  await pressNext(p2, 3);
  await expect(p2.locator('[data-part="check-list"] [data-check]').first()).toBeVisible({ timeout: 120_000 });
  await pressNext(p2, 4, 120_000);
  await skipStep(p2, 5);
  await skipStep(p2, 9);
  await expect(p2.locator('[data-part="wizard-summary"] dd')).toHaveCount(4);
  await expect(p2.locator('[data-part="wizard-summary"] dd[data-step="6"]')).toHaveCount(0);
  await expect(p2.locator('[data-first="record"] input')).toBeChecked();
  await nextButton(p2).click();
  await expect(overlay(p2)).toHaveCount(0);
  expect(readWizardFile(team)).toMatchObject({ done: [2, 3, 9], skipped: [4, 5] });
});
