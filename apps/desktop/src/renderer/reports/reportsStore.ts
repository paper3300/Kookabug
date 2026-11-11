// 보고함 상태 (M8 계획 3.11·3.17, KB문서 12장). 목록 = 작업(jobs.list) + 보고(reports.list), 상세 = reports.get.
// 사람 결정은 모두 사람 전용 daemon 메서드로만 간다: 묶음 수락·거절 `report.decide`, 자동 채택 되돌리기 `adopt.revert`,
// 질문 답 `unknowns.answer`(UX2: "답 보내기" 한 번에 글을 넣은 질문 전부), 설정 제안 수락·거절 `report.decide`,
// "이어서 진행" = 주 프로세스 `agentJobRun("followup")`, 작업 취소 `job.end`. 렌더러는 작업 토큰·Agent 연결을 갖지 않는다.
// 같은 결정을 두 번 보내지 않게 진행 중인 동작 키를 들고 있다(두 번 누르기)
import { create } from "zustand";
import { client, toRpcError } from "../rpc/client";
import type { JobCliResult, KookabugBridge } from "../../preload/bridge";
import { useTabs } from "../store/tabs";

export interface ReportItem {
  kind: string;
  case?: string;
  adoption?: string;
  change?: string;
  checks?: string[];
  evidence?: string;
  claims?: { id: string; rev: number }[];
  detail?: string;
  unknowns?: string[];
  cheat?: string;
  summary?: Record<string, unknown>;
  /** UX2 설정 바꾸기 제안 (Agent 제안 → 사람이 수락·거절) */
  setting?: SettingProposal;
}

export interface SettingProposal {
  id: string;
  key: string;
  reason: string;
  /**
   * 이 PC `proposals.json`의 값 (`reports.get`이 붙인다 — 팀 보고 파일에는 값이 없다, UX2 검수 1 H1). null이면 다른 PC에서
   * 만든 제안이라 값을 볼 수 없고 수락할 수 없다
   */
  local?: SettingLocal | null;
}

export interface SettingLocal {
  value: unknown;
  /** 제안 때 그 키의 값 (목록에 더하는 키는 그때 목록). 비밀값이 있어 남기지 않았으면 null + `current_hidden` */
  current: unknown;
  current_hidden: boolean;
  reason?: string;
}

export const NOT_LOCAL_TEXT = "이 PC에서 만든 제안이 아니라 값을 볼 수 없어요";
export const HIDDEN_TEXT = "[가림]";

/** 설정 제안을 수락할 수 있나: 이 PC 제안 파일이 있을 때만 (없으면 거절만) */
export function settingAcceptable(setting: SettingProposal | undefined): boolean {
  return setting !== undefined && setting.local != null;
}

export interface ReportGroup {
  key: string;
  cause: string;
  title: string;
  items: ReportItem[];
  decision: { decision: string; by: string; at: string } | null;
}

export interface Report {
  job: string;
  playbook: string;
  trigger?: string;
  agent?: string;
  state: string;
  started_at?: string;
  ended_at?: string | null;
  budget?: { minutes?: [number, number]; runs?: [number, number] };
  groups: ReportGroup[];
  unknowns?: string[];
  notes?: string;
  rendered?: string;
}

export interface Row {
  job: string;
  playbook: string;
  state: string;
  startedAt: string;
  groups: number | null;
  undecided: number;
  hasReport: boolean;
  used: { runs?: number; minutes?: number } | null;
}

export interface Unknown {
  id: string;
  rev: number;
  question: string;
  human_only?: boolean;
  state: string;
  options?: string[];
  answer?: { text: string } | null;
}

export const STATE_TEXT: Record<string, string> = {
  running: "진행 중",
  ending: "끝내는 중",
  done: "끝남",
  failed: "실패",
  cancelled: "취소됨",
  budget_exhausted: "예산 소진",
  interrupted: "중단됨",
  prep_failed: "준비 실패",
  recovery_unconfirmed: "입력 복구 확인 중",
};

export const KIND_TEXT: Record<string, string> = {
  auto_adopted: "자동 수리",
  working_only: "작업 기준에만",
  regression_suspect: "회귀 의심",
  undetermined: "판단 불가",
  cheat_candidate: "치트 후보",
  init_summary: "Init 요약",
  budget: "예산",
  stalled: "정체",
  prep_failed: "준비 실패",
  setting_change: "설정 제안",
};

/** 설정 제안 키 → 사람이 읽는 이름 (마법사 단계의 칸 이름) */
export const SETTING_LABEL: Record<string, string> = {
  "game.title": "게임 창 제목",
  "game.executable": "실행 파일",
  "game.args": "실행 인자",
  "game.cwd": "작업 폴더",
  "sources.add": "정보 원본 추가",
  "cheats.categories.add": "치트 분류 추가",
  "automation.forbidden.add": "금지 동작 추가",
};

const ADD_KEYS = new Set(["sources.add", "cheats.categories.add", "automation.forbidden.add"]);

function obj(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
}

/** 제안 값 한 줄 (글로만 그린다 — HTML 아님) */
export function settingValueText(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "(없음)";
  if (key === "game.args" && Array.isArray(value)) {
    return value.length === 0 ? "(없음)" : value.map((a) => (/[\s"]/.test(String(a)) || a === "" ? JSON.stringify(String(a)) : String(a))).join(" ");
  }
  if (typeof value === "string") return value;
  const v = obj(value);
  if (key === "sources.add") return `${String(v.title ?? v.kind ?? "")}: ${String(v.location ?? "")}`;
  if (key === "cheats.categories.add") return `${String(v.title ?? "")} (${String(v.id ?? "")}) · 무인 ${v.unattended === true ? "허용" : "안 함"}`;
  if (key === "automation.forbidden.add") {
    if (v.kind === "text") return `문구 "${String(v.value ?? "")}"`;
    if (v.kind === "target") return `target ${String(v.path ?? "")}`;
    if (v.kind === "screen") return `화면 ${String(v.id ?? "")}`;
  }
  return JSON.stringify(value);
}

/** 현재 값 한 줄: 목록에 더하는 키는 지금 개수, 비밀값이 있어 남기지 않았으면 "[가림]" */
export function settingCurrentText(key: string, current: unknown, hidden = false): string {
  if (hidden) return HIDDEN_TEXT;
  if (ADD_KEYS.has(key)) return Array.isArray(current) ? `지금 ${current.length}개` : "지금 없음";
  return settingValueText(key, current);
}

/** 설정 제안 묶음인가 (수락 = 설정 반영) */
export function isSettingGroup(group: ReportGroup): boolean {
  return group.items.some((i) => i.kind === "setting_change");
}

/** 작업 목록과 보고 요약을 한 줄씩 (같은 작업은 합친다, 최근 먼저) */
export function mergeRows(jobs: readonly Record<string, unknown>[], reports: readonly Record<string, unknown>[]): Row[] {
  const rows = new Map<string, Row>();
  for (const j of jobs) {
    const id = String(j.job ?? j.id ?? "");
    if (id === "") continue;
    rows.set(id, {
      job: id,
      playbook: String(j.playbook ?? "-"),
      state: String(j.state ?? "-"),
      startedAt: String(j.started_at ?? ""),
      groups: null,
      undecided: 0,
      hasReport: false,
      used: (j.used as Row["used"]) ?? null,
    });
  }
  for (const r of reports) {
    const id = String(r.job ?? "");
    if (id === "") continue;
    const cur = rows.get(id);
    rows.set(id, {
      job: id,
      playbook: String(r.playbook ?? cur?.playbook ?? "-"),
      // 살아 있는 작업 상태(진행 중·끝내는 중)가 보고보다 먼저다
      state: cur !== undefined && (cur.state === "running" || cur.state === "ending") ? cur.state : String(r.state ?? cur?.state ?? "-"),
      startedAt: String(r.started_at ?? cur?.startedAt ?? ""),
      groups: typeof r.groups === "number" ? r.groups : null,
      undecided: typeof r.undecided === "number" ? r.undecided : 0,
      hasReport: true,
      used: cur?.used ?? null,
    });
  }
  // 통과한 연결 시험(probe)은 보고함을 어지럽히기만 해서 뺀다 (실패한 시험은 남긴다)
  return [...rows.values()]
    .filter((r) => !(r.playbook === "probe" && r.state === "done"))
    .sort((a, b) => (a.startedAt === b.startedAt ? b.job.localeCompare(a.job) : b.startedAt.localeCompare(a.startedAt)));
}

/** 상태 바 "보고함 N": 사람이 볼 것 = 결정하지 않은 묶음이 있는 보고 + 도는 작업 */
export function inboxCount(rows: readonly Row[]): number {
  return rows.filter((r) => r.undecided > 0 || r.state === "running" || r.state === "ending").length;
}

/** 취소 단추: 진행 중일 때만 (끝내는 중이면 이미 취소 경로를 지나는 중 — 다시 보내지 않는다) */
export function canCancel(row: Pick<Row, "state">): boolean {
  return row.state === "running";
}

/** 묶음 수락·거절 단추를 보일까: 아직 결정하지 않았고 작업 기준에만 있는 변경이나 설정 제안이 있다 */
export function decidable(group: ReportGroup): boolean {
  return group.decision === null && group.items.some((i) => i.kind === "working_only" || i.kind === "setting_change");
}

/** "이어서 진행"을 둘 보고: Init 또는 이어 하기 (UX2 D) */
export function followupPlaybook(report: Pick<Report, "playbook">): boolean {
  return report.playbook === "init" || report.playbook === "followup";
}

/** "이어서 진행"을 막는 이유 (무인 작업이 도는 중). 없으면 null */
export function followupBlock(rows: readonly Pick<Row, "state">[]): string | null {
  return rows.some((r) => r.state === "running" || r.state === "ending") ? "무인 작업이 도는 중이에요. 끝난 뒤 이어서 진행할 수 있어요" : null;
}

export interface AnswerOutcome {
  answered: string[];
  /** 질문 ID → 실패 이유 (사람이 읽는 글) */
  failed: Record<string, string>;
}

/**
 * 질문 일괄 답 (UX2 B): 글을 넣은 질문만 차례로 보낸다(빈 칸은 건너뜀). 하나가 실패해도 나머지는 보낸다.
 * `send`는 사람 전용 `unknowns.answer` 한 번
 */
export async function sendAnswers(
  questions: readonly Unknown[],
  drafts: Readonly<Record<string, string>>,
  send: (u: Unknown, text: string) => Promise<unknown>,
): Promise<AnswerOutcome> {
  const out: AnswerOutcome = { answered: [], failed: {} };
  for (const u of questions) {
    const text = (drafts[u.id] ?? "").trim();
    if (text === "") continue;
    try {
      await send(u, text);
      out.answered.push(u.id);
    } catch (err) {
      const e = toRpcError(err);
      out.failed[u.id] = ANSWER_ERROR_TEXT[e.kind ?? ""] ?? e.message;
    }
  }
  return out;
}

const ANSWER_ERROR_TEXT: Record<string, string> = {
  revision_conflict: "그 사이 질문이 바뀌었어요. 새로 읽은 뒤 다시 보내 주세요",
  secret_in_text: "답에 비밀값이 들어 있어 보내지 않았어요",
  secret_unchecked: "비밀값을 확인하지 못해 보내지 않았어요",
  not_found: "없는 질문이에요",
};

/** 보낼 글이 있는 질문 수 */
export function filledCount(questions: readonly Unknown[], drafts: Readonly<Record<string, string>>): number {
  return questions.filter((u) => (drafts[u.id] ?? "").trim() !== "").length;
}

/** 되돌리기 단추 (자동 채택 하나에 한 번) */
export function revertable(item: ReportItem, reverted: ReadonlySet<string>): boolean {
  return item.kind === "auto_adopted" && typeof item.adoption === "string" && !reverted.has(item.adoption);
}

/** 보고에서 질문으로 올릴 미지수: "사람만 답할 수 있음"이고 아직 열린 것 */
export function openQuestions(report: Report, unknowns: readonly Unknown[]): Unknown[] {
  const ids = new Set([...(report.unknowns ?? []), ...report.groups.flatMap((g) => g.items.flatMap((i) => i.unknowns ?? []))]);
  return unknowns.filter((u) => ids.has(u.id) && u.human_only === true && u.state === "open");
}

// ── 저장소 ─────────────────────────────────────────────────────

interface ReportsState {
  rows: Row[];
  loaded: boolean;
  selected: string | null;
  detail: Report | null;
  unknowns: Unknown[];
  reverted: Set<string>;
  /** 진행 중인 동작 키 (`cancel:<job>`·`decide:<job>:<group>`·`revert:<a>`·`answer:<u>`) */
  pending: Set<string>;
  /** 동작 결과·오류 글 (키별) */
  messages: Record<string, string>;
  /** 마지막으로 끝난 agent-job CLI 결과 (주 프로세스 jobs.cli 알림, 정해진 필드만) */
  lastCli: JobCliResult | null;
  error: string | null;
  /** 사람이 줄을 고르기 전에는 가장 최근 작업을 따라간다 (Init 시작 뒤 자동으로 그 작업) */
  follow: boolean;
  /** 질문 답 칸 (질문 ID → 글). "답 보내기"가 한 번에 보낸다 (UX2 B) */
  drafts: Record<string, string>;
  /** 일괄 답에서 실패한 질문 → 이유 */
  answerErrors: Record<string, string>;
  /** 일괄 답을 보내는 중 */
  sending: boolean;
}

export const useReports = create<ReportsState>(() => ({
  rows: [],
  loaded: false,
  selected: null,
  detail: null,
  unknowns: [],
  reverted: new Set(),
  pending: new Set(),
  messages: {},
  lastCli: null,
  error: null,
  follow: true,
  drafts: {},
  answerErrors: {},
  sending: false,
}));

export const REPORTS_TAB_PATH = "reports:inbox";

export function openReportsTab(): void {
  useReports.setState({ follow: true });
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === REPORTS_TAB_PATH)) return { active: REPORTS_TAB_PATH };
    return { tabs: [...s.tabs, { path: REPORTS_TAB_PATH, kind: "reports", graphKind: null, title: "보고함" }], active: REPORTS_TAB_PATH };
  });
  void reloadReports();
}

export async function reloadReports(): Promise<void> {
  try {
    const [jobs, reports, adoptions] = await Promise.all([
      client().call("jobs.list", {}),
      client().call("reports.list", {}),
      client()
        .call("adoptions.list", {})
        .catch(() => ({ adoptions: [] as Record<string, unknown>[] })),
    ]);
    const reverted = new Set(
      (adoptions.adoptions as Record<string, unknown>[]).filter((a) => a.reverted != null && a.reverted !== false).map((a) => String(a.id)),
    );
    const rows = mergeRows(jobs.jobs, reports.reports);
    useReports.setState({ rows, reverted, loaded: true, error: null });
    const { selected, follow } = useReports.getState();
    const target = follow && rows.length > 0 ? rows[0].job : selected;
    if (target !== selected) useReports.setState({ selected: target, detail: null });
    if (target !== null) await loadDetail(target);
  } catch (err) {
    useReports.setState({ loaded: true, error: toRpcError(err).message });
  }
}

/** 사람이 줄을 골랐다: 이제 최근 작업을 따라가지 않는다 */
export async function selectReport(job: string): Promise<void> {
  useReports.setState({ selected: job, detail: null, follow: false });
  await loadDetail(job);
}

async function loadDetail(job: string): Promise<void> {
  const row = useReports.getState().rows.find((r) => r.job === job);
  if (row === undefined || !row.hasReport) {
    if (useReports.getState().selected === job) useReports.setState({ detail: null });
    return;
  }
  try {
    const { report } = await client().call("reports.get", { job });
    let unknowns: Unknown[] = [];
    try {
      const doc = (await client().call("knowledge.get", { file: "unknowns" })).doc as { unknowns?: Unknown[] } | undefined;
      unknowns = doc?.unknowns ?? [];
    } catch {
      // 미지수 파일이 없다
    }
    if (useReports.getState().selected === job) useReports.setState({ detail: report as unknown as Report, unknowns });
  } catch (err) {
    if (useReports.getState().selected === job) useReports.setState({ detail: null, error: toRpcError(err).message });
  }
}

/** 키가 진행 중이면 아무것도 하지 않는다 (두 번 누르기). 끝나면 목록을 다시 읽는다 */
async function once(key: string, fn: () => Promise<string>): Promise<void> {
  if (useReports.getState().pending.has(key)) return;
  useReports.setState((s) => ({ pending: new Set(s.pending).add(key), messages: { ...s.messages, [key]: "" } }));
  let message: string;
  try {
    message = await fn();
  } catch (err) {
    const e = toRpcError(err);
    message = ERROR_TEXT[e.kind ?? ""] ?? e.message;
  }
  useReports.setState((s) => {
    const pending = new Set(s.pending);
    pending.delete(key);
    return { pending, messages: { ...s.messages, [key]: message } };
  });
  await reloadReports();
}

const ERROR_TEXT: Record<string, string> = {
  already_reverted: "이미 되돌렸어요",
  revision_conflict: "그 사이 파일이 바뀌어 아무것도 하지 않았어요",
  job_active: "작업 중이에요. 끝난 뒤 다시 해 주세요",
  not_found: "이미 끝난 작업이에요",
  exists: "이미 있는 항목이라 반영하지 않았어요",
  setting_not_allowed: "바꿀 수 없는 설정이에요",
  settings_invalid: "설정 파일 형식이 틀려 고치지 않았어요",
};

export function cancelJob(job: string): Promise<void> {
  return once(`cancel:${job}`, async () => {
    const r = await client().call("job.end", { job, reason: "cancelled" });
    return r.state === "ending" ? "끝내는 중이에요 (입력 복구를 기다려요)" : `${STATE_TEXT[r.state ?? ""] ?? r.state ?? "끝남"}`;
  });
}

export function decideGroup(job: string, group: string, decision: "accept" | "reject", setting = false): Promise<void> {
  return once(`decide:${job}:${group}`, async () => {
    await client().call("report.decide", { job, group, decision });
    if (setting) return decision === "accept" ? "설정에 반영했어요" : "거절했어요. 설정은 그대로예요";
    return decision === "accept" ? "팀 기준에 반영했어요" : "작업 기준에서 뺐어요";
  });
}

export function setDraft(id: string, text: string): void {
  useReports.setState((s) => {
    const answerErrors = { ...s.answerErrors };
    delete answerErrors[id];
    return { drafts: { ...s.drafts, [id]: text }, answerErrors };
  });
}

/** "답 보내기" (UX2 B): 글을 넣은 질문 전부. 성공한 칸은 비우고(목록을 다시 읽으면 답한 질문은 빠진다), 실패한 질문 옆에 이유 */
export async function answerAll(job: string, questions: readonly Unknown[]): Promise<void> {
  const { sending, drafts } = useReports.getState();
  if (sending || filledCount(questions, drafts) === 0) return;
  const key = `answers:${job}`;
  useReports.setState((s) => ({ sending: true, messages: { ...s.messages, [key]: "" } }));
  const out = await sendAnswers(questions, drafts, (u, text) => client().call("unknowns.answer", { id: u.id, base_rev: u.rev, text }));
  const failed = Object.keys(out.failed).length;
  useReports.setState((s) => {
    const next = { ...s.drafts };
    for (const id of out.answered) delete next[id];
    const parts = [out.answered.length > 0 ? `답 ${out.answered.length}개를 보냈어요` : "", failed > 0 ? `${failed}개는 보내지 못했어요` : ""];
    return {
      drafts: next,
      answerErrors: out.failed,
      sending: false,
      messages: { ...s.messages, [key]: parts.filter((p) => p !== "").join(" · ") },
    };
  });
  await reloadReports();
}

/**
 * "이어서 진행" (UX2 D): 사용자 설정의 기본 Agent로 followup 무인 작업을 만든다 — 9단계 Init과 같은 주 프로세스 경로
 * (`agentJobRun`, 플레이북 허용 목록·예산 기본값). 렌더러는 명령줄을 주지 않는다
 */
export function startFollowup(job: string): Promise<void> {
  return once(`followup:${job}`, async () => {
    const agents = await client().call("agents.get", {});
    // 기본 Agent, 없고 하나뿐이면 그것 (9단계 Init도 5단계에서 고른 하나를 쓴다)
    const agentId = agents.default_agent ?? (agents.agents.length === 1 ? agents.agents[0].id : null);
    if (agentId === null) return "기본 Agent가 없어요. 설정 도우미 5단계에서 Agent를 연결해 주세요";
    const bridge = (globalThis as unknown as { kookabug: KookabugBridge }).kookabug;
    let started: { started: boolean; error_code?: string };
    try {
      started = await bridge.app.agentJobRun("followup", agentId);
    } catch (err) {
      const code = (err as { code?: unknown }).code;
      return code === "agent_job_unsupported" ? "무인 작업은 Claude Code·Codex CLI만 지원해요" : "이어서 진행하지 못했어요";
    }
    if (!started.started) return started.error_code === "job_active" ? ERROR_TEXT.job_active : "이어서 진행하지 못했어요";
    useReports.setState({ follow: true });
    return "이어서 진행을 시작했어요. 새 작업이 목록 맨 위에 생겨요";
  });
}

export function revertAdoption(adoption: string): Promise<void> {
  return once(`revert:${adoption}`, async () => {
    await client().call("adopt.revert", { adoption });
    useReports.setState((s) => ({ reverted: new Set(s.reverted).add(adoption) }));
    return "되돌렸어요. 게임 계정·서버 상태는 되돌리지 않아요";
  });
}

let started = false;

/** 앱 시작 때 한 번: 작업·보고 알림과 주 프로세스의 agent-job 끝 알림 */
export function initReports(): void {
  if (started) return;
  started = true;
  client().on("job.changed", () => void reloadReports());
  client().on("reports.changed", () => void reloadReports());
  client().on("job.budget", () => void reloadReports());
  client().on("knowledge.changed", (p) => {
    if (p.files.some((f) => f.includes("unknowns") || f.includes("reports") || f.includes("adoptions"))) void reloadReports();
  });
  // globalThis: 순수 함수 검사(tsconfig.node, DOM 없음)도 이 파일을 타입 검사한다
  (globalThis as unknown as { kookabug: KookabugBridge }).kookabug.on("jobs.cli", (data: unknown) => {
    useReports.setState({ lastCli: data as JobCliResult });
    void reloadReports();
  });
}
