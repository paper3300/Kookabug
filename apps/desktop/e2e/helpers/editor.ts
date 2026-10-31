// 그래프 편집 E2E 도우미 (M2 계획 T9): 워크스페이스 사본 열기, 탭 열기, 노드 끌기·핀 잇기·팔레트 끌어 놓기,
// 저장 기다리기, Python 코어 규칙으로 파일 보기 (graph_check.py)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type ElectronApplication, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_ROOT, setContentSize, stubOpenDialog } from "./app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./daemon";

export const CORPUS_DIR = path.join(REPO_ROOT, "fixtures", "graph-corpus");
const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const CHECK = path.join(import.meta.dirname, "graph_check.py");

export interface EditorSession {
  app: ElectronApplication;
  page: Page;
  userData: string;
  workspace: string;
}

/** 예제 워크스페이스 사본에 파일을 더해(첫 트리에 보이게) 앱으로 연다 */
export async function openEditor(files: Record<string, string | Buffer> = {}): Promise<EditorSession> {
  const workspace = copySampleWorkspace();
  for (const [rel, data] of Object.entries(files)) writeFile(workspace, rel, data);
  const { app, userData } = await launchApp();
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  return { app, page, userData, workspace };
}

export async function closeEditor(s: EditorSession | null): Promise<void> {
  if (s === null) return;
  await closeApp(s.app);
  await cleanupWorkspace(s.workspace);
  fs.rmSync(s.userData, { recursive: true, force: true });
}

export function filePath(workspace: string, rel: string): string {
  return path.join(workspace, ...rel.split("/"));
}

export function writeFile(workspace: string, rel: string, data: string | Buffer): void {
  const file = filePath(workspace, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, data);
}

export function readBytes(workspace: string, rel: string): Buffer {
  return fs.readFileSync(filePath(workspace, rel));
}

export function readJson<T = Record<string, unknown>>(workspace: string, rel: string): T {
  return JSON.parse(readBytes(workspace, rel).toString("utf8")) as T;
}

export function mtime(workspace: string, rel: string): number {
  return fs.statSync(filePath(workspace, rel)).mtimeMs;
}

/** 탐색기에서 연다. 폴더가 접혀 있으면 펼친다 */
export async function openGraph(page: Page, rel: string): Promise<Locator> {
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  const parts = rel.split("/");
  for (let i = 1; i < parts.length; i++) {
    const dir = tree.locator(`[data-path="${parts.slice(0, i).join("/")}"]`);
    await expect(dir).toBeVisible();
    if ((await dir.getAttribute("aria-expanded")) === "false") await dir.click();
  }
  await tree.locator(`[data-path="${rel}"]`).click();
  const canvas = canvasOf(page, rel);
  await expect(canvas).toHaveAttribute("data-status", "ready");
  if ((await canvas.locator(".react-flow").count()) > 0) await settleCanvas(page);
  return canvas;
}

export function canvasOf(page: Page, rel: string): Locator {
  return page.locator(`[data-part="canvas"][data-path="${rel}"]`);
}

export function tabOf(page: Page, rel: string): Locator {
  return page.locator(`[role="tab"][data-path="${rel}"]`);
}

export function nodeEl(page: Page, id: string): Locator {
  return page.locator(`.react-flow__node[data-id="${id}"]`);
}

export function pin(page: Page, node: string, handle: string): Locator {
  return nodeEl(page, node).locator(`[data-pin="${handle}"]`);
}

async function center(l: Locator): Promise<{ x: number; y: number }> {
  const box = await l.boundingBox();
  if (box === null) throw new Error("보이지 않는 요소");
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

/** 캔버스가 처음 맞춤(fitView)을 끝내 노드 자리가 멈출 때까지 */
export async function settleCanvas(page: Page): Promise<void> {
  let last = "";
  await expect
    .poll(
      async () => {
        const now = await page.evaluate(() => {
          const vp = document.querySelector<HTMLElement>(".react-flow__viewport");
          const measured = document.querySelectorAll(".react-flow__node:not([style*='visibility: hidden'])").length;
          return `${vp?.style.transform ?? ""}|${measured}`;
        });
        const same = now === last && !now.startsWith("|");
        last = now;
        return same;
      },
      { intervals: [100, 100, 150, 200, 250] },
    )
    .toBe(true);
}

/** 노드 머리를 잡고 끈다 (끌기 하나 = 이동 명령 하나). 줌이 작아도 노드 안을 잡는다 */
export async function dragNode(page: Page, id: string, dx: number, dy: number): Promise<void> {
  const head = nodeEl(page, id).locator('[data-part="node-head"]');
  const box = await head.boundingBox();
  if (box === null) throw new Error(`보이지 않는 노드: ${id}`);
  const x = box.x + Math.min(24, box.width / 4);
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 12 });
  await page.mouse.up();
}

/** 핀에서 핀으로 끌어 잇는다. during: 놓기 전에 할 일 (호환 표시 확인) */
export async function connectPins(page: Page, from: Locator, to: Locator, during?: () => Promise<void>): Promise<void> {
  const a = await center(from);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(a.x + 30, a.y + 10, { steps: 4 });
  // 데이터 연결이면 숨긴 입력 핀이 생겨 자리가 바뀔 수 있다: 움직인 뒤 도착 핀 자리를 잰다
  if (during !== undefined) await during();
  const b = await center(to);
  await page.mouse.move(b.x, b.y, { steps: 10 });
  await page.mouse.up();
}

/** 팔레트에서 찾아 캔버스 위 자리(캔버스 기준)에 끌어 놓는다. 새 노드 ID를 돌려준다 */
export async function dropFromPalette(page: Page, canvas: Locator, query: string, type: string, at: { x: number; y: number }): Promise<string> {
  const before = new Set(await nodeIds(page));
  await page.getByRole("searchbox", { name: "노드 검색" }).fill(query);
  const item = page.locator(`[data-node-type="${type}"]`);
  await expect(item).toBeVisible();
  await item.dragTo(canvas, { targetPosition: at });
  await page.getByRole("searchbox", { name: "노드 검색" }).fill("");
  let added = "";
  await expect
    .poll(async () => {
      const now = (await nodeIds(page)).filter((id) => !before.has(id));
      added = now[0] ?? "";
      return now.length;
    })
    .toBe(1);
  expect(added).toMatch(/^n_[a-z2-7]{8}$/);
  return added;
}

export async function nodeIds(page: Page): Promise<string[]> {
  return page.$$eval(".react-flow__node[data-id]", (els) =>
    els.map((e) => e.getAttribute("data-id") ?? "").filter((id) => !id.includes(":")),
  );
}

/** 연결선 경로의 가운데 점을 누른다 (곡선의 상자 가운데는 선 위가 아닐 수 있다) */
export async function clickEdge(page: Page, id: string): Promise<void> {
  const at = await page.evaluate((edgeId) => {
    const edge = [...document.querySelectorAll(".react-flow__edge")].find((e) => e.getAttribute("data-id") === edgeId);
    const path = edge?.querySelector<SVGPathElement>("path.react-flow__edge-path");
    const ctm = path?.getScreenCTM();
    if (!path || !ctm) return null;
    const p = path.getPointAtLength(path.getTotalLength() / 2);
    return { x: p.x * ctm.a + p.y * ctm.c + ctm.e, y: p.x * ctm.b + p.y * ctm.d + ctm.f };
  }, id);
  if (at === null) throw new Error(`연결선이 없다: ${id}`);
  await page.mouse.click(at.x, at.y);
}

/** Ctrl+S 하고 저장 응답까지 기다린다 */
export async function save(page: Page, rel: string): Promise<void> {
  const canvas = canvasOf(page, rel);
  const before = Number((await canvas.getAttribute("data-saves")) ?? "0");
  await page.keyboard.press("Control+S");
  await expect(canvas).toHaveAttribute("data-saves", String(before + 1));
}

/** 그 노드만 고른다 (머리 누르기) */
export async function selectOnly(page: Page, id: string): Promise<void> {
  await nodeEl(page, id).locator('[data-part="node-head"]').click();
  await expect(nodeEl(page, id)).toHaveClass(/selected/);
}

function python(args: string[]): unknown {
  const out = execFileSync(PYTHON, ["-X", "utf8", CHECK, ...args], { encoding: "utf8", env: { ...process.env, PYTHONUTF8: "1" } });
  return JSON.parse(out.trim().split("\n").at(-1)!);
}

/** 파일 값이 기대 값과 Python `json_equal`로 같은가 */
export function pyEqual(file: string, expected: unknown): boolean {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-expect-"));
  try {
    const exp = path.join(dir, "expected.json");
    fs.writeFileSync(exp, JSON.stringify(expected));
    return (python(["equal", file, exp]) as { equal: boolean }).equal;
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

/** 포인터 자리 값의 Python 타입 이름 */
export function pyTypes(file: string, pointers: string[]): Record<string, string> {
  return (python(["types", file, ...pointers]) as { types: Record<string, string> }).types;
}
