// 편집 명령 (M2 계획 2.6 "편집 규칙", T9 완료 기준 commands.test.ts)
import { describe, expect, test } from "vitest";
import { deepFreeze, readCorpus } from "../corpus.testutil";
import { dataEdgeId, execEdgeId } from "../mapping";
import type { GraphValue } from "../model";
import { getIn, jsonEqual } from "../valueOps";
import {
  addNode,
  connect,
  connectData,
  connectExec,
  deleteNodes,
  deleteSelection,
  disconnect,
  moveNodes,
  parseEdgeId,
} from "./index";

describe("노드 지우기", () => {
  test("test_delete_node_cleans_next_links_layout_groups", () => {
    const value = deepFreeze({
      format: "kookabug.graph/0",
      kind: "test",
      nodes: {
        a: { type: "core.graph.entry", version: 1, next: { start: "c" } },
        b: { type: "core.flow.branch", version: 1, next: { true: "c", false: "d" }, in: { condition: true } },
        c: { type: "core.image.wait", version: 1, next: { found: "d" } },
        d: {
          type: "core.log.message",
          version: 1,
          in: {
            text: { $link: "c.match" },
            list: [{ $link: "c.match" }, 1],
            nested: { a: { b: { $link: "c.match" } } },
            literal: { $literal: { $link: "c.match" } },
            other: { $link: "b.value" },
          },
        },
      },
      layout: {
        nodes: { a: { x: 0, y: 0 }, c: { x: 1, y: 2 }, d: { x: 3, y: 4 } },
        collapsed: { g: { nodes: ["c", "d"], x: 0, y: 0, title: "묶음" } },
        comments: { n_note: { rect: [0, 0, 1, 1], text: "c" } },
        x_view: 1,
      },
      plugins: { core: "0.1.0" },
      x_top: true,
    });
    const out = deleteNodes(value, ["c", "없는 노드"]);
    expect(out).toEqual({
      format: "kookabug.graph/0",
      kind: "test",
      nodes: {
        // 출구 하나뿐이면 비게 된 next도 지운다
        a: { type: "core.graph.entry", version: 1 },
        b: { type: "core.flow.branch", version: 1, next: { false: "d" }, in: { condition: true } },
        // $link가 핀 값 자체·배열 원소·객체 안쪽이어도 그 핀을 지운다. $literal 안은 연결이 아니다
        d: {
          type: "core.log.message",
          version: 1,
          in: { literal: { $literal: { $link: "c.match" } }, other: { $link: "b.value" } },
        },
      },
      layout: {
        nodes: { a: { x: 0, y: 0 }, d: { x: 3, y: 4 } },
        collapsed: { g: { nodes: ["d"], x: 0, y: 0, title: "묶음" } },
        comments: { n_note: { rect: [0, 0, 1, 1], text: "c" } },
        x_view: 1,
      },
      plugins: { core: "0.1.0" },
      x_top: true,
    });
    // 여러 개 지우기
    const both = deleteNodes(value, ["c", "d"]);
    expect(Object.keys(both.nodes as object)).toEqual(["a", "b"]);
    expect(getIn(both, ["nodes", "b", "next"])).toBeUndefined();
    expect(getIn(both, ["layout", "collapsed", "g", "nodes"])).toEqual([]);
    // 없는 노드만이면 그대로
    expect(deleteNodes(value, ["없음"])).toBe(value);
  });

  test("고른 연결선과 노드를 명령 하나로 지운다", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/unknown-node.graph.json"));
    const out = deleteSelection(value, ["n_pass"], [execEdgeId("n_entry", "start"), dataEdgeId("n_fail", "reason", [])]);
    expect(getIn(out, ["nodes", "n_entry", "next"])).toBeUndefined();
    expect(getIn(out, ["nodes", "n_fail", "in"])).toBeUndefined();
    expect(getIn(out, ["nodes", "n_pass"])).toBeUndefined();
    expect(getIn(out, ["nodes", "n_log", "next"])).toBeUndefined();
  });
});

describe("연결", () => {
  test("test_connect_replaces_existing", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/doc-inventory-open.graph.json"));
    const nodes = value.nodes as Record<string, { next?: Record<string, string>; in?: Record<string, unknown> }>;
    const [from, node] = Object.entries(nodes).find(([, n]) => n.next !== undefined && Object.keys(n.next).length > 0)!;
    const exit = Object.keys(node.next!)[0];
    const other = Object.keys(nodes).find((id) => id !== from && id !== node.next![exit])!;
    // 흐름: 출구 하나에 하나 → 바꾼다
    const exec = connectExec(value, from, exit, other);
    expect(getIn(exec, ["nodes", from, "next", exit])).toBe(other);
    expect(Object.keys(getIn(exec, ["nodes", from, "next"]) as object)).toEqual(Object.keys(node.next!));
    // 같은 연결이면 같은 값
    expect(connectExec(value, from, exit, node.next![exit])).toBe(value);
    // 없는 노드로는 잇지 않는다
    expect(connectExec(value, from, exit, "없음")).toBe(value);

    // 데이터: 핀 하나에 하나 → 핀 값 전체가 $link 하나로 바뀐다 (배열 상수·앞 연결 모두)
    const v2 = deepFreeze({
      nodes: {
        a: { type: "x.a", version: 1 },
        b: { type: "x.b", version: 1, in: { region: [0, 0, 10, { $link: "a.n" }], text: { $link: "a.old" }, keep: 1 } },
      },
    });
    const d1 = connectData(v2, "a", "rect", "b", "region");
    expect(getIn(d1, ["nodes", "b", "in"])).toEqual({ region: { $link: "a.rect" }, text: { $link: "a.old" }, keep: 1 });
    const d2 = connect(v2, { source: "a", sourceHandle: "o:label", target: "b", targetHandle: "i:text" });
    expect(getIn(d2, ["nodes", "b", "in", "text"])).toEqual({ $link: "a.label" });
    // 새 핀
    const d3 = connect(v2, { source: "b", sourceHandle: "o:out", target: "a", targetHandle: "i:value" });
    expect(getIn(d3, ["nodes", "a", "in"])).toEqual({ value: { $link: "b.out" } });
    // 흐름 손잡이
    const e1 = connect(v2, { source: "a", sourceHandle: "x:done", target: "b", targetHandle: "in" });
    expect(getIn(e1, ["nodes", "a", "next"])).toEqual({ done: "b" });
    // 종류가 다른 손잡이는 잇지 않는다
    expect(connect(v2, { source: "a", sourceHandle: "x:done", target: "b", targetHandle: "i:text" })).toBe(v2);
    expect(connect(v2, { source: "a", sourceHandle: "o:x", target: "b", targetHandle: "in" })).toBe(v2);
    expect(connect(v2, { source: "a", sourceHandle: "g:out", target: "b", targetHandle: "g:in" })).toBe(v2);
  });

  test("연결 끊기: 흐름은 그 출구, 데이터는 그 핀 전체. 비면 next·in도 지운다", () => {
    const value = deepFreeze({
      nodes: {
        a: { type: "t", version: 1, next: { done: "b", fail: "b" } },
        b: { type: "t", version: 1, in: { x: { $link: "a.v" } } },
        c: { type: "t", version: 1, in: { list: [{ $link: "a.v" }, { $link: "b.w" }], y: 1 } },
      },
    });
    const e = parseEdgeId(execEdgeId("a", "done"))!;
    expect(getIn(disconnect(value, e), ["nodes", "a", "next"])).toEqual({ fail: "b" });
    const d = parseEdgeId(dataEdgeId("b", "x", []))!;
    expect(Object.hasOwn(getIn(disconnect(value, d), ["nodes", "b"]) as object, "in")).toBe(false);
    const nested = parseEdgeId(dataEdgeId("c", "list", [1]))!;
    expect(nested).toEqual({ kind: "data", node: "c", pin: "list", path: [1] });
    expect(getIn(disconnect(value, nested), ["nodes", "c", "in"])).toEqual({ y: 1 });
    // 마침표·대괄호가 든 키도 ID에서 그대로 되읽는다
    expect(parseEdgeId(dataEdgeId("n.1", "p", ["a.b", 0, "[c]"]))).toEqual({
      kind: "data",
      node: "n.1",
      pin: "p",
      path: ["a.b", 0, "[c]"],
    });
    expect(parseEdgeId("x:not json")).toBeNull();
    expect(parseEdgeId("g:[]")).toBeNull();
  });
});

describe("모르는 노드·모르는 키", () => {
  test("test_unknown_node_untouched_by_neighbor_edits", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/unknown-node.graph.json"));
    const magic = getIn(value, ["nodes", "n_magic"]);
    let v: GraphValue = value;
    v = moveNodes(v, [{ id: "n_log", x: 10.4, y: -3.6 }]);
    v = addNode(v, { id: "n_new00000", type: "core.flow.delay", version: 1, x: 5, y: 5, plugin: { id: "core", version: "9" } });
    v = connectExec(v, "n_log", "done", "n_new00000");
    v = connectData(v, "n_new00000", "x", "n_fail", "reason");
    v = deleteNodes(v, ["n_pass"]);
    v = disconnect(v, parseEdgeId(dataEdgeId("n_log", "text", []))!);
    // 이웃 노드를 고치고 지워도 모르는 노드는 같은 참조 그대로 (in·config·next·version)
    expect(getIn(v, ["nodes", "n_magic"])).toBe(magic);
    expect(getIn(v, ["plugins"])).toEqual({ acme: "2.0.0", core: "0.1.0" });
    expect(getIn(v, ["layout", "nodes", "n_log"])).toEqual({ x: 10, y: -4 });

    // 모르는 노드 연결을 끊으면 그 키만 지운다
    const cut = disconnect(value, parseEdgeId(execEdgeId("n_magic", "missing"))!);
    expect(getIn(cut, ["nodes", "n_magic"])).toEqual({
      config: { mode: "fast", retries: 3 },
      in: { region: [0, 0, 100, 50], target: { $target: "targets/x.target.json" } },
      next: { found: "n_log" },
      type: "acme.vision.magic",
      version: 2,
    });
  });

  test("노드 더하기: in을 채우지 않고 좌표는 정수, plugins는 없을 때만 적는다", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/unknown-keys.graph.json"));
    const out = addNode(value, {
      id: "n_abcdefgh",
      type: "acme.vision.magic",
      version: 3,
      x: -0.4,
      y: 12.5,
      plugin: { id: "acme", version: "1.2.0" },
    });
    expect(getIn(out, ["nodes", "n_abcdefgh"])).toEqual({ type: "acme.vision.magic", version: 3 });
    const at = getIn(out, ["layout", "nodes", "n_abcdefgh"]) as { x: number; y: number };
    expect(at).toEqual({ x: 0, y: 13 });
    expect(Object.is(at.x, -0)).toBe(false);
    expect(getIn(out, ["plugins"])).toEqual({ core: "0.1.0", acme: "1.2.0" });
    expect(getIn(out, ["layout", "x_view"])).toEqual({ zoom: 1.5 });
    expect(getIn(out, ["x_editor"])).toBe(getIn(value, ["x_editor"]));
    // 이미 있는 플러그인 판은 그대로
    const core = addNode(value, { id: "n_x", type: "core.flow.delay", version: 1, x: 0, y: 0, plugin: { id: "core", version: "9" } });
    expect(getIn(core, ["plugins", "core"])).toBe("0.1.0");
    // layout이 없는 그래프에도 더한다
    const bare = addNode({ nodes: {} }, { id: "n_y", type: "t", version: 1, x: 1, y: 2 });
    expect(bare).toEqual({ nodes: { n_y: { type: "t", version: 1 } }, layout: { nodes: { n_y: { x: 1, y: 2 } } } });
    expect(() => addNode(value, { id: "n_pass", type: "t", version: 1, x: 0, y: 0 })).toThrow();
  });

  test("옮기기: 좌표 객체의 다른 키는 그대로, 없는 노드는 무시", () => {
    const value = deepFreeze({
      nodes: { a: { type: "t", version: 1 }, b: { type: "t", version: 1 } },
      layout: { nodes: { a: { x: 0, y: 0, x_pin: true } } },
    });
    const out = moveNodes(value, [
      { id: "a", x: 1.5, y: -2.5 },
      { id: "b", x: 7, y: 8 },
      { id: "없음", x: 0, y: 0 },
    ]);
    expect(getIn(out, ["layout", "nodes"])).toEqual({ a: { x: 2, y: -2, x_pin: true }, b: { x: 7, y: 8 } });
    expect(moveNodes(value, [{ id: "a", x: 0.2, y: -0.2 }])).toBe(value);
    expect(jsonEqual(moveNodes(value, []), value)).toBe(true);
  });
});
