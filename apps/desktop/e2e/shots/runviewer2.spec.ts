// 시안 비교 스크린샷: 기록 뷰어 2 (M3 계획 T11 "시안 대비", 2.12)
//   runviewer-compare-<테마>  1440×900  vs RunViewer(다크 시안뿐): RUN 머리 단추(에디터에서 재현·분석 번들 내보내기)·
//                                       하위 탭(노드별 통계·#<기준> 과 비교)·회차 막대·스크린샷 줄 머리의
//                                       "스크린샷 | 영상" 전환(U8, 시안에 없음)·매칭 후보 표 옆 "#<기준> (성공) 과
//                                       차이" 상자·상태 바 보관 문구
//   runviewer-stats-<테마>    노드별 통계 탭 (시안은 탭 이름뿐, 내용은 시안에 없음)
// 결과 build/ui-shots/runviewer-*-<테마>.png → node tools/design-ref/compare.mjs runviewer-compare runviewer-stats runviewer-comparetab
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { closeRunApp, openRunApp, prepareRunWorkspace, type RunSession } from "../helpers/run";
import {
  rowOfNode,
  runItem,
  runTab,
  runToEnd,
  setLocalGameArgs,
  setWorkspaceVideo,
  showRunList,
  VIEWER_CMP,
  writeViewerGraphs,
} from "../helpers/runs";

const OUT = path.join(REPO_BUILD, "ui-shots");

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

for (const theme of ["dark", "light"] as const) {
  test(`runviewer-compare-${theme}`, async () => {
    test.setTimeout(300_000);
    fs.mkdirSync(OUT, { recursive: true });
    const ws = prepareRunWorkspace();
    writeViewerGraphs(ws);
    setWorkspaceVideo(ws, "failed_only");
    s = await openRunApp(ws, { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    setLocalGameArgs(ws, ["-m", "sample_game", "--maintenance"]);
    await runToEnd(page, VIEWER_CMP, "pass");
    setLocalGameArgs(ws, null);
    const fail = await runToEnd(page, VIEWER_CMP, "fail");
    await showRunList(page);
    await runItem(page, fail).click();
    await expect(runTab(page, fail)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
    // 회차 막대를 펼친다 (시안 위쪽 막대 줄)
    await rowOfNode(page, "n_repeat").locator('[data-part="timeline-toggle"]').click();
    await expect(page.locator('[data-part="iteration-bar"]')).toHaveCount(3);
    const box = page.locator('[data-part="compare-box"]');
    await expect(box).not.toHaveAttribute("data-baseline", "", { timeout: 30_000 });
    await expect(page.locator('[data-part="shot-image"]').first()).toHaveJSProperty("complete", true);
    await box.scrollIntoViewIfNeeded();
    await page.mouse.move(1, 1);
    await settle(page);
    const file = path.join(OUT, `runviewer-compare-${theme}.png`);
    await page.screenshot({ path: file });
    expect(fs.statSync(file).size).toBeGreaterThan(0);

    await page.locator('[data-part="subtab-stats"]').click();
    await expect(page.locator('[data-part="stats-row"]').first()).toBeVisible();
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `runviewer-stats-${theme}.png`) });
    await page.locator('[data-part="subtab-compare"]').click();
    await expect(page.locator('[data-part="compare-image"]')).toHaveJSProperty("complete", true);
    await settle(page);
    await page.screenshot({ path: path.join(OUT, `runviewer-comparetab-${theme}.png`) });
  });
}
