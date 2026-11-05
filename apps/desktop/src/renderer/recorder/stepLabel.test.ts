// 녹화 스텝 줄 문구 (M4 계획 T9 완료 기준 stepLabel.test.ts): 시안 문구 — 이미지 클릭 "…"·click (x, y) · 00:03.2·
// type ●●●●●●·배지 색, 비밀값 메모는 redact_secrets에 따라 (U16). 원문 글자는 ordinary 스텝만 보인다
import { describe, expect, test } from "vitest";
import { commitBlocker, formatStepTime, stepLabel, stepMarks, stepRaw, type RecorderStep } from "./labels";

function step(over: Partial<RecorderStep> & Pick<RecorderStep, "step" | "kind">): RecorderStep {
  return { badges: [], needs_review: [], node: { title: "", type: "" }, t_ms: 0, ...over } as RecorderStep;
}

const STEPS: RecorderStep[] = [
  step({ step: "s1", kind: "text", t_ms: 1100, text_state: "secret", text_len: 6, secret_key: null, node: { title: "비밀값 입력", type: "core.input.type_text" } }),
  step({ step: "s2", kind: "click", t_ms: 3200, input: { point: [180, 216], button: "left" }, node: { title: '이미지 클릭 "가방 아이콘"', type: "core.image.click" } }),
  step({ step: "s3", kind: "wait", t_ms: 5000, input: { gap_ms: 1800 }, node: { title: '나타날 때까지 대기 "가방 창"', type: "core.image.wait" } }),
  step({
    step: "s4",
    kind: "click",
    t_ms: 6900,
    input: { point: [640, 288] },
    badges: [{ code: "same_shape", severity: "review", message: "같은 모양이 여러 곳 — 검색 범위를 좁히세요" }],
    node: { title: '이미지 클릭 "장비 슬롯"', type: "core.image.click" },
  }),
  step({ step: "s5", kind: "check_text", t_ms: 9000, node: { title: "값 확인", type: "core.assert.text" } }),
  step({ step: "s6", kind: "key", t_ms: 12000, input: { keys: "enter" }, node: { title: "키 입력 enter", type: "core.input.key" } }),
  step({ step: "s7", kind: "text", t_ms: 1500, text_state: "ordinary", text: "qa_tester_01", text_len: 12, node: { title: "글자 입력", type: "core.input.type_text" } }),
];

describe("스텝 줄", () => {
  const marks = stepMarks(STEPS);

  test("번호 칸: 순번·비밀값 P·확인 V·대기 빈칸, 점 색", () => {
    expect(STEPS.map((s) => marks.get(s.step))).toEqual([
      { mark: "P", dot: "special" },
      { mark: "1", dot: "step" },
      { mark: "", dot: "wait" },
      { mark: "2", dot: "step" },
      { mark: "V", dot: "special" },
      { mark: "3", dot: "step" },
      { mark: "4", dot: "step" },
    ]);
  });

  test("시안 문구: 제목·원래 입력·메모", () => {
    expect(stepLabel(STEPS[1], marks, false)).toMatchObject({ title: '이미지 클릭 "가방 아이콘"', raw: "click (180, 216) · 00:03.2", note: "", tone: "muted" });
    expect(stepLabel(STEPS[2], marks, false)).toMatchObject({ raw: "wait 1.8s" });
    expect(stepLabel(STEPS[3], marks, false)).toMatchObject({ note: "같은 모양이 여러 곳 — 검색 범위를 좁히세요", tone: "review" });
    expect(stepLabel(STEPS[4], marks, false)).toMatchObject({ raw: "assert text" });
    expect(stepLabel(STEPS[5], marks, false)).toMatchObject({ raw: "key enter · 00:12.0" });
  });

  test("비밀값은 ● × 길이, 메모는 비밀값 선택 필요 (U16: 가림 켜면 스크린샷 생략 절)", () => {
    expect(stepLabel(STEPS[0], marks, false)).toMatchObject({ raw: "type ●●●●●● · 00:01.1", note: "비밀값 선택 필요", tone: "secret" });
    expect(stepLabel(STEPS[0], marks, true).note).toBe("비밀값 선택 필요 · 재생 때 이 스텝은 스크린샷 생략");
    const chosen = { ...STEPS[0], secret_key: "accounts.qa_tester_01" };
    expect(stepLabel(chosen, marks, false)).toMatchObject({ note: "비밀값 accounts.qa_tester_01", tone: "muted" });
  });

  test("원문 글자는 ordinary 스텝만 — 판정 중·확인 필요는 글자 없이", () => {
    expect(stepRaw(STEPS[6])).toBe('type "qa_tester_01" · 00:01.5');
    // 판정 중·확인 필요 스텝에 (잘못) text가 실려 와도 보이지 않는다
    const pending = step({ step: "p", kind: "text", t_ms: 0, text_state: "pending", text_len: 5, text: "leak!" });
    const review = step({ step: "r", kind: "text", t_ms: 0, text_state: "needs_review", text_len: 5, text: "leak!", needs_review: ["no_evidence"] });
    const secret = step({ step: "x", kind: "text", t_ms: 0, text_state: "secret", text_len: 3, text: "leak!" });
    for (const s of [pending, review, secret]) expect(JSON.stringify(stepLabel(s, stepMarks([s]), true))).not.toContain("leak!");
    expect(stepLabel(pending, stepMarks([pending]), false)).toMatchObject({ raw: "type (판정 중) · 00:00.0", note: "판정 중" });
    expect(stepLabel(review, stepMarks([review]), false)).toMatchObject({ raw: "type (확인 필요) · 00:00.0", note: "비밀번호인지 확인하지 못했어요", tone: "review" });
  });

  test("secret_overlap 메모 (B3 인계 문구)", () => {
    const s = step({ step: "o", kind: "click", t_ms: 0, needs_review: ["secret_overlap"] });
    expect(stepLabel(s, stepMarks([s]), false)).toMatchObject({ note: "비밀번호 칸과 겹쳐 대상을 버렸어요 — 영역을 다시 고르거나 지우세요", tone: "review" });
  });

  test("다른 입력 종류", () => {
    expect(stepRaw(step({ step: "a", kind: "click", t_ms: 61_000, input: { point: [1, 2], button: "right" } }))).toBe("right click (1, 2) · 01:01.0");
    expect(stepRaw(step({ step: "b", kind: "click", t_ms: 0, input: { point: [1, 2], count: 2 } }))).toBe("double click (1, 2) · 00:00.0");
    expect(stepRaw(step({ step: "c", kind: "drag", t_ms: 0, input: { point: [1, 2], end: [3, 4] } }))).toBe("drag (1, 2) → (3, 4) · 00:00.0");
    expect(formatStepTime(9_449)).toBe("00:09.4");
  });

  test("저장 단추를 막는 이유: 판정 중 → 비밀값 키 → 확인 필요 → 스텝 없음", () => {
    expect(commitBlocker(STEPS)).toBe("비밀값을 고르면 저장할 수 있어요");
    const resolved = STEPS.map((s) => (s.step === "s1" ? { ...s, secret_key: "accounts.qa_tester_01" } : s));
    expect(commitBlocker(resolved)).toBeNull();
    expect(commitBlocker([...resolved, step({ step: "p", kind: "text", t_ms: 0, text_state: "pending" })])).toBe("비밀번호 판정 중이에요");
    expect(commitBlocker([step({ step: "r", kind: "text", t_ms: 0, text_state: "needs_review" })])).toBe("확인 필요한 입력을 먼저 고르세요");
    expect(commitBlocker([])).toBe("녹화된 스텝이 없어요");
  });
});
