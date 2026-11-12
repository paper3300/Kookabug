// 이전 대화 (UX4): 저장 줄 변환·맥락 요약·ID, 다시 열기 두 경로(loadSession 있음·없음), 지우기, 목록 그리기
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, test } from "vitest";
import { HistoryList } from "./AgentPanel";
import {
  continuationContext,
  continueConversation,
  deleteConversation,
  endSession,
  fromSavedItems,
  newConversation,
  switchAgent,
  initAgent,
  newConversationId,
  resetAgent,
  setAgentRootSource,
  openConversation,
  sendPrompt,
  setDraft,
  toSavedItems,
  useAgent,
  type ApprovalCard,
  type ChatItem,
  type SavedItem,
} from "./agentStore";

const calls: { method: string; params: Record<string, unknown> }[] = [];
const starts: { agentId: string; load: string | null; root: string }[] = [];
let root = "C:/ws/A";
/** conversations.save를 붙잡아 둘 때 (검수 재현: 저장 대기 중 프로젝트 전환) */
let holdSave: { reject(e: unknown): void } | null = null;
let holding = false;
/** agentStart를 붙잡아 둘 때 (시작 대기 중 프로젝트 전환) */
let holdStart: (() => void) | null = null;
let holdingStart = false;
const stops: string[] = [];
const prompts: string[] = [];
let canLoad = false;
let stored: Record<string, unknown> = {};

const CONV = {
  format: "kookabug.conversation/0",
  id: "c-20261112-101010-abcd",
  title: "로비 테스트 만들어 줘",
  agent_id: "fake",
  agent_name: "가짜",
  acp_session: "old-s",
  created_at: "2026-11-12T01:00:00Z",
  updated_at: "2026-11-12T01:05:00Z",
  items: [
    { kind: "user", text: "로비 테스트 만들어 줘", chips: [] },
    { kind: "agent", text: "만들었어요" },
    { kind: "tools", tools: [{ title: "kb_graph_create", status: "completed", failed: false }], hidden: 1, seconds: 3 },
    { kind: "approval", title: "kb_run_start", outcome: "allow_once" },
  ],
};

(globalThis as unknown as { window: unknown }).window = globalThis;
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  async rpc(method: string, params: Record<string, unknown>) {
    calls.push({ method, params });
    if (method === "conversations.get") return { conversation: stored[params.id as string] ?? CONV };
    if (method === "conversations.list") return { conversations: [] };
    if (method === "conversations.delete") return { deleted: true };
    if (method === "conversations.save") {
      if (holding) return new Promise((_, reject) => (holdSave = { reject }));
      return { conversation: {} };
    }
    return {};
  },
  on: () => () => {},
  app: {
    async agentStart(agentId: string, load: string | null, wsRoot: string) {
      starts.push({ agentId, load, root: wsRoot });
      if (holdingStart) await new Promise<void>((r) => (holdStart = r));
      return { session: `p${starts.length}`, agentId, name: "가짜", config: [], acpSession: canLoad && load ? load : "new-s", loaded: canLoad && load !== null };
    },
    async agentStop(session: string) {
      stops.push(session);
    },
    async agentPrompt(_session: string, text: string) {
      prompts.push(text);
      return { stopReason: "end_turn" };
    },
  },
};

setAgentRootSource(() => root);
initAgent();

beforeEach(() => {
  root = "C:/ws/A";
  holding = false;
  holdSave = null;
  holdingStart = false;
  holdStart = null;
  stops.length = 0;
  calls.length = 0;
  starts.length = 0;
  prompts.length = 0;
  stored = {};
  useAgent.setState({
    session: null,
    items: [],
    agents: [{ id: "fake", name: "가짜", command: "x" }] as never,
    defaultAgent: "fake",
    conversationId: null,
    readOnly: false,
    pendingContext: null,
    historyOpen: true,
  });
});

describe("저장 줄", () => {
  test("화면 줄 ↔ 저장 줄: 메시지·도구 요약·권한 카드 결과·확인 요청 결과·오류", () => {
    const items: ChatItem[] = [
      { kind: "user", key: 1, text: "해 줘", chips: ["@run abcd"] },
      { kind: "agent", key: 2, text: "네" },
      { kind: "tools", key: 3, started: 1000, updated: 4000, tools: [{ id: "t", title: "kb_run_start", status: "completed", failed: false }], hidden: 2, open: null },
      { kind: "acp_permission", key: 4, id: "perm1", title: "파일 쓰기", options: [{ id: "y", name: "허용", kind: "allow_once" }], state: "selected", chosen: "y" },
      { kind: "approval", key: 5, id: "a1" },
      { kind: "error", key: 6, text: "끊겼어요", restart: true },
    ];
    const approvals = new Map<string, ApprovalCard>([["a1", { request: { tool: "kb_input_click" } as never, state: "deny", busy: false, error: null }]]);
    const saved = toSavedItems(items, approvals);
    expect(saved).toEqual([
      { kind: "user", text: "해 줘", chips: ["@run abcd"] },
      { kind: "agent", text: "네" },
      { kind: "tools", tools: [{ title: "kb_run_start", status: "completed", failed: false }], hidden: 2, seconds: 3 },
      { kind: "permission", title: "파일 쓰기", outcome: "selected", chosen: "허용" },
      { kind: "approval", title: "kb_input_click", outcome: "deny" },
      { kind: "error", text: "끊겼어요" },
    ]);
    const back = fromSavedItems(saved);
    expect(back.map((i) => i.kind)).toEqual(["user", "agent", "tools", "acp_permission", "past_approval", "error"]);
    expect(back[3]).toMatchObject({ state: "selected", chosen: "허용", options: [{ name: "허용" }] });
    expect(toSavedItems(back, new Map())).toEqual(saved);
  });

  test("맥락 요약: 마지막 N개 메시지, 크기 상한", () => {
    const saved: SavedItem[] = Array.from({ length: 30 }, (_, i) => ({ kind: i % 2 === 0 ? "user" : "agent", text: `m${i}` }) as SavedItem);
    const text = continuationContext(saved, 4);
    expect(text).toContain("사용자: m26");
    expect(text).toContain("Agent: m29");
    expect(text).not.toContain("m25");
    const big = continuationContext([{ kind: "agent", text: "x".repeat(5000) }, { kind: "user", text: "끝" }], 20, 100);
    expect(big).toContain("사용자: 끝");
    expect(big).not.toContain("xxxx");
  });

  test("ID 형식", () => {
    expect(newConversationId(new Date(2026, 10, 12, 9, 8, 7), () => 0.5)).toBe("c-20261112-090807-8000");
  });
});

describe("다시 열기", () => {
  test("loadSession 지원: session/load로 이어 가고 입력할 수 있다", async () => {
    canLoad = true;
    await openConversation(CONV.id);
    expect(starts).toEqual([{ agentId: "fake", load: "old-s", root: "C:/ws/A" }]);
    const s = useAgent.getState();
    expect(s.readOnly).toBe(false);
    expect(s.conversationId).toBe(CONV.id);
    expect(s.items.map((i) => i.kind)).toEqual(["user", "agent", "tools", "past_approval"]);
    expect(s.session?.loaded).toBe(true);
  });

  test("지원하지 않음: 읽기 전용, 이어 하기를 누르면 첫 메시지에 지난 대화 요약을 붙인다", async () => {
    canLoad = false;
    await openConversation(CONV.id);
    expect(useAgent.getState().readOnly).toBe(true);
    setDraft("계속해");
    await sendPrompt();
    expect(prompts).toEqual([]); // 읽기 전용에서는 보내지 않는다
    await continueConversation();
    expect(useAgent.getState()).toMatchObject({ readOnly: false });
    setDraft("계속해");
    await sendPrompt();
    expect(prompts).toHaveLength(1);
    expect(prompts[0]).toContain("[지난 대화 요약");
    expect(prompts[0]).toContain("사용자: 로비 테스트 만들어 줘");
    expect(prompts[0]!.endsWith("계속해")).toBe(true);
    // 화면에는 사람이 쓴 글만, 다음 메시지에는 요약을 다시 붙이지 않는다
    expect(useAgent.getState().items.at(-1)).toMatchObject({ kind: "user", text: "계속해" });
    setDraft("하나 더");
    await sendPrompt();
    expect(prompts[1]).toBe("하나 더");
  });

  test("지우기는 daemon에 지우고 목록을 다시 읽는다, 지운 대화가 지금 대화면 새 대화로", async () => {
    useAgent.setState({ conversationId: CONV.id });
    await deleteConversation(CONV.id);
    expect(calls.map((c) => c.method)).toEqual(["conversations.delete", "conversations.list"]);
    expect(useAgent.getState().conversationId).toBeNull();
  });
});

describe("프로젝트 전환·다른 Agent (검수 1)", () => {
  test("H2 재현: A에서 열기 → 저장 대기 → B로 전환 → 저장 실패: Agent를 시작하지 않고 B 화면에 A 대화가 없다", async () => {
    // A에서 대화 중 (저장 대기 상태를 만든다)
    useAgent.setState({ conversationId: "c-20261112-000000-0001", items: [{ kind: "user", key: 900, text: "A 대화", chips: [] }] });
    holding = true;
    const opening = openConversation(CONV.id);
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.map((c) => c.method)).toEqual(["conversations.get", "conversations.save"]);
    // 프로젝트 B로 전환 (switchProject → resetAgent, 루트 바뀜), 끊긴 저장은 실패
    resetAgent();
    root = "C:/ws/B";
    useAgent.setState({ agents: [{ id: "fake", name: "가짜", command: "x" }] as never, defaultAgent: "fake" });
    holdSave!.reject({ code: -32000, message: "not_connected" });
    await opening;
    expect(starts).toEqual([]);
    const s = useAgent.getState();
    expect(s.items).toEqual([]);
    expect(s.conversationId).toBeNull();
    expect(s.readOnly).toBe(false);
  });

  test("H2: 시작을 기다리는 동안 프로젝트가 바뀌면 그 세션은 버린다", async () => {
    canLoad = true;
    holdingStart = true;
    const opening = openConversation(CONV.id);
    for (let i = 0; i < 5 && holdStart === null; i++) await new Promise((r) => setTimeout(r, 0));
    expect(starts).toEqual([{ agentId: "fake", load: "old-s", root: "C:/ws/A" }]);
    resetAgent();
    root = "C:/ws/B";
    holdStart!();
    await opening;
    // 열린 세션은 바로 끝내고 화면에 붙이지 않는다
    expect(stops).toContain(`p${starts.length}`);
    const s = useAgent.getState();
    expect(s.session).toBeNull();
    expect(s.items).toEqual([]);
    expect(s.readOnly).toBe(false);
  });

  test("M3: 저장한 Agent가 설정에 없으면 세션 ID를 넘기지 않고 읽기 전용", async () => {
    canLoad = true;
    stored[CONV.id] = { ...CONV, agent_id: "removed-agent" };
    useAgent.setState({ agents: [{ id: "new-agent", name: "새", command: "x" }] as never, defaultAgent: "new-agent" });
    await openConversation(CONV.id);
    expect(starts).toEqual([{ agentId: "new-agent", load: null, root: "C:/ws/A" }]);
    expect(useAgent.getState().readOnly).toBe(true);
    // 이어 하기는 새 세션에 가린(저장된) 요약
    await continueConversation();
    setDraft("이어서");
    await sendPrompt();
    expect(prompts.at(-1)).toContain("사용자: 로비 테스트 만들어 줘");
  });
});

describe("모든 진입점의 세대·루트 검사 (검수 2 H1)", () => {
  const A_SESSION = { id: "A-session", agentId: "fake", name: "가짜", status: "ready" as const, config: [], acpSession: "a", loaded: false };
  const B_SESSION = { ...A_SESSION, id: "B-session", acpSession: "b" };
  const B_ITEMS: ChatItem[] = [{ kind: "user", key: 991, text: "B 대화", chips: [] }];

  /** A에서 대화 중 + 저장 대기(타이머) 상태를 만들고 저장 응답을 붙잡는다 */
  function pendingInA(): void {
    useAgent.setState({ session: A_SESSION, conversationId: "c-20261112-000000-000a", items: [{ kind: "user", key: 990, text: "A 대화", chips: [] }] });
    holding = true;
  }

  /** 프로젝트 B로 전환 (switchProject → resetAgent, 루트 바뀜) 뒤 B의 세션·대화 */
  function switchToB(): void {
    resetAgent();
    root = "C:/ws/B";
    stops.length = 0;
    useAgent.setState({ session: B_SESSION, items: B_ITEMS, agents: [{ id: "fake", name: "가짜", command: "x" }] as never, defaultAgent: "fake" });
  }

  const tick = () => new Promise((r) => setTimeout(r, 0));

  function expectBUntouched(): void {
    expect(starts).toEqual([]);
    expect(stops).toEqual([]);
    const s = useAgent.getState();
    expect(s.session?.id).toBe("B-session");
    expect(s.items).toBe(B_ITEMS);
  }

  test("newConversation: 저장 대기 → B 전환 → 저장 실패 — B 세션을 끄거나 새로 열지 않고 B 화면 그대로", async () => {
    pendingInA();
    const running = newConversation();
    await tick();
    expect(calls.map((c) => c.method)).toEqual(["conversations.save"]);
    switchToB();
    holdSave!.reject({ code: -32000, message: "not_connected" });
    await running;
    expectBUntouched();
  });

  test("switchAgent: 확인 대화 중 B 전환 / 저장 대기 중 B 전환 — 둘 다 B 그대로", async () => {
    // 확인 대화를 기다리는 동안 전환
    useAgent.setState({ session: A_SESSION, items: [{ kind: "user", key: 989, text: "A", chips: [] }] });
    let answer: (ok: boolean) => void = () => {};
    const asked = switchAgent("other", () => new Promise<boolean>((r) => (answer = r)));
    await tick();
    switchToB();
    answer(true);
    await asked;
    expectBUntouched();
    // 저장을 기다리는 동안 전환
    root = "C:/ws/A";
    pendingInA();
    const saving = switchAgent("other", async () => true);
    await tick();
    expect(calls.at(-1)?.method).toBe("conversations.save");
    switchToB();
    holdSave!.reject({ code: -32000, message: "not_connected" });
    await saving;
    expectBUntouched();
  });

  test("endSession: 저장 대기 → B 전환 → 저장 실패 — B 세션을 끄지 않는다", async () => {
    pendingInA();
    const ending = endSession();
    await tick();
    switchToB();
    holdSave!.reject({ code: -32000, message: "not_connected" });
    await ending;
    expectBUntouched();
    expect(useAgent.getState().userEnded).toBe(false);
  });

  test("같은 프로젝트에서는 그대로 동작: 새 대화는 저장 뒤 같은 Agent로 새 세션", async () => {
    useAgent.setState({ session: A_SESSION, conversationId: "c-20261112-000000-000b", items: [{ kind: "user", key: 988, text: "A", chips: [] }] });
    await newConversation();
    expect(calls[0]?.method).toBe("conversations.save");
    expect(stops).toEqual(["A-session"]);
    expect(starts).toEqual([{ agentId: "fake", load: null, root: "C:/ws/A" }]);
    expect(useAgent.getState().items).toEqual([]);
  });
});

describe("목록", () => {
  test("제목·날짜·Agent·지우기, 지금 대화 표시, 비면 안내", () => {
    const row = { id: CONV.id, title: CONV.title, agent_id: "fake", agent_name: "가짜", created_at: CONV.created_at, updated_at: CONV.updated_at, count: 4 };
    const html = renderToStaticMarkup(<HistoryList list={[row]} error={null} current={CONV.id} />);
    expect(html).toContain("로비 테스트 만들어 줘");
    expect(html).toContain("가짜");
    expect(html).toMatch(/2026-11-12 \d\d:05/);
    expect(html).toContain('data-current="true"');
    expect(html).toContain('data-part="agent-history-delete"');
    expect(renderToStaticMarkup(<HistoryList list={[]} error={null} current={null} />)).toContain("저장한 대화가 없어요");
  });
});
