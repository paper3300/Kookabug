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
  // 다듬기 P1-B: 탐색기 파일 보기 탭
  "workspace.read",
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
  // M3 디버거 (계획 2.3)
  "debug.breakpoints.get",
  "debug.breakpoints.set",
  "run.pause",
  "run.resume",
  "run.restart",
  // M3 기록 읽기 (계획 2.7)
  "run.index",
  "run.children",
  "run.step",
  "run.file",
  "run.compare",
  // M4 녹화·비밀값 (계획 2.9): daemon이 소유 연결을 검사한다
  "recorder.start",
  "recorder.pause",
  "recorder.resume",
  "recorder.stop",
  "recorder.discard",
  "recorder.state",
  "recorder.steps",
  "recorder.step.update",
  "recorder.frame",
  "recorder.insert_check",
  "recorder.commit_prepare",
  "recorder.commit_finish",
  "recorder.commit_abort",
  "recorder.target.materialize",
  "secrets.list",
  "secrets.create",
  "target.read_text",
  // M5 사람 확인·권한 설정 (계획 3.5·3.6): 답·설정은 사람(ui 연결)만 — daemon이 agent 연결을 거부한다
  "approval.list",
  "approval.respond",
  "approval.preview",
  "permissions.get",
  "permissions.set",
  // M5 B5 에이전트 패널: 에이전트 목록(사용자 설정)·감지·agent 연결 목록
  "agents.get",
  "agents.detect",
  "agents.set",
  "agent.connections",
  // M6 B4 플러그인: 목록(조회)과 설치·제거·준비·다시 잠그기·정리(사람만 — daemon이 agent 연결을 거부한다)
  "plugins.list",
  "plugins.preview",
  "plugins.install",
  "plugins.upgrade",
  "plugins.remove",
  "plugins.sync",
  "plugins.relock",
  "plugins.gc",
  "plugins.cancel",
  // M7 탐색 세션 목록 (사람 화면용 — daemon이 agent 연결을 거부한다)
  "explore.list",
  // M7 B4 이동 그래프 (화면 지도 탭)
  "screens.map",
  // M7 화면 지도 사람 전용 (승격·버리기·확인·카드 배치 — daemon이 agent 연결을 거부한다)
  "screens.check",
  "screens.promote",
  "screens.discard",
  "screens.layout_get",
  "screens.layout_set",
]);

// 주 프로세스 안에서만 쓰는 메서드. 렌더러 표면에서 뺀다. run.export는 dest(쓸 경로)를 주 프로세스의
// 저장 대화 상자가 정한다 — 렌더러가 임의 경로에 쓰게 하지 않는다 (M3 계획 2.7)
export const INTERNAL_METHODS: ReadonlySet<string> = new Set([
  "session.hello",
  "daemon.shutdown",
  "run.export",
]);

// 렌더러가 구독할 수 있는 알림
export const RENDERER_EVENTS: ReadonlySet<string> = new Set([
  "workspace.changed",
  "graph.changed",
  "run.event",
  "run.lagged",
  "run.ended",
  "lease.changed",
  "debug.breakpoints.changed",
  "recorder.changed",
  // M5 사람 확인 카드·agent 연결 목록 (ui 연결에만 온다)
  "approval.requested",
  "approval.resolved",
  "agent.connections.changed",
  // M7 에이전트 보호 기록 손상 알림·탐색 세션 변경 (ui 연결에만, 화면 표시는 B5)
  "agent.protect_corrupt",
  "explore.changed",
  // M7 B4 화면 지도 파일 변경 (ui 연결에만)
  "screens.changed",
  // M6 B4 플러그인 작업 진행·끝(ui 연결에만), 잠금 변경
  "plugins.progress",
  "plugins.done",
  "plugins.changed",
]);

// 주 프로세스가 보내는 앱 알림 (daemon 알림이 아님): 연결 상태, 출력 패널 줄, 창 최대화 상태, 테마,
// 창 닫기 확인 요청 (close-guard.ts)
export const APP_EVENTS: ReadonlySet<string> = new Set([
  "daemon.state",
  "daemon.log",
  "window.state",
  "theme.state",
  "app.closeRequested",
  // 에이전트 패널 세션 (M5 B5, acp/host.ts): 대화·도구 호출·권한 카드·끝남
  "agent.session",
]);

// 앱 API (preload `window.kookabug.app`). 인자 모양은 주 프로세스가 다시 검사한다
export const APP_ACTIONS: ReadonlySet<string> = new Set([
  "openFolder",
  "openRecent",
  "recent",
  "closeWorkspace",
  "themeGet",
  "themeSet",
  "debugToolbarGet",
  "debugToolbarSet",
  "daemonState",
  "daemonLog",
  "daemonRetry",
  "daemonRestart",
  "windowControl",
  "windowState",
  "closeGuard",
  "closeAnswer",
  // 기록 뷰어 "분석 번들 내보내기": 저장 대화 상자 → run.export (M3 T11, dialogs.ts)
  "exportRun",
  // 녹화 단축키 등록·해제 (M4 T9, shortcuts.ts): 등록에 성공해야 recorder.start를 보낸다
  "recorderArm",
  "recorderDisarm",
  // 에이전트 패널 (M5 B5, acp/host.ts): 띄울 명령은 daemon agents.get에서 ID로 찾는다 (렌더러가 주지 않는다)
  "agentStart",
  "agentPrompt",
  "agentCancel",
  "agentPermission",
  "agentStop",
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
