// target 편집기 확장 (M4 계획 T11 완료 기준 e2e/target-ext.spec.ts): Shift+드래그 검색 범위 저장·숫자 칸·지우기,
// 민감 대상·색 허용치 저장(다른 키 보존·되돌리면 처음 JSON), 같은 모양 N곳·점선 상자·다른 배율 점수, 글자 읽기,
// 탐색기 targets/ 머리의 "새 찾기 대상" 단추. 실제 daemon(레포 .venv) + 예제 워크스페이스 사본 + 장면 PNG
import { expect, test } from "@playwright/test";
import { writeFile } from "./helpers/editor";
import { encodePng } from "./helpers/png";
import { closeRunApp, openRunApp, prepareRunWorkspace, type RunSession } from "./helpers/run";
import {
  addCapture,
  editorOf,
  frameOf,
  listDir,
  loadFrame,
  openExtPanels,
  openTarget,
  readTarget,
  saveTargetTab,
  selectRect,
  START_BUTTON,
  waitPreview,
} from "./helpers/target";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

const START = "targets/title/start_button.target.json";
const CLIENT: [number, number] = [1024, 640];

/** kookabug_platform.dpi.normalized_to_pixels */
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

/** 같은 무늬 셋이 있는 장면 (400x300, 무늬 40x30). 배경·무늬는 정해진 의사 난수라 매번 같다 */
const PATTERN_SIZE = [40, 30] as const;
const PATTERN_AT = [
  [60, 50],
  [280, 190],
  [170, 230],
] as const;

function patternScene(): Buffer {
  const [w, h] = [400, 300];
  let seed = 7;
  const next = () => {
    seed = (seed * 1103515245 + 12345) >>> 0;
    return (seed >>> 16) & 0xff;
  };
  const rgb = new Uint8Array(w * h * 3);
  for (let i = 0; i < rgb.length; i++) rgb[i] = next();
  const pattern = new Uint8Array(PATTERN_SIZE[0] * PATTERN_SIZE[1] * 3);
  seed = 11;
  for (let i = 0; i < pattern.length; i++) pattern[i] = next();
  for (const [px, py] of PATTERN_AT) {
    for (let y = 0; y < PATTERN_SIZE[1]; y++) {
      const src = y * PATTERN_SIZE[0] * 3;
      rgb.set(pattern.subarray(src, src + PATTERN_SIZE[0] * 3), ((py + y) * w + px) * 3);
    }
  }
  return encodePng(w, h, rgb);
}

async function open(): Promise<RunSession> {
  const ws = prepareRunWorkspace();
  addCapture(ws.root, "title.png");
  writeFile(ws.root, "captures/pattern_three.png", patternScene());
  s = await openRunApp(ws);
  return s;
}

test("test_shift_drag_sets_search_region_and_saves", async () => {
  const { page, ws } = await open();
  const before = readTarget(ws.root, START);
  await openTarget(page, START);
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  // Shift+드래그 = 검색 범위 (M2 사람 확인 T1에서 못 본 것)
  expect(await selectRect(page, [300, 330, 460, 200], true)).toEqual([300, 330, 460, 200]);
  // 보조 패널은 접혀 있다 (판을 넓게) — 요약 줄에 검색 범위가 있다고 보인다
  await expect(page.locator('[data-part="search-panel"]')).toHaveCount(0);
  await expect(page.locator('[data-part="ext-summary"]')).toContainText("검색 범위 있음");
  await openExtPanels(page);
  await expect(page.locator('[data-part="search-pixels"]')).toContainText("픽셀 300, 330 · 460×200");
  await expect(page.getByRole("textbox", { name: "검색 범위 x" })).toHaveValue(String(Math.round((300 / 1024) * 10000) / 10000));
  await waitPreview(page, true);
  await saveTargetTab(page, START);
  let saved = readTarget(ws.root, START) as { search: { region: number[] } } & Record<string, unknown>;
  expect(normalizedToPixels(saved.search.region, CLIENT)).toEqual([300, 330, 460, 200]);
  for (const key of ["click", "format", "image", "recorded"]) expect(saved[key]).toEqual(before[key]);

  // 숫자 칸으로 x를 고치면 판의 검색 범위가 따라오고 저장된다
  const x = page.getByRole("textbox", { name: "검색 범위 x" });
  await x.fill("0.25");
  await x.press("Enter");
  await expect(frameOf(page).locator('[data-part="search-rect"]')).toHaveAttribute("data-rect", "256,330,460,200");
  await saveTargetTab(page, START);
  saved = readTarget(ws.root, START) as typeof saved;
  expect(normalizedToPixels(saved.search.region, CLIENT)).toEqual([256, 330, 460, 200]);

  // 지우기: 검색 범위가 없어지고 저장하면 처음 파일과 같은 JSON
  await page.locator('[data-part="clear-search"]').click();
  await expect(frameOf(page).locator('[data-part="search-rect"]')).toHaveCount(0);
  await expect(page.locator('[data-part="search-pixels"]')).toContainText("화면 전체");
  await saveTargetTab(page, START);
  expect(readTarget(ws.root, START)).toEqual(before);
});

test("test_sensitive_checkbox_saved", async () => {
  const { page, ws } = await open();
  const before = readTarget(ws.root, START);
  await openTarget(page, START);
  const sensitive = page.getByRole("checkbox", { name: "민감 대상" });
  await expect(sensitive).not.toBeChecked();
  await sensitive.check();
  await expect(editorOf(page, START)).toHaveAttribute("data-dirty", "true");
  // 색 허용치 (색까지 확인이 켜져 있을 때)
  const tolerance = page.getByRole("textbox", { name: "색 허용치" });
  await expect(tolerance).toHaveValue("40");
  await tolerance.fill("25");
  await tolerance.press("Enter");
  await saveTargetTab(page, START);
  const saved = readTarget(ws.root, START);
  expect(saved.sensitive).toBe(true);
  expect(saved.match).toEqual({ color_tolerance: 25 });
  for (const key of ["click", "format", "image", "recorded"]) expect(saved[key]).toEqual(before[key]);
  // 이미지는 다시 쓰지 않는다 (사양만 저장)
  expect(listDir(ws.root, "targets/title").filter((n) => n.endsWith(".png")).sort()).toEqual(["maintenance_popup.png", "start_button.png"]);

  // 민감 대상을 끄면 키를 지운다 (색 허용치는 사용자가 정한 값이라 남는다)
  await sensitive.uncheck();
  await saveTargetTab(page, START);
  expect(readTarget(ws.root, START)).toEqual({ ...before, match: { color_tolerance: 25 } });

  // 글자 읽기: 찾은 상자(시작 버튼)의 글자
  await loadFrame(page, "captures/title.png");
  await waitPreview(page, true);
  // 민감 대상 툴팁은 기록 가림이 워크스페이스 설정을 따른다고 말한다 (D3)
  await expect(page.locator("label", { has: sensitive })).toHaveAttribute("title", /기록 가림은 워크스페이스 설정을 따라요/);
  await openExtPanels(page);
  await page.locator('[data-part="read-text"]').click();
  await expect(page.locator('[data-part="read-text-result"]')).toContainText("시작", { timeout: 30_000 });
});

test("test_same_shape_count_shown", async () => {
  const { page } = await open();
  await openTarget(page, START);
  await loadFrame(page, "captures/pattern_three.png");
  const [x, y] = PATTERN_AT[0];
  await selectRect(page, [x, y, PATTERN_SIZE[0], PATTERN_SIZE[1]]);
  await waitPreview(page, true);
  const same = page.locator('[data-part="same-shape"]');
  await expect(same).toHaveAttribute("data-count", "3");
  await expect(same).toContainText("같은 모양 3곳");
  // 찾은 상자 말고 두 자리를 점선 상자로 (셋 다 같은 점수라 어느 자리를 찾을지는 정하지 않는다)
  const peaks = frameOf(page).locator('[data-part="peak-rect"]');
  await expect(peaks).toHaveCount(2);
  const rects = await peaks.evaluateAll((els) => els.map((e) => e.getAttribute("data-rect")));
  const found = await frameOf(page).locator('[data-part="match-rect"]').getAttribute("data-rect");
  expect([found, ...rects].sort()).toEqual(PATTERN_AT.map(([px, py]) => `${px},${py},${PATTERN_SIZE[0]},${PATTERN_SIZE[1]}`).sort());

  // 다른 배율에서: 펼치면 1.00·1.25·1.50·2.00배 점수 표
  await openExtPanels(page);
  await expect(page.locator('[data-part="scale-note"]')).toHaveText("화면을 키워 계산한 값이에요 — 실제 DPI 변경은 더 낮을 수 있어요");
  const rows = page.locator('[data-part="scale-table"] tbody tr');
  await expect(rows).toHaveCount(4, { timeout: 30_000 });
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-factor")))).toEqual(["1", "1.25", "1.5", "2"]);

  // 시작 버튼처럼 하나뿐이면 표시하지 않는다
  await loadFrame(page, "captures/title.png");
  await frameOf(page).scrollIntoViewIfNeeded();
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await expect(same).toHaveCount(0);
  await expect(peaks).toHaveCount(0);
});

test("test_new_target_button_in_explorer", async () => {
  const { page, ws } = await open();
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  const button = tree.locator('[data-path="targets"] [data-part="new-target-button"]');
  await expect(button).toBeVisible();
  const expanded = await tree.locator('[data-path="targets"]').getAttribute("aria-expanded");
  await button.click();
  // 머리 줄 펼치기·접기는 바뀌지 않는다 (단추 누름이 줄로 가지 않는다)
  await expect(tree.locator('[data-path="targets"]')).toHaveAttribute("aria-expanded", expanded ?? "");
  const dialog = page.getByRole("dialog", { name: "새 찾기 대상" });
  await dialog.getByRole("textbox", { name: "이름" }).fill("ext/start");
  await dialog.getByRole("button", { name: "만들기" }).click();
  const rel = "targets/ext/start.target.json";
  await expect(editorOf(page, rel)).toHaveAttribute("data-new", "true");
  await loadFrame(page, "captures/title.png");
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await saveTargetTab(page, rel);
  expect(listDir(ws.root, "targets/ext")).toEqual(["start.png", "start.target.json"]);
  expect(readTarget(ws.root, rel).image).toBe("start.png");
});
