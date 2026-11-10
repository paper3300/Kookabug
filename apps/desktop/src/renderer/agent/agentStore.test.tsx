// 에이전트 패널 대화 모델 (M5 계획 3.10): 조각 이어 붙이기·도구 호출 접기·권한 카드·취소, 확인 요청 라우팅
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import { ApprovalCardView } from "./AgentPanel";
import {
  applyEvent,
  approvalButtons,
  belongsToSession,
  fromEndedSession,
  pendingCount,
  effectivePreset,
  leaseRefused,
  promptText,
  splitCommandLine,
  toolsRunning,
  toolsSummary,
  type ApprovalRequest,
  type ChatItem,
  type PermissionsInfo,
} from "./agentStore";

function run(events: Parameters<typeof applyEvent>[1][], start: ChatItem[] = []): ChatItem[] {
  let items = start;
  let t = 1000;
  for (const e of events) items = applyEvent(items, e, (t += 1000));
  return items;
}

const tool = (id: string, status: string, title = "kb_graph_get") =>
  ({ type: "tool", id, title, status, kind: "read", failed: status === "failed", text: "" }) as const;

describe("대화 모델", () => {
  test("받은 조각은 마지막 답에 이어 붙이고, 도구 호출 뒤 말은 새 답", () => {
    const items = run([
      { type: "message", text: "그래프를 " },
      { type: "message", text: "볼게요." },
      tool("t1", "in_progress"),
      { type: "message", text: "다 봤어요" },
    ]);
    expect(items.map((i) => i.kind)).toEqual(["agent", "tools", "agent"]);
    expect(items[0]).toMatchObject({ text: "그래프를 볼게요." });
    expect(items[2]).toMatchObject({ text: "다 봤어요" });
  });

  test("도구 호출은 한 줄로 접는다: 같은 ID는 고치고, 진행 중이면 펼침, 생각 조각은 개수만", () => {
    const items = run([
      tool("t1", "in_progress"),
      tool("t2", "pending", "kb_graph_patch"),
      { type: "hidden", kind: "agent_thought_chunk" },
      tool("t1", "completed"),
    ]);
    expect(items).toHaveLength(1);
    const line = items[0] as Extract<ChatItem, { kind: "tools" }>;
    expect(line.tools.map((t) => [t.id, t.status])).toEqual([
      ["t1", "completed"],
      ["t2", "pending"],
    ]);
    expect(line.hidden).toBe(1);
    expect(toolsRunning(line)).toBe(true);
    expect(toolsSummary(line)).toBe("작업 3초 · 도구 2개");
    const done = run([tool("t2", "completed", "kb_graph_patch")], items)[0] as Extract<ChatItem, { kind: "tools" }>;
    expect(toolsRunning(done)).toBe(false);
    // 말이 끼어든 뒤의 같은 도구 갱신도 원래 줄을 고친다
    const later = run([{ type: "message", text: "중간" }, tool("t2", "failed", "kb_graph_patch")], items);
    expect(later.map((i) => i.kind)).toEqual(["tools", "agent"]);
    expect((later[0] as Extract<ChatItem, { kind: "tools" }>).tools[1]).toMatchObject({ status: "failed", failed: true });
  });

  test("권한 요청은 열린 카드로 들어오고, 닫힘(선택·취소)만 카드 상태를 바꾼다", () => {
    const options = [
      { id: "a", name: "허용", kind: "allow_once" },
      { id: "r", name: "거부", kind: "reject_once" },
    ];
    const opened = run([{ type: "permission", id: "perm1", title: "파일 편집", options }]);
    expect(opened[0]).toMatchObject({ kind: "acp_permission", state: "open", chosen: null, options });
    const chosen = run([{ type: "permission_closed", id: "perm1", outcome: "selected", optionId: "r" }], opened);
    expect(chosen[0]).toMatchObject({ state: "selected", chosen: "r" });
    // 중지·세션 끝 = cancelled
    const cancelled = run([{ type: "permission_closed", id: "perm1", outcome: "cancelled" }], opened);
    expect(cancelled[0]).toMatchObject({ state: "cancelled", chosen: null });
  });

  test("임대권 거부는 도구 결과 글자로 알아본다", () => {
    expect(leaseRefused({ ...tool("t", "failed", "kb_input_click"), text: "input_lease_busy: 입력 임대권" })).toBe(true);
    expect(leaseRefused(tool("t", "failed"))).toBe(false);
    expect(leaseRefused({ type: "message", text: "input_lease_busy" })).toBe(false);
  });
});

describe("확인 요청 라우팅", () => {
  const request = (agentId: string): ApprovalRequest => ({
    id: "a".repeat(32),
    connection: 3,
    agent: { id: agentId, name: "panel" },
    tool: "kb_graph_patch",
    method: "graph.patch",
    arg: "tests/a.graph.json",
    summary: ["set_meta 1"],
    always_rule: "kb_graph_patch(tests/a.graph.json)",
    previewable: true,
    expires_at: "2026-11-06T00:00:00.000Z",
    session: null,
  });

  test("panel:<세션>이면 그 세션 대화, 아니면 외부 에이전트", () => {
    expect(belongsToSession(request("panel:p1ab"), "p1ab")).toBe(true);
    expect(belongsToSession(request("panel:p2cd"), "p1ab")).toBe(false);
    expect(belongsToSession(request("mcp:1234"), "p1ab")).toBe(false);
    expect(belongsToSession(request("panel:p1ab"), null)).toBe(false);
  });
});

describe("도우미", () => {
  test("promptText: 칩 글자를 앞에", () => {
    expect(promptText(" 분석해 줘 ", [])).toBe("분석해 줘");
    expect(promptText("분석해 줘", [{ kind: "run", label: "@run #ab", text: "[첨부: 실행]" }])).toBe("[첨부: 실행]\n\n분석해 줘");
  });

  test("splitCommandLine: 큰따옴표 칸은 한 인자", () => {
    expect(splitCommandLine('npx "my agent" --acp')).toEqual(["npx", "my agent", "--acp"]);
    expect(splitCommandLine("   ")).toEqual([]);
  });

  test("effectivePreset: 프로젝트 → 사용자 → 팀, 없으면 graph_author", () => {
    const info = (layers: [string, unknown][]): PermissionsInfo =>
      ({
        principal: { kind: "agent", id: "x", attended: true },
        tools: [],
        layers: layers.map(([layer, permissions]) => ({
          layer,
          permissions,
          source: null,
          revision: null,
          diagnostics: [],
          editable: layer !== "team",
        })),
      }) as PermissionsInfo;
    expect(effectivePreset(null)).toBe("graph_author");
    expect(effectivePreset(info([["project", null], ["user", { preset: "runner" }], ["team", { preset: "full" }]]))).toBe("runner");
    expect(effectivePreset(info([["project", { preset: "read_only" }], ["user", { preset: "runner" }]]))).toBe("read_only");
  });
});

describe("끝난 세션의 확인 요청 (검수 H1)", () => {
  const req = (agentId: string) => ({ agent: { id: agentId, name: "panel" } }) as ApprovalRequest;
  test("패널 세션이 끝났거나 다른 세션이면 단추를 막는다, 외부 에이전트는 무관", () => {
    const live = { id: "p1ab", agentId: "a", name: "A", status: "ready" as const, config: [] };
    expect(fromEndedSession(req("panel:p1ab"), live)).toBe(false);
    expect(fromEndedSession(req("panel:p1ab"), { ...live, status: "ended" })).toBe(true);
    expect(fromEndedSession(req("panel:p0zz"), live)).toBe(true);
    expect(fromEndedSession(req("panel:p1ab"), null)).toBe(true);
    expect(fromEndedSession(req("mcp:123"), null)).toBe(false);
  });
});

describe("확인 카드 단추 — 이 탐색 동안 허용 (M7 3.11 B3)", () => {
  const SESSION = { id: "20261107-101500-ab12", title: "예제 탐색" };
  const ask = (tool: string, method: string, always: string | null, session: typeof SESSION | null): ApprovalRequest => ({
    id: "ap_0123456789abcdef",
    connection: 4,
    agent: { id: "mcp:1", name: "mcp" },
    tool: tool as ApprovalRequest["tool"],
    method: method as ApprovalRequest["method"],
    arg: tool.startsWith("kb_input_") ? "SampleRPG" : "",
    summary: ["창 'SampleRPG' 클릭"],
    always_rule: always,
    previewable: false,
    expires_at: "2026-11-07T00:00:00.000Z",
    session,
  });
  const verdicts = (r: ApprovalRequest) => approvalButtons(r).map((b) => b.verdict);
  const labels = (r: ApprovalRequest) => approvalButtons(r).map((b) => b.label);

  test("게임 조작 + 탐색 세션: 허용 / 이 탐색 동안 허용 (항상 허용 없음)", () => {
    const r = ask("kb_input_click", "control.click", null, SESSION);
    expect(labels(r)).toEqual(["허용", "이 탐색 동안 허용"]);
    expect(verdicts(r)).toEqual(["allow_once", "allow_session"]);
  });

  test("게임 실행은 탐색 세션이 있어도 이 탐색 동안 허용이 없다 (B3 검수 Low 3)", () => {
    expect(verdicts(ask("kb_app_launch", "app.launch", null, SESSION))).toEqual(["allow_once"]);
  });

  test("게임 조작은 daemon이 규칙을 줘도 항상 허용을 그리지 않는다", () => {
    const r = ask("kb_input_key", "control.key", "kb_input_key(SampleRPG)", SESSION);
    expect(verdicts(r)).not.toContain("allow_always");
  });

  test("화면 지도 쓰기 + 탐색 세션: 한 번 허용 / 이 탐색 동안 허용 / 항상 허용", () => {
    const r = ask("kb_screen_save", "screens.save", "kb_screen_save()", SESSION);
    expect(labels(r)).toEqual(["한 번 허용", "이 탐색 동안 허용", "항상 허용"]);
  });

  test("탐색 세션이 없으면 이 탐색 동안 허용 단추가 없다 (M5 카드 그대로)", () => {
    expect(labels(ask("kb_input_click", "control.click", null, null))).toEqual(["한 번 허용"]);
    expect(labels(ask("kb_graph_patch", "graph.patch", "kb_graph_patch(tests/a.graph.json)", null))).toEqual([
      "한 번 허용",
      "항상 허용",
    ]);
  });

  test("카드 렌더: 세션 안내와 단추 (거부는 늘 따로)", () => {
    const card = { request: ask("kb_input_click", "control.click", null, SESSION), state: "open", busy: false, error: null } as const;
    const html = renderToStaticMarkup(<ApprovalCardView card={card} />);
    expect(html).toContain('data-verdict="allow_session"');
    expect(html).toContain("이 탐색 동안 허용");
    expect(html).toContain("예제 탐색");
    expect(html).not.toContain('data-verdict="allow_always"');
    expect(html).toContain("거부");
    const done = { ...card, state: "allow_session" } as const;
    expect(renderToStaticMarkup(<ApprovalCardView card={done} />)).toContain("이 탐색 동안 허용했어요");
  });
});

describe("승인 대기 수 (검수 B5 M1)", () => {
  test("열린 ACP 카드 + 열린 Kookabug 카드", () => {
    const items = run([
      { type: "permission", id: "perm1", title: "a", options: [] },
      { type: "permission", id: "perm2", title: "b", options: [] },
      { type: "permission_closed", id: "perm2", outcome: "cancelled" },
    ]);
    const card = (state: string) => ({ request: {} as ApprovalRequest, state, busy: false, error: null }) as never;
    const approvals = new Map([
      ["x", card("open")],
      ["y", card("deny")],
      ["z", card("open")],
    ]);
    expect(pendingCount({ items, approvals })).toBe(3);
    expect(pendingCount({ items: [], approvals: new Map() })).toBe(0);
  });
});
