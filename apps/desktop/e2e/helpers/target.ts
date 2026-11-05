// target 편집기 E2E 도우미 (M2 계획 T12): TARGET 탭 열기, 정지 화면 고르기(이미지), 정지 화면 픽셀 좌표로 끌기·
// 누르기, 미리보기·저장 기다리기. 좌표는 정지 화면 물리 픽셀이고 판의 data-view(x,y,zoom)로 화면 좌표를 구한다
import fs from "node:fs";
import path from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";
import { REPO_ROOT } from "./app";
import { filePath, writeFile } from "./editor";

export const FRAMES_DIR = path.join(REPO_ROOT, "fixtures", "sample-game", "frames");
/** 예제 게임 타이틀 화면의 시작 버튼 (1024x640, 화면에 한 번만 있다) */
export const START_BUTTON = [412, 380, 200, 64] as const;
/** 타이틀 화면의 제목 글자 (시작 버튼과 다른 유일한 무늬) */
export const TITLE_TEXT = [312, 150, 400, 80] as const;

/** 장면 PNG를 워크스페이스 captures/에 넣는다 (워크스페이스 안이어야 target.load_image로 열 수 있다) */
export function addCapture(workspace: string, scene: string): string {
  const rel = `captures/${scene}`;
  writeFile(workspace, rel, fs.readFileSync(path.join(FRAMES_DIR, scene)));
  return rel;
}

export function editorOf(page: Page, rel: string): Locator {
  return page.locator(`[data-part="target-editor"][data-path="${rel}"]`);
}

export function frameOf(page: Page): Locator {
  return page.locator('[data-part="target-frame"]');
}

export function previewOf(page: Page): Locator {
  return page.locator('[data-part="preview-result"]');
}

/** 탐색기에서 target 파일을 열고 TARGET 편집기가 준비될 때까지 */
export async function openTarget(page: Page, rel: string): Promise<Locator> {
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  const parts = rel.split("/");
  for (let i = 1; i < parts.length; i++) {
    const dir = tree.locator(`[data-path="${parts.slice(0, i).join("/")}"]`);
    await expect(dir).toBeVisible();
    if ((await dir.getAttribute("aria-expanded")) === "false") await dir.click();
  }
  await tree.locator(`[data-path="${rel}"]`).click();
  const editor = editorOf(page, rel);
  await expect(editor).toHaveAttribute("data-status", "ready");
  return editor;
}

/** "이미지에서" → 경로 입력 → 열기. 정지 화면이 바뀔 때까지 */
export async function loadFrame(page: Page, image: string): Promise<string> {
  const before = (await frameOf(page).getAttribute("data-frame")) ?? "";
  await page.locator('[data-part="target-toolbar"]').getByRole("button", { name: "이미지에서" }).click();
  const picker = page.locator('[data-part="image-picker"]');
  await picker.getByRole("textbox", { name: "PNG 경로" }).fill(image);
  await picker.getByRole("button", { name: "열기" }).click();
  await expect(picker).toHaveCount(0);
  await expect(frameOf(page)).not.toHaveAttribute("data-frame", before === "" ? /^$/ : before);
  await expect(frameOf(page)).not.toHaveAttribute("data-view", "");
  return (await frameOf(page).getAttribute("data-frame")) ?? "";
}

/** 정지 화면 픽셀 (x, y)의 가운데가 있는 페이지 좌표 */
export async function pagePoint(page: Page, x: number, y: number): Promise<{ x: number; y: number }> {
  const frame = frameOf(page);
  const view = ((await frame.getAttribute("data-view")) ?? "").split(",").map(Number);
  if (view.length !== 3 || view.some((v) => !Number.isFinite(v))) throw new Error("정지 화면 보기가 없다");
  const [vx, vy, zoom] = view;
  const inner = await frame.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return { left: r.left + el.clientLeft, top: r.top + el.clientTop };
  });
  return { x: inner.left + vx + (x + 0.5) * zoom, y: inner.top + vy + (y + 0.5) * zoom };
}

/** 정지 화면 픽셀 a에서 b까지 끈다 (shift = 검색 범위) */
export async function dragPixels(page: Page, a: readonly [number, number], b: readonly [number, number], shift = false): Promise<void> {
  const p = await pagePoint(page, a[0], a[1]);
  const q = await pagePoint(page, b[0], b[1]);
  if (shift) await page.keyboard.down("Shift");
  await page.mouse.move(p.x, p.y);
  await page.mouse.down();
  await page.mouse.move((p.x + q.x) / 2, (p.y + q.y) / 2, { steps: 4 });
  await page.mouse.move(q.x, q.y, { steps: 4 });
  await page.mouse.up();
  if (shift) await page.keyboard.up("Shift");
}

/** 사각형 [x, y, w, h]을 끌어 고른다 (안쪽 2px 여유: 확대가 1보다 작아도 같은 픽셀 안을 누른다) */
export async function selectRect(page: Page, rect: readonly number[], shift = false): Promise<number[]> {
  const [x, y, w, h] = rect;
  await dragPixels(page, [x, y], [x + w - 1, y + h - 1], shift);
  const part = shift ? "search-rect" : "template-rect";
  const el = frameOf(page).locator(`[data-part="${part}"]`);
  await expect(el).toHaveCount(1);
  return ((await el.getAttribute("data-rect")) ?? "").split(",").map(Number);
}

/** 접힌 보조 패널(검색 범위 숫자·영역 글자·다른 배율, M4 T11)을 펼친다 */
export async function openExtPanels(page: Page): Promise<void> {
  const ext = page.locator('[data-part="ext-panels"]');
  if ((await ext.getAttribute("open")) === null) await page.locator('[data-part="ext-summary"]').click();
  await expect(page.locator('[data-part="search-panel"]')).toBeVisible();
}

export async function clickPixel(page: Page, x: number, y: number): Promise<void> {
  const p = await pagePoint(page, x, y);
  await page.mouse.click(p.x, p.y);
}

/** 찾은 결과까지 (찾음이면 그 상자) */
export async function waitPreview(page: Page, found: boolean): Promise<number[] | null> {
  await expect(previewOf(page)).toHaveAttribute("data-found", String(found), { timeout: 20_000 });
  if (!found) return null;
  const rect = frameOf(page).locator('[data-part="match-rect"]');
  await expect(rect).toHaveCount(1);
  return ((await rect.getAttribute("data-rect")) ?? "").split(",").map(Number);
}

/** 저장 단추를 누르고 저장 수가 늘 때까지 */
export async function saveTargetTab(page: Page, rel: string): Promise<void> {
  const editor = editorOf(page, rel);
  const saves = Number((await editor.getAttribute("data-saves")) ?? "0");
  await page.locator('[data-part="target-save"]').click();
  await expect(editor).toHaveAttribute("data-saves", String(saves + 1), { timeout: 30_000 });
  await expect(editor).toHaveAttribute("data-dirty", "false");
}

export function readTarget(workspace: string, rel: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(filePath(workspace, rel), "utf8")) as Record<string, unknown>;
}

/** 폴더의 파일 이름 목록 (정렬) */
export function listDir(workspace: string, rel: string): string[] {
  const dir = filePath(workspace, rel);
  return fs.existsSync(dir) ? fs.readdirSync(dir).sort() : [];
}
