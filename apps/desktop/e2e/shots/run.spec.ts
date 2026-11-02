// 시안 비교 스크린샷: 실행 중간 시점 (M2 계획 T11 "시안 대비")
//   main-running-<테마>  1440×900  vs Main·MainLight 전체 (강조 노드·상태 줄·실행 로그·파란 상태 바)
// 그래프는 e2e/fixtures/sian-main.graph.json(시안 Main 노드 배치)에서 "창 찾기"만 가짜 플랫폼에서 돌도록 게임
// 실행 노드로 바꾼 것이다(가짜 플랫폼에는 실행 전에 창이 없다). 반복 → 이미지 클릭 → "나타날 때까지 대기"가
// 오류 팝업을 기다리는 동안(제한 10초) 찍는다: 시안의 "● 1.4s" 시점
// 결과 build/ui-shots/main-running-<테마>.png → node tools/design-ref/compare.mjs main-running
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { openGraph } from "../helpers/editor";
import {
  clickRun,
  closeRunApp,
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

for (const theme of ["dark", "light"] as const) {
  test(`main-running-${theme}`, async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const ws = prepareRunWorkspace();
    fs.writeFileSync(path.join(ws.root, ...GRAPH.split("/")), runnableSianMain());
    s = await openRunApp(ws, { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    await openGraph(page, GRAPH);
    await expect(page.locator(".react-flow__node")).toHaveCount(10);
    await clickRun(page);
    // 시안과 같은 시점: 대기 노드가 강조되고 1초 남짓 지났다
    await expect(runNode(page, "n_wait")).toHaveAttribute("data-run", "active", { timeout: 30_000 });
    await expect(runNode(page, "n_wait").locator('[data-part="node-status"]')).toHaveText(/^● 1\.\ds$/, { timeout: 5000 });
    await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "true");
    await page.mouse.move(1, 1);
    await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
    await settle(page);
    const file = path.join(OUT, `main-running-${theme}.png`);
    await page.screenshot({ path: file });
    expect(fs.statSync(file).size).toBeGreaterThan(0);
  });
}
