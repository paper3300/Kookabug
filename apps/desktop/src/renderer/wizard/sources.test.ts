// 6단계 원본 칸 여러 줄 (UX1 U4): 줄 ID 규칙(첫 줄 = 칸 ID, 그다음 <칸>_<무작위 hex>, 예전 _2도 읽음), 칸당 여러 ID의
// 초기값·저장 계획·같은 ID 막기
import { describe, expect, test } from "vitest";
import {
  duplicateIds,
  initialRows,
  initialValues,
  nextRowId,
  planSources,
  rowNumber,
  rowTag,
  rowTitle,
  SLOTS,
  slotOf,
  toSource,
  type SourceDef,
} from "./sources";

const DESIGN = SLOTS.find((s) => s.id === "design_doc")!;

describe("줄 ID", () => {
  test("첫 줄은 칸 ID, 그다음 _2부터. 칸 밖 ID·_1·_0은 칸 줄이 아니다", () => {
    expect(rowNumber(DESIGN, "design_doc")).toBe(1);
    expect(rowNumber(DESIGN, "design_doc_2")).toBe(2);
    expect(rowNumber(DESIGN, "design_doc_12")).toBe(12);
    expect(rowNumber(DESIGN, "design_doc_1")).toBeNull();
    expect(rowNumber(DESIGN, "design_doc_02")).toBeNull();
    expect(rowNumber(DESIGN, "design_docs")).toBeNull();
    expect(slotOf("design_doc_3")?.id).toBe("design_doc");
    expect(slotOf("item_table")).toBeNull();
    expect(rowTitle(DESIGN, "design_doc")).toBe("기획 문서");
    expect(rowTitle(DESIGN, "design_doc_2")).toBe("기획 문서 2");
    expect(toSource(DESIGN, "docs/b", "design_doc_2")?.def).toEqual({ id: "design_doc_2", kind: "design_doc", title: "기획 문서 2", path: "docs/b" });
  });

  test("다음 줄 ID는 <칸>_<무작위 6자 hex>, 있는 ID와 같으면 다시 뽑는다", () => {
    expect(nextRowId(DESIGN, [])).toMatch(/^design_doc_[0-9a-f]{6}$/);
    const draws = ["3fa91c", "3fa91c", "123456", "b0b0b0"];
    const random = () => draws.shift()!;
    // 이미 있는 ID·예전 번호 ID 모양(숫자만)은 건너뛴다
    expect(nextRowId(DESIGN, ["design_doc", "design_doc_3fa91c"], random)).toBe("design_doc_b0b0b0");
    expect(rowTag(DESIGN, "design_doc_3fa91c")).toBe("3fa91c");
    expect(rowTag(DESIGN, "design_doc_2")).toBeNull();
    expect(rowTag(DESIGN, "game_code_3fa91c")).toBeNull();
    expect(slotOf("design_doc_3fa91c")?.id).toBe("design_doc");
    expect(rowTitle(DESIGN, "design_doc_3fa91c")).toBe("기획 문서 3fa91c");
  });

  test("가장 큰 ID를 지움 → 저장 → 다시 열기 → 추가: 지운 ID와 다르다 (UX1 검수 M1)", () => {
    // 저장된 두 줄 (예전 번호 ID 하나 + 새 ID 하나)
    const first = nextRowId(DESIGN, ["design_doc"]);
    const team: SourceDef[] = [
      { id: "design_doc", kind: "design_doc", title: "기획 문서", path: "a" },
      { id: "design_doc_2", kind: "design_doc", title: "기획 문서 2", path: "b" },
      { id: first, kind: "design_doc", title: rowTitle(DESIGN, first), local: true },
    ];
    const initial = initialValues(team, { [first]: "D:/c" });
    expect(initialRows(team).design_doc).toEqual(["design_doc", "design_doc_2", first]);
    // 마지막(새) 줄을 지우고 저장
    const plan = planSources(team, initial, { ...initial, [first]: "" });
    expect(plan.defs.map((d) => d.id)).toEqual(["design_doc", "design_doc_2"]);
    // 다시 열기: 남은 원본만으로 화면을 다시 만든다 → 추가
    const reopened = initialRows(plan.defs);
    const taken = [...plan.defs.map((d) => d.id), ...Object.values(reopened).flat()];
    for (let i = 0; i < 50; i += 1) {
      const next = nextRowId(DESIGN, taken);
      expect(next).not.toBe(first);
      expect(taken).not.toContain(next);
    }
  });

  test("칸마다 줄 ID: 팀 원본 순서와 무관하게 번호 순, 없는 칸은 첫 줄 하나", () => {
    const team: SourceDef[] = [
      { id: "design_doc_3", kind: "design_doc", title: "기획 문서 3", path: "c" },
      { id: "design_doc", kind: "design_doc", title: "기획 문서", path: "a" },
    ];
    const rows = initialRows(team);
    expect(rows.design_doc).toEqual(["design_doc", "design_doc_3"]);
    expect(rows.game_code).toEqual(["game_code"]);
    // 첫 줄을 지운 칸도 남은 ID 그대로
    expect(initialRows([{ id: "design_doc_2", kind: "design_doc", title: "x", path: "b" }]).design_doc).toEqual(["design_doc_2"]);
  });
});

describe("칸당 여러 줄 저장", () => {
  test("두 줄 저장: 상대 경로는 팀, 절대 경로는 이 PC (local)", () => {
    const plan = planSources([], {}, { design_doc: "docs/design", design_doc_2: "D:\\planning\\more" });
    expect(plan.changed).toBe(true);
    expect(plan.defs).toEqual([
      { id: "design_doc", kind: "design_doc", title: "기획 문서", path: "docs/design" },
      { id: "design_doc_2", kind: "design_doc", title: "기획 문서 2", local: true },
    ]);
    expect(plan.local).toEqual({ design_doc: null, design_doc_2: "D:\\planning\\more" });
  });

  test("가운데 줄을 지워도 남은 줄의 ID·이 PC 경로는 그대로", () => {
    const team: SourceDef[] = [
      { id: "design_doc", kind: "design_doc", title: "기획 문서", path: "docs/a" },
      { id: "design_doc_2", kind: "design_doc", title: "기획 문서 2", local: true },
      { id: "design_doc_3", kind: "design_doc", title: "기획 문서 3", local: true },
    ];
    const initial = initialValues(team, { design_doc_2: "D:/b", design_doc_3: "D:/c" });
    expect(initial).toEqual({ design_doc: "docs/a", design_doc_2: "D:/b", design_doc_3: "D:/c" });
    // 화면의 "−" = 그 줄을 빈 값으로
    const plan = planSources(team, initial, { ...initial, design_doc_2: "" });
    expect(plan.defs.map((d) => d.id)).toEqual(["design_doc", "design_doc_3"]);
    // 지운 줄만 local에서 지운다 (design_doc_3의 경로는 건드리지 않는다)
    expect(plan.local).toEqual({ design_doc_2: null });
  });

  test("바꾸지 않은 줄은 쓰지 않는다 (값이 없는 local 줄 포함)", () => {
    const team: SourceDef[] = [{ id: "design_doc_2", kind: "design_doc", title: "기획 문서 2", local: true }];
    const initial = initialValues(team, {});
    const plan = planSources(team, initial, { ...initial, design_doc: "" });
    expect(plan.changed).toBe(false);
    expect(plan.defs).toEqual(team);
  });

  test("새 줄은 칸 순서·번호 순으로 뒤에 붙는다", () => {
    const team: SourceDef[] = [{ id: "item_table", kind: "data", title: "아이템", path: "x" }];
    const plan = planSources(team, {}, { qa_sheet: "https://example.invalid/q", design_doc_3: "c", design_doc_2: "b", game_code: "g" });
    expect(plan.defs.map((d) => d.id)).toEqual(["item_table", "game_code", "design_doc_2", "design_doc_3", "qa_sheet"]);
  });

  test("같은 ID가 둘인 줄은 막고, 다른 줄은 저장한다", () => {
    const team: SourceDef[] = [
      { id: "design_doc_2", kind: "design_doc", title: "a", path: "a" },
      { id: "design_doc_2", kind: "design_doc", title: "b", path: "b" },
    ];
    expect([...duplicateIds(team)]).toEqual(["design_doc_2"]);
    const plan = planSources(team, initialValues(team, {}), { design_doc_2: "c", design_doc: "d" });
    expect(plan.blocked).toEqual(["design_doc_2"]);
    expect(plan.defs.filter((d) => d.id === "design_doc_2")).toEqual(team);
    expect(plan.defs).toContainEqual({ id: "design_doc", kind: "design_doc", title: "기획 문서", path: "d" });
  });
});
