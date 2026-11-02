// 실패 노드로 바로 이동 (M3 계획 T10 완료 기준, 2.10)
import { describe, expect, test } from "vitest";
import { index, step } from "./fixtures.testutil";
import { planJump, type ChildLoader } from "./failureJump";
import type { StepNode } from "./runIndexStore";

/** 부모(·회차) → 그 아래 스텝. 부른 것을 적는다 */
function loader(children: Record<string, StepNode[]>, calls: string[] = []): ChildLoader {
  return async (parent, iteration) => {
    const key = iteration === null ? parent.step : `${parent.step}#${iteration}`;
    calls.push(key);
    return children[key] ?? [];
  };
}

describe("planJump", () => {
  test("test_failure_chain_expands_and_selects_failure_step", async () => {
    // 테스트 → 반복(3회, 마지막 회차 실패) → 호출 → 서브그래프 안 대기 실패
    const loop = step("s2", {
      node: "n_loop",
      exit: null,
      status: "fail",
      children: 9,
      iterations: [
        { iteration: 0, t_start: "2026-11-02T01:00:01.000Z", duration_ms: 50, status: "success", steps: 4 },
        { iteration: 1, t_start: "2026-11-02T01:00:02.000Z", duration_ms: 50, status: "success", steps: 4 },
        { iteration: 2, t_start: "2026-11-02T01:00:03.000Z", duration_ms: 900, status: "fail", steps: 3 },
      ],
    });
    const call = step("s11", { parent: "s2", iteration: 2, node: "n_call", calls: "subgraphs/s.graph.json", status: "fail", exit: null, children: 3 });
    const wait = step("s13", {
      parent: "s11",
      node: "n_wait",
      graph: "subgraphs/s.graph.json",
      path: ["n_loop", "n_call", "n_wait"],
      status: "fail",
      exit: "timeout",
      evidence: true,
    });
    const idx = index([step("s1", { node: "n_entry" }), loop, call, wait], { failure_chain: ["s2", "s11", "s13"] });
    const calls: string[] = [];
    const plan = await planJump(idx, loader({}, calls));
    expect(plan.expand).toEqual([
      { step: "s2", iteration: 2 },
      { step: "s11", iteration: null },
    ]);
    expect(plan.select).toBe("s13");
    // 사슬은 색인만으로 정한다 (쪽을 읽지 않는다)
    expect(calls).toEqual([]);
  });

  test("test_aborted_run_selects_last_open_step", async () => {
    // runner가 죽은 실행: 실패 스텝이 없고, 마지막 호출 안 마지막 스텝이 끝나지 않았다
    const call = step("s3", { node: "n_call", calls: "subgraphs/s.graph.json", status: "aborted", exit: null, children: 3, t_end: null, duration_ms: null });
    const inner = [
      step("s4", { parent: "s3", node: "n_entry", graph: "subgraphs/s.graph.json" }),
      step("s5", { parent: "s3", node: "n_click", graph: "subgraphs/s.graph.json" }),
      step("s6", { parent: "s3", node: "n_wait", graph: "subgraphs/s.graph.json", status: "aborted", exit: null, t_end: null, duration_ms: null }),
    ];
    const idx = index([step("s1"), step("s2", { status: "aborted", exit: null }), call], {
      run: { graph: "tests/t.graph.json", verdict: "error", failure_step: null },
    });
    const calls: string[] = [];
    const plan = await planJump(idx, loader({ s3: inner }, calls));
    // 끝나지 않은 최상위 스텝 중 마지막(s3) → 그 안 마지막 끝나지 않은 스텝
    expect(plan).toEqual({ expand: [{ step: "s3", iteration: null }], select: "s6" });
    expect(calls).toEqual(["s3"]);

    // 반복 안에서 중단: 끝나지 않은 회차를 열고 그 안을 고른다
    const loop = step("s2", {
      node: "n_loop",
      status: "aborted",
      exit: null,
      children: 5,
      iterations: [
        { iteration: 0, t_start: "2026-11-02T01:00:01.000Z", duration_ms: 50, status: "success", steps: 3 },
        { iteration: 1, t_start: "2026-11-02T01:00:02.000Z", duration_ms: null, status: "aborted", steps: 2 },
      ],
    });
    const body = [step("s9", { parent: "s2", iteration: 1 }), step("s10", { parent: "s2", iteration: 1, status: "aborted", exit: null })];
    const plan2 = await planJump(index([step("s1"), loop]), loader({ "s2#1": body }));
    expect(plan2).toEqual({ expand: [{ step: "s2", iteration: 1 }], select: "s10" });

    // 다 끝난 성공 실행은 아무것도 고르지 않는다
    expect(await planJump(index([step("s1"), step("s2")]), loader({}))).toEqual({ expand: [], select: null });
  });

  test("test_input_eval_failure_step_selected", async () => {
    // 2차 N1: 입력 계산 실패(any → string type_mismatch)도 그 스텝의 step.start·step.end가 있어 실패 사슬 끝이다.
    // 노드를 부르지 않아 증거·출구가 없다
    const call = step("s2", { node: "n_call", calls: "subgraphs/s.graph.json", status: "error", exit: null, children: 2 });
    const bad = step("s4", {
      parent: "s2",
      node: "n_type",
      graph: "subgraphs/s.graph.json",
      path: ["n_call", "n_type"],
      status: "error",
      exit: null,
      duration_ms: 0,
      message: "type_mismatch: 입력 text에 string이 아닌 값",
    });
    const idx = index([step("s1"), call, bad], {
      failure_chain: ["s2", "s4"],
      run: { graph: "tests/t.graph.json", verdict: "error", failure_step: "s4" },
    });
    const plan = await planJump(idx, loader({}));
    expect(plan.select).toBe("s4");
    expect(plan.expand).toEqual([{ step: "s2", iteration: null }]);
  });
});
