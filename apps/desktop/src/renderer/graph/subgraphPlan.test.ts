// 서브그래프 호출 노드 → 열 탭 (다듬기 P1-B, 사용자 요청 ⑧)
import { describe, expect, test } from "vitest";
import type { TreeEntry } from "../explorer/tree";
import { callTargetOf, planSubgraph, snapshotRoot } from "./subgraphPlan";

const ENTRIES: TreeEntry[] = [
  { path: "subgraphs", type: "dir" },
  { path: "subgraphs/enter_world.graph.json", type: "file", kind: "graph", graph_kind: "subgraph" },
  { path: "subgraphs/broken.graph.json", type: "file", kind: "graph", problem: "읽을 수 없다" },
  { path: "tests/inventory_open.graph.json", type: "file", kind: "graph", graph_kind: "test" },
  { path: "screens/lobby.screen.json", type: "file", kind: "screen" },
  { path: "tests/odd.graph.json.txt", type: "file", kind: "other" },
];

const WS_TAB = { path: "tests/inventory_open.graph.json", title: "inventory_open" };

describe("callTargetOf", () => {
  const value = {
    kind: "test",
    nodes: {
      call: { type: "core.graph.call", version: 1, config: { graph: "subgraphs/enter_world.graph.json" } },
      empty: { type: "core.graph.call", version: 1 },
      number: { type: "core.graph.call", version: 1, config: { graph: 3 } },
      wait: { type: "core.flow.wait", version: 1, config: { graph: "x.graph.json" } },
    },
  };
  test("호출 노드면 config.graph, 아니면 null", () => {
    expect(callTargetOf(value, "call")).toBe("subgraphs/enter_world.graph.json");
    expect(callTargetOf(value, "empty")).toBe("");
    expect(callTargetOf(value, "number")).toBe("");
    expect(callTargetOf(value, "wait")).toBeNull();
    expect(callTargetOf(value, "none")).toBeNull();
    expect(callTargetOf(null, "call")).toBeNull();
  });
});

describe("planSubgraph", () => {
  test("탐색기 목록의 서브그래프는 그 종류로 바로 연다", () => {
    expect(planSubgraph("subgraphs/enter_world.graph.json", WS_TAB, ENTRIES)).toEqual({
      ok: true,
      open: "tab",
      path: "subgraphs/enter_world.graph.json",
      graphKind: "subgraph",
    });
    // 테스트 그래프를 부르는 일은 없지만 열기는 그대로 한다. 읽을 수 없는 그래프도 탭에서 오류를 보인다
    expect(planSubgraph("tests/inventory_open.graph.json", WS_TAB, ENTRIES)).toMatchObject({ ok: true, graphKind: "test" });
    expect(planSubgraph("subgraphs/broken.graph.json", WS_TAB, ENTRIES)).toMatchObject({ ok: true, graphKind: null });
  });

  test("대소문자가 다르면 목록의 실제 이름으로 연다", () => {
    expect(planSubgraph("Subgraphs/Enter_World.graph.json", WS_TAB, ENTRIES)).toMatchObject({
      ok: true,
      open: "tab",
      path: "subgraphs/enter_world.graph.json",
    });
  });

  test("목록 밖이면 읽어 보고 연다", () => {
    expect(planSubgraph("lib/shared.graph.json", WS_TAB, ENTRIES)).toEqual({
      ok: true,
      open: "probe",
      path: "lib/shared.graph.json",
      snapshot: null,
    });
    expect(planSubgraph("subgraphs/none.graph.json", WS_TAB, ENTRIES)).toMatchObject({ open: "probe" });
  });

  test.each([
    ["", "empty"],
    ["   ", "empty"],
    ["/subgraphs/a.graph.json", "bad_path"],
    ["subgraphs\\a.graph.json", "bad_path"],
    ["C:/a.graph.json", "bad_path"],
    ["subgraphs/../a.graph.json", "bad_path"],
    ["./a.graph.json", "bad_path"],
    ["subgraphs//a.graph.json", "bad_path"],
    ["screens/lobby.screen.json", "not_graph"],
    ["subgraphs/enter_world", "not_graph"],
  ])("%j → %s", (target, reason) => {
    expect(planSubgraph(target, WS_TAB, ENTRIES)).toEqual({ ok: false, reason, target });
  });

  test("같은 이름의 폴더는 파일 항목이 아니다: 읽어 보고 daemon 답으로 알린다", () => {
    const entries: TreeEntry[] = [{ path: "tests/x.graph.json", type: "dir" }];
    expect(planSubgraph("tests/x.graph.json", WS_TAB, entries)).toMatchObject({ open: "probe" });
  });

  test("실행 스냅샷 탭에서는 같은 스냅샷 안의 서브그래프", () => {
    const from = {
      path: "runs/20261103-0930-ab12cd34/snapshot/tests/inventory_open.graph.json",
      title: "inventory_open · #ab12",
      runId: "ab12cd34",
      snapshot: true,
    };
    expect(planSubgraph("subgraphs/enter_world.graph.json", from, ENTRIES)).toEqual({
      ok: true,
      open: "probe",
      path: "runs/20261103-0930-ab12cd34/snapshot/subgraphs/enter_world.graph.json",
      snapshot: { runId: "ab12cd34", shortId: "ab12" },
    });
    expect(planSubgraph("../x.graph.json", from, ENTRIES)).toMatchObject({ ok: false, reason: "bad_path" });
  });

  test("snapshotRoot", () => {
    expect(snapshotRoot("runs/r1/snapshot/tests/a.graph.json")).toBe("runs/r1/snapshot");
    expect(snapshotRoot("tests/a.graph.json")).toBeNull();
    expect(snapshotRoot("runs/r1/other/tests/a.graph.json")).toBeNull();
  });
});
