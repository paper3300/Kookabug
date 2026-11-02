// 시안 비교 스크린샷: 디버거 (M3 계획 T9 "시안 대비", 2.12)
//   main-debug-<테마>         1440×900  vs Main·MainLight: 실행 중 디버그 툴바(상자·단추 색·간격), 정지 단추가
//                                       탭 줄에서 빠짐, 브레이크포인트 점(시안에 없음, U1)
//   main-debug-paused-<테마>  1440×900  vs Main·MainLight: 브레이크포인트에서 멈춘 상태 — 툴바 "계속", 노란 테두리·
//                                       "⏸ 멈춤", 멈춤 띠, 상태 바 "⏸ 멈춤 · 노드" (시안에 없음, U2)
// 그래프는 시안 Main 배치(shots/run.spec.ts와 같은 실행 가능한 사본)다. 브레이크포인트는 실행 전에 파일로 둔다
// 결과 build/ui-shots/main-debug*-<테마>.png → node tools/design-ref/compare.mjs main-debug main-debug-paused
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { openGraph } from "../helpers/editor";
import {
  clickRun,
  closeRunApp,
  debugToolbar,
  openRunApp,
  prepareRunWorkspace,
  runNode,
  runnableSianMain,
  SIAN_RUN_GRAPH as GRAPH,
  type RunSession,
} from "../helpers/run";

const OUT = path.join(REPO_BUILD, "ui-shots");

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

async function open(theme: "dark" | "light", breakpoints: string[]): Promise<Page> {
  fs.mkdirSync(OUT, { recursive: true });
  const ws = prepareRunWorkspace();
  fs.writeFileSync(path.join(ws.root, ...GRAPH.split("/")), runnableSianMain());
  fs.writeFileSync(
    path.join(ws.root, ".kookabug", "breakpoints.json"),
    JSON.stringify({ format: "kookabug.breakpoints/0", breakpoints: breakpoints.map((node) => ({ graph: GRAPH, node })) }),
  );
  s = await openRunApp(ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, theme);
  await openGraph(page, GRAPH);
  await expect(page.locator(".react-flow__node")).toHaveCount(10);
  for (const node of breakpoints) await expect(runNode(page, node)).toHaveAttribute("data-breakpoint", "true");
  return page;
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.mouse.move(1, 1);
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await settle(page);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

for (const theme of ["dark", "light"] as const) {
  test(`main-debug-${theme}`, async () => {
    // 지나가지 않을 노드(OCR 읽기)에 건 브레이크포인트 점 + 시안과 같은 "● 1.4s" 시점의 툴바
    const page = await open(theme, ["n_ocr"]);
    await clickRun(page);
    await expect(runNode(page, "n_wait")).toHaveAttribute("data-run", "active", { timeout: 30_000 });
    await expect(runNode(page, "n_wait").locator('[data-part="node-status"]')).toHaveText(/^● 1\.\ds$/, { timeout: 5000 });
    await expect(debugToolbar(page)).toHaveAttribute("data-state", "running");
    await shoot(page, `main-debug-${theme}`);
  });

  test(`main-debug-paused-${theme}`, async () => {
    const page = await open(theme, ["n_wait"]);
    await clickRun(page);
    await expect(debugToolbar(page)).toHaveAttribute("data-state", "paused", { timeout: 30_000 });
    await expect(runNode(page, "n_wait")).toHaveAttribute("data-paused", "breakpoint");
    await shoot(page, `main-debug-paused-${theme}`);
  });
}
