// 화면 지도 E2E 도우미 (M7 B5): 실제 탐색 결과 준비(explore_world.py — 가짜 예제 게임 + 실제 MCP·daemon·runner,
// 선작성·모킹 없음)를 한 번 만들고, 검사마다 그 워크스페이스 사본을 앱으로 연다
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type ElectronApplication, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_ROOT, setContentSize, setTheme, stubOpenDialog, showActivity } from "./app";
import { cleanupWorkspace, copyWorkspaceFolder, waitConnected } from "./daemon";

const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const SCRIPT = path.join(import.meta.dirname, "explore_world.py");

export interface World {
  dir: string;
  workspace: string;
  sessions: [string, string];
  saved: string[];
}

/** 실제 탐색 결과를 만든다 (20초쯤) */
export function prepareWorld(): World {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-explore-"));
  const out = execFileSync(PYTHON, ["-X", "utf8", SCRIPT, dir], {
    encoding: "utf8",
    timeout: 600_000,
    env: { ...process.env, PYTHONUTF8: "1" },
  });
  const line = out.trim().split("\n").at(-1) ?? "{}";
  const r = JSON.parse(line) as { workspace: string; sessions: [string, string]; saved: string[] };
  return { dir, ...r };
}

export function removeWorld(world: World | null): void {
  if (world !== null) fs.rmSync(world.dir, { recursive: true, force: true });
}

export interface MapSession {
  app: ElectronApplication;
  page: Page;
  userData: string;
  workspace: string;
}

/** 탐색 결과 사본을 앱으로 연다 (폴더 이름 sample-rpg) */
export async function openMapApp(world: World): Promise<MapSession> {
  const workspace = copyWorkspaceFolder(world.workspace, "sample-rpg", [path.join(".kookabug", "session.json")]);
  const { app, userData } = await launchApp();
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  await setTheme(page, "dark"); // 시안 ScreenMap 색 (다크)
  return { app, page, userData, workspace };
}

export async function closeMapApp(s: MapSession | null): Promise<void> {
  if (s === null) return;
  await closeApp(s.app);
  await cleanupWorkspace(s.workspace);
  fs.rmSync(s.userData, { recursive: true, force: true });
}

/** 액티비티 바 "화면 지도" → 사이드바, 첫 화면 줄을 눌러 지도 탭 */
export async function showMap(page: Page): Promise<Locator> {
  await showActivity(page.locator('[data-part="activity-screens"]'));
  await expect(page.locator('[data-part="sidebar"][data-view="screens"]')).toBeVisible();
  await page.locator('[data-part="map-row"]').first().click();
  const map = page.locator('[data-part="screen-map"]');
  await expect(map).toBeVisible();
  await expect(map.locator('[data-part="map-card"]').first()).toBeVisible();
  return map;
}

export function card(page: Page, node: string): Locator {
  return page.locator(`[data-part="map-card"][data-node="${node}"]`);
}

export function candidate(session: string, key: string): string {
  return `x:${session}/${key}`;
}
