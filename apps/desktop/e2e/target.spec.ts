// target 편집기 (M2 계획 T12 완료 기준 e2e/target.spec.ts). 실제 daemon(레포 .venv) + 예제 워크스페이스 사본 +
// 예제 게임 장면 PNG(이미지 소스). 그래프 실행은 가짜 플랫폼이다 (helpers/run.ts).
// M2 완료 기준 3 "target 편집기로 만든 대상이 바로 매칭"의 앱 쪽 근거다
import fs from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { killDaemon, SAMPLE_WORKSPACE, waitConnected } from "./helpers/daemon";
import { filePath, nodeEl, readJson, save, selectOnly, tabOf, writeFile } from "./helpers/editor";
import { clickRun, closeRunApp, openRunApp, prepareRunWorkspace, waitEnded, type RunSession } from "./helpers/run";
import {
  addCapture,
  editorOf,
  frameOf,
  listDir,
  loadFrame,
  openTarget,
  previewOf,
  readTarget,
  saveTargetTab,
  selectRect,
  START_BUTTON,
  TITLE_TEXT,
  waitPreview,
} from "./helpers/target";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

type Graph = { nodes: Record<string, { in?: Record<string, unknown> }> };

const INVENTORY = "tests/inventory_open.graph.json";
const MADE_GRAPH = "tests/editor_target.graph.json";
const MADE_TARGET = "targets/made/start.target.json";

/** 그 target을 기다리는 그래프 (게임 실행 → 이미지 대기 → 통과) */
function madeGraph(target: string | null): string {
  return JSON.stringify(
    {
      format: "kookabug.graph/0",
      kind: "test",
      layout: { nodes: { n_entry: { x: 0, y: 0 }, n_launch: { x: 260, y: 0 }, n_wait: { x: 560, y: 0 }, n_pass: { x: 860, y: 0 } } },
      meta: { title: "편집기 대상" },
      nodes: {
        n_entry: { next: { start: "n_launch" }, type: "core.graph.entry", version: 1 },
        n_launch: {
          in: { path: "SampleRPG", timeout_ms: 5000, window_title: "SampleRPG" },
          next: { attached: "n_wait" },
          type: "core.app.launch",
          version: 1,
        },
        n_wait: {
          in: { ...(target === null ? {} : { target: { $target: target } }), timeout_ms: 5000 },
          next: { found: "n_pass" },
          title: "시작 버튼",
          type: "core.image.wait",
          version: 1,
        },
        n_pass: { type: "core.test.pass", version: 1 },
      },
      plugins: { core: "0.1.0" },
    },
    null,
    2,
  );
}

/** kookabug_platform.dpi.normalized_to_pixels (검사가 Python 규칙을 그대로 따라 계산한다) */
function normalizedToPixels(region: number[], [cw, ch]: [number, number]): number[] {
  const up = (v: number) => Math.floor(v + 0.5);
  const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);
  const [x, y, w, h] = region;
  const x0 = clamp(up(x * cw), 0, cw);
  const y0 = clamp(up(y * ch), 0, ch);
  const x1 = clamp(up((x + w) * cw), x0, cw);
  const y1 = clamp(up((y + h) * ch), y0, ch);
  return [x0, y0, x1 - x0, y1 - y0];
}

async function open(files: Record<string, string | Buffer> = {}, captures: string[] = ["title.png"]): Promise<RunSession> {
  const ws = prepareRunWorkspace();
  for (const [rel, data] of Object.entries(files)) writeFile(ws.root, rel, data);
  for (const c of captures) addCapture(ws.root, c);
  s = await openRunApp(ws);
  return s;
}

async function openGraphTab(page: Page, rel: string): Promise<void> {
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  await tree.locator(`[data-path="${rel}"]`).click();
  await expect(page.locator(`[data-part="canvas"][data-path="${rel}"]`)).toHaveAttribute("data-status", "ready");
}

/** 속성 편집기 대상 칸의 "새 대상 만들기" → 이름 → 새 TARGET 탭 */
async function newTargetFromInspector(page: Page, node: string, name: string): Promise<string> {
  await selectOnly(page, node);
  const field = page.locator(`[data-part="inspector"] [data-part="field"][data-field="in"][data-pin="target"]`);
  await field.locator('[data-part="new-target"]').click();
  const dialog = page.getByRole("dialog", { name: "새 찾기 대상" });
  await dialog.getByRole("textbox", { name: "이름" }).fill(name);
  await dialog.getByRole("button", { name: "만들기" }).click();
  const rel = `targets/${name}.target.json`;
  await expect(editorOf(page, rel)).toHaveAttribute("data-new", "true");
  await expect(tabOf(page, rel)).toHaveAttribute("aria-selected", "true");
  return rel;
}

test("test_make_target_from_image_then_matches_immediately", async () => {
  const { page, ws } = await open({ [MADE_GRAPH]: madeGraph(MADE_TARGET) });
  await openGraphTab(page, MADE_GRAPH);
  const rel = await newTargetFromInspector(page, "n_wait", "made/start");
  expect(rel).toBe(MADE_TARGET);
  // 새 대상은 영역을 고르기 전에는 저장할 수 없다
  await expect(page.locator('[data-part="target-save"]')).toBeDisabled();
  await loadFrame(page, "captures/title.png");
  const crop = await selectRect(page, START_BUTTON);
  // 저장 전 미리보기 (자른 영역): 찾은 상자 = 고른 영역, 배율 1
  expect(await waitPreview(page, true)).toEqual(crop);
  await expect(previewOf(page)).toContainText("찾음 · 점수 1.00 · 배율 1.00");
  await saveTargetTab(page, rel);
  // 바로 매칭: 저장 결과의 미리보기가 찾음이고 점수 ≥ 임계값
  const saved = page.locator('[data-part="target-saved"]');
  await expect(saved).toHaveAttribute("data-found", "true");
  await expect(saved).toContainText("바로 매칭: 찾음 · 점수 1.00");
  const spec = readTarget(ws.root, rel);
  expect(spec.image).toBe("start.png");
  expect(spec.recorded).toEqual({ client_size: [1024, 640], dpi: 96 });
  expect(fs.existsSync(filePath(ws.root, "targets/made/start.png"))).toBe(true);
  // 저장한 파일(디스크 이미지)로 다시 찾아도 같은 자리
  await expect(frameOf(page).locator('[data-part="template-rect"]')).toHaveCount(0);
  expect(await waitPreview(page, true)).toEqual(crop);
  await expect(editorOf(page, rel)).toHaveAttribute("data-new", "false");
  // 그 target을 쓰는 그래프를 가짜 플랫폼으로 실행 → 통과
  await tabOf(page, MADE_GRAPH).getByRole("button").first().click();
  await expect(nodeEl(page, "n_wait")).toBeVisible();
  await clickRun(page);
  await waitEnded(page, "pass");
});

test("test_threshold_slider_updates_preview_result", async () => {
  const { page } = await open();
  await openTarget(page, "targets/login/account_field.target.json");
  await loadFrame(page, "captures/title.png");
  // 기존 이미지로 찾는다: 타이틀 화면에는 계정 칸이 없다 → 못 찾음과 최고 점수 (후보 개수는 쓰지 않는다)
  await waitPreview(page, false);
  await expect(previewOf(page)).toHaveText(/^못 찾음 · 최고 점수 0\.6\d$/);
  await expect(frameOf(page).locator('[data-part="best-rect"]')).toHaveCount(1);
  const slider = page.getByRole("slider", { name: "유사도 임계값" });
  await slider.focus();
  await page.keyboard.press("Home");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.50");
  await waitPreview(page, true);
  // 임계값 0.50이면 비슷한 다른 자리도 넘을 수 있다: "같은 모양 N곳"이 붙는다 (M4 T11)
  await expect(previewOf(page)).toHaveText(/^찾음 · 점수 0\.6\d · 배율 \d\.\d\d( · 같은 모양 \d곳)?$/);
  await expect(frameOf(page).locator('[data-part="score-badge"]')).toHaveText(/^0\.6\d$/);
  await page.keyboard.press("End");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.99");
  await waitPreview(page, false);
  await expect(editorOf(page, "targets/login/account_field.target.json")).toHaveAttribute("data-dirty", "true");
});

test("test_search_region_saved_normalized_roundtrip", async () => {
  const { page, ws } = await open();
  await openGraphTab(page, INVENTORY);
  const rel = await newTargetFromInspector(page, "n_check_inventory", "made/region");
  await loadFrame(page, "captures/title.png");
  const crop = await selectRect(page, START_BUTTON);
  const search = await selectRect(page, [301, 333, 457, 201], true);
  expect(await waitPreview(page, true)).toEqual(crop);
  await saveTargetTab(page, rel);
  const region = (readTarget(ws.root, rel).search as { region: number[] }).region;
  // 6자리 정규화 값이고, 같은 클라이언트 크기에서 고른 픽셀 그대로 돌아온다
  for (const v of region) expect(Number(v.toFixed(6))).toBe(v);
  expect(normalizedToPixels(region, [1024, 640])).toEqual(search);
  // 다시 연 사양의 검색 범위도 같은 픽셀
  await expect(frameOf(page).locator('[data-part="search-rect"]')).toHaveAttribute("data-rect", search.join(","));
});

test("test_two_unsaved_selections_change_preview", async () => {
  const { page, ws } = await open();
  await openGraphTab(page, INVENTORY);
  await newTargetFromInspector(page, "n_check_inventory", "made/two");
  await loadFrame(page, "captures/title.png");
  const a = await selectRect(page, START_BUTTON);
  expect(await waitPreview(page, true)).toEqual(a);
  const b = await selectRect(page, TITLE_TEXT);
  expect(b).not.toEqual(a);
  await expect(frameOf(page).locator('[data-part="match-rect"]')).toHaveAttribute("data-rect", b.join(","));
  await waitPreview(page, true);
  // 저장 전이라 파일은 하나도 생기지 않았다
  expect(listDir(ws.root, "targets/made")).toEqual([]);
});

test("test_out_of_order_preview_responses_show_latest_only", async () => {
  const { app, page } = await open();
  await openGraphTab(page, INVENTORY);
  await newTargetFromInspector(page, "n_check_inventory", "made/order");
  await loadFrame(page, "captures/title.png");
  const a = await selectRect(page, START_BUTTON);
  expect(await waitPreview(page, true)).toEqual(a);
  const seqA = Number(await previewOf(page).getAttribute("data-seq"));
  // 다음 미리보기 응답 둘: 먼저 보낸 것(제목 글자)을 늦게, 나중 것(시작 버튼)을 바로 → 역순으로 도착
  await app.evaluate((_electron, method) => {
    (globalThis as unknown as { __kookabugE2E: { delayResponses(m: string, d: number[]): void } }).__kookabugE2E.delayResponses(method, [3000, 0]);
  }, "target.preview");
  await selectRect(page, TITLE_TEXT);
  await page.waitForTimeout(700);
  const c = await selectRect(page, START_BUTTON);
  // 나중 요청의 결과가 보인다
  await expect(previewOf(page)).toHaveAttribute("data-seq", String(seqA + 2), { timeout: 10_000 });
  await expect(frameOf(page).locator('[data-part="match-rect"]')).toHaveAttribute("data-rect", c.join(","));
  // 늦게 온 옛 응답(제목 글자)이 덮지 않는다
  await page.waitForTimeout(3500);
  await expect(previewOf(page)).toHaveAttribute("data-seq", String(seqA + 2));
  await expect(frameOf(page).locator('[data-part="match-rect"]')).toHaveAttribute("data-rect", c.join(","));
  await expect(frameOf(page).locator('[data-part="template-rect"]')).toHaveAttribute("data-rect", c.join(","));
});

test("test_save_conflict_banner_keeps_existing_target", async () => {
  const { page, ws } = await open();
  const rel = "targets/title/start_button.target.json";
  const image = filePath(ws.root, "targets/title/start_button.png");
  const imageBytes = fs.readFileSync(image);
  const folder = listDir(ws.root, "targets/title");
  await openTarget(page, rel);
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(editorOf(page, rel)).toHaveAttribute("data-dirty", "true");
  // 밖에서 target JSON을 바꾼다
  const external = JSON.stringify({ format: "kookabug.target/0", image: "start_button.png", match: { threshold: 0.9 }, x_external: 1 }, null, 2);
  fs.writeFileSync(filePath(ws.root, rel), external);
  await page.locator('[data-part="target-save"]').click();
  const banner = page.locator('[data-part="target-conflict"]');
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("기존 대상 파일은 그대로예요");
  // 기존 target(밖에서 바꾼 내용)·이미지·폴더는 그대로
  expect(fs.readFileSync(filePath(ws.root, rel), "utf8")).toBe(external);
  expect(fs.readFileSync(image).equals(imageBytes)).toBe(true);
  expect(listDir(ws.root, "targets/title")).toEqual(folder);
  await expect(editorOf(page, rel)).toHaveAttribute("data-dirty", "true");
  // "내 편집으로 덮어쓰기": 지금 디스크 revision으로 다시 보낸다
  const editor = editorOf(page, rel);
  await banner.getByRole("button", { name: "내 편집으로 덮어쓰기" }).click();
  await expect(editor).toHaveAttribute("data-saves", "1");
  await expect(banner).toHaveCount(0);
  expect((readTarget(ws.root, rel).match as { threshold: number }).threshold).toBe(0.84);
  expect(fs.readFileSync(image).equals(imageBytes)).toBe(true);
});

test("test_resave_keeps_user_imported_png", async () => {
  const userPng = fs.readFileSync(filePath(SAMPLE_WORKSPACE, "targets/title/start_button.png"));
  const rel = "targets/user/button.target.json";
  const { page, ws } = await open({
    "targets/user/source.png": userPng,
    [rel]: JSON.stringify({ format: "kookabug.target/0", image: "source.png", recorded: { client_size: [1024, 640], dpi: 96 } }, null, 2),
  });
  await openTarget(page, rel);
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  // 새 영역으로 다시 저장 → 새 이미지 파일. 사용자가 넣은 PNG는 어떤 target도 가리키지 않게 돼도 남는다
  await selectRect(page, TITLE_TEXT);
  await waitPreview(page, true);
  await saveTargetTab(page, rel);
  const spec = readTarget(ws.root, rel);
  expect(spec.image).not.toBe("source.png");
  expect(fs.existsSync(filePath(ws.root, `targets/user/${String(spec.image)}`))).toBe(true);
  expect(fs.readFileSync(filePath(ws.root, "targets/user/source.png")).equals(userPng)).toBe(true);
});

test("test_edit_existing_target_preserves_unknown_keys_and_minimal_diff", async () => {
  const png = fs.readFileSync(filePath(SAMPLE_WORKSPACE, "targets/title/start_button.png"));
  const rel = "targets/user/keep.target.json";
  // target 형식은 모르는 키를 받지 않는다(additionalProperties false). 여기서 "모르는 키"는 편집기가 다루지 않는
  // 키(sensitive·color_tolerance)다 (T6 test_save_existing_target_preserves_unknown_keys와 같은 뜻)
  const original = {
    sensitive: true,
    format: "kookabug.target/0",
    image: "keep.png",
    match: { color_tolerance: 25, threshold: 0.85 },
    click: { anchor: "top_left", offset: [3, -2] },
    recorded: { client_size: [1024, 640], dpi: 96 },
  };
  // 비canonical(4칸 들여쓰기·키 순서): 고친 키 말고는 의미가 그대로여야 한다
  const { page, ws } = await open({ "targets/user/keep.png": png, [rel]: JSON.stringify(original, null, 4) });
  const folder = listDir(ws.root, "targets/user");
  await openTarget(page, rel);
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  await expect(page.locator('[data-part="target-save"]')).toBeDisabled();
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await page.getByRole("checkbox", { name: "색까지 확인" }).uncheck();
  await saveTargetTab(page, rel);
  // 영역을 고르지 않았으니 JSON만 (이미지·폴더 그대로), 바뀐 것은 match 두 칸뿐
  expect(readJson(ws.root, rel)).toEqual({ ...original, match: { color_tolerance: 25, threshold: 0.83, rgb: false } });
  expect(fs.readFileSync(filePath(ws.root, "targets/user/keep.png")).equals(png)).toBe(true);
  expect(listDir(ws.root, "targets/user")).toEqual(folder);
  // 저장 결과 띠: crop 없는 저장은 바로 매칭 값이 없고, 편집기 미리보기는 디스크 이미지로 다시 찾는다
  await expect(page.locator('[data-part="target-saved"]')).toHaveAttribute("data-found", "");
  await waitPreview(page, true);
});

test("test_daemon_replaced_expires_frame_keeps_edits", async () => {
  const { page, ws } = await open();
  const rel = "targets/title/start_button.target.json";
  await openTarget(page, rel);
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  // daemon이 바뀌면 옛 frame_id는 전부 만료: "정지 화면을 다시 고르세요", 편집 중인 사양은 그대로 (2.3 6)
  await killDaemon(ws.root);
  await waitConnected(page, 30_000);
  await expect(page.locator('[data-part="frame-message"]')).toHaveText("정지 화면을 다시 고르세요");
  await expect(frameOf(page)).toHaveAttribute("data-frame", "");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  await expect(editorOf(page, rel)).toHaveAttribute("data-dirty", "true");
  // 다시 고르면 이어서 찾는다
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
});

// ── 늦은 응답 경계 (T12 검수 1차) ─────────────────────────────────

/** 주 프로세스 E2E 훅: 그 메서드의 다음 응답들을 늦춘다 */
async function delay(app: RunSession["app"], method: string, ms: number[]): Promise<void> {
  await app.evaluate(
    (_electron, [m, d]) => {
      (globalThis as unknown as { __kookabugE2E: { delayResponses(m: string, d: number[]): void } }).__kookabugE2E.delayResponses(m, d);
    },
    [method, ms] as [string, number[]],
  );
}

test("test_save_all_on_close_project_fills_graph_ref", async () => {
  // High 1: 저장 단추 대신 "프로젝트 닫기 → 모두 저장"으로 새 target을 저장해도 그 핀의 참조가 디스크에 남는다
  const { page, ws } = await open();
  await openGraphTab(page, INVENTORY);
  const rel = await newTargetFromInspector(page, "n_check_inventory", "review/new");
  await loadFrame(page, "captures/title.png");
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "프로젝트 닫기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("저장하지 않은 파일이");
  await dialog.getByRole("button", { name: "모두 저장" }).click();
  await expect(page.getByRole("button", { name: "프로젝트 열기" })).toBeVisible({ timeout: 30_000 });
  expect(fs.existsSync(filePath(ws.root, rel))).toBe(true);
  const graph = readJson<Graph>(ws.root, INVENTORY);
  expect(graph.nodes.n_check_inventory.in).toEqual({ target: { $target: rel }, timeout_ms: 5000 });
});

test("test_edit_during_save_keeps_saved_image_preview", async () => {
  // Mid 1: 저장 응답을 기다리는 동안 임계값을 바꿔도 저장 뒤 디스크 이미지로 미리보기하고 그 편집은 남는다
  const { app, page, ws } = await open();
  await openGraphTab(page, INVENTORY);
  const rel = await newTargetFromInspector(page, "n_check_inventory", "review/during");
  await loadFrame(page, "captures/title.png");
  const crop = await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await delay(app, "target.save", [2000]);
  await page.locator('[data-part="target-save"]').click();
  await expect(page.locator('[data-part="target-save"]')).toHaveText("저장 중…");
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  const editor = editorOf(page, rel);
  await expect(editor).toHaveAttribute("data-saves", "1", { timeout: 15_000 });
  expect(await waitPreview(page, true)).toEqual(crop);
  await expect(frameOf(page).locator('[data-part="template-rect"]')).toHaveCount(0);
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  await expect(editor).toHaveAttribute("data-dirty", "true");
  // 파일은 저장 때의 사양(임계값 없음), 다음 저장이 0.84를 쓴다 (이미지는 그대로)
  expect(readTarget(ws.root, rel).match).toBeUndefined();
  await saveTargetTab(page, rel);
  const spec = readTarget(ws.root, rel);
  expect(spec.match).toEqual({ threshold: 0.84 });
  expect(spec.image).toBe("during.png");
});

test("test_daemon_replaced_stale_preview_not_shown", async () => {
  // Mid 2: daemon 교체 전에 보낸 미리보기 성공 응답이 늦게 와도 만료된 화면에 "찾음"을 다시 보이지 않는다
  const { app, page, ws } = await open();
  await openTarget(page, "targets/title/start_button.target.json");
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  await delay(app, "target.preview", [7000]);
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(700);
  await killDaemon(ws.root);
  await waitConnected(page, 30_000);
  await expect(page.locator('[data-part="frame-message"]')).toHaveText("정지 화면을 다시 고르세요");
  await expect(previewOf(page)).toHaveAttribute("data-found", "");
  // 늦은 응답이 도착할 시간 (요청 뒤 7초)을 넘겨도 그대로
  await page.waitForTimeout(8000);
  await expect(previewOf(page)).toHaveAttribute("data-found", "");
  await expect(frameOf(page)).toHaveAttribute("data-frame", "");
  await expect(frameOf(page).locator('[data-part="match-rect"]')).toHaveCount(0);
});

test("test_auto_reload_keeps_edit_made_while_waiting", async () => {
  // High 2: 바깥 변경으로 자동 다시 열기를 기다리는 동안 한 편집은 지워지지 않고 충돌 띠가 뜬다
  const { app, page, ws } = await open();
  const rel = "targets/title/start_button.target.json";
  await openTarget(page, rel);
  await delay(app, "target.open", [3000]);
  const disk = readJson<Record<string, unknown>>(ws.root, rel);
  const external = JSON.stringify({ ...disk, match: { threshold: 0.9 } });
  fs.writeFileSync(filePath(ws.root, rel), external);
  await page.waitForTimeout(1500);
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  await expect(page.locator('[data-part="target-conflict"]')).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.84");
  await expect(editorOf(page, rel)).toHaveAttribute("data-dirty", "true");
  // 기준 revision은 그대로라 그냥 저장하면 다시 충돌, 파일은 밖에서 쓴 내용 그대로
  await page.locator('[data-part="target-save"]').click();
  await expect(page.locator('[data-part="target-conflict"]')).toBeVisible();
  expect(fs.readFileSync(filePath(ws.root, rel), "utf8")).toBe(external);
});

test("test_same_ref_completes_and_later_user_ref_kept", async () => {
  // 검수 2차 Mid 1: 핀이 처음부터 새 target 경로면 "채우지 못함"이 아니라 연결 완료다. 그 뒤 사용자가 핀을 다른
  // 대상으로 바꾸고 target을 다시 저장해도 그 참조를 덮지 않는다
  const rel = "targets/review/noop.target.json";
  const other = "targets/world/minimap.target.json";
  const ws = prepareRunWorkspace();
  addCapture(ws.root, "title.png");
  const before = readJson<Graph>(ws.root, INVENTORY);
  before.nodes.n_check_inventory.in = { ...before.nodes.n_check_inventory.in, target: { $target: rel } };
  writeFile(ws.root, INVENTORY, JSON.stringify(before, null, 2));
  s = await openRunApp(ws);
  const { page } = s;
  await openGraphTab(page, INVENTORY);
  await newTargetFromInspector(page, "n_check_inventory", "review/noop");
  await loadFrame(page, "captures/title.png");
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await saveTargetTab(page, rel);
  await expect(page.locator('[data-part="target-saved"]')).not.toContainText("채우지");
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "false");
  // 사용자가 핀을 다른 대상으로 바꿔 저장
  await tabOf(page, INVENTORY).getByRole("button").first().click();
  await selectOnly(page, "n_check_inventory");
  const field = page.locator('[data-part="inspector"] [data-part="field"][data-field="in"][data-pin="target"]');
  await field.getByRole("combobox", { name: "target", exact: true }).selectOption(other);
  await save(page, INVENTORY);
  // target을 고쳐 다시 저장해도 그래프는 그대로
  await tabOf(page, rel).getByRole("button").first().click();
  await page.getByRole("slider", { name: "유사도 임계값" }).focus();
  await page.keyboard.press("ArrowLeft");
  await saveTargetTab(page, rel);
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "false");
  expect(readJson<Graph>(ws.root, INVENTORY).nodes.n_check_inventory.in?.target).toEqual({ $target: other });
});

for (const [name, delays] of [
  ["first_arrives_first", [2000, 4000]],
  ["last_arrives_first", [4000, 1000]],
] as const) {
  test(`test_consecutive_image_picks_last_wins[${name}]`, async () => {
    // 검수 2차 Mid 2: 이미지를 연속으로 고르면 응답 순서와 무관하게 마지막으로 고른 것이 남고 고르기 창이 닫힌다
    const { app, page } = await open({}, ["title.png", "login.png"]);
    await openTarget(page, "targets/title/start_button.target.json");
    await delay(app, "target.load_image", [...delays]);
    await page.locator('[data-part="target-toolbar"]').getByRole("button", { name: "이미지에서" }).click();
    const picker = page.locator('[data-part="image-picker"]');
    for (const image of ["captures/title.png", "captures/login.png"]) {
      await picker.getByRole("textbox", { name: "PNG 경로" }).fill(image);
      await picker.getByRole("button", { name: "열기", exact: true }).click();
    }
    await expect(page.locator('[data-part="frame-source"]')).toHaveText("정지 화면 · captures/login.png", { timeout: 15_000 });
    await expect(picker).toHaveCount(0);
    // 늦은 쪽 응답이 모두 온 뒤에도 그대로
    await page.waitForTimeout(Math.max(...delays) + 500);
    await expect(page.locator('[data-part="frame-source"]')).toHaveText("정지 화면 · captures/login.png");
    // 로그인 화면에는 시작 버튼이 없다 (그 정지 화면으로 찾았다)
    await waitPreview(page, false);
  });
}

test("test_new_target_from_inspector_fills_ref", async () => {
  const { page, ws } = await open();
  await openGraphTab(page, INVENTORY);
  const rel = await newTargetFromInspector(page, "n_check_inventory", "inventory/new_title");
  await loadFrame(page, "captures/title.png");
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await saveTargetTab(page, rel);
  // 저장되면 그 핀에 {"$target": 경로}가 들어간다 (그래프는 저장 안 됨 상태)
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "true");
  await tabOf(page, INVENTORY).getByRole("button").first().click();
  await save(page, INVENTORY);
  const graph = readJson<Graph>(ws.root, INVENTORY);
  expect(graph.nodes.n_check_inventory.in).toEqual({ target: { $target: rel }, timeout_ms: 5000 });
  expect(fs.existsSync(filePath(ws.root, rel))).toBe(true);
});
