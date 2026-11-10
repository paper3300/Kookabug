// 에이전트 패널 상태 (M5 계획 3.10). 대화 한 줄 모델은 순수 함수(applyEvent·routeApproval)라 vitest로 본다.
// - 세션 = 주 프로세스가 띄운 에이전트 프로세스 하나 (window.kookabug.app.agent*). 대화는 저장하지 않는다 (C13)
// - 받은 조각은 마지막 답에 이어 붙이고, 도구 호출은 "작업 N초 · 도구 M개" 한 줄로 접는다 (진행 중이면 펼침)
// - 에이전트 자기 도구의 권한 요청은 그 선택지 그대로 카드로 (자동 허용 없음)
// - Kookabug 확인 요청(approval.requested): agent.id가 panel:<세션>이면 대화 안, 아니면 맨 위 "외부 에이전트" 카드
import type { NotificationParamsOf, ResultOf } from "@kookabug/schema";
import { create } from "zustand";
import type { AgentConfigOption, AgentEvent, AgentSessionEvent } from "../../preload/bridge";
import type { AgentPermissionOption } from "../../main/acp/events";
import { client, toRpcError } from "../rpc/client";
import { noteAllowSession } from "../screens/mapStore";

export type ApprovalRequest = NotificationParamsOf<"approval.requested">;
export type ApprovalVerdict = NotificationParamsOf<"approval.resolved">["verdict"];
export type AgentConnection = ResultOf<"agent.connections">["connections"][number];
export type AgentSpec = ResultOf<"agents.get">["agents"][number];
export type AgentCandidate = ResultOf<"agents.detect">["candidates"][number];
export type PermissionsInfo = ResultOf<"permissions.get">;

/** 입력창 @칩: 화면에는 label, 보낼 때는 text를 글 앞에 붙인다 */
export interface Chip {
  kind: "run" | "node" | "screen";
  label: string;
  text: string;
}

export interface ToolEntry {
  id: string;
  title: string;
  status: string;
  failed: boolean;
}

export type ChatItem =
  | { kind: "user"; key: number; text: string; chips: string[] }
  | { kind: "agent"; key: number; text: string }
  | { kind: "tools"; key: number; started: number; updated: number; tools: ToolEntry[]; hidden: number; open: boolean | null }
  | {
      kind: "acp_permission";
      key: number;
      id: string;
      title: string;
      options: AgentPermissionOption[];
      state: "open" | "selected" | "cancelled";
      chosen: string | null;
    }
  | { kind: "approval"; key: number; id: string }
  | { kind: "error"; key: number; text: string; restart: boolean };

export interface ApprovalCard {
  request: ApprovalRequest;
  /** open이면 답을 기다림, 그 밖은 닫힌 이유 */
  state: "open" | ApprovalVerdict;
  busy: boolean;
  error: string | null;
}

export interface SessionInfo {
  id: string;
  agentId: string;
  name: string;
  status: "starting" | "ready" | "busy" | "ended" | "error";
  /** 에이전트가 알려 준 세션 설정 (모델·생각 수준 등, 없으면 빈 배열) */
  config: AgentConfigOption[];
}

interface AgentState {
  session: SessionInfo | null;
  starting: string | null;
  startError: string | null;
  items: ChatItem[];
  approvals: ReadonlyMap<string, ApprovalCard>;
  /** 패널 맨 위 "외부 에이전트" 카드 (열린 것만) */
  external: string[];
  connections: AgentConnection[];
  agents: AgentSpec[];
  agentsRevision: string | null;
  defaultAgent: string | null;
  agentsProblem: string | null;
  agentsLoaded: boolean;
  candidates: AgentCandidate[] | null;
  permissions: PermissionsInfo | null;
  draft: string;
  chips: Chip[];
  /** 에이전트의 게임 조작이 입력 임대권에 막힘 (시안 Main 띠) */
  leaseBlocked: { owner: string | null } | null;
  /** 에이전트의 실행·조작이 무인 작업(agent-job)에 막힘 (`job_active`) */
  jobBlocked: boolean;
  /** 화면이 읽은 뒤 다른 곳에서 사용자 설정이 바뀌어 저장이 revision_conflict로 거부됨 ("다시 읽기" 전까지) */
  userConflict: boolean;
  /**
   * 화면이 받아들인 사용자 설정 revision (null = 아직 읽지 않음). 처음 읽기·"다시 읽기" 성공·자기 쓰기로만 바뀐다. 다른 경로의
   * 읽기(재연결 등)가 캐시를 바꿔도 그대로라, 캐시 revision과 다르면 다음 저장을 충돌로 본다 (review_merge_3)
   */
  userBase: { revision: string | null } | null;
  /** 자기 agents.set이 마지막에 저장한 기본 에이전트와 그 revision (뒤이은 자기 permissions.set만 revision을 이어 받는다) */
  ownDefault: { agentId: string | null; revision: string } | null;
}

const EMPTY: Omit<
  AgentState,
  "agents" | "agentsRevision" | "defaultAgent" | "agentsProblem" | "agentsLoaded" | "candidates" | "permissions" | "connections" | "userBase" | "ownDefault"
> = {
  session: null,
  starting: null,
  startError: null,
  items: [],
  approvals: new Map(),
  external: [],
  draft: "",
  chips: [],
  leaseBlocked: null,
  jobBlocked: false,
  userConflict: false,
};

export const useAgent = create<AgentState>(() => ({
  ...EMPTY,
  connections: [],
  agents: [],
  agentsRevision: null,
  defaultAgent: null,
  agentsProblem: null,
  agentsLoaded: false,
  candidates: null,
  permissions: null,
  userBase: null,
  ownDefault: null,
}));

let nextKey = 1;
const key = () => nextKey++;

// ── 순수 모델 ──────────────────────────────────────────────────

/** 세션 알림 하나를 대화 목록에 적용한다 (now: 밀리초) */
export function applyEvent(items: readonly ChatItem[], event: AgentEvent, now: number): ChatItem[] {
  const last = items[items.length - 1];
  const out = items.slice();
  switch (event.type) {
    case "message": {
      if (last?.kind === "agent") out[out.length - 1] = { ...last, text: last.text + event.text };
      else out.push({ kind: "agent", key: key(), text: event.text });
      return out;
    }
    case "tool": {
      const entry: ToolEntry = { id: event.id, title: event.title, status: event.status, failed: event.failed };
      // 같은 도구 호출의 갱신은 그 줄을 고친다 (중간에 말이 끼었어도)
      for (let i = out.length - 1; i >= 0; i--) {
        const item = out[i];
        if (item.kind === "tools" && item.tools.some((t) => t.id === event.id)) {
          out[i] = { ...item, updated: now, tools: item.tools.map((t) => (t.id === event.id ? entry : t)) };
          return out;
        }
      }
      if (last?.kind === "tools") out[out.length - 1] = { ...last, updated: now, tools: [...last.tools, entry] };
      else out.push({ kind: "tools", key: key(), started: now, updated: now, tools: [entry], hidden: 0, open: null });
      return out;
    }
    case "hidden": {
      if (last?.kind === "tools") out[out.length - 1] = { ...last, updated: now, hidden: last.hidden + 1 };
      else out.push({ kind: "tools", key: key(), started: now, updated: now, tools: [], hidden: 1, open: null });
      return out;
    }
    case "permission":
      out.push({ kind: "acp_permission", key: key(), id: event.id, title: event.title, options: event.options, state: "open", chosen: null });
      return out;
    case "permission_closed":
      return out.map((item) =>
        item.kind === "acp_permission" && item.id === event.id
          ? { ...item, state: event.outcome, chosen: event.optionId ?? null }
          : item,
      );
    default:
      return out;
  }
}

/** 답을 기다리는 카드 수: 에이전트 자기 도구 권한 카드 + Kookabug 확인 요청(세션·외부) — 패널이 접혀도 보인다 */
export function pendingCount(s: Pick<AgentState, "items" | "approvals">): number {
  const acp = s.items.filter((i) => i.kind === "acp_permission" && i.state === "open").length;
  let approvals = 0;
  for (const card of s.approvals.values()) if (card.state === "open") approvals++;
  return acp + approvals;
}

/** 도구 줄이 진행 중인가 (진행 중이면 펼친다) */
export function toolsRunning(item: Extract<ChatItem, { kind: "tools" }>): boolean {
  return item.tools.some((t) => t.status === "pending" || t.status === "in_progress");
}

/** "작업 N초 · 도구 M개" */
export function toolsSummary(item: Extract<ChatItem, { kind: "tools" }>): string {
  const seconds = Math.max(0, Math.round((item.updated - item.started) / 1000));
  return `작업 ${seconds}초 · 도구 ${item.tools.length}개`;
}

/**
 * 패널 세션이 낸 확인 요청인데 그 세션이 이미 끝났는가 (검수 B5 H1). 끝난 세션의 카드는 단추를 막는다 — daemon은
 * 그 MCP 연결이 끊기면 요청을 cancelled로 닫는다(approval.resolved)
 */
export function fromEndedSession(request: ApprovalRequest, session: SessionInfo | null): boolean {
  if (!request.agent.id.startsWith("panel:")) return false;
  return session === null || request.agent.id !== `panel:${session.id}` || session.status === "ended" || session.status === "error";
}

export type ApprovalAnswer = "allow_once" | "allow_session" | "allow_always" | "deny";

export interface ApprovalButton {
  verdict: Exclude<ApprovalAnswer, "deny">;
  label: string;
  primary: boolean;
}

/** 게임 조작 도구 (control 툴셋 — "항상 허용" 없음, M5 U2) */
export function isControlTool(tool: string): boolean {
  return tool.startsWith("kb_input_") || tool === "kb_app_launch";
}

/**
 * 확인 카드의 허용 단추 (M7 3.11). 거부는 카드가 늘 따로 둔다.
 * - 게임 조작: 허용 / 이 탐색 동안 허용(탐색 세션이 있을 때) — "항상 허용"은 daemon이 줘도 그리지 않는다
 * - 그 밖: 한 번 허용 / 이 탐색 동안 허용(daemon이 session을 줄 때 — 화면 지도 쓰기) / 항상 허용(규칙이 있을 때)
 * 단추는 렌더러에만 있다 — 답(approval.respond)은 사람(ui) 연결만 보낼 수 있다
 */
export function approvalButtons(r: ApprovalRequest): ApprovalButton[] {
  const control = isControlTool(r.tool);
  // 게임 실행(kb_app_launch)은 범위 인자가 없어 daemon이 session을 주지 않는다 — 렌더러도 그리지 않는다
  const exploring = r.session !== null && r.tool !== "kb_app_launch";
  const out: ApprovalButton[] = [
    { verdict: "allow_once", label: control && exploring ? "허용" : "한 번 허용", primary: true },
  ];
  if (exploring) out.push({ verdict: "allow_session", label: "이 탐색 동안 허용", primary: false });
  if (r.always_rule !== null && !control) out.push({ verdict: "allow_always", label: "항상 허용", primary: false });
  return out;
}

/** 이 확인 요청을 지금 세션 대화에 넣을지 (아니면 외부 에이전트 카드) */
export function belongsToSession(request: ApprovalRequest, session: string | null): boolean {
  return session !== null && request.agent.id === `panel:${session}`;
}

/** 도구 결과 글자에 입력 임대권 거부가 있는가 (control.* → input_lease_busy) */
export function leaseRefused(event: AgentEvent): boolean {
  return event.type === "tool" && event.text.includes("input_lease_busy");
}

/** 도구 결과 글자에 무인 작업 거부가 있는가 (작업 중 실행·제어·게임 띄우기 → job_active, M8 R8) */
export function jobRefused(event: AgentEvent): boolean {
  return event.type === "tool" && event.text.includes("job_active");
}

/** 칩과 글을 보낼 글자로 */
export function promptText(draft: string, chips: readonly Chip[]): string {
  const head = chips.map((c) => c.text).join("\n");
  return head === "" ? draft.trim() : `${head}\n\n${draft.trim()}`;
}

const PRESET_LABEL: Record<string, string> = {
  read_only: "읽기 전용",
  graph_author: "그래프 작성",
  runner: "실행",
  full: "전체",
  explorer: "탐색",
  curator: "지식 관리",
};

export function presetLabel(preset: string | null | undefined): string {
  return preset === null || preset === undefined ? "그래프 작성" : (PRESET_LABEL[preset] ?? preset);
}

/** 계층 값에서 실효 프리셋 (프로젝트 → 사용자 → 팀, 없으면 기본 graph_author) */
export function effectivePreset(info: PermissionsInfo | null): string {
  for (const name of ["project", "user", "team"] as const) {
    const layer = info?.layers?.find((l) => l.layer === name);
    const preset = (layer?.permissions as { preset?: unknown } | null | undefined)?.preset;
    if (typeof preset === "string") return preset;
  }
  return "graph_author";
}

/** 직접 입력한 명령줄을 명령·인자로 (큰따옴표로 묶은 칸은 한 인자) */
export function splitCommandLine(line: string): string[] {
  const out: string[] = [];
  const re = /"([^"]*)"|(\S+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line)) !== null) out.push(m[1] ?? m[2]);
  return out;
}

// ── 동작 ───────────────────────────────────────────────────────

const app = () => window.kookabug.app;

function setItems(fn: (items: readonly ChatItem[]) => ChatItem[]): void {
  useAgent.setState((s) => ({ items: fn(s.items) }));
}

function pushError(text: string, restart: boolean): void {
  setItems((items) => [...items, { kind: "error", key: key(), text, restart }]);
}

function errorText(err: unknown): string {
  const message = err instanceof Error ? err.message : String((err as { message?: unknown })?.message ?? err);
  // 주 프로세스 오류 "Error invoking remote method 'kb:app': Error: code: 메시지"
  return message.replace(/^Error invoking remote method '[^']*': (\w*Error: )?/, "");
}

let stopping: string | null = null;

function onSessionEvent(data: AgentSessionEvent): void {
  const { session } = useAgent.getState();
  if (session === null || data.session !== session.id) return;
  const event = data.event;
  if (event.type === "status") {
    useAgent.setState((s) => (s.session === null ? s : { session: { ...s.session, status: event.status } }));
    return;
  }
  if (event.type === "exit") {
    if (stopping !== data.session) pushError(`에이전트 프로세스가 끝났어요. ${event.message}`, true);
    return;
  }
  if (event.type === "turn_end") return;
  if (event.type === "config") {
    useAgent.setState((s) => (s.session === null ? s : { session: { ...s.session, config: event.options } }));
    return;
  }
  if (leaseRefused(event)) {
    const lease = currentLease();
    useAgent.setState({ leaseBlocked: { owner: lease } });
  }
  if (jobRefused(event)) useAgent.setState({ jobBlocked: true });
  setItems((items) => applyEvent(items, event, Date.now()));
}

/** 지금 입력 임대권 소유자 글 (실행 화면 저장소가 받은 lease.changed) */
let leaseSource: () => string | null = () => null;
export function setLeaseSource(fn: () => string | null): void {
  leaseSource = fn;
}
function currentLease(): string | null {
  return leaseSource();
}

function onApprovalRequested(request: ApprovalRequest): void {
  useAgent.setState((s) => {
    const approvals = new Map(s.approvals);
    approvals.set(request.id, { request, state: "open", busy: false, error: null });
    if (belongsToSession(request, s.session?.id ?? null)) {
      return { approvals, items: [...s.items, { kind: "approval", key: key(), id: request.id }] };
    }
    return { approvals, external: s.external.includes(request.id) ? s.external : [...s.external, request.id] };
  });
}

function onApprovalResolved(p: NotificationParamsOf<"approval.resolved">): void {
  // "이 탐색 동안 허용": 상태 바 "입력 도구: 이 탐색 동안 허용됨" (그 세션이 끝나면 사라진다)
  const session = useAgent.getState().approvals.get(p.id)?.request.session ?? null;
  if (p.verdict === "allow_session" && session !== null) noteAllowSession(session.id);
  useAgent.setState((s) => {
    const card = s.approvals.get(p.id);
    if (card === undefined) return s;
    const approvals = new Map(s.approvals);
    approvals.set(p.id, { ...card, state: p.verdict, busy: false });
    return { approvals, external: s.external.filter((id) => id !== p.id) };
  });
}

export async function refreshConnections(): Promise<void> {
  try {
    const { connections } = await client().call("agent.connections", {});
    useAgent.setState({ connections });
  } catch {
    // 연결 전: 다시 붙으면 다시 읽는다
  }
}

/**
 * 사용자 설정의 에이전트 목록을 읽는다. 읽었으면 true (파일 문제(`problem`)가 있어도 읽기는 된 것). 캐시만 바꾼다 — 저장 기준
 * (`userBase`)은 아직 없을 때만 정한다 (외부 변경은 "다시 읽기"로만 받아들인다)
 */
export async function refreshAgents(): Promise<boolean> {
  try {
    const got = await client().call("agents.get", {});
    useAgent.setState((s) => ({
      agents: got.agents,
      agentsRevision: got.revision ?? null,
      defaultAgent: got.default_agent ?? null,
      agentsProblem: got.problem ?? null,
      agentsLoaded: true,
      ...(s.userBase === null ? { userBase: { revision: got.revision ?? null } } : {}),
    }));
    return true;
  } catch (err) {
    useAgent.setState({ agentsProblem: toRpcError(err).message, agentsLoaded: true });
    return false;
  }
}

export async function refreshCandidates(): Promise<void> {
  try {
    const { candidates } = await client().call("agents.detect", {});
    useAgent.setState({ candidates });
  } catch {
    useAgent.setState({ candidates: [] });
  }
}

/** 권한 계층을 읽는다. 읽었으면 true */
export async function refreshPermissions(): Promise<boolean> {
  try {
    const permissions = await client().call("permissions.get", {});
    useAgent.setState((s) => ({
      permissions,
      ...(s.userBase === null ? { userBase: { revision: userLayerRevision(permissions) } } : {}),
    }));
    return true;
  } catch {
    // 연결 전
    return false;
  }
}

export const USER_RELOAD_FAILED_TEXT = "사용자 설정을 다시 읽지 못했어요. 잠시 뒤 다시 읽어 주세요.";

/**
 * 사용자 설정 다시 읽기 (충돌 안내의 "다시 읽기"·설정 화면을 열 때): 에이전트·권한을 새로 읽는다. 둘 다 읽었을 때만 충돌
 * 표시를 지우고 true. 하나라도 못 읽으면 충돌을 그대로 둔다 (옛 화면 값으로 저장이 풀리지 않게, review_merge_2)
 */
export async function reloadUserSettings(): Promise<boolean> {
  const [agents, permissions] = await Promise.all([refreshAgents(), refreshPermissions()]);
  if (!agents || !permissions) return false;
  const s = useAgent.getState();
  // 둘을 읽는 사이 바뀌었으면 (같은 파일이라 revision이 같아야 한다) 받아들이지 않는다
  if (s.agentsRevision !== userLayerRevision(s.permissions)) return false;
  useAgent.setState({ userConflict: false, userBase: { revision: s.agentsRevision } });
  return true;
}

function userLayerRevision(info: PermissionsInfo | null): string | null {
  return info?.layers?.find((l) => l.layer === "user")?.revision ?? null;
}

/**
 * 저장 기준 revision. 캐시(`cached`)가 화면이 받아들인 revision과 다르면(다른 경로의 읽기가 외부 변경을 가져옴) 충돌로 보고
 * `userConflict`를 켠다 — 새 revision을 몰래 쓰지 않는다. 충돌이면 undefined
 */
function userWriteBase(cached: string | null): string | null | undefined {
  const { userConflict, userBase } = useAgent.getState();
  if (userConflict) return undefined;
  if (userBase !== null && userBase.revision !== cached) {
    useAgent.setState({ userConflict: true });
    return undefined;
  }
  return userBase?.revision ?? cached;
}

/**
 * 자기 자신이 사용자 설정 파일에 쓴 뒤 그 응답 revision을 이어 받는다. 에이전트 목록과 사용자 권한 계층은 같은 파일이라
 * revision도 같다. 쓰기 전 기준(`before`)과 같은 값을 들고 있던 칸만 바꾼다 — 다른 값을 들고 있던 칸(그 사이 다른 곳에서
 * 바뀐 것을 본 적 없는 화면)은 그대로 두어 다음 저장이 revision_conflict로 거부되게 한다.
 * agents.set(`defaultAgent`)이면 `ownDefault`를 새로 두고, permissions.set(`preset`)이면 바로 앞이 자기 쓰기일 때만 이어 받는다
 */
function adoptUserRevision(before: string | null, after: string, patch: { preset: string } | { defaultAgent: string | null }): void {
  useAgent.setState((s) => {
    const preset = "preset" in patch ? patch.preset : undefined;
    const layers = s.permissions?.layers?.map((l) => {
      if (l.layer !== "user" || (l.revision ?? null) !== before) return l;
      const permissions = preset === undefined ? l.permissions : { ...((l.permissions ?? {}) as Record<string, unknown>), preset };
      return { ...l, revision: after, permissions } as typeof l;
    });
    const ownDefault =
      "defaultAgent" in patch
        ? { agentId: patch.defaultAgent, revision: after }
        : s.ownDefault !== null && s.ownDefault.revision === before
          ? { ...s.ownDefault, revision: after }
          : null;
    return {
      agentsRevision: s.agentsRevision === before ? after : s.agentsRevision,
      userBase: s.userBase === null || s.userBase.revision === before ? { revision: after } : s.userBase,
      ownDefault,
      ...(s.permissions !== null && layers !== undefined ? { permissions: { ...s.permissions, layers } } : {}),
    };
  });
}

/**
 * 이 앱이 자기 agents.set으로 `agentId`를 기본으로 저장했고, 그 뒤 자기 permissions.set만 이어졌는가 (캐시·저장 기준 모두 그
 * revision). 진행 콜백의 완료 조건 — 캐시의 기본 값이 같다는 것만으로는 완료하지 않는다
 */
export function ownDefaultSaved(agentId: string): boolean {
  const { userConflict, ownDefault, userBase, agentsRevision } = useAgent.getState();
  return !userConflict && ownDefault !== null && ownDefault.agentId === agentId && userBase?.revision === ownDefault.revision && agentsRevision === ownDefault.revision;
}

/**
 * 파일의 지금 revision이 저장 기준과 같은지 읽어 본다 (캐시·기준은 바꾸지 않는다). 다르면 `userConflict`를 켜고 false.
 * 읽기 실패면 null (충돌로 보지 않지만 끝내지도 않는다)
 */
export async function checkUserRevision(): Promise<boolean | null> {
  let revision: string | null;
  try {
    revision = (await client().call("agents.get", {})).revision ?? null;
  } catch {
    return null;
  }
  const { userBase } = useAgent.getState();
  if (userBase === null || userBase.revision !== revision) {
    useAgent.setState({ userConflict: true });
    return false;
  }
  return true;
}

async function loadApprovals(): Promise<void> {
  try {
    const { requests } = await client().call("approval.list", {});
    for (const r of requests) if (!useAgent.getState().approvals.has(r.id)) onApprovalRequested(r);
  } catch {
    // 연결 전
  }
}

/** 앱 시작 때 한 번 (store/workspace.ts initWorkspace) */
export function initAgent(): void {
  window.kookabug.on("agent.session", (data) => onSessionEvent(data as AgentSessionEvent));
  client().on("approval.requested", (p) => onApprovalRequested(p));
  client().on("approval.resolved", (p) => onApprovalResolved(p));
  client().on("agent.connections.changed", () => void refreshConnections());
}

/** daemon에 붙을 때마다 (끊긴 동안 바뀌었을 수 있다) */
export async function agentConnected(): Promise<void> {
  await Promise.all([refreshConnections(), refreshAgents(), refreshPermissions(), loadApprovals()]);
}

/** 프로젝트가 바뀜: 세션을 끝내고 비운다 */
export function resetAgent(): void {
  const { session } = useAgent.getState();
  if (session !== null) {
    stopping = session.id;
    void app().agentStop(session.id).catch(() => {});
  }
  useAgent.setState({ ...EMPTY, approvals: new Map(), connections: [], permissions: null, candidates: null });
}

export async function startSession(agentId: string): Promise<boolean> {
  const before = useAgent.getState().session;
  if (before !== null) {
    stopping = before.id;
    await app().agentStop(before.id).catch(() => {});
  }
  useAgent.setState({ starting: agentId, startError: null, session: null });
  try {
    const started = await app().agentStart(agentId);
    useAgent.setState({
      starting: null,
      session: { id: started.session, agentId: started.agentId, name: started.name, status: "ready", config: started.config ?? [] },
    });
    void refreshConnections();
    void applyRememberedConfig(started.session, started.agentId, started.config ?? []);
    return true;
  } catch (err) {
    useAgent.setState({ starting: null, startError: errorText(err) });
    return false;
  }
}

// ── 세션 설정 (패널 하단 Model·Effort) ────────────────────────────────
// 고른 값은 에이전트마다 이 PC에 기억해 두고, 다음 세션이 열리면 에이전트가 그 값을 아직 알려 줄 때만 다시 건다

const CONFIG_KEY = "kookabug.agentConfig.";

function rememberedConfig(agentId: string): Record<string, string> {
  try {
    const v = JSON.parse(window.localStorage.getItem(CONFIG_KEY + agentId) ?? "{}") as unknown;
    return typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, string>) : {};
  } catch {
    return {};
  }
}

function rememberConfig(agentId: string, id: string, value: string): void {
  try {
    window.localStorage.setItem(CONFIG_KEY + agentId, JSON.stringify({ ...rememberedConfig(agentId), [id]: value }));
  } catch {
    // 기억하지 못해도 이번 세션 값은 그대로다
  }
}

async function applyRememberedConfig(session: string, agentId: string, config: readonly AgentConfigOption[]): Promise<void> {
  const saved = rememberedConfig(agentId);
  for (const option of config) {
    const value = saved[option.id];
    if (value === undefined || value === option.current || !option.options.some((c) => c.value === value)) continue;
    if (useAgent.getState().session?.id !== session) return;
    try {
      const next = await app().agentSetConfig(session, option.id, value);
      useAgent.setState((s) => (s.session?.id !== session ? s : { session: { ...s.session, config: next } }));
    } catch {
      // 에이전트가 거절하면 에이전트 기본값으로 둔다
    }
  }
}

/** 패널 하단 Model·Effort 고르기 */
export async function setAgentConfig(id: string, value: string): Promise<void> {
  const { session } = useAgent.getState();
  if (session === null) return;
  try {
    const next = await app().agentSetConfig(session.id, id, value);
    rememberConfig(session.agentId, id, value);
    useAgent.setState((s) => (s.session?.id !== session.id ? s : { session: { ...s.session, config: next } }));
  } catch (err) {
    pushError(`설정을 바꾸지 못했어요: ${errorText(err)}`, false);
  }
}

/** 하단 Model 칸에 쓸 설정 (category model, 없으면 null) */
export function modelOption(config: readonly AgentConfigOption[]): AgentConfigOption | null {
  return config.find((o) => o.category === "model") ?? null;
}

/** 하단 Mode 칸에 쓸 설정 (category mode — 옛 modes도 mode로 읽는다) */
export function modeOption(config: readonly AgentConfigOption[]): AgentConfigOption | null {
  return config.find((o) => o.category === "mode") ?? null;
}

/** 하단 Effort 칸에 쓸 설정: category thought_level, 없으면 이름에 effort·reasoning·thinking이 든 것 */
export function effortOption(config: readonly AgentConfigOption[]): AgentConfigOption | null {
  return (
    config.find((o) => o.category === "thought_level") ??
    config.find((o) => o.category !== "model" && o.category !== "mode" && /effort|reasoning|think/i.test(`${o.id} ${o.name}`)) ??
    null
  );
}

/** 하단 Agent 칸: 다른 에이전트로 바꾼다 (대화가 있으면 끝난다고 묻는다) */
export async function switchAgent(agentId: string, confirm: () => Promise<boolean>): Promise<void> {
  const { session, items } = useAgent.getState();
  if (session?.agentId === agentId) return;
  if (session !== null && items.length > 0 && !(await confirm())) return;
  useAgent.setState({ items: [], leaseBlocked: null, jobBlocked: false });
  await startSession(agentId);
}

/** 새 대화: 같은 에이전트로 새 세션, 대화 비우기 */
export async function newConversation(): Promise<void> {
  const { session } = useAgent.getState();
  useAgent.setState({ items: [], leaseBlocked: null, jobBlocked: false });
  if (session !== null) await startSession(session.agentId);
}

/** 세션 끝 (빈 화면으로) */
export async function endSession(): Promise<void> {
  const { session } = useAgent.getState();
  if (session === null) return;
  stopping = session.id;
  useAgent.setState({ session: null, items: [], leaseBlocked: null, jobBlocked: false });
  await app().agentStop(session.id).catch(() => {});
}

export async function sendPrompt(): Promise<void> {
  const { session, draft, chips } = useAgent.getState();
  if (session === null || session.status === "busy") return;
  const text = promptText(draft, chips);
  if (text === "") return;
  useAgent.setState((s) => ({
    draft: "",
    chips: [],
    items: [...s.items, { kind: "user", key: key(), text: draft.trim(), chips: chips.map((c) => c.label) }],
  }));
  try {
    await app().agentPrompt(session.id, text);
  } catch (err) {
    // 프로세스가 끝나 실패한 보내기는 끝남 오류 줄(다시 시작)이 대신한다
    await new Promise((r) => setTimeout(r, 200));
    const now = useAgent.getState().session;
    if (now?.id === session.id && now.status !== "ended" && now.status !== "error") pushError(errorText(err), false);
  }
}

export async function cancelPrompt(): Promise<void> {
  const { session } = useAgent.getState();
  if (session !== null) await app().agentCancel(session.id).catch(() => {});
}

export async function restartSession(): Promise<void> {
  const { session } = useAgent.getState();
  if (session !== null) await startSession(session.agentId);
}

export async function answerAcpPermission(id: string, optionId: string | null): Promise<void> {
  const { session } = useAgent.getState();
  if (session === null) return;
  await app().agentPermission(session.id, id, optionId).catch(() => false);
}

export async function respondApproval(id: string, verdict: ApprovalAnswer): Promise<void> {
  const { approvals, session } = useAgent.getState();
  const card = approvals.get(id);
  if (card === undefined || card.state !== "open") return;
  if (fromEndedSession(card.request, session)) return; // 끝난 세션의 요청은 답하지 않는다
  const patch = (p: Partial<ApprovalCard>) =>
    useAgent.setState((s) => {
      const c = s.approvals.get(id);
      return c === undefined ? s : { approvals: new Map(s.approvals).set(id, { ...c, ...p }) };
    });
  patch({ busy: true, error: null });
  try {
    await client().call("approval.respond", { id, verdict });
  } catch (err) {
    const e = toRpcError(err);
    const text =
      e.kind === "not_found"
        ? "이미 닫힌 요청이에요"
        : e.kind === "session_not_allowed"
          ? "탐색 세션이 없어 '이 탐색 동안 허용'을 쓸 수 없어요"
          : e.message;
    patch({ busy: false, error: text });
  }
}

export function setDraft(draft: string): void {
  useAgent.setState({ draft });
}

export function addChip(chip: Chip): void {
  useAgent.setState((s) => (s.chips.some((c) => c.label === chip.label) ? s : { chips: [...s.chips, chip] }));
}

export function removeChip(label: string): void {
  useAgent.setState((s) => ({ chips: s.chips.filter((c) => c.label !== label) }));
}

export function toggleTools(itemKey: number): void {
  setItems((items) =>
    items.map((item) =>
      item.kind === "tools" && item.key === itemKey ? { ...item, open: !(item.open ?? toolsRunning(item)) } : item,
    ),
  );
}

export function dismissLease(): void {
  useAgent.setState({ leaseBlocked: null });
}

export function dismissJobBlocked(): void {
  useAgent.setState({ jobBlocked: false });
}

/** 사용자 설정 에이전트 목록에 더하거나 바꾼다 (agents.set, revision) */
export async function saveAgent(spec: AgentSpec): Promise<void> {
  const { agents, agentsRevision, defaultAgent } = useAgent.getState();
  const base = userWriteBase(agentsRevision);
  if (base === undefined) throw new Error(USER_CONFLICT_TEXT);
  const next = agents.some((a) => a.id === spec.id) ? agents.map((a) => (a.id === spec.id ? spec : a)) : [...agents, spec];
  let revision: string;
  try {
    ({ revision } = await client().call("agents.set", { agents: next, default_agent: defaultAgent, base_revision: base }));
  } catch (err) {
    if (toRpcError(err).kind === "revision_conflict") useAgent.setState({ userConflict: true });
    throw err;
  }
  useAgent.setState({ agents: next });
  adoptUserRevision(base, revision, { defaultAgent });
}

/** 권한 프리셋 고르기 목록 (값, 보이는 글자) */
export const PRESETS: [string, string][] = [
  ["graph_author", "그래프 작성 — 읽기 + 편집은 확인 후"],
  ["read_only", "읽기 전용"],
  ["runner", "실행 — 작성 + 실행, 입력은 확인 후"],
  ["explorer", "탐색 — 화면 지도 쓰기, 게임 조작은 확인 후"],
  // 마법사 5단계가 추천하는 값이라 패널 고르기에도 있어야 지금 값이 보인다
  ["curator", "지식 관리 — 지식·사건·작업 기준 편집, 게임 조작은 확인 후"],
  ["full", "전체 (주의)"],
];

export type CandidateTone = "ready" | "npx" | "blocked" | "missing";

/** 감지한 에이전트 한 줄의 상태 글자: 연결 가능·npx로 어댑터 받음·본체만 있음·설치 안 됨 */
export function candidateStatus(c: AgentCandidate): { tone: CandidateTone; text: string } {
  if (c.via === "path") return { tone: "ready", text: "연결 준비됨" };
  if (c.via === "npx") return { tone: "npx", text: `처음 연결할 때 ACP 어댑터(${c.package ?? "?"})를 npx로 받아요` };
  if (c.cli_path !== null) {
    return c.package !== null
      ? { tone: "blocked", text: `${c.cli}는 있지만 Node.js(npx)가 없어 ACP 어댑터를 띄울 수 없어요` }
      : { tone: "blocked", text: `${c.cli}는 있지만 ACP 연결 명령을 찾지 못했어요` };
  }
  return { tone: "missing", text: `설치 안 됨 (${c.cli} 명령을 찾지 못함)` };
}

/**
 * 에이전트 설정 저장 (마법사 5단계 — 에이전트 패널 "설정 도우미"도 같은 화면): 고른 에이전트를 설정에 더하고(이미 있는 id는
 * 그대로) 기본 에이전트·권한 프리셋을 정한다. 패널과 같은 저장소 revision을 쓴다(서로 다른 revision으로 덮지 않게).
 * revision 충돌(외부 변경)이면 다시 읽지 않고 `userConflict`를 켠다 — 사람이 "다시 읽기"로 바뀐 값을 본 뒤에만 받아들인다
 * (review_merge_3). 실패하면 이유 글자, 성공하면 null
 */
export async function saveAgentSetup(
  picked: readonly Pick<AgentSpec, "id" | "name" | "command" | "args">[],
  defaultId: string | null,
  preset: string | null,
): Promise<string | null> {
  if (useAgent.getState().userConflict) return USER_CONFLICT_TEXT;
  if (!useAgent.getState().agentsLoaded) await refreshAgents();
  const { agents, agentsRevision, defaultAgent } = useAgent.getState();
  const base = userWriteBase(agentsRevision);
  if (base === undefined) return USER_CONFLICT_TEXT;
  const have = new Set(agents.map((a) => a.id));
  const next = [...agents, ...picked.filter((c) => !have.has(c.id)).map((c) => ({ id: c.id, name: c.name, command: c.command, args: c.args }))];
  const written = defaultId ?? defaultAgent;
  try {
    const { revision } = await client().call("agents.set", { agents: next, default_agent: written, base_revision: base });
    useAgent.setState({ agents: next, defaultAgent: written });
    adoptUserRevision(base, revision, { defaultAgent: written });
  } catch (err) {
    const e = toRpcError(err);
    if (e.kind === "revision_conflict") {
      useAgent.setState({ userConflict: true });
      return USER_CONFLICT_TEXT;
    }
    return e.message;
  }
  if (preset !== null && preset !== effectivePreset(useAgent.getState().permissions)) return setUserPreset(preset);
  return null;
}

/** 감지한 에이전트로 연결: 설정에 없으면 더한 뒤 세션 시작 */
export async function connectCandidate(c: AgentCandidate): Promise<void> {
  try {
    if (!useAgent.getState().agents.some((a) => a.id === c.id)) {
      await saveAgent({ id: c.id, name: c.name, command: c.command, args: c.args });
    }
  } catch (err) {
    useAgent.setState({ startError: toRpcError(err).message });
    await refreshAgents();
    return;
  }
  await startSession(c.id);
}

/** 직접 입력한 명령줄을 설정에 더하고 연결 */
export async function connectManual(name: string, line: string): Promise<void> {
  const [command, ...args] = splitCommandLine(line);
  if (command === undefined) {
    useAgent.setState({ startError: "명령을 입력해 주세요" });
    return;
  }
  const taken = new Set(useAgent.getState().agents.map((a) => a.id));
  let n = 1;
  while (taken.has(`custom-${n}`)) n++;
  const id = `custom-${n}`;
  try {
    await saveAgent({ id, name: name.trim() || command, command, args });
  } catch (err) {
    useAgent.setState({ startError: toRpcError(err).message });
    await refreshAgents();
    return;
  }
  await startSession(id);
}

/** 프리셋 저장 충돌 글자 (마법사 Conflict.tsx와 같은 문구) */
export const USER_CONFLICT_TEXT = "다른 곳에서 설정이 바뀌었어요";

/**
 * 프리셋 고르기 (사용자 계층 permissions.preset만 바꾼다). 에이전트 패널·마법사 5단계가 같이 쓴다.
 * 기준은 **화면이 읽은 권한**(`useAgent.permissions`)의 사용자 계층 값·revision이다. 저장 직전에 다시 읽어 revision을 갈아
 * 끼우지 않는다 — 그 사이 다른 곳에서 바뀌었으면 daemon이 revision_conflict로 거부하고 `userConflict`가 켜진다(사람이
 * "다시 읽기"로 바뀐 값을 보고 다시 고른다, B7 마법사와 같은 방식). 같은 흐름에서 자기가 먼저 쓴 agents 저장의 revision은
 * `adoptUserRevision`이 이어 받아 둔다. 실패하면 이유 글자, 성공하면 null
 */
export async function setUserPreset(preset: string): Promise<string | null> {
  if (useAgent.getState().userConflict) return USER_CONFLICT_TEXT;
  let problem: string | null = null;
  try {
    // 화면이 아직 한 번도 읽지 않았을 때만 지금 읽는다 (그 값이 곧 이 저장의 기준)
    if (useAgent.getState().permissions === null) await refreshPermissions();
    const info = useAgent.getState().permissions;
    const user = info?.layers?.find((l) => l.layer === "user");
    const current = (user?.permissions ?? {}) as Record<string, unknown>;
    const base = userWriteBase(user?.revision ?? null);
    if (base === undefined) return USER_CONFLICT_TEXT;
    const { revision } = await client().call("permissions.set", {
      layer: "user",
      permissions: { ...current, preset },
      base_revision: base,
    });
    adoptUserRevision(base, revision, { preset });
  } catch (err) {
    const e = toRpcError(err);
    if (e.kind === "revision_conflict") {
      // 다시 읽지 않는다: 화면은 읽은 값 그대로, 사람이 "다시 읽기"를 누른다
      useAgent.setState({ userConflict: true });
      return USER_CONFLICT_TEXT;
    }
    problem = e.message;
    useAgent.setState({ startError: problem });
  }
  await refreshPermissions();
  return problem;
}
