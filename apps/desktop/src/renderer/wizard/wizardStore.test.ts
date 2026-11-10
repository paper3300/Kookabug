// 마법사 판정 (M8 계획 3.17·B7): 완료 조건·건너뛰기·이어서·짧은 마법사 판정
import { describe, expect, test } from "vitest";
import { duplicateIds, initialValues, planSources } from "./sources";
import {
  advance,
  autoOpenPlan,
  back,
  canAdvance,
  canGoBack,
  canSkip,
  emptyShortSteps,
  NEW_STEPS,
  only,
  setWarnings,
  skip,
  start,
  toFile,
  type SetupSnapshot,
  type WizardFile,
} from "./wizardStore";

const SNAP: SetupSnapshot = { wizard: null, teamSetup: true, gameExecutable: "C:/g.exe", gameTitle: "G", secretKeys: 1, agents: 1 };

function file(partial: Partial<WizardFile>): WizardFile {
  return { format: "kookabug.wizard/0", step: 2, done: [], skipped: [], warnings: [], ...partial };
}

describe("완료 조건", () => {
  test("필수 단계는 ready일 때만 다음 (양성 대조: ready면 켜진다)", () => {
    const p = start("new", NEW_STEPS, 2);
    expect(canAdvance(p, false)).toBe(false);
    expect(canAdvance(p, true)).toBe(true);
    expect(canSkip(p)).toBe(false); // 2 게임은 필수
  });

  test("0단계는 다음이 없고 새/열기 고르기로만 넘어간다", () => {
    expect(canAdvance(start("new", NEW_STEPS, 0), true)).toBe(false);
  });

  test("advance는 완료 표시·건너뜀 해제·다음 단계, 끝이면 finished", () => {
    let p = { ...start("new", NEW_STEPS, 5), skipped: [5] };
    const r = advance(p);
    expect(r.progress.step).toBe(6);
    expect(r.progress.done).toEqual([5]);
    expect(r.progress.skipped).toEqual([]);
    expect(r.finished).toBe(false);
    p = start("new", NEW_STEPS, 9);
    expect(advance(p).finished).toBe(true);
  });
});

describe("건너뛰기", () => {
  test("선택 단계(4·5·6)만 건너뛴다, 필수 단계는 그대로", () => {
    for (const n of [4, 5, 6] as const) {
      const r = skip(start("new", NEW_STEPS, n));
      expect(r.progress.skipped).toEqual([n]);
      expect(r.progress.step).toBe(n + 1);
      expect(r.progress.done).not.toContain(n);
    }
    for (const n of [1, 2, 3, 7, 8] as const) {
      const p = start("new", NEW_STEPS, n);
      expect(canSkip(p)).toBe(false);
      expect(skip(p).progress).toBe(p);
    }
  });

  test("단계 하나만 다시 열기(returnTo): 5 → 9로 돌아온다", () => {
    const p = { ...start("new", NEW_STEPS, 5), skipped: [5], returnTo: 9 as const };
    const r = advance(p);
    expect(r.progress.step).toBe(9);
    expect(r.progress.returnTo).toBeNull();
    expect(r.progress.done).toContain(5);
    expect(r.progress.skipped).not.toContain(5);
  });

  test("only 모드는 그 단계 하나로 끝난다", () => {
    const r = advance(only(4, file({ done: [1, 2, 3], skipped: [4] })));
    expect(r.finished).toBe(true);
    expect(r.progress.done).toEqual([1, 2, 3, 4]);
  });
});

describe("이전", () => {
  test("1단계를 마친 뒤에는 0·1로 돌아가지 않는다", () => {
    const p = { ...start("new", NEW_STEPS, 2), done: [1] };
    expect(canGoBack(p)).toBe(false);
    const q = { ...start("new", NEW_STEPS, 3), done: [1, 2] };
    expect(back(q).step).toBe(2);
    expect(back(start("new", NEW_STEPS, 1)).step).toBe(0);
  });
});

describe("이어서 · 짧은 마법사", () => {
  test("끝나지 않은 새 프로젝트 진행은 저장된 단계부터 이어서 (1단계 마침)", () => {
    const plan = autoOpenPlan({ ...SNAP, wizard: file({ step: 6, done: [1, 2, 3], skipped: [4, 5] }) });
    expect(plan?.mode).toBe("new");
    expect(plan?.step).toBe(6);
    expect(plan?.skipped).toEqual([4, 5]);
  });

  test("끝난 진행(9 완료)은 띄우지 않는다", () => {
    expect(autoOpenPlan({ ...SNAP, wizard: file({ done: [1, 2, 3, 7, 8, 9] }) })).toBeNull();
  });

  test("이 PC 진행이 없고 팀 설정을 마친 프로젝트면 빈 단계만 + 완료", () => {
    const snap = { ...SNAP, gameExecutable: null, secretKeys: 0 };
    expect(emptyShortSteps(snap)).toEqual([2, 3, 4]);
    const plan = autoOpenPlan(snap);
    expect(plan?.mode).toBe("short");
    expect(plan?.steps).toEqual([2, 3, 4, 9]);
    expect(plan?.step).toBe(2);
  });

  test("팀 설정을 마치지 않은 프로젝트(team_setup 없음)는 자동으로 띄우지 않는다", () => {
    expect(autoOpenPlan({ ...SNAP, teamSetup: false, agents: 0, secretKeys: 0, gameExecutable: null })).toBeNull();
  });

  test("짧은 마법사 중간에 닫았으면 남은 짧은 단계부터", () => {
    const plan = autoOpenPlan({ ...SNAP, wizard: file({ step: 4, done: [2, 3], skipped: [] }) });
    expect(plan?.mode).toBe("short");
    expect(plan?.steps).toEqual([4, 5, 9]);
    expect(plan?.step).toBe(4);
  });

  test("3 점검은 이 PC 기록이 없으면 늘 빈 단계 (양성 대조: 기록 있으면 빠진다)", () => {
    expect(emptyShortSteps({ ...SNAP })).toEqual([3]);
    expect(emptyShortSteps({ ...SNAP, wizard: file({ done: [3] }) })).toEqual([]);
  });
});

describe("저장 형식", () => {
  test("wizard.json에는 단계 상태만", () => {
    const p = setWarnings({ ...start("new", NEW_STEPS, 3), done: [1, 2] }, 3, ["check_failed:dpi"]);
    expect(Object.keys(toFile(p)).sort()).toEqual(["done", "format", "skipped", "step", "warnings"]);
    expect(toFile(p).warnings).toEqual([{ step: 3, code: "check_failed:dpi" }]);
    // 같은 단계 경고는 바꿔 쓴다
    expect(setWarnings(p, 3, []).warnings).toEqual([]);
  });
});

describe("6단계 원본 저장 계획 (B7 검수 H4)", () => {
  const team = [
    { id: "item_table", kind: "data", title: "아이템 테이블", path: "sources/items.csv" },
    { id: "game_code", kind: "code", title: "게임 코드", local: true },
    { id: "design_doc", kind: "design_doc", title: "기획 문서", url: "https://example.invalid/doc" },
  ];

  test("다시 열고 그대로 확인하면 아무것도 바꾸지 않는다 (이 PC 경로를 못 읽은 local 원본도 유지)", () => {
    const initial = initialValues(team, {}); // 이 PC에 경로가 없다 → game_code 칸은 비어 있다
    expect(initial).toEqual({ game_code: "", design_doc: "https://example.invalid/doc" });
    const plan = planSources(team, initial, { ...initial });
    expect(plan).toEqual({ defs: team, local: {}, changed: false, blocked: [] });
  });

  test("이 PC 경로로 채우고, 사람이 비운 칸만 지운다", () => {
    const initial = initialValues(team, { game_code: "D:/src/game" });
    expect(initial.game_code).toBe("D:/src/game");
    const cleared = planSources(team, initial, { ...initial, game_code: "" });
    expect(cleared.defs.map((d) => d.id)).toEqual(["item_table", "design_doc"]);
    expect(cleared.local).toEqual({ game_code: null });
    // 경로만 바꾸면 팀 정의는 그대로, local 경로만
    const moved = planSources(team, initial, { ...initial, game_code: "E:/src/game" });
    expect(moved.defs).toEqual(team);
    expect(moved.local).toEqual({ game_code: "E:/src/game" });
    // 새 칸은 끝에 더한다
    const added = planSources(team, initial, { ...initial, qa_sheet: "https://example.invalid/qa" });
    expect(added.defs.at(-1)).toMatchObject({ id: "qa_sheet", url: "https://example.invalid/qa" });
    expect(added.local).toEqual({ qa_sheet: null });
  });

  test("review_duplicate_source_ids_do_not_destroy_hidden_entry", () => {
    const hidden = { id: "game_code", kind: "other", title: "review-hidden-source", path: "sources/first" };
    const visible = { id: "game_code", kind: "code", title: "review-visible-source", path: "sources/second" };
    const doc = { id: "design_doc", kind: "design_doc", title: "기획 문서", url: "https://example.invalid/doc" };
    const sources = [hidden, visible, doc];
    const initial = initialValues(sources, {});
    const plan = planSources(sources, initial, { ...initial, game_code: "sources/third", data_table: "sources/data" });
    // 같은 ID 원본 둘은 그대로 (같은 값으로 치환·삭제하지 않는다)
    expect(plan.defs.filter((d) => d.id === "game_code")).toEqual([hidden, visible]);
    // 그 칸은 저장이 막히고, 다른 칸은 정상 저장
    expect(duplicateIds(sources)).toEqual(new Set(["game_code"]));
    expect(plan.blocked).toEqual(["game_code"]);
    expect(plan.defs).toContainEqual(doc);
    expect(plan.defs.at(-1)).toMatchObject({ id: "data_table", path: "sources/data" });
    expect(plan.local).toEqual({ data_table: null });
    // 칸을 비워도 지우지 않는다
    expect(planSources(sources, initial, { ...initial, game_code: "" }).defs).toEqual(sources);
  });
});
