// 실행 화면 상태와 구독 커서 (M2 계획 2.8 "구독 순서와 커서", 검수 M3, T11 완료 기준)
import { beforeEach, describe, expect, test } from "vitest";
import { RpcError, type RpcCall } from "../rpc/client";
import { SessionRecovery } from "../rpc/recovery";
import { tabRunView } from "./highlight";
import { mergeCalls, RunModel, type RunHooks } from "./runStore";

const RUN = "abcd1234";
const GRAPH = "tests/a.graph.json";
const T0 = Date.parse("2026-11-01T00:00:00.000Z");

interface Call {
  method: string;
  params: Record<string, unknown>;
}

let calls: Call[];
let replies: Map<string, (params: Record<string, unknown>) => unknown>;
const call: RpcCall = async (method, params) => {
  calls.push({ method, params: params as Record<string, unknown> });
  const reply = replies.get(method);
  if (reply === undefined) return {} as never;
  return reply(params as Record<string, unknown>) as never;
};
const subscribes = () => calls.filter((c) => c.method === "run.subscribe").map((c) => c.params.after_seq);
const tick = () => new Promise((r) => setTimeout(r, 0));

function step(seq: number, n = seq): Record<string, unknown> {
  return { event: "step.start", seq, t: new Date(T0 + seq).toISOString(), run: RUN, step: `s${n}`, node: `n${n}`, path: [`n${n}`], parent: null, attempt: 1 };
}

let notes: string[];
let saved: string[];
let dirty: boolean;
let model: RunModel;

function hooks(): Partial<RunHooks> {
  return {
    note: (_l, m) => notes.push(m),
    showPanel: () => {},
    save: async (p) => {
      saved.push(p);
      dirty = false;
      return "saved";
    },
    revision: () => ({ dirty, revision: dirty ? "r1" : "r2" }),
  };
}

beforeEach(() => {
  calls = [];
  notes = [];
  saved = [];
  dirty = false;
  replies = new Map([["run.start", () => ({ run_id: RUN, run_dir: "C:/ws/runs/x", graph: GRAPH })]]);
  model = new RunModel(call, hooks());
});

async function started(): Promise<void> {
  expect(await model.start(GRAPH)).toBe(true);
  expect(subscribes()).toEqual([0]);
}

describe("구독 커서", () => {
  test("test_applied_cursor_advances_only_in_order", async () => {
    await started();
    model.event({ run_id: RUN, seq: 1, event: { event: "run.start", seq: 1, t: new Date(T0).toISOString(), run: RUN, graph: GRAPH, protocol: 1, runner: { pid: 1, created: 1, version: "0" } } as never });
    model.event({ run_id: RUN, seq: 2, event: step(2) as never });
    expect(model.cursors.applied(RUN)).toBe(2);
    // 빈틈(4): 적용하지 않고 커서도 그대로
    model.event({ run_id: RUN, seq: 4, event: step(4) as never });
    expect(model.cursors.applied(RUN)).toBe(2);
    expect(model.store.getState().current!.trace.lastSeq).toBe(2);
    // 중복·역행은 버린다
    model.event({ run_id: RUN, seq: 2, event: step(2, 99) as never });
    model.event({ run_id: RUN, seq: 1, event: step(1, 98) as never });
    expect(model.cursors.applied(RUN)).toBe(2);
    expect([...model.store.getState().current!.trace.open.keys()]).toEqual(["s2"]);
    // 다음 seq가 오면 이어서 적용한다
    model.event({ run_id: RUN, seq: 3, event: step(3) as never });
    model.event({ run_id: RUN, seq: 4, event: step(4) as never });
    expect(model.cursors.applied(RUN)).toBe(4);
    expect(model.store.getState().current!.trace.lastSeq).toBe(4);
  });

  test("test_gap_triggers_resubscribe_from_applied_seq", async () => {
    await started();
    model.event({ run_id: RUN, seq: 1, event: step(1) as never });
    model.event({ run_id: RUN, seq: 2, event: step(2) as never });
    model.event({ run_id: RUN, seq: 5, event: step(5) as never });
    await tick();
    expect(subscribes()).toEqual([0, 2]);
  });

  test("test_lagged_resubscribes_from_applied_not_server_seq", async () => {
    await started();
    for (let s = 1; s <= 3; s++) model.event({ run_id: RUN, seq: s, event: step(s) as never });
    // daemon은 더 보냈을 수 있지만(큐에 넣고 못 보냄) 커서는 렌더러가 적용한 3이다
    model.lagged({ run_id: RUN });
    await tick();
    expect(subscribes()).toEqual([0, 3]);
    // 다시 받은 이벤트는 4부터 이어진다 (중복 없음)
    model.event({ run_id: RUN, seq: 3, event: step(3) as never });
    model.event({ run_id: RUN, seq: 4, event: step(4) as never });
    expect(model.store.getState().current!.trace.open.size).toBe(4);
  });

  test("다시 붙으면 끝나지 않은 실행을 적용한 seq부터 (recovery RunHost)", async () => {
    await started();
    for (let s = 1; s <= 2; s++) model.event({ run_id: RUN, seq: s, event: step(s) as never });
    await model.cursors.resubscribeAll();
    expect(subscribes()).toEqual([0, 2]);
    model.ended({ run_id: RUN, last_seq: 2, outcome: { verdict: "pass", exit_code: 0, finalized_by: "runner" } });
    await model.cursors.resubscribeAll();
    expect(subscribes()).toEqual([0, 2]);
    expect(model.store.getState().current!.phase).toBe("ended");
  });
});

describe("시작", () => {
  test("저장 안 된 문서는 저장한 뒤 실행한다 (U2)", async () => {
    dirty = true;
    expect(await model.start(GRAPH)).toBe(true);
    expect(saved).toEqual([GRAPH]);
    const order = calls.map((c) => c.method);
    expect(order).toEqual(["run.start", "run.subscribe"]);
    // 시작할 때(저장 뒤)의 revision을 기억한다
    expect(model.store.getState().current!.revision).toBe("r2");
  });

  test("저장이 안 되면 실행하지 않는다", async () => {
    dirty = true;
    model.setHooks({ save: async () => "conflict" });
    expect(await model.start(GRAPH)).toBe(false);
    expect(calls).toEqual([]);
    expect(model.store.getState().blocked).toMatchObject({ kind: "save", path: GRAPH });
  });

  test("검증 오류면 막고 오류 수를 보인다", async () => {
    replies.set("run.start", () => {
      throw new RpcError(-32100, "검증 실패", {
        code: "validation_failed",
        diagnostics: [
          { severity: "error", code: "a", message: "x" },
          { severity: "warning", code: "b", message: "y" },
          { severity: "error", code: "c", message: "z" },
        ],
      });
    });
    const panels: string[] = [];
    model.setHooks({ showPanel: (t) => panels.push(t) });
    expect(await model.start(GRAPH)).toBe(false);
    expect(model.store.getState().blocked).toMatchObject({ kind: "validation", errors: 2, message: "검증 오류 2개" });
    expect(model.store.getState().current).toBeNull();
    expect(panels).toEqual(["problems"]);
  });

  test("실행 중에는 다시 시작하지 않는다", async () => {
    await started();
    expect(await model.start(GRAPH)).toBe(false);
    expect(calls.filter((c) => c.method === "run.start")).toHaveLength(1);
  });

  test("붙을 때 진행 중 실행을 처음부터 다시 구독한다 (앱 다시 열기)", async () => {
    replies.set("run.list", () => ({
      runs: [
        { run_id: "zzzz0000", graph: GRAPH, run_dir: "d1", state: "ended", outcome: null, last_seq: 9, started_at: null },
        { run_id: RUN, graph: GRAPH, run_dir: "d2", state: "running", outcome: null, last_seq: 4, started_at: null },
      ],
    }));
    replies.set("run.status", () => ({ calls: { [GRAPH]: { n_call: "subgraphs/s.graph.json" } } }));
    await model.syncActive();
    expect(model.store.getState().current).toMatchObject({ runId: RUN, phase: "running", runDir: "d2", revision: null });
    expect(subscribes()).toEqual([0]);
    // 이미 돌던 실행은 스냅샷 호출 관계를 바로 받는다 (조상 탭이 안 열려 있어도 서브그래프 강조)
    expect(model.store.getState().current!.calls).toEqual({ [GRAPH]: { n_call: "subgraphs/s.graph.json" } });
    // 따라가는 실행이 있으면 다시 찾지 않는다
    await model.syncActive();
    expect(calls.filter((c) => c.method === "run.list")).toHaveLength(1);
  });

  test("test_profile_validation_diagnostics_kept_for_problems", async () => {
    // 검수 1차 반례: 기본 설정은 정상이고 고른 프로필만 설정을 null로 둔다. 문서 검증에는 없는 진단이라
    // 실행 거부 진단을 보관해야 문제 패널에 원인(파일·노드·코드)이 나온다
    const diag = {
      severity: "error",
      code: "setting_null",
      message: "설정 'message'가 null이다",
      file: GRAPH,
      node: "n_log",
      pointer: "/nodes/n_log/in/text",
    };
    replies.set("run.start", () => {
      throw new RpcError(-32100, "검증 실패", { code: "validation_failed", diagnostics: [diag] });
    });
    model.setProfile("broken");
    expect(await model.start(GRAPH)).toBe(false);
    expect(calls.find((c) => c.method === "run.start")!.params.profile).toBe("broken");
    expect(model.store.getState().blocked).toMatchObject({
      kind: "validation",
      errors: 1,
      message: "검증 오류 1개",
      profile: "broken",
      diagnostics: [diag],
    });
    // 같은 프로필이면 남고, 프로필을 바꾸면 그 진단은 버린다
    model.setProfile("broken");
    expect(model.store.getState().blocked).not.toBeNull();
    model.setProfile(null);
    expect(model.store.getState().blocked).toBeNull();
  });

  test("test_calls_loaded_from_snapshot_on_nested_step", async () => {
    let statusCalls = 0;
    replies.set("run.status", () => {
      statusCalls++;
      return { calls: { [GRAPH]: { n_call: "subgraphs/s.graph.json" } } };
    });
    await started();
    expect(model.store.getState().current!.calls).toEqual({});
    model.event({ run_id: RUN, seq: 1, event: { ...step(1), node: "n_call", path: ["n_call"] } as never });
    expect(statusCalls).toBe(0); // 루트 스텝은 호출 관계가 필요 없다
    model.event({ run_id: RUN, seq: 2, event: { ...step(2), node: "x", path: ["n_call", "x"] } as never });
    await tick();
    expect(statusCalls).toBe(1);
    expect(model.store.getState().current!.calls).toEqual({ [GRAPH]: { n_call: "subgraphs/s.graph.json" } });
    // 알게 된 호출은 다시 묻지 않는다
    model.event({ run_id: RUN, seq: 3, event: { ...step(3), node: "y", path: ["n_call", "y"] } as never });
    await tick();
    expect(statusCalls).toBe(1);
  });

  test("임대권 소유자", () => {
    model.lease({ owner: { kind: "runner", run_id: RUN, pid: 3 } });
    expect(model.store.getState().lease).toMatchObject({ run_id: RUN });
    model.lease({ owner: null });
    expect(model.store.getState().lease).toBeNull();
  });
});

describe("실행 스냅샷 호출 관계 조회 (T11 검수 2차)", () => {
  const SUB = "subgraphs/a.graph.json";
  const CALLS = { [GRAPH]: { call: SUB } };
  const TAB = { path: SUB, value: { nodes: { inner: { type: "core.log.message" }, later: { type: "core.log.message" } } } };
  const summary = { run_id: RUN, graph: GRAPH, run_dir: "C:/ws/runs/r", state: "running", outcome: null, last_seq: 0, started_at: null };
  const ev = (seq: number, type: string, fields: Record<string, unknown>) =>
    model.event({ run_id: RUN, seq, event: { event: type, run: RUN, seq, t: new Date(T0 + seq).toISOString(), ...fields } as never });
  const initialSteps = () => {
    ev(1, "run.start", { graph: GRAPH });
    ev(2, "step.start", { step: "s1", node: "call", path: ["call"], parent: null, attempt: 1 });
    ev(3, "step.start", { step: "s2", node: "inner", path: ["call", "inner"], parent: "s1", attempt: 1 });
  };
  const subgraphStates = () => {
    const current = model.store.getState().current!;
    return tabRunView(current.trace, TAB, current.calls).nodes.size;
  };

  test("test_calls_fetch_failure_retried_on_reconnect_without_next_step", async () => {
    // 첫 조회가 끊겨 실패한다 → 같은 daemon에 다시 붙는다 → 다음 스텝이 오지 않아도(긴 대기) 다시 받는다
    let statusCount = 0;
    replies.set("run.list", () => ({ runs: [summary] }));
    replies.set("run.status", () => {
      statusCount++;
      if (statusCount === 1) throw new RpcError(-32000, "끊김", { code: "not_connected" });
      return { ...summary, calls: CALLS };
    });
    const recovery = new SessionRecovery(call);
    recovery.addRuns(model.cursors);
    await recovery.connected({ root: "C:/ws", startId: "d1", connection: 1 });
    await started();
    initialSteps();
    await tick();
    expect(statusCount).toBe(1);
    expect(subgraphStates()).toBe(0);
    // workspace.onDaemonState와 같은 순서: 복구(적용한 seq부터 다시 구독) → syncActive
    await recovery.connected({ root: "C:/ws", startId: "d1", connection: 2 });
    await model.syncActive();
    await tick();
    expect(statusCount).toBe(2);
    expect(model.store.getState().current!.calls).toEqual(CALLS);
    expect(subgraphStates()).toBeGreaterThan(0);
    expect(model.cursors.applied(RUN)).toBe(3);
  });

  test("test_calls_fetch_failure_retried_on_next_nested_step", async () => {
    let statusCount = 0;
    replies.set("run.status", () => {
      statusCount++;
      if (statusCount === 1) throw new RpcError(-32000, "끊김", { code: "not_connected" });
      return { ...summary, calls: CALLS };
    });
    await started();
    initialSteps();
    await tick();
    expect(statusCount).toBe(1);
    ev(4, "step.end", { step: "s2", status: "success", exit: "done", outputs: {}, duration_ms: 1, attempt: 1 });
    ev(5, "step.start", { step: "s3", node: "later", path: ["call", "later"], parent: "s1", attempt: 1 });
    await tick();
    expect(statusCount).toBe(2);
    expect(subgraphStates()).toBe(2);
  });

  test("test_late_empty_calls_response_does_not_erase", async () => {
    // 붙을 때의 조회(스냅샷 전 빈 결과)가 늦게 돌아온다. 그 사이 서브그래프 스텝이 왔다
    let statusCount = 0;
    let finishOld!: (value: unknown) => void;
    const old = new Promise((resolve) => (finishOld = resolve));
    replies.set("run.list", () => ({ runs: [summary] }));
    replies.set("run.status", () => {
      statusCount++;
      return statusCount === 1 ? old : { ...summary, calls: CALLS };
    });
    const sync = model.syncActive();
    await tick();
    initialSteps();
    await tick();
    // 한 실행에 조회는 한 번에 하나: 앞 조회가 끝나기를 기다린다
    expect(statusCount).toBe(1);
    finishOld({ ...summary, calls: {} });
    await sync;
    await tick();
    // 앞 조회는 이 스텝들보다 먼저 나갔다: 덮지 못한 스텝이 있어 한 번 더 묻고 관계를 채운다
    expect(statusCount).toBe(2);
    expect(model.store.getState().current!.calls).toEqual(CALLS);
    expect(subgraphStates()).toBeGreaterThan(0);
    // 다음 스텝은 아는 호출이라 더 묻지 않는다
    ev(4, "step.end", { step: "s2", status: "success", exit: "done", outputs: {}, duration_ms: 1, attempt: 1 });
    ev(5, "step.start", { step: "s3", node: "later", path: ["call", "later"], parent: "s1", attempt: 1 });
    await tick();
    expect(statusCount).toBe(2);
    expect(subgraphStates()).toBe(2);
  });

  test("test_merge_calls_never_drops_known", () => {
    // 응답 순서가 바뀌어도(나중 응답이 빈·덜 찬 결과) 받은 관계는 남는다
    const full = mergeCalls({}, { [GRAPH]: { call: SUB }, [SUB]: { deep: "subgraphs/b.graph.json" } });
    expect(mergeCalls(full, {})).toEqual(full);
    expect(mergeCalls(full, { [GRAPH]: {} })).toEqual(full);
    expect(mergeCalls(full, { [GRAPH]: { other: "subgraphs/c.graph.json" } })).toEqual({
      [GRAPH]: { call: SUB, other: "subgraphs/c.graph.json" },
      [SUB]: { deep: "subgraphs/b.graph.json" },
    });
    const proto = mergeCalls({}, JSON.parse('{"tests/a.graph.json": {"__proto__": "subgraphs/p.graph.json"}}'));
    expect(Object.hasOwn(proto[GRAPH], "__proto__")).toBe(true);
  });
});
