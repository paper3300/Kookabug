// 마법사·보고함 스크린샷 (M8 B7, 시안 Wizard5Agent·6Sources·9Init·9NoAgent, 시안이 없는 단계는 Setup*와 대비)
//   wizard0~2·5·6·9-dark  새 프로젝트 첫 실행 순서 0·1·2·(3)·5·6·9 (UX5) — 5단계는 가짜 QA CLI로 연결 시험 통과
//   wizard3-dark          3 환경 점검에 경고가 있어 화면에 머물 때만 (모두 통과하면 화면 없이 넘어간다 — UX5)
//   wizard9-noagent-dark  Agent 건너뜀 → Init 꺼짐 → "Kookabug 열기" 주 단추·녹화 보조 링크
//   reports-dark          9단계 Init 시작 뒤 보고함 (1440×900)
// 계정(4)·자동화 정책(7)·기록(8)은 UX5부터 첫 실행 흐름에 없고 설정 도우미에서만 연다 → 여기서 찍지 않는다
// 결과 build/ui-shots/<이름>-dark.png (reports는 시안 없음). wizard3은 찍혔을 때만 따로 비교한다(id는 compare.mjs에 있다).
// 시안 비교:
// node tools/design-ref/compare.mjs wizard0 wizard1 wizard2 wizard5 wizard6 wizard9 wizard9-noagent
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorld, closeWizardApp, expectStep, launchWizardApp, nextButton, overlay, prepareWizardWorld, pressNext, skipStep, type WizardSession, type WizardWorld } from "../helpers/wizard";

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

/**
 * 1→2→3 점검까지. 점검이 모두 통과하면 화면 없이 5로 넘어가고(UX5), 경고가 있으면 3에 머문다 — 머물면 찍고 "계속"으로 5.
 * 지난 실행의 wizard3 그림이 남아 오해하지 않게 머물지 않으면 지운다
 */
async function toStep5(page: Page, w: WizardWorld, name: string, take: boolean): Promise<void> {
  await page.getByRole("button", { name: "시작하기", exact: true }).click();
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
  await expect(nextButton(page)).toBeEnabled();
  await nextButton(page).click();
  // 3 점검: 결과가 나와 머물렀는지(stay), 모두 통과해 5로 넘어갔는지(skipped)
  let state = "wait";
  await expect
    .poll(
      async () => {
        const step = await overlay(page).getAttribute("data-step");
        if (step === "5") state = "skipped";
        else if (step === "3" && (await page.locator('[data-part="check-list"] [data-check]').count()) > 0) state = "stay";
        else state = "wait";
        return state;
      },
      { timeout: 180_000 },
    )
    .not.toBe("wait");
  if (state === "stay") {
    if (take) await shot(page, "wizard3");
    await pressNext(page, 5, 120_000);
  } else if (take) {
    fs.rmSync(path.join(OUT, "wizard3-dark.png"), { force: true });
  }
}

test("wizard shots", async () => {
  test.setTimeout(480_000);
  world = prepareWizardWorld();
  s = await launchWizardApp(world);
  const { page } = s;
  await setTheme(page, "dark");
  await shot(page, "wizard0");
  await toStep5(page, world, "sample-rpg", true);
  // 5 Agent: 검사 사용자 설정에 Agent가 없어 화면이 보인다 → 직접 입력해 연결 시험
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
  // 6 다음은 9 (7·8은 기본값으로 저장 — UX5)
  await pressNext(page, 9);
  await expect(page.locator('[data-part="wizard-defaults"]')).toHaveAttribute("data-state", "saved", { timeout: 30_000 });
  await expect(nextButton(page)).toHaveText(/Init 시작/);
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
  await toStep5(page, world, "sample-rpg", false);
  await skipStep(page, 6);
  // 6의 건너뛰기 단추는 "나중에"다 (UX5)
  await page.getByRole("button", { name: "나중에", exact: true }).click();
  await expectStep(page, 9);
  await expect(page.locator('[data-part="wizard-defaults"]')).toHaveAttribute("data-state", "saved", { timeout: 30_000 });
  await expect(page.locator('[data-first="init"]')).toHaveAttribute("data-disabled", "true");
  await expect(page.locator('[data-part="first-record"]')).toBeVisible();
  await expect(nextButton(page)).toHaveText(/Kookabug 열기/);
  await shot(page, "wizard9-noagent");
});
