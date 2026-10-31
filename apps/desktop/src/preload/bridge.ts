// window.kookabug 로 내놓는 좁은 API (M2 계획 2.10). ipcRenderer를 인자로 받아 vitest가
// 가짜 ipc로 검사한다
import { checkRendererEvent, checkRendererMethod, EVENT_CHANNEL, RPC_CHANNEL } from "../main/ipc-guard";

type Listener = (event: unknown, ...args: unknown[]) => void;

export interface IpcRendererLike {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: Listener): unknown;
  removeListener(channel: string, listener: Listener): unknown;
}

export interface KookabugBridge {
  rpc(method: string, params?: unknown): Promise<unknown>;
  on(event: string, cb: (data: unknown) => void): () => void;
}

export function createBridge(ipc: IpcRendererLike): KookabugBridge {
  return {
    rpc(method, params) {
      try {
        checkRendererMethod(method);
      } catch (err) {
        return Promise.reject(err);
      }
      return ipc.invoke(RPC_CHANNEL, method, params);
    },
    on(event, cb) {
      const name = checkRendererEvent(event);
      if (typeof cb !== "function") throw new TypeError("콜백이 함수가 아니다");
      // Electron 이벤트 객체(sender 등)는 넘기지 않고 데이터만 준다
      const listener: Listener = (_event, eventName, data) => {
        if (eventName === name) cb(data);
      };
      ipc.on(EVENT_CHANNEL, listener);
      let attached = true;
      return () => {
        if (!attached) return;
        attached = false;
        ipc.removeListener(EVENT_CHANNEL, listener);
      };
    },
  };
}
