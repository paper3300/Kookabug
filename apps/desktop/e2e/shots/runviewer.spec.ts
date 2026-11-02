// 시안 비교 스크린샷: 기록 뷰어 (M3 계획 T10 "시안 대비", 2.12)
//   runviewer-<테마>  1440×900  vs RunViewer(다크 시안뿐): 액티비티 바 "실행 기록"·사이드바 실행 목록(날짜 묶음·결과 점·
//                               배지·메타)·RUN 탭 머리·하위 탭·스텝 타임라인(실패 사슬 펼침)·스크린샷 줄(처음·중간·
//                               시간 초과 + 후보 상자)·매칭 후보 표
// 에이전트 패널·"에이전트에게 분석 요청"·"수집 데이터"는 숨긴다(U11, M5). 노드별 통계·비교·재현·내보내기는 T11
// 결과 build/ui-shots/runviewer-<테마>.png → node tools/design-ref/compare.mjs runviewer
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { closeRunApp, openRunApp, prepareRunWorkspace, type RunSession } from "../helpers/run";
import { cloneRun, runItem, runTab, runToEnd, showRunList, VIEWER_FAIL, VIEWER_LOOP, VIEWER_NOASSERT, writeViewerGraphs } from "../helpers/runs";

const OUT = path.join(REPO_BUILD, "ui-shots");

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

for (const theme of ["dark", "light"] as const) {
  test(`runviewer-${theme}`, async () => {
    test.setTimeout(300_000);
    fs.mkdirSync(OUT, { recursive: true });
    const ws = prepareRunWorkspace();
    writeViewerGraphs(ws);
    s = await openRunApp(ws, { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    const loop = await runToEnd(page, VIEWER_LOOP, "pass");
    cloneRun(ws, loop, "f1a2b3c4", { retried_steps: 1 });
    await runToEnd(page, VIEWER_NOASSERT, "fail");
    const fail = await runToEnd(page, VIEWER_FAIL, "fail");
    await showRunList(page);
    await runItem(page, fail).click();
    await expect(runTab(page, fail)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
    await expect(page.locator('[data-part="shot-image"]').first()).toHaveJSProperty("complete", true);
    await expect(page.locator('[data-part="candidate-box"]').first()).toBeVisible();
    await page.mouse.move(1, 1);
    await settle(page);
    const file = path.join(OUT, `runviewer-${theme}.png`);
    await page.screenshot({ path: file });
    expect(fs.statSync(file).size).toBeGreaterThan(0);
  });
}
