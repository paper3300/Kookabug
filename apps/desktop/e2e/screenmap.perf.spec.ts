// 화면 지도 성능 (M7 계획 3.14): 카드 300·간선 600 합성 지도. 여유 큰 단언(그리기 15초·확대 3초) — 성능 회귀를
// 잡는 용도이고, 정밀 측정이 아니다. 합성 지도는 화면 판정 파일 형식 그대로 쓴다(지도 계산은 daemon이 한다)
import { expect, test } from "@playwright/test";
import { closeEditor, openEditor, type EditorSession } from "./helpers/editor";

let s: EditorSession | null = null;

test.afterEach(async () => {
  await closeEditor(s);
  s = null;
});

const COUNT = 300;

function syntheticScreens(): Record<string, string> {
  const files: Record<string, string> = {};
  for (let i = 0; i < COUNT; i++) {
    const id = `screen_${String(i).padStart(3, "0")}`;
    const next = (n: number) => `screen_${String(n % COUNT).padStart(3, "0")}`;
    files[`screens/perf/${id}.screen.json`] = JSON.stringify({
      format: "kookabug.screen/1",
      title: `화면 ${i}`,
      detect: { all: [{ $target: "targets/login/login_button.target.json" }] },
      moves: [
        { via: { key: "f1" }, to: next(i + 1), status: "tried" },
        { via: { key: "f2" }, to: next(i * 7 + 3), status: i % 5 === 0 ? "untried" : "tried" },
      ],
    });
  }
  return files;
}

test("screen map draws 300 cards and 600 edges quickly", async () => {
  test.setTimeout(180_000);
  s = await openEditor(syntheticScreens());
  const { page } = s;
  await page.locator('[data-part="activity-screens"]').click();
  const started = Date.now();
  await page.locator('[data-part="map-row"]').first().click();
  const map = page.locator('[data-part="screen-map"]');
  // 예제 워크스페이스의 확정 화면도 함께 그린다 (300 이상)
  await expect.poll(() => map.locator('[data-part="map-card"]').count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(COUNT);
  const drawn = Date.now() - started;
  expect(await map.locator('[data-part="map-edge"]').count()).toBeGreaterThanOrEqual(2 * COUNT);
  expect(drawn).toBeLessThan(15_000);
  // 확대·축소가 늦지 않다
  // 처음 보기는 화면에 맞춘 확대 (큰 지도라 작다) — 확대 단추 한 번이 3초 안에 반영
  const label = page.locator('[data-part="map-zoom"] span');
  const before = await label.textContent();
  const zoomStart = Date.now();
  await page.locator('[data-part="map-zoom"] button[aria-label="확대"]').click();
  await expect(label).not.toHaveText(before ?? "");
  expect(Date.now() - zoomStart).toBeLessThan(3_000);
  console.log(`화면 지도 그리기 ${drawn}ms (카드 ${COUNT}, 간선 ${2 * COUNT})`);
});
