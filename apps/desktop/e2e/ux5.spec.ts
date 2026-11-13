// UX5 (설정 마법사 줄이기·Init 범위 줄이기·접속 경로 단계) E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) → 실제 `kookabug workspace
// new`·`doctor`·`agent-job run`(가짜 QA CLI 각본) → 실제 `kookabug secret set`(Windows 자격 증명 관리자, 검사 끝에 지운다).
// 실제 게임 입력·네트워크·실제 Agent CLI 없음. 샘플 게임만 쓴다
// - 새 마법사를 짧게: 1 프로젝트 → 2 게임 → (3 점검·5 Agent 자동 통과) → 6 원본 "나중에" → 9 "Init 시작"이 주 단추
// - 가짜 Agent Init: 사람 질문은 question_limit로 거부되고 게임 실행·게임 종료 서브그래프(작업 기준)를 만들고 보고
// - 보고 "접속 경로 만들기" → entry: 테스트 계정 질문 카드 → "테스트 계정 등록"(4단계) → 답함 → "이어서 진행"으로 entry 다시
// 샷: build/e2e/ux5-shots
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { DEFAULT_TEST_AGENT, REPO_BUILD, REPO_CLI, stubOpenDialog } from "./helpers/app";
import {
  cleanupWorld,
  closeWizardApp,
  expectStep,
  launchWizardApp,
  nextButton,
  overlay,
  pressNext,
  prepareWizardWorld,
  type WizardSession,
  type WizardWorld,
} from "./helpers/wizard";

const SCRIPT = path.join(import.meta.dirname, "fixtures", "qa-ux5.json");
const SHOTS = path.join(REPO_BUILD, "e2e", "ux5-shots");
const ID_VALUE = "ux5_tester";
const PASS_VALUE = "ux5-pass Zq81!";

let s: WizardSession | null = null;
let world: WizardWorld | null = null;
let roots: string[] = [];

test.afterEach(async () => {
  await closeWizardApp(s);
  s = null;
  // 검사가 자격 증명 관리자에 쓴 키를 지운다 (사람 PC에 남기지 않는다)
  for (const root of roots) {
    for (const key of ["login.id", "login.password"]) {
      spawnSync(REPO_CLI, ["secret", "delete", key, "--workspace", root, "--json"], { windowsHide: true, env: { ...process.env, ...(world?.env ?? {}) } });
    }
  }
  await cleanupWorld(world, roots);
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

function filesUnder(dir: string): string[] {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir, { recursive: true, withFileTypes: true }).filter((e) => e.isFile()).map((e) => path.join(e.parentPath, e.name));
}

/** 작업 폴더의 가짜 Agent 결과: 각본 단언이 모두 지났나 */
function fakeOk(root: string, job: string): Json {
  const fake = readJson(path.join(root, ".kookabug", "jobs", job, "fake.json"));
  expect(fake.failed, JSON.stringify(fake)).toBeUndefined();
  return fake;
}

test("새 마법사 짧게 → Init(질문 없이 실행·종료 서브그래프) → 접속 경로 → 계정 등록 → 이어서 진행", async () => {
  test.setTimeout(600_000);
  world = prepareWizardWorld(SCRIPT);
  // 기본 Agent가 있는 사용자 (프로젝트를 열면 자동 연결 대상 — 5단계를 건너뛴다). 권한 프리셋은 아직 없다
  fs.writeFileSync(
    path.join(world.env.KOOKABUG_USER_CONFIG_DIR, "settings.json"),
    JSON.stringify({ format: "kookabug.user-settings/0", agents: [DEFAULT_TEST_AGENT], default_agent: DEFAULT_TEST_AGENT.id }),
  );
  s = await launchWizardApp(world, { width: 1440, height: 900 });
  const { page } = s;
  await page.getByRole("button", { name: "시작하기", exact: true }).click();
  await expectStep(page, 1);
  await stubOpenDialog(s.app, world.parent);
  await page.getByRole("button", { name: "찾아보기" }).click();
  await page.getByLabel("프로젝트 이름").fill("ux5-game");
  await pressNext(page, 2, 90_000);
  const root = path.join(world.parent, "ux5-game");
  roots.push(root);
  // 진행 표시: 새 순서는 보이는 단계 6개(1·2·3·5·6·9) 중 2번째 — 4·7·8이 없다
  await expect(page.locator('[data-part="wizard-crumb"]')).toContainText("2 / 6");
  await expect(page.locator('[data-part="wizard-dots"] span')).toHaveCount(6);
  await page.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  await nextButton(page).click();

  // 3 점검: 모두 통과면 화면 없이 넘어가고, 경고가 있으면 머문다 (이 PC 환경에 따라 둘 다 맞다)
  await expect
    .poll(async () => {
      const step = await overlay(page).getAttribute("data-step");
      if (step === "3" && (await page.locator('[data-part="check-list"] [data-check]').count()) > 0) return "stay";
      return step === "6" ? "skipped" : "wait";
    }, { timeout: 180_000 })
    .not.toBe("wait");
  if ((await overlay(page).getAttribute("data-step")) === "3") {
    await expect(page.locator('[data-part="check-list"] [data-check][data-ok="false"]').first()).toBeVisible();
    await pressNext(page, 6, 60_000); // 5는 기본 Agent가 있어 화면 없이 지나간다
  }
  // 5 Agent는 보이지 않고 넘어갔다 → 6 원본 "나중에"
  await expectStep(page, 6, 60_000);
  await expect.poll(() => readJson(path.join(root, ".kookabug", "wizard.json")).done, { timeout: 15_000 }).toEqual(expect.arrayContaining([1, 2, 3, 5]));
  // 기본 Agent 자동 통과도 마법사 추천 프리셋을 저장한다 (무인 Init이 위키·그래프를 쓸 수 있게)
  const user = readJson(path.join(world.env.KOOKABUG_USER_CONFIG_DIR, "settings.json"));
  expect((user.permissions as Json | undefined)?.preset).toBe("curator");
  await expect(page.locator('[data-part="wizard-skip"]')).toHaveText("나중에");
  await page.locator('[data-part="wizard-skip"]').click();
  await expectStep(page, 9);

  // 9 완료: "Init 시작"이 주 단추, 녹화는 보조 링크, 뺀 단계는 기본값으로 저장 (금지 동작 빈 목록)
  await expect(nextButton(page)).toHaveText(/Init 시작/);
  // 5단계는 기본 Agent 연결 시험(실제 agent-job probe)을 통과해서 건너뛰었다 (검수 1 Mid)
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="5"]')).toContainText("연결 시험 통과");
  await expect(page.locator('[data-part="first-record"]')).toBeVisible();
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="4"]')).toHaveCount(0);
  await expect(page.locator('[data-part="wizard-summary"] dd[data-step="7"]')).toHaveCount(0);
  await expect(page.locator('[data-part="wizard-defaults"]')).toHaveAttribute("data-state", "saved", { timeout: 30_000 });
  const config = readJson(path.join(root, "kookabug.json"));
  expect(config.automation).toMatchObject({ format: "kookabug.automation/0", forbidden: [], budget: { minutes: 60, runs: 30 } });
  expect(config.cheats).toMatchObject({ enabled: true });
  expect(config.record).toMatchObject({ screenshots: "on", video: "failed_only" });
  await shot(page, "01-wizard-done");
  await nextButton(page).click();

  // Init: 보고함이 열리고 작업이 끝난다
  await expect(overlay(page)).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator('[data-part="reports-tab"]')).toBeVisible();
  const initRow = page.locator('[data-part="report-list"] li[data-job]').first();
  await expect(initRow).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  const initJob = String(await initRow.getAttribute("data-job"));
  fakeOk(root, initJob);
  // 서브그래프는 작업 기준(사람이 수락하기 전 사본)에 생겼다 — 팀 파일은 그대로
  const working = filesUnder(path.join(root, "knowledge", "working")).map((f) => f.replaceAll("\\", "/"));
  expect(working.some((f) => f.endsWith("files/subgraphs/common/game_launch.graph.json"))).toBe(true);
  expect(working.some((f) => f.endsWith("files/subgraphs/common/game_exit.graph.json"))).toBe(true);
  expect(fs.existsSync(path.join(root, "subgraphs", "common", "game_launch.graph.json"))).toBe(false);
  // Init은 사람 질문을 남기지 않았다
  expect(fs.existsSync(path.join(root, "knowledge", "unknowns.json")) ? (readJson(path.join(root, "knowledge", "unknowns.json")).unknowns as unknown[]) : []).toEqual([]);
  const initDetail = page.locator(`[data-part="report-detail"][data-job="${initJob}"]`);
  await expect(initDetail.locator('[data-kind="working_only"]').first()).toBeVisible({ timeout: 30_000 });
  await expect(initDetail.locator('[data-part="questions"]')).toHaveCount(0);
  // "다음: 게임 접속 경로 만들기"는 사람이 누른다 (자동으로 시작하지 않았다)
  await expect(page.locator('[data-part="report-list"] li[data-job]')).toHaveCount(1);
  await shot(page, "02-init-report");
  await initDetail.locator('[data-part="start-entry"]').click();

  // entry 첫 실행: 일반 질문은 거부되고 테스트 계정 질문 하나
  const entryRow = page.locator('[data-part="report-list"] li[data-job]').first();
  await expect.poll(async () => entryRow.getAttribute("data-job"), { timeout: 60_000 }).not.toBe(initJob);
  await expect(entryRow).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  const entryJob = String(await entryRow.getAttribute("data-job"));
  fakeOk(root, entryJob);
  const entryDetail = page.locator(`[data-part="report-detail"][data-job="${entryJob}"]`);
  const card = entryDetail.locator('[data-part="questions"] li[data-kind="credential"]');
  await expect(card).toHaveCount(1, { timeout: 30_000 });
  await expect(card).toContainText("login.password");
  // 글 입력 칸·답 보내기 없이 "테스트 계정 등록" 단추만
  await expect(entryDetail.locator('[data-part="questions"] textarea')).toHaveCount(0);
  await expect(entryDetail.locator('[data-part="send-answers"]')).toHaveCount(0);
  await expect(entryDetail.locator('[data-part="feature-test-hint"]')).toHaveCount(0); // 계정을 기다리는 중
  await shot(page, "03-credential-card");
  await card.locator('[data-part="register-credential"]').click();

  // 4단계 계정 화면 (질문의 키를 채워서)
  await expectStep(page, 4);
  await expect(overlay(page)).toHaveAttribute("data-mode", "only");
  await expect(page.locator('[data-part="credential-ask"]')).toBeVisible();
  await expect(nextButton(page)).toBeDisabled();
  await page.getByLabel("값: login.id").fill(ID_VALUE);
  await page.getByLabel("값: login.password").fill(PASS_VALUE);
  await shot(page, "04-register");
  await expect(nextButton(page)).toBeEnabled();
  await nextButton(page).click();
  await expect(overlay(page)).toHaveCount(0, { timeout: 60_000 });

  // 질문이 답함이 됐고, 값은 워크스페이스 어디에도 없다 (자격 증명 관리자에만)
  const unknown = (readJson(path.join(root, "knowledge", "unknowns.json")).unknowns as Json[])[0];
  expect(unknown).toMatchObject({ kind: "credential", state: "answered" });
  expect(String((unknown.answer as Json).text)).toContain("login.password");
  let scanned = 0;
  for (const file of filesUnder(root)) {
    let data: Buffer;
    try {
      data = fs.readFileSync(file);
    } catch {
      continue; // daemon이 쥔 잠금 파일
    }
    scanned += 1;
    expect(data.includes(Buffer.from(PASS_VALUE)), file).toBe(false);
  }
  expect(scanned).toBeGreaterThan(10); // 양성 대조: 실제로 훑었다
  await expect(card).toHaveCount(0, { timeout: 30_000 });

  // "이어서 진행" = entry를 다시 이어 간다
  const followup = entryDetail.locator('[data-part="followup-row"]');
  await expect(followup).toHaveAttribute("data-playbook", "entry");
  await followup.locator('[data-part="followup"]').click();
  const againRow = page.locator('[data-part="report-list"] li[data-job]').first();
  await expect.poll(async () => againRow.getAttribute("data-job"), { timeout: 60_000 }).not.toBe(entryJob);
  await expect(againRow).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  const againJob = String(await againRow.getAttribute("data-job"));
  fakeOk(root, againJob);
  const againDetail = page.locator(`[data-part="report-detail"][data-job="${againJob}"]`);
  await expect(againDetail).toContainText("entry");
  await expect(againDetail.locator('[data-part="feature-test-hint"]')).toBeVisible({ timeout: 30_000 });
  await shot(page, "05-entry-done");
});
