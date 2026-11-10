// 마법사·보고함 스크린샷 (M8 B7, 시안 Wizard5Agent·6Sources·7Automation·9Init·9NoAgent, 시안이 없는 단계는 Setup*와 대비)
//   wizard0~9-dark        새 프로젝트 0→9 (5단계는 가짜 QA CLI로 연결 시험 통과)
//   wizard9-noagent-dark  Agent 건너뜀 → Init 꺼짐·녹화 기본
//   reports-dark          9단계 Init 시작 뒤 보고함 (1440×900)
// 결과 build/ui-shots/<이름>-dark.png → node tools/design-ref/compare.mjs wizard0 … wizard9 wizard9-noagent
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorld, closeWizardApp, expectStep, launchWizardApp, nextButton, prepareWizardWorld, pressNext, skipStep, type WizardSession, type WizardWorld } from "../helpers/wizard";

const OUT = path.join(REPO_BUILD, "ui-shots");

let s: WizardSession | null = null;
let world: WizardWorld | null = null;
let roots: string[] = [];

test.beforeEach(() => {
  fs.mkdirSync(OUT, { recursive: true });
});

test.afterEach(async () => {
  await closeWizardApp(s);
  s = null;
  await cleanupWorld(world, roots);
  world = null;
  roots = [];
});

async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  await page.mouse.move(2, 700);
  await page.screenshot({ path: path.join(OUT, `${name}-dark.png`) });
}

async function toStep3(page: Page, w: WizardWorld, name: string, take: boolean): Promise<void> {
  await page.getByRole("button", { name: "새 프로젝트 만들기" }).click();
  await expectStep(page, 1);
  await stubOpenDialog(s!.app, w.parent);
  await page.getByRole("button", { name: "찾아보기" }).click();
  await page.getByLabel("프로젝트 이름").fill(name);
  if (take) await shot(page, "wizard1");
  await pressNext(page, 2, 90_000);
  roots.push(path.join(w.parent, name));
  await page.locator('[data-part="window-list"] input[type="radio"]').first().check();
  await expect(page.locator('[data-part="game-preview"]')).toBeVisible({ timeout: 30_000 });
  if (take) await shot(page, "wizard2");
  await pressNext(page, 3);
  await expect(page.locator('[data-part="check-list"] [data-check]').first()).toBeVisible({ timeout: 120_000 });
  if (take) await shot(page, "wizard3");
}

test("wizard shots", async () => {
  test.setTimeout(480_000);
  world = prepareWizardWorld();
  s = await launchWizardApp(world);
  const { page } = s;
  await setTheme(page, "dark");
  await shot(page, "wizard0");
  await toStep3(page, world, "sample-rpg", true);
  await pressNext(page, 4, 120_000);
  await shot(page, "wizard4");
  await skipStep(page, 5);
  await page.getByRole("radio", { name: /직접 입력/ }).check();
  await page.getByLabel("Agent 이름").fill("Claude Code");
  await page.getByLabel("Agent 명령줄").fill("claude-code-acp");
  await page.getByRole("button", { name: "추가·시험" }).click();
  await expect(page.locator('[data-part="probe-card"]')).toHaveAttribute("data-state", "ok", { timeout: 120_000 });
  await shot(page, "wizard5");
  await pressNext(page, 6);
  await page.getByLabel("게임 코드").fill(world.dir);
  await page.getByLabel("데이터 테이블").fill(path.join(world.dir, "Data", "Tables"));
  await page.getByLabel("기획 문서").fill("https://wiki.example.com/sample-rpg");
  await page.getByLabel("패치 노트").fill("docs/patch-notes/");
  await nextButton(page).click();
  await expect(page.locator('[data-source="game_code"]')).toHaveAttribute("data-state", "ok", { timeout: 30_000 });
  await shot(page, "wizard6");
  await pressNext(page, 7);
  await shot(page, "wizard7");
  await page.getByLabel("금지 문구").fill("결제");
  await page.getByRole("button", { name: "+ 추가" }).click();
  await pressNext(page, 8);
  await shot(page, "wizard8");
  await pressNext(page, 9);
  await shot(page, "wizard9");
  // Init 시작 → 보고함 (앱 틀 크기로)
  await nextButton(page).click();
  await expect(page.locator('[data-part="reports-tab"]')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-part="report-list"] li[data-job]').first()).toHaveAttribute("data-state", "done", { timeout: 180_000 });
  await expect(page.locator('[data-part="report-detail"] [data-kind="init_summary"]').first()).toBeVisible({ timeout: 30_000 });
  await setContentSize(s.app, page, 1440, 900);
  await shot(page, "reports");
});

test("wizard no-agent shot", async () => {
  test.setTimeout(300_000);
  world = prepareWizardWorld();
  s = await launchWizardApp(world);
  const { page } = s;
  await setTheme(page, "dark");
  await toStep3(page, world, "sample-rpg", false);
  await pressNext(page, 4, 120_000);
  await skipStep(page, 5);
  await skipStep(page, 6);
  await skipStep(page, 7);
  await pressNext(page, 8);
  await pressNext(page, 9);
  await expect(page.locator('[data-first="record"] input')).toBeChecked();
  await shot(page, "wizard9-noagent");
});
