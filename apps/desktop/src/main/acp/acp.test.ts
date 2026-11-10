// ACP 클라이언트 (M5 계획 3.10): 가짜 에이전트 프로세스로 initialize·session/new·prompt·권한 카드·취소를 본다
import { describe, expect, test } from "vitest";
import type { AgentEvent } from "./events";
import { AgentHost, hostArgs, parseAgentOverride, type SpawnRequest } from "./host";
import { CLIENT_CAPABILITIES, parseSessionConfig, type AgentProcess } from "./session";

/** 주 프로세스가 쓴 줄을 받아 각본대로 답하는 가짜 에이전트 */
class FakeProc implements AgentProcess {
  readonly received: { id?: number | string; method?: string; params?: unknown; result?: unknown; error?: unknown }[] = [];
  /** session/new 결과에 더할 값 (configOptions·models 검사) */
  sessionExtra: Record<string, unknown> = {};
  /** session/set_* 요청 답 (없으면 빈 객체) */
  setResult: unknown = {};
  killed = false;
  /** false면 kill() 뒤 끝남 알림을 바로 보내지 않는다 (도우미가 Job을 정리하는 동안) */
  exitOnKill = true;
  private out: (chunk: string) => void = () => {};
  private exit: (code: number | null, message: string) => void = () => {};
  onPrompt: (id: number | string) => void = (id) => this.reply(id, { stopReason: "end_turn" });

  write(line: string): void {
    const msg = JSON.parse(line) as (typeof this.received)[number];
    this.received.push(msg);
    if (msg.method === "initialize") this.reply(msg.id!, { protocolVersion: 1, agentCapabilities: {} });
    else if (msg.method === "session/new") this.reply(msg.id!, { sessionId: "s1", ...this.sessionExtra });
    else if (msg.method?.startsWith("session/set_") === true) this.reply(msg.id!, this.setResult);
    else if (msg.method === "session/prompt") this.onPrompt(msg.id!);
  }
  onStdout(cb: (chunk: string) => void): void {
    this.out = cb;
  }
  onExit(cb: (code: number | null, message: string) => void): void {
    this.exit = cb;
  }
  kill(): void {
    this.killed = true;
    if (this.exitOnKill) this.exit(1, "killed");
  }
  /** 도우미가 끝났다 (Job 정리 끝) */
  exited(code: number | null, message: string): void {
    this.exit(code, message);
  }
  send(msg: object, split = false): void {
    const text = JSON.stringify({ jsonrpc: "2.0", ...msg }) + "\n";
    if (!split) return this.out(text);
    // 줄이 조각으로 와도 이어 붙여 읽는다
    this.out(text.slice(0, 7));
    this.out(text.slice(7));
  }
  reply(id: number | string, result: unknown): void {
    queueMicrotask(() => this.send({ id, result }));
  }
  update(update: object): void {
    this.send({ method: "session/update", params: { sessionId: "s1", update } }, true);
  }
}

function host(proc: FakeProc, overrides: Partial<ConstructorParameters<typeof AgentHost>[0]> = {}) {
  const events: AgentEvent[] = [];
  const spawned: SpawnRequest[] = [];
  const h = new AgentHost({
    agents: async () => [{ id: "fake", name: "가짜", command: "fake-agent", args: ["--acp"], env: { EXTRA: "1", TOKEN: { $secret: "k" } } }],
    cli: () => "C:/kb/kookabug.exe",
    root: () => "C:/ws",
    baseEnv: { PATH: "C:/bin", KOOKABUG_SESSION_TOKEN: "t0p", kookabug_pipe: "x", HOME: "h" },
    override: null,
    spawn: (r) => {
      spawned.push(r);
      return proc;
    },
    emit: (e) => events.push(e.event),
    ...overrides,
  });
  return { h, events, spawned };
}

describe("ACP 세션", () => {
  test("initialize·session/new: 능력 fs·terminal false, MCP 서버는 kookabug mcp 하나, 도우미(agent-host)로 띄운다", async () => {
    const proc = new FakeProc();
    const { h, spawned } = host(proc);
    const started = await h.start("fake");
    expect(started).toMatchObject({ agentId: "fake", name: "가짜" });
    const [init, created] = proc.received;
    expect(init).toMatchObject({ method: "initialize", params: { protocolVersion: 1, clientCapabilities: CLIENT_CAPABILITIES } });
    expect(created).toMatchObject({
      method: "session/new",
      params: {
        cwd: "C:/ws",
        mcpServers: [
          {
            name: "kookabug",
            command: "C:/kb/kookabug.exe",
            args: ["mcp", "--workspace", "C:/ws", "--agent-id", `panel:${started.session}`, "--client", "panel"],
            env: [],
          },
        ],
      },
    });
    // 에이전트는 도우미가 Job에 넣어 띄운다. KOOKABUG_* 제거와 $secret 해석은 도우미가 한다 (값은 여기 없다)
    expect(spawned[0]).toEqual({
      file: "C:/kb/kookabug.exe",
      args: ["agent-host", "--workspace", "C:/ws", "--env", "EXTRA=1", "--secret-env", "TOKEN=k", "--", "fake-agent", "--acp"],
      cwd: "C:/ws",
      env: { PATH: "C:/bin", KOOKABUG_SESSION_TOKEN: "t0p", kookabug_pipe: "x", HOME: "h" },
    });
  });

  test("세션 끝: 도우미가 끝났다는 알림(Job 정리 끝) 전에는 추적을 버리지 않는다", async () => {
    const proc = new FakeProc();
    proc.exitOnKill = false;
    const { h, events } = host(proc);
    const { session } = await h.start("fake");
    h.stop(session);
    expect(proc.killed).toBe(true);
    expect(h.tracked).toBe(1);
    proc.exited(1, "끝");
    expect(h.tracked).toBe(0);
    expect(events).toContainEqual({ type: "exit", code: 1, message: "끝" });
    // 자연 종료도 같다
    const proc2 = new FakeProc();
    const second = host(proc2);
    await second.h.start("fake");
    expect(second.h.tracked).toBe(1);
    proc2.exited(0, "에이전트가 끝났어요");
    expect(second.h.tracked).toBe(0);
  });

  test("받은 조각·도구 호출을 알림으로 넘기고, 권한 요청은 카드로만 (자동 허용 없음)", async () => {
    const proc = new FakeProc();
    const { h, events } = host(proc);
    let promptId: number | string = 0;
    proc.onPrompt = (id) => {
      promptId = id;
      proc.update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "안녕" } });
      proc.update({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: "하세요" } });
      proc.update({ sessionUpdate: "tool_call", toolCallId: "t1", title: "kb_graph_patch", kind: "edit", status: "in_progress" });
      proc.update({
        sessionUpdate: "tool_call_update",
        toolCallId: "t1",
        status: "failed",
        content: [{ type: "content", content: { type: "text", text: "input_lease_busy: 다른 실행" } }],
      });
      proc.update({ sessionUpdate: "agent_thought_chunk", content: { type: "text", text: "..." } });
      proc.send({
        id: 77,
        method: "session/request_permission",
        params: {
          sessionId: "s1",
          toolCall: { toolCallId: "p1", title: "파일 편집" },
          options: [
            { optionId: "yes", name: "허용", kind: "allow_once" },
            { optionId: "no", name: "거부", kind: "reject_once" },
          ],
        },
      });
    };
    const { session } = await h.start("fake");
    const pending = h.prompt(session, "해 줘");
    await new Promise((r) => setTimeout(r, 10));
    expect(events.filter((e) => e.type === "message").map((e) => (e as { text: string }).text)).toEqual(["안녕", "하세요"]);
    const tools = events.filter((e) => e.type === "tool");
    expect(tools.at(-1)).toMatchObject({ id: "t1", title: "kb_graph_patch", status: "failed", failed: true });
    expect((tools.at(-1) as { text: string }).text).toContain("input_lease_busy");
    expect(events).toContainEqual({ type: "hidden", kind: "agent_thought_chunk" });
    const card = events.find((e) => e.type === "permission") as Extract<AgentEvent, { type: "permission" }>;
    expect(card).toMatchObject({ title: "파일 편집", options: [{ id: "yes", kind: "allow_once" }, { id: "no", kind: "reject_once" }] });
    // 답하기 전에는 에이전트에게 아무 답도 가지 않는다
    expect(proc.received.some((m) => m.id === 77)).toBe(false);
    // 에이전트가 주지 않은 선택지는 받지 않는다
    expect(h.permission(session, card.id, "allow-everything")).toBe(false);
    expect(h.permission(session, card.id, "no")).toBe(true);
    expect(proc.received.find((m) => m.id === 77)).toMatchObject({ result: { outcome: { outcome: "selected", optionId: "no" } } });
    proc.reply(promptId, { stopReason: "end_turn" });
    expect(await pending).toEqual({ stopReason: "end_turn" });
    expect(events).toContainEqual({ type: "turn_end", stopReason: "end_turn" });
  });

  test("중지·세션 끝: 열린 카드는 cancelled로 닫히고 session/cancel을 보낸다, fs·terminal 요청은 거부", async () => {
    const proc = new FakeProc();
    const { h, events } = host(proc);
    proc.onPrompt = () => {
      proc.send({ id: 5, method: "fs/read_text_file", params: { path: "C:/secret.txt" } });
      proc.send({
        id: 6,
        method: "session/request_permission",
        params: { sessionId: "s1", toolCall: { toolCallId: "x" }, options: [{ optionId: "ok", name: "허용", kind: "allow_always" }] },
      });
    };
    const { session } = await h.start("fake");
    void h.prompt(session, "읽어 줘").catch(() => {});
    await new Promise((r) => setTimeout(r, 10));
    expect(proc.received.find((m) => m.id === 5)).toMatchObject({ error: { code: -32601 } });
    h.cancel(session);
    expect(proc.received.find((m) => m.id === 6)).toMatchObject({ result: { outcome: { outcome: "cancelled" } } });
    expect(proc.received.at(-1)).toMatchObject({ method: "session/cancel", params: { sessionId: "s1" } });
    expect(events.find((e) => e.type === "permission_closed")).toMatchObject({ outcome: "cancelled" });

    // 카드가 열린 채 세션을 닫으면 cancelled, 프로세스는 끝낸다
    proc.send({
      id: 8,
      method: "session/request_permission",
      params: { sessionId: "s1", toolCall: { toolCallId: "y" }, options: [{ optionId: "ok", name: "허용", kind: "allow_once" }] },
    });
    h.stop(session);
    expect(proc.received.find((m) => m.id === 8)).toMatchObject({ result: { outcome: { outcome: "cancelled" } } });
    expect(proc.killed).toBe(true);
    expect(events.at(-1)).toMatchObject({ type: "status", status: "ended" });
    await expect(h.prompt(session, "또")).rejects.toThrow();
  });

  test("에이전트가 죽으면 열린 카드를 닫고 exit 알림", async () => {
    const proc = new FakeProc();
    const { h, events } = host(proc);
    const { session } = await h.start("fake");
    proc.send({
      id: 9,
      method: "session/request_permission",
      params: { sessionId: "s1", toolCall: { toolCallId: "z" }, options: [{ optionId: "ok", name: "허용", kind: "allow_once" }] },
    });
    proc.kill();
    expect(events.filter((e) => e.type === "permission_closed")).toHaveLength(1);
    expect(events).toContainEqual({ type: "exit", code: 1, message: "killed" });
    expect(() => h.cancel(session)).toThrow();
  });

  test("설정에 없는 에이전트·워크스페이스 없음은 띄우지 않는다", async () => {
    const proc = new FakeProc();
    const { h, spawned } = host(proc, { root: () => null });
    await expect(h.start("fake")).rejects.toMatchObject({ code: "no_workspace" });
    const other = host(proc);
    await expect(other.h.start("nope")).rejects.toMatchObject({ code: "agent_not_configured" });
    expect(spawned).toEqual([]);
    expect(other.spawned).toEqual([]);
  });
});

describe("띄우기 도우미", () => {
  test("hostArgs: 글자 env는 --env, {$secret}은 키만 --secret-env (값은 도우미가 찾는다)", () => {
    expect(hostArgs("C:/ws", "agent", ["a b"], { A: "1", T: { $secret: "acc.key" }, N: 3 })).toEqual([
      "agent-host",
      "--workspace",
      "C:/ws",
      "--env",
      "A=1",
      "--secret-env",
      "T=acc.key",
      "--",
      "agent",
      "a b",
    ]);
  });

  test("parseAgentOverride: 틀리면 null", () => {
    expect(parseAgentOverride('{"command":"py","args":["a.py"],"env":{"K":"v","N":1}}')).toEqual({
      command: "py",
      args: ["a.py"],
      env: { K: "v" },
    });
    expect(parseAgentOverride("{nope")).toBeNull();
    expect(parseAgentOverride('{"args":[]}')).toBeNull();
    expect(parseAgentOverride(undefined)).toBeNull();
  });
});

describe("세션 설정 (Model·Effort)", () => {
  const CONFIG = [
    {
      id: "model",
      name: "Model",
      category: "model",
      type: "select",
      currentValue: "sonnet",
      options: [
        { value: "sonnet", name: "Sonnet" },
        { group: "more", name: "더 보기", options: [{ value: "opus", name: "Opus", description: "가장 강함" }] },
      ],
    },
    { id: "effort", name: "Effort", category: "thought_level", type: "select", currentValue: "medium", options: [{ value: "low", name: "Low" }, { value: "medium", name: "Medium" }] },
    { id: "flag", name: "Flag", type: "boolean", currentValue: true },
  ];

  test("configOptions: 선택형만, 묶음은 펼친다. 시작 결과에 담긴다", async () => {
    const proc = new FakeProc();
    proc.sessionExtra = { configOptions: CONFIG };
    const { h } = host(proc);
    const started = await h.start("fake");
    expect(started.config.map((o) => [o.id, o.category, o.current, o.options.map((c) => c.value)])).toEqual([
      ["model", "model", "sonnet", ["sonnet", "opus"]],
      ["effort", "thought_level", "medium", ["low", "medium"]],
    ]);
  });

  test("set_config_option: 알려 준 값만 보내고 답의 configOptions로 갈아 끼운다, 모르는 값은 거부", async () => {
    const proc = new FakeProc();
    proc.sessionExtra = { configOptions: CONFIG };
    proc.setResult = { configOptions: [{ ...CONFIG[1], currentValue: "low" }] };
    const { h, events } = host(proc);
    const { session } = await h.start("fake");
    await expect(h.setConfig(session, "effort", "ultra")).rejects.toThrow();
    const next = await h.setConfig(session, "effort", "low");
    expect(proc.received.at(-1)).toMatchObject({ method: "session/set_config_option", params: { sessionId: "s1", configId: "effort", value: "low" } });
    expect(next.map((o) => [o.id, o.current])).toEqual([["effort", "low"]]);
    expect(events.at(-1)).toMatchObject({ type: "config" });
  });

  test("옛 models·modes: set_model·set_mode로 바꾸고, config_option_update 알림을 따른다", async () => {
    const proc = new FakeProc();
    proc.sessionExtra = {
      models: { currentModelId: "a", availableModels: [{ modelId: "a", name: "A" }, { modelId: "b", name: "B" }] },
      modes: { currentModeId: "default", availableModes: [{ id: "default", name: "Default" }, { id: "plan", name: "Plan" }] },
    };
    const { h, events } = host(proc);
    const { session, config } = await h.start("fake");
    expect(config.map((o) => [o.id, o.source, o.current])).toEqual([
      ["model", "model", "a"],
      ["mode", "mode", "default"],
    ]);
    const next = await h.setConfig(session, "model", "b");
    expect(proc.received.at(-1)).toMatchObject({ method: "session/set_model", params: { sessionId: "s1", modelId: "b" } });
    expect(next.find((o) => o.id === "model")?.current).toBe("b");
    proc.update({ sessionUpdate: "config_option_update", configOptions: [CONFIG[0]] });
    await new Promise((r) => setTimeout(r, 0));
    expect(events.at(-1)).toMatchObject({ type: "config", options: [{ id: "model", current: "sonnet" }] });
  });

  test("설정이 없는 에이전트는 빈 배열", () => {
    expect(parseSessionConfig({ sessionId: "s1" })).toEqual([]);
  });
});
