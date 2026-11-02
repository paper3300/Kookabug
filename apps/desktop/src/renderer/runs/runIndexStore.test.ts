// 기록 뷰어 색인 상태 (M3 계획 2.7·2.10, T10 완료 기준)
import { describe, expect, test } from "vitest";
import type { RpcCall } from "../rpc/client";
import { index, step } from "./fixtures.testutil";
import { evidenceCells } from "./evidenceCells";
import { childrenOf, detailComplete, mergeSteps, RunIndexModel, topSteps, type RunIndex, type StepDetail } from "./runIndexStore";

interface Pending {
  method: string;
  params: Record<string, unknown>;
  resolve(value: unknown): void;
  reject(err: unknown): void;
}

/** 응답을 손으로 돌려주는 가짜 daemon. graph.open(제목)은 바로 거절하고, autoStep이면 run.step은 바로 답한다 */
function fakeDaemon(autoStep = false) {
  const pending: Pending[] = [];
  const call = ((method: string, params: Record<string, unknown>) => {
    if (method === "graph.open" || method === "graph.close") return Promise.reject(new Error("no snapshot"));
    if (autoStep && method === "run.step") {
      return Promise.resolve({ events: [], ocr_text: null, run_dir: "runs/r", step: step(String(params.step)), thumbnail: null });
    }
    return new Promise((resolve, reject) => pending.push({ method, params, resolve, reject }));
  }) as unknown as RpcCall;
  const take = (method: string): Pending => {
    const i = pending.findIndex((p) => p.method === method);
    if (i < 0) throw new Error(`${method} 요청이 없다 (${pending.map((p) => p.method).join(", ")})`);
    return pending.splice(i, 1)[0];
  };
  return { call, pending, take };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

/** 타이머를 손으로 돌린다 */
function manualTimers() {
  const queue: (() => void)[] = [];
  const delay = (fn: () => void) => {
    queue.push(fn);
    return 0 as unknown as ReturnType<typeof setTimeout>;
  };
  const run = () => {
    for (const fn of queue.splice(0)) fn();
  };
  return { delay, run, queue };
}

describe("RunIndexModel", () => {
  test("test_live_events_extend_timeline_in_seq_order", async () => {
    const d = fakeDaemon(true);
    const timers = manualTimers();
    const model = new RunIndexModel(d.call, timers.delay);
    const live = (lastSeq: number, ids: string[]): RunIndex =>
      index(
        ids.map((id) => step(id, { status: id === ids[ids.length - 1] ? "running" : "success" })),
        { state: "running", last_seq: lastSeq },
      );

    // 열기: 첫 색인 요청은 아직 답하지 않았다
    const opening = model.open("ab12cd34");
    await flush();
    const first = d.take("run.index");
    // 실행 화면이 seq 10까지 적용했다 → 묶어서 다시 읽기 (타이머)
    model.noteSeq("ab12cd34", 10);
    expect(timers.queue.length).toBe(1);
    timers.run();
    await flush();
    const second = d.take("run.index");
    // 나중 요청(seq 10)이 먼저 오고, 앞 요청(seq 4)이 늦게 온다: 늦은 옛 응답은 쓰지 않는다
    second.resolve(live(10, ["s1", "s2", "s3"]));
    await flush();
    first.resolve(live(4, ["s1"]));
    await opening;
    await flush();
    let view = model.get("ab12cd34")!;
    expect(view.index!.last_seq).toBe(10);
    expect(topSteps(view).map((s) => s.step)).toEqual(["s1", "s2", "s3"]);

    // 다시 읽는 중에 더 온 seq는 끝난 뒤 한 번 더 읽는다
    model.noteSeq("ab12cd34", 14);
    timers.run();
    await flush();
    const third = d.take("run.index");
    model.noteSeq("ab12cd34", 20);
    expect(timers.queue.length).toBe(0);
    third.resolve(live(14, ["s1", "s2", "s3", "s4"]));
    await flush();
    await flush();
    expect(timers.queue.length).toBe(1);
    timers.run();
    await flush();
    d.take("run.index").resolve(live(20, ["s1", "s2", "s3", "s4", "s5"]));
    await flush();
    await flush();
    view = model.get("ab12cd34")!;
    expect(topSteps(view).map((s) => s.step)).toEqual(["s1", "s2", "s3", "s4", "s5"]);
    // 적용한 seq가 색인을 넘지 않으면 다시 읽지 않는다
    model.noteSeq("ab12cd34", 20);
    expect(timers.queue.length).toBe(0);
  });

  test("test_children_paging_merges", async () => {
    const d = fakeDaemon();
    const model = new RunIndexModel(d.call, manualTimers().delay);
    const call = step("s2", { node: "n_call", calls: "subgraphs/s.graph.json", children: 5, status: "fail", exit: null });
    // 실패 사슬로 색인이 이미 아는 안쪽 스텝 (쪽을 읽기 전에도 보인다)
    const failing = step("s9", { parent: "s2", status: "fail", exit: "timeout", graph: "subgraphs/s.graph.json" });
    const opening = model.open("ab12cd34");
    await flush();
    d.take("run.index").resolve(index([step("s1"), call, failing], { failure_chain: ["s2", "s9"] }));
    await flush();
    await flush();
    // 이동이 펼친 부모의 첫 쪽
    const p1 = d.take("run.children");
    expect(p1.params).toMatchObject({ parent: "s2", offset: 0 });
    let view = model.get("ab12cd34")!;
    expect(childrenOf(view, call).map((s) => s.step)).toEqual(["s9"]);
    p1.resolve({ offset: 0, total: 5, steps: [step("s3", { parent: "s2" }), step("s5", { parent: "s2" })] });
    await opening;
    await flush();
    d.take("run.step").resolve({ events: [], ocr_text: null, run_dir: "runs/r", step: failing, thumbnail: null });
    view = model.get("ab12cd34")!;
    expect(view.selected).toBe("s9");
    expect(childrenOf(view, call).map((s) => s.step)).toEqual(["s3", "s5", "s9"]);
    // 다음 쪽: 겹친 스텝(s5)은 새 것으로, step 순으로 합친다 (s10은 s9 뒤 — 글자 순이 아니라 번호 순)
    const more = model.loadChildren("ab12cd34", "s2", null, 2);
    await flush();
    d.take("run.children").resolve({
      offset: 2,
      total: 5,
      steps: [step("s5", { parent: "s2", status: "fail" }), step("s10", { parent: "s2" }), step("s7", { parent: "s2" })],
    });
    await more;
    view = model.get("ab12cd34")!;
    const kids = childrenOf(view, call);
    expect(kids.map((s) => s.step)).toEqual(["s3", "s5", "s7", "s9", "s10"]);
    expect(kids.find((s) => s.step === "s5")?.status).toBe("fail");
    expect(view.pages.get("s2")?.total).toBe(5);
  });

  test("test_selected_running_step_detail_rereads_after_end", async () => {
    // T10 검수 1: 실행 중 고른 스텝이 끝나면 증거(처음·중간·후보)가 든 기록을 다시 읽는다
    let ended = false;
    let reads = 0;
    const call = (async (method: string) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") {
        return index([step("s1", { status: ended ? "fail" : "running", exit: ended ? "timeout" : null, evidence: ended })], {
          state: ended ? "ended" : "running",
          last_seq: ended ? 4 : 1,
          failure_chain: ended ? ["s1"] : [],
        });
      }
      if (method === "run.step") {
        reads++;
        const events = ended
          ? [{ event: "step.end", step: "s1", status: "fail", evidence: { first: "steps/s1_first.png", last: "steps/s1_fail.png" } }]
          : [{ event: "step.start", step: "s1" }];
        return { run_dir: "runs/r", step: step("s1"), events, thumbnail: null, ocr_text: null };
      }
      throw new Error(method);
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    await flush();
    expect(model.get("ab12cd34")!.selected).toBe("s1");
    expect(reads).toBe(1);
    // 끝나기 전 다시 골라도 끝나지 않은 기록은 다시 읽는다
    model.select("ab12cd34", "s1");
    await flush();
    expect(reads).toBe(2);
    ended = true;
    await model.refresh("ab12cd34");
    await flush();
    const detail = model.get("ab12cd34")!.details.get("s1");
    expect(reads).toBe(3);
    expect(detailComplete(detail)).toBe(true);
    expect(evidenceCells(model.get("ab12cd34")!.index!.steps[0], detail as StepDetail).map((c) => c.key)).toEqual(["first", "last"]);
    // 끝난 기록은 다시 골라도 다시 읽지 않는다
    model.select("ab12cd34", "s1");
    await flush();
    expect(reads).toBe(3);
  });

  test("test_late_running_detail_after_end_rereads_final_evidence", async () => {
    // T10 2차 검수: 첫 기록 응답 보류 → 끝난 색인 적용 → 옛(끝나지 않은) 응답 도착 → 다시 고르지 않아도 최종 증거
    let final = false;
    const pending: ((v: unknown) => void)[] = [];
    let reads = 0;
    const done = () => ({
      run_dir: "runs/r",
      step: step("s1", { status: "fail" }),
      events: [{ event: "step.end", step: "s1", status: "fail", evidence: { first: "steps/s1_first.png", mid: "steps/s1_mid.png", last: "steps/s1_fail.png" } }],
      thumbnail: null,
      ocr_text: null,
    });
    const running = () => ({ run_dir: "runs/r", step: step("s1", { status: "running" }), events: [{ event: "step.start", step: "s1" }], thumbnail: null, ocr_text: null });
    const call = (async (method: string) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") {
        return index([step("s1", { status: final ? "fail" : "running", exit: final ? "timeout" : null })], {
          state: final ? "ended" : "running",
          last_seq: final ? 4 : 1,
          failure_chain: final ? ["s1"] : [],
        });
      }
      if (method === "run.step") {
        reads++;
        if (reads === 1) return new Promise((r) => pending.push(r));
        return final ? done() : running();
      }
      throw new Error(method);
    }) as unknown as RpcCall;
    const timers = manualTimers();
    const model = new RunIndexModel(call, timers.delay);
    await model.open("ab12cd34");
    await flush();
    expect(model.get("ab12cd34")!.details.get("s1")).toBe("loading");
    final = true;
    await model.refresh("ab12cd34");
    expect(model.get("ab12cd34")!.index!.state).toBe("ended");
    pending[0](running());
    await flush();
    await flush();
    model.noteSeq("ab12cd34", 4, true);
    await flush();
    const view = model.get("ab12cd34")!;
    expect(reads).toBe(2);
    expect(detailComplete(view.details.get("s1"))).toBe(true);
    expect(evidenceCells(view.index!.steps[0], view.details.get("s1") as StepDetail).map((c) => c.key)).toEqual(["first", "mid", "last"]);

    // 순서가 거꾸로여도(옛 응답이 늦게 와도) 끝난 기록을 덮지 않는다
    let reads2 = 0;
    const hold: ((v: unknown) => void)[] = [];
    let ended2 = false;
    const call2 = (async (method: string) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") return index([step("s1", { status: ended2 ? "fail" : "running" })], { state: ended2 ? "ended" : "running", last_seq: ended2 ? 4 : 1 });
      if (method === "run.step") {
        reads2++;
        return reads2 === 1 ? new Promise((r) => hold.push(r)) : done();
      }
      throw new Error(method);
    }) as unknown as RpcCall;
    const m2 = new RunIndexModel(call2, manualTimers().delay);
    await m2.open("ab12cd34");
    await flush();
    ended2 = true;
    await m2.refresh("ab12cd34");
    // 첫 요청이 끝나지 않아 두 번째는 보내지 않고 기억만 했다. 첫 응답이 이미 끝난 기록이면 더 읽지 않는다
    expect(reads2).toBe(1);
    hold[0](done());
    await flush();
    await flush();
    expect(detailComplete(m2.get("ab12cd34")!.details.get("s1"))).toBe(true);
    expect(reads2).toBe(1);
    // 끝난 기록 뒤에는 고르기·갱신이 다시 읽지 않고, 끝나지 않은 기록으로 덮이지 않는다
    m2.select("ab12cd34", "s1");
    await m2.refresh("ab12cd34");
    await flush();
    expect(reads2).toBe(1);
    expect(detailComplete(m2.get("ab12cd34")!.details.get("s1"))).toBe(true);
  });

  test("test_more_after_tail_page_reads_every_child", async () => {
    // T10 검수 4: 중단 위치를 찾느라 마지막 쪽을 먼저 읽어도 "더 보기"가 그 사이를 빠짐없이 읽는다
    const parent = step("s1", { status: "aborted", exit: null, children: 600, calls: "subgraphs/s.graph.json" });
    const kids = Array.from({ length: 600 }, (_, i) => step(`s${i + 2}`, { parent: "s1", status: i === 599 ? "aborted" : "success" }));
    const call = (async (method: string, params: { offset: number; limit: number }) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") return index([parent]);
      if (method === "run.children") return { steps: kids.slice(params.offset, params.offset + params.limit), total: 600, offset: params.offset };
      if (method === "run.step") return { run_dir: "runs/r", step: kids[599], events: [], thumbnail: null, ocr_text: null };
      throw new Error(method);
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    await flush();
    let page = model.get("ab12cd34")!.pages.get("s1")!;
    expect(model.get("ab12cd34")!.selected).toBe("s601");
    expect([page.steps.length, page.loaded]).toEqual([400, 200]);
    for (let n = 0; n < 5 && page.steps.length < page.total; n++) {
      await model.loadMore("ab12cd34", "s1", null);
      page = model.get("ab12cd34")!.pages.get("s1")!;
    }
    expect([page.steps.length, page.loaded]).toEqual([600, 600]);
    expect(childrenOf(model.get("ab12cd34")!, parent).map((s) => s.step)).toEqual(kids.map((s) => s.step));
  });

  test("test_reopen_after_close_reloads_titles", async () => {
    // T10 검수 5: 탭을 닫았다 다시 열면 제목을 다시 읽는다. 닫기 전 요청의 늦은 응답은 새 보기에 쓰지 않는다
    let reads = 0;
    const late: ((v: unknown) => void)[] = [];
    let hold = false;
    const call = (async (method: string) => {
      if (method === "run.index") return index([step("s1")]);
      if (method === "graph.open") {
        reads++;
        const value = { doc_id: "d", value: { meta: { title: `제목 ${reads}` }, nodes: { n_s1: { title: "노드" } } } };
        if (hold) return new Promise((r) => late.push(() => r(value)));
        return value;
      }
      if (method === "graph.close") return {};
      if (method === "run.step") return { run_dir: "runs/r", step: step("s1"), events: [], thumbnail: null, ocr_text: null };
      throw new Error(method);
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    await flush();
    expect(model.get("ab12cd34")!.testTitle).toBe("제목 1");
    model.close("ab12cd34");
    await model.open("ab12cd34");
    await flush();
    expect(model.get("ab12cd34")!.testTitle).toBe("제목 2");
    expect(model.get("ab12cd34")!.nodes.get("tests/t.graph.json")?.get("n_s1")?.title).toBe("노드");
    // 늦은 응답: 닫힌 보기의 제목 요청이 다시 연 보기보다 늦게 와도 새 보기를 덮지 않는다
    model.close("ab12cd34");
    hold = true;
    await model.open("ab12cd34");
    await flush();
    model.close("ab12cd34");
    hold = false;
    await model.open("ab12cd34");
    await flush();
    expect(model.get("ab12cd34")!.testTitle).toBe(`제목 ${reads}`);
    const fresh = model.get("ab12cd34")!.testTitle;
    for (const r of late) r(undefined);
    await flush();
    expect(model.get("ab12cd34")!.testTitle).toBe(fresh);
  });

  test("test_open_again_jumps_to_failure_even_if_open", async () => {
    // T10 검수 3: 목록·"실패 보기"로 다시 열면 열린 탭에서도 실패 스텝으로 다시 간다
    const call = (async (method: string) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") {
        return index([step("s1"), step("s2", { status: "fail", exit: "timeout" })], { failure_chain: ["s2"] });
      }
      if (method === "run.step") return { run_dir: "runs/r", step: step("s2"), events: [{ event: "step.end" }], thumbnail: null, ocr_text: null };
      if (method === "run.file") return { text: "{}", truncated: false, bytes: 2 };
      throw new Error(method);
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34", true);
    await flush();
    expect(model.get("ab12cd34")!.selected).toBe("s2");
    model.select("ab12cd34", "s1");
    model.setView("ab12cd34", "runjson");
    const nonce = model.get("ab12cd34")!.reveal!.nonce;
    // 탭 전환(그냥 열기)은 고른 것을 그대로 둔다
    await model.open("ab12cd34");
    expect(model.get("ab12cd34")!.selected).toBe("s1");
    await model.open("ab12cd34", true);
    await flush();
    const view = model.get("ab12cd34")!;
    expect([view.selected, view.view]).toEqual(["s2", "timeline"]);
    expect(view.reveal!.nonce).toBeGreaterThan(nonce);
  });

  test("test_reveal_step_walks_parents_through_unloaded_pages", async () => {
    // 노드별 통계 → 마지막 실패 (T11): s50은 반복 s1의 3회차 안 호출 s40 아래에 있고, 읽은 쪽(첫 쪽)에는 없다
    const loop = step("s1", { children: 900, iterations: [0, 1, 2].map((i) => ({ iteration: i, status: "success" as const, steps: 300, t_start: "2026-11-02T01:00:00.000Z", duration_ms: 10 })) });
    const call40 = step("s40", { parent: "s1", iteration: 2, calls: "subgraphs/c.graph.json", children: 600 });
    const target = step("s50", { parent: "s40", status: "fail", graph: "subgraphs/c.graph.json" });
    const asked: string[] = [];
    const call = (async (method: string, params: Record<string, unknown>) => {
      if (method === "graph.open") throw new Error("no graph");
      if (method === "run.index") return index([loop], { failure_chain: [] });
      if (method === "run.children") return { offset: 0, total: 600, steps: [step(`s${1000 + Number(params.offset)}`, { parent: String(params.parent) })] };
      if (method === "run.step") {
        asked.push(String(params.step));
        const node = params.step === "s50" ? target : call40;
        return { run_dir: "runs/r", step: node, events: [{ event: "step.start" }, { event: "step.end" }], thumbnail: null, ocr_text: null };
      }
      throw new Error(method);
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    model.setView("ab12cd34", "stats");
    expect(await model.revealStep("ab12cd34", "s50")).toBe(true);
    const view = model.get("ab12cd34")!;
    expect(asked).toEqual(["s50", "s40"]);
    expect(view.view).toBe("timeline");
    expect(view.selected).toBe("s50");
    expect(view.reveal?.step).toBe("s50");
    expect([...view.expanded].sort()).toEqual(["s1", "s40"]);
    expect(view.iteration.get("s1")).toBe(2);
    // 쪽에 없어도 고정한 조상 사슬로 줄이 보인다
    expect(childrenOf(view, loop).map((s) => s.step)).toContain("s40");
    expect(childrenOf(view, call40).map((s) => s.step)).toContain("s50");
    // 이미 받은 끝난 기록은 다시 읽지 않는다
    expect(detailComplete(view.details.get("s50"))).toBe(true);
  });

  test("test_compare_late_running_response_does_not_overwrite_after_end", async () => {
    // T11 검수 3: 진행 중 비교 요청 → 색인 ended → 강제 재요청, 새 응답이 먼저 오고 옛 응답이 늦게 와도 새 결과가 남는다
    let state: "running" | "ended" = "running";
    const pending: ((v: unknown) => void)[] = [];
    const call = (async (method: string) => {
      if (method === "run.index") return index([], { state });
      if (method === "run.compare") return new Promise((resolve) => pending.push(resolve));
      throw new Error("no graph");
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    const old = model.loadCompare("ab12cd34", null);
    state = "ended";
    await model.refresh("ab12cd34");
    const fresh = model.loadCompare("ab12cd34", null, true);
    expect(pending).toHaveLength(2);
    pending[1]({ baseline: "good0001", baseline_picked: "auto", screen: { diff_ratio: 0.5 } });
    await fresh;
    pending[0]({ baseline: "good0001", baseline_picked: "auto", screen: { reason: "no_evidence", file: null, baseline_file: "thumbs/s1.jpg" } });
    await old;
    const result = model.get("ab12cd34")!.compare!.result as { screen: { diff_ratio?: number; reason?: string } };
    expect(result.screen.diff_ratio).toBe(0.5);
    expect(result.screen.reason).toBeUndefined();
    // 같은 열쇠는 캐시: 다시 불러도 요청하지 않는다
    await model.loadCompare("ab12cd34", null);
    expect(pending).toHaveLength(2);
  });

  test("test_compare_a_b_a_drops_late_first_response", async () => {
    // T11 검수 3: 스텝 A → B → A. 첫 A 응답이 마지막에 와도 두 번째 A의 결과가 남는다
    const pending: { step: unknown; resolve(v: unknown): void }[] = [];
    const call = (async (method: string, params: Record<string, unknown>) => {
      if (method === "run.index") return index([step("s1"), step("s2")], { state: "ended" });
      if (method === "run.compare") return new Promise((resolve) => pending.push({ step: params.step, resolve }));
      if (method === "run.step") return { run_dir: "runs/r", step: step(String(params.step)), events: [], thumbnail: null, ocr_text: null };
      throw new Error("no graph");
    }) as unknown as RpcCall;
    const model = new RunIndexModel(call, manualTimers().delay);
    await model.open("ab12cd34");
    const a1 = model.loadCompare("ab12cd34", "s1");
    const b = model.loadCompare("ab12cd34", "s2");
    const a2 = model.loadCompare("ab12cd34", "s1");
    expect(pending.map((p) => p.step)).toEqual(["s1", "s2", "s1"]);
    pending[2].resolve({ baseline: "good0001", baseline_picked: "auto", screen: { diff_ratio: 0.25 } });
    await a2;
    pending[1].resolve({ baseline: "good0001", baseline_picked: "auto", screen: { diff_ratio: 0.9 } });
    pending[0].resolve({ baseline: "good0001", baseline_picked: "auto", screen: { diff_ratio: 0.1 } });
    await Promise.all([a1, b]);
    const compare = model.get("ab12cd34")!.compare!;
    expect(compare.key).toBe("auto|s1");
    expect((compare.result as { screen: { diff_ratio: number } }).screen.diff_ratio).toBe(0.25);
  });

  test("mergeSteps_orders_by_step_number", () => {
    expect(mergeSteps([step("s10"), step("s2")], [step("s9")]).map((s) => s.step)).toEqual(["s2", "s9", "s10"]);
  });
});
