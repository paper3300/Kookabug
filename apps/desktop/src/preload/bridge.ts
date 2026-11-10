// window.kookabug 로 내놓는 좁은 API (M2 계획 2.10). ipcRenderer를 인자로 받아 vitest가
// 가짜 ipc로 검사한다
import type { AgentConfigOption, AgentEvent, AgentSessionEvent, AgentStartResult } from "../main/acp/events";
import type { DaemonState } from "../main/daemon-state";
import type { ExportResult } from "../main/dialogs";
import {
  APP_CHANNEL,
  checkAppAction,
  checkJobArgs,
  checkRendererEvent,
  checkRendererMethod,
  EVENT_CHANNEL,
  RPC_CHANNEL,
} from "../main/ipc-guard";
import type { RpcErrorShape } from "../main/rpc-connection";
import type { ArmResult } from "../main/shortcuts";

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

export type { AgentConfigOption, AgentEvent, AgentSessionEvent, AgentStartResult, ArmResult, DaemonState, ExportResult, RpcErrorShape };

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
  /** 패널 배치 (store/ui.ts Layout) */
  layoutGet(): Promise<unknown>;
  layoutSet(layout: unknown): Promise<void>;
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
  /** 실행 폴더를 zip으로: 저장 대화 상자가 고른 곳에 run.export (M3 T11) */
  exportRun(runId: string): Promise<ExportResult>;
  /** 녹화 단축키 등록 (M4 T9). 실패하면 recorder.start를 보내지 않는다 */
  recorderArm(): Promise<ArmResult>;
  /** 녹화 단축키 해제 */
  recorderDisarm(): Promise<void>;
  /** 에이전트 패널 세션 시작 (M5 B5): 사용자 설정의 그 에이전트를 띄우고 ACP 세션을 연다 */
  agentStart(agentId: string): Promise<AgentStartResult>;
  /** 글자 하나 보내기. 끝나면 stopReason (대화 갱신은 agent.session 알림) */
  agentPrompt(session: string, text: string): Promise<{ stopReason: string }>;
  /** 중지 (session/cancel) */
  agentCancel(session: string): Promise<void>;
  /** 에이전트 권한 카드의 답 (optionId null = 닫기·cancelled). 에이전트가 준 선택지만 받는다 */
  agentPermission(session: string, id: string, optionId: string | null): Promise<boolean>;
  /** 세션 설정(모델·생각 수준 등) 바꾸기 → 바뀐 설정 전체 */
  agentSetConfig(session: string, id: string, value: string): Promise<AgentConfigOption[]>;
  /** 세션 끝 (프로세스 트리 종료, 열린 카드는 cancelled) */
  agentStop(session: string): Promise<void>;
  /** 마법사 1단계 위치 고르기 (M8 B7). 취소면 null */
  pickFolder(): Promise<string | null>;
  /** 마법사 1단계: kookabug workspace new → 그 폴더를 연다 */
  workspaceCreate(request: { parent: string; name: string; git: boolean }): Promise<OpenResult>;
  /** 마법사 5단계 연결 시험 (agent-job probe). Agent는 사용자 설정의 ID */
  agentProbe(agentId: string): Promise<JobCliResult & { ok: boolean }>;
  /** 마법사 9단계 Init (agent-job run, 기다리지 않음). 끝나면 jobs.cli 알림 */
  agentJobRun(playbook: "init", agentId: string): Promise<{ started: boolean; error_code?: string }>;
  /** 마법사 3단계 환경 점검 (kookabug doctor --json, 항목 ID·통과만) */
  doctor(): Promise<{ ok: boolean; checks: { id: string; ok: boolean }[] }>;
}

/** agent-job CLI `--json` 결과의 정해진 필드 (jobs.ts pickResult) */
export interface JobCliResult {
  job?: string;
  state?: string;
  exit_code?: number | null;
  error_code?: string;
  code?: string;
  probe_ok?: boolean;
  report?: string | null;
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
      checkJobArgs(action, args);
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
    layoutGet: call("layoutGet"),
    layoutSet: call("layoutSet"),
    daemonState: call("daemonState"),
    daemonLog: call("daemonLog"),
    daemonRetry: call("daemonRetry"),
    daemonRestart: call("daemonRestart"),
    windowControl: call("windowControl"),
    windowState: call("windowState"),
    closeGuard: call("closeGuard"),
    closeAnswer: call("closeAnswer"),
    exportRun: call("exportRun"),
    recorderArm: call("recorderArm"),
    recorderDisarm: call("recorderDisarm"),
    agentStart: call("agentStart"),
    agentPrompt: call("agentPrompt"),
    agentCancel: call("agentCancel"),
    agentPermission: call("agentPermission"),
    agentSetConfig: call("agentSetConfig"),
    agentStop: call("agentStop"),
    pickFolder: call("pickFolder"),
    workspaceCreate: call("workspaceCreate"),
    agentProbe: call("agentProbe"),
    agentJobRun: call("agentJobRun"),
    doctor: call("doctor"),
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
