// 시안 비교 스크린샷: 녹화 화면 (M4 계획 2.14, T9·T10). 가짜 플랫폼 + 가짜 각본(예제 로그인)으로 실제 daemon 녹화 세션
//   recorder-<테마>       1440×900 vs Recorder(다크 시안뿐) — 녹화 중 사이드바(REC·단추·비밀값 띠·스텝 목록·옵션) + REC 탭(로그인
//                         클릭 정지 화면·보호 영역 빗금) + 빨간 상태 바. 시안의 장비 강화 화면·"02:14"는 맞추지 않는다
//   recorder-idle-dark    녹화 전 (시안 없음, U1 — 사람 확인용)
//   recorder-paused-dark  일시정지 (시안 없음)
//   recorder-stopped-dark 정지 뒤 다듬는 중 (상태 바 기본 색, 시안 없음)
//   recorder-error-dark   오류로 멈춤 hook_lost (사이드바 빨간 띠, 시안 없음)
// 결과 build/ui-shots/<이름>.png → node tools/design-ref/compare.mjs recorder recorder-idle recorder-paused recorder-stopped recorder-error
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { closeRunApp, type RunSession } from "../helpers/run";
import {
  openRecorderApp,
  prepareRecorderWorkspace,
  scriptWithHookLost,
  sidebar,
  startLaunch,
  stopRecording,
  waitLoginRecorded,
} from "../helpers/recorder";

const OUT = path.join(REPO_BUILD, "ui-shots");

test.setTimeout(180_000);

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

async function shoot(page: Page, name: string): Promise<void> {
  await page.mouse.move(1, 1);
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await page.locator("body").focus();
  await settle(page);
  fs.mkdirSync(OUT, { recursive: true });
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

/** 로그인 클릭(마지막 클릭) 정지 화면을 REC 탭에 */
async function selectLoginClick(page: Page): Promise<void> {
  await page.locator('[data-part="rec-step"][data-kind="click"]').last().click();
  await expect(page.locator('[data-part="rec-tab"]')).not.toHaveAttribute("data-frame", "", { timeout: 30_000 });
  await expect(page.locator('[data-part="target-frame"]')).not.toHaveAttribute("data-view", "", { timeout: 30_000 });
  await expect(page.locator('[data-part="preview-result"]')).toHaveAttribute("data-found", /true|false/, { timeout: 30_000 });
}

for (const theme of ["dark", "light"] as const) {
  test(`recorder-${theme}`, async () => {
    s = await openRecorderApp(prepareRecorderWorkspace(), { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    await startLaunch(page);
    await waitLoginRecorded(page);
    await selectLoginClick(page);
    await shoot(page, `recorder-${theme}`);
  });
}

test("recorder-states-dark", async () => {
  s = await openRecorderApp(prepareRecorderWorkspace(), { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await expect(page.locator('[data-part="rec-start"]')).toBeVisible();
  await shoot(page, "recorder-idle-dark");
  await startLaunch(page);
  await waitLoginRecorded(page);
  await sidebar(page).getByRole("button", { name: "일시정지" }).click();
  await expect(sidebar(page)).toHaveAttribute("data-state", "paused");
  await shoot(page, "recorder-paused-dark");
  await sidebar(page).getByRole("button", { name: "계속" }).click();
  await expect(sidebar(page)).toHaveAttribute("data-state", "recording");
  await stopRecording(page);
  await selectLoginClick(page);
  await shoot(page, "recorder-stopped-dark");
});

test("recorder-error-dark", async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-script-"));
  try {
    s = await openRecorderApp(prepareRecorderWorkspace(), { scaleFactor: 1, script: scriptWithHookLost(dir) });
    const { page } = s;
    await setTheme(page, "dark");
    await startLaunch(page);
    await expect(page.locator('[data-part="rec-stop-reason"]')).toHaveAttribute("data-reason", "hook_lost", { timeout: 60_000 });
    await expect(page.locator('[data-part="rec-stop-reason"]')).toContainText("그 뒤 입력은 녹화되지 않았어요");
    await shoot(page, "recorder-error-dark");
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
