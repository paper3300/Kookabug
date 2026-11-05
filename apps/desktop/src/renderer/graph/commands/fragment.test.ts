// 녹화 조각 넣기 (M4 계획 T10 완료 기준 fragment.test.ts)
import { describe, expect, test } from "vitest";
import { deepFreeze } from "../corpus.testutil";
import { EMPTY_HISTORY, record, undo } from "../history";
import { NODE_ID_PATTERN } from "../ids";
import type { GraphValue } from "../model";
import { getIn } from "../valueOps";
import { FragmentInsertError, insertExits, insertFragment, type Fragment } from "./fragment";

/** 정해진 바이트를 차례로 내는 가짜 무작위 (겹침 다시 뽑기 검사) */
function bytesFrom(seq: number[][]): (n: number) => Uint8Array {
  let i = 0;
  return (n) => {
    const b = seq[Math.min(i++, seq.length - 1)];
    return Uint8Array.from({ length: n }, (_, k) => b[k % b.length]);
  };
}

const CHAIN_GRAPH = deepFreeze({
  format: "kookabug.graph/0",
  kind: "test",
  plugins: { core: "0.1.0" },
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_click" } },
    n_click: { type: "core.image.click", version: 1, in: { target: { $target: "targets/a.target.json" } }, next: { clicked: "n_check" } },
    n_check: { type: "core.assert.visible", version: 1, next: { ok: "n_pass" }, x_keep: { a: 1 } },
    n_pass: { type: "core.test.pass", version: 1 },
  },
  layout: { nodes: { n_entry: { x: 0, y: 0 }, n_click: { x: 260, y: 0 }, n_check: { x: 520, y: 0, w: 9 } }, x_view: 3 },
  x_top: "그대로",
}) as GraphValue;

function insertFrag(count: number, withLink = false): Fragment {
  const nodes: Fragment["nodes"][number][] = [];
  for (let i = 1; i <= count; i++) {
    const last = i === count;
    nodes.push({
      local_id: `r${i}`,
      type: i === 1 ? "core.image.wait" : "core.input.key",
      version: 1,
      title: `노드 ${i}`,
      in: withLink && i === 2 ? { keys: "enter", deep: [{ a: { $link: "r1.match" } }, { $literal: { $link: "r1.match" } }] } : { keys: "a" },
      ...(last ? {} : { next: { [i === 1 ? "found" : "done"]: `r${i + 1}` } }),
    } as Fragment["nodes"][number]);
  }
  return {
    mode: "insert",
    nodes: nodes as Fragment["nodes"],
    chain: nodes.map((n) => n.local_id) as Fragment["chain"],
    open_end: { node: `r${count}`, exit: "done" },
    warnings: [],
  };
}

describe("insertFragment", () => {
  test("test_insert_after_selected_rewires_ok_exit", () => {
    const { value, nodes } = insertFragment(CHAIN_GRAPH, insertFrag(2), { after: { node: "n_click", exit: "clicked" } });
    // 고른 출구 → 조각 첫 노드, 조각 열린 끝 → 원래 다음 노드
    expect(getIn(value, ["nodes", "n_click", "next", "clicked"])).toBe(nodes[0]);
    expect(getIn(value, ["nodes", nodes[0], "next", "found"])).toBe(nodes[1]);
    expect(getIn(value, ["nodes", nodes[1], "next", "done"])).toBe("n_check");
    // 다른 노드·모르는 키·배치는 그대로
    expect(getIn(value, ["nodes", "n_check"])).toBe(getIn(CHAIN_GRAPH, ["nodes", "n_check"]));
    expect(getIn(value, ["nodes", "n_entry"])).toBe(getIn(CHAIN_GRAPH, ["nodes", "n_entry"]));
    expect(getIn(value, ["layout", "nodes", "n_check"])).toEqual({ x: 520, y: 0, w: 9 });
    expect(value.x_top).toBe("그대로");
    expect(getIn(value, ["layout", "x_view"])).toBe(3);
    // 넣은 노드는 제목·in을 그대로 싣고 고른 노드 오른쪽 아래부터
    expect(getIn(value, ["nodes", nodes[0]])).toMatchObject({ type: "core.image.wait", version: 1, title: "노드 1" });
    expect(getIn(value, ["layout", "nodes", nodes[0]])).toEqual({ x: 520, y: 180 });
    expect(getIn(value, ["layout", "nodes", nodes[1]])).toEqual({ x: 780, y: 180 });
  });

  test("test_new_ids_unique_with_existing_and_groups", () => {
    const graph = deepFreeze({
      ...CHAIN_GRAPH,
      layout: { nodes: {}, collapsed: { n_aaaaaaaa: { nodes: [], x: 0, y: 0 } }, comments: { n_bbbbbbbb: { rect: [0, 0, 1, 1], text: "" } } },
    }) as GraphValue;
    // 첫 두 번은 그룹·주석 ID와 겹치는 바이트(0 = 'a', 1 = 'b'), 그 뒤는 새 ID
    const random = bytesFrom([[0], [1], [2], [3], [4]]);
    const { nodes } = insertFragment(graph, insertFrag(3), { random });
    expect(new Set(nodes).size).toBe(3);
    for (const id of nodes) {
      expect(id).toMatch(NODE_ID_PATTERN);
      expect(["n_aaaaaaaa", "n_bbbbbbbb", "n_entry", "n_click", "n_check", "n_pass"]).not.toContain(id);
    }
  });

  test("test_links_remapped_recursively", () => {
    const { value, nodes } = insertFragment(CHAIN_GRAPH, insertFrag(2, true), { after: { node: "n_click", exit: "clicked" } });
    const inputs = getIn(value, ["nodes", nodes[1], "in"]);
    expect(inputs).toEqual({
      keys: "enter",
      // 배열·객체 안쪽 $link는 새 ID로, $literal 안은 값이라 그대로
      deep: [{ a: { $link: `${nodes[0]}.match` } }, { $literal: { $link: "r1.match" } }],
    });
  });

  test("test_terminal_selected_rejected", () => {
    expect(() => insertFragment(CHAIN_GRAPH, insertFrag(1), { after: { node: "n_pass", exit: "ok" } })).toThrow(FragmentInsertError);
    expect(insertExits("core.test.pass", [])).toEqual({ kind: "terminal" });
    expect(insertExits("core.log.message", [])).toEqual({ kind: "terminal" });
    // 없는 노드도 거부 (값은 그대로)
    expect(() => insertFragment(CHAIN_GRAPH, insertFrag(1), { after: { node: "n_none", exit: "ok" } })).toThrow("넣을 자리의 노드가 없어요");
  });

  test("test_multi_ok_exit_uses_chosen_exit", () => {
    const graph = deepFreeze({
      ...CHAIN_GRAPH,
      nodes: {
        ...(CHAIN_GRAPH.nodes as object),
        n_any: { type: "core.image.wait_any", version: 1, next: { a: "n_check", b: "n_pass", timeout: "n_pass" } },
      },
    }) as GraphValue;
    expect(
      insertExits("core.image.wait_any", [
        { name: "a", kind: "ok", outputs: [] },
        { name: "b", kind: "ok", outputs: [] },
        { name: "timeout", kind: "fail", outputs: [] },
      ]),
    ).toEqual({ kind: "many", exits: ["a", "b"] });
    const { value, nodes } = insertFragment(graph, insertFrag(1), { after: { node: "n_any", exit: "b" } });
    expect(getIn(value, ["nodes", "n_any", "next"])).toEqual({ a: "n_check", b: nodes[0], timeout: "n_pass" });
    expect(getIn(value, ["nodes", nodes[0], "next", "done"])).toBe("n_pass");
  });

  test("test_single_undo_entry", () => {
    // 렌더러 문서는 명령 하나 = 기록 하나 (applyEdit). 한 번 되돌리면 넣기 전 값과 같다
    const { value } = insertFragment(CHAIN_GRAPH, insertFrag(4), { after: { node: "n_click", exit: "clicked" } });
    const history = record(EMPTY_HISTORY, CHAIN_GRAPH);
    expect(history.past).toHaveLength(1);
    const back = undo(history, value);
    expect(back?.value).toBe(CHAIN_GRAPH);
  });

  test("test_layout_rows_of_six", () => {
    const { value, nodes } = insertFragment(CHAIN_GRAPH, insertFrag(8), { at: { x: 100, y: 50 } });
    const at = nodes.map((id) => getIn(value, ["layout", "nodes", id]));
    expect(at[0]).toEqual({ x: 100, y: 50 });
    expect(at[5]).toEqual({ x: 100 + 5 * 260, y: 50 });
    expect(at[6]).toEqual({ x: 100, y: 230 });
    expect(at[7]).toEqual({ x: 360, y: 230 });
    // 이어지지 않은 사슬: 기존 노드의 next는 그대로
    expect(getIn(value, ["nodes", "n_click", "next"])).toEqual({ clicked: "n_check" });
  });

  test("새 테스트: 시작 노드 뒤에 넣고 없는 플러그인만 더한다", () => {
    const empty = deepFreeze({
      format: "kookabug.graph/0",
      kind: "test",
      layout: { nodes: { n_entry: { x: 0, y: 0 } } },
      nodes: { n_entry: { type: "core.graph.entry", version: 1 } },
      plugins: { core: "0.1.0" },
    }) as GraphValue;
    const frag: Fragment = { ...insertFrag(2), mode: "new_test" };
    delete frag.open_end;
    const { value, nodes } = insertFragment(empty, frag, { after: { node: "n_entry", exit: "start" }, plugins: { core: "9.9.9", ext: "1.0.0" } });
    expect(getIn(value, ["nodes", "n_entry", "next"])).toEqual({ start: nodes[0] });
    expect(getIn(value, ["plugins"])).toEqual({ core: "0.1.0" });
    expect(getIn(value, ["layout", "nodes", nodes[0]])).toEqual({ x: 260, y: 180 });
  });

  test("열린 끝이 없는 조각을 사슬 중간에 넣지 않는다 (값 그대로)", () => {
    const frag: Fragment = { ...insertFrag(1), mode: "new_test" };
    delete frag.open_end;
    expect(() => insertFragment(CHAIN_GRAPH, frag, { after: { node: "n_click", exit: "clicked" } })).toThrow(FragmentInsertError);
  });
});
