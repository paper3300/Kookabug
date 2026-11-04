// 빌드한 앱을 Electron으로 띄운다. 사용자 데이터 폴더를 검사마다 따로 둬서 단일 인스턴스
// 잠금·설정이 개발자 실행과 섞이지 않게 한다
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { _electron as electron, type ElectronApplication, type Page } from "@playwright/test";

export const APP_DIR = path.resolve(import.meta.dirname, "..", "..");
export const REPO_ROOT = path.resolve(APP_DIR, "..", "..");
export const REPO_BUILD = path.join(REPO_ROOT, "build");
export const REPO_CLI = path.join(REPO_ROOT, ".venv", "Scripts", "kookabug.exe");
const MAIN = path.join(APP_DIR, "dist", "main", "main.cjs");

export interface LaunchOptions {
  /** 같은 사용자 데이터로 다시 띄울 때 (설정·최근 목록 유지) */
  userData?: string;
  /** 1이면 화면 배율과 무관하게 1배로 그린다 (시안 비교 스크린샷) */
  scaleFactor?: number;
  env?: Record<string, string>;
}

/**
 * 검사 창 모니터 (`KOOKABUG_TEST_DISPLAY`, tools/kb_testing/display.py와 같은 값: left·right·primary·"x,y").
 * 없으면 지금처럼 Electron이 정한 자리에 둔다
 */
export const TEST_DISPLAY = process.env.KOOKABUG_TEST_DISPLAY?.trim() ?? "";
/** 앱 → daemon → runner가 띄운 tkinter 창(예제 게임)도 그 모니터에 뜨게 하는 `HOME` (display.py `tk_env`) */
const TK_HOME = path.join(REPO_ROOT, "tools", "kb_testing", "tk_home");
/** 검사가 직접 띄우는 파이썬 tkinter 창(예제 게임)에 더할 환경 — 값이 없으면 빈 객체 */
export function testDisplayEnv(): Record<string, string> {
  return TEST_DISPLAY === "" ? {} : { HOME: TK_HOME };
}
/** 주 프로세스에 앱보다 먼저 싣는 창 놓기 스크립트 (창을 만드는 순간 그 모니터로 옮긴다) */
const PLACE_WINDOW = path.join(import.meta.dirname, "place-window.cjs");

export async function launchApp(options: LaunchOptions = {}): Promise<{ app: ElectronApplication; userData: string }> {
  if (!fs.existsSync(MAIN)) throw new Error(`앱 빌드가 없다: ${MAIN} (pnpm build 먼저)`);
  const userData = options.userData ?? fs.mkdtempSync(path.join(os.tmpdir(), "kb-e2e-"));
  const executablePath = createRequire(import.meta.url)("electron") as string;
  const args = [MAIN, `--user-data-dir=${userData}`];
  if (options.scaleFactor !== undefined) args.push(`--force-device-scale-factor=${options.scaleFactor}`);
  if (TEST_DISPLAY !== "") args.unshift("-r", PLACE_WINDOW);
  const app = await electron.launch({
    executablePath,
    args,
    cwd: APP_DIR,
    env: { ...process.env, KOOKABUG_CLI: REPO_CLI, ...testDisplayEnv(), ...options.env } as Record<string, string>,
  });
  return { app, userData };
}

/**
 * 앱을 닫는다. 10초 안에 안 닫히면 프로세스를 끝낸다 (검사 정리가 멈추지 않게). 검사 정리는 저장 안 된 편집을
 * 버린다: 창을 destroy해 닫기 확인(close-guard)을 거치지 않는다. 닫기 확인 자체는 edit.spec.ts가 창 X로 검사한다
 */
export async function closeApp(app: ElectronApplication | undefined): Promise<void> {
  if (app === undefined) return;
  await app
    .evaluate(({ BrowserWindow }) => {
      for (const w of BrowserWindow.getAllWindows()) w.destroy();
    })
    .catch(() => {});
  const closed = app.close().catch(() => {});
  const timer = new Promise((r) => setTimeout(r, 10_000));
  await Promise.race([closed, timer]);
  try {
    app.process().kill();
  } catch {
    // 이미 끝남
  }
}

/** 창 내용 크기를 시안 판 크기로 (시작 화면 1120×720, 나머지 1440×900) */
export async function setContentSize(app: ElectronApplication, page: Page, width: number, height: number): Promise<void> {
  await app.evaluate(
    ({ BrowserWindow }, [w, h]) => {
      const win = BrowserWindow.getAllWindows()[0];
      if (win.isMaximized()) win.unmaximize();
      win.setContentSize(w, h);
      // 크기가 바뀌면 고른 모니터 안으로 다시 놓는다 (KOOKABUG_TEST_DISPLAY가 있을 때만 있음)
      (globalThis as { __kbPlaceWindow?: (win: unknown) => void }).__kbPlaceWindow?.(win);
    },
    [width, height] as const,
  );
  await page.waitForFunction(([w, h]) => window.innerWidth === w && window.innerHeight === h, [width, height] as const, {
    timeout: 5000,
  });
}

/** "프로젝트 열기" 대화 상자가 이 폴더를 고른 것처럼 바꾼다 */
export async function stubOpenDialog(app: ElectronApplication, dir: string | null): Promise<void> {
  await app.evaluate(({ dialog }, picked) => {
    dialog.showOpenDialog = (async () =>
      picked === null ? { canceled: true, filePaths: [] } : { canceled: false, filePaths: [picked] }) as never;
  }, dir);
}

/** 테마를 앱 API로 고른다 (보기 메뉴·시작 화면 고르기와 같은 경로) */
export async function setTheme(page: Page, mode: "system" | "light" | "dark"): Promise<void> {
  await page.evaluate((m) => window.kookabug.app.themeSet(m), mode);
  if (mode !== "system") await page.waitForFunction((m) => document.documentElement.dataset.theme === m, mode);
}

/** 글꼴을 다 받고 한 번 더 그린 뒤 */
export async function settle(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await document.fonts.ready;
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
}
