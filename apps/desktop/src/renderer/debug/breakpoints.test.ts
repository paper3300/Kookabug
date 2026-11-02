// 브레이크포인트 (M3 계획 2.3·2.9, U1, T9 완료 기준): exec 노드에만, {그래프 파일, 노드 ID} 열쇠라 편집 뒤에도 남음,
// daemon 목록과 맞추기
import { beforeEach, describe, expect, test } from "vitest";
import { addNode, moveNodes } from "../graph/commands/nodes";
import { connectData } from "../graph/commands/edges";
import { setNodeTitle, setNodeValue } from "../graph/commands/setPin";
import { indexNodeTypes } from "../graph/mapping";
import type { GraphValue } from "../graph/model";
import type { RpcCall } from "../rpc/client";
import {
  BreakpointModel,
  breakpointsIn,
  canBreak,
  toggleBreakpoint,
  toggleMany,
  type Breakpoint,
} from "./breakpoints";

const ROOT = "tests/a.graph.json";
const SUB = "subgraphs/login.graph.json";

const types = indexNodeTypes([
  {
    nodes: [
      { type: "core.graph.entry", engine: "graph_entry" },
      { type: "core.input.key", effects: ["input"] },
      { type: "core.ocr.read", effects: ["capture"] },
      { type: "core.logic.compare", pure: true },
      { type: "core.flow.branch" },
    ],
  },
]);

const graph: GraphValue = {
  nodes: {
    n_entry: { type: "core.graph.entry", next: { start: "n_read" } },
    n_read: { type: "core.ocr.read", title: "글자 읽기", next: { done: "n_branch" } },
    n_cmp: { type: "core.logic.compare", in: { a: { $link: "n_read.text" }, b: "ok", op: "==" } },
    n_branch: { type: "core.flow.branch", in: { condition: { $link: "n_cmp.result" } }, next: { true: "n_key" } },
    n_key: { type: "core.input.key", title: "I 키", in: { keys: "I" } },
  },
  layout: { nodes: { n_entry: { x: 0, y: 0 }, n_key: { x: 200, y: 0 } } },
};

describe("브레이크포인트 토글", () => {
  test("test_toggle_not_allowed_on_pure_node", () => {
    // 순수 노드는 스텝이 없다: 토글이 목록을 바꾸지 않는다(점 자리도, 메뉴도 꺼짐)
    expect(canBreak(graph, "n_cmp", types)).toBe(false);
    expect(toggleBreakpoint([], ROOT, "n_cmp", graph, types)).toBeNull();
    expect(toggleMany([], ROOT, ["n_cmp"], graph, types)).toBeNull();
    // exec 노드는 된다 (관측·입력·분기·시작점)
    for (const id of ["n_entry", "n_read", "n_branch", "n_key"]) {
      expect(canBreak(graph, id, types)).toBe(true);
      expect(toggleBreakpoint([], ROOT, id, graph, types)).toEqual([{ graph: ROOT, node: id }]);
    }
    // 그래프에 없는 노드에는 걸지 않는다
    expect(toggleBreakpoint([], ROOT, "n_gone", graph, types)).toBeNull();
    // 순수 노드가 섞인 선택(F9)은 exec 노드만 건다. 모두 걸려 있으면 모두 푼다
    const set = toggleMany([], ROOT, ["n_cmp", "n_key", "n_branch"], graph, types)!;
    expect(set).toEqual([
      { graph: ROOT, node: "n_key" },
      { graph: ROOT, node: "n_branch" },
    ]);
    expect(toggleMany(set, ROOT, ["n_cmp", "n_key", "n_branch"], graph, types)).toEqual([]);
    // 일부만 걸려 있으면 나머지도 건다
    expect(toggleMany([{ graph: ROOT, node: "n_key" }], ROOT, ["n_key", "n_read"], graph, types)).toEqual([
      { graph: ROOT, node: "n_key" },
      { graph: ROOT, node: "n_read" },
    ]);
  });

  test("test_breakpoints_keyed_by_graph_and_node_survive_edit", () => {
    const list: Breakpoint[] = [
      { graph: ROOT, node: "n_key" },
      { graph: SUB, node: "n_read" }, // 같은 노드 ID, 다른 파일
    ];
    expect([...breakpointsIn(list, ROOT, graph)]).toEqual(["n_key"]);
    // 옮기기·제목 바꾸기·입력 고치기·연결·노드 더하기 뒤에도 그대로 (노드 ID는 바뀌지 않는다)
    let edited = moveNodes(graph, [{ id: "n_key", x: 480, y: 320 }]);
    edited = setNodeTitle(edited, "n_key", "인벤토리 열기");
    edited = setNodeValue(edited, "n_key", "in", "keys", "Tab");
    edited = connectData(edited, "n_read", "text", "n_key", "keys");
    edited = addNode(edited, { id: "n_new", type: "core.input.key", version: 1, x: 0, y: 100, plugin: null });
    expect(edited).not.toEqual(graph);
    expect([...breakpointsIn(list, ROOT, edited)]).toEqual(["n_key"]);
    // 다른 파일의 같은 노드 ID는 이 탭에 보이지 않는다
    expect(breakpointsIn(list, SUB, edited).has("n_key")).toBe(false);
    expect([...breakpointsIn(list, SUB, graph)]).toEqual(["n_read"]);
    // 노드를 지우면 표시는 없어지지만 목록은 그대로다 (같은 ID를 되살리면 다시 보인다)
    const { n_key: _gone, ...rest } = (graph.nodes as Record<string, unknown>);
    const deleted = { ...graph, nodes: rest };
    expect(breakpointsIn(list, ROOT, deleted).size).toBe(0);
    expect(list).toHaveLength(2);
  });
});

describe("daemon 목록 맞추기", () => {
  let sent: unknown[];
  let replies: Map<string, (params: Record<string, unknown>) => unknown>;
  const call: RpcCall = async (method, params) => {
    sent.push([method, params]);
    const reply = replies.get(method);
    return (reply === undefined ? {} : await reply(params as Record<string, unknown>)) as never;
  };

  beforeEach(() => {
    sent = [];
    replies = new Map();
  });

  /**
   * 가짜 daemon: 저장 요청은 각자 따로 끝나고(요청마다 작업·스레드), 끝나는 순간 파일에 쓴다. 끝나는 순서는
   * 검사가 정한다 — 먼저 보낸 요청이 나중에 끝날 수 있다 (검수 T9-1 REPRO 1)
   */
  function fakeDaemon(): {
    disk: () => Breakpoint[];
    inflight: { params: Breakpoint[]; ok: () => void; fail: () => void }[];
    maxInflight: () => number;
  } {
    let disk: Breakpoint[] = [];
    let max = 0;
    const inflight: { params: Breakpoint[]; ok: () => void; fail: () => void }[] = [];
    replies.set("debug.breakpoints.get", () => ({ breakpoints: disk }));
    replies.set(
      "debug.breakpoints.set",
      (p) =>
        new Promise((resolve, reject) => {
          const params = p.breakpoints as Breakpoint[];
          const entry = {
            params,
            ok: () => {
              inflight.splice(inflight.indexOf(entry), 1);
              disk = params;
              resolve({ breakpoints: disk });
            },
            fail: () => {
              inflight.splice(inflight.indexOf(entry), 1);
              reject({ code: -32100, message: "disk full", data: { code: "io_error" } });
            },
          };
          inflight.push(entry);
          max = Math.max(max, inflight.length);
        }),
    );
    return { disk: () => disk, inflight, maxInflight: () => max };
  }
  const tick = () => new Promise((r) => setTimeout(r, 0));
  const a = { graph: ROOT, node: "n_key" };
  const b = { graph: ROOT, node: "n_read" };

  test("test_breakpoint_saves_serialized_final_storage_matches_ui", async () => {
    const daemon = fakeDaemon();
    const model = new BreakpointModel(call);
    // 저장 중에 한 토글은 최신 희망 목록(화면 목록에서 계산)으로 합쳐 다음에 보낸다
    const first = model.set(toggleBreakpoint(model.list, ROOT, "n_key", graph, types)!);
    const second = model.set(toggleBreakpoint(model.list, ROOT, "n_read", graph, types)!);
    expect(model.list).toEqual([a, b]);
    expect(daemon.inflight.map((r) => r.params)).toEqual([[a]]);
    daemon.inflight[0].ok();
    await tick();
    // 앞 저장이 끝난 뒤에야 다음을 보낸다: 쓰기 순서 = 희망 순서
    expect(daemon.inflight.map((r) => r.params)).toEqual([[a, b]]);
    daemon.inflight[0].ok();
    await Promise.all([first, second]);
    expect(daemon.maxInflight()).toBe(1);
    expect(daemon.disk()).toEqual([a, b]);
    expect(model.list).toEqual([a, b]);
    // 다시 붙으면(새 연결) 파일 값이 화면과 같다
    const reconnected = new BreakpointModel(call);
    await reconnected.load();
    expect(reconnected.list).toEqual([a, b]);
  });

  test("test_breakpoint_all_saves_failed_ui_returns_to_confirmed", async () => {
    const daemon = fakeDaemon();
    const notes: string[] = [];
    const model = new BreakpointModel(call, (m) => notes.push(m));
    model.changed({ breakpoints: [] });
    const first = model.set([a]);
    const second = model.set([a, b]);
    daemon.inflight[0].fail();
    await tick();
    daemon.inflight[0].fail();
    await Promise.all([first, second]);
    // 확정되지 않은 낙관 값([a])이 아니라 daemon이 확인한 값으로 돌아간다
    expect(daemon.disk()).toEqual([]);
    expect(model.list).toEqual([]);
    expect(notes).toHaveLength(2);
  });

  test("앞 저장이 실패해도 뒤 저장이 되면 그 값이 최종", async () => {
    const daemon = fakeDaemon();
    const model = new BreakpointModel(call, () => {});
    const first = model.set([a]);
    const second = model.set([a, b]);
    daemon.inflight[0].fail();
    await tick();
    daemon.inflight[0].ok();
    await Promise.all([first, second]);
    expect(daemon.disk()).toEqual([a, b]);
    expect(model.list).toEqual([a, b]);
  });

  test("저장 중 다른 연결의 변경 알림은 화면을 덮지 않는다 (우리 저장이 나중에 쓰인다)", async () => {
    const daemon = fakeDaemon();
    const model = new BreakpointModel(call);
    const saving = model.set([a]);
    model.changed({ breakpoints: [{ graph: SUB, node: "x" }] });
    expect(model.list).toEqual([a]);
    daemon.inflight[0].ok();
    await saving;
    expect(model.list).toEqual([a]);
    expect(daemon.disk()).toEqual([a]);
  });

  test("저장이 실패하면 앞 목록으로 되돌리고 알린다", async () => {
    const notes: string[] = [];
    replies.set("debug.breakpoints.set", () => Promise.reject({ code: -32100, message: "io", data: { code: "io_error" } }));
    const model = new BreakpointModel(call, (m) => notes.push(m));
    model.changed({ breakpoints: [{ graph: ROOT, node: "n_key" }] });
    await model.set([]);
    expect(model.list).toEqual([{ graph: ROOT, node: "n_key" }]);
    expect(notes).toHaveLength(1);
  });

  test("붙을 때 받은 값보다 그 사이 보낸 set이 이긴다, 다른 연결의 변경 알림을 받는다", async () => {
    let releaseGet: () => void = () => {};
    replies.set("debug.breakpoints.get", () => new Promise((r) => (releaseGet = () => r({ breakpoints: [{ graph: ROOT, node: "old" }] }))));
    replies.set("debug.breakpoints.set", (p) => ({ breakpoints: p.breakpoints }));
    const model = new BreakpointModel(call);
    const loading = model.load();
    await model.set([{ graph: ROOT, node: "n_key" }]);
    releaseGet();
    await loading;
    expect(model.list).toEqual([{ graph: ROOT, node: "n_key" }]);
    model.changed({ breakpoints: [{ graph: SUB, node: "x" }, { graph: SUB, node: "x" }] });
    expect(model.list).toEqual([{ graph: SUB, node: "x" }]);
    model.reset();
    expect(model.list).toEqual([]);
  });
});
