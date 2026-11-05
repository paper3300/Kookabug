// 시안 비교 스크린샷: target 편집기 확장 (M4 계획 T11 "시안 대비", 2.14). 기존 target 샷과 같은 상태(타이틀 정지 화면·
// 찾은 상자·검색 범위·임계값 0.80)에 시안에 없는 요소(U14)를 켠다: 민감 대상 체크, 색 허용치, 검색 범위 숫자 칸,
// 글자 읽기 결과, 펼친 "다른 배율에서" 점수 표
//   target-ext-<테마>        1440×900  vs Recorder(다크 시안뿐) — 보조 패널 접힘(기본), 오른쪽 영역 배치·색 대조
//   target-ext-open-<테마>   보조 패널 펼침 (사람 확인용)
//   target-ext-peaks-dark    1440×900  같은 모양 3곳·점선 상자 (시안 없음, 사람 확인용)
// 결과 build/ui-shots/target-ext-<테마>.png → node tools/design-ref/compare.mjs target-ext
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { writeFile } from "../helpers/editor";
import { encodePng } from "../helpers/png";
import { closeRunApp, openRunApp, prepareRunWorkspace, type RunSession } from "../helpers/run";
import { addCapture, loadFrame, openExtPanels, openTarget, selectRect, waitPreview } from "../helpers/target";

const OUT = path.join(REPO_BUILD, "ui-shots");
const TARGET = "targets/title/start_button.target.json";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

/** 같은 무늬 셋 (e2e/target-ext.spec.ts와 같은 장면, 1024x640로 키움) */
function patternScene(): Buffer {
  const [w, h] = [1024, 640];
  let seed = 7;
  const next = () => {
    seed = (seed * 1103515245 + 12345) >>> 0;
    return (seed >>> 16) & 0xff;
  };
  const rgb = new Uint8Array(w * h * 3);
  for (let i = 0; i < rgb.length; i++) rgb[i] = 40 + (next() >> 3);
  const [pw, ph] = [120, 72];
  const pattern = new Uint8Array(pw * ph * 3);
  seed = 11;
  for (let i = 0; i < pattern.length; i++) pattern[i] = next();
  for (const [px, py] of [
    [160, 120],
    [600, 150],
    [380, 420],
  ]) {
    for (let y = 0; y < ph; y++) rgb.set(pattern.subarray(y * pw * 3, (y + 1) * pw * 3), ((py + y) * w + px) * 3);
  }
  return encodePng(w, h, rgb);
}

async function shoot(page: Page, name: string): Promise<void> {
  await page.mouse.move(1, 1);
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await page.locator("body").focus();
  await settle(page);
  const file = path.join(OUT, `${name}.png`);
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
}

for (const theme of ["dark", "light"] as const) {
  test(`target-ext-${theme}`, async () => {
    fs.mkdirSync(OUT, { recursive: true });
    const ws = prepareRunWorkspace();
    addCapture(ws.root, "title.png");
    s = await openRunApp(ws, { scaleFactor: 1 });
    const { page } = s;
    await setTheme(page, theme);
    await openTarget(page, TARGET);
    await loadFrame(page, "captures/title.png");
    await waitPreview(page, true);
    await selectRect(page, [300, 330, 460, 200], true);
    const slider = page.getByRole("slider", { name: "유사도 임계값" });
    await slider.focus();
    for (let i = 0; i < 5; i++) await page.keyboard.press("ArrowLeft");
    await expect(page.locator('[data-part="threshold-value"]')).toHaveText("0.80");
    await page.getByRole("checkbox", { name: "민감 대상" }).check();
    await waitPreview(page, true);
    // 기본 상태: 보조 패널은 접힌 한 줄, 하단 출력 패널은 열린 채 — 판과 기본 조작부가 스크롤 없이 같이 보인다
    const body = page.locator('[data-part="target-frame"]').locator("xpath=..");
    const fit = await body.evaluate((el) => ({
      scroll: el.scrollHeight,
      client: el.clientHeight,
      parts: [...el.children].map((c) => Math.round(c.getBoundingClientRect().height)),
    }));
    expect(fit.scroll, JSON.stringify(fit)).toBeLessThanOrEqual(fit.client + 1);
    await shoot(page, `target-ext-${theme}`);
    // 보조 패널을 펼친 상태 (사람 확인용, 시안 비교 없음)
    await openExtPanels(page);
    await page.locator('[data-part="read-text"]').click();
    await expect(page.locator('[data-part="read-text-result"]')).toContainText("시작", { timeout: 30_000 });
    await expect(page.locator('[data-part="scale-table"] tbody tr')).toHaveCount(4, { timeout: 30_000 });
    await page.locator('[data-part="ext-panels"]').scrollIntoViewIfNeeded();
    await shoot(page, `target-ext-open-${theme}`);
  });
}

test("target-ext-peaks-dark", async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const ws = prepareRunWorkspace();
  writeFile(ws.root, "captures/pattern_three.png", patternScene());
  s = await openRunApp(ws, { scaleFactor: 1 });
  const { page } = s;
  await setTheme(page, "dark");
  await openTarget(page, TARGET);
  await loadFrame(page, "captures/pattern_three.png");
  await selectRect(page, [160, 120, 120, 72]);
  await waitPreview(page, true);
  await expect(page.locator('[data-part="same-shape"]')).toHaveAttribute("data-count", "3");
  await shoot(page, "target-ext-peaks-dark");
});
