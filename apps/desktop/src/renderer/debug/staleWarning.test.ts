// 재개 경고 (M3 계획 2.9 "재개 경고"): runner 스텝 입력 검사(2.4)와 같은 예외로 그래프 모양을 본다
import { describe, expect, test } from "vitest";
import { indexNodeTypes } from "../graph/mapping";
import type { GraphValue } from "../graph/model";
import { staleInputs, staleWarningText } from "./staleWarning";

const types = indexNodeTypes([
  {
    nodes: [
      { type: "core.graph.entry", engine: "graph_entry" },
      { type: "core.ocr.read", effects: ["capture"] },
      { type: "core.image.wait", effects: ["capture"] },
      { type: "core.logic.compare", pure: true },
      { type: "core.text.format", pure: true },
      { type: "core.flow.branch", inputs: { condition: { type: "bool" } } },
      { type: "core.assert.compare", inputs: { a: { type: "any" }, b: { type: "any" } } },
      { type: "core.input.click", effects: ["input"], inputs: { match: { type: "match" }, point: { type: "point" } } },
      { type: "core.input.type_text", effects: ["capture", "input"], inputs: { text: { type: "string|secret" } } },
      { type: "core.log.message", inputs: { text: { type: "string|secret" } } },
    ],
  },
]);

const graph: GraphValue = {
  nodes: {
    n_entry: { type: "core.graph.entry", next: { start: "n_read" } },
    n_read: { type: "core.ocr.read", title: "오류 문구 읽기" },
    n_wait: { type: "core.image.wait", title: "타이틀 대기" },
    n_cmp: { type: "core.logic.compare", in: { a: { $link: "n_read.text" }, b: "ok" } },
    n_fmt: { type: "core.text.format", in: { values: { v: { $link: "n_entry.server" } } } },
    // OCR 글자 → 순수 비교 → 분기: 재개하면 오래된 값
    n_branch: { type: "core.flow.branch", title: "문구 확인", in: { condition: { $link: "n_cmp.result" } } },
    // 관측과 무관한 값(서브그래프 입력 → 글자 만들기)
    n_branch2: { type: "core.flow.branch", in: { condition: { $link: "n_fmt.text" } } },
    // 값 안쪽 경로·원소에서 오는 관측값
    n_assert: { type: "core.assert.compare", in: { a: { $link: "n_wait.match.point" }, b: [{ $link: "n_read.text" }] } },
    // input 노드의 Match는 입력 서비스가 다시 찾는다
    n_click: { type: "core.input.click", in: { match: { $link: "n_wait.match" } } },
    // input 노드라도 Match가 아닌 관측값(OCR 글자를 입력)은 실패한다
    n_type: { type: "core.input.type_text", title: "글자 입력", in: { text: { $link: "n_read.text" } } },
    // 기록·옮기기 노드는 예외
    n_log: { type: "core.log.message", in: { text: { $link: "n_read.text" } } },
  },
};

describe("재개 경고", () => {
  test("test_stale_warning_follows_pure_nodes_to_observation", () => {
    expect(staleInputs(graph, "n_branch", types)).toEqual([{ pin: "condition", node: "n_read", output: "text" }]);
    expect(staleInputs(graph, "n_assert", types)).toEqual([
      { pin: "a", node: "n_wait", output: "match" },
      { pin: "b", node: "n_read", output: "text" },
    ]);
    expect(staleInputs(graph, "n_type", types)).toEqual([{ pin: "text", node: "n_read", output: "text" }]);
  });

  test("test_stale_warning_exceptions_match_runner", () => {
    expect(staleInputs(graph, "n_branch2", types)).toEqual([]);
    expect(staleInputs(graph, "n_click", types)).toEqual([]);
    expect(staleInputs(graph, "n_log", types)).toEqual([]);
    expect(staleInputs(graph, "n_entry", types)).toEqual([]);
    expect(staleInputs(graph, "n_gone", types)).toEqual([]);
  });

  test("문구", () => {
    const titles: Record<string, string> = { n_read: "오류 문구 읽기" };
    expect(staleWarningText("문구 확인", staleInputs(graph, "n_branch", types), (id) => titles[id] ?? id)).toBe(
      "재개하면 '문구 확인'는 멈추기 전 화면 값(오류 문구 읽기.text)을 쓸 수 없어 실패합니다",
    );
  });
});
