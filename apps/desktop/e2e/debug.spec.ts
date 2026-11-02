// 에디터 디버거 UI (M3 계획 2.9, T9 완료 기준). 실제 daemon + 가짜 플랫폼으로 예제 그래프를 돌린다.
// 멈춤 판단은 runner가 하고, 화면은 이벤트로만 안다: 실행 폴더의 events.jsonl과 화면을 같이 본다.
// 단축키·끌기는 Playwright가 페이지에 넣는 입력이다 (OS 입력을 보내지 않는다)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { closeApp, setContentSize } from "./helpers/app";
import { openGraph, selectOnly, tabOf, writeFile } from "./helpers/editor";
import {
  clickRun,
  closeRunApp,
  debugToolbar,
  INVENTORY,
  openRunApp,
  prepareRunWorkspace,
  readEvents,
  releaseGate,
  runFolder,
  runNode,
  toolbar,
  waitEnded,
  waitGate,
  type RunSession,
  type RunWorkspace,
} from "./helpers/run";

const SUB = "subgraphs/enter_world.graph.json";
const DELAY = "tests/debug_delay.graph.json";
const STALE = "tests/debug_stale.graph.json";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

const button = (page: Page, name: string): Locator => debugToolbar(page).getByRole("button", { name, exact: true });
const banner = (page: Page): Locator => page.locator('[data-part="pause-banner"]');
const runState = (page: Page): Locator => page.locator('[data-part="run-state"]');
const runId = async (page: Page): Promise<string> => (await toolbar(page).getAttribute("data-run-id"))!;

/** 그 노드에서 멈췄다 (노란 테두리·상태 줄·멈춤 띠) */
async function expectPausedAt(page: Page, node: string, reason: "breakpoint" | "step" | "request", banneredNode = node): Promise<void> {
  await expect(debugToolbar(page)).toHaveAttribute("data-state", "paused", { timeout: 60_000 });
  await expect(runNode(page, node)).toHaveAttribute("data-paused", reason);
  await expect(page.locator('[data-part="node"][data-paused]')).toHaveCount(1);
  await expect(banner(page)).toHaveAttribute("data-node", banneredNode);
  await expect(banner(page)).toHaveAttribute("data-reason", reason);
}

/** 실행 폴더의 debug.pause 기록 */
function pauses(ws: RunWorkspace, id: string): Record<string, unknown>[] {
  return readEvents(ws, id).filter((e) => e.event === "debug.pause");
}

function breakpointsFile(ws: RunWorkspace): { graph: string; node: string }[] {
  const file = path.join(ws.root, ".kookabug", "breakpoints.json");
  if (!fs.existsSync(file)) return [];
  return (JSON.parse(fs.readFileSync(file, "utf8")) as { breakpoints: { graph: string; node: string }[] }).breakpoints;
}

/** 머리 왼쪽 점 자리를 눌러 브레이크포인트를 건다 */
async function clickSpot(page: Page, node: string): Promise<void> {
  await runNode(page, node).locator('[data-part="bp-spot"]').click();
  await expect(runNode(page, node)).toHaveAttribute("data-breakpoint", "true");
}

const GRAPH_HEAD = { format: "kookabug.graph/0", kind: "test", plugins: { core: "0.1.0" } };
const LAUNCH = {
  type: "core.app.launch",
  version: 1,
  title: "게임 실행",
  in: {
    args: { $setting: "game.args" },
    cwd: { $setting: "game.cwd" },
    path: { $setting: "game.executable" },
    timeout_ms: 30000,
    window_title: { $setting: "game.title" },
  },
};

test("test_breakpoint_pauses_and_marks_node_then_continue_passes", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  // 노드를 고르고 F9: 머리 왼쪽 빨간 점, daemon이 브레이크포인트 파일에 쓴다
  await selectOnly(page, "n_press_i");
  await page.keyboard.press("F9");
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-breakpoint", "true");
  await expect(runNode(page, "n_press_i").locator('[data-part="bp-dot"]')).toBeVisible();
  await expect.poll(() => breakpointsFile(ws)).toEqual([{ graph: INVENTORY, node: "n_press_i" }]);
  // 실행이 없으면 디버그 툴바가 없다
  await expect(debugToolbar(page)).toHaveCount(0);

  await clickRun(page);
  await expectPausedAt(page, "n_press_i", "breakpoint");
  await expect(runNode(page, "n_press_i").locator('[data-part="node-paused"]')).toHaveText("⏸ 멈춤");
  await expect(runNode(page, "n_press_i").locator('[data-part="node-paused"]')).toHaveAttribute("title", "멈춤 · 브레이크포인트");
  await expect(banner(page)).toContainText("⏸ 멈춤 · 브레이크포인트 · I 키");
  // 상태 바는 파랑(실행 중) 그대로 "⏸ 멈춤 · 노드 제목"
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "true");
  await expect(runState(page)).toHaveText("⏸ 멈춤 · I 키");
  // 멈춘 동안: 계속이 일시정지 자리에, Step 단추가 켜짐
  await expect(button(page, "계속 F5")).toBeEnabled();
  await expect(button(page, "다음 노드 F10")).toBeEnabled();
  const id = await runId(page);
  // 화면은 기록의 debug.pause 그대로다 (노드는 아직 시작 전: step.start 없음)
  expect(pauses(ws, id)).toEqual([expect.objectContaining({ node: "n_press_i", graph: INVENTORY, reason: "breakpoint", where: "boundary" })]);
  expect(readEvents(ws, id).some((e) => e.event === "step.start" && e.node === "n_press_i")).toBe(false);

  await button(page, "계속 F5").click();
  await waitEnded(page, "pass");
  await expect(page.locator('[data-part="node"][data-paused]')).toHaveCount(0);
  await expect(banner(page)).toHaveCount(0);
  await expect(debugToolbar(page)).toHaveCount(0);
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-run-tone", "ok");
  const runJson = JSON.parse(fs.readFileSync(path.join(runFolder(ws, id), "run.json"), "utf8")) as Record<string, unknown>;
  expect(runJson.debug_intervened).toBe(true);
  expect(runJson.pause_count).toBe(1);
  // 브레이크포인트는 실행 뒤에도 남는다
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-breakpoint", "true");
});

test("test_step_over_into_out_buttons_and_keys", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  // 오른쪽 클릭 메뉴로 호출 노드에 건다
  await runNode(page, "n_enter_world").locator('[data-part="node-head"]').click({ button: "right" });
  await page.locator('[data-part="node-menu"]').getByRole("menuitem", { name: /브레이크포인트 설정/ }).click();
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-breakpoint", "true");
  await clickRun(page);
  await expectPausedAt(page, "n_enter_world", "breakpoint");

  // F11: 서브그래프 첫 동작 노드에서 멈춘다(시작점은 건너뜀). 루트 탭은 호출 노드에 표시한다
  await page.keyboard.press("F11");
  await expect(banner(page)).toHaveAttribute("data-node", "n_launch");
  // F11은 창 전체 화면 전환이 아니라 디버거 명령이다
  expect(await s.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].isFullScreen())).toBe(false);
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-paused", "step");
  // 서브그래프 탭을 열면 안쪽 노드에도 표시한다
  await openGraph(page, SUB);
  await expect(runNode(page, "n_launch")).toHaveAttribute("data-paused", "step");
  await expect(runState(page)).toHaveText("⏸ 멈춤 · 게임 실행");

  // F10: 같은 깊이 다음 노드
  await page.keyboard.press("F10");
  await expectPausedAt(page, "n_wait_title", "step");
  await button(page, "다음 노드 F10").click();
  await expectPausedAt(page, "n_click_start", "step");
  // 입력 노드가 받는 Match는 입력 서비스가 다시 찾으므로 재개 경고가 없다
  await expect(page.locator('[data-part="resume-warning"]')).toHaveCount(0);

  // Shift+F11 서브그래프에서 나오기: 호출이 돌아온 뒤 루트의 다음 노드 (호출이 낸 창을 현재 창으로 정하는 노드)
  await expect(button(page, "서브그래프에서 나오기")).toBeEnabled();
  await expect(button(page, "서브그래프로 들어가기 F11")).toBeEnabled();
  await page.keyboard.press("Shift+F11");
  await expect(banner(page)).toHaveAttribute("data-node", "n_use_window", { timeout: 60_000 });
  await tabOf(page, INVENTORY).locator("button").first().click();
  await expectPausedAt(page, "n_use_window", "step");
  await page.keyboard.press("F10");
  await expectPausedAt(page, "n_press_i", "step");
  await page.keyboard.press("F10");
  await expectPausedAt(page, "n_check_inventory", "step");
  // F5: 계속
  await page.keyboard.press("F5");
  await waitEnded(page, "pass");

  const steps = pauses(ws, await runId(page)).map((e) => [e.node, e.reason, (e.path as string[]).length]);
  expect(steps).toEqual([
    ["n_enter_world", "breakpoint", 1],
    ["n_launch", "step", 2],
    ["n_wait_title", "step", 2],
    ["n_click_start", "step", 2],
    ["n_use_window", "step", 1],
    ["n_press_i", "step", 1],
    ["n_check_inventory", "step", 1],
  ]);
  const modes = readEvents(ws, await runId(page))
    .filter((e) => e.event === "debug.resume")
    .map((e) => e.mode);
  expect(modes).toEqual(["step_into", "step_over", "step_over", "step_out", "step_over", "step_over", "continue"]);
});

test("test_pause_during_wait_then_resume", async () => {
  const ws = prepareRunWorkspace();
  writeFile(
    ws.root,
    DELAY,
    JSON.stringify({
      ...GRAPH_HEAD,
      meta: { title: "지연 중 멈춤" },
      nodes: {
        n_entry: { type: "core.graph.entry", version: 1, title: "시작", next: { start: "n_delay" } },
        n_delay: { type: "core.flow.delay", version: 1, title: "6초 대기", in: { ms: 6000 }, next: { done: "n_pass" } },
        n_pass: { type: "core.test.pass", version: 1, title: "성공" },
      },
      layout: { nodes: { n_entry: { x: 0, y: 0 }, n_delay: { x: 260, y: 0 }, n_pass: { x: 520, y: 0 } } },
    }),
  );
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, DELAY);
  await clickRun(page);
  await expect(runNode(page, "n_delay")).toHaveAttribute("data-run", "active", { timeout: 30_000 });
  // F6: 기다리는 노드 안(폴링 확인 지점)에서 바로 멈춘다
  await page.keyboard.press("F6");
  await expectPausedAt(page, "n_delay", "request");
  await expect(banner(page)).toHaveAttribute("data-where", "poll");
  await expect(banner(page)).toContainText("(기다리는 중)");
  // 멈춘 동안은 기한·지연이 흐르지 않는다: 지연보다 길게 두어도 끝나지 않는다
  await page.waitForTimeout(6500);
  await expect(debugToolbar(page)).toHaveAttribute("data-state", "paused");
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running");
  await button(page, "계속 F5").click();
  await waitEnded(page, "pass");

  const events = readEvents(ws, await runId(page));
  expect(events.filter((e) => e.event === "debug.pause")).toEqual([
    expect.objectContaining({ node: "n_delay", reason: "request", where: "poll" }),
  ]);
  const end = events.find((e) => e.event === "run.end")!;
  expect(end.debug_intervened).toBe(true);
  expect(end.paused_ms as number).toBeGreaterThanOrEqual(6000);
  expect(end.active_duration_ms as number).toBeLessThan(end.duration_ms as number);
});

test("test_stop_button_in_debug_toolbar_only", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  // 탭 줄 툴바에는 실행 ▶만 있다 (정지는 시안대로 디버그 툴바)
  await expect(toolbar(page).getByRole("button", { name: "정지" })).toHaveCount(0);
  await clickSpot(page, "n_press_i");
  await clickRun(page);
  await expectPausedAt(page, "n_press_i", "breakpoint");
  await expect(toolbar(page).getByRole("button", { name: "정지" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "정지", exact: true })).toHaveCount(1);
  // 멈춘 실행도 정지가 바로 먹는다 (취소가 재개를 이긴다)
  await button(page, "정지").click();
  await waitEnded(page);
  expect(await toolbar(page).getAttribute("data-verdict")).not.toBe("pass");
  const end = readEvents(ws, await runId(page)).find((e) => e.event === "run.end")!;
  expect(String(end.cancel_reason ?? end.code)).toMatch(/cancel/);
  await expect(debugToolbar(page)).toHaveCount(0);
  await expect(banner(page)).toHaveCount(0);
});

test("test_restart_starts_new_run", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  await clickSpot(page, "n_press_i");
  await clickRun(page);
  await expectPausedAt(page, "n_press_i", "breakpoint");
  const first = await runId(page);
  await button(page, "다시 시작").click();
  // 새 실행을 따라가고, 그 순간의 브레이크포인트로 다시 멈춘다
  await expect.poll(() => runId(page), { timeout: 60_000 }).not.toBe(first);
  const second = await runId(page);
  await expectPausedAt(page, "n_press_i", "breakpoint");
  // 옛 실행은 취소로 끝났다
  const oldEnd = readEvents(ws, first).find((e) => e.event === "run.end")!;
  expect(oldEnd.verdict).not.toBe("pass");
  expect(pauses(ws, second)).toHaveLength(1);
  await page.keyboard.press("F5");
  await waitEnded(page, "pass");
  expect(await runId(page)).toBe(second);
  // 단축키 Ctrl+Shift+F5도 같은 명령이다 (실행이 없으면 아무것도 하지 않는다)
  await page.keyboard.press("Control+Shift+F5");
  await expect(debugToolbar(page)).toHaveCount(0);
});

test("test_toolbar_hidden_without_run_and_drag_position_kept", async () => {
  const ws = prepareRunWorkspace({ i: "press_i" });
  s = await openRunApp(ws);
  const { page, userData } = s;
  await openGraph(page, INVENTORY);
  await expect(debugToolbar(page)).toHaveCount(0);
  await clickRun(page);
  await waitGate(ws, "press_i");
  await expect(debugToolbar(page)).toHaveAttribute("data-state", "running");
  await expect(button(page, "일시정지 F6")).toBeEnabled();
  await expect(button(page, "다음 노드 F10")).toBeDisabled();
  const area = page.locator('[data-part="debug-toolbar"]').locator("xpath=..");
  const areaBox = (await area.boundingBox())!;
  const before = (await debugToolbar(page).boundingBox())!;
  // 손잡이로 가로로 150px 옮긴다
  const handle = page.locator('[data-part="debug-toolbar-handle"]');
  const h = (await handle.boundingBox())!;
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
  await page.mouse.down();
  await page.mouse.move(h.x + h.width / 2 + 150, h.y + h.height / 2 + 40, { steps: 10 });
  await page.mouse.up();
  await expect(debugToolbar(page)).toHaveAttribute("data-x", "150");
  const moved = (await debugToolbar(page).boundingBox())!;
  expect(Math.round(moved.x - before.x)).toBe(150);
  expect(moved.y).toBe(before.y); // 세로로는 움직이지 않는다
  // 앱 설정에 기억한다
  await expect
    .poll(() => (JSON.parse(fs.readFileSync(path.join(userData, "settings.json"), "utf8")) as { debugToolbarX?: number }).debugToolbarX)
    .toBe(150);

  releaseGate(ws, "press_i");
  await waitEnded(page, "pass");
  await expect(debugToolbar(page)).toHaveCount(0);

  // 다음 실행에도 같은 자리
  await clickSpot(page, "n_check_inventory");
  await clickRun(page);
  await expectPausedAt(page, "n_check_inventory", "breakpoint");
  const again = (await debugToolbar(page).boundingBox())!;
  expect(Math.round(again.x + again.width / 2 - (areaBox.x + areaBox.width / 2))).toBe(150);
  await button(page, "정지").click();
  await waitEnded(page);
});

/** 툴바 자리: 기억한 값(data-x), 화면 값(data-shown-x), 영역 안에 다 들어 있는가 */
async function toolbarPlace(page: Page): Promise<{ x: number; shown: number; inside: boolean; left: number }> {
  return page.evaluate(() => {
    const bar = document.querySelector<HTMLElement>('[data-part="debug-toolbar"]')!;
    const area = bar.parentElement!.getBoundingClientRect();
    const box = bar.getBoundingClientRect();
    return {
      x: Number(bar.dataset.x),
      shown: Number(bar.dataset.shownX),
      inside: box.left >= area.left && box.right <= area.right && bar.style.visibility !== "hidden",
      left: box.left,
    };
  });
}

async function dragHandle(page: Page, dx: number): Promise<void> {
  const h = (await page.locator('[data-part="debug-toolbar-handle"]').boundingBox())!;
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
  await page.mouse.down();
  await page.mouse.move(h.x + h.width / 2 + dx, h.y + h.height / 2, { steps: 8 });
  await page.mouse.up();
}

function savedX(userData: string): number | undefined {
  return (JSON.parse(fs.readFileSync(path.join(userData, "settings.json"), "utf8")) as { debugToolbarX?: number }).debugToolbarX;
}

test("test_toolbar_stays_inside_on_resize_restores_and_redrags", async () => {
  // 검수 T9-1: 멈춘 채(다른 상태 변화 없이) 창만 줄여도 툴바·정지 단추가 영역 안에 남고, 기억한 자리는 그대로라
  // 넓히면 돌아가며, 줄인 자리에서 다시 끌면 튀지 않는다. 작은 창으로 다시 열어도 첫 표시부터 영역 안이다
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page, app, userData } = s;
  await openGraph(page, INVENTORY);
  await clickSpot(page, "n_press_i");
  await clickRun(page);
  await expectPausedAt(page, "n_press_i", "breakpoint");
  await dragHandle(page, 200);
  const wide = await toolbarPlace(page);
  expect(wide.x).toBeGreaterThan(100);
  expect(wide.shown).toBe(wide.x);
  await expect.poll(() => savedX(userData)).toBe(wide.x);

  // 넓은 창 → 최소 폭: 화면 자리만 안으로 들인다
  await setContentSize(app, page, 960, 900);
  await expect.poll(async () => (await toolbarPlace(page)).inside).toBe(true);
  const narrow = await toolbarPlace(page);
  expect(narrow.x).toBe(wide.x);
  expect(narrow.shown).toBeLessThan(wide.x);
  await expect(button(page, "정지")).toBeInViewport({ ratio: 1 });
  expect(savedX(userData)).toBe(wide.x);

  // 다시 넓히면 기억한 자리로 돌아간다
  await setContentSize(app, page, 1440, 900);
  await expect.poll(async () => (await toolbarPlace(page)).shown).toBe(wide.x);

  // 줄인 자리에서 다시 끌기: 보정된 자리에서 시작한다 (기억한 자리로 튀지 않음)
  await setContentSize(app, page, 960, 900);
  await expect.poll(async () => (await toolbarPlace(page)).inside).toBe(true);
  const before = await toolbarPlace(page);
  await dragHandle(page, -40);
  const after = await toolbarPlace(page);
  expect(after.x).toBe(before.shown - 40);
  expect(Math.round(after.left - before.left)).toBe(-40);
  await expect.poll(() => savedX(userData)).toBe(before.shown - 40);
  await button(page, "정지").click();
  await waitEnded(page);

  // 작은 창에서 큰 저장 자리로 다시 연다: 첫 표시부터 영역 안, 기억한 값은 그대로
  await closeApp(app);
  const settings = JSON.parse(fs.readFileSync(path.join(userData, "settings.json"), "utf8")) as Record<string, unknown>;
  fs.writeFileSync(path.join(userData, "settings.json"), JSON.stringify({ ...settings, debugToolbarX: 300 }));
  s = await openRunApp(ws, { userData });
  const again = s.page;
  await setContentSize(s.app, again, 960, 900);
  await openGraph(again, INVENTORY);
  await clickRun(again);
  await expectPausedAt(again, "n_press_i", "breakpoint");
  const reopened = await toolbarPlace(again);
  expect(reopened.x).toBe(300);
  expect(reopened.inside).toBe(true);
  expect(reopened.shown).toBeLessThan(300);
  await button(again, "정지").click();
  await waitEnded(again);
});

test("test_resume_warning_for_stale_input", async () => {
  const ws = prepareRunWorkspace();
  writeFile(
    ws.root,
    STALE,
    JSON.stringify({
      ...GRAPH_HEAD,
      meta: { title: "오래된 관측 경고" },
      nodes: {
        n_entry: { type: "core.graph.entry", version: 1, title: "시작", next: { start: "n_launch" } },
        n_launch: { ...LAUNCH, next: { attached: "n_wait" } },
        n_wait: {
          type: "core.image.wait",
          version: 1,
          title: "타이틀 대기",
          in: { target: { $target: "targets/title/start_button.target.json" }, timeout_ms: 30000 },
          next: { found: "n_check" },
        },
        n_check: {
          type: "core.assert.compare",
          version: 1,
          title: "찾은 자리 확인",
          in: { a: { $link: "n_wait.match" }, b: "없음", op: "!=" },
          next: { ok: "n_pass" },
        },
        n_pass: { type: "core.test.pass", version: 1, title: "성공" },
      },
      layout: {
        nodes: {
          n_entry: { x: 0, y: 0 },
          n_launch: { x: 240, y: 0 },
          n_wait: { x: 480, y: 0 },
          n_check: { x: 720, y: 0 },
          n_pass: { x: 960, y: 0 },
        },
      },
    }),
  );
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, STALE);
  await clickSpot(page, "n_check");
  await clickRun(page);
  await expectPausedAt(page, "n_check", "breakpoint");
  // 멈추기 전 관측(타이틀 대기.match)을 받는 검증 노드: 재개하면 실패한다고 미리 알린다
  await expect(page.locator('[data-part="resume-warning"]')).toHaveText(
    "재개하면 '찾은 자리 확인'는 멈추기 전 화면 값(타이틀 대기.match)을 쓸 수 없어 실패합니다",
  );
  await button(page, "계속 F5").click();
  // 실제 판정은 runner: 노드를 부르지 않고 stale_observation 실패
  await waitEnded(page, "fail");
  await expect(runNode(page, "n_check")).toHaveAttribute("data-run-tone", "fail");
  const events = readEvents(ws, await runId(page));
  const step = events.find((e) => e.event === "step.start" && e.node === "n_check")!.step;
  const end = events.find((e) => e.event === "step.end" && e.step === step)!;
  expect(end.status).toBe("fail");
  expect(String(end.message)).toMatch(/^stale_observation:/);
});
