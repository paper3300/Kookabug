// 실행 중 강조 규칙 (M2 계획 2.8 "강조 규칙", T11 완료 기준·검수 1차 반례)
import { describe, expect, test } from "vitest";
import type { GraphValue } from "../graph/model";
import {
  applyEvent,
  emptyTrace,
  formatClock,
  loopProgress,
  pathKey,
  runningText,
  stepLabel,
  tabRunView,
  unresolvedCall,
  type CallMap,
  type GraphLookup,
  type RunEvent,
  type RunTrace,
} from "./highlight";

const ROOT = "tests/a.graph.json";
const SUB = "subgraphs/login.graph.json";
const OTHER = "subgraphs/other.graph.json";
const T0 = Date.parse("2026-11-01T00:00:00.000Z");

const root: GraphValue = {
  nodes: {
    n_entry: { type: "core.graph.entry", title: "시작", next: { start: "n_call" } },
    n_call: { type: "core.graph.call", title: "로그인", config: { graph: SUB }, next: { success: "n_key" } },
    n_key: { type: "core.input.key", title: "I 키", in: { keys: "I" } },
    n_loop: { type: "core.flow.repeat", title: "반복", in: { times: 10000 }, next: { body: "n_key" } },
  },
};
const sub: GraphValue = {
  nodes: {
    s_entry: { type: "core.graph.entry" },
    s_click: { type: "core.image.click", title: "시작 누르기" },
  },
};
/** 같은 노드 ID를 가진 다른 서브그래프 (실행하지 않음) */
const other: GraphValue = { nodes: { s_entry: { type: "core.graph.entry" }, s_click: { type: "core.image.click" } } };
const docs = new Map<string, GraphValue>([
  [ROOT, root],
  [SUB, sub],
  [OTHER, other],
]);
const lookup: GraphLookup = (p) => docs.get(p) ?? null;
const rootOnly: GraphLookup = (p) => (p === ROOT ? root : null);
/** 실행 스냅샷의 호출 관계 (daemon run.status calls) */
const CALLS: CallMap = { [ROOT]: { n_call: SUB } };
const loopLimit = (type: string) => (type === "core.flow.repeat" ? "times" : null);

const at = (ms: number) => new Date(T0 + ms).toISOString();

/** 시험용 이벤트 열: seq는 1부터 차례로 */
class Events {
  private seq = 0;
  private stepNo = 0;
  readonly list: RunEvent[] = [];

  private push(event: string, extra: Record<string, unknown>, ms: number): RunEvent {
    const e = { event, seq: ++this.seq, t: at(ms), run: "abcd1234", ...extra };
    this.list.push(e);
    return e;
  }

  runStart(ms = 0) {
    return this.push("run.start", { graph: ROOT, protocol: 1 }, ms);
  }

  start(path: string[], ms: number, extra: Record<string, unknown> = {}): string {
    const step = `s${++this.stepNo}`;
    this.push("step.start", { step, node: path[path.length - 1], path, parent: null, attempt: 1, ...extra }, ms);
    return step;
  }

  end(step: string, ms: number, extra: Record<string, unknown> = {}) {
    return this.push("step.end", { step, attempt: 1, status: "success", exit: "done", outputs: {}, duration_ms: 0, ...extra }, ms);
  }

  runEnd(ms: number, verdict = "pass") {
    return this.push("run.end", { verdict, code: "x", reason: "", duration_ms: ms, failure_path: null, failure_step: null, finalized_by: "runner" }, ms);
  }
}

function traceOf(events: RunEvent[]): RunTrace {
  return events.reduce(applyEvent, emptyTrace("abcd1234", ROOT));
}

/** 서브그래프 안 스텝이 열린 기록 */
function nestedRunning(): RunTrace {
  const ev = new Events();
  ev.runStart();
  ev.start(["n_call"], 1);
  ev.end(ev.start(["n_call", "s_entry"], 2), 2, { duration_ms: 0 });
  ev.start(["n_call", "s_click"], 3);
  return traceOf(ev.list);
}

describe("강조", () => {
  test("test_open_step_highlights_root_node", () => {
    const ev = new Events();
    ev.runStart();
    ev.end(ev.start(["n_entry"], 1), 1);
    ev.start(["n_key"], 5);
    const view = tabRunView(traceOf(ev.list), { path: ROOT, value: root }, CALLS);
    const key = view.nodes.get("n_key")!;
    expect(key.highlight).toBe(true);
    expect(key.tone).toBe("run");
    expect(key.since).toBe(T0 + 5);
    expect(runningText(key.since!, T0 + 1405)).toBe("● 1.4s");
    expect(view.nodes.get("n_entry")!.highlight).toBe(false);
    expect([...view.nodes.values()].filter((v) => v.highlight)).toHaveLength(1);
    expect(view.running).toBe(true);
  });

  test("test_nested_step_highlights_call_node_in_root", () => {
    const trace = nestedRunning();
    const view = tabRunView(trace, { path: ROOT, value: root }, CALLS);
    const node = view.nodes.get("n_call")!;
    expect(node.highlight).toBe(true);
    // 강조 노드의 스텝은 그 호출 스텝이다
    expect(node.step.path).toEqual(["n_call"]);
    // 안쪽 노드 ID는 루트 탭에 없다
    expect(view.nodes.has("s_click")).toBe(false);
    // 호출 관계를 아직 모르면(스냅샷 전) 루트 탭의 호출 노드는 그래도 강조한다
    expect(tabRunView(trace, { path: ROOT, value: root }, {}).nodes.get("n_call")!.highlight).toBe(true);
  });

  test("test_subgraph_tab_highlights_inner_node", () => {
    const trace = nestedRunning();
    const view = tabRunView(trace, { path: SUB, value: sub }, CALLS);
    expect(view.nodes.get("s_click")!.highlight).toBe(true);
    expect(view.nodes.get("s_entry")!.text).toBe("✓ 0ms");
    expect(view.running).toBe(true);
    // 호출 관계를 모르면 서브그래프 탭은 강조하지 않는다
    const lost = tabRunView(trace, { path: SUB, value: sub }, {});
    expect(lost.nodes.size).toBe(0);
    expect(lost.running).toBe(false);
    expect(unresolvedCall(ROOT, ["n_call", "s_click"], {})).toBe(JSON.stringify([ROOT, "n_call"]));
    expect(unresolvedCall(ROOT, ["n_call", "s_click"], CALLS)).toBeNull();
    // 노드 이름은 그 파일이 열려 있으면 버퍼에서 온다
    expect(stepLabel(ROOT, ["n_call", "s_click"], CALLS, lookup)).toBe("시작 누르기");
    expect(stepLabel(ROOT, ["n_call", "s_click"], CALLS, rootOnly)).toBe("s_click");
  });

  test("test_snapshot_calls_not_buffer_when_call_target_edited", () => {
    // 검수 1차 반례: 실행 중 루트 버퍼의 호출 대상을 다른 파일로 고쳐도 실행한 파일(스냅샷)에 붙는다
    const trace = nestedRunning();
    const edited: GraphValue = structuredClone(root);
    ((edited.nodes as Record<string, { config: { graph: string } }>).n_call.config).graph = OTHER;
    docs.set(ROOT, edited);
    try {
      expect(tabRunView(trace, { path: SUB, value: sub }, CALLS).nodes.get("s_click")!.highlight).toBe(true);
      const never = tabRunView(trace, { path: OTHER, value: other }, CALLS);
      expect(never.nodes.size).toBe(0);
      expect(never.running).toBe(false);
    } finally {
      docs.set(ROOT, root);
    }
  });

  test("test_subgraph_highlight_without_ancestor_tab_open", () => {
    // 루트 탭을 닫았거나(앱을 다시 열어) 조상 탭이 열려 있지 않아도 실행 중 서브그래프 탭은 강조·결과를 보인다
    const trace = nestedRunning();
    const onlySub: GraphLookup = (p) => (p === SUB ? sub : null);
    const view = tabRunView(trace, { path: SUB, value: sub }, CALLS);
    expect(view.nodes.get("s_click")!.highlight).toBe(true);
    expect(view.nodes.get("s_entry")!.result?.end?.status).toBe("success");
    expect(stepLabel(ROOT, ["n_call", "s_click"], CALLS, onlySub)).toBe("시작 누르기");
  });

  test("test_ended_step_status_and_duration", () => {
    const ev = new Events();
    ev.runStart();
    ev.end(ev.start(["n_entry"], 1), 39, { duration_ms: 38 });
    ev.end(ev.start(["n_key"], 40), 50, { status: "fail", exit: "timeout", duration_ms: 10_012 });
    ev.end(ev.start(["n_call"], 60), 61, { status: "error", exit: null, duration_ms: 1, error: { code: "x", message: "y" } });
    const view = tabRunView(traceOf(ev.list), { path: ROOT, value: root }, CALLS);
    expect(view.nodes.get("n_entry")).toMatchObject({ tone: "ok", text: "✓ 38ms", since: null, highlight: false });
    expect(view.nodes.get("n_key")).toMatchObject({ tone: "fail", text: "✕ 10.0s" });
    expect(view.nodes.get("n_call")).toMatchObject({ tone: "error", text: "✕ 1ms" });
    expect(view.nodes.get("n_call")!.result!.end!.error).toEqual({ code: "x", message: "y" });
    // 실행이 끝나면 강조가 없고 아직 닿지 않음도 없다
    ev.runEnd(70, "fail");
    const ended = tabRunView(traceOf(ev.list), { path: ROOT, value: root }, CALLS);
    expect([...ended.nodes.values()].some((v) => v.highlight)).toBe(false);
    expect(ended.running).toBe(false);
  });

  test("test_loop_iteration_counter", () => {
    const ev = new Events();
    ev.runStart();
    for (let i = 0; i < 3; i++) {
      ev.end(ev.start(["n_loop"], 10 * i), 10 * i, { exit: "body", outputs: { index: i } });
      ev.end(ev.start(["n_key"], 10 * i + 1, { iteration: i }), 10 * i + 2);
    }
    const trace = traceOf(ev.list);
    const view = tabRunView(trace, { path: ROOT, value: root }, CALLS, loopLimit);
    expect(view.nodes.get("n_loop")).toMatchObject({ tone: "run", text: "3 / 10,000" });
    expect(loopProgress(trace, CALLS, lookup, loopLimit)).toEqual({ count: 3, limit: 10000 });
    ev.end(ev.start(["n_loop"], 40), 40, { exit: "done" });
    ev.runEnd(50);
    const done = tabRunView(traceOf(ev.list), { path: ROOT, value: root }, CALLS, loopLimit);
    expect(done.nodes.get("n_loop")).toMatchObject({ tone: "ok", text: "✓ 3 / 10,000" });
  });

  test("test_unknown_node_ids_ignored", () => {
    const ev = new Events();
    ev.runStart();
    // 스냅샷에만 있는 노드 (버퍼에서 지움): 강조·상태 없음, 실행 로그에는 남는다
    ev.end(ev.start(["n_gone"], 1), 2, { duration_ms: 1 });
    ev.start(["n_gone_too"], 3);
    const trace = traceOf(ev.list);
    const view = tabRunView(trace, { path: ROOT, value: root }, CALLS);
    expect(view.nodes.size).toBe(0);
    expect(trace.log.some((l) => l.path?.[0] === "n_gone" && l.level === "OK")).toBe(true);
    expect(stepLabel(ROOT, ["n_gone"], CALLS, lookup)).toBe("n_gone");
  });

  test("test_events_out_of_order_rejected", () => {
    const ev = new Events();
    ev.runStart();
    const s1 = ev.start(["n_entry"], 1);
    ev.end(s1, 2, { duration_ms: 1 });
    const s2 = ev.start(["n_key"], 3);
    const [start, a, b, c] = ev.list;
    let trace = emptyTrace("abcd1234", ROOT);
    for (const e of [start, a, b, c]) trace = applyEvent(trace, e);
    const after = trace;
    // 중복·역행은 그대로 돌려준다 (같은 객체)
    expect(applyEvent(after, b)).toBe(after);
    expect(applyEvent(after, a)).toBe(after);
    expect(applyEvent(after, { ...b, seq: 0 })).toBe(after);
    expect(after.lastSeq).toBe(4);
    expect(after.open.has(s2)).toBe(true);
    expect(after.stepsEnded).toBe(1);
  });
});

describe("노드 결과", () => {
  test("test_last_completed_result_kept_while_next_step_runs", () => {
    // 검수 1차 반례: 다음 회차의 step.start가 앞 회차의 결과(출력·오류·생략·증거)를 지우지 않는다
    const ev = new Events();
    ev.runStart();
    const first = ev.start(["n_key"], 1, { iteration: 0 });
    ev.end(first, 5, {
      status: "fail",
      exit: "timeout",
      duration_ms: 4,
      outputs: { text: "previous result" },
      error: { code: "e", message: "m" },
      omitted: [{ kind: "screenshot", reason: "policy_off" }],
      artifacts: ["steps/s2_timeout.png"],
    });
    const second = ev.start(["n_key"], 6, { iteration: 1 });
    const trace = traceOf(ev.list);
    expect(trace.latest.get(pathKey(["n_key"]))!.end).toBeNull();
    const view = tabRunView(trace, { path: ROOT, value: root }, CALLS).nodes.get("n_key")!;
    expect(view.step.step).toBe(second);
    expect(view.highlight).toBe(true);
    const result = view.result!;
    expect(result.step).toBe(first);
    expect(result.end).toMatchObject({
      status: "fail",
      exit: "timeout",
      outputs: { text: "previous result" },
      error: { code: "e", message: "m" },
      artifacts: ["steps/s2_timeout.png"],
    });
    expect(result.end!.omitted).toHaveLength(1);
  });

  test("test_final_attempt_from_step_end", () => {
    // 재시도해도 step.start는 한 번이다: 끝 이벤트의 attempt가 마지막 시도 번호
    const ev = new Events();
    ev.runStart();
    ev.end(ev.start(["n_key"], 1), 9, { attempt: 3, retried: true, duration_ms: 8 });
    const view = tabRunView(traceOf(ev.list), { path: ROOT, value: root }, CALLS).nodes.get("n_key")!;
    expect(view.result!.attempt).toBe(3);
    expect(view.step.attempt).toBe(3);
  });
});

describe("기록", () => {
  test("run.end가 열린 스텝을 중단으로 닫는다", () => {
    const ev = new Events();
    ev.runStart();
    ev.start(["n_key"], 5);
    ev.runEnd(1005, "error");
    const trace = traceOf(ev.list);
    expect(trace.open.size).toBe(0);
    const view = tabRunView(trace, { path: ROOT, value: root }, CALLS);
    expect(view.nodes.get("n_key")).toMatchObject({ tone: "muted", text: "■ 중단", highlight: false });
    expect(trace.end?.verdict).toBe("error");
    expect(trace.log.at(-1)).toMatchObject({ level: "ERROR" });
  });

  test("로그 시각은 실행 시작부터", () => {
    expect(formatClock(0)).toBe("00:00:00.000");
    expect(formatClock(4_324_331)).toBe("01:12:04.331");
  });

  test("다른 그래프 탭은 흐리지 않는다", () => {
    const ev = new Events();
    ev.runStart();
    ev.start(["n_key"], 5);
    const view = tabRunView(traceOf(ev.list), { path: "tests/other.graph.json", value: root }, CALLS);
    expect(view.running).toBe(false);
    expect(view.nodes.size).toBe(0);
  });
});
