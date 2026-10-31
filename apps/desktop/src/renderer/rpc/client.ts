// daemon 클라이언트 (M2 계획 2.10). 렌더러는 소켓을 모른다: preload 다리(window.kookabug)로 주 프로세스에
// 부탁한다. 타입은 @kookabug/schema 생성 타입이고, 실제 검사는 주 프로세스가 한다
import type { MethodName, NotificationName, NotificationParamsOf, ParamsOf, ResultOf } from "@kookabug/schema";
import type { KookabugBridge } from "../../preload/bridge";

export type { MethodName, NotificationName };

/** daemon·주 프로세스가 돌려준 오류. kind = error.data.code (예: revision_conflict) */
export class RpcError extends Error {
  override name = "RpcError";
  readonly code: number;
  readonly data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.code = code;
    this.data = data;
  }

  get kind(): string | null {
    const d = this.data as { code?: unknown } | undefined;
    return typeof d?.code === "string" ? d.code : null;
  }
}

export function toRpcError(err: unknown): RpcError {
  if (err instanceof RpcError) return err;
  if (typeof err === "object" && err !== null && "code" in err && "message" in err) {
    const e = err as { code: unknown; message: unknown; data?: unknown };
    return new RpcError(typeof e.code === "number" ? e.code : -32000, String(e.message), e.data);
  }
  return new RpcError(-32000, err instanceof Error ? err.message : String(err), { code: "ipc_rejected" });
}

/** 메서드 호출 함수 모양. 검사가 가짜를 넣는다 */
export type RpcCall = <M extends MethodName>(method: M, params: ParamsOf<M>) => Promise<ResultOf<M>>;

export function createClient(bridge: Pick<KookabugBridge, "rpc" | "on">) {
  const call: RpcCall = async (method, params) => {
    try {
      return (await bridge.rpc(method, params)) as never;
    } catch (err) {
      throw toRpcError(err);
    }
  };
  function on<N extends NotificationName>(name: N, cb: (params: NotificationParamsOf<N>) => void): () => void {
    return bridge.on(name, (data) => cb(data as NotificationParamsOf<N>));
  }
  return { call, on };
}

export type Client = ReturnType<typeof createClient>;

let shared: Client | null = null;

/** 앱 전체가 쓰는 클라이언트 (window.kookabug) */
export function client(): Client {
  // globalThis: 주 프로세스 검사(tsconfig.node, DOM 없음)도 이 파일을 타입 검사한다
  shared ??= createClient((globalThis as unknown as { kookabug: KookabugBridge }).kookabug);
  return shared;
}
