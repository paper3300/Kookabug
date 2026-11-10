// 앱 틀·daemon 연결·테마·탐색기 (M2 계획 T7). 실제 daemon(레포 .venv의 kookabug daemon)을 띄운다
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, stubOpenDialog } from "./helpers/app";
import {
  cleanupWorkspace,
  copySampleWorkspace,
  copyWorkspaceFolder,
  killDaemon,
  readSession,
  samePath,
  waitConnected,
} from "./helpers/daemon";

let app: ElectronApplication;
let page: Page;
let userData: string;
let workspace: string | null = null;
const extraDirs: string[] = [];
const extraWorkspaces: string[] = [];

async function start(reuseUserData?: string): Promise<void> {
  ({ app, userData } = await launchApp({ userData: reuseUserData }));
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
}

async function openWorkspace(dir: string): Promise<void> {
  await stubOpenDialog(app, dir);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
}

test.afterEach(async () => {
  await closeApp(app);
  if (workspace !== null) await cleanupWorkspace(workspace);
  workspace = null;
  for (const w of extraWorkspaces.splice(0)) await cleanupWorkspace(w);
  for (const d of extraDirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
  if (userData) fs.rmSync(userData, { recursive: true, force: true });
});

test("test_welcome_open_folder_shows_explorer", async () => {
  await start();
  await expect(page.locator('[data-screen="welcome"]')).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kookabug에 오신 걸 환영해요" })).toBeVisible();
  // 시안 단추 배치 (U15): 주 단추 "시작하기"(첫 프로젝트 마법사), 글자 단추 "이미 있는 프로젝트 열기"
  await expect(page.getByRole("button", { name: "시작하기", exact: true })).toBeVisible();
  await expect(page.locator('[data-part="open-project"]')).toHaveText("이미 있는 프로젝트 열기");

  workspace = copySampleWorkspace();
  await openWorkspace(workspace);
  await expect(page.locator('[data-screen="shell"]')).toBeVisible();
  await waitConnected(page);
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  // 시안 순서: tests(펼침) → subgraphs → targets → screens → 설정 파일. .kookabug는 숨긴다
  await expect(tree.getByRole("treeitem").first()).toHaveAttribute("data-path", "tests");
  await expect(tree.locator('[data-path="tests/smoke_headless.graph.json"]')).toBeVisible();
  await expect(tree.locator('[data-path="kookabug.json"]')).toBeVisible();
  await expect(tree.locator('[data-path=".kookabug"]')).toHaveCount(0);
  // 섹션 머리 = 폴더 이름, 상태 바 = 실행 환경
  await expect(page.getByRole("button", { name: "sample-rpg" })).toBeVisible();
  await expect(page.locator('[data-part="statusbar"]')).toContainText("Python 3.14");
  await expect(page.locator('[data-part="statusbar"]')).toContainText("플러그인 1");
  // 연결되면 띠가 없다
  await expect(page.getByRole("status", { name: "daemon 연결" })).toHaveCount(0);
  // 폴더를 펼치고 접는다
  await tree.locator('[data-path="targets"]').click();
  await expect(tree.locator('[data-path="targets/title"]')).toBeVisible();
  await tree.locator('[data-path="targets"]').click();
  await expect(tree.locator('[data-path="targets/title"]')).toHaveCount(0);
  // 밖에서 파일을 만들면 workspace.changed로 다시 읽는다
  fs.copyFileSync(
    path.join(workspace, "tests", "smoke_headless.graph.json"),
    path.join(workspace, "tests", "새 테스트.graph.json"),
  );
  await expect(tree.locator('[data-path="tests/새 테스트.graph.json"]')).toBeVisible({ timeout: 10_000 });
  // 그래프를 누르면 탭으로 열린다
  await tree.locator('[data-path="tests/inventory_open.graph.json"]').click();
  await expect(page.getByRole("tab", { name: /inventory_open/ })).toHaveAttribute("aria-selected", "true");
});

test("test_non_workspace_folder_message", async () => {
  await start();
  const plain = fs.mkdtempSync(path.join(os.tmpdir(), "kb-plain-"));
  extraDirs.push(plain);
  await openWorkspace(plain);
  const alert = page.getByRole("alert");
  await expect(alert).toContainText("Kookabug 프로젝트가 아닙니다");
  await expect(alert).toContainText(plain);
  await expect(page.locator('[data-screen="welcome"]')).toBeVisible();
  // 대화 상자를 닫으면 아무 일도 없다
  await stubOpenDialog(app, null);
  await page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await expect(page.locator('[data-screen="welcome"]')).toBeVisible();
  // 최근 목록에 넣지 않는다
  expect(await page.evaluate(() => window.kookabug.app.recent())).toEqual([]);
});

test("test_recent_projects_listed", async () => {
  await start();
  workspace = copySampleWorkspace("recent-project");
  await openWorkspace(workspace);
  await waitConnected(page);
  // 파일 → 프로젝트 닫기 → 시작 화면에 최근 프로젝트
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "프로젝트 닫기" }).click();
  const recent = page.getByRole("region", { name: "최근 프로젝트" });
  await expect(recent.getByRole("button", { name: /recent-project/ })).toBeVisible();

  // 앱을 다시 띄워도 남는다 (userData/recent.json)
  await closeApp(app);
  await start(userData);
  const again = page.getByRole("region", { name: "최근 프로젝트" }).getByRole("button", { name: /recent-project/ });
  await expect(again).toBeVisible();
  await expect(again).toHaveAttribute("title", workspace);
  await again.click();
  await expect(page.locator('[data-screen="shell"]')).toBeVisible();
  await waitConnected(page);
});

test("test_theme_follows_system_and_toggle_persists", async () => {
  await start();
  const theme = () => page.evaluate(() => document.documentElement.dataset.theme);
  const bg = () => page.evaluate(() => getComputedStyle(document.querySelector('[data-screen="welcome"]')!).backgroundColor);
  // 첫 실행: 시스템 (Windows 설정 = nativeTheme)
  const group = page.getByRole("group", { name: "테마" });
  await expect(group.getByRole("button", { name: "시스템" })).toHaveAttribute("aria-pressed", "true");
  const systemDark = await app.evaluate(({ nativeTheme }) => nativeTheme.shouldUseDarkColors);
  await expect.poll(theme).toBe(systemDark ? "dark" : "light");

  await group.getByRole("button", { name: "라이트" }).click();
  await expect.poll(theme).toBe("light");
  expect(await bg()).toBe("rgb(255, 255, 255)");
  await group.getByRole("button", { name: "다크" }).click();
  await expect.poll(theme).toBe("dark");
  expect(await bg()).toBe("rgb(31, 31, 31)");
  await expect(group.getByRole("button", { name: "다크" })).toHaveAttribute("aria-pressed", "true");

  // 다시 띄워도 고른 테마 (userData/settings.json)
  await closeApp(app);
  await start(userData);
  await expect(page.getByRole("group", { name: "테마" }).getByRole("button", { name: "다크" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect.poll(theme).toBe("dark");
  expect(JSON.parse(fs.readFileSync(path.join(userData, "settings.json"), "utf8"))).toMatchObject({ theme: "dark" });

  // 보기 메뉴에서도 바꾼다 (앱 틀)
  workspace = copySampleWorkspace();
  await openWorkspace(workspace);
  await page.getByRole("button", { name: "보기", exact: true }).click();
  await page.getByRole("menuitemradio", { name: "테마: 라이트" }).click();
  await expect.poll(theme).toBe("light");
  // 시스템으로 돌리면 다시 Windows 설정
  await page.getByRole("button", { name: "보기", exact: true }).click();
  await page.getByRole("menuitemradio", { name: "테마: 시스템" }).click();
  await expect.poll(theme).toBe(systemDark ? "dark" : "light");
});

test("test_daemon_killed_banner_then_reconnects", async () => {
  await start();
  workspace = copySampleWorkspace();
  await openWorkspace(workspace);
  await waitConnected(page);
  const before = readSession(workspace)!;
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  await expect(tree.locator('[data-path="tests"]')).toBeVisible();

  await killDaemon(workspace);
  // 끊김 띠 → 0.5초 뒤 다시 붙기 순서(오래된 session → 새 daemon) → 연결됨
  const banner = page.getByRole("status", { name: "daemon 연결" });
  await expect(banner).toBeVisible({ timeout: 5_000 });
  await expect(banner).toHaveAttribute("data-status", /disconnected|connecting/);
  await waitConnected(page, 30_000);
  await expect(banner).toHaveCount(0);
  const after = readSession(workspace)!;
  expect(after.pid).not.toBe(before.pid);
  expect(after.start_id).not.toBe(before.start_id);
  // 다시 붙은 뒤에도 탐색기를 다시 읽는다
  await expect(tree.locator('[data-path="tests"]')).toBeVisible();
  await expect(page.getByRole("tabpanel", { name: "출력" })).toContainText("daemon 연결이 끊겼다");
});

test("test_ctrl_p_opens_file", async () => {
  await start();
  workspace = copySampleWorkspace();
  await openWorkspace(workspace);
  await waitConnected(page);
  await expect(page.getByRole("tree", { name: "워크스페이스 파일" }).locator('[data-path="tests"]')).toBeVisible();

  await page.keyboard.press("Control+P");
  const dialog = page.getByRole("dialog", { name: "파일 빠른 열기" });
  await expect(dialog).toBeVisible();
  // 그래프·target만 나온다 (화면 지도·PNG·설정 파일은 없음)
  const options = dialog.getByRole("option");
  await expect(options.first()).toBeVisible();
  const paths = await options.allTextContents();
  expect(paths.some((t) => t.includes(".screen.json") || t.includes(".png") || t.includes("kookabug.json"))).toBe(false);
  await page.keyboard.type("inventory_open");
  await expect(options).toHaveCount(1);
  await page.keyboard.press("Enter");
  await expect(dialog).toHaveCount(0);
  const tab = page.getByRole("tab", { name: /inventory_open/ });
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(tab).toContainText("TEST");
  await expect(page.locator('[data-part="breadcrumb"]')).toHaveText(/sample-rpg\s*›\s*tests\s*›\s*inventory_open\.graph\.json/);

  // target도 열고, 제목 바의 검색 자리를 눌러도 열린다
  await page.getByRole("button", { name: "파일 빠른 열기" }).click();
  await page.keyboard.type("start_button");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowUp");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("tab", { name: /start_button/ }).first()).toContainText("TARGET");
  // Esc로 닫는다
  await page.keyboard.press("Control+P");
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  // Ctrl+W로 탭을 닫는다
  await page.keyboard.press("Control+W");
  await expect(page.getByRole("tablist", { name: "열린 파일" }).getByRole("tab")).toHaveCount(1);
});

/** 앱 틀에서 파일 메뉴 → 프로젝트 열기 (Ctrl+O와 같은 경로) */
async function openFromShell(dir: string): Promise<void> {
  await stubOpenDialog(app, dir);
  await page.keyboard.press("Control+O");
}

test("test_copied_live_session_opens_own_daemon", async () => {
  // A가 실행 중일 때 A 폴더를 통째로 복사한 B(살아 있는 A의 session.json 포함)를 연다 (검수 T7_1 High)
  await start();
  workspace = copySampleWorkspace("project-a");
  await openWorkspace(workspace);
  await waitConnected(page);
  const sessionA = readSession(workspace)!;
  const b = copyWorkspaceFolder(workspace, "project-b");
  extraWorkspaces.push(b);
  expect(readSession(b)!.start_id).toBe(sessionA.start_id); // 복사된 세션은 A를 가리킨다

  await openFromShell(b);
  await expect(page.getByRole("button", { name: "project-b" })).toBeVisible();
  await waitConnected(page);
  // B는 자기 daemon에 붙는다: B 세션이 새로 쓰였고, daemon이 맡은 워크스페이스가 B
  await expect.poll(() => readSession(b)?.start_id).not.toBe(sessionA.start_id);
  const info = (await page.evaluate(() => window.kookabug.rpc("workspace.info", {}))) as { root: string };
  expect(samePath(info.root, b)).toBe(true);
  // 만드는 파일은 B에 생긴다 (A에는 생기지 않는다)
  await page.evaluate(() =>
    window.kookabug.rpc("graph.create", { path: "tests/created_from_b.graph.json", kind: "test" }),
  );
  expect(fs.existsSync(path.join(b, "tests", "created_from_b.graph.json"))).toBe(true);
  expect(fs.existsSync(path.join(workspace, "tests", "created_from_b.graph.json"))).toBe(false);
  // A daemon은 그대로 살아 있다 (UI가 놓아도 daemon은 남는다)
  expect(readSession(workspace)!.start_id).toBe(sessionA.start_id);
});

test("test_switch_project_clears_tabs_and_view_state", async () => {
  // 프로젝트를 닫지 않고 다른 프로젝트를 열면 앞 프로젝트의 탭·경로·선택이 남지 않는다 (검수 T7_1 Mid)
  await start();
  workspace = copySampleWorkspace("project-a");
  fs.copyFileSync(path.join(workspace, "tests", "smoke_headless.graph.json"), path.join(workspace, "tests", "only_a.graph.json"));
  await openWorkspace(workspace);
  await waitConnected(page);
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  await tree.locator('[data-path="targets"]').click();
  await tree.locator('[data-path="tests/only_a.graph.json"]').click();
  await expect(page.getByRole("tab", { name: /only_a/ })).toHaveAttribute("aria-selected", "true");

  const b = copySampleWorkspace("project-b");
  extraWorkspaces.push(b);
  await openFromShell(b);
  await expect(page.getByRole("button", { name: "project-b" })).toBeVisible();
  await waitConnected(page);
  await expect(page.getByRole("tablist", { name: "열린 파일" }).getByRole("tab")).toHaveCount(0);
  await expect(page.locator('[data-part="breadcrumb"]')).toHaveText("");
  await expect(page.locator('[data-part="canvas"]')).toHaveCount(0);
  await expect(tree.locator('[data-path="tests/smoke_headless.graph.json"]')).toBeVisible();
  await expect(tree.locator('[data-path="tests/only_a.graph.json"]')).toHaveCount(0);
  // 펼침 상태도 처음으로 (tests만 펼침)
  await expect(tree.locator('[data-path="targets/title"]')).toHaveCount(0);
  expect(await tree.locator('[aria-selected="true"]').count()).toBe(0);
});

test("test_non_workspace_folder_in_shell_shows_error_keeps_project", async () => {
  // 앱 틀에서 kookabug.json 없는 폴더를 고르면 오류를 보이고 지금 프로젝트는 그대로 (검수 T7_1 Mid)
  await start();
  workspace = copySampleWorkspace();
  await openWorkspace(workspace);
  await waitConnected(page);
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  await tree.locator('[data-path="tests/inventory_open.graph.json"]').click();
  const plain = fs.mkdtempSync(path.join(os.tmpdir(), "kb-plain-"));
  extraDirs.push(plain);

  await openFromShell(plain);
  const alert = page.getByRole("alert", { name: "폴더 열기 오류" });
  await expect(alert).toContainText("Kookabug 프로젝트가 아닙니다");
  await expect(alert).toContainText(plain);
  await expect(page.locator('[data-screen="shell"]')).toBeVisible();
  await expect(page.getByRole("button", { name: "sample-rpg" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /inventory_open/ })).toBeVisible();
  // 파일 메뉴로 열어도 같다
  await alert.getByRole("button", { name: "닫기" }).click();
  await expect(alert).toHaveCount(0);
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "프로젝트 열기…" }).click();
  await expect(page.getByRole("alert", { name: "폴더 열기 오류" })).toContainText("Kookabug 프로젝트가 아닙니다");
  // 그 뒤 올바른 프로젝트를 열면 오류가 사라진다
  const other = copySampleWorkspace("other");
  extraWorkspaces.push(other);
  await openFromShell(other);
  await expect(page.getByRole("button", { name: "other" })).toBeVisible();
  await expect(page.getByRole("alert", { name: "폴더 열기 오류" })).toHaveCount(0);
});
