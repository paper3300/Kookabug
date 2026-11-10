// 보고함 판정 (M8 계획 3.11·3.17, B7): 목록 합치기·결정 단추·되돌리기 한 번·질문·취소
import { describe, expect, test } from "vitest";
import { canCancel, decidable, inboxCount, mergeRows, openQuestions, revertable, type Report, type ReportGroup } from "./reportsStore";

const JOB_A = "j-20261110-010000-aaaa";
const JOB_B = "j-20261110-020000-bbbb";

describe("목록", () => {
  test("작업과 보고를 합치고 최근 먼저, 도는 작업 상태가 보고보다 먼저", () => {
    const rows = mergeRows(
      [
        { job: JOB_B, playbook: "init", state: "running", started_at: "2026-11-10T02:00:00Z", used: { runs: 1 } },
        { job: JOB_A, playbook: "repair", state: "done", started_at: "2026-11-10T01:00:00Z" },
      ],
      [{ job: JOB_A, playbook: "repair", state: "done", started_at: "2026-11-10T01:00:00Z", groups: 2, undecided: 1 }],
    );
    expect(rows.map((r) => r.job)).toEqual([JOB_B, JOB_A]);
    expect(rows[0]).toMatchObject({ state: "running", hasReport: false, groups: null });
    expect(rows[1]).toMatchObject({ groups: 2, undecided: 1, hasReport: true });
    expect(inboxCount(rows)).toBe(2);
  });

  test("통과한 연결 시험(probe)은 목록에서 빼고 실패한 시험은 남긴다", () => {
    const rows = mergeRows(
      [
        { job: JOB_A, playbook: "probe", state: "done", started_at: "a" },
        { job: JOB_B, playbook: "probe", state: "failed", started_at: "b" },
      ],
      [],
    );
    expect(rows.map((r) => r.job)).toEqual([JOB_B]);
  });

  test("빈 목록이면 0 (양성 대조는 위)", () => {
    expect(mergeRows([], [])).toEqual([]);
    expect(inboxCount([])).toBe(0);
  });
});

describe("단추", () => {
  const group = (items: ReportGroup["items"], decision: ReportGroup["decision"] = null): ReportGroup => ({
    key: "k",
    cause: "ui_change",
    title: "t",
    items,
    decision,
  });

  test("묶음 수락·거절은 작업 기준 변경이 있고 결정 전일 때만", () => {
    expect(decidable(group([{ kind: "working_only", change: "w-1" }]))).toBe(true);
    expect(decidable(group([{ kind: "working_only" }], { decision: "accept", by: "human", at: "x" }))).toBe(false);
    expect(decidable(group([{ kind: "auto_adopted", adoption: "a-1" }]))).toBe(false);
  });

  test("되돌리기는 자동 채택 하나에 한 번", () => {
    const item = { kind: "auto_adopted", adoption: "a-20261110-000000-abcd" };
    expect(revertable(item, new Set())).toBe(true);
    expect(revertable(item, new Set(["a-20261110-000000-abcd"]))).toBe(false);
    expect(revertable({ kind: "working_only" }, new Set())).toBe(false);
  });

  test("취소는 진행 중일 때만 (끝내는 중이면 다시 보내지 않는다)", () => {
    expect(canCancel({ state: "running" })).toBe(true);
    expect(canCancel({ state: "ending" })).toBe(false);
    expect(canCancel({ state: "done" })).toBe(false);
  });
});

describe("질문", () => {
  test("사람만 답할 수 있고 열린 미지수만 질문으로", () => {
    const report: Report = { job: JOB_A, playbook: "init", state: "done", groups: [], unknowns: ["u-1", "u-2", "u-3"] };
    const qs = openQuestions(report, [
      { id: "u-1", rev: 1, question: "q1", human_only: true, state: "open" },
      { id: "u-2", rev: 1, question: "q2", human_only: false, state: "open" },
      { id: "u-3", rev: 2, question: "q3", human_only: true, state: "answered" },
      { id: "u-9", rev: 1, question: "다른 보고", human_only: true, state: "open" },
    ]);
    expect(qs.map((q) => q.id)).toEqual(["u-1"]);
  });
});
