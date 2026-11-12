// 닫기·떠나기의 마지막 대화 저장 기한 (UX4 검수 2 H2): 저장 응답이 오지 않아도 가상 1.5초 뒤 창 닫기·프로젝트 떠나기가 끝나고,
// 늦게 끝난 저장은 새 상태를 바꾸지 않는다
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { FLUSH_LIMIT_MS, initAgent, resetAgent, useAgent } from "../agent/agentStore";
import { canLeave, useWorkspace } from "../store/workspace";
import { confirmClose } from "./closeFlow";

const calls: string[] = [];
let held: { resolve(v: unknown): void }[] = [];

(globalThis as unknown as { window: unknown }).window = globalThis;
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc(method: string) {
    calls.push(method);
    if (method === "conversations.save") return new Promise((resolve) => held.push({ resolve }));
    return new Promise(() => {});
  },
  on: () => () => {},
  app: {},
};

initAgent();

/** 저장할 대화가 있고 자동 저장 타이머가 걸린 상태 */
function pendingConversation(): void {
  useAgent.setState({
    conversationId: "c-20261112-000000-00cc",
    readOnly: false,
    items: [{ kind: "user", key: 1, text: "저장할 대화", chips: [] }],
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  calls.length = 0;
  held = [];
  useWorkspace.setState({ root: "C:/ws/A" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("마지막 저장 기한", () => {
  test("창 닫기: 저장 응답을 보류해도 1.5초 뒤 닫기 답(true)", async () => {
    pendingConversation();
    let answered: boolean | null = null;
    void confirmClose().then((ok) => (answered = ok));
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toEqual(["conversations.save"]);
    await vi.advanceTimersByTimeAsync(FLUSH_LIMIT_MS - 1);
    expect(answered).toBeNull();
    await vi.advanceTimersByTimeAsync(1);
    expect(answered).toBe(true);
    expect(FLUSH_LIMIT_MS).toBe(1500);
  });

  test("프로젝트 떠나기: 저장 응답을 보류해도 1.5초 뒤 떠나기 확인이 끝나고, 늦은 저장은 새 프로젝트를 바꾸지 않는다", async () => {
    pendingConversation();
    useAgent.setState({ historyOpen: true, history: null });
    let left: boolean | null = null;
    void canLeave().then((ok) => (left = ok));
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toEqual(["conversations.save"]);
    await vi.advanceTimersByTimeAsync(FLUSH_LIMIT_MS);
    expect(left).toBe(true);
    // 전환 (switchProject → resetAgent, 루트 B). 그 뒤 앞 저장이 늦게 끝나도 목록을 다시 읽거나 화면을 바꾸지 않는다
    resetAgent();
    useWorkspace.setState({ root: "C:/ws/B" });
    useAgent.setState({ historyOpen: true });
    const before = useAgent.getState();
    held[0]!.resolve({ conversation: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toEqual(["conversations.save"]);
    expect(useAgent.getState()).toBe(before);
  });

  test("저장할 것이 없으면 기다리지 않는다", async () => {
    useAgent.setState({ conversationId: null, items: [] });
    await vi.advanceTimersByTimeAsync(1000);
    let left: boolean | null = null;
    void canLeave().then((ok) => (left = ok));
    await vi.advanceTimersByTimeAsync(0);
    expect(left).toBe(true);
    expect(calls).toEqual([]);
  });
});
