// target 편집기 실제 창 (M2 계획 T12 데스크톱, 조율자 PC): 예제 게임을 띄우고 "창에서 캡처"로 정지 화면을 찍어
// 대상을 만든 뒤, 저장한 대상이 바로 매칭되는지 본다. 대화형 데스크톱이 필요하다:
// KOOKABUG_DESKTOP_TESTS=require(또는 1)일 때만 돈다 (Python `desktop` 표시와 같은 환경 변수)
import { spawn, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { REPO_ROOT } from "./helpers/app";
import { closeEditor, filePath, openEditor, type EditorSession } from "./helpers/editor";
import { frameOf, openTarget, saveTargetTab, selectRect, START_BUTTON, waitPreview } from "./helpers/target";

const DESKTOP = process.env.KOOKABUG_DESKTOP_TESTS;
const GAME_DIR = path.join(REPO_ROOT, "fixtures", "sample-game");
const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");

test.skip(DESKTOP !== "require" && DESKTOP !== "1", "대화형 데스크톱 검사 (KOOKABUG_DESKTOP_TESTS=require)");

let s: EditorSession | null = null;
let game: ChildProcess | null = null;

test.afterEach(async () => {
  await closeEditor(s);
  s = null;
  game?.kill();
  game = null;
});

test("test_capture_window_make_target_live_match", async () => {
  const title = `KBT12 ${Math.random().toString(16).slice(2, 10)}`;
  const logDir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-game-"));
  game = spawn(PYTHON, ["-X", "utf8", "-m", "sample_game", "--title", title, "--event-log", path.join(logDir, "events.jsonl")], {
    cwd: GAME_DIR,
    env: { ...process.env, PYTHONPATH: GAME_DIR, PYTHONIOENCODING: "utf-8" },
    stdio: "ignore",
    windowsHide: false,
  });
  s = await openEditor();
  const { page, workspace } = s;
  // 기존 target을 열고 실제 창에서 새로 고른 영역으로 다시 저장한다 (새 이미지 파일 + JSON 커밋)
  const rel = "targets/title/start_button.target.json";
  await openTarget(page, rel);
  // 창 목록에 예제 게임이 나올 때까지 (게임이 뜨는 시간)
  const toolbar = page.locator('[data-part="target-toolbar"]');
  let picked = false;
  for (let i = 0; i < 30 && !picked; i++) {
    await toolbar.getByRole("button", { name: "창에서 캡처" }).click();
    const picker = page.locator('[data-part="window-picker"]');
    await expect(picker).not.toContainText("창 목록을 읽는 중");
    const item = picker.locator("button", { hasText: title });
    if ((await item.count()) > 0) {
      await item.first().click();
      picked = true;
    } else {
      await page.keyboard.press("Escape");
      await page.waitForTimeout(1000);
    }
  }
  expect(picked).toBe(true);
  // 캡처가 끝나면 고르기 창이 닫힌다. 실패하면 그 이유(캡처 오류 문구)를 검사 메시지로 남긴다
  const pickerAfter = page.locator('[data-part="window-picker"]');
  await expect
    .poll(async () => ((await pickerAfter.count()) === 0 ? "closed" : await pickerAfter.innerText()), { timeout: 20_000 })
    .toBe("closed");
  await expect(frameOf(page)).not.toHaveAttribute("data-frame", "");
  await expect(page.locator('[data-part="frame-source"]')).toContainText(title);
  // 화면 배율만큼 커진 시작 버튼 (예제 게임은 1024x640 기준으로 그린다)
  const size = await page.evaluate(() => {
    const img = document.querySelector<HTMLImageElement>('[data-part="target-frame"] img');
    return img === null ? [0, 0] : [img.naturalWidth, img.naturalHeight];
  });
  const scale = size[1] / 640;
  const [x, y, w, h] = START_BUTTON.map((v) => Math.round(v * scale));
  const crop = await selectRect(page, [x + 4, y + 4, w - 8, h - 8]);
  // 연 target(원래 시작 버튼 전체)이 캡처에서 이미 찾음이라, 고른 영역의 미리보기가 올 때까지 기다린다
  await expect.poll(() => waitPreview(page, true), { timeout: 20_000 }).toEqual(crop);
  await saveTargetTab(page, rel);
  await expect(page.locator('[data-part="target-saved"]')).toHaveAttribute("data-found", "true");
  expect(fs.existsSync(filePath(workspace, rel))).toBe(true);
  // 새로 찍은 화면에서 저장한 파일 그대로 찾는다
  await toolbar.getByRole("button", { name: "창에서 캡처" }).click();
  await page.locator('[data-part="window-picker"] button', { hasText: title }).first().click();
  const match = await waitPreview(page, true);
  expect(match).not.toBeNull();
  expect(Math.abs(match![0] - crop[0])).toBeLessThanOrEqual(2);
  expect(Math.abs(match![1] - crop[1])).toBeLessThanOrEqual(2);
});
