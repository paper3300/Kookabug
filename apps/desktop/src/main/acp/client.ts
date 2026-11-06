// ACP 줄 단위 JSON-RPC 2.0 (M5 계획 D8·3.10). stdio 한 줄 = 메시지 하나. electron·child_process를 import하지 않는다
// (vitest가 가짜 쓰기로 검사한다)

export type JsonValue = unknown;

export interface RpcErrorBody {
  code: number;
  message: string;
  data?: unknown;
}

export class AcpError extends Error {
  override name = "AcpError";
  constructor(
    readonly code: number,
    message: string,
    readonly data?: unknown,
  ) {
    super(message);
  }
}

/** 받은 줄 상한 (넘는 줄은 버리고 연결 오류로 본다) */
export const LINE_LIMIT = 8 * 1024 * 1024;
export const METHOD_NOT_FOUND = -32601;

type RequestHandler = (method: string, params: unknown, id: number | string) => void;
type NotificationHandler = (method: string, params: unknown) => void;

interface Pending {
  resolve(value: unknown): void;
  reject(err: Error): void;
}

/** 에이전트 쪽 JSON-RPC 끝점. 보내기는 `write`(한 줄), 받기는 `feed`(조각) */
export class LineRpc {
  private buffer = "";
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private closedReason: string | null = null;
  onRequest: RequestHandler = (_m, _p, id) => this.respondError(id, METHOD_NOT_FOUND, "method not found");
  onNotification: NotificationHandler = () => {};
  /** 읽을 수 없는 줄 (기록용) */
  onProtocolError: (message: string) => void = () => {};

  constructor(private readonly write: (line: string) => void) {}

  get closed(): boolean {
    return this.closedReason !== null;
  }

  request(method: string, params: unknown): Promise<unknown> {
    if (this.closedReason !== null) return Promise.reject(new AcpError(-32000, this.closedReason));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.send({ jsonrpc: "2.0", id, method, params });
    });
  }

  notify(method: string, params: unknown): void {
    if (this.closedReason !== null) return;
    this.send({ jsonrpc: "2.0", method, params });
  }

  respond(id: number | string, result: unknown): void {
    if (this.closedReason !== null) return;
    this.send({ jsonrpc: "2.0", id, result });
  }

  respondError(id: number | string, code: number, message: string): void {
    if (this.closedReason !== null) return;
    this.send({ jsonrpc: "2.0", id, error: { code, message } });
  }

  /** stdout 조각. 줄마다 메시지 하나 */
  feed(chunk: string): void {
    this.buffer += chunk;
    if (this.buffer.length > LINE_LIMIT && !this.buffer.includes("\n")) {
      this.buffer = "";
      this.onProtocolError("줄이 너무 길다");
      return;
    }
    let at: number;
    while ((at = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, at).trim();
      this.buffer = this.buffer.slice(at + 1);
      if (line !== "") this.dispatch(line);
    }
  }

  /** 프로세스가 끝남: 기다리는 요청을 모두 실패시킨다 */
  close(reason: string): void {
    if (this.closedReason !== null) return;
    this.closedReason = reason;
    for (const p of this.pending.values()) p.reject(new AcpError(-32000, reason));
    this.pending.clear();
  }

  private send(message: object): void {
    try {
      this.write(JSON.stringify(message) + "\n");
    } catch (err) {
      this.close(`보내기 실패: ${(err as Error).message}`);
    }
  }

  private dispatch(line: string): void {
    let msg: { id?: unknown; method?: unknown; params?: unknown; result?: unknown; error?: unknown };
    try {
      msg = JSON.parse(line) as typeof msg;
    } catch {
      this.onProtocolError(`JSON이 아닌 줄: ${line.slice(0, 120)}`);
      return;
    }
    if (typeof msg !== "object" || msg === null) {
      this.onProtocolError("객체가 아닌 메시지");
      return;
    }
    if (typeof msg.method === "string") {
      if (msg.id === undefined || msg.id === null) this.onNotification(msg.method, msg.params);
      else if (typeof msg.id === "number" || typeof msg.id === "string") this.onRequest(msg.method, msg.params, msg.id);
      return;
    }
    if (typeof msg.id !== "number") return;
    const waiter = this.pending.get(msg.id);
    if (waiter === undefined) return;
    this.pending.delete(msg.id);
    if (msg.error !== undefined && msg.error !== null) {
      const e = msg.error as Partial<RpcErrorBody>;
      waiter.reject(new AcpError(typeof e.code === "number" ? e.code : -32000, String(e.message ?? "오류"), e.data));
    } else {
      waiter.resolve(msg.result);
    }
  }
}
