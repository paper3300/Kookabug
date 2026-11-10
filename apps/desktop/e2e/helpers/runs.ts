// 기록 뷰어 E2E가 쓰는 실행 만들기 도우미 (M3 계획 작업 크기 메모: 실패·반복·성공 기준 실행 도우미는 이 파일
// 하나). 예제 워크스페이스(가짜 플랫폼)에 뷰어 검사용 그래프를 더하고, 렌더러 다리(window.kookabug.rpc)로
// run.start를 불러 끝까지 기다린다 — UI 연결에서 시작한 실행이라 브레이크포인트도 적용된다
import { showActivity } from "./app";
import fs from "node:fs";
import path from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";
import type { RunWorkspace } from "./run";

/** 서브그래프 안 대기가 시간 초과로 실패 (fail 증거·후보, "그래프에서 보기") */
export const VIEWER_FAIL = "tests/viewer_fail.graph.json";
export const VIEWER_CHECK = "subgraphs/viewer_check.graph.json";
/** 반복 3회 뒤 검증 통과 (회차 막대, 성공 기준·디버거 개입) */
export const VIEWER_LOOP = "tests/viewer_loop.graph.json";
/** 스크린샷 기록을 끈 서브그래프 안에서 실패 (정책으로 생략 칸) */
export const VIEWER_OMIT = "tests/viewer_omit.graph.json";
export const VIEWER_PRIVATE = "subgraphs/viewer_private.graph.json";
/** 검증 노드 없이 끝남 (검증 없음 배지) */
export const VIEWER_NOASSERT = "tests/viewer_noassert.graph.json";
/**
 * 타이틀에서 시작 단추를 누른 뒤 점검 팝업을 기다린다 (지난 성공과 비교, T11): 게임 인수에 `--maintenance`가 있으면
 * 점검 팝업이 떠 통과, 없으면 로그인 화면이라 시간 초과 실패 → 화면·환경 차이
 */
export const VIEWER_CMP = "tests/viewer_compare.graph.json";

const START_BUTTON = { $target: "targets/title/start_button.target.json" };
/** 타이틀 화면에 없는 대상 (점검 팝업) */
const MISSING = { $target: "targets/title/maintenance_popup.target.json" };

const launch = (next: string) => ({
  in: {
    args: { $setting: "game.args" },
    cwd: { $setting: "game.cwd" },
    path: { $setting: "game.executable" },
    timeout_ms: 30000,
    window_title: { $setting: "game.title" },
  },
  next: { attached: next },
  title: "게임 실행",
  type: "core.app.launch",
  version: 1,
});

function testGraph(title: string, nodes: Record<string, unknown>): object {
  return { format: "kookabug.graph/0", kind: "test", meta: { title }, nodes, plugins: { core: "0.1.0" } };
}

function subgraph(title: string, nodes: Record<string, unknown>, record?: object): object {
  return {
    format: "kookabug.graph/0",
    kind: "subgraph",
    interface: { exits: { done: { kind: "ok" } }, inputs: {}, outputs: {} },
    meta: { title },
    nodes,
    plugins: { core: "0.1.0" },
    ...(record === undefined ? {} : { record }),
  };
}

/** 타이틀을 기다린 뒤 없는 팝업을 1.5초 기다리다 시간 초과 */
function checkNodes(missingTitle = "점검 팝업 대기"): Record<string, unknown> {
  return {
    n_entry: { next: { start: "n_wait_title" }, title: "입력", type: "core.graph.entry", version: 1 },
    n_wait_title: {
      in: { target: START_BUTTON, timeout_ms: 30000 },
      next: { found: "n_wait_missing" },
      title: "타이틀 대기",
      type: "core.image.wait",
      version: 1,
    },
    n_wait_missing: {
      in: { target: MISSING, timeout_ms: 1500 },
      next: { found: "n_exit" },
      title: missingTitle,
      type: "core.image.wait",
      version: 1,
    },
    n_exit: { config: { exit: "done" }, title: "끝", type: "core.graph.exit", version: 1 },
  };
}

function callTest(title: string, callee: string): object {
  return testGraph(title, {
    n_entry: { next: { start: "n_launch" }, title: "시작", type: "core.graph.entry", version: 1 },
    n_launch: launch("n_call"),
    n_call: { config: { graph: callee }, next: { done: "n_pass" }, title: "화면 확인", type: "core.graph.call", version: 1 },
    n_pass: { title: "통과", type: "core.test.pass", version: 1 },
  });
}

/** 뷰어 검사용 그래프를 워크스페이스에 쓴다 */
export function writeViewerGraphs(ws: RunWorkspace): void {
  const files: Record<string, object> = {
    [VIEWER_CHECK]: subgraph("화면 확인", checkNodes()),
    [VIEWER_PRIVATE]: subgraph("비공개 확인", checkNodes(), { screenshots: "off" }),
    [VIEWER_FAIL]: callTest("뷰어 실패", VIEWER_CHECK),
    [VIEWER_OMIT]: callTest("뷰어 생략", VIEWER_PRIVATE),
    [VIEWER_LOOP]: testGraph("뷰어 반복", {
      n_entry: { next: { start: "n_launch" }, title: "시작", type: "core.graph.entry", version: 1 },
      n_launch: launch("n_repeat"),
      n_repeat: { in: { times: 3 }, next: { body: "n_wait", done: "n_assert" }, title: "세 번", type: "core.flow.repeat", version: 1 },
      n_wait: { in: { target: START_BUTTON, timeout_ms: 30000 }, title: "타이틀 대기", type: "core.image.wait", version: 1 },
      n_assert: { in: { target: START_BUTTON, timeout_ms: 5000 }, title: "타이틀 확인", type: "core.assert.visible", version: 1 },
    }),
    [VIEWER_CMP]: testGraph("뷰어 비교", {
      n_entry: { next: { start: "n_launch" }, title: "시작", type: "core.graph.entry", version: 1 },
      n_launch: launch("n_wait_title"),
      n_wait_title: { in: { target: START_BUTTON, timeout_ms: 30000 }, next: { found: "n_settle" }, title: "타이틀 대기", type: "core.image.wait", version: 1 },
      // 실제 녹화(MSMF)는 인코더 준비에 시간이 든다: 그 뒤에 시작하는 스텝이 조각 안에 들게 기다린다 (T11 검수: 실제 조각 안 탐색)
      n_settle: { in: { ms: 3000 }, next: { done: "n_repeat" }, title: "녹화 준비 대기", type: "core.flow.delay", version: 1 },
      // 회차 막대 (시안 대비 스크린샷)
      n_repeat: { in: { times: 3 }, next: { body: "n_check", done: "n_click" }, title: "세 번 확인", type: "core.flow.repeat", version: 1 },
      n_check: { in: { target: START_BUTTON, timeout_ms: 30000 }, title: "타이틀 확인", type: "core.image.wait", version: 1 },
      n_click: { in: { target: START_BUTTON }, next: { done: "n_wait_popup" }, title: "시작 클릭", type: "core.image.click", version: 1 },
      n_wait_popup: { in: { target: MISSING, timeout_ms: 2000 }, next: { found: "n_pass" }, title: "점검 팝업 대기", type: "core.image.wait", version: 1 },
      n_pass: { title: "통과", type: "core.test.pass", version: 1 },
    }),
    [VIEWER_NOASSERT]: testGraph("뷰어 검증 없음", {
      n_entry: { next: { start: "n_launch" }, title: "시작", type: "core.graph.entry", version: 1 },
      n_launch: launch("n_wait"),
      n_wait: { in: { target: START_BUTTON, timeout_ms: 30000 }, title: "타이틀 대기", type: "core.image.wait", version: 1 },
    }),
  };
  for (const [rel, value] of Object.entries(files)) {
    const file = path.join(ws.root, ...rel.split("/"));
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n");
  }
}

/** 렌더러 다리로 run.start (UI 연결). profile을 주면 그 프로필로 */
export async function startRun(page: Page, graph: string, profile?: string): Promise<string> {
  const r = (await page.evaluate(
    ([p, prof]) => window.kookabug.rpc("run.start", prof === undefined ? { path: p } : { path: p, profile: prof }),
    [graph, profile] as const,
  )) as { run_id: string };
  return r.run_id;
}

/** `.kookabug/local.json`의 게임 인수 (null이면 빼서 프로필·워크스페이스 값을 쓴다) */
export function setLocalGameArgs(ws: RunWorkspace, args: string[] | null): void {
  const file = path.join(ws.root, ".kookabug", "local.json");
  const local = JSON.parse(fs.readFileSync(file, "utf8")) as { settings: Record<string, unknown> };
  if (args === null) delete local.settings["game.args"];
  else local.settings["game.args"] = args;
  fs.writeFileSync(file, JSON.stringify(local));
}

/** 워크스페이스 영상 정책 (예제 워크스페이스는 off) */
export function setWorkspaceVideo(ws: RunWorkspace, mode: "on" | "failed_only" | "off"): void {
  const file = path.join(ws.root, "kookabug.json");
  const value = JSON.parse(fs.readFileSync(file, "utf8")) as { record?: Record<string, unknown> };
  value.record = { ...(value.record ?? {}), video: mode };
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + "\n");
}

export async function runState(page: Page, runId: string): Promise<{ state: string; verdict: string | null }> {
  const r = (await page.evaluate((id) => window.kookabug.rpc("run.status", { run_id: id }), runId)) as {
    state: string;
    outcome: { verdict: string } | null;
  };
  return { state: r.state, verdict: r.outcome?.verdict ?? null };
}

/** 실행이 끝날 때까지 기다리고 판정을 돌려준다 */
export async function waitRunEnded(page: Page, runId: string, timeout = 120_000): Promise<string> {
  await expect.poll(async () => (await runState(page, runId)).state, { timeout, message: `실행 ${runId}` }).toBe("ended");
  return (await runState(page, runId)).verdict ?? "";
}

/** 그래프를 끝까지 실행한다 (판정 확인) */
export async function runToEnd(page: Page, graph: string, verdict: string): Promise<string> {
  const runId = await startRun(page, graph);
  expect(await waitRunEnded(page, runId)).toBe(verdict);
  return runId;
}

export function runFolderOf(ws: RunWorkspace, runId: string): string {
  const runs = path.join(ws.root, "runs");
  const dir = fs.readdirSync(runs).find((d) => d.endsWith(`_${runId}`));
  if (dir === undefined) throw new Error(`실행 폴더가 없다: ${runId}`);
  return path.join(runs, dir);
}

/**
 * 끝난 실행 폴더를 새 실행 ID로 복사하고 run.json을 고친다 (재시도 끝 성공 같은, 가짜 플랫폼으로 만들기 어려운
 * 요약 필드 표시 검사용). 실행 ID가 든 글자는 모두 바꾼다
 */
export function cloneRun(ws: RunWorkspace, runId: string, newId: string, patch: Record<string, unknown>): string {
  const from = runFolderOf(ws, runId);
  const to = path.join(path.dirname(from), path.basename(from).replace(runId, newId));
  fs.cpSync(from, to, { recursive: true });
  for (const name of ["run.json", "events.jsonl"]) {
    const file = path.join(to, name);
    fs.writeFileSync(file, fs.readFileSync(file, "utf8").replaceAll(runId, newId));
  }
  const runJson = path.join(to, "run.json");
  fs.writeFileSync(runJson, JSON.stringify({ ...JSON.parse(fs.readFileSync(runJson, "utf8")), ...patch }, null, 2));
  return to;
}

// ── 화면 ──────────────────────────────────────────────────────────

/** 사이드바 실행 기록을 연다 */
export async function showRunList(page: Page): Promise<Locator> {
  await showActivity(page.getByRole("button", { name: /^실행 기록/ }));
  const list = page.locator('[data-part="run-list"]');
  await expect(list).toBeVisible();
  return list;
}

export function runItem(page: Page, runId: string): Locator {
  return page.locator(`[data-part="run-item"][data-run-id="${runId}"]`);
}

export function runTab(page: Page, runId: string): Locator {
  return page.locator(`[data-part="run-tab"][data-run-id="${runId}"]`);
}

export function timelineRow(page: Page, step: string): Locator {
  return page.locator(`[data-part="timeline-row"][data-step="${step}"]`);
}

export function rowOfNode(page: Page, node: string): Locator {
  return page.locator(`[data-part="timeline-row"][data-node="${node}"]`);
}

/** 실행 폴더의 run.end */
export function runEnd(ws: RunWorkspace, runId: string): Record<string, unknown> {
  const lines = fs
    .readFileSync(path.join(runFolderOf(ws, runId), "events.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>);
  const end = lines.find((e) => e.event === "run.end");
  if (end === undefined) throw new Error(`run.end가 없다: ${runId}`);
  return end;
}
