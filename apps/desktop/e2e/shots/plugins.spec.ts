// 플러그인 관리 화면 스크린샷 (M6 계획 B5, U1 기본값 — 확정 시안 없음, 시안 Main 사이드바·Permissions 표 언어로 그림)
//   plugins-sidebar-<테마>          사이드바 목록 (공유·격리 줄, [+ 플러그인 추가]·[정리])
//   plugin-detail-dark              상세 탭 (출처·환경·권한 표·노드·의존성)
//   plugin-add-trust-dark           추가 → 미리보기 → 신뢰 카드 (레포 밖 로컬 git)
//   plugin-add-progress-dark        승인 뒤 진행 (단계 줄)
//   plugin-add-failed-dark          설치 실패 결과 (자세히 펼침)
//   plugins-env-banner-dark         클론한 프로젝트의 준비 띠 (잠금만 있고 환경 없음)
//   palette-plugin-category-dark    팔레트의 플러그인 title 분류 (오른쪽 "플러그인")
// 결과 build/ui-shots/<이름>.png (비교할 시안 PNG 없음 — 사람이 본다)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import {
  closePluginApp,
  openPluginApp,
  pluginRow,
  pluginWorkspace,
  preinstall,
  previewSource,
  showPlugins,
  startWorld,
  stopWorld,
  type PluginSession,
  type PluginWorld,
} from "../helpers/plugins";

const OUT = path.join(REPO_BUILD, "ui-shots");
const WAIT = 240_000;

let world: PluginWorld | null = null;
let s: PluginSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(300_000);
  fs.mkdirSync(OUT, { recursive: true });
  world = await startWorld();
});

test.afterAll(async () => {
  await stopWorld(world);
  world = null;
});

test.afterEach(async () => {
  await closePluginApp(s);
  s = null;
});

function w(): PluginWorld {
  if (world === null) throw new Error("세계가 없다");
  return world;
}

async function shot(page: Page, name: string): Promise<void> {
  await settle(page);
  await page.mouse.move(2, 600);
  await page.screenshot({ path: path.join(OUT, `${name}.png`) });
}

test("sidebar, detail, palette", async () => {
  test.setTimeout(WAIT + 120_000);
  const ws = pluginWorkspace(w());
  for (const name of ["sample", "conflict_a", "conflict_b"]) preinstall(w(), ws, name);
  s = await openPluginApp(w(), ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await showPlugins(page);
  await expect(pluginRow(page, "conflict_b")).toContainText("격리");
  await pluginRow(page, "sample").click();
  await expect(page.locator('[data-part="plugin-detail"][data-plugin="sample"]')).toBeVisible();
  await shot(page, "plugins-sidebar-dark");
  await setTheme(page, "light");
  await shot(page, "plugins-sidebar-light");
  await setTheme(page, "dark");
  await page.locator('[data-part="plugin-detail"] [data-part="plugin-deps"] summary').click();
  await shot(page, "plugin-detail-dark");

  await page.getByRole("button", { name: "탐색기" }).click();
  const group = page.locator('[data-part="palette"] [data-group="플러그인:sample"]');
  await group.locator('[aria-level="1"]').click();
  await expect(group.locator('[data-node-type="sample.text.reverse"]')).toBeVisible();
  await group.scrollIntoViewIfNeeded();
  await shot(page, "palette-plugin-category-dark");
});

test("add: trust, progress, failed", async () => {
  test.setTimeout(2 * WAIT + 120_000);
  const ws = pluginWorkspace(w());
  s = await openPluginApp(w(), ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await showPlugins(page);
  await previewSource(page, "Git 주소", w().git_repo, "v0.1.0");
  await page.locator('[data-part="trust-deps"] summary').click();
  await shot(page, "plugin-add-trust-dark");
  await page.locator('[data-part="plugin-trust"]').getByRole("button", { name: "신뢰하고 설치" }).click();
  // 단계가 하나 이상 지난 진행 화면 (git 원천은 빌드가 있어 몇 초 걸린다)
  await expect(page.locator('[data-part="progress-steps"] [data-state="done"]').nth(1)).toBeVisible({ timeout: WAIT });
  await shot(page, "plugin-add-progress-dark");
  const ok = page.locator('[data-part="plugin-result-ok"]');
  await expect(ok).toBeVisible({ timeout: WAIT });
  await ok.getByRole("button", { name: "닫기" }).click();

  await previewSource(page, "wheel 파일·주소", w().wheels.broken_import);
  await page.locator('[data-part="plugin-trust"]').getByRole("button", { name: "신뢰하고 설치" }).click();
  const failed = page.locator('[data-part="plugin-result-failed"]');
  await expect(failed).toBeVisible({ timeout: WAIT });
  await failed.getByText("자세히").click();
  await shot(page, "plugin-add-failed-dark");
});

test("env banner", async () => {
  test.setTimeout(WAIT);
  const ws = pluginWorkspace(w());
  preinstall(w(), ws, "sample", ["--drop-env", "--untrust"]);
  s = await openPluginApp(w(), ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await showPlugins(page);
  await expect(page.locator('[data-part="plugins-banner"]')).toBeVisible();
  await shot(page, "plugins-env-banner-dark");
});
