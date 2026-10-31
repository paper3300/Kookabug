// 문제 → 노드 (M2 계획 T8 완료 기준 highlight-free)
import { describe, expect, test } from "vitest";
import type { Diagnostic } from "../graph/model";
import { problemNode, sortProblems } from "./locate";

const ids = new Set(["n_a", "n_b/x", "n_c"]);
const diag = (d: Partial<Diagnostic>): Diagnostic => ({ severity: "error", code: "c", message: "m", ...d });

describe("문제 → 노드", () => {
  test("test_problem_to_node_by_pointer_and_node", () => {
    const doc = "tests/a.graph.json";
    expect(problemNode(diag({ node: "n_a" }), doc, ids)).toBe("n_a");
    expect(problemNode(diag({ node: "n_a", pointer: "/nodes/n_c/in" }), doc, ids)).toBe("n_a");
    // node가 없거나 이 문서에 없는 노드면 pointer로
    expect(problemNode(diag({ node: "n_zz", pointer: "/nodes/n_c/in/target" }), doc, ids)).toBe("n_c");
    expect(problemNode(diag({ pointer: "/layout/nodes/n_a" }), doc, ids)).toBe("n_a");
    expect(problemNode(diag({ pointer: "/nodes/n_b~1x/next" }), doc, ids)).toBe("n_b/x");
    expect(problemNode(diag({ pointer: "/meta/title" }), doc, ids)).toBeNull();
    expect(problemNode(diag({ pointer: "/nodes/n_none" }), doc, ids)).toBeNull();
    expect(problemNode(diag({ pointer: "nodes/n_a" }), doc, ids)).toBeNull();
    // 다른 파일의 진단은 이 문서의 노드가 아니다
    expect(problemNode(diag({ file: "subgraphs/s.graph.json", node: "n_a" }), doc, ids)).toBeNull();
    expect(problemNode(diag({ file: doc, node: "n_a" }), doc, ids)).toBe("n_a");
  });

  test("오류가 경고보다 먼저, 같은 수준은 받은 순서", () => {
    const items = [
      { diag: diag({ severity: "warning", code: "w1" }) },
      { diag: diag({ code: "e1" }) },
      { diag: diag({ severity: "warning", code: "w2" }) },
      { diag: diag({ code: "e2" }) },
    ];
    expect(sortProblems(items).map((i) => i.diag.code)).toEqual(["e1", "e2", "w1", "w2"]);
  });
});
