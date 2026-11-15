// UX7 보고함 E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) → 실제 `agent-job run`(가짜 QA CLI 각본 qa-ux7) → 실제 `kookabug secret set`
// (Windows 자격 증명 관리자, 검사 끝에 지운다). 실제 게임 입력·네트워크·실제 Agent CLI 없음
// - 진행 중 머리: 단계·하는 일(kb_job_progress), 기다림 이유("테스트 계정 등록을 기다리는 중" — kb_question_wait)
// - 진행 중 작업에서 테스트 계정 등록: 보고가 생기기 전에 질문 카드의 "테스트 계정 등록" → 작업이 바로 이어 간다
// - 목록 줄: 끝난 작업의 한 줄 결과(kb_report_note headline)
// 샷: build/e2e/ux7-shots
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, REPO_CLI, setContentSize, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, waitConnected } from "./helpers/daemon";
import { cleanupShopWorld, prepareShopWorld, runAgentJob, type ShopWorld } from "./helpers/reports";
import { expectStep, nextButton, overlay } from "./helpers/wizard";

const SCRIPT = path.join(import.meta.dirname, "fixtures", "qa-ux7.json");
const SHOTS = path.join(REPO_BUILD, "e2e", "ux7-shots");
const ID_VALUE = "ux7_tester";
const PASS_VALUE = "ux7-pass Wq92!";

let app: ElectronApplication | null = null;
let world: ShopWorld | null = null;

test.afterEach(async () => {
  await closeApp(app ?? undefined);
  app = null;
  if (world !== null) {
    // 검사가 자격 증명 관리자에 쓴 키를 지운다 (사람 PC에 남기지 않는다)
    for (const key of ["login.id", "login.password"]) {
      spawnSync(REPO_CLI, ["secret", "delete", key, "--workspace", world.root, "--json"], {
        windowsHide: true,
        env: { ...process.env, ...world.env },
      });
    }
    await cleanupWorkspace(world.root);
  }
  cleanupShopWorld(world);
  world = null;
});

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test("진행 중 머리(단계·기다림) → 진행 중에 테스트 계정 등록 → 작업이 이어 가 한 줄 결과", async () => {
  test.setTimeout(600_000);
  world = prepareShopWorld("moved");
  const launched = await launchApp({ env: world.env, scaleFactor: 1 });
  app = launched.app;
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, world.root);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(page);

  const running = runAgentJob(world, SCRIPT, "entry");
  await page.locator('[data-part="status-reports"]').click();
  const row = page.locator('[data-part="report-list"] li[data-state="running"]');
  await expect(row).toHaveCount(1, { timeout: 90_000 });
  await row.locator("button").first().click();

  // 진행 중 머리: 단계·하는 일, 기다림 이유 (목록 줄에도 단계)
  const head = page.locator('[data-part="job-head"]');
  await expect(head.locator('[data-part="job-progress"]')).toHaveText("3/5 한 세션으로 걷기 — 로그인 팝업 — 계정 기다리는 중", { timeout: 90_000 });
  await expect(head.locator('[data-part="job-waiting"]')).toHaveText("테스트 계정 등록을 기다리는 중", { timeout: 30_000 });
  await expect(row.locator('[data-part="row-sub"]')).toContainText("3/5 한 세션으로 걷기");
  // 활동 목록: 기다림은 MCP 호출 한 번 = 한 줄 (안쪽 폴링을 세지 않는다)
  const list = page.locator('[data-part="activity-list"]');
  await expect(list).toContainText("단계 시작", { timeout: 30_000 });

  // 보고가 생기기 전에도 질문 카드의 "테스트 계정 등록"
  const card = page.locator('[data-part="live-questions"] li[data-kind="credential"]');
  await expect(card).toHaveCount(1, { timeout: 30_000 });
  await expect(card).toContainText("login.password");
  await shot(page, "01-running-waiting");
  await card.locator('[data-part="register-credential"]').click();
  await expectStep(page, 4);
  await expect(page.locator('[data-part="credential-ask"]')).toBeVisible();
  await page.getByLabel("값: login.id").fill(ID_VALUE);
  await page.getByLabel("값: login.password").fill(PASS_VALUE);
  await expect(nextButton(page)).toBeEnabled();
  await nextButton(page).click();
  await expect(overlay(page)).toHaveCount(0, { timeout: 60_000 });

  // 작업이 살아 있던 채로 이어 가서 끝난다 (다시 시작하지 않았다 — 같은 작업)
  const job = await running;
  expect(job.json.state, JSON.stringify(job.json)).toBe("done");
  const done = page.locator(`[data-part="report-list"] li[data-job="${String(job.json.job)}"]`);
  await expect(done).toHaveAttribute("data-state", "done", { timeout: 60_000 });
  await expect(done.locator('[data-part="row-sub"]')).toContainText("로그인 팝업까지 — 계정 등록됨", { timeout: 30_000 });
  await shot(page, "02-done-headline");
  const fake = JSON.parse(fs.readFileSync(path.join(world.root, ".kookabug", "jobs", String(job.json.job), "fake.json"), "utf8")) as Record<string, unknown>;
  expect(fake.failed, JSON.stringify(fake)).toBeUndefined();
  // 값은 워크스페이스 어디에도 없다 (자격 증명 관리자에만)
  for (const entry of fs.readdirSync(world.root, { recursive: true, withFileTypes: true })) {
    if (!entry.isFile()) continue;
    let data: Buffer;
    try {
      data = fs.readFileSync(path.join(entry.parentPath, entry.name));
    } catch {
      continue;
    }
    expect(data.includes(Buffer.from(PASS_VALUE)), entry.name).toBe(false);
  }
});
