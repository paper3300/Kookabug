// 스크린샷 줄 칸 (M3 계획 2.6·2.10, T10 완료 기준)
import { describe, expect, test } from "vitest";
import { candidateRows, evidenceCells } from "./evidenceCells";
import { step } from "./fixtures.testutil";
import type { StepDetail, StepNode } from "./runIndexStore";

function detail(s: StepNode, end: Record<string, unknown>, thumbnail: string | null = null): StepDetail {
  return {
    run_dir: "runs/r",
    step: s,
    ocr_text: null,
    thumbnail,
    events: [
      { event: "step.start", run: "ab12cd34", seq: 1, t: s.t_start, step: s.step, node: s.node, parent: null, path: s.path, attempt: 1 },
      { event: "step.end", run: "ab12cd34", seq: 2, t: s.t_start, step: s.step, attempt: 1, status: s.status, exit: s.exit, duration_ms: 1400, outputs: {}, ...end },
    ] as StepDetail["events"],
  };
}

describe("evidenceCells", () => {
  test("test_no_mid_cell_shows_reason", () => {
    // 2차 N3: 중간은 최선 노력. 표본이 중간 근처에 없으면 _mid 없이 mid null + mid_missing → "중간 장면 없음" 칸
    const s = step("s5", { status: "fail", exit: "timeout", evidence: true });
    const cells = evidenceCells(
      s,
      detail(s, {
        evidence: {
          first: "steps/s5_first.png",
          first_at_ms: 0,
          mid: null,
          mid_missing: "no_sample_near_mid",
          last: "steps/s5_fail.png",
          last_at_ms: 1400,
          target: "targets/a.target.json",
          threshold: 0.8,
          candidates: [{ rect: [10, 20, 30, 40], score: 0.41, scale: 1 }],
        },
        artifacts: ["steps/s5_first.png", "steps/s5_fail.png"],
      }),
    );
    expect(cells.map((c) => [c.key, c.label, c.file, c.reason])).toEqual([
      ["first", "처음", "steps/s5_first.png", null],
      ["missing", "중간", null, "중간 장면 없음"],
      ["last", "시간 초과", "steps/s5_fail.png", null],
    ]);
    // 후보 상자는 마지막 칸에만
    expect(cells.map((c) => c.candidates)).toEqual([false, false, true]);

    // 중간이 있으면 실제 캡처 시각으로 "대기 N초"
    const withMid = evidenceCells(
      s,
      detail(s, { evidence: { first: "steps/s5_first.png", mid: "steps/s5_mid.png", mid_at_ms: 700, last: "steps/s5_fail.png" } }),
    );
    expect(withMid.map((c) => c.label)).toEqual(["처음", "대기 0.7초", "시간 초과"]);
  });

  test("test_policy_omitted_shows_reason_and_success_shows_thumbnail", () => {
    // 기록 끈 서브그래프의 실패 스텝: 화면 없이 "정책으로 생략" 칸과 이유
    const s = step("s7", { status: "fail", exit: "timeout", graph: "subgraphs/private.graph.json" });
    const omitted = evidenceCells(
      s,
      detail(s, { omitted: [{ kind: "screenshot", reason: "policy_off", source: "subgraphs/private.graph.json#/record" }] }),
      "tests/t.graph.json",
    );
    expect(omitted.map((c) => [c.key, c.label, c.reason])).toEqual([["omitted", "정책으로 생략", "서브그래프 기록 끔"]]);
    // 성공한 캡처 스텝: 썸네일 한 칸
    const ok = step("s8");
    expect(evidenceCells(ok, detail(ok, {}, "thumbs/s8.jpg")).map((c) => [c.key, c.file])).toEqual([["thumb", "thumbs/s8.jpg"]]);
  });

  test("test_candidate_rows_rank_and_threshold", () => {
    const s = step("s5", { status: "fail" });
    const rows = candidateRows(
      detail(s, {
        evidence: {
          threshold: 0.8,
          candidates: [
            { rect: [384, 432, 10, 10], score: 0.81, scale: 1 },
            { rect: [902, 140, 10, 10], score: 0.33, scale: 0.95 },
          ],
        },
      }),
    );
    expect(rows).toEqual([
      { rank: 1, score: 0.81, x: 384, y: 432, scale: 1, pass: true },
      { rank: 2, score: 0.33, x: 902, y: 140, scale: 0.95, pass: false },
    ]);
  });
});
