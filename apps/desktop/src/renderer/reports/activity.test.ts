// 작업 활동 목록 (UX1 U3): 도구 → 한국어 한 줄, 머리 요약, 이어 읽기 합치기
import { describe, expect, test } from "vitest";
import { ACTIVITY_KEEP, activityHead, activityLive, activityText, collapseActivity, mergeActivity, type ActivityEntry } from "./activity";

const e = (seq: number, tool = "kb_wiki_write", result = "ok", target = ""): ActivityEntry => ({ seq, at: "2026-11-11T01:02:03.000Z", tool, result, target });

describe("활동 줄", () => {
  test("도구·대상 → 한국어, 실패는 코드", () => {
    expect(activityText(e(1, "kb_wiki_write", "ok", "wiki/overview.md"))).toBe("위키 쓰기: wiki/overview.md");
    expect(activityText(e(1, "kb_project_info"))).toBe("설정 확인");
    expect(activityText(e(1, "kb_run_start", "job_budget_exhausted", "tests/a.graph.json"))).toBe("테스트 실행: tests/a.graph.json · 실패 (job_budget_exhausted)");
    expect(activityText(e(1, "kb_unknown_tool"))).toBe("kb_unknown_tool");
  });

  test("머리: 쓴 시간·실행 수·도구 호출 수", () => {
    expect(activityHead({ minutes: 3, runs: 1, tool_calls: 12 })).toBe("3분 · 실행 1 · 도구 호출 12");
    expect(activityHead(null)).toBe("");
    expect(activityLive("running")).toBe(true);
    expect(activityLive("ending")).toBe(true);
    expect(activityLive("done")).toBe(false);
  });

  test("연달아 같은 줄은 하나로 묶는다 (MCP 도구 하나 = daemon 메서드 여럿)", () => {
    const rows = collapseActivity([
      e(1, "kb_project_info"),
      e(2, "kb_project_info"),
      e(3, "kb_project_info", "permission_denied"),
      e(4, "kb_knowledge_get", "ok", "unknowns"),
      e(5, "kb_project_info"),
    ]);
    expect(rows.map((r) => [r.text, r.count, r.seq])).toEqual([
      ["설정 확인", 2, 2],
      ["설정 확인 · 실패 (permission_denied)", 1, 3],
      ["지식 읽기: unknowns", 1, 4],
      ["설정 확인", 1, 5],
    ]);
  });

  test("이어 읽기: 같은 seq는 한 번, seq 순, 오래된 것부터 버린다", () => {
    expect(mergeActivity([e(1), e(2)], [e(2), e(3)]).map((x) => x.seq)).toEqual([1, 2, 3]);
    const many = Array.from({ length: ACTIVITY_KEEP + 5 }, (_, i) => e(i + 1));
    const kept = mergeActivity([], many);
    expect(kept).toHaveLength(ACTIVITY_KEEP);
    expect(kept[0].seq).toBe(6);
  });
});
