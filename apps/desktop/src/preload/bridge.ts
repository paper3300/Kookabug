// window.kookabug 로 내놓는 좁은 API (M2 계획 2.10). ipcRenderer를 인자로 받아 vitest가
// 가짜 ipc로 검사한다
import type { DaemonState } from "../main/daemon-state";
import {
  APP_CHANNEL,
  checkAppAction,
  checkRendererEvent,
  checkRendererMethod,
  EVENT_CHANNEL,
  RPC_CHANNEL,
} from "../main/ipc-guard";
import type { RpcErrorShape } from "../main/rpc-connection";

type Listener = (event: unknown, ...args: unknown[]) => void;

export interface IpcRendererLike {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, listener: Listener): unknown;
  removeListener(channel: string, listener: Listener): unknown;
}

export type ThemeMode = "system" | "light" | "dark";

/** 고른 테마와 실제 테마 (nativeTheme.shouldUseDarkColors) */
export interface ThemeState {
  mode: ThemeMode;
  dark: boolean;
}

export interface RecentProject {
  path: string;
  name: string;
  openedAt: string;
}

export type OpenResult =
  | { ok: true; root: string; name: string }
  | { ok: false; reason: "canceled" | "not_workspace" | "not_found"; path?: string };

export interface OutputLine {
  time: string;
  level: "info" | "warn" | "error";
  message: string;
}

export interface WindowState {
  maximized: boolean;
}

export type { DaemonState, RpcErrorShape };

/** 앱 API. 주 프로세스가 동작 이름과 인자를 다시 검사한다 */
export interface AppApi {
  openFolder(): Promise<OpenResult>;
  openRecent(path: string): Promise<OpenResult>;
  recent(): Promise<RecentProject[]>;
  closeWorkspace(): Promise<void>;
  themeGet(): Promise<ThemeState>;
  themeSet(mode: ThemeMode): Promise<ThemeState>;
  /** 디버그 툴바 가로 자리 (캔버스 가운데 기준 px) */
  debugToolbarGet(): Promise<number>;
  debugToolbarSet(x: number): Promise<void>;
  daemonState(): Promise<DaemonState>;
  daemonLog(): Promise<OutputLine[]>;
  daemonRetry(): Promise<DaemonState>;
  daemonRestart(): Promise<DaemonState>;
  windowControl(action: "minimize" | "maximize" | "close"): Promise<void>;
  windowState(): Promise<WindowState>;
  /** 창 닫기 때 렌더러에 물을지 (app.closeRequested 알림을 받을 준비가 됨) */
  closeGuard(on: boolean): Promise<void>;
  /** app.closeRequested의 답: true면 창을 닫는다 */
  closeAnswer(ok: boolean): Promise<void>;
}

export interface KookabugBridge {
  /** daemon 메서드. 실패하면 RpcErrorShape(평범한 객체)로 거부된다 */
  rpc(method: string, params?: unknown): Promise<unknown>;
  on(event: string, cb: (data: unknown) => void): () => void;
  app: AppApi;
}

type Envelope = { ok: true; result: unknown } | { ok: false; error: RpcErrorShape };

function appApi(ipc: IpcRendererLike): AppApi {
  const call =
    (action: string) =>
    (...args: unknown[]): Promise<never> => {
      checkAppAction(action);
      return ipc.invoke(APP_CHANNEL, action, ...args) as Promise<never>;
    };
  return {
    openFolder: call("openFolder"),
    openRecent: call("openRecent"),
    recent: call("recent"),
    closeWorkspace: call("closeWorkspace"),
    themeGet: call("themeGet"),
    themeSet: call("themeSet"),
    debugToolbarGet: call("debugToolbarGet"),
    debugToolbarSet: call("debugToolbarSet"),
    daemonState: call("daemonState"),
    daemonLog: call("daemonLog"),
    daemonRetry: call("daemonRetry"),
    daemonRestart: call("daemonRestart"),
    windowControl: call("windowControl"),
    windowState: call("windowState"),
    closeGuard: call("closeGuard"),
    closeAnswer: call("closeAnswer"),
  };
}

export function createBridge(ipc: IpcRendererLike): KookabugBridge {
  return {
    async rpc(method, params) {
      checkRendererMethod(method);
      const reply = (await ipc.invoke(RPC_CHANNEL, method, params)) as Envelope;
      if (reply.ok) return reply.result;
      // contextBridge가 평범한 객체로 복제한다 (Error의 추가 필드는 넘어가지 않는다)
      throw { code: reply.error.code, message: reply.error.message, data: reply.error.data };
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
    app: appApi(ipc),
  };
}
