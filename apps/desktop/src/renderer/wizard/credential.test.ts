// UX5 보고함 테스트 계정 질문 → 4단계 "등록" → 질문 답함. 값은 등록(주 프로세스)으로만 가고 답 글에는 없다
import { describe, expect, test } from "vitest";
import { ANSWER_TEXT, askReady, registerAsk, secretInputOk } from "./credential";

const ASK = { unknown: "u-20261113-000000-cccc", rev: 2, keys: ["login.id", "login.password"], question: "로그인 화면" };
const VALUES = { "login.id": "qa_tester", "login.password": "ux5-pass Zq81!" };

describe("테스트 계정 등록", () => {
  test("키를 모두 채워야 등록 (이미 저장된 키는 비워도 된다)", () => {
    expect(askReady(ASK, {}, [])).toBe(false);
    expect(askReady(ASK, { "login.id": "qa" }, [])).toBe(false);
    expect(askReady(ASK, VALUES, [])).toBe(true);
    expect(askReady(ASK, { "login.id": "qa" }, ["login.password"])).toBe(true);
    expect(askReady(ASK, { ...VALUES, "login.password": "a\nb" }, [])).toBe(false);
    expect(secretInputOk("bad key", "v")).toBe(false);
  });

  test("등록 → 답함: 값은 등록에만, 답 글은 고정 글", async () => {
    const registered: [string, string][] = [];
    const answered: unknown[] = [];
    await registerAsk(ASK, VALUES, [], {
      register: async (k, v) => registered.push([k, v]),
      answer: async (id, rev, text) => answered.push({ id, rev, text }),
    });
    expect(registered).toEqual(Object.entries(VALUES));
    expect(answered).toEqual([{ id: ASK.unknown, rev: 2, text: ANSWER_TEXT }]);
    expect(JSON.stringify(answered)).not.toContain(VALUES["login.password"]);
  });

  test("등록이 하나라도 실패하면 답하지 않는다 / 저장된 키는 비우면 건너뛴다", async () => {
    const answered: unknown[] = [];
    await expect(
      registerAsk(ASK, VALUES, [], {
        register: async (k) => {
          if (k === "login.password") throw new Error("io_error");
        },
        answer: async (...a) => answered.push(a),
      }),
    ).rejects.toThrow();
    expect(answered).toEqual([]);
    const registered: string[] = [];
    await registerAsk(ASK, { "login.id": "qa" }, ["login.password"], {
      register: async (k) => registered.push(k),
      answer: async (...a) => answered.push(a),
    });
    expect(registered).toEqual(["login.id"]);
    expect(answered).toHaveLength(1);
  });
});
