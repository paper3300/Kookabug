// 실행·실행 중 강조 (M2 계획 2.8, T11 완료 기준). 실제 daemon + 가짜 플랫폼(예제 장면)으로 예제 그래프를 돌린다.
// 실행 중간 상태는 가짜 입력 훅으로 그 입력 앞에서 세워 만든다 (helpers/run.ts)
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { closeApp } from "./helpers/app";
import { dragNode, openGraph, readJson, tabOf, writeFile } from "./helpers/editor";
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
  runFolders,
  runNode,
  SWAPPED,
  toolbar,
  waitEnded,
  waitGate,
  type RunSession,
} from "./helpers/run";

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

const status = (node: ReturnType<typeof runNode>) => node.locator('[data-part="node-status"]');
const runLog = (page: RunSession["page"]) => page.locator('[data-part="run-log"]');

/** 화면의 실행 로그가 실행 폴더의 기록과 같은 수의 스텝·마지막 seq를 적용했다 */
async function expectLogMatchesRecord(session: RunSession): Promise<void> {
  const runId = (await toolbar(session.page).getAttribute("data-run-id"))!;
  const events = readEvents(session.ws, runId);
  const ends = events.filter((e) => e.event === "step.end").length;
  const last = events.at(-1)!.seq as number;
  await expect(runLog(session.page)).toHaveAttribute("data-applied", String(last));
  await expect(runLog(session.page)).toHaveAttribute("data-steps-ended", String(ends));
  // 끝난 스텝 줄(OK·FAIL·ERROR·STOP)이 기록의 step.end 수와 같다: 빠진 줄·겹친 줄이 없다
  const lines = await runLog(session.page).locator('[data-level="OK"], [data-level="FAIL"], [data-level="ERROR"], [data-level="STOP"]').count();
  expect(lines).toBe(ends + 1); // + run.end 판정 줄
}

test("test_run_highlights_running_node_then_pass", async () => {
  const ws = prepareRunWorkspace({ i: "press_i" });
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  await clickRun(page);
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running");
  await waitGate(ws, "press_i");
  // 열린 스텝(I 키)만 강조, 지나간 노드는 결과·시간, 아직 닿지 않은 노드는 흐리게
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-run", "active");
  await expect(status(runNode(page, "n_press_i"))).toHaveText(/^● \d+\.\ds$/);
  await expect(page.locator('[data-part="node"][data-run="active"]')).toHaveCount(1);
  for (const id of ["n_entry", "n_enter_world"]) {
    await expect(runNode(page, id)).toHaveAttribute("data-run-tone", "ok");
    await expect(status(runNode(page, id))).toHaveText(/^✓ \d/);
  }
  await expect(runNode(page, "n_check_inventory")).toHaveAttribute("data-run", "idle");
  // 실행 로그 패널이 열리고 맨 위가 지금 노드의 RUN 줄
  await expect(page.getByRole("tab", { name: "실행 로그" })).toHaveAttribute("aria-selected", "true");
  const top = runLog(page).locator("[data-level]").first();
  await expect(top).toHaveAttribute("data-level", "RUN");
  await expect(top).toContainText("I 키");
  // 실행 중에는 다시 실행할 수 없고 정지할 수 있다 (정지는 M3부터 디버그 툴바)
  await expect(toolbar(page).getByRole("button", { name: "실행 F5" })).toBeDisabled();
  await expect(debugToolbar(page).getByRole("button", { name: "정지", exact: true })).toBeEnabled();
  // 실행 중 그래프를 고치면 경로 표시줄 옆에 "실행은 저장된 버전 기준"
  await expect(page.locator('[data-part="run-snapshot"]')).toHaveCount(0);
  await dragNode(page, "n_skip_maintenance", 0, 60);
  await expect(page.locator('[data-part="run-snapshot"]')).toHaveText("실행은 저장된 버전 기준");

  releaseGate(ws, "press_i");
  await waitEnded(page, "pass");
  await expect(page.locator('[data-part="node"][data-run="active"]')).toHaveCount(0);
  await expect(runNode(page, "n_check_inventory")).toHaveAttribute("data-run-tone", "ok");
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-run-tone", "ok");
  // 지나가지 않은 노드는 끝난 뒤 흐리지 않고 상태도 없다
  await expect(runNode(page, "n_skip_maintenance")).not.toHaveAttribute("data-run");
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "false");
  await expect(page.locator('[data-part="run-result"]')).toHaveAttribute("data-verdict", "pass");
  await expectLogMatchesRecord(s);
});

test("test_dirty_graph_saved_before_run", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  const before = readJson<{ layout: { nodes: Record<string, { x: number; y: number }> } }>(ws.root, INVENTORY);
  await dragNode(page, "n_press_i", 60, 80);
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "true");
  await clickRun(page);
  await waitEnded(page, "pass");
  // 먼저 저장했다: 탭이 깨끗하고 디스크에 옮긴 자리가 있다
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "false");
  const disk = readJson<{ layout: { nodes: Record<string, { x: number; y: number }> } }>(ws.root, INVENTORY);
  expect(disk.layout.nodes.n_press_i).not.toEqual(before.layout.nodes.n_press_i);
  // 실행은 저장한 파일의 스냅샷으로 돌았다
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  const snapshot = JSON.parse(
    fs.readFileSync(path.join(runFolder(ws, runId), "snapshot", ...INVENTORY.split("/")), "utf8"),
  ) as typeof disk;
  expect(snapshot.layout.nodes.n_press_i).toEqual(disk.layout.nodes.n_press_i);
  // 실행 뒤 그래프를 고치면 "실행은 저장된 버전 기준"은 실행 중에만 보인다 (끝난 뒤에는 없다)
  await expect(page.locator('[data-part="run-snapshot"]')).toHaveCount(0);
});

test("test_validation_error_blocks_run_shows_problems", async () => {
  const ws = prepareRunWorkspace();
  const broken = readJson<{ nodes: Record<string, { next?: Record<string, string> }> }>(ws.root, INVENTORY);
  broken.nodes.n_press_i.next = { done: "n_nowhere" };
  const rel = "tests/broken_next.graph.json";
  writeFile(ws.root, rel, JSON.stringify(broken, null, 2));
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, rel);
  await clickRun(page);
  const blocked = toolbar(page).locator('[data-part="run-blocked"]');
  await expect(blocked).toHaveAttribute("data-kind", "validation");
  await expect(blocked).toHaveText(/^검증 오류 [1-9]\d*개$/);
  await expect(page.getByRole("tab", { name: /문제/ })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("list", { name: "문제 목록" })).toContainText("n_nowhere");
  await expect(toolbar(page)).toHaveAttribute("data-phase", "idle");
  // 실행 폴더를 만들지 않았다
  expect(runFolders(ws)).toEqual([]);
});

test("test_profile_only_validation_error_shown_in_problems", async () => {
  // 기본 설정은 정상이고 고른 프로필만 게임 창 제목을 null로 둔다: 문서 검증(기본 설정)에는 없는 오류다
  // (T11 검수 1차). 실행 거부 진단을 문제 패널의 "실행 전 검증"으로 보인다
  const ws = prepareRunWorkspace();
  const config = readJson<{ profiles: Record<string, unknown> }>(ws.root, "kookabug.json");
  config.profiles.no_title = { settings: { "game.title": null } };
  writeFile(ws.root, "kookabug.json", JSON.stringify(config, null, 2));
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  await page.getByRole("tab", { name: /문제/ }).click();
  await expect(page.getByRole("list", { name: "문제 목록" })).toHaveCount(0);
  await toolbar(page).getByRole("combobox", { name: "실행 프로필" }).selectOption("no_title");
  await clickRun(page);
  const blocked = toolbar(page).locator('[data-part="run-blocked"]');
  await expect(blocked).toHaveAttribute("data-kind", "validation");
  await expect(blocked).toHaveText(/^검증 오류 [1-9]\d*개$/);
  const runProblems = page.getByRole("list", { name: "실행 전 검증 문제" });
  await expect(runProblems.locator('[data-code="setting_null"]').first()).toBeVisible();
  await expect(page.locator('[data-part="run-problems-header"]')).toContainText("no_title");
  await expect(page.locator('[data-part="panel-tabs"] [data-part="problem-count"]')).not.toHaveText("0");
  expect(runFolders(ws)).toEqual([]);
  // 프로필을 기본으로 돌리면 그 진단은 사라진다 (그 프로필의 결과다)
  await toolbar(page).getByRole("combobox", { name: "실행 프로필" }).selectOption("");
  await expect(runProblems).toHaveCount(0);
  await expect(blocked).toHaveCount(0);
});

test("test_cancel_ends_cancelled", async () => {
  const ws = prepareRunWorkspace({ i: "press_i" });
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, INVENTORY);
  await clickRun(page);
  await waitGate(ws, "press_i");
  await debugToolbar(page).getByRole("button", { name: "정지", exact: true }).click();
  // 취소가 입력 앞에서 선 스텝에 닿도록 지점을 푼다 (훅은 취소로 끊기지 않는 대기다)
  releaseGate(ws, "press_i");
  await waitEnded(page);
  const verdict = await toolbar(page).getAttribute("data-verdict");
  expect(verdict).not.toBe("pass");
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  const end = readEvents(ws, runId).find((e) => e.event === "run.end")!;
  expect(end.verdict).toBe(verdict);
  expect(end.cancel_reason ?? end.code).toMatch(/cancel/);
  await expect(runLog(page)).toContainText("취소 요청");
  await expect(page.locator('[data-part="node"][data-run="active"]')).toHaveCount(0);
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "false");
  await expect(toolbar(page).getByRole("button", { name: "실행 F5" })).toBeEnabled();
});

test("test_daemon_reconnect_mid_run_no_missing_steps", async () => {
  // 월드 접속 서브그래프의 첫 클릭 앞에서 세운다: 루트 탭은 호출 노드(월드 접속)를 강조한다
  const ws = prepareRunWorkspace({ "mouse:left": "first_click" });
  s = await openRunApp(ws);
  const { page, app } = s;
  await openGraph(page, INVENTORY);
  await clickRun(page);
  await waitGate(ws, "first_click");
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-run", "active");
  // 서브그래프 탭을 열면 안쪽 노드가 강조된다 (스냅샷 호출 관계)
  await openGraph(page, "subgraphs/enter_world.graph.json");
  await expect(runNode(page, "n_click_start")).toHaveAttribute("data-run", "active");
  await page.locator(`[role="tab"][data-path="${INVENTORY}"] button`).first().click();
  const before = Number(await runLog(page).getAttribute("data-applied"));
  // daemon·실행은 두고 연결만 끊는다. 끊긴 사이에 실행이 이어 가도록 바로 지점을 푼다
  const dropped = await app.evaluate(() => (globalThis as { __kookabugE2E?: { dropDaemonConnection(): boolean } }).__kookabugE2E!.dropDaemonConnection());
  expect(dropped).toBe(true);
  releaseGate(ws, "first_click");
  await expect(page.locator('[data-part="statusbar"] [data-status]')).toHaveAttribute("data-status", "connected", { timeout: 30_000 });
  await waitEnded(page, "pass");
  expect(Number(await runLog(page).getAttribute("data-applied"))).toBeGreaterThan(before);
  await expectLogMatchesRecord(s);
  await page.getByRole("tab", { name: "출력" }).click();
  await expect(page.getByRole("tabpanel", { name: "출력" })).toContainText("daemon 연결이 끊겼다");
});

test("test_reopen_app_resubscribes_active_run", async () => {
  const ws = prepareRunWorkspace({ i: "press_i" });
  s = await openRunApp(ws);
  await openGraph(s.page, INVENTORY);
  await clickRun(s.page);
  await waitGate(ws, "press_i");
  const runId = (await toolbar(s.page).getAttribute("data-run-id"))!;
  // UI를 꺼도 daemon과 실행은 남는다
  await closeApp(s.app);
  fs.rmSync(s.userData, { recursive: true, force: true });
  s = await openRunApp(ws);
  const { page } = s;
  await expect(toolbar(page)).toHaveAttribute("data-run-id", runId);
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running");
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "true");
  // 임대권을 쥔 실행에 다시 붙었다: daemon이 hello 직후 한 번 보낸 지금 소유자가 상태 바에 나온다
  // (T11 검수 1차: 받는 쪽을 달기 전에 온 알림을 잃었다)
  await expect(page.locator('[data-part="statusbar"] [data-part="lease"]')).toHaveText(`입력: 실행 #${runId}`);
  await openGraph(page, INVENTORY);
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-run", "active");
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-run-tone", "ok");
  releaseGate(ws, "press_i");
  await waitEnded(page, "pass");
  await page.getByRole("tab", { name: "실행 로그" }).click();
  await expectLogMatchesRecord(s);
});

test("test_reopen_subgraph_tab_only_highlights_inner_node", async () => {
  // 앱을 다시 열고 루트(조상) 탭은 열지 않은 채 서브그래프 탭만 연다: 강조는 실행 스냅샷의 호출 관계로 붙는다
  // (T11 검수 1차: 편집 버퍼·조상 탭에 기대지 않는다)
  const ws = prepareRunWorkspace({ "mouse:left": "first_click" });
  s = await openRunApp(ws);
  await openGraph(s.page, INVENTORY);
  await clickRun(s.page);
  await waitGate(ws, "first_click");
  await closeApp(s.app);
  fs.rmSync(s.userData, { recursive: true, force: true });
  s = await openRunApp(ws);
  const { page } = s;
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running");
  await openGraph(page, "subgraphs/enter_world.graph.json");
  await expect(runNode(page, "n_click_start")).toHaveAttribute("data-run", "active");
  await expect(runNode(page, "n_launch")).toHaveAttribute("data-run-tone", "ok");
  await expect(page.locator(`[role="tab"][data-path="${INVENTORY}"]`)).toHaveCount(0);
  releaseGate(ws, "first_click");
  await waitEnded(page, "pass");
  await expect(runNode(page, "n_click_start")).toHaveAttribute("data-run-tone", "ok");
});

test("test_status_bar_running_color_and_lease", async () => {
  const ws = prepareRunWorkspace({ i: "press_i" });
  s = await openRunApp(ws);
  const { page } = s;
  const bar = page.locator('[data-part="statusbar"]');
  const token = (name: string) =>
    page.evaluate((n) => {
      const probe = document.createElement("div");
      probe.style.background = `var(${n})`;
      document.body.append(probe);
      const v = getComputedStyle(probe).backgroundColor;
      probe.remove();
      return v;
    }, name);
  const bg = () => bar.evaluate((el) => getComputedStyle(el).backgroundColor);
  // 붙은 직후 임대권 소유자 없음 (daemon이 hello 직후 지금 상태를 한 번 보낸다)
  await expect(bar.locator('[data-part="lease"]')).toHaveCount(0);
  expect(await bg()).toBe(await token("--kb-statusbar-idle-bg"));
  await openGraph(page, INVENTORY);
  await clickRun(page);
  await waitGate(ws, "press_i");
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  await expect(bar).toHaveAttribute("data-running", "true");
  expect(await bg()).toBe(await token("--kb-statusbar-running-bg"));
  await expect(bar.locator('[data-part="run-state"]')).toHaveText("실행 중");
  expect(await bar.locator('[data-part="run-state"]').evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(
    await token("--kb-statusbar-ok-bg"),
  );
  await expect(bar.locator('[data-part="run-progress"]')).toHaveText(/^경과 \d+:\d\d:\d\d$/);
  await expect(bar.locator('[data-part="lease"]')).toHaveText(`입력: 실행 #${runId}`);
  releaseGate(ws, "press_i");
  await waitEnded(page, "pass");
  await expect(bar).toHaveAttribute("data-running", "false");
  expect(await bg()).toBe(await token("--kb-statusbar-idle-bg"));
  await expect(bar.locator('[data-part="lease"]')).toHaveCount(0);
});

test("test_broken_variant_fail_shows_fail_node_and_artifact_path", async () => {
  const ws = prepareRunWorkspace();
  s = await openRunApp(ws);
  const { page } = s;
  await openGraph(page, SWAPPED);
  await clickRun(page);
  await waitEnded(page, "fail", 120_000);
  // 실패 위치: 월드 접속 > 타이틀 대기 (서브그래프 안 대기가 시간 초과). 루트 탭은 호출 노드가 fail이다
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-run-tone", "fail");
  await expect(status(runNode(page, "n_enter_world"))).toHaveText(/^✕ /);
  await runNode(page, "n_enter_world").click();
  await page.getByRole("tab", { name: "노드 결과" }).click();
  await expect(page.locator('[data-part="node-result"][data-node="n_enter_world"] [data-part="node-result-status"]')).toHaveAttribute(
    "data-status",
    "fail",
  );
  // 서브그래프 탭: 실패한 안쪽 노드와 그 실패 증거(스크린샷) 경로
  await openGraph(page, "subgraphs/broken/enter_world_swapped_target.graph.json");
  await expect(runNode(page, "n_wait_title")).toHaveAttribute("data-run-tone", "fail");
  await expect(runNode(page, "n_launch")).toHaveAttribute("data-run-tone", "ok");
  await runNode(page, "n_wait_title").click();
  const result = page.locator('[data-part="node-result"][data-node="n_wait_title"]');
  await expect(result.locator('[data-part="node-result-status"]')).toHaveAttribute("data-status", "fail");
  const artifact = result.locator('[data-part="node-result-artifacts"] [data-artifact]').first();
  // fail 출구로 나간 스텝의 증거 (steps/<스텝>_<출구>.png)
  await expect(artifact).toHaveAttribute("data-artifact", /^steps\/s\d+_timeout\.png$/);
  const runId = (await toolbar(page).getAttribute("data-run-id"))!;
  const rel = (await artifact.getAttribute("data-artifact"))!;
  const full = path.join(runFolder(ws, runId), ...rel.split("/"));
  expect(fs.existsSync(full)).toBe(true);
  // 같은 파일인지는 실제 경로로 본다: 임시 폴더가 8.3 짧은 이름(PAPER3~1)이면 화면(긴 이름)과 글자가 다르다.
  // path.normalize는 별칭을 펴지 않는다
  const shown = (await artifact.textContent())!;
  expect(fs.existsSync(shown)).toBe(true);
  expect(fs.realpathSync.native(shown)).toBe(fs.realpathSync.native(full));
  // 실행 로그에 판정 줄
  await page.getByRole("tab", { name: "실행 로그" }).click();
  await expect(runLog(page).locator('[data-level="FAIL"]').first()).toContainText("판정 fail");
});
