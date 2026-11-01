// 실행·정지 활성 조건: 툴바·메뉴 "실행"·F5가 같은 함수를 쓴다 (M2 T14 조율자 결정)
import { describe, expect, test } from "vitest";
import { runAvailability, type RunAvailabilityInput } from "./commands";

const TEST_TAB = { path: "tests/a.graph.json", kind: "graph", graphKind: "test" } as const;
const idle: RunAvailabilityInput = { tab: TEST_TAB, connected: true, running: false, starting: null };

describe("runAvailability", () => {
  test("test_idle_test_graph_can_run_not_stop", () => {
    expect(runAvailability(idle)).toEqual({ path: TEST_TAB.path, canRun: true, canStop: false, runTitle: "실행 (F5)" });
  });

  test("test_running_can_stop_not_run", () => {
    const a = runAvailability({ ...idle, running: true });
    expect([a.canRun, a.canStop, a.runTitle]).toEqual([false, true, "실행이 끝나면 다시 실행할 수 있어요"]);
  });

  test("test_starting_or_disconnected_cannot_run", () => {
    expect(runAvailability({ ...idle, starting: TEST_TAB.path }).canRun).toBe(false);
    expect(runAvailability({ ...idle, connected: false }).canRun).toBe(false);
  });

  test("test_subgraph_target_or_no_tab_not_runnable", () => {
    const sub = runAvailability({ ...idle, tab: { path: "subgraphs/s.graph.json", kind: "graph", graphKind: "subgraph" } });
    expect([sub.path, sub.canRun, sub.runTitle]).toEqual([null, false, "서브그래프는 테스트에서 불러 실행해요"]);
    const target = runAvailability({ ...idle, tab: { path: "targets/t.target.json", kind: "target" } });
    expect([target.path, target.canRun, target.runTitle]).toEqual([null, false, "그래프 탭에서 실행해요"]);
    expect(runAvailability({ ...idle, tab: undefined }).canRun).toBe(false);
  });

  test("test_stop_follows_running_regardless_of_tab", () => {
    // 다른 탭(TARGET)을 보고 있어도 진행 중인 실행은 멈출 수 있다 (툴바 ■와 같음)
    expect(runAvailability({ ...idle, tab: { path: "targets/t.target.json", kind: "target" }, running: true }).canStop).toBe(true);
  });
});
