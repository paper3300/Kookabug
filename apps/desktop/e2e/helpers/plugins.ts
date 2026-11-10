// 플러그인 E2E 도우미 (M6 B5): 로컬 인덱스·SDK wheel·레포 밖 git 레포(plugin_world.py serve)를 파일 하나에
// 한 번 띄우고, 검사마다 예제 워크스페이스 사본(plugin_index = 로컬 인덱스)을 앱으로 연다. 네트워크 없음,
// uv 캐시는 세계 폴더의 임시 LOCALAPPDATA (이 PC의 실제 캐시를 쓰지 않는다)
import { spawn, execFileSync, type ChildProcess } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_ROOT, setContentSize, stubOpenDialog, showActivity } from "./app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./daemon";

const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const SCRIPT = path.join(import.meta.dirname, "plugin_world.py");

export interface PluginWorld {
  root: string;
  file: string;
  index_url: string;
  sdk_wheel: string;
  sdk_wheel_next: string;
  appdata: string;
  git_repo: string;
  wheels: Record<string, string>;
  proc: ChildProcess;
}

/** 세계를 만들고 인덱스 서버를 띄운다 (파일당 한 번, 수십 초) */
export async function startWorld(): Promise<PluginWorld> {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "kb-pw-"));
  const proc = spawn(PYTHON, ["-X", "utf8", SCRIPT, "serve", root], { stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  let err = "";
  proc.stderr?.on("data", (d: Buffer) => (err += d.toString()));
  const file = await new Promise<string>((resolve, reject) => {
    let out = "";
    proc.stdout?.on("data", (d: Buffer) => {
      out += d.toString();
      const m = /READY (.+)\r?\n/.exec(out);
      if (m) resolve(m[1].trim());
    });
    proc.on("exit", (code) => reject(new Error(`plugin_world serve 종료 ${code}: ${err}`)));
  });
  const world = JSON.parse(fs.readFileSync(file, "utf8")) as Omit<PluginWorld, "root" | "file" | "proc">;
  return { ...world, root, file, proc };
}

export async function stopWorld(world: PluginWorld | null): Promise<void> {
  if (world === null) return;
  world.proc.stdin?.end();
  await new Promise((r) => {
    const timer = setTimeout(() => {
      world.proc.kill();
      r(null);
    }, 5000);
    world.proc.on("exit", () => {
      clearTimeout(timer);
      r(null);
    });
  });
  fs.rmSync(world.root, { recursive: true, force: true, maxRetries: 3 });
}

/** 예제 워크스페이스 사본 + plugin_index = 로컬 인덱스 */
export function pluginWorkspace(world: PluginWorld, name = "sample-rpg"): string {
  const ws = copySampleWorkspace(name);
  const file = path.join(ws, "kookabug.json");
  const data = JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
  data.plugin_index = { url: world.index_url };
  fs.writeFileSync(file, JSON.stringify(data, null, 2));
  return ws;
}

/** 워크스페이스에 픽스처 wheel을 미리 설치한다 (CLI 거래와 같은 PluginOps — 앱 밖) */
export function preinstall(world: PluginWorld, ws: string, wheel: string, flags: string[] = []): void {
  execFileSync(PYTHON, ["-X", "utf8", SCRIPT, "install", world.file, ws, wheel, ...flags], { stdio: "pipe", timeout: 300_000 });
}

/** 실제 `PluginOps.verify()`를 앱 밖에서 돌린다 (환경 파일이 바뀌었으면 깨짐 기록). 결과 JSON */
export function verifyPlugins(world: PluginWorld, ws: string): { ok: boolean; environments: Record<string, { status: string }> } {
  const out = execFileSync(PYTHON, ["-X", "utf8", SCRIPT, "verify", world.file, ws], { encoding: "utf8", timeout: 300_000 });
  return JSON.parse(out.trim().split("\n").at(-1)!);
}

export interface PluginSession {
  app: ElectronApplication;
  page: Page;
  userData: string;
  workspace: string;
}

/** 앱을 띄워 워크스페이스를 연다. sdk: 앱 SDK wheel (기본 세계의 것 — 다른 판이면 조건 다름) */
export async function openPluginApp(world: PluginWorld, ws: string, options: { sdk?: string; scaleFactor?: number } = {}): Promise<PluginSession> {
  const { app, userData } = await launchApp({
    scaleFactor: options.scaleFactor,
    env: { LOCALAPPDATA: world.appdata, KOOKABUG_SDK_WHEEL: options.sdk ?? world.sdk_wheel },
  });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, ws);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(page);
  return { app, page, userData, workspace: ws };
}

export async function closePluginApp(s: PluginSession | null): Promise<void> {
  if (s === null) return;
  await closeApp(s.app);
  await cleanupWorkspace(s.workspace);
  fs.rmSync(s.userData, { recursive: true, force: true });
}

export async function showPlugins(page: Page): Promise<void> {
  await showActivity(page.locator('[data-part="activity-plugins"]'));
  await expect(page.locator('[data-part="sidebar"][data-view="plugins"]')).toBeVisible();
}

/** 추가 대화 상자: 원천 입력 → 미리보기 → 신뢰 카드가 뜰 때까지 */
export async function previewSource(page: Page, kind: "Git 주소" | "wheel 파일·주소" | "폴더", text: string, ref?: string): Promise<void> {
  await page.locator('[data-part="plugin-add"]').click();
  const dialog = page.locator('[data-part="plugin-add-dialog"]');
  await expect(dialog).toBeVisible();
  await dialog.getByRole("tab", { name: kind }).click();
  await dialog.locator("input").first().fill(text);
  if (ref !== undefined) await dialog.getByRole("textbox", { name: "버전" }).fill(ref);
  await dialog.getByRole("button", { name: "미리보기" }).click();
  await expect(page.locator('[data-part="plugin-trust"]')).toBeVisible({ timeout: 60_000 });
}

/** 플러그인 목록 줄 */
export function pluginRow(page: Page, id: string) {
  return page.locator(`[data-part="plugin-row"][data-plugin="${id}"]`);
}

/** 잠금 파일 바이트 (없으면 null) */
export function lockBytes(ws: string): Buffer | null {
  const file = path.join(ws, "kookabug.lock");
  return fs.existsSync(file) ? fs.readFileSync(file) : null;
}
