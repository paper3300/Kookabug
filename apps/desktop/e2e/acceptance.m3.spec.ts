// M3 완료 기준 인수 검사, 앱 쪽 (M3 계획 3장 "완료 기준 → 테스트 매핑"). 실제 Electron 앱 + 실제 daemon(레포 .venv) +
// 예제 워크스페이스 사본 + 가짜 플랫폼(예제 장면 표). 다른 검사 모듈은 가져오지 않고 helpers만 쓴다.
//
// 1. 실패 실행을 뷰어로 열어 실패 노드까지 한 번에 이동 — 목록 클릭 한 번 → 실패 스텝 선택·증거, "그래프에서 보기" →
//    스냅샷 노드 강조. 입력 계산 실패(`any → string` type_mismatch) 실행도 그 노드로 간다 (2차 N1)
// 2. 재개 후 대상이 사라졌으면 입력이 나가지 않음 — 브레이크포인트에서 멈춘 사이 화면이 바뀐 실행: 입력 없이
//    stale_observation, 화면에 그 노드 실패·이유
// (범위) 서브그래프 펼치기·스크린샷·지난 성공과 비교
// (범위) 브레이크포인트·Step Into/Over/Out
//
// Python 쪽 인수는 python/kookabug_core/tests/acceptance/test_m3.py. 실행을 만드는 데 시간이 들어 앱 하나·워크스페이스
// 하나를 검사들이 차례로 같이 쓴다 (serial). 장면이 다른 2번만 따로 앱을 띄운다
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { canvasOf, nodeEl, openGraph, settleCanvas, tabOf, writeFile } from "./helpers/editor";
import {
  clickRun,
  closeRunApp,
  debugToolbar,
  INVENTORY,
  openRunApp,
  prepareRunWorkspace,
  readEvents,
  runNode,
  toolbar,
  waitEnded,
  type RunSession,
  type RunWorkspace,
} from "./helpers/run";
import {
  rowOfNode,
  runEnd,
  runFolderOf,
  runItem,
  runTab,
  runToEnd,
  setLocalGameArgs,
  showRunList,
  startRun,
  timelineRow,
  VIEWER_CHECK,
  VIEWER_CMP,
  VIEWER_FAIL,
  waitRunEnded,
  writeViewerGraphs,
} from "./helpers/runs";

test.describe.configure({ mode: "serial" });

const EVAL_FAIL = "tests/m3_eval_fail.graph.json";
const TARGET_GONE = "tests/m3_target_gone.graph.json";
const SUB = "subgraphs/enter_world.graph.json";
const START_BUTTON = { $target: "targets/title/start_button.target.json" };
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
const HEAD = { format: "kookabug.graph/0", kind: "test", plugins: { core: "0.1.0" } };

/** var.set(7) → var.get(any) → log.message(string): 정적 검증은 통과하고 입력 계산에서 type_mismatch */
const EVAL_FAIL_GRAPH = {
  ...HEAD,
  meta: { title: "입력 계산 실패" },
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, title: "시작", next: { start: "n_set" } },
    n_set: { type: "core.var.set", version: 1, title: "값 넣기", in: { name: "x", value: 7 }, next: { done: "n_log" } },
    n_get: { type: "core.var.get", version: 1, title: "값 읽기", in: { name: "x" } },
    n_log: { type: "core.log.message", version: 1, title: "글자로 남기기", in: { text: { $link: "n_get.value" } } },
  },
  layout: { nodes: { n_entry: { x: 0, y: 0 }, n_set: { x: 240, y: 0 }, n_get: { x: 240, y: 200 }, n_log: { x: 480, y: 0 } } },
};

/** 타이틀 시작 단추를 찾아(대기) 그 매칭으로 클릭 */
const TARGET_GONE_GRAPH = {
  ...HEAD,
  meta: { title: "재개 뒤 대상 사라짐" },
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, title: "시작", next: { start: "n_launch" } },
    n_launch: { ...LAUNCH, next: { attached: "n_wait" } },
    n_wait: { type: "core.image.wait", version: 1, title: "타이틀 대기", in: { target: START_BUTTON, timeout_ms: 30000 }, next: { found: "n_click" } },
    n_click: { type: "core.input.click", version: 1, title: "시작 클릭", in: { match: { $link: "n_wait.match" } }, next: { done: "n_pass" } },
    n_pass: { type: "core.test.pass", version: 1, title: "성공" },
  },
  layout: {
    nodes: {
      n_entry: { x: 0, y: 0 },
      n_launch: { x: 240, y: 0 },
      n_wait: { x: 480, y: 0 },
      n_click: { x: 720, y: 0 },
      n_pass: { x: 960, y: 0 },
    },
  },
};

let s: RunSession | null = null;
const runs: Record<"fail" | "eval" | "base" | "cmp", string> = { fail: "", eval: "", base: "", cmp: "" };

test.beforeAll(async () => {
  test.setTimeout(600_000);
  const ws = prepareRunWorkspace();
  writeViewerGraphs(ws);
  writeFile(ws.root, EVAL_FAIL, JSON.stringify(EVAL_FAIL_GRAPH, null, 2));
  s = await openRunApp(ws);
  const { page } = s;
  runs.fail = await runToEnd(page, VIEWER_FAIL, "fail");
  runs.eval = await startRun(page, EVAL_FAIL);
  expect(await waitRunEnded(page, runs.eval)).toBe("error");
  // 지난 성공과 비교: 게임 인수 --maintenance면 점검 팝업이 떠 통과(기준), 없으면 로그인 화면이라 실패
  setLocalGameArgs(ws, ["-m", "sample_game", "--maintenance"]);
  runs.base = await runToEnd(page, VIEWER_CMP, "pass");
  setLocalGameArgs(ws, null);
  runs.cmp = await runToEnd(page, VIEWER_CMP, "fail");
});

test.afterAll(async () => {
  await closeRunApp(s);
  s = null;
});

function session(): RunSession {
  if (s === null) throw new Error("앱이 없다");
  return s;
}

/** 목록에서 한 번 눌러 RUN 탭을 연다 (그 한 번으로 실패 스텝까지 간다) */
async function openFromList(page: Page, runId: string): Promise<void> {
  await showRunList(page);
  await expect(runItem(page, runId)).toBeVisible({ timeout: 15_000 });
  await runItem(page, runId).click();
  await expect(runTab(page, runId)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
}

function stepOf(ws: RunWorkspace, runId: string, node: string): { start: Record<string, unknown>; end: Record<string, unknown> } {
  const events = readEvents(ws, runId);
  const start = events.find((e) => e.event === "step.start" && e.node === node);
  if (start === undefined) throw new Error(`${node} 스텝이 없다`);
  const end = events.find((e) => e.event === "step.end" && e.step === start.step);
  if (end === undefined) throw new Error(`${node} step.end가 없다`);
  return { start, end };
}

// ── 1. 실패 노드까지 한 번에 ────────────────────────────────────────

test("test_failed_run_one_action_to_failure_node", async () => {
  const { page, ws } = session();
  const failure = runEnd(ws, runs.fail).failure_step as string;
  expect(runEnd(ws, runs.fail).failure_path).toEqual(["n_call", "n_wait_missing"]);
  // 목록 클릭 한 번: 실패 사슬이 펼쳐지고 실패 스텝이 골라져 화면 안에 있다 + 증거
  await openFromList(page, runs.fail);
  await expect(runTab(page, runs.fail)).toHaveAttribute("data-selected", failure);
  const row = timelineRow(page, failure);
  await expect(row).toHaveAttribute("aria-selected", "true");
  await expect(row).toHaveAttribute("data-node", "n_wait_missing");
  await expect(row).toHaveAttribute("data-status", "fail");
  await expect(row).toBeInViewport();
  await expect(rowOfNode(page, "n_call")).toHaveAttribute("aria-expanded", "true");
  const evidence = page.locator(`[data-part="evidence"][data-step="${failure}"]`);
  const last = evidence.locator('[data-part="shot"][data-kind="last"]');
  await expect(last.locator("[data-part=shot-image]")).toHaveJSProperty("complete", true);
  expect(await last.locator("[data-part=shot-image]").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);

  // 실행 뒤 그래프 파일이 바뀌었다: "그래프에서 보기"는 실행 때 스냅샷을 읽기 전용으로 열고 실패 노드를 고른다
  const file = path.join(ws.root, ...VIEWER_CHECK.split("/"));
  const original = fs.readFileSync(file, "utf8");
  const changed = JSON.parse(original) as { nodes: Record<string, { title: string }> };
  changed.nodes.n_wait_missing.title = "실행 뒤 바꾼 제목";
  fs.writeFileSync(file, JSON.stringify(changed, null, 2) + "\n");
  try {
    await page.locator('[data-part="view-in-graph"]').click();
    const snapTab = page.locator('[role="tab"][data-kind="SNAPSHOT"]');
    await expect(snapTab).toHaveAttribute("aria-selected", "true");
    const snapPath = (await snapTab.getAttribute("data-path"))!;
    expect(snapPath).toMatch(new RegExp(`^runs/[^/]+_${runs.fail}/snapshot/${VIEWER_CHECK}$`));
    const canvas = canvasOf(page, snapPath);
    await expect(canvas).toHaveAttribute("data-readonly", "true");
    await settleCanvas(page);
    const node = canvas.locator('.react-flow__node[data-id="n_wait_missing"]');
    await expect(node).toHaveClass(/selected/);
    await expect(node).toContainText("점검 팝업 대기");
    await snapTab.locator('[aria-label^="탭 닫기"]').click();
    await expect(snapTab).toHaveCount(0);
  } finally {
    fs.writeFileSync(file, original);
  }
});

test("test_input_eval_failure_run_jumps_to_node", async () => {
  // 2차 N1: 입력 계산이 실패한 스텝도 step.start·step.end가 남아 run.end.failure_step → 색인 → 뷰어가 그 노드를 고른다
  const { page, ws } = session();
  const end = runEnd(ws, runs.eval);
  expect(end.code).toBe("type_mismatch");
  const { start, end: stepEnd } = stepOf(ws, runs.eval, "n_log");
  expect(end.failure_step).toBe(start.step);
  expect(stepEnd.status).toBe("error");
  await openFromList(page, runs.eval);
  await expect(runTab(page, runs.eval)).toHaveAttribute("data-selected", start.step as string);
  const row = timelineRow(page, start.step as string);
  await expect(row).toHaveAttribute("aria-selected", "true");
  await expect(row).toHaveAttribute("data-node", "n_log");
  await expect(row).toHaveAttribute("data-status", "error");
  await expect(page.locator(`[data-part="evidence"][data-step="${start.step as string}"]`)).toContainText("글자로 남기기");
  // 그래프가 그대로면 워크스페이스 그래프에서 그 노드를 고른다
  await page.locator('[data-part="view-in-graph"]').click();
  await expect(tabOf(page, EVAL_FAIL)).toHaveAttribute("aria-selected", "true");
  await expect(nodeEl(page, "n_log")).toHaveClass(/selected/);
});

// ── (범위) 서브그래프 펼치기·스크린샷·지난 성공과 비교 ──────────────────────

test("test_viewer_expand_screenshots_compare", async () => {
  const { page, ws } = session();
  // 서브그래프 펼치기·접기 (실패 실행의 호출 줄)
  await openFromList(page, runs.fail);
  const call = rowOfNode(page, "n_call");
  await expect(rowOfNode(page, "n_wait_title")).toHaveCount(1);
  await call.locator('[data-part="timeline-toggle"]').click();
  await expect(call).toHaveAttribute("aria-expanded", "false");
  await expect(rowOfNode(page, "n_wait_title")).toHaveCount(0);
  await call.locator('[data-part="timeline-toggle"]').click();
  await expect(rowOfNode(page, "n_wait_title")).toHaveCount(1);

  // 비교할 실패 실행: 스크린샷 줄(처음·마지막) + 지난 성공과 비교 상자
  const failure = runEnd(ws, runs.cmp).failure_step as string;
  await openFromList(page, runs.cmp);
  await expect(runTab(page, runs.cmp)).toHaveAttribute("data-selected", failure);
  const evidence = page.locator(`[data-part="evidence"][data-step="${failure}"]`);
  for (const kind of ["first", "last"]) {
    const image = evidence.locator(`[data-part="shot"][data-kind="${kind}"] [data-part=shot-image]`);
    await expect(image).toHaveJSProperty("complete", true);
    expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  }
  const box = page.locator('[data-part="compare-box"]');
  await expect(box).toHaveAttribute("data-baseline", runs.base, { timeout: 30_000 });
  await expect(box).toContainText(`#${runs.base.slice(0, 4)} (성공) 과 차이`);
  await expect(box.locator('[data-part="compare-screen"]')).toHaveAttribute("data-differs", "true");
  await expect(box.locator('[data-part="compare-graph"]')).toHaveText(/^같음 · [0-9a-f]{6}$/);
  await expect(box.locator('[data-part="compare-env"]')).toContainText("game.args");
  // 비교 탭: 두 화면 + 차이 영역 상자
  await page.locator('[data-part="subtab-compare"]').click();
  await expect(page.locator('[data-part="compare-tab"]')).toBeVisible();
  await expect(page.locator('[data-part="diff-box"]').first()).toBeVisible();
  const base = page.locator('[data-part="baseline-image"]');
  await expect(base).toHaveJSProperty("complete", true);
  expect(await base.getAttribute("src")).toContain(runs.base);
});

// ── (범위) 브레이크포인트·Step Into/Over/Out ────────────────────────────

const button = (page: Page, name: string): Locator => debugToolbar(page).getByRole("button", { name, exact: true });
const banner = (page: Page): Locator => page.locator('[data-part="pause-banner"]');

/**
 * 그 노드에서 멈췄다. 툴바 `data-state`는 재개 이벤트(`debug.resume`)가 오기 전까지 앞 멈춤 그대로
 * paused라 단추를 누른 직후에는 바로 맞는다 — 다음 멈춤은 배너의 노드로 기다린다 (서브그래프에서
 * 나오기는 남은 서브그래프 대기·입력 노드를 다 돈 뒤에 멈춘다. 기다림 상한은 멈춤 기다림과 같은 60초)
 */
async function expectPausedAt(page: Page, node: string, reason: "breakpoint" | "step"): Promise<void> {
  await expect(banner(page)).toHaveAttribute("data-node", node, { timeout: 60_000 });
  await expect(debugToolbar(page)).toHaveAttribute("data-state", "paused");
  await expect(banner(page)).toHaveAttribute("data-reason", reason);
}

test("test_breakpoint_step_into_over_out", async () => {
  test.setTimeout(240_000);
  const { page, ws } = session();
  await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
  await page.getByRole("button", { name: /^탐색기/ }).click();
  await openGraph(page, INVENTORY);
  // 호출 노드 머리 왼쪽 점 자리로 브레이크포인트
  await runNode(page, "n_enter_world").locator('[data-part="bp-spot"]').click();
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-breakpoint", "true");
  await clickRun(page);
  await expectPausedAt(page, "n_enter_world", "breakpoint");
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-paused", "breakpoint");
  // 서브그래프로 들어가기 F11 → 서브그래프 첫 동작 노드, 다음 노드 F10 → 같은 깊이 다음 노드
  await page.keyboard.press("F11");
  await expectPausedAt(page, "n_launch", "step");
  await button(page, "다음 노드 F10").click();
  await expectPausedAt(page, "n_wait_title", "step");
  // 서브그래프에서 나오기 Shift+F11 → 호출이 돌아온 뒤 루트의 다음 노드
  await button(page, "서브그래프에서 나오기").click();
  await expectPausedAt(page, "n_use_window", "step");
  await page.keyboard.press("F10");
  await expectPausedAt(page, "n_press_i", "step");
  await button(page, "계속 F5").click();
  await waitEnded(page, "pass");
  await expect(debugToolbar(page)).toHaveCount(0);

  const id = (await toolbar(page).getAttribute("data-run-id"))!;
  const events = readEvents(ws, id);
  const pauses = events.filter((e) => e.event === "debug.pause").map((e) => [e.node, e.reason, (e.path as string[]).length]);
  expect(pauses).toEqual([
    ["n_enter_world", "breakpoint", 1],
    ["n_launch", "step", 2],
    ["n_wait_title", "step", 2],
    ["n_use_window", "step", 1],
    ["n_press_i", "step", 1],
  ]);
  const inner = events.find((e) => e.event === "debug.pause" && e.node === "n_launch")!;
  expect(inner.graph).toBe(SUB);
  expect(events.filter((e) => e.event === "debug.resume").map((e) => e.mode)).toEqual([
    "step_into",
    "step_over",
    "step_out",
    "step_over",
    "continue",
  ]);
  await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
});

// ── 2. 재개 후 대상이 사라짐 (장면이 다른 워크스페이스·앱) ────────────────────

/** 예제 장면 표에서 전이만 "타이틀은 캡처 한 번만 보이고 로비로 넘어감"으로 바꾼 가짜 플랫폼 */
function useVanishingTitle(ws: RunWorkspace): string {
  const parent = path.dirname(ws.root);
  const scenario = JSON.parse(fs.readFileSync(path.join(parent, "frames", "scenario.json"), "utf8")) as Record<string, unknown>;
  scenario.transitions = [{ after_frames: 1, from: "title", to: "lobby" }];
  fs.writeFileSync(path.join(parent, "frames", "vanishing.json"), JSON.stringify(scenario));
  const platform = JSON.parse(fs.readFileSync(ws.platform, "utf8")) as Record<string, unknown>;
  platform.scenario = "frames/vanishing.json";
  fs.writeFileSync(ws.platform, JSON.stringify(platform));
  return path.join(parent, String(platform.input_log));
}

function runnerInputs(log: string): Record<string, unknown>[] {
  if (!fs.existsSync(log)) return [];
  return fs
    .readFileSync(log, "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>)
    .filter((l) => l.by === "runner");
}

test("test_breakpoint_resume_target_gone_ui_shows_stale", async () => {
  test.setTimeout(240_000);
  const ws = prepareRunWorkspace();
  const inputLog = useVanishingTitle(ws);
  writeFile(ws.root, TARGET_GONE, JSON.stringify(TARGET_GONE_GRAPH, null, 2));
  const own = await openRunApp(ws);
  try {
    const { page } = own;
    await openGraph(page, TARGET_GONE);
    await runNode(page, "n_click").locator('[data-part="bp-spot"]').click();
    await expect(runNode(page, "n_click")).toHaveAttribute("data-breakpoint", "true");
    await clickRun(page);
    // 멈춘 동안 게임 화면은 로비로 넘어간다(다음 캡처부터). 입력 노드가 받는 Match는 입력 서비스가 다시 찾으므로 경고 없음
    await expectPausedAt(page, "n_click", "breakpoint");
    await expect(page.locator('[data-part="resume-warning"]')).toHaveCount(0);
    await button(page, "계속 F5").click();
    await waitEnded(page, "fail");
    await expect(runNode(page, "n_click")).toHaveAttribute("data-run-tone", "fail");
    const id = (await toolbar(page).getAttribute("data-run-id"))!;
    // 입력은 하나도 나가지 않았다 (가짜 입력 기록·이벤트)
    expect(runnerInputs(inputLog)).toEqual([]);
    const events = readEvents(ws, id);
    expect(events.some((e) => e.event === "input.down")).toBe(false);
    const { start, end } = stepOf(ws, id, "n_click");
    expect(end.status).toBe("fail");
    expect(String(end.message)).toMatch(/^stale_observation:/);
    const resume = events.find((e) => e.event === "debug.resume")!;
    expect(resume.epoch).toBe(1);
    // 기록 뷰어: 목록 한 번 → 그 노드 실패 스텝, 이유가 보인다
    await showRunList(page);
    await runItem(page, id).click();
    await expect(runTab(page, id)).toHaveAttribute("data-selected", start.step as string, { timeout: 15_000 });
    await expect(timelineRow(page, start.step as string)).toHaveAttribute("data-node", "n_click");
    await expect(page.locator(`[data-part="evidence"][data-step="${start.step as string}"]`)).toContainText("stale_observation");
    expect(fs.existsSync(runFolderOf(ws, id))).toBe(true);
  } finally {
    await closeRunApp(own);
  }
});
