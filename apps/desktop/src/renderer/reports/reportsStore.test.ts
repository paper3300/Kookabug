// 보고함 판정 (M8 계획 3.11·3.17, B7): 목록 합치기·결정 단추·되돌리기 한 번·질문·취소
import { describe, expect, test } from "vitest";
import { RpcError } from "../rpc/client";
import {
  canCancel,
  decidable,
  filledCount,
  followupBlock,
  followupPlaybook,
  inboxCount,
  isSettingGroup,
  mergeRows,
  openQuestions,
  revertable,
  sendAnswers,
  settingAcceptable,
  settingCurrentText,
  settingValueText,
  type Report,
  type ReportGroup,
  type Unknown,
} from "./reportsStore";

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

describe("질문 일괄 답 (UX2 B)", () => {
  const qs: Unknown[] = [
    { id: "u-1", rev: 1, question: "창 제목은?", human_only: true, state: "open" },
    { id: "u-2", rev: 3, question: "기획 문서는?", human_only: true, state: "open" },
    { id: "u-3", rev: 1, question: "치트는?", human_only: true, state: "open" },
    { id: "u-4", rev: 1, question: "계정은?", human_only: true, state: "open" },
  ];

  test("글을 넣은 질문만 차례로 보내고 빈 칸(공백만 포함)은 건너뛴다", async () => {
    const sent: [string, number, string][] = [];
    const drafts = { "u-1": " SampleRPG ", "u-2": "   ", "u-4": "qa 계정\n두 줄" };
    expect(filledCount(qs, drafts)).toBe(2);
    const out = await sendAnswers(qs, drafts, async (u, text) => {
      sent.push([u.id, u.rev, text]);
    });
    expect(sent).toEqual([
      ["u-1", 1, "SampleRPG"],
      ["u-4", 1, "qa 계정\n두 줄"],
    ]);
    expect(out).toEqual({ answered: ["u-1", "u-4"], failed: {} });
  });

  test("일부만 실패하면 그 질문만 이유를 남기고 나머지는 보낸다", async () => {
    const drafts = { "u-1": "a", "u-2": "b", "u-3": "c" };
    const out = await sendAnswers(qs, drafts, async (u) => {
      if (u.id === "u-2") throw new RpcError(-32100, "미지수가 그사이 바뀌었다", { code: "revision_conflict" });
      if (u.id === "u-3") throw new RpcError(-32100, "x", { code: "secret_in_text", field: "text" });
    });
    expect(out.answered).toEqual(["u-1"]);
    expect(Object.keys(out.failed)).toEqual(["u-2", "u-3"]);
    expect(out.failed["u-2"]).toContain("바뀌었어요");
    expect(out.failed["u-3"]).toContain("비밀값");
  });

  test("보낼 글이 없으면 아무것도 부르지 않는다", async () => {
    let calls = 0;
    const out = await sendAnswers(qs, {}, async () => {
      calls += 1;
    });
    expect(calls).toBe(0);
    expect(out).toEqual({ answered: [], failed: {} });
  });
});

describe("설정 바꾸기 제안 (UX2 C)", () => {
  const group = (decision: ReportGroup["decision"] = null): ReportGroup => ({
    key: "setting_change|game.title|s-20261111-000000-abcd",
    cause: "game.title",
    title: "설정 바꾸기 제안 · game.title",
    items: [
      {
        kind: "setting_change",
        setting: {
          id: "s-20261111-000000-abcd",
          key: "game.title",
          reason: "사람 답",
          local: { value: "SampleRPG 2", current: "SampleRPG", current_hidden: false },
        },
      },
    ],
    decision,
  });

  test("결정 전 제안 묶음은 수락·거절 단추, 결정 뒤에는 없다", () => {
    expect(isSettingGroup(group())).toBe(true);
    expect(decidable(group())).toBe(true);
    expect(decidable(group({ decision: "accept", by: "human", at: "x" }))).toBe(false);
    expect(isSettingGroup({ ...group(), items: [{ kind: "working_only" }] })).toBe(false);
  });

  test("이 PC 제안 파일이 없으면(다른 PC 보고) 수락할 수 없다 — 거절만", () => {
    const item = group().items[0];
    expect(settingAcceptable(item.setting)).toBe(true);
    expect(settingAcceptable({ ...item.setting!, local: null })).toBe(false);
    expect(settingAcceptable({ id: "s", key: "game.title", reason: "r" })).toBe(false);
    expect(decidable(group())).toBe(true); // 거절은 남는다
  });

  test("비밀값이 있어 남기지 않은 현재 값은 [가림]", () => {
    expect(settingCurrentText("game.args", null, true)).toBe("[가림]");
    expect(settingCurrentText("sources.add", null, true)).toBe("[가림]");
  });

  test("현재 값 → 제안 값 글", () => {
    expect(settingCurrentText("game.title", "SampleRPG")).toBe("SampleRPG");
    expect(settingValueText("game.title", "SampleRPG 2")).toBe("SampleRPG 2");
    expect(settingCurrentText("game.executable", null)).toBe("(없음)");
    expect(settingValueText("game.args", ["-windowed", "C:\\My Game\\a.ini", ""])).toBe('-windowed "C:\\\\My Game\\\\a.ini" ""');
    expect(settingValueText("sources.add", { kind: "design_doc", location: "D:/plans", title: "기획 문서" })).toBe("기획 문서: D:/plans");
    expect(settingCurrentText("sources.add", ["a", "b"])).toBe("지금 2개");
    expect(settingValueText("automation.forbidden.add", { kind: "text", value: "결제" })).toBe('문구 "결제"');
    expect(settingValueText("cheats.categories.add", { id: "qa_only", title: "QA 전용", unattended: false })).toBe("QA 전용 (qa_only) · 무인 안 함");
  });
});

describe("이어서 진행 (UX2 D)", () => {
  test("Init·이어 하기 보고에만 둔다", () => {
    expect(followupPlaybook({ playbook: "init" })).toBe(true);
    expect(followupPlaybook({ playbook: "followup" })).toBe(true);
    expect(followupPlaybook({ playbook: "repair" })).toBe(false);
  });

  test("무인 작업이 도는 중이면 끄고 이유를 보인다", () => {
    expect(followupBlock([{ state: "done" }, { state: "failed" }])).toBeNull();
    expect(followupBlock([{ state: "done" }, { state: "running" }])).toContain("도는 중");
    expect(followupBlock([{ state: "ending" }])).not.toBeNull();
  });
});
