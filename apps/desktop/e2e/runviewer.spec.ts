// 기록 뷰어 1 (M3 계획 T10 완료 기준, 2.10): 실행 목록·RUN 탭·스텝 타임라인·증거·실패로 이동·스냅샷 읽기 전용 탭.
// 실제 daemon + 가짜 플랫폼(예제 장면)으로 뷰어 검사용 그래프를 돌린다 (helpers/runs.ts). 실행을 만드는 데 시간이
// 들어 앱 하나·워크스페이스 하나를 검사들이 차례로 같이 쓴다 (serial)
import { showActivity } from "./helpers/app";
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { canvasOf, nodeEl, openGraph, settleCanvas } from "./helpers/editor";
import {
  clickRun,
  closeRunApp,
  INVENTORY,
  openRunApp,
  prepareRunWorkspace,
  releaseGate,
  toolbar,
  waitEnded,
  waitGate,
  type RunSession,
} from "./helpers/run";
import {
  cloneRun,
  rowOfNode,
  runEnd,
  runFolderOf,
  runItem,
  runTab,
  runToEnd,
  showRunList,
  startRun,
  timelineRow,
  VIEWER_CHECK,
  VIEWER_FAIL,
  VIEWER_LOOP,
  VIEWER_NOASSERT,
  VIEWER_OMIT,
  waitRunEnded,
  writeViewerGraphs,
} from "./helpers/runs";

test.describe.configure({ mode: "serial" });

let s: RunSession | null = null;
const runs: Record<"fail" | "loop" | "noassert" | "debug" | "flaky", string> = {
  fail: "",
  loop: "",
  noassert: "",
  debug: "",
  flaky: "",
};

test.beforeAll(async () => {
  test.setTimeout(600_000);
  const ws = prepareRunWorkspace({ i: "press_i" });
  writeViewerGraphs(ws);
  s = await openRunApp(ws);
  const { page } = s;
  runs.fail = await runToEnd(page, VIEWER_FAIL, "fail");
  runs.loop = await runToEnd(page, VIEWER_LOOP, "pass");
  runs.noassert = await runToEnd(page, VIEWER_NOASSERT, "fail");
  // 디버거 개입: 반복 뒤 검증 노드에 건 브레이크포인트에서 멈췄다가 계속 (UI 연결에서 시작한 실행)
  await page.evaluate((g) => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [{ graph: g, node: "n_assert" }] }), VIEWER_LOOP);
  runs.debug = await startRun(page, VIEWER_LOOP);
  await expect
    .poll(() => {
      try {
        return fs.readFileSync(path.join(runFolderOf(ws, runs.debug), "events.jsonl"), "utf8").includes('"debug.pause"');
      } catch {
        return false;
      }
    }, { timeout: 60_000 })
    .toBe(true);
  await page.evaluate((id) => window.kookabug.rpc("run.resume", { run_id: id, mode: "continue" }), runs.debug);
  expect(await waitRunEnded(page, runs.debug)).toBe("pass");
  await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
  // 불안정: 재시도 끝 성공 스텝이 있는 pass. 가짜 장면으로 만들기 어려워 성공 실행 폴더를 복사해 요약 필드만 바꾼다
  runs.flaky = "f1a2b3c4";
  cloneRun(ws, runs.loop, runs.flaky, { retried_steps: 1 });
});

test.afterAll(async () => {
  await closeRunApp(s);
  s = null;
});

function session(): RunSession {
  if (s === null) throw new Error("앱이 없다");
  return s;
}

/** 목록에서 한 번 눌러 RUN 탭을 연다 */
async function openFromList(page: Page, runId: string): Promise<void> {
  await showRunList(page);
  await expect(runItem(page, runId)).toBeVisible({ timeout: 15_000 });
  await runItem(page, runId).click();
  await expect(runTab(page, runId)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
}

test("test_open_failed_run_jumps_to_failure_step_with_evidence", async () => {
  const { page, ws } = session();
  const end = runEnd(ws, runs.fail);
  const failure = end.failure_step as string;
  expect(failure).toMatch(/^s\d+$/);
  // 목록 클릭 한 번 → 실패 사슬이 펼쳐지고 실패 스텝이 골라져 보인다
  await openFromList(page, runs.fail);
  const tab = runTab(page, runs.fail);
  await expect(tab).toHaveAttribute("data-selected", failure);
  const row = timelineRow(page, failure);
  await expect(row).toHaveAttribute("aria-selected", "true");
  await expect(row).toHaveAttribute("data-node", "n_wait_missing");
  await expect(row).toHaveAttribute("data-status", "fail");
  await expect(row).toBeInViewport();
  // 사슬의 호출 줄은 펼쳐져 있다
  await expect(rowOfNode(page, "n_call")).toHaveAttribute("aria-expanded", "true");
  // 머리: 결과
  await expect(tab.locator('[data-part="run-verdict"]')).toContainText("실패");
  // 증거: 처음·마지막(_fail) 화면이 실제로 읽힌다, 후보 표
  const evidence = page.locator(`[data-part="evidence"][data-step="${failure}"]`);
  const last = evidence.locator('[data-part="shot"][data-kind="last"]');
  await expect(last).toHaveAttribute("data-file", new RegExp(`^steps/${failure}_fail\\.png$`));
  await expect(last).toContainText("시간 초과");
  await expect(last.locator("[data-part=shot-image]")).toHaveJSProperty("complete", true);
  expect(await last.locator("[data-part=shot-image]").evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(evidence.locator('[data-part="shot"][data-kind="first"]')).toHaveCount(1);
  await expect(evidence.locator('[data-part="candidate-row"]').first()).toBeVisible();
  await expect(last.locator('[data-part="candidate-box"]').first()).toBeVisible();
  // 증거 파일이 실행 폴더에 있다
  const file = (await last.getAttribute("data-file"))!;
  expect(fs.existsSync(path.join(runFolderOf(ws, runs.fail), ...file.split("/")))).toBe(true);
});

test("test_status_bar_shows_effective_video_policy", async () => {
  // M4 T12: 뷰어 상태 바에 그 실행의 실효 영상 정책과 정한 층 (예제 워크스페이스 kookabug.json record.video off)
  const { page } = session();
  await openFromList(page, runs.fail);
  const item = page.locator('[data-part="statusbar"] [data-part="video-policy"]');
  await expect(item).toHaveText("영상: 끔 (kookabug.json)");
  await expect(item).toHaveAttribute("data-mode", "off");
});

test("test_open_again_from_list_rejumps_to_failure", async () => {
  // T10 검수 3: 열린 RUN 탭에서 다른 스텝을 고르고 실패 사슬을 접은 뒤 목록을 다시 누르면 실패 스텝으로 다시 간다
  const { page, ws } = session();
  const failure = runEnd(ws, runs.fail).failure_step as string;
  await openFromList(page, runs.fail);
  const first = page.locator('[data-part="timeline-row"]').first();
  const firstStep = (await first.getAttribute("data-step"))!;
  await first.click();
  await expect(runTab(page, runs.fail)).toHaveAttribute("data-selected", firstStep);
  await rowOfNode(page, "n_call").locator('[data-part="timeline-toggle"]').click();
  await expect(timelineRow(page, failure)).toHaveCount(0);
  await page.getByRole("tab", { name: "run.json" }).click();
  await runItem(page, runs.fail).click();
  await expect(runTab(page, runs.fail)).toHaveAttribute("data-selected", failure);
  await expect(timelineRow(page, failure)).toHaveAttribute("aria-selected", "true");
  await expect(timelineRow(page, failure)).toBeInViewport();
  await expect(page.locator(`[data-part="evidence"][data-step="${failure}"]`)).toBeVisible();
});

test("test_view_in_graph_unsaved_edit_opens_snapshot", async () => {
  // T10 검수 2: 디스크는 스냅샷과 같지만 열린 탭에 실패 노드를 지운 저장 안 된 편집이 있으면 스냅샷 탭으로 간다
  const { page } = session();
  await showActivity(page.getByRole("button", { name: /^탐색기/ }));
  await openGraph(page, VIEWER_CHECK);
  await nodeEl(page, "n_wait_missing").click();
  await page.keyboard.press("Delete");
  await expect(canvasOf(page, VIEWER_CHECK)).toHaveAttribute("data-dirty", "true");
  await expect(nodeEl(page, "n_wait_missing")).toHaveCount(0);
  await openFromList(page, runs.fail);
  await page.locator('[data-part="view-in-graph"]').click();
  const snapTab = page.locator('[role="tab"][data-kind="SNAPSHOT"]');
  await expect(snapTab).toHaveAttribute("aria-selected", "true");
  const snapPath = (await snapTab.getAttribute("data-path"))!;
  const canvas = canvasOf(page, snapPath);
  await expect(canvas).toHaveAttribute("data-readonly", "true");
  await settleCanvas(page);
  await expect(canvas.locator('.react-flow__node[data-id="n_wait_missing"]')).toHaveClass(/selected/);
  // 사용자 버퍼는 그대로다
  await page.locator(`[role="tab"][data-path="${VIEWER_CHECK}"] button`).first().click();
  await expect(canvasOf(page, VIEWER_CHECK)).toHaveAttribute("data-dirty", "true");
  await expect(nodeEl(page, "n_wait_missing")).toHaveCount(0);
  // 되돌려 다음 검사가 디스크와 같은 버퍼에서 시작하게 한다
  await canvasOf(page, VIEWER_CHECK).click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+z");
  await expect(canvasOf(page, VIEWER_CHECK)).toHaveAttribute("data-dirty", "false");
  await page.locator(`[role="tab"][data-path="${snapPath}"] [aria-label^="탭 닫기"]`).click();
  await expect(snapTab).toHaveCount(0);
});

test("test_view_in_graph_opens_snapshot_readonly_focused_node", async () => {
  const { page, ws } = session();
  await openFromList(page, runs.fail);
  const view = page.locator('[data-part="view-in-graph"]');
  // 지금 파일이 스냅샷과 같으면 워크스페이스 그래프를 연다 (편집 가능)
  await view.click();
  const workspaceTab = page.locator(`[role="tab"][data-path="${VIEWER_CHECK}"]`);
  await expect(workspaceTab).toHaveAttribute("aria-selected", "true");
  await expect(workspaceTab).toHaveAttribute("data-kind", "SUB");
  await expect(canvasOf(page, VIEWER_CHECK)).toHaveAttribute("data-readonly", "false");
  await expect(nodeEl(page, "n_wait_missing")).toHaveClass(/selected/);

  // 파일이 실행 뒤 바뀌었다: 실행 때 쓴 스냅샷을 읽기 전용 탭으로 연다
  const file = path.join(ws.root, ...VIEWER_CHECK.split("/"));
  const changed = JSON.parse(fs.readFileSync(file, "utf8")) as { nodes: Record<string, { title: string }> };
  changed.nodes.n_wait_missing.title = "바뀐 제목";
  const revision = (await canvasOf(page, VIEWER_CHECK).getAttribute("data-revision"))!;
  fs.writeFileSync(file, JSON.stringify(changed, null, 2) + "\n");
  // 열린(편집 안 한) 탭은 디스크 버전으로 다시 열린다: 비교는 그 버퍼로 한다
  await expect(canvasOf(page, VIEWER_CHECK)).not.toHaveAttribute("data-revision", revision, { timeout: 15_000 });
  await expect(nodeEl(page, "n_wait_missing")).toContainText("바뀐 제목");
  await page.locator(`[role="tab"][data-path="run:${runs.fail}"] button`).first().click();
  await expect(runTab(page, runs.fail)).toBeVisible();
  await view.click();
  const snapTab = page.locator('[role="tab"][data-kind="SNAPSHOT"]');
  await expect(snapTab).toHaveAttribute("aria-selected", "true");
  const snapPath = (await snapTab.getAttribute("data-path"))!;
  expect(snapPath).toMatch(new RegExp(`^runs/[^/]+_${runs.fail}/snapshot/${VIEWER_CHECK}$`));
  await expect(snapTab).toContainText(`· #${runs.fail.slice(0, 4)}`);
  const canvas = canvasOf(page, snapPath);
  await expect(canvas).toHaveAttribute("data-status", "ready");
  await expect(canvas).toHaveAttribute("data-readonly", "true");
  await settleCanvas(page);
  const node = canvas.locator('.react-flow__node[data-id="n_wait_missing"]');
  await expect(node).toHaveClass(/selected/);
  // 스냅샷 값(실행 때 제목)
  await expect(node).toContainText("점검 팝업 대기");
  // 편집 불가: 지우기·저장이 아무것도 바꾸지 않는다, 속성 편집기 입력이 잠겨 있다, 실행할 수 없다
  await node.click();
  await page.keyboard.press("Delete");
  await expect(canvas.locator('.react-flow__node[data-id="n_wait_missing"]')).toHaveCount(1);
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  await page.keyboard.press("Control+s");
  await expect(canvas).toHaveAttribute("data-saves", "0");
  await expect(page.locator('[data-part="inspector"] input:not([disabled])')).toHaveCount(0);
  await expect(toolbar(page).getByRole("button", { name: "실행 F5" })).toBeDisabled();
  // 스냅샷 파일은 그대로다
  const snapFile = path.join(ws.root, ...snapPath.split("/"));
  expect(JSON.parse(fs.readFileSync(snapFile, "utf8")).nodes.n_wait_missing.title).toBe("점검 팝업 대기");
});

test("test_subgraph_row_expand_collapse", async () => {
  const { page } = session();
  await openFromList(page, runs.fail);
  const call = rowOfNode(page, "n_call");
  await expect(call).toHaveAttribute("aria-expanded", "true");
  // 서브그래프 안 스텝 (입력·타이틀 대기·점검 팝업 대기)
  await expect(rowOfNode(page, "n_wait_title")).toHaveCount(1);
  await call.locator('[data-part="timeline-toggle"]').click();
  await expect(call).toHaveAttribute("aria-expanded", "false");
  await expect(rowOfNode(page, "n_wait_title")).toHaveCount(0);
  await expect(rowOfNode(page, "n_wait_missing")).toHaveCount(0);
  await call.locator('[data-part="timeline-toggle"]').click();
  await expect(call).toHaveAttribute("aria-expanded", "true");
  await expect(rowOfNode(page, "n_wait_title")).toHaveAttribute("data-status", "success");
  await expect(rowOfNode(page, "n_wait_missing")).toHaveAttribute("data-status", "fail");
  // 안쪽 줄은 들여 쓴다 (호출 줄보다 오른쪽)
  const outer = (await call.locator('[data-part="row-status"]').boundingBox())!;
  const inner = (await rowOfNode(page, "n_wait_title").locator('[data-part="row-status"]').boundingBox())!;
  expect(inner.x).toBeGreaterThan(outer.x);
});

test("test_iteration_bar_opens_that_iteration", async () => {
  const { page } = session();
  await openFromList(page, runs.loop);
  const loop = rowOfNode(page, "n_repeat").first();
  await expect(loop).toHaveAttribute("data-status", "success");
  await loop.locator('[data-part="timeline-toggle"]').click();
  const bars = page.locator('[data-part="iterations"] [data-part="iteration-bar"]');
  await expect(bars).toHaveCount(3);
  // 처음 펼치면 마지막 회차
  await expect(bars.nth(2)).toHaveAttribute("aria-pressed", "true");
  await expect(rowOfNode(page, "n_wait")).toHaveAttribute("data-iteration", "2");
  // 두 번째 막대 → 2회차(회차 1) 스텝
  await bars.nth(1).click();
  await expect(bars.nth(1)).toHaveAttribute("aria-pressed", "true");
  await expect(rowOfNode(page, "n_wait")).toHaveCount(1);
  await expect(rowOfNode(page, "n_wait")).toHaveAttribute("data-iteration", "1");
  await expect(page.locator('[data-part="iterations"]')).toContainText("2회차");
  // 그 회차 스텝을 고르면 썸네일(성공한 캡처 스텝)
  await rowOfNode(page, "n_wait").click();
  await expect(page.locator('[data-part="evidence"] [data-part="shot"][data-kind="thumb"]')).toHaveCount(1);
});

test("test_policy_omitted_cell_shown", async () => {
  const { page } = session();
  // UI에서 실행해 끝난 뒤 상태 바 "실패 보기"로 연다 (실행 로그·상태 바 연결)
  await showActivity(page.getByRole("button", { name: /^탐색기/ }));
  await openGraph(page, VIEWER_OMIT);
  await clickRun(page);
  await waitEnded(page, "fail", 120_000);
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  await page.locator('[data-part="status-show-failure"]').click();
  const tab = runTab(page, runId);
  await expect(tab).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
  await expect(rowOfNode(page, "n_wait_missing")).toHaveAttribute("aria-selected", "true");
  // 기록 끈 서브그래프의 실패 스텝: 화면 대신 시안 "정책으로 생략" 칸과 이유
  const cell = page.locator('[data-part="evidence"] [data-part="omitted-cell"]');
  await expect(cell).toBeVisible();
  await expect(cell).toContainText("정책으로 생략");
  await expect(cell).toContainText("서브그래프 기록 끔");
  await expect(page.locator('[data-part="evidence"] [data-part="shot-image"]')).toHaveCount(0);
  await expect(rowOfNode(page, "n_wait_missing").locator('[data-part="omitted-tag"]')).toBeVisible();
  // 실행 로그에서도 같은 RUN 탭으로 간다
  await page.getByRole("tab", { name: "실행 로그" }).click();
  await expect(page.locator('[data-part="runlog-show-failure"]')).toBeVisible();
});

test("test_badges_debug_flaky_no_assertion", async () => {
  const { page } = session();
  await showRunList(page);
  const badges = async (runId: string) => runItem(page, runId).locator('[data-part="run-badge"]').allTextContents();
  await expect(runItem(page, runs.flaky)).toBeVisible({ timeout: 15_000 });
  expect(await badges(runs.debug)).toEqual(["디버거 개입"]);
  expect(await badges(runs.flaky)).toEqual(["불안정"]);
  expect(await badges(runs.noassert)).toEqual(["검증 없음"]);
  expect(await badges(runs.loop)).toEqual([]);
  // 결과 점·메타·짧은 ID
  await expect(runItem(page, runs.noassert)).toHaveAttribute("data-tone", "fail");
  await expect(runItem(page, runs.loop)).toHaveAttribute("data-tone", "pass");
  await expect(runItem(page, runs.loop)).toContainText(`#${runs.loop.slice(0, 4)}`);
  await expect(runItem(page, runs.noassert)).toContainText("실패");
  // 날짜 묶음 "오늘"
  await expect(page.locator('[data-part="run-list"] section[aria-label="오늘"]')).toBeVisible();
});

test("test_live_run_timeline_updates", async () => {
  const { page, ws } = session();
  await showActivity(page.getByRole("button", { name: /^탐색기/ }));
  await openGraph(page, INVENTORY);
  await clickRun(page);
  await waitGate(ws, "press_i");
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  // 진행 중 실행은 목록 맨 위 "실행 중"
  await showRunList(page);
  const running = page.locator('[data-part="run-list"] section[aria-label="실행 중"]');
  await expect(running.locator(`[data-run-id="${runId}"]`)).toBeVisible({ timeout: 15_000 });
  await runItem(page, runId).click();
  const tab = runTab(page, runId);
  await expect(tab).toHaveAttribute("data-state", "running");
  // 지금 도는 스텝(I 키 입력 앞)이 골라져 있다
  await expect(rowOfNode(page, "n_press_i")).toHaveAttribute("data-status", "running");
  await expect(rowOfNode(page, "n_enter_world")).toHaveAttribute("data-status", "success");
  await expect(rowOfNode(page, "n_check_inventory")).toHaveCount(0);
  const before = Number(await tab.getAttribute("data-last-seq"));
  releaseGate(ws, "press_i");
  // 이벤트를 따라 늘어난다: 다음 스텝 줄, 끝난 결과
  await expect(rowOfNode(page, "n_check_inventory")).toHaveAttribute("data-status", "success", { timeout: 60_000 });
  await expect(rowOfNode(page, "n_press_i")).toHaveAttribute("data-status", "success");
  await expect(tab).toHaveAttribute("data-state", "ended", { timeout: 30_000 });
  await expect(tab.locator('[data-part="run-verdict"]')).toContainText("성공");
  expect(Number(await tab.getAttribute("data-last-seq"))).toBeGreaterThan(before);
  await expect(runItem(page, runId)).toHaveAttribute("data-tone", "pass");
});
