// 에이전트 패널 세션 하나 = 에이전트 프로세스 하나 (M5 계획 3.10). ACP 클라이언트 쪽 흐름만 둔다: 프로세스를
// 띄우는 일은 host.ts가 넣어 준다 (vitest가 가짜 프로세스로 검사한다).
// - initialize: fs 읽기·쓰기 false, terminal false
// - session/new: cwd = 워크스페이스 루트, mcpServers = [kookabug mcp] 하나
// - 이전 대화 이어 가기(UX4): 에이전트가 initialize에서 loadSession을 알렸으면 session/load로 그 세션을 연다.
//   불러오는 동안 에이전트가 다시 보내는 지난 대화(session/update)는 화면에 내지 않는다 (화면은 저장한 대화를 그린다).
//   지원하지 않거나 불러오기가 실패하면 session/new
// - session/request_permission은 카드로만 묻는다. 자동 허용 없음 — 답이 오기 전에 세션이 끝나면 cancelled
// - 그 밖의 에이전트 → 클라이언트 요청(fs/*·terminal/*)은 "메서드 없음"
import { AcpError, LineRpc, METHOD_NOT_FOUND } from "./client";
import type { AgentConfigOption, AgentEvent, AgentPermissionOption } from "./events";

export const ACP_PROTOCOL_VERSION = 1;
export const CLIENT_CAPABILITIES = { fs: { readTextFile: false, writeTextFile: false }, terminal: false } as const;

/** 도구 호출 줄에 남길 글자 상한 (임대권 거부 알아보기용 — 화면에는 제목만 낸다) */
const TOOL_TEXT_LIMIT = 4096;

export interface AgentProcess {
  write(line: string): void;
  onStdout(cb: (chunk: string) => void): void;
  onExit(cb: (code: number | null, message: string) => void): void;
  /** 프로세스 트리를 끝낸다 */
  kill(): void;
}

export interface McpServerSpec {
  name: string;
  command: string;
  args: string[];
}

export interface SessionOptions {
  cwd: string;
  mcpServer: McpServerSpec;
  emit(event: AgentEvent): void;
}

interface PendingPermission {
  rpcId: number | string;
  options: AgentPermissionOption[];
}

type Obj = Record<string, unknown>;

function obj(v: unknown): Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Obj) : {};
}

function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

/** tool_call 내용에서 글자만 (content[].content.text, rawOutput) */
export function toolText(update: Obj): string {
  const parts: string[] = [];
  const content = Array.isArray(update.content) ? update.content : [];
  for (const item of content) {
    const inner = obj(obj(item).content);
    if (typeof inner.text === "string") parts.push(inner.text);
  }
  if (update.rawOutput !== undefined) {
    parts.push(typeof update.rawOutput === "string" ? update.rawOutput : JSON.stringify(update.rawOutput));
  }
  return parts.join("\n").slice(0, TOOL_TEXT_LIMIT);
}

function selectChoices(raw: unknown): AgentConfigOption["options"] {
  const out: AgentConfigOption["options"] = [];
  for (const item of Array.isArray(raw) ? raw : []) {
    const o = obj(item);
    // 묶음 선택지 {group, name, options: [...]}는 펼친다
    if (Array.isArray(o.options)) {
      out.push(...selectChoices(o.options));
      continue;
    }
    const value = str(o.value);
    if (value === "") continue;
    out.push({ value, name: str(o.name, value), ...(typeof o.description === "string" ? { description: o.description } : {}) });
  }
  return out;
}

/** ACP session config options (선택형만) */
export function parseConfigOptions(raw: unknown): AgentConfigOption[] {
  const out: AgentConfigOption[] = [];
  for (const item of Array.isArray(raw) ? raw : []) {
    const o = obj(item);
    const id = str(o.id);
    if (id === "" || (o.type !== undefined && o.type !== "select")) continue;
    const options = selectChoices(o.options);
    if (options.length === 0) continue;
    out.push({ id, name: str(o.name, id), category: str(o.category), current: str(o.currentValue), options, source: "config" });
  }
  return out;
}

/** session/new 결과의 설정: configOptions가 있으면 그것, 없으면 옛 models·modes */
export function parseSessionConfig(result: Obj): AgentConfigOption[] {
  if (Array.isArray(result.configOptions)) return parseConfigOptions(result.configOptions);
  const out: AgentConfigOption[] = [];
  const models = obj(result.models);
  const modelList = Array.isArray(models.availableModels) ? models.availableModels : [];
  const modelChoices = modelList
    .map((m) => obj(m))
    .filter((m) => str(m.modelId) !== "")
    .map((m) => ({ value: str(m.modelId), name: str(m.name, str(m.modelId)), ...(typeof m.description === "string" ? { description: m.description } : {}) }));
  if (modelChoices.length > 0) {
    out.push({ id: "model", name: "Model", category: "model", current: str(models.currentModelId), options: modelChoices, source: "model" });
  }
  const modes = obj(result.modes);
  const modeList = Array.isArray(modes.availableModes) ? modes.availableModes : [];
  const modeChoices = modeList
    .map((m) => obj(m))
    .filter((m) => str(m.id) !== "")
    .map((m) => ({ value: str(m.id), name: str(m.name, str(m.id)), ...(typeof m.description === "string" ? { description: m.description } : {}) }));
  if (modeChoices.length > 0) {
    out.push({ id: "mode", name: "Mode", category: "mode", current: str(modes.currentModeId), options: modeChoices, source: "mode" });
  }
  return out;
}

export class AgentSession {
  private readonly rpc: LineRpc;
  private acpSession: string | null = null;
  private readonly permissions = new Map<string, PendingPermission>();
  private readonly tools = new Map<string, { title: string; kind: string; status: string }>();
  private ended = false;
  private nextPermission = 1;
  private configOptions: AgentConfigOption[] = [];
  private replaying = false;
  private loadedSession = false;

  constructor(
    private readonly proc: AgentProcess,
    private readonly options: SessionOptions,
  ) {
    this.rpc = new LineRpc((line) => proc.write(line));
    this.rpc.onRequest = (method, params, id) => this.onRequest(method, params, id);
    this.rpc.onNotification = (method, params) => this.onNotification(method, params);
    proc.onStdout((chunk) => this.rpc.feed(chunk));
    proc.onExit((code, message) => this.onExit(code, message));
  }

  get alive(): boolean {
    return !this.ended;
  }

  /**
   * initialize → session/new (또는 `load`가 있고 에이전트가 loadSession을 지원하면 session/load).
   * 실패하면 프로세스를 끝내고 오류를 던진다
   */
  async start(load?: string): Promise<void> {
    this.options.emit({ type: "status", status: "starting" });
    try {
      const init = obj(
        await this.rpc.request("initialize", {
          protocolVersion: ACP_PROTOCOL_VERSION,
          clientCapabilities: CLIENT_CAPABILITIES,
          clientInfo: { name: "kookabug", version: "0" },
        }),
      );
      const canLoad = obj(init.agentCapabilities).loadSession === true;
      const { name, command, args } = this.options.mcpServer;
      const mcpServers = [{ name, command, args, env: [] }];
      let result: Obj | null = null;
      if (load !== undefined && load !== "" && canLoad) {
        this.replaying = true;
        try {
          result = obj(await this.rpc.request("session/load", { sessionId: load, cwd: this.options.cwd, mcpServers }));
          this.acpSession = load;
          this.loadedSession = true;
        } catch (err) {
          // 프로세스가 끝났으면 그대로 실패, 에이전트가 거절만 했으면 새 세션으로
          if (this.ended) throw err;
          result = null;
        } finally {
          this.replaying = false;
        }
      }
      if (result === null) {
        result = obj(await this.rpc.request("session/new", { cwd: this.options.cwd, mcpServers }));
        const id = result.sessionId;
        if (typeof id !== "string" || id === "") throw new AcpError(-32603, "session/new 결과에 sessionId가 없다");
        this.acpSession = id;
      }
      this.configOptions = parseSessionConfig(result);
    } catch (err) {
      this.stop();
      const message = (err as Error).message;
      this.options.emit({ type: "status", status: "error", message });
      throw err;
    }
    this.options.emit({ type: "status", status: "ready" });
  }

  /** 에이전트의 ACP 세션 ID (없으면 빈 글) */
  get acpSessionId(): string {
    return this.acpSession ?? "";
  }

  /** start(load)가 지난 세션을 불러왔는가 */
  get loaded(): boolean {
    return this.loadedSession;
  }

  /** 지금 세션 설정 (모델·생각 수준 등) */
  get config(): AgentConfigOption[] {
    return this.configOptions;
  }

  /** 세션 설정 하나를 바꾼다. 에이전트가 알려 준 선택지 값만 받는다 */
  async setConfig(id: string, value: string): Promise<AgentConfigOption[]> {
    if (this.acpSession === null || this.ended) throw new AcpError(-32000, "세션이 없다");
    const option = this.configOptions.find((o) => o.id === id);
    if (option === undefined || !option.options.some((c) => c.value === value)) {
      throw new AcpError(-32602, `에이전트가 알려 주지 않은 설정 값: ${id}=${value}`);
    }
    const sessionId = this.acpSession;
    if (option.source === "config") {
      const result = obj(await this.rpc.request("session/set_config_option", { sessionId, configId: id, value }));
      const next = Array.isArray(result.configOptions) ? parseConfigOptions(result.configOptions) : null;
      this.configOptions = next ?? this.configOptions.map((o) => (o.id === id ? { ...o, current: value } : o));
    } else {
      if (option.source === "model") await this.rpc.request("session/set_model", { sessionId, modelId: value });
      else await this.rpc.request("session/set_mode", { sessionId, modeId: value });
      this.configOptions = this.configOptions.map((o) => (o.id === id ? { ...o, current: value } : o));
    }
    this.options.emit({ type: "config", options: this.configOptions });
    return this.configOptions;
  }

  /** 글자 하나를 보낸다. 끝나면 stopReason */
  async prompt(text: string): Promise<string> {
    if (this.acpSession === null || this.ended) throw new AcpError(-32000, "세션이 없다");
    this.options.emit({ type: "status", status: "busy" });
    try {
      const result = obj(
        await this.rpc.request("session/prompt", { sessionId: this.acpSession, prompt: [{ type: "text", text }] }),
      );
      const stopReason = str(result.stopReason, "end_turn");
      this.options.emit({ type: "turn_end", stopReason });
      return stopReason;
    } catch (err) {
      if (!this.ended) this.options.emit({ type: "turn_end", stopReason: "error" });
      throw err;
    } finally {
      if (!this.ended) this.options.emit({ type: "status", status: "ready" });
    }
  }

  /** 중지 단추: session/cancel. 열린 권한 카드는 cancelled로 닫는다 (ACP: 취소 때 기다리는 요청은 cancelled) */
  cancel(): void {
    this.closePermissions();
    if (this.acpSession !== null) this.rpc.notify("session/cancel", { sessionId: this.acpSession });
  }

  /** 권한 카드의 답. optionId null = 닫기(cancelled). 에이전트가 준 선택지만 받는다 */
  answerPermission(id: string, optionId: string | null): boolean {
    const pending = this.permissions.get(id);
    if (pending === undefined) return false;
    if (optionId !== null && !pending.options.some((o) => o.id === optionId)) return false;
    this.permissions.delete(id);
    if (optionId === null) {
      this.rpc.respond(pending.rpcId, { outcome: { outcome: "cancelled" } });
      this.options.emit({ type: "permission_closed", id, outcome: "cancelled" });
    } else {
      this.rpc.respond(pending.rpcId, { outcome: { outcome: "selected", optionId } });
      this.options.emit({ type: "permission_closed", id, outcome: "selected", optionId });
    }
    return true;
  }

  /** 패널 닫힘·새 대화·앱 종료: 카드는 cancelled, 프로세스 트리를 끝낸다 */
  stop(): void {
    this.closePermissions();
    if (this.ended) return;
    this.proc.kill();
  }

  private closePermissions(): void {
    for (const id of [...this.permissions.keys()]) this.answerPermission(id, null);
  }

  private onExit(code: number | null, message: string): void {
    if (this.ended) return;
    // 카드는 cancelled로 닫는다 (답할 곳이 없어도 화면에서 걷는다)
    for (const id of [...this.permissions.keys()]) {
      this.permissions.delete(id);
      this.options.emit({ type: "permission_closed", id, outcome: "cancelled" });
    }
    this.ended = true;
    this.rpc.close(message || "에이전트 프로세스가 끝났다");
    this.options.emit({ type: "exit", code, message });
    this.options.emit({ type: "status", status: "ended", message });
  }

  private onRequest(method: string, params: unknown, id: number | string): void {
    if (method !== "session/request_permission") {
      this.rpc.respondError(id, METHOD_NOT_FOUND, `kookabug 패널은 ${method}를 제공하지 않는다`);
      return;
    }
    const p = obj(params);
    const call = obj(p.toolCall);
    const options: AgentPermissionOption[] = [];
    for (const raw of Array.isArray(p.options) ? p.options : []) {
      const o = obj(raw);
      const optionId = str(o.optionId);
      if (optionId === "") continue;
      options.push({ id: optionId, name: str(o.name, optionId), kind: str(o.kind) });
    }
    const key = `perm${this.nextPermission++}`;
    this.permissions.set(key, { rpcId: id, options });
    const known = this.tools.get(str(call.toolCallId));
    this.options.emit({
      type: "permission",
      id: key,
      title: str(call.title) || known?.title || "에이전트 도구",
      options,
    });
  }

  private onNotification(method: string, params: unknown): void {
    if (method !== "session/update") return;
    // session/load가 다시 보내는 지난 대화는 내지 않는다 (화면은 저장한 대화를 그린다)
    if (this.replaying) return;
    const update = obj(obj(params).update);
    const kind = str(update.sessionUpdate);
    if (kind === "agent_message_chunk") {
      const content = obj(update.content);
      if (content.type === "text" && typeof content.text === "string") {
        this.options.emit({ type: "message", text: content.text });
      }
      return;
    }
    if (kind === "tool_call" || kind === "tool_call_update") {
      const id = str(update.toolCallId);
      const before = this.tools.get(id);
      const merged = {
        title: str(update.title) || before?.title || "도구",
        kind: str(update.kind) || before?.kind || "other",
        status: str(update.status) || before?.status || "pending",
      };
      this.tools.set(id, merged);
      this.options.emit({
        type: "tool",
        id,
        ...merged,
        failed: merged.status === "failed",
        text: toolText(update),
      });
      return;
    }
    if (kind === "config_option_update" && Array.isArray(update.configOptions)) {
      this.configOptions = parseConfigOptions(update.configOptions);
      this.options.emit({ type: "config", options: this.configOptions });
      return;
    }
    if (kind === "current_mode_update" && typeof update.currentModeId === "string") {
      const mode = update.currentModeId;
      this.configOptions = this.configOptions.map((o) => (o.source === "mode" ? { ...o, current: mode } : o));
      this.options.emit({ type: "config", options: this.configOptions });
      return;
    }
    this.options.emit({ type: "hidden", kind: kind || "unknown" });
  }
}
