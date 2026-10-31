// 빌드한 앱을 Electron으로 띄운다. 사용자 데이터 폴더를 검사마다 따로 둬서 단일 인스턴스
// 잠금·설정이 개발자 실행과 섞이지 않게 한다
import fs from "node:fs";
import { createRequire } from "node:module";
import os from "node:os";
import path from "node:path";
import { _electron as electron, type ElectronApplication } from "@playwright/test";

export const APP_DIR = path.resolve(import.meta.dirname, "..", "..");
export const REPO_BUILD = path.resolve(APP_DIR, "..", "..", "build");
const MAIN = path.join(APP_DIR, "dist", "main", "main.cjs");

export async function launchApp(): Promise<{ app: ElectronApplication; userData: string }> {
  if (!fs.existsSync(MAIN)) throw new Error(`앱 빌드가 없다: ${MAIN} (pnpm build 먼저)`);
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), "kb-e2e-"));
  const executablePath = createRequire(import.meta.url)("electron") as string;
  const app = await electron.launch({
    executablePath,
    args: [MAIN, `--user-data-dir=${userData}`],
    cwd: APP_DIR,
  });
  return { app, userData };
}
