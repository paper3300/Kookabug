// 플러그인 관리 화면 (M6 계획 B5, U1 기본값): 레포 밖 로컬 git 레포에서 대화 상자로 설치 → 팔레트에 노드,
// 설치 실패가 목록·잠금을 바꾸지 않음, 클론한 프로젝트(잠금만 있고 환경 없음)의 준비 띠 → 신뢰 확인 → 준비,
// 앱 SDK가 바뀐 잠금의 조건 다름 띠 → 다시 잠그기. 실제 daemon·uv·venv, 로컬 인덱스(네트워크 없음)·임시 uv 캐시
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { closeApp } from "./helpers/app";
import {
  closePluginApp,
  lockBytes,
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
} from "./helpers/plugins";

const TRUST_WARNING = "이 플러그인은 내 PC에서 내 권한으로 실행돼요. 출처를 믿을 때만 설치하세요.";
const INSTALL_WAIT = 240_000;

let world: PluginWorld | null = null;
let s: PluginSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(300_000);
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

/** 화면 글에 이 PC의 로컬 절대 경로(임시 폴더)가 없다 */
function noLocalPaths(text: string): void {
  expect(text).not.toMatch(/(?<![A-Za-z])[A-Za-z]:[\\/]/);
  expect(text).not.toContain(path.basename(w().root));
}

test("install from local git via dialog → palette shows node", async () => {
  test.setTimeout(INSTALL_WAIT + 120_000);
  const ws = pluginWorkspace(w());
  s = await openPluginApp(w(), ws);
  const { page } = s;
  await showPlugins(page);
  await expect(page.locator('[data-part="plugin-list"]')).toContainText("설치한 플러그인이 없어요");

  await previewSource(page, "Git 주소", w().git_repo, "v0.1.0");
  const trust = page.locator('[data-part="plugin-trust"]');
  await expect(trust).toContainText(TRUST_WARNING);
  await expect(trust).toContainText("Sample");
  await expect(trust).toContainText("sample · 0.1.0");
  await expect(trust).toContainText("@ v0.1.0");
  await expect(trust).toContainText("화면 캡처");
  await expect(trust).toContainText("게임 창 화면을 읽어요");
  noLocalPaths(await trust.innerText());
  // 신뢰 전: 잠금·환경 없음 (받고 정적으로 읽기만 했다)
  expect(lockBytes(ws)).toBeNull();
  expect(fs.existsSync(path.join(ws, ".kookabug", "plugins", "envs"))).toBe(false);

  await trust.getByRole("button", { name: "신뢰하고 설치" }).click();
  await expect(page.locator('[data-part="plugin-progress"]')).toBeVisible();
  const ok = page.locator('[data-part="plugin-result-ok"]');
  await expect(ok).toBeVisible({ timeout: INSTALL_WAIT });
  await expect(ok).toContainText("Sample — 설치했어요");
  await ok.getByRole("button", { name: "닫기" }).click();

  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  await expect(pluginRow(page, "sample")).toContainText("0.1.0");
  await expect(pluginRow(page, "sample")).toContainText("공유");
  // 잠금 + 커밋된 wheel
  const lock = JSON.parse(lockBytes(ws)!.toString("utf8")) as { plugins: { id: string; wheel: string; source: { kind: string } }[] };
  expect(lock.plugins.map((p) => p.id)).toEqual(["sample"]);
  expect(lock.plugins[0].source.kind).toBe("git");
  expect(fs.existsSync(path.join(ws, ...lock.plugins[0].wheel.split("/")))).toBe(true);

  // 상세 탭: 출처(경로 가림)·권한 표
  await pluginRow(page, "sample").click();
  const detail = page.locator('[data-part="plugin-detail"][data-plugin="sample"]');
  await expect(detail).toBeVisible();
  await expect(page.locator('[role="tab"][data-kind="PLUGIN"]')).toContainText("Sample 플러그인");
  await expect(detail.locator('[data-part="permission-table"] tr[data-permission="capture"]')).toContainText("창 제목");
  await expect(detail.locator('[data-part="plugin-env"]')).toContainText("공유 · 준비됨");
  noLocalPaths(await detail.innerText());

  // 팔레트: 플러그인 title 분류 (오른쪽 "플러그인"), 노드 줄
  await page.getByRole("button", { name: "탐색기" }).click();
  const group = page.locator('[data-part="palette"] [data-group="플러그인:sample"]');
  await expect(group).toBeVisible();
  await expect(group.locator('[aria-level="1"]')).toContainText("Sample");
  await expect(group.locator('[aria-level="1"]')).toContainText("플러그인");
  await group.locator('[aria-level="1"]').click();
  await expect(group.locator('[data-node-type="sample.text.reverse"]')).toBeVisible();
});

test("install failure keeps list", async () => {
  test.setTimeout(INSTALL_WAIT + 120_000);
  const ws = pluginWorkspace(w());
  preinstall(w(), ws, "sample");
  const before = lockBytes(ws);
  s = await openPluginApp(w(), ws);
  const { page } = s;
  await showPlugins(page);
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");

  // import가 실패하는 wheel: 승인 뒤 환경 확인에서 실패
  await previewSource(page, "wheel 파일·주소", w().wheels.broken_import);
  await page.locator('[data-part="plugin-trust"]').getByRole("button", { name: "신뢰하고 설치" }).click();
  const failed = page.locator('[data-part="plugin-result-failed"]');
  await expect(failed).toBeVisible({ timeout: INSTALL_WAIT });
  await expect(failed).toContainText("설치하지 못했어요. 기존 플러그인은 그대로예요.");
  await failed.getByText("자세히").click();
  await expect(failed.locator('[data-part="result-detail"]')).toContainText(".kookabug/plugins/logs/");
  noLocalPaths(await failed.innerText());
  await failed.getByRole("button", { name: "닫기" }).click();

  // 목록·잠금 그대로
  await expect(page.locator('[data-part="plugin-row"]')).toHaveCount(1);
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  expect(lockBytes(ws)).toEqual(before);
});

test("env missing banner → prepare", async () => {
  test.setTimeout(INSTALL_WAIT + 120_000);
  const ws = pluginWorkspace(w());
  // 클론한 프로젝트: 잠금·커밋된 wheel은 있고 이 PC에 환경·신뢰 기억은 없다
  preinstall(w(), ws, "sample", ["--drop-env", "--untrust"]);
  const before = lockBytes(ws);
  s = await openPluginApp(w(), ws);
  const { page } = s;
  await expect(page.locator('[data-part="status-plugins"]')).toHaveAttribute("data-attention", "1");
  await expect(page.locator('[data-part="activity-plugins-badge"]')).toHaveText("1");
  await showPlugins(page);
  const banner = page.locator('[data-part="plugins-banner"]');
  await expect(banner).toHaveAttribute("data-kind", "prepare");
  await expect(banner).toContainText("준비 필요 1");
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "missing");

  await banner.getByRole("button", { name: "준비…" }).click();
  const card = page.locator('[data-part="plugin-sync-trust"]');
  await expect(card).toBeVisible();
  await expect(card).toContainText("내 PC에서 내 권한으로 실행돼요");
  await expect(card.locator('[data-plugin="sample"]')).toContainText("화면 캡처");
  noLocalPaths(await card.innerText());
  // 신뢰 전에는 아무것도 만들지 않는다
  expect(fs.existsSync(path.join(ws, ".kookabug", "plugins", "envs"))).toBe(false);
  await card.getByRole("button", { name: "신뢰하고 준비" }).click();
  const ok = page.locator('[data-part="plugin-result-ok"]');
  await expect(ok).toBeVisible({ timeout: INSTALL_WAIT });
  await expect(ok).toContainText("준비했어요");
  await ok.getByRole("button", { name: "닫기" }).click();

  await expect(banner).toHaveCount(0);
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  await expect(page.locator('[data-part="status-plugins"]')).toHaveAttribute("data-attention", "0");
  // 준비는 잠금을 쓰지 않는다
  expect(lockBytes(ws)).toEqual(before);
});

test("stale banner → relock", async () => {
  test.setTimeout(INSTALL_WAIT + 120_000);
  const ws = pluginWorkspace(w());
  preinstall(w(), ws, "sample");
  // 앱 SDK가 바뀐 판 (0.1.1): 잠금의 SDK와 달라 조건 다름
  s = await openPluginApp(w(), ws, { sdk: w().sdk_wheel_next });
  const { page } = s;
  await showPlugins(page);
  const banner = page.locator('[data-part="plugins-banner"]');
  await expect(banner).toHaveAttribute("data-kind", "relock");
  await expect(banner).toContainText("앱의 Python·SDK가 잠금과 달라요");
  noLocalPaths(await banner.innerText());
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "stale");

  await banner.getByRole("button", { name: "다시 잠그기…" }).click();
  const card = page.locator('[data-part="plugin-relock-confirm"]');
  await expect(card).toBeVisible();
  await expect(card.locator('[data-part="lock-plugins"] [data-plugin]')).toHaveCount(1);
  noLocalPaths(await card.innerText());
  // 카드를 연 뒤 밖에서 잠금이 바뀜(다른 플러그인 추가, 검수 H): 카드가 새 목록으로 바뀌고 다시 확인하라고 알린다.
  // 확인 단추는 그 새 카드의 잠금 해시로만 진행한다 (daemon이 거래 안에서 비교)
  preinstall(w(), ws, "conflict_a");
  await expect(card.locator('[data-part="card-changed"]')).toContainText("잠금이 바뀌었어요", { timeout: 30_000 });
  await expect(card.locator('[data-plugin="conflict_a"]')).toBeVisible();
  await card.getByRole("button", { name: "다시 잠그기" }).click();
  const ok = page.locator('[data-part="plugin-result-ok"]');
  await expect(ok).toBeVisible({ timeout: INSTALL_WAIT });
  await expect(ok).toContainText("다시 잠갔어요");
  await ok.getByRole("button", { name: "닫기" }).click();

  await expect(banner).toHaveCount(0);
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  await expect(pluginRow(page, "conflict_a")).toHaveAttribute("data-status", "ready");
  const lock = JSON.parse(lockBytes(ws)!.toString("utf8")) as { sdk: { version: string } };
  expect(lock.sdk.version).toBe("0.1.1");
});

test("other window cancel clears busy", async () => {
  test.setTimeout(240_000);
  const ws = pluginWorkspace(w());
  s = await openPluginApp(w(), ws);
  const observer = await openPluginApp(w(), ws);
  try {
    await showPlugins(s.page);
    await previewSource(s.page, "wheel 파일·주소", w().wheels.sample);
    await showPlugins(observer.page);
    const busy = observer.page.locator('[data-part="plugin-busy"]');
    await expect(busy).toContainText("다른 창에서 신뢰 확인");
    await expect(observer.page.locator('[data-part="plugin-add"]')).toBeDisabled();
    // 연 창에서 Esc: 미리보기 취소 → 다른 창도 다시 보기 없이 busy가 풀린다 (검수 Mid)
    await s.page.keyboard.press("Escape");
    await expect(s.page.locator('[data-part="plugin-trust"]')).toHaveCount(0);
    await expect(busy).toHaveCount(0, { timeout: 15_000 });
    await expect(observer.page.locator('[data-part="plugin-add"]')).toBeEnabled();
    await expect(s.page.locator('[data-part="plugin-busy"]')).toHaveCount(0);
    expect(lockBytes(ws)).toBeNull();
  } finally {
    await closeApp(observer.app);
    fs.rmSync(observer.userData, { recursive: true, force: true });
  }
});
