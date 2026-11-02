// 디버거 멈춤 상태 (M3 계획 2.1·2.9, T9 완료 기준): 이벤트로만 알고, 다시 붙으면 재전송으로 같은 상태,
// 서브그래프 안에서 멈추면 루트 탭의 호출 노드에도 표시
import { beforeEach, describe, expect, test } from "vitest";
import type { RpcCall } from "../rpc/client";
import type { CallMap, RunEvent } from "../run/highlight";
import { RunModel } from "../run/runStore";
import { debugAvailability } from "./availability";
import { applyPause, NO_PAUSE, pauseNeedsCalls, pausedNodeIn, type PausePoint } from "./pauseState";

const RUN = "abcd1234";
const ROOT = "tests/a.graph.json";
const SUB = "subgraphs/login.graph.json";
const INNER = "subgraphs/inner.graph.json";
const T0 = Date.parse("2026-11-02T00:00:00.000Z");

let calls: { method: string; params: Record<string, unknown> }[];
let replies: Map<string, (params: Record<string, unknown>) => unknown>;
const call: RpcCall = async (method, params) => {
  calls.push({ method, params: params as Record<string, unknown> });
  const reply = replies.get(method);
  return (reply === undefined ? {} : reply(params as Record<string, unknown>)) as never;
};
const tick = () => new Promise((r) => setTimeout(r, 0));

function ev(seq: number, body: Record<string, unknown>): RunEvent {
  return { event: "", seq, t: new Date(T0 + seq).toISOString(), run: RUN, ...body };
}

/** 루트 → 호출(n_call) → 서브그래프 첫 노드(s_click) 경계에서 브레이크포인트로 멈춘 실행 */
const PAUSED_IN_SUB: RunEvent[] = [
  ev(1, { event: "run.start", graph: ROOT }),
  ev(2, { event: "step.start", step: "s1", node: "n_entry", path: ["n_entry"] }),
  ev(3, { event: "step.end", step: "s1", status: "success", exit: "start", duration_ms: 1 }),
  ev(4, { event: "step.start", step: "s2", node: "n_call", path: ["n_call"] }),
  ev(5, { event: "debug.pause", step: "s3", node: "s_click", graph: SUB, path: ["n_call", "s_click"], reason: "breakpoint", where: "boundary" }),
];

function newModel(): RunModel {
  return new RunModel(call, { note: () => {}, showPanel: () => {}, save: async () => "saved", revision: () => null });
}

function feed(model: RunModel, events: readonly RunEvent[]): void {
  for (const e of events) model.event({ run_id: RUN, seq: e.seq, event: e as never });
}

beforeEach(() => {
  calls = [];
  replies = new Map<string, (params: Record<string, unknown>) => unknown>([
    ["run.start", () => ({ run_id: RUN, run_dir: "C:/ws/runs/x", graph: ROOT })],
    ["run.status", () => ({ calls: { [ROOT]: { n_call: SUB } } })],
    ["run.list", () => ({ runs: [{ run_id: RUN, graph: ROOT, run_dir: "C:/ws/runs/x", state: "running" }] })],
  ]);
});

describe("멈춤 상태", () => {
  test("test_pause_state_from_events_only", async () => {
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    feed(model, PAUSED_IN_SUB.slice(0, 4));
    const cur = () => model.store.getState().current!;
    expect(cur().pause.paused).toBeNull();

    // 일시정지 요청의 응답(pausing)은 "멈추는 중"일 뿐 멈춤이 아니다: 멈춤은 debug.pause가 와야 안다
    replies.set("run.pause", () => ({ state: "pausing" }));
    await model.pause();
    expect(cur().pausing).toBe(true);
    expect(cur().pause.paused).toBeNull();
    expect(debugAvailability(model.store.getState())).toMatchObject({ pausing: true, canPause: false, canStep: false });

    feed(model, PAUSED_IN_SUB.slice(4));
    expect(cur().pausing).toBe(false);
    expect(cur().pause.paused).toMatchObject({ node: "s_click", graph: SUB, reason: "breakpoint", where: "boundary" });
    expect(debugAvailability(model.store.getState())).toMatchObject({ paused: true, canStep: true, canPause: false });

    // 재개 응답(running)만으로는 멈춤을 풀지 않는다: debug.resume이 와야 푼다
    replies.set("run.resume", () => ({ state: "running" }));
    await model.resume("step_over");
    expect(calls.at(-1)).toEqual({ method: "run.resume", params: { run_id: RUN, mode: "step_over" } });
    expect(cur().pause.paused).not.toBeNull();
    feed(model, [ev(6, { event: "debug.resume", step: "s3", mode: "step_over", epoch: 1, paused_ms: 1500 })]);
    expect(cur().pause).toEqual({ paused: null, count: 1, pausedMs: 1500, epoch: 1, debugSeq: 6 });

    // 멈추지 않은 실행에는 Step을 보내지 않는다
    const before = calls.length;
    await model.resume("step_into");
    expect(calls.length).toBe(before);

    // 멈춘 채 실행이 끝나도(취소) 멈춤은 풀린다
    feed(model, [
      ev(7, { event: "debug.pause", step: "s4", node: "n_key", graph: ROOT, path: ["n_key"], reason: "request", where: "poll" }),
      ev(8, { event: "run.end", verdict: "error", code: "cancelled", reason: "user" }),
    ]);
    expect(cur().pause.paused).toBeNull();
    expect(cur().pause.count).toBe(2);
  });

  test("test_reconnect_replay_restores_paused_node", async () => {
    // 앱을 다시 열면(또는 daemon이 바뀌면) 진행 중 실행을 처음부터 다시 구독한다: 같은 이벤트로 같은 멈춤
    const first = newModel();
    expect(await first.start(ROOT)).toBe(true);
    feed(first, PAUSED_IN_SUB);
    await tick();

    const reopened = newModel();
    await reopened.syncActive();
    expect(calls.filter((c) => c.method === "run.subscribe").at(-1)?.params.after_seq).toBe(0);
    expect(reopened.store.getState().current!.pause.paused).toBeNull();
    feed(reopened, PAUSED_IN_SUB);
    await tick();
    const a = first.store.getState().current!;
    const b = reopened.store.getState().current!;
    expect(b.pause).toEqual(a.pause);
    // 재전송으로 같은 이벤트가 겹쳐 와도(중복 seq) 멈춘 횟수가 늘지 않는다
    feed(reopened, PAUSED_IN_SUB);
    expect(reopened.store.getState().current!.pause.count).toBe(1);
    // 같은 노드가 표시된다 (루트 탭 → 호출 노드, 서브그래프 탭 → 안쪽 노드)
    const has = () => true;
    expect(pausedNodeIn(b.trace.graph, b.pause.paused!, b.calls, ROOT, has)).toBe("n_call");
    expect(pausedNodeIn(b.trace.graph, b.pause.paused!, b.calls, SUB, has)).toBe("s_click");
  });

  test("test_paused_inner_node_marks_root_call_node", () => {
    const point: PausePoint = {
      seq: 5,
      step: "s3",
      node: "s_click",
      graph: SUB,
      path: ["n_call", "s_click"],
      reason: "step",
      where: "boundary",
    };
    const ids = new Set(["n_call", "s_click", "n_entry"]);
    const has = (id: string) => ids.has(id);
    // 호출 관계를 몰라도 멈춘 노드의 그래프는 이벤트로 안다: 루트 탭은 호출 노드, 서브그래프 탭은 안쪽 노드
    expect(pausedNodeIn(ROOT, point, {}, ROOT, has)).toBe("n_call");
    expect(pausedNodeIn(ROOT, point, {}, SUB, has)).toBe("s_click");
    // 실행과 무관한 탭(같은 노드 ID를 가진 다른 파일)은 표시하지 않는다
    expect(pausedNodeIn(ROOT, point, {}, "subgraphs/other.graph.json", has)).toBeNull();
    // 탭 버퍼에서 그 노드를 지웠으면 표시하지 않는다
    expect(pausedNodeIn(ROOT, point, {}, ROOT, (id) => id !== "n_call")).toBeNull();

    // 중첩: 중간 깊이(SUB 안 s_call → INNER)는 호출 관계가 있어야 따라간다
    const nested: PausePoint = { ...point, node: "i_wait", graph: INNER, path: ["n_call", "s_call", "i_wait"], where: "poll" };
    expect(pauseNeedsCalls(ROOT, nested, {})).toBe(true);
    expect(pausedNodeIn(ROOT, nested, {}, SUB, () => true)).toBeNull();
    const calls: CallMap = { [ROOT]: { n_call: SUB }, [SUB]: { s_call: INNER } };
    expect(pauseNeedsCalls(ROOT, nested, calls)).toBe(false);
    expect(pausedNodeIn(ROOT, nested, calls, ROOT, () => true)).toBe("n_call");
    expect(pausedNodeIn(ROOT, nested, calls, SUB, () => true)).toBe("s_call");
    expect(pausedNodeIn(ROOT, nested, calls, INNER, () => true)).toBe("i_wait");
  });

  test("서브그래프 안에서 멈추면 중간 깊이를 따라갈 호출 관계를 받는다", async () => {
    replies.set("run.status", () => ({ calls: { [ROOT]: { n_call: SUB }, [SUB]: { s_call: INNER } } }));
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    feed(model, [
      ev(1, { event: "run.start", graph: ROOT }),
      ev(2, { event: "debug.pause", step: "s9", node: "i_wait", graph: INNER, path: ["n_call", "s_call", "i_wait"], reason: "request", where: "poll" }),
    ]);
    await tick();
    expect(calls.some((c) => c.method === "run.status")).toBe(true);
    const cur = model.store.getState().current!;
    expect(pausedNodeIn(cur.trace.graph, cur.pause.paused!, cur.calls, SUB, () => true)).toBe("s_call");
  });

  test("M0b 기록(노드·경로 없는 debug.pause)도 멈춤으로 읽는다", () => {
    const s = applyPause(NO_PAUSE, ev(3, { event: "debug.pause", step: "s2" }));
    expect(s.paused).toMatchObject({ step: "s2", node: null, path: [], reason: "request", where: "boundary" });
    expect(pausedNodeIn(ROOT, s.paused!, {}, ROOT, () => true)).toBeNull();
    const r = applyPause(s, ev(4, { event: "debug.resume", step: "s2" }));
    expect(r).toEqual({ paused: null, count: 1, pausedMs: 0, epoch: 1, debugSeq: 4 });
  });

  test("test_stale_pause_reply_after_pause_and_resume_ignored", async () => {
    // 검수 T9-1 REPRO 3: run.pause 요청 → debug.pause → 계속 → debug.resume → 늦은 {state: pausing} 응답.
    // 이미 재개된 실행을 "멈추는 중"으로 되돌리지 않는다 (F6이 꺼진 채 남지 않는다)
    let respond: (r: unknown) => void = () => {};
    replies.set("run.pause", () => new Promise((r) => (respond = r)));
    replies.set("run.resume", () => ({ state: "running" }));
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    feed(model, PAUSED_IN_SUB.slice(0, 4));
    const pending = model.pause();
    feed(model, [ev(5, { event: "debug.pause", step: "s3", node: "n_key", graph: ROOT, path: ["n_key"], reason: "request", where: "boundary" })]);
    await model.resume("continue");
    feed(model, [ev(6, { event: "debug.resume", step: "s3", mode: "continue", epoch: 1, paused_ms: 5 })]);
    respond({ state: "pausing" });
    await pending;
    const cur = model.store.getState().current!;
    expect(cur.pause.paused).toBeNull();
    expect(cur.pausing).toBe(false);
    expect(debugAvailability(model.store.getState())).toMatchObject({ canPause: true, pausing: false });
  });

  test("멈추는 중 표시는 재개 이벤트에서도 풀린다", async () => {
    // 브레이크포인트로 멈춘 실행 → 계속 → 일시정지 요청(pausing) → 그 사이 다른 창이 재개 (debug.resume)
    replies.set("run.pause", () => ({ state: "pausing" }));
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    feed(model, PAUSED_IN_SUB.slice(0, 4));
    await model.pause();
    expect(model.store.getState().current!.pausing).toBe(true);
    feed(model, [ev(5, { event: "debug.resume", step: "s3", mode: "continue", epoch: 1, paused_ms: 0 })]);
    expect(model.store.getState().current!.pausing).toBe(false);
  });

  test("응답이 멈춤 전에 오면 멈추는 중, 멈춤 이벤트가 그것을 끝낸다", async () => {
    let respond: (r: unknown) => void = () => {};
    replies.set("run.pause", () => new Promise((r) => (respond = r)));
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    feed(model, PAUSED_IN_SUB.slice(0, 4));
    const pending = model.pause();
    // 멈춤과 무관한 이벤트는 응답을 낡게 하지 않는다
    feed(model, [ev(5, { event: "log", level: "info", message: "x" })]);
    respond({ state: "pausing" });
    await pending;
    expect(model.store.getState().current!.pausing).toBe(true);
    feed(model, [ev(6, { event: "debug.pause", step: "s3", node: "n_key", graph: ROOT, path: ["n_key"], reason: "request", where: "poll" })]);
    expect(model.store.getState().current!.pausing).toBe(false);
  });
});

describe("활성 조건", () => {
  test("툴바는 실행이 있을 때만, Step은 멈춘 동안만, 다시 시작 중에는 단추를 끈다", async () => {
    const model = newModel();
    expect(debugAvailability(model.store.getState()).visible).toBe(false);
    expect(await model.start(ROOT)).toBe(true);
    expect(debugAvailability(model.store.getState())).toEqual({
      visible: true,
      paused: false,
      pausing: false,
      canPause: true,
      canStep: false,
      canRestart: true,
      canStop: true,
    });
    model.ended({ run_id: RUN, last_seq: 0, outcome: { verdict: "pass", exit_code: 0, finalized_by: "runner" } });
    expect(debugAvailability(model.store.getState()).visible).toBe(false);
  });

  test("다시 시작은 새 실행을 따라가고 그동안 툴바를 남긴다", async () => {
    let release: () => void = () => {};
    replies.set("run.restart", () => new Promise((r) => (release = () => r({ run_id: "new00001", run_dir: "C:/ws/runs/y", graph: ROOT }))));
    const model = newModel();
    expect(await model.start(ROOT)).toBe(true);
    const restarting = model.restart();
    await tick();
    // 옛 실행이 끝나도 새 실행 응답 전까지 툴바는 남고 단추는 꺼진다
    model.ended({ run_id: RUN, last_seq: 0, outcome: { verdict: "error", exit_code: 1, finalized_by: "runner" } });
    expect(debugAvailability(model.store.getState())).toMatchObject({ visible: true, canRestart: false, canPause: false });
    release();
    expect(await restarting).toBe(true);
    expect(model.store.getState().current).toMatchObject({ runId: "new00001", phase: "running" });
    expect(calls.find((c) => c.method === "run.restart")?.params).toEqual({ run_id: RUN });
  });
});
