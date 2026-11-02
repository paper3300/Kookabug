// "에디터에서 재현" 결과 (M3 계획 2.10, T11 검수 4): 브레이크포인트 저장이 끝나고 daemon이 확인한 뒤에만 준비 완료
import { afterEach, describe, expect, test } from "vitest";
import { breakpointModel } from "../debug/breakpoints";
import type { RpcCall } from "../rpc/client";
import { index, step } from "./fixtures.testutil";
import { reproduce, reproduceNotice } from "./reproduce";
import { RunIndexModel } from "./runIndexStore";

interface Save {
  breakpoints: unknown;
  resolve(v: unknown): void;
  reject(e: unknown): void;
}

const saves: Save[] = [];
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  on: () => () => {},
  rpc: (method: string, params: Record<string, unknown>) => {
    if (method === "graph.open") {
      return Promise.resolve({ doc_id: "doc", value: { nodes: { n_s1: { type: "core.test.fail", in: {}, next: {} } } } });
    }
    if (method === "graph.close") return Promise.resolve({});
    if (method === "debug.breakpoints.set") {
      return new Promise((resolve, reject) => saves.push({ breakpoints: params.breakpoints, resolve, reject }));
    }
    return Promise.reject(new Error(method));
  },
};

const tick = () => new Promise((r) => setTimeout(r, 0));

async function failedRun() {
  const call = (async (method: string) => {
    if (method === "run.index") return index([step("s1", { status: "fail" })], { failure_chain: ["s1"] });
    if (method === "run.step") return { step: step("s1"), events: [], thumbnail: null, ocr_text: null, run_dir: "runs/r" };
    throw new Error("no graph");
  }) as unknown as RpcCall;
  const model = new RunIndexModel(call);
  await model.open("ab12cd34");
  return model.get("ab12cd34")!;
}

describe("reproduce", () => {
  afterEach(() => {
    saves.length = 0;
    breakpointModel.reset();
  });

  test("test_reproduce_waits_for_breakpoint_save_before_ready", async () => {
    const view = await failedRun();
    let done = false;
    const running = reproduce(view).then((r) => {
      done = true;
      return r;
    });
    for (let i = 0; i < 5 && saves.length === 0; i++) await tick();
    expect(saves).toHaveLength(1);
    await tick();
    // 저장 응답 전에는 준비 완료로 끝나지 않는다
    expect(done).toBe(false);
    saves[0].resolve({ breakpoints: saves[0].breakpoints });
    const result = await running;
    expect(result).toMatchObject({ ok: true, breakpoint: true, breakpointFailed: false });
    expect(breakpointModel.confirmedList).toEqual([{ graph: "tests/t.graph.json", node: "n_s1" }]);
    expect(reproduceNotice(result, "실패")?.tone).toBe("info");
  });

  test("test_reproduce_reports_failed_breakpoint_save", async () => {
    const view = await failedRun();
    const running = reproduce(view);
    for (let i = 0; i < 5 && saves.length === 0; i++) await tick();
    saves[0].reject(new Error("disk write rejected"));
    const result = await running;
    expect(result).toMatchObject({ ok: true, breakpoint: false, breakpointFailed: true });
    expect(breakpointModel.list).toEqual([]);
    const notice = reproduceNotice(result, "실패")!;
    expect(notice.tone).toBe("warn");
    expect(notice.text).toContain("'실패'에 브레이크포인트를 저장하지 못했어요");
    expect(notice.text).not.toContain("'실패'에 브레이크포인트 ·");
  });
});
