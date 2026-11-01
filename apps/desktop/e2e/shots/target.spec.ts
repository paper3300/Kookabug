// 시안 비교 스크린샷: target 편집기 (M2 계획 T12 "시안 대비"). 시안 Recorder 오른쪽 영역(정지 화면·매칭
// 미리보기·클릭 지점)과 같은 상태를 만든다: 정지 화면(예제 게임 타이틀) + 찾은 상자·점수 배지 + 검색 범위 +
// 클릭 지점 십자, 임계값 0.80. 왼쪽 녹화 사이드바·녹화 상태 바는 M4 범위라 앱에 없다(의도한 차이)
//   target-<테마>  1440×900
// 결과 build/ui-shots/target-<테마>.png → node tools/design-ref/compare.mjs target
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { closeRunApp, openRunApp, prepareRunWorkspace, type RunSession } from "../helpers/run";
import { addCapture, loadFrame, openTarget, selectRect, waitPreview } from "../helpers/target";

const OUT = path.join(REPO_BUILD, "ui-shots");
const TARGET = "targets/title/start_button.target.json";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

for (const theme of ["dark", "light"] as const) {
  test(`target-${theme}`, async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const ws = prepareRunWorkspace();
    addCapture(ws.root, "title.png");
    s = await openRunApp(ws, { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    await openTarget(page, TARGET);
    await loadFrame(page, "captures/title.png");
    await waitPreview(page, true);
    // 시안처럼 시작 버튼 둘레의 검색 범위와 임계값 0.80
    await selectRect(page, [300, 330, 460, 200], true);
    const slider = page.getByRole("slider", { name: "유사도 임계값" });
    await slider.focus();
    for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowLeft");
    await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.80");
    await waitPreview(page, true);
    await expect(page.locator('[data-part="click-point"]')).toHaveCount(1);
    await page.mouse.move(1, 1);
    await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
    await page.locator("body").focus();
    await settle(page);
    const file = path.join(OUT, `target-${theme}.png`);
    await page.screenshot({ path: file });
    expect(fs.statSync(file).size).toBeGreaterThan(0);
  });
}
