// 에이전트 패널 세션들 (M5 계획 3.10). 주 프로세스가 에이전트 CLI를 띄우고 IPC 동작(agentStart 등)을 처리한다.
// - 띄울 명령은 렌더러가 주지 않는다: daemon `agents.get`(사용자 설정) 목록에서 ID로 찾는다
// - 에이전트는 `kookabug agent-host`(Python 도우미)로 감싸 띄운다: 도우미가 에이전트와 모든 자손을 Job 하나에
//   넣고, 에이전트가 끝나거나 죽거나 도우미가 끝나면 Job을 끝낸다 (자손 `kookabug mcp`가 죽어 그 연결의 확인
//   요청이 취소된다, 검수 B5 H1). 에이전트 환경의 KOOKABUG_* 제거와 `{"$secret"}` env 해석도 도우미가 한다
//   (비밀값 원문이 주 프로세스·렌더러에 오지 않는다, 검수 M2)
// - 에이전트가 받는 MCP 서버는 `kookabug mcp --agent-id panel:<세션>` 하나다 (사람이 몰고 있는 attended 연결)
// - 세션 추적은 도우미 프로세스가 끝났다는 알림(= Job 정리 끝)을 받은 뒤에만 버린다
// - 앱을 닫으면 세션 프로세스 트리를 끝낸다 (대화는 저장하지 않음 — C13)
// electron을 import하지 않는다 (vitest)
import type { AgentConfigOption, AgentEvent, AgentSessionEvent, AgentStartResult } from "./events";
import { AgentSession, type AgentProcess } from "./session";

export interface AgentSpecLite {
  id: string;
  name: string;
  command: string;
  args?: string[];
  env?: Record<string, unknown>;
}

/** 검사용 에이전트 바꿔 치기 (KOOKABUG_E2E_AGENT, E2E 빌드에서만): 고른 에이전트의 명령·인자를 이것으로 */
export interface AgentOverride {
  command: string;
  args: string[];
  env: Record<string, string>;
}

export interface SpawnRequest {
  file: string;
  args: string[];
  cwd: string;
  env: Record<string, string>;
}

export interface HostDeps {
  agents(): Promise<AgentSpecLite[]>;
  cli(): string | null;
  root(): string | null;
  baseEnv: Readonly<Record<string, string | undefined>>;
  override: AgentOverride | null;
  spawn(request: SpawnRequest): AgentProcess;
  emit(event: AgentSessionEvent): void;
}

export class AgentHostError extends Error {
  override name = "AgentHostError";
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/** 도우미 인자: `agent-host --workspace <루트> [--env 이름=값] [--secret-env 이름=키] -- <명령> [인자]` */
export function hostArgs(root: string, command: string, args: readonly string[], env: Readonly<Record<string, unknown>>): string[] {
  const out = ["agent-host", "--workspace", root];
  for (const [name, value] of Object.entries(env)) {
    if (typeof value === "string") out.push("--env", `${name}=${value}`);
    else if (typeof value === "object" && value !== null && typeof (value as { $secret?: unknown }).$secret === "string") {
      out.push("--secret-env", `${name}=${(value as { $secret: string }).$secret}`);
    }
  }
  return [...out, "--", command, ...args];
}

/** 같은 프로젝트 루트인가 (Windows 경로: 구분자·대소문자·끝 구분자 무시) */
export function sameRoot(a: string, b: string): boolean {
  const norm = (p: string) => p.replace(/[\\/]+/g, "/").replace(/\/$/, "").toLowerCase();
  return norm(a) === norm(b);
}

export class AgentHost {
  private readonly sessions = new Map<string, AgentSession>();
  private counter = 0;

  constructor(private readonly deps: HostDeps) {}

  /** 사용자 설정의 그 에이전트로 세션을 띄우고 ACP 세션을 연다 */
  /**
   * `expectedRoot` = 렌더러가 시작을 요청한 프로젝트 루트. 지금 루트와 다르면(요청을 기다리는 동안 프로젝트가 바뀜) 세션을
   * 열지 않는다 — 앞 프로젝트의 대화·세션을 새 프로젝트의 cwd·MCP에 붙이지 않게 (UX4 검수 1 H2)
   */
  async start(agentId: string, load?: string, expectedRoot?: string): Promise<AgentStartResult> {
    const root = this.deps.root();
    if (root === null) throw new AgentHostError("no_workspace", "프로젝트가 열려 있지 않아요");
    if (expectedRoot !== undefined && !sameRoot(expectedRoot, root)) {
      throw new AgentHostError("workspace_changed", "프로젝트가 바뀌어 에이전트를 열지 않았어요");
    }
    const cli = this.deps.cli();
    if (cli === null) throw new AgentHostError("cli_not_found", "kookabug CLI를 찾지 못했어요");
    const spec = (await this.deps.agents()).find((a) => a.id === agentId);
    if (spec === undefined) throw new AgentHostError("agent_not_configured", `설정에 에이전트 ${agentId}가 없어요`);
    const session = `p${++this.counter}${Math.random().toString(16).slice(2, 6)}`;
    const override = this.deps.override;
    const command = override?.command ?? spec.command;
    const args = override?.args ?? spec.args ?? [];
    const args2 = hostArgs(root, command, args, { ...(spec.env ?? {}), ...(override?.env ?? {}) });
    const emit = (event: AgentEvent) => this.deps.emit({ session, event });
    let proc: AgentProcess;
    try {
      // 도우미 환경은 앱 환경 그대로 (KOOKABUG_SECRET_* 같은 비밀값 제공자 설정을 도우미가 읽는다).
      // 에이전트에게 넘길 때 도우미가 KOOKABUG_*를 뺀다
      const env: Record<string, string> = {};
      for (const [k, v] of Object.entries(this.deps.baseEnv)) if (v !== undefined) env[k] = v;
      proc = this.deps.spawn({ file: cli, args: args2, cwd: root, env });
    } catch (err) {
      throw new AgentHostError("agent_start_failed", `에이전트를 띄우지 못했어요: ${(err as Error).message}`);
    }
    const agent = new AgentSession(proc, {
      cwd: root,
      mcpServer: {
        name: "kookabug",
        command: cli,
        args: ["mcp", "--workspace", root, "--agent-id", `panel:${session}`, "--client", "panel"],
      },
      emit: (event) => {
        // 도우미가 끝남 = Job 정리가 끝남. 그때에만 추적을 버린다
        if (event.type === "exit") this.sessions.delete(session);
        emit(event);
      },
    });
    this.sessions.set(session, agent);
    try {
      await agent.start(load);
    } catch (err) {
      // 실패한 세션도 프로세스가 끝났다는 알림이 올 때까지 표에 둔다 (start가 이미 stop을 불렀다)
      throw new AgentHostError("agent_start_failed", `에이전트가 ACP 연결에 답하지 않았어요: ${(err as Error).message}`);
    }
    return { session, agentId: spec.id, name: spec.name, config: agent.config, acpSession: agent.acpSessionId, loaded: agent.loaded };
  }

  private get(session: unknown): AgentSession {
    const agent = typeof session === "string" ? this.sessions.get(session) : undefined;
    if (agent === undefined || !agent.alive) throw new AgentHostError("no_session", "에이전트 세션이 없어요");
    return agent;
  }

  async prompt(session: unknown, text: unknown): Promise<{ stopReason: string }> {
    if (typeof text !== "string" || text.trim() === "") throw new AgentHostError("bad_args", "보낼 글자가 없어요");
    return { stopReason: await this.get(session).prompt(text) };
  }

  cancel(session: unknown): void {
    this.get(session).cancel();
  }

  permission(session: unknown, id: unknown, optionId: unknown): boolean {
    if (typeof id !== "string" || !(optionId === null || typeof optionId === "string")) {
      throw new AgentHostError("bad_args", "권한 답 인자가 틀렸어요");
    }
    return this.get(session).answerPermission(id, optionId);
  }

  /** 세션 설정 바꾸기 (Agent 패널 하단 Model·Effort) */
  async setConfig(session: unknown, id: unknown, value: unknown): Promise<AgentConfigOption[]> {
    if (typeof id !== "string" || typeof value !== "string") throw new AgentHostError("bad_args", "설정 인자가 틀렸어요");
    return this.get(session).setConfig(id, value);
  }

  /** 세션 끝: 도우미를 끝낸다. 표에서는 프로세스가 끝났다는 알림(exit)이 온 뒤에 뺀다 */
  stop(session: unknown): void {
    const agent = typeof session === "string" ? this.sessions.get(session) : undefined;
    agent?.stop();
  }

  /** 추적 중인 세션 수 (끝나는 중인 것 포함, 검사용) */
  get tracked(): number {
    return this.sessions.size;
  }

  stopAll(): void {
    for (const id of [...this.sessions.keys()]) this.stop(id);
  }
}

/** KOOKABUG_E2E_AGENT (JSON {command, args?, env?}). 틀리면 null */
export function parseAgentOverride(text: string | undefined): AgentOverride | null {
  if (!text) return null;
  try {
    const v = JSON.parse(text) as { command?: unknown; args?: unknown; env?: unknown };
    if (typeof v.command !== "string" || v.command === "") return null;
    const args = Array.isArray(v.args) && v.args.every((a) => typeof a === "string") ? (v.args as string[]) : [];
    const env: Record<string, string> = {};
    if (typeof v.env === "object" && v.env !== null) {
      for (const [k, val] of Object.entries(v.env)) if (typeof val === "string") env[k] = val;
    }
    return { command: v.command, args, env };
  } catch {
    return null;
  }
}
