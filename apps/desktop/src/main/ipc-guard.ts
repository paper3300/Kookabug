// IPC 다리 검사 (M2 계획 2.10 "IPC 다리"). preload와 주 프로세스가 같은 표를 쓴다.
// electron을 import하지 않는다: preload 번들과 vitest가 이 파일을 그대로 쓴다

export const RPC_CHANNEL = "kb:rpc";
export const EVENT_CHANNEL = "kb:event";
export const APP_CHANNEL = "kb:app";

// 렌더러가 부를 수 있는 daemon 메서드 (2.4 메서드 표 중 renderer: true). params 스키마 검사는
// 주 프로세스 ipc.ts가 daemon-rpc.schema.json으로 한다. 표와 같은지는 ipc.test.ts가 본다
export const RENDERER_METHODS: ReadonlySet<string> = new Set([
  "workspace.info",
  "workspace.tree",
  "nodes.list",
  "graph.open",
  "graph.validate",
  "graph.save",
  "graph.create",
  "graph.close",
  "run.start",
  "run.cancel",
  "run.status",
  "run.list",
  "run.subscribe",
  "run.unsubscribe",
  "windows.list",
  "target.capture",
  "target.load_image",
  "target.open",
  "target.preview",
  "target.save",
]);

// 주 프로세스 안에서만 쓰는 메서드. 렌더러 표면에서 뺀다
export const INTERNAL_METHODS: ReadonlySet<string> = new Set(["session.hello", "daemon.shutdown"]);

// 렌더러가 구독할 수 있는 알림
export const RENDERER_EVENTS: ReadonlySet<string> = new Set([
  "workspace.changed",
  "graph.changed",
  "run.event",
  "run.lagged",
  "run.ended",
  "lease.changed",
]);

// 주 프로세스가 보내는 앱 알림 (daemon 알림이 아님): 연결 상태, 출력 패널 줄, 창 최대화 상태, 테마,
// 창 닫기 확인 요청 (close-guard.ts)
export const APP_EVENTS: ReadonlySet<string> = new Set([
  "daemon.state",
  "daemon.log",
  "window.state",
  "theme.state",
  "app.closeRequested",
]);

// 앱 API (preload `window.kookabug.app`). 인자 모양은 주 프로세스가 다시 검사한다
export const APP_ACTIONS: ReadonlySet<string> = new Set([
  "openFolder",
  "openRecent",
  "recent",
  "closeWorkspace",
  "themeGet",
  "themeSet",
  "daemonState",
  "daemonLog",
  "daemonRetry",
  "daemonRestart",
  "windowControl",
  "windowState",
  "closeGuard",
  "closeAnswer",
]);

export class IpcGuardError extends Error {
  override name = "IpcGuardError";
}

export function checkAppAction(action: unknown): string {
  if (typeof action !== "string" || !APP_ACTIONS.has(action)) {
    throw new IpcGuardError(`허용되지 않은 앱 동작: ${String(action)}`);
  }
  return action;
}

export function checkRendererMethod(method: unknown): string {
  if (typeof method !== "string" || INTERNAL_METHODS.has(method) || !RENDERER_METHODS.has(method)) {
    throw new IpcGuardError(`허용되지 않은 메서드: ${String(method)}`);
  }
  return method;
}

export function checkRendererEvent(event: unknown): string {
  if (typeof event !== "string" || (!RENDERER_EVENTS.has(event) && !APP_EVENTS.has(event))) {
    throw new IpcGuardError(`허용되지 않은 알림: ${String(event)}`);
  }
  return event;
}

// WebFrameMain에서 쓰는 부분만
export interface FrameLike {
  readonly url: string;
  readonly processId: number;
  readonly routingId: number;
}

/**
 * 발신 프레임이 앱 창의 주 프레임이고 주소가 app://인지 본다. 하위 프레임(iframe)·다른 창·
 * 탐색으로 바뀐 페이지는 거부한다.
 */
export function checkSender(
  senderFrame: FrameLike | null | undefined,
  mainFrame: FrameLike | null | undefined,
  appOrigin: string,
): void {
  if (!senderFrame || !mainFrame) throw new IpcGuardError("발신 프레임이 없다");
  // 번호가 없으면(undefined === undefined) 같은 프레임으로 보지 않는다
  const ids = [senderFrame.processId, senderFrame.routingId, mainFrame.processId, mainFrame.routingId];
  const same =
    senderFrame === mainFrame ||
    (ids.every(Number.isInteger) &&
      senderFrame.processId === mainFrame.processId &&
      senderFrame.routingId === mainFrame.routingId);
  if (!same) throw new IpcGuardError("주 프레임이 아닌 곳에서 보낸 IPC");
  if (senderFrame.url !== appOrigin && !senderFrame.url.startsWith(`${appOrigin}/`)) {
    throw new IpcGuardError(`앱 주소가 아닌 프레임: ${senderFrame.url}`);
  }
}
