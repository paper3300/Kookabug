// daemon과의 JSON-RPC 연결 하나 (M2 계획 2.4). WebSocket 텍스트 프레임 하나에 메시지 하나.
// 보내는 JSON은 전송 코덱 wireStringify로만 만든다(2.6). 받은 메시지는 봉투·result·알림 params를
// 메타스키마로 검사한다(2.4 "보내기 전과 받은 뒤 양쪽이 같은 메타스키마로 검사").
// electron을 import하지 않는다: vitest가 가짜 소켓으로 검사한다
import {
  checkMessage,
  checkNotification,
  checkResult,
  wireStringify,
  type SchemaIssue,
} from "@kookabug/schema";

/** 렌더러에 넘기는 오류 모양 (JSON-RPC error 객체와 같다) */
export interface RpcErrorShape {
  code: number;
  message: string;
  data?: unknown;
}

/** 앱 쪽에서 만든 오류 코드 (JSON-RPC 서버 오류 범위). 종류는 data.code */
export const LOCAL_ERROR = -32000;
export const INVALID_PARAMS = -32602;
export const INTERNAL_ERROR = -32603;

export class RpcFailure extends Error {
  override name = "RpcFailure";
  readonly code: number;
  readonly data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.code = code;
    this.data = data;
  }

  /** error.data.code (daemon 오류 종류). 없으면 null */
  get kind(): string | null {
    const d = this.data as { code?: unknown } | undefined;
    return typeof d?.code === "string" ? d.code : null;
  }

  toShape(): RpcErrorShape {
    return this.data === undefined
      ? { code: this.code, message: this.message }
      : { code: this.code, message: this.message, data: this.data };
  }
}

export function notConnected(): RpcFailure {
  return new RpcFailure(LOCAL_ERROR, "daemon에 연결되지 않았다", { code: "not_connected" });
}

/** WebSocket에서 쓰는 부분만. 검사가 가짜를 넣는다 */
export interface SocketLike {
  send(text: string): void;
  close(): void;
  /** 텍스트 프레임이면 문자열, 바이너리 프레임이면 null */
  onMessage(cb: (data: string | null) => void): void;
  onClose(cb: () => void): void;
}

type NotificationListener = (method: string, params: unknown) => void;

interface Pending {
  method: string;
  resolve(value: unknown): void;
  reject(err: RpcFailure): void;
}

function describe(issues: SchemaIssue[]): string {
  return issues.map((i) => `${i.pointer || "/"} ${i.message}`).join("; ");
}

export class RpcConnection {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly notificationListeners = new Set<NotificationListener>();
  private readonly closeListeners = new Set<() => void>();
  private isClosed = false;
  private resolveClosed!: () => void;
  /** 연결이 닫히면 풀린다 */
  readonly closed: Promise<void> = new Promise((resolve) => (this.resolveClosed = resolve));
  /** 받았지만 계약에 맞지 않아 버린 메시지 (출력 패널·검사용) */
  readonly dropped: string[] = [];

  constructor(private readonly socket: SocketLike) {
    socket.onMessage((data) => this.receive(data));
    socket.onClose(() => this.finish());
  }

  get isOpen(): boolean {
    return !this.isClosed;
  }

  /**
   * 요청을 보내고 응답을 기다린다. paramsText가 있으면 이미 wireStringify로 만든 params 텍스트다
   * (IPC가 비유한 수 검사 때 한 번 만든 것을 다시 쓴다).
   */
  call(method: string, params: unknown, paramsText?: string): Promise<unknown> {
    if (this.isClosed) return Promise.reject(notConnected());
    const id = this.nextId++;
    let text: string;
    try {
      const body = paramsText ?? wireStringify(params === undefined ? {} : params);
      text = `{"jsonrpc":"2.0","id":${id},"method":${JSON.stringify(method)},"params":${body}}`;
    } catch (err) {
      return Promise.reject(new RpcFailure(INVALID_PARAMS, (err as Error).message));
    }
    return new Promise((resolve, reject) => {
      this.pending.set(id, { method, resolve, reject });
      try {
        this.socket.send(text);
      } catch (err) {
        this.pending.delete(id);
        reject(new RpcFailure(LOCAL_ERROR, `보내지 못했다: ${(err as Error).message}`, { code: "not_connected" }));
      }
    });
  }

  onNotification(cb: NotificationListener): () => void {
    this.notificationListeners.add(cb);
    return () => this.notificationListeners.delete(cb);
  }

  onClose(cb: () => void): void {
    if (this.isClosed) queueMicrotask(cb);
    else this.closeListeners.add(cb);
  }

  close(): void {
    if (this.isClosed) return;
    this.socket.close();
    this.finish();
  }

  private finish(): void {
    if (this.isClosed) return;
    this.isClosed = true;
    for (const p of this.pending.values()) p.reject(notConnected());
    this.pending.clear();
    this.resolveClosed();
    for (const cb of this.closeListeners) cb();
    this.closeListeners.clear();
  }

  // 계약을 어긴 메시지는 연결을 믿을 수 없다는 뜻이라 닫는다 (daemon도 같은 규칙)
  private violate(reason: string): void {
    this.dropped.push(reason);
    this.close();
  }

  private receive(data: string | null): void {
    if (this.isClosed) return;
    if (data === null) return this.violate("바이너리 프레임");
    let message: unknown;
    try {
      message = JSON.parse(data);
    } catch {
      return this.violate("JSON이 아닌 프레임");
    }
    const issues = checkMessage(message);
    if (issues.length > 0) return this.violate(`봉투가 계약에 맞지 않는다: ${describe(issues)}`);
    const msg = message as {
      id?: number | string | null;
      method?: string;
      params?: unknown;
      result?: unknown;
      error?: { code: number; message: string; data?: unknown };
    };
    if (typeof msg.method === "string") {
      const problems = checkNotification(msg.method, msg.params);
      if (problems.length > 0) {
        this.dropped.push(`알림 ${msg.method}: ${describe(problems)}`);
        return;
      }
      for (const cb of this.notificationListeners) cb(msg.method, msg.params ?? {});
      return;
    }
    const pending = typeof msg.id === "number" ? this.pending.get(msg.id) : undefined;
    if (pending === undefined) {
      this.dropped.push(`모르는 응답 id ${String(msg.id)}`);
      return;
    }
    this.pending.delete(msg.id as number);
    if (msg.error !== undefined) {
      pending.reject(new RpcFailure(msg.error.code, msg.error.message, msg.error.data));
      return;
    }
    const problems = checkResult(pending.method, msg.result);
    if (problems.length > 0) {
      pending.reject(
        new RpcFailure(INTERNAL_ERROR, `${pending.method} 결과가 계약에 맞지 않는다: ${describe(problems)}`),
      );
      return;
    }
    pending.resolve(msg.result);
  }
}
