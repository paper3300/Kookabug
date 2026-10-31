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

export async function launchApp(options: LaunchOptions = {}): Promise<{ app: ElectronApplication; userData: string }> {
  if (!fs.existsSync(MAIN)) throw new Error(`앱 빌드가 없다: ${MAIN} (pnpm build 먼저)`);
  const userData = options.userData ?? fs.mkdtempSync(path.join(os.tmpdir(), "kb-e2e-"));
  const executablePath = createRequire(import.meta.url)("electron") as string;
  const args = [MAIN, `--user-data-dir=${userData}`];
  if (options.scaleFactor !== undefined) args.push(`--force-device-scale-factor=${options.scaleFactor}`);
  const app = await electron.launch({
    executablePath,
    args,
    cwd: APP_DIR,
    env: { ...process.env, KOOKABUG_CLI: REPO_CLI, ...options.env } as Record<string, string>,
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
