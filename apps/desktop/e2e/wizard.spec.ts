// 첫 프로젝트 설정 마법사 E2E (M8 계획 3.17·B7): 새 프로젝트 0→9, 필수 단계 "다음" 꺼짐, 건너뛴 단계 요약·다시 열기,
// 중간에 닫고 이어서, Agent 건너뜀 → 녹화 기본 → "지금 연결" → 연결 시험 → Init → 보고함, 팀원 짧은 마법사.
// 실제 앱 → 실제 daemon(가짜 플랫폼) → 실제 `kookabug workspace new`·`doctor`·`agent-job`(가짜 QA CLI)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { stubOpenDialog } from "./helpers/app";
import { showAgentTab } from "./helpers/agent";
import { cleanupWorkspace, copySampleWorkspace } from "./helpers/daemon";
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
  type WizardSession,
  type WizardWorld,
} from "./helpers/wizard";

let s: WizardSession | null = null;
let world: WizardWorld | null = null;
/** 검사가 연 워크스페이스 (끝에 daemon을 끈다) */
let roots: string[] = [];

test.afterEach(async () => {
  await closeWizardApp(s);
  s = null;
  await cleanupWorld(world, roots);
  for (const r of roots.filter((x) => !world || !x.startsWith(world.dir))) await cleanupWorkspace(r);
  world = null;
  roots = [];
});

test("새 프로젝트 0→9: 필수 단계 잠금·중간 닫고 이어서·건너뛴 단계·Agent 없으면 녹화 기본·지금 연결·Init", async () => {
  test.setTimeout(420_000);
  world = prepareWizardWorld();
  s = await launchWizardApp(world);
  const { page } = s;
  await page.getByRole("button", { name: "시작하기", exact: true }).click();
  await expectStep(page, 1);
  // 1 프로젝트: 위치를 고르기 전에는 "만들기"가 꺼져 있다 (필수 단계)
  await expect(nextButton(page)).toBeDisabled();
  await overlay(page).getByRole("button", { name: "‹ 이전" }).click();
  await expectStep(page, 0); // 0단계 = 새 / 열기
  await expect(nextButton(page)).toBeDisabled();
  await page.getByRole("button", { name: /새 프로젝트 만들기/ }).last().click();
  await expectStep(page, 1);
  await stubOpenDialog(s.app, world.parent);
  await page.getByRole("button", { name: "찾아보기" }).click();
  await page.getByLabel("프로젝트 이름").fill("my-game");
  await pressNext(page, 2, 90_000);
  const root = path.join(world.parent, "my-game");
  roots.push(root);
  expect(fs.existsSync(path.join(root, "kookabug.json"))).toBe(true);
  expect(fs.existsSync(path.join(root, "wiki", "index.md"))).toBe(true);
  // 1단계를 마치면 wizard.json에 남기 시작한다 (단계 상태만 — 화면이 먼저 넘어가고 저장이 뒤따른다)
  await expect.poll(() => fs.existsSync(path.join(root, ".kookabug", "wizard.json")), { timeout: 15_000 }).toBe(true);
  expect(readWizardFile(root)).toMatchObject({ format: "kookabug.wizard/0", step: 2, done: [1] });
  expect(Object.keys(readWizardFile(root)).sort()).toEqual(["done", "format", "skipped", "step", "warnings"]);

  // 2 게임: 창을 잡기 전에는 "연결"이 꺼져 있다
  await expect(nextButton(page)).toBeDisabled();
  // 프로젝트를 만든 뒤에는 0·1로 못 간다 (양성 대조: 1단계에서는 위에서 눌렀다)
  await expect(overlay(page).locator("footer, div").getByRole("button", { name: "‹ 이전", includeHidden: true })).toBeDisabled();
  await page.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  await expect(nextButton(page)).toBeEnabled();
  await nextButton(page).click();
  await expect.poll(async () => overlay(page).getAttribute("data-step"), { timeout: 60_000 }).not.toBe("2");
  const config = JSON.parse(fs.readFileSync(path.join(root, "kookabug.json"), "utf8")) as Record<string, Record<string, unknown>>;
  expect(config.settings["game.title"]).toBeTruthy();

  // 3 점검: 모두 통과면 화면 없이 넘어가고(UX5), 경고가 있으면 머물러 "계속" (경고가 있어도 진행)
  await passCheck(page, 5);

  // (UX5: 4 계정은 첫 실행 흐름에 없다) 5 Agent: 사용자 설정에 Agent가 없어 보인다. 시험 전에는 "다음"이 꺼져 있다 → 건너뛰기
  await expect(nextButton(page)).toBeDisabled();
  await skipStep(page, 6);

  // 6에서 중간에 닫는다 → 진행은 wizard.json에 남는다
  await page.locator('[data-part="wizard-close"]').click();
  await expect(overlay(page)).toHaveCount(0);
  expect(readWizardFile(root)).toMatchObject({ step: 6, done: [1, 2, 3], skipped: [5] });
  const userData = s.userData;
  await closeWizardApp(s);
  s = null;

  // 다시 열면 6단계부터 이어서
  s = await launchWizardApp(world, { userData });
  await openProject(s, root);
  const page2 = s.page;
  await expectStep(page2, 6, 30_000);
  await expect(overlay(page2)).toHaveAttribute("data-mode", "new");
  // 6 원본: 없는 경로 → 확인 → 경고로 남기고 다음
  await page2.getByLabel("데이터 테이블").fill(path.join(world.dir, "no-such-table.csv"));
  await nextButton(page2).click();
  await expect(page2.locator('[data-source="data_table"]')).toHaveAttribute("data-state", "missing", { timeout: 30_000 });
  await expect(page2.getByText("읽지 못한 1개는 경고로 남기고")).toBeVisible();
  // (UX5: 7 자동화·8 기록은 첫 실행 흐름에 없다 — 6 다음은 9, 기본값으로 저장)
  await pressNext(page2, 9);
  await expect(page2.locator('[data-part="wizard-defaults"]')).toHaveAttribute("data-state", "saved", { timeout: 30_000 });
  const after = JSON.parse(fs.readFileSync(path.join(root, "kookabug.json"), "utf8")) as Record<string, Record<string, unknown>>;
  expect(after.automation).toMatchObject({ format: "kookabug.automation/0", forbidden: [], budget: { minutes: 60, runs: 30 } });
  expect((after.automation.auto_repair as Record<string, unknown>).enabled).toBe(true);
  expect(after.cheats).toMatchObject({ enabled: true });
  expect(after.record).toMatchObject({ screenshots: "on", video: "failed_only" });
  expect(after.sources).toEqual([{ id: "data_table", kind: "data", title: "데이터 테이블", local: true }]);
  // 금지 동작이 비어 있는 것은 기본값이라 경고가 아니다 (UX5)
  await expect
    .poll(() => readWizardFile(root).warnings, { timeout: 15_000 })
    .toEqual(expect.arrayContaining([{ step: 6, code: "source_missing:data_table" }]));
  expect(readWizardFile(root).warnings).not.toContainEqual({ step: 7, code: "forbidden_empty" });

  // 9 완료: 건너뛴 단계 요약·Agent 없으면 Init 꺼짐 → "Kookabug 열기"가 주 단추, 녹화는 보조 링크
  await expect(page2.locator('[data-part="wizard-summary"] dd[data-step="4"]')).toHaveCount(0);
  await expect(page2.locator('[data-part="wizard-summary"] dd[data-step="5"]')).toHaveAttribute("data-skipped", "true");
  await expect(page2.locator('[data-first="init"]')).toHaveAttribute("data-disabled", "true");
  await expect(page2.locator('[data-part="first-record"]')).toBeVisible();
  await expect(nextButton(page2)).toHaveText(/Kookabug 열기/);

  // 지금 연결 → 5단계(직접 입력한 Agent, 연결 시험 = 주 프로세스 agent-job probe) → 9로
  await page2.locator('[data-part="connect-now"]').click();
  await expectStep(page2, 5);
  await page2.getByRole("radio", { name: /직접 입력/ }).check();
  await page2.getByLabel("Agent 이름").fill("fakeqa");
  await page2.getByLabel("Agent 명령줄").fill("fake-qa-agent");
  await page2.getByRole("button", { name: "추가·시험" }).click();
  await expect(page2.locator('[data-part="probe-card"]')).toHaveAttribute("data-state", "ok", { timeout: 120_000 });
  await pressNext(page2, 9);
  await expect(page2.locator('[data-first="init"]')).toHaveAttribute("data-disabled", "false");
  await expect(nextButton(page2)).toHaveText(/Init 시작/);
  await nextButton(page2).click();
  // 마법사가 닫히고 보고함이 열린다 → 작업이 끝나 보고가 생긴다
  await expect(overlay(page2)).toHaveCount(0, { timeout: 30_000 });
  await expect(page2.locator('[data-part="reports-tab"]')).toBeVisible();
  const row = page2.locator('[data-part="report-list"] li[data-job]').first();
  await expect(row).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  await expect(page2.locator('[data-part="report-detail"] [data-kind="init_summary"]').first()).toBeVisible({ timeout: 30_000 });
  const done = readWizardFile(root);
  expect(done.done).toEqual(expect.arrayContaining([1, 2, 3, 5, 6, 9]));
  expect(done.skipped).toEqual([]);
});

/** 3 점검: 모두 통과면 화면 없이 `next`로(UX5), 경고가 있으면 머문 화면에서 "계속" */
async function passCheck(page: Page, next: number): Promise<void> {
  await expect
    .poll(
      async () => {
        const step = await overlay(page).getAttribute("data-step");
        if (step === String(next)) return "skipped";
        return step === "3" && (await page.locator('[data-part="check-list"] [data-check]').count()) > 0 ? "stay" : "wait";
      },
      { timeout: 180_000 },
    )
    .not.toBe("wait");
  if ((await overlay(page).getAttribute("data-step")) === "3") await pressNext(page, next, 120_000);
}

// B7 검수 재현 (라운드 2): 다시 연 단계가 이 PC 원본을 지우지 않고, 화면을 연 뒤 바뀐 설정을 덮어쓰지 않는다
function writeJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify(value, null, 2)}\n`);
}

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
}

/** 저장된 마법사 진행을 `step`에 둔 예제 프로젝트 */
function resumeAt(name: string, step: number, done: number[]): string {
  const root = copySampleWorkspace(name);
  roots.push(root);
  writeJson(path.join(root, ".kookabug", "wizard.json"), { format: "kookabug.wizard/0", step, done, skipped: [4, 5], warnings: [] });
  return root;
}

test("review_local_sources_preserved_when_reopening_step6", async () => {
  test.setTimeout(180_000);
  world = prepareWizardWorld();
  const root = resumeAt("src6", 6, [1, 2, 3]);
  const codeDir = path.join(world.dir, "game-src");
  fs.mkdirSync(codeDir);
  const configFile = path.join(root, "kookabug.json");
  const config = readJson(configFile);
  config.sources = [...(config.sources as unknown[]), { id: "game_code", kind: "code", title: "게임 코드", local: true }];
  writeJson(configFile, config);
  const localFile = path.join(root, ".kookabug", "local.json");
  writeJson(localFile, { format: "kookabug.local/0", sources: { game_code: { path: codeDir } } });
  const teamBefore = readJson(configFile).sources;
  const localBefore = readJson(localFile).sources;
  // 양성 대조: 초기 팀 설정과 이 PC 경로가 실제로 있다 (빈 배열끼리 같아서 통과하지 않게)
  expect(teamBefore).toContainEqual({ id: "game_code", kind: "code", title: "게임 코드", local: true });
  expect(localBefore).toEqual({ game_code: { path: codeDir } });

  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 6, 30_000);
  // 초기 읽기가 끝나야 확인을 누를 수 있다 (읽는 중·실패면 꺼짐)
  await expect(page.locator('[data-part="source-list"]')).toBeVisible();
  await page.waitForTimeout(1500);
  // 아무것도 지우지 않고 확인 → 결과를 보여 준 뒤("다음")
  await expect(nextButton(page)).toBeEnabled({ timeout: 15_000 });
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  expect(readJson(configFile).sources).toEqual(teamBefore);
  expect(readJson(localFile).sources).toEqual(localBefore);
  // 이 PC 경로를 사람 전용 읽기(wizard.get)로 채웠다
  await expect(page.getByLabel("게임 코드")).toHaveValue(codeDir);
  await expect(page.locator('[data-source="game_code"]')).toHaveAttribute("data-state", "ok");

  // 사람이 칸을 비운 항목만 지운다 (양성 대조: 지우기가 실제로 동작)
  await page.getByLabel("게임 코드").fill("");
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  expect(readJson(configFile).sources).toEqual((teamBefore as { id: string }[]).filter((x) => x.id !== "game_code"));
  expect(readJson(localFile).sources).toEqual({});
});

test("review_duplicate_source_id_preserves_hidden_user_source_on_save", async () => {
  test.setTimeout(180_000);
  world = prepareWizardWorld();
  const root = resumeAt("dup6", 6, [1, 2, 3]);
  const configFile = path.join(root, "kookabug.json");
  const config = readJson(configFile);
  // 키는 daemon이 쓰는 정규 순서(정렬)로 둔다 — 저장 뒤 두 항목의 바이트를 그대로 비교한다
  const hidden = { id: "game_code", kind: "other", path: "sources/first", title: "review-hidden-source" };
  const visible = { id: "game_code", kind: "code", path: "sources/second", title: "review-visible-source" };
  config.sources = [...(config.sources as unknown[]), hidden, visible];
  writeJson(configFile, config);
  const dupBefore = JSON.stringify((readJson(configFile).sources as { id: string }[]).filter((x) => x.id === "game_code"));
  expect(JSON.parse(dupBefore)).toEqual([hidden, visible]); // 양성 대조: 두 항목이 실제로 있다

  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 6, 30_000);
  await expect(page.getByLabel("게임 코드")).toHaveValue("sources/second", { timeout: 15_000 });
  await expect(nextButton(page)).toBeEnabled({ timeout: 15_000 });
  // 고치기 전 화면은 이 칸을 바꿀 수 있었다 (검수 재현) — 고친 뒤에는 읽기 전용
  const code = page.getByLabel("게임 코드");
  if (await code.isEditable()) await code.fill("sources/third");
  // 다른 칸은 정상 저장된다
  await page.getByLabel("QA 시트").fill("https://example.invalid/review-qa");
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  const after = readJson(configFile).sources as { id: string }[];
  // 같은 ID 원본 둘이 그대로 (경로·종류·제목)
  expect(JSON.stringify(after.filter((x) => x.id === "game_code"))).toBe(dupBefore);
  await expect(page.locator('[data-source="game_code"] [data-part="source-duplicate"]')).toContainText(
    "같은 ID의 원본이 여러 개예요 — kookabug.json에서 정리해 주세요",
  );
  await expect(code).not.toBeEditable();
  expect(after).toContainEqual({ id: "qa_sheet", kind: "qa_sheet", title: "QA 시트", url: "https://example.invalid/review-qa" });
});

test("review_step7_refuses_policy_changed_after_display", async () => {
  test.setTimeout(180_000);
  world = prepareWizardWorld();
  const root = resumeAt("auto7", 7, [1, 2, 3, 6]);
  const configFile = path.join(root, "kookabug.json");
  s = await launchWizardApp(world);
  await openProject(s, root);
  const { page } = s;
  await expectStep(page, 7, 30_000);
  await expect(page.locator('[data-part="forbidden-list"]')).toContainText("결제", { timeout: 15_000 });
  // 화면을 연 뒤 다른 곳에서 금지 동작을 바꾼다
  const config = readJson(configFile);
  (config.automation as Record<string, unknown>).forbidden = [{ kind: "text", value: "review-new-forbidden" }];
  writeJson(configFile, config);
  expect((readJson(configFile).automation as Record<string, unknown>).forbidden).toEqual([{ kind: "text", value: "review-new-forbidden" }]);
  await expect(nextButton(page)).toBeEnabled();
  await nextButton(page).click();
  const notice = page.locator('[data-part="wizard-conflict"]');
  // (UX5: 옛 순서 7에서 이어 가면 다음은 9 — 8 기록은 첫 실행 흐름에 없다)
  await expect.poll(async () => (await notice.count()) > 0 || (await overlay(page).getAttribute("data-step")) === "9", { timeout: 30_000 }).toBe(true);
  // 디스크의 새 금지 문구가 보존된다
  expect((readJson(configFile).automation as Record<string, unknown>).forbidden).toEqual([{ kind: "text", value: "review-new-forbidden" }]);
  await expect(notice).toContainText("다른 곳에서 설정이 바뀌었어요");
  await expect(overlay(page)).toHaveAttribute("data-step", "7");
  // 양성 대조: 다시 읽은 뒤 확인하면 저장되고 새 문구가 그대로다
  await notice.getByRole("button", { name: "다시 읽기" }).click();
  await expect(page.locator('[data-part="forbidden-list"]')).toContainText("review-new-forbidden", { timeout: 15_000 });
  await expect(notice).toHaveCount(0);
  await pressNext(page, 9);
  const after = readJson(configFile).automation as Record<string, unknown>;
  expect(after.forbidden).toEqual([{ kind: "text", value: "review-new-forbidden" }]);
  expect(after.budget).toEqual({ minutes: 60, runs: 30 }); // 7단계 저장이 실제로 일어났다
});

test("팀원 짧은 마법사: 팀 설정을 마친 프로젝트를 이 PC에서 처음 열면 빈 단계만, 끝나면 다시 띄우지 않는다", async () => {
  test.setTimeout(300_000);
  world = prepareWizardWorld();
  // 양성·음성 대조용 두 프로젝트: wiki/index.md(팀 첫 설정 끝)가 있는 것과 없는 것
  const plain = copySampleWorkspace("plain");
  const team = copySampleWorkspace("team");
  roots.push(plain, team);
  fs.mkdirSync(path.join(team, "wiki"), { recursive: true });
  fs.writeFileSync(path.join(team, "wiki", "index.md"), "# 위키\n");
  s = await launchWizardApp(world, { width: 1440, height: 900 });
  // 음성: 팀 첫 설정 전 프로젝트는 짧은 마법사를 띄우지 않는다 (상태 바가 붙고 보고함 단추가 보일 때까지 기다린 뒤 확인).
  // 에이전트 미설정이라 5단계만 뜬다 (자동 화면은 하나)
  await openProject(s, plain);
  await expect(s.page.locator('[data-part="status-reports"]')).toBeVisible({ timeout: 30_000 });
  await s.page.waitForTimeout(2000);
  await expect(overlay(s.page)).toHaveCount(1);
  await expect(overlay(s.page)).toHaveAttribute("data-mode", "only");
  await expectStep(s.page, 5);
  const userData = s.userData;
  await closeWizardApp(s);
  s = null;
  // 양성: 팀 프로젝트는 빈 이 PC 단계(게임 2·점검 3·Agent 5 — UX5부터 계정 4는 묻지 않는다)만
  s = await launchWizardApp(world, { userData, width: 1440, height: 900 });
  await openProject(s, team);
  const { page } = s;
  await expectStep(page, 2, 30_000);
  await expect(overlay(page)).toHaveAttribute("data-mode", "short");
  await expect(page.locator('[data-part="wizard-crumb"]')).toContainText("게임");
  await page.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  await nextButton(page).click();
  await passCheck(page, 5);
  await skipStep(page, 9); // 짧은 마법사는 6~8(팀 설정)을 묻지 않는다
  await expect(page.locator('[data-part="wizard-summary"] dd')).toHaveCount(3);
  await nextButton(page).click();
  await expect(overlay(page)).toHaveCount(0);
  expect(readWizardFile(team)).toMatchObject({ done: [2, 3, 9], skipped: [5] });
  await closeWizardApp(s);
  s = null;
  // 끝났으면 다시 열어도 띄우지 않는다
  s = await launchWizardApp(world, { userData, width: 1440, height: 900 });
  await openProject(s, team);
  await expect(s.page.locator('[data-part="status-reports"]')).toBeVisible({ timeout: 30_000 });
  await s.page.waitForTimeout(2000);
  await expect(overlay(s.page)).toHaveCount(0);
});

/**
 * 자동으로 뜨는 설정 화면은 하나 (M8 R11): 옛 에이전트 첫 설정 대화 상자(`agent-setup`)는 없어졌고, 짧은 마법사 조건이
 * 양성이면 마법사 겹 화면 1개·옛 대화 상자 0개. 음성이고 에이전트 미설정이면 5단계 only 1개(닫으면 건너뜀, 다시 열면 0).
 * 세 경우 모두 사용자 설정에 에이전트가 없다(에이전트 미설정)
 */
test("test_auto_open_single_screen_new_team_and_no_agent", async () => {
  test.setTimeout(360_000);
  world = prepareWizardWorld();
  const oldDialog = (page: Page) => page.locator('[data-part="agent-setup"]');
  /** 상태 바가 붙은 뒤 늦게 뜨는 화면까지 기다렸다가 센다 */
  const settle = async (page: Page) => {
    await expect(page.locator('[data-part="status-reports"]')).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(2500);
  };
  const plain = copySampleWorkspace("noagent");
  const team = copySampleWorkspace("member");
  roots.push(plain, team);
  fs.mkdirSync(path.join(team, "wiki"), { recursive: true });
  fs.writeFileSync(path.join(team, "wiki", "index.md"), "# 위키\n");
  expect(fs.readdirSync(world.env.KOOKABUG_USER_CONFIG_DIR)).toEqual([]); // 에이전트 미설정

  // ① 에이전트 미설정 + 팀 첫 설정 전 프로젝트: 짧은 마법사 음성 → 5단계 only 화면 1·옛 대화 상자 0 (늦게 뜨는 것도 없다)
  s = await launchWizardApp(world, { width: 1440, height: 900 });
  const userData = s.userData;
  await openProject(s, plain);
  await settle(s.page);
  await expect(overlay(s.page)).toHaveCount(1);
  await expectStep(s.page, 5);
  await expect(overlay(s.page)).toHaveAttribute("data-mode", "only");
  await expect(oldDialog(s.page)).toHaveCount(0);
  // 닫으면 건너뜀으로 남는다
  await s.page.locator('[data-part="wizard-close"]').click();
  await expect(overlay(s.page)).toHaveCount(0);
  await expect.poll(() => (fs.existsSync(path.join(plain, ".kookabug", "wizard.json")) ? readWizardFile(plain).skipped : null)).toEqual([5]);
  // 에이전트 패널 "설정 도우미 열기"는 같은 화면(5단계 only)을 연다 (옛 대화 상자 아님)
  const panel = await showAgentTab(s.page);
  await panel.locator('[data-part="open-agent-setup"]').click();
  await expect(overlay(s.page)).toHaveCount(1);
  await expectStep(s.page, 5);
  await expect(overlay(s.page)).toHaveAttribute("data-mode", "only");
  await expect(oldDialog(s.page)).toHaveCount(0);
  await s.page.locator('[data-part="wizard-close"]').click();
  await expect(overlay(s.page)).toHaveCount(0);
  await closeWizardApp(s);
  s = null;
  // ①' 닫고 다시 열면 0 (5단계 건너뜀 기록, 팀 첫 설정 전이라 짧은 마법사도 없음)
  s = await launchWizardApp(world, { userData, width: 1440, height: 900 });
  await openProject(s, plain);
  await settle(s.page);
  await expect(overlay(s.page)).toHaveCount(0);
  await expect(oldDialog(s.page)).toHaveCount(0);
  await closeWizardApp(s);
  s = null;

  // ② 팀원 첫 열기: 양성 → 마법사 1·옛 대화 상자 0 (늦게 뜨는 것도 없다)
  s = await launchWizardApp(world, { userData, width: 1440, height: 900 });
  await openProject(s, team);
  await expectStep(s.page, 2, 30_000);
  await settle(s.page);
  await expect(overlay(s.page)).toHaveCount(1);
  await expect(overlay(s.page)).toHaveAttribute("data-mode", "short");
  await expect(oldDialog(s.page)).toHaveCount(0);
  await closeWizardApp(s);
  s = null;

  // ③ 새 워크스페이스(시작하기 → 1단계 만들기): 양성 → 새 프로젝트 마법사 1·옛 대화 상자 0 (짧은 마법사가 겹치지 않는다)
  s = await launchWizardApp(world, { userData, width: 1440, height: 900 });
  const { page } = s;
  await page.getByRole("button", { name: "시작하기", exact: true }).click();
  await expectStep(page, 1);
  await stubOpenDialog(s.app, world.parent);
  await page.getByRole("button", { name: "찾아보기" }).click();
  await page.getByLabel("프로젝트 이름").fill("fresh");
  await pressNext(page, 2, 90_000);
  roots.push(path.join(world.parent, "fresh"));
  await settle(page);
  await expect(overlay(page)).toHaveCount(1);
  await expect(overlay(page)).toHaveAttribute("data-mode", "new");
  await expectStep(page, 2);
  await expect(oldDialog(page)).toHaveCount(0);
});
