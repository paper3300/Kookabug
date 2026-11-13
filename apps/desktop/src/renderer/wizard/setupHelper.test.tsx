// UX5: 첫 실행 흐름에서 뺀 계정(4)·자동화 정책(7)·기록(8)은 설정 도우미에서 그 단계 하나로 열린다. 보고함 테스트 계정 질문은
// 4단계를 그 질문의 키로 연다 (진행 기록은 이어 쓴다)
import { describe, expect, test, vi } from "vitest";

vi.mock("../rpc/client", async (original) => {
  const mod = await original<typeof import("../rpc/client")>();
  const wizard = { format: "kookabug.wizard/0", step: 9, done: [1, 2, 3, 5, 6, 9], skipped: [], warnings: [] };
  return { ...mod, client: () => ({ call: async (method: string) => (method === "wizard.get" ? { wizard } : {}) }) };
});

const { openCredentialStep, openSetupStep } = await import("./ShortWizardWatch");
const { HELPER_ONLY, STEPS, useWizard } = await import("./wizardStore");

describe("설정 도우미에서 뺀 단계 열기", () => {
  test("계정·정책·기록은 설정 도우미 목록에 있고 그 단계 하나로 열린다", async () => {
    const listed = STEPS.filter((s) => s.n >= 1 && s.n <= 8).map((s) => s.n);
    for (const n of HELPER_ONLY) {
      expect(listed).toContain(n);
      await openSetupStep(n);
      const s = useWizard.getState();
      expect(s.open).toBe(true);
      expect(s.progress).toMatchObject({ mode: "only", steps: [n], step: n });
      // 끝낸 마법사 기록은 이어 쓴다 (지우지 않는다)
      expect(s.progress.done).toEqual([1, 2, 3, 5, 6, 9]);
      expect(s.credential).toBeNull();
    }
  });

  test("보고함 테스트 계정 질문 → 4단계를 그 키로 연다", async () => {
    await openCredentialStep({ unknown: "u-20261113-000000-cccc", rev: 2, keys: ["login.id", "login.password"], question: "로그인" });
    const s = useWizard.getState();
    expect(s.progress).toMatchObject({ mode: "only", steps: [4], step: 4 });
    expect(s.credential).toEqual({ unknown: "u-20261113-000000-cccc", rev: 2, keys: ["login.id", "login.password"], question: "로그인" });
    // 다른 단계를 열면 질문 맥락은 남지 않는다
    await openSetupStep(7);
    expect(useWizard.getState().credential).toBeNull();
  });
});
