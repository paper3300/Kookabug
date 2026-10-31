// 렌더러 → daemon 요청 처리와 daemon → 렌더러 알림 전달 (M2 계획 2.10 "IPC 다리", 검수 M9).
// 발신 프레임 검사는 main.ts가 이 처리기를 부르기 전에 한다. electron을 import하지 않는다 (vitest)
import { checkParams, WireValueError, wireStringify } from "@kookabug/schema";
import { checkRendererMethod, IpcGuardError, RENDERER_EVENTS } from "./ipc-guard";
import { INVALID_PARAMS, LOCAL_ERROR, RpcFailure, type RpcErrorShape } from "./rpc-connection";

/** IPC 응답. 오류도 값으로 돌려준다 (Electron이 던진 오류의 추가 필드를 버리기 때문) */
export type RpcEnvelope = { ok: true; result: unknown } | { ok: false; error: RpcErrorShape };

export type DaemonCall = (method: string, params: unknown, paramsText: string) => Promise<unknown>;

/**
 * 렌더러 요청 하나를 처리한다. 순서: 메서드 허용 목록 → 값 전송 가능(비유한 수 거부) → params 스키마 →
 * daemon. 앞 단계에서 걸리면 daemon에 아무것도 보내지 않는다
 */
export function createRpcHandler(call: DaemonCall) {
  return async (method: unknown, params: unknown): Promise<RpcEnvelope> => {
    let name: string;
    try {
      name = checkRendererMethod(method);
    } catch (err) {
      return fail(LOCAL_ERROR, (err as Error).message, { code: "method_not_allowed" });
    }
    const value = params === undefined ? {} : params;
    let text: string;
    try {
      text = wireStringify(value);
    } catch (err) {
      if (err instanceof WireValueError) {
        // 렌더러는 number_not_finite 진단과 같은 문구로 보여 준다 (2.6 전송 코덱)
        return fail(INVALID_PARAMS, err.message, { code: "number_not_finite", pointer: err.pointer });
      }
      return fail(INVALID_PARAMS, (err as Error).message, { code: "invalid_params" });
    }
    const issues = checkParams(name, value);
    if (issues.length > 0) {
      return fail(INVALID_PARAMS, `${name} params가 계약에 맞지 않는다`, { code: "invalid_params", issues });
    }
    try {
      return { ok: true, result: await call(name, value, text) };
    } catch (err) {
      if (err instanceof RpcFailure) return { ok: false, error: err.toShape() };
      return fail(LOCAL_ERROR, (err as Error).message ?? String(err), { code: "internal" });
    }
  };
}

function fail(code: number, message: string, data: unknown): RpcEnvelope {
  return { ok: false, error: { code, message, data } };
}

/** daemon 알림 중 렌더러 허용 목록에 있는 것만 넘긴다 */
export function createNotificationForwarder(send: (name: string, params: unknown) => void) {
  return (name: string, params: unknown): boolean => {
    if (!RENDERER_EVENTS.has(name)) return false;
    send(name, params);
    return true;
  };
}

export { IpcGuardError };
