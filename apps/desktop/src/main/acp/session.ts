// 에이전트 패널 세션 하나 = 에이전트 프로세스 하나 (M5 계획 3.10). ACP 클라이언트 쪽 흐름만 둔다: 프로세스를
// 띄우는 일은 host.ts가 넣어 준다 (vitest가 가짜 프로세스로 검사한다).
// - initialize: fs 읽기·쓰기 false, terminal false
// - session/new: cwd = 워크스페이스 루트, mcpServers = [kookabug mcp] 하나
// - session/request_permission은 카드로만 묻는다. 자동 허용 없음 — 답이 오기 전에 세션이 끝나면 cancelled
// - 그 밖의 에이전트 → 클라이언트 요청(fs/*·terminal/*)은 "메서드 없음"
import { AcpError, LineRpc, METHOD_NOT_FOUND } from "./client";
import type { AgentEvent, AgentPermissionOption } from "./events";

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

export class AgentSession {
  private readonly rpc: LineRpc;
  private acpSession: string | null = null;
  private readonly permissions = new Map<string, PendingPermission>();
  private readonly tools = new Map<string, { title: string; kind: string; status: string }>();
  private ended = false;
  private nextPermission = 1;

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

  /** initialize → session/new. 실패하면 프로세스를 끝내고 오류를 던진다 */
  async start(): Promise<void> {
    this.options.emit({ type: "status", status: "starting" });
    try {
      await this.rpc.request("initialize", {
        protocolVersion: ACP_PROTOCOL_VERSION,
        clientCapabilities: CLIENT_CAPABILITIES,
        clientInfo: { name: "kookabug", version: "0" },
      });
      const { name, command, args } = this.options.mcpServer;
      const result = obj(
        await this.rpc.request("session/new", {
          cwd: this.options.cwd,
          mcpServers: [{ name, command, args, env: [] }],
        }),
      );
      const id = result.sessionId;
      if (typeof id !== "string" || id === "") throw new AcpError(-32603, "session/new 결과에 sessionId가 없다");
      this.acpSession = id;
    } catch (err) {
      this.stop();
      const message = (err as Error).message;
      this.options.emit({ type: "status", status: "error", message });
      throw err;
    }
    this.options.emit({ type: "status", status: "ready" });
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
    this.options.emit({ type: "hidden", kind: kind || "unknown" });
  }
}
