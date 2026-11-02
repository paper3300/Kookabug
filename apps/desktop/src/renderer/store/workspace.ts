// 열린 워크스페이스·daemon 연결·탐색기 항목·출력 줄 (M2 계획 2.3·2.11)
import type { ResultOf } from "@kookabug/schema";
import { create } from "zustand";
import type { DaemonState, OpenResult, OutputLine, RecentProject } from "../../preload/bridge";
import type { TreeEntry } from "../explorer/tree";
import { client, toRpcError } from "../rpc/client";
import { SessionRecovery } from "../rpc/recovery";
import { breakpointModel } from "../debug/breakpoints";
import { runModel } from "../run/runStore";
import { framesHost, onWorkspaceChanged as onTargetFilesChanged, resetTargets } from "../target/targetStore";
import {
  documentsHost,
  onGraphChanged,
  resetDocuments,
  revalidateOpenDocs,
  setDocumentsConnection,
} from "./documents";
import { refreshRegistry, resetRegistry } from "./registry";
import { closeAllTabs } from "./tabs";
import { useUi } from "./ui";

export type WorkspaceInfo = ResultOf<"workspace.info">;

export interface OpenError {
  reason: "not_workspace" | "not_found";
  path: string;
}

interface WorkspaceState {
  root: string | null;
  name: string | null;
  daemon: DaemonState;
  info: WorkspaceInfo | null;
  entries: TreeEntry[];
  treeLoaded: boolean;
  output: OutputLine[];
  recent: RecentProject[];
  openError: OpenError | null;
}

const OUTPUT_MAX = 500;

export const useWorkspace = create<WorkspaceState>(() => ({
  root: null,
  name: null,
  daemon: { status: "idle", root: null, appProtocol: 1 },
  info: null,
  entries: [],
  treeLoaded: false,
  output: [],
  recent: [],
  openError: null,
}));

const app = () => window.kookabug.app;

/** 다시 붙은 뒤 복구. 문서 표(T8)·target 편집기(T12)·실행 화면(T11)이 Host를 등록한다 */
export const recovery = new SessionRecovery((method, params) => client().call(method, params));

function pushOutput(line: OutputLine): void {
  useWorkspace.setState((s) => {
    const output = [...s.output, line];
    return { output: output.length > OUTPUT_MAX ? output.slice(-OUTPUT_MAX) : output };
  });
}

function note(level: OutputLine["level"], message: string): void {
  pushOutput({ time: new Date().toISOString(), level, message });
}

export async function refreshTree(): Promise<void> {
  const root = useWorkspace.getState().root;
  if (root === null) return;
  try {
    const tree = await client().call("workspace.tree", {});
    if (useWorkspace.getState().root === root) useWorkspace.setState({ entries: tree.entries, treeLoaded: true });
  } catch (err) {
    note("warn", `탐색기를 읽지 못했다: ${toRpcError(err).message}`);
  }
}

export async function refreshInfo(): Promise<void> {
  const root = useWorkspace.getState().root;
  if (root === null) return;
  try {
    const info = await client().call("workspace.info", {});
    if (useWorkspace.getState().root === root) useWorkspace.setState({ info });
  } catch (err) {
    note("warn", `워크스페이스 정보를 읽지 못했다: ${toRpcError(err).message}`);
  }
}

/**
 * 프로젝트가 바뀌었다(열기·바꾸기·닫기). 프로젝트 상태를 한 곳에서 정리한다: 탭·탐색기 펼침·선택·빠른
 * 열기·실행 구독 커서·다시 붙기 복구. 주 프로세스의 daemon.state 루트가 바뀔 때 부른다 (루트의 권위는 주
 * 프로세스다. 열기 응답과 상태 알림의 순서와 무관하게 같은 결과)
 */
function switchProject(root: string | null): void {
  // 문서 표를 먼저 비운다: 앞 연결은 이미 놓았으므로 탭을 닫으며 graph.close를 보내지 않는다
  resetDocuments();
  resetTargets();
  resetRegistry();
  closeAllTabs();
  useUi.setState({ expanded: null, selected: null, quickOpen: false });
  runModel.reset();
  breakpointModel.reset();
  recovery.reset();
  useWorkspace.setState({
    root,
    name: root === null ? null : baseName(root),
    info: null,
    entries: [],
    treeLoaded: false,
    openError: null,
  });
}

/** 연결 번호가 없는 상태 알림을 매번 다른 연결로 보기 위한 수 */
let unnumbered = 0;

async function onDaemonState(state: DaemonState): Promise<void> {
  if (state.root !== useWorkspace.getState().root) switchProject(state.root);
  useWorkspace.setState({ daemon: state });
  // 문서 참조는 연결 단위다 (다시 열기 전에 지금 연결을 알려 둔다)
  setDocumentsConnection(
    state.status === "connected" && state.startId !== undefined
      ? `${state.startId}:${state.connection ?? `unknown-${++unnumbered}`}`
      : null,
  );
  if (state.status !== "connected" || state.root === null || state.startId === undefined) return;
  const kind = await recovery.connected({
    root: state.root,
    startId: state.startId,
    ...(state.connection === undefined ? {} : { connection: state.connection }),
  });
  if (useWorkspace.getState().root !== state.root) return;
  if (kind === "daemon_replaced") note("info", "daemon이 바뀌어 열린 문서를 다시 열었다");
  // 진행 중인 실행 다시 따라가기 (앱을 다시 열었거나 따라가던 실행이 없을 때). 따라가던 실행은 위 복구가
  // 적용한 마지막 seq부터 다시 구독했다
  const runs = kind === "same_connection" ? Promise.resolve() : runModel.syncActive();
  // 브레이크포인트는 daemon 파일 값이 기준이다: 붙을 때마다 받는다 (끊긴 동안 다른 창이 바꿨을 수 있다)
  await Promise.all([refreshTree(), refreshInfo(), loadRegistry(), runs, breakpointModel.load()]);
}

async function loadRegistry(): Promise<void> {
  try {
    await refreshRegistry();
  } catch (err) {
    note("warn", `노드 목록을 읽지 못했다: ${toRpcError(err).message}`);
  }
}

let treeTimer: ReturnType<typeof setTimeout> | null = null;

/** 앱 시작 때 한 번 */
export async function initWorkspace(): Promise<void> {
  window.kookabug.on("daemon.state", (data) => void onDaemonState(data as DaemonState));
  window.kookabug.on("daemon.log", (data) => pushOutput(data as OutputLine));
  client().on("workspace.changed", (p) => {
    if (treeTimer !== null) clearTimeout(treeTimer);
    treeTimer = setTimeout(() => void refreshTree(), 150);
    // 서브그래프·target·화면 파일이 바뀌면 열린 그래프의 검증 결과도 바뀐다
    revalidateOpenDocs();
    // 편집하지 않은 TARGET 탭은 디스크 버전으로 다시 연다
    onTargetFilesChanged(p.paths);
  });
  // 열린 문서의 디스크가 바뀜: 편집하지 않았으면 다시 열고, 편집 중이면 충돌 띠 (2.6)
  client().on("graph.changed", (p) => onGraphChanged(p.doc_id, p.revision ?? null));
  runModel.setHooks({ note });
  client().on("run.event", (p) => {
    try {
      runModel.event(p);
    } catch (err) {
      // 커서는 그대로다: 다음 이벤트·다시 붙기에서 이 seq부터 다시 받는다
      note("error", `실행 이벤트를 적용하지 못했다 (${p.run_id} #${p.seq}): ${(err as Error).message}`);
    }
  });
  client().on("run.lagged", (p) => runModel.lagged(p));
  client().on("run.ended", (p) => runModel.ended(p));
  client().on("lease.changed", (p) => runModel.lease(p));
  breakpointModel.setNote((message) => note("warn", message));
  client().on("debug.breakpoints.changed", (p) => breakpointModel.changed(p));
  recovery.addRuns(runModel.cursors);
  recovery.addDocs(documentsHost);
  recovery.addFrames(framesHost);
  const [recent, output, state] = await Promise.all([app().recent(), app().daemonLog(), app().daemonState()]);
  useWorkspace.setState({ recent, output });
  await onDaemonState(state);
}

function baseName(p: string): string {
  return p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() ?? p;
}

/**
 * 지금 프로젝트를 떠나도 되는지 묻는 함수들. 편집 버퍼가 생기면(T8·T9) 저장 안 된 문서를 묻는다.
 * 하나라도 false면 열기·바꾸기·닫기를 하지 않는다
 */
type LeaveGuard = () => Promise<boolean> | boolean;
const leaveGuards = new Set<LeaveGuard>();

export function addLeaveGuard(guard: LeaveGuard): () => void {
  leaveGuards.add(guard);
  return () => leaveGuards.delete(guard);
}

async function canLeaveProject(): Promise<boolean> {
  if (useWorkspace.getState().root === null) return true;
  for (const guard of leaveGuards) if (!(await guard())) return false;
  return true;
}

/** 열기 결과. 성공한 전환 자체는 daemon.state가 switchProject로 처리한다 */
async function afterOpen(result: OpenResult): Promise<void> {
  if (!result.ok) {
    if (result.reason !== "canceled") {
      useWorkspace.setState({ openError: { reason: result.reason, path: result.path ?? "" } });
    }
    return;
  }
  useWorkspace.setState({ openError: null, recent: await app().recent() });
}

export async function openFolder(): Promise<void> {
  if (!(await canLeaveProject())) return;
  await afterOpen(await app().openFolder());
}

export async function openRecent(path: string): Promise<void> {
  if (!(await canLeaveProject())) return;
  await afterOpen(await app().openRecent(path));
}

export async function closeWorkspace(): Promise<void> {
  if (!(await canLeaveProject())) return;
  await app().closeWorkspace();
  switchProject(null);
  useWorkspace.setState({ recent: await app().recent() });
}

export function dismissOpenError(): void {
  useWorkspace.setState({ openError: null });
}

export async function retryDaemon(): Promise<void> {
  await app().daemonRetry();
}

export async function restartDaemon(): Promise<void> {
  await app().daemonRestart();
}
