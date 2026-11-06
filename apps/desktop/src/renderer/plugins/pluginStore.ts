// 플러그인 목록과 작업 흐름 (M6 계획 B5, daemon 3.8). 렌더러는 ui 연결(client)로만 daemon을 부른다.
// 흐름: 추가 = 원천 → plugins.preview → 신뢰 카드 → plugins.install {op_id} → 진행(plugins.progress) → 결과(plugins.done).
// 준비 = 신뢰하지 않은 잠금이면 신뢰 카드 → plugins.sync {lock_sha256}. 다시 잠그기·제거·정리는 확인 카드 뒤.
// 신뢰·확인 카드를 거치지 않고 설치·준비를 시작하는 길은 없다 (준비는 이 PC가 이미 신뢰한 잠금일 때만 카드 없이)
import { create } from "zustand";
import { client, toRpcError } from "../rpc/client";
import {
  errorView,
  previewParams,
  type DoneParams,
  type OpKind,
  type PluginEntry,
  type PluginErrorInfo,
  type PluginsList,
  type PreviewResult,
  type SourceDraft,
  EMPTY_DRAFT,
} from "./model";

/** 작업 하나의 알림 (op_id별). 응답보다 알림이 먼저 올 수 있어 흐름과 따로 모은다 */
export interface OpState {
  stages: string[];
  message: string | null;
  done: DoneParams | null;
}

export type Flow =
  | { kind: "install"; step: "source"; draft: SourceDraft; error: string | null }
  | { kind: "install"; step: "previewing"; draft: SourceDraft }
  | { kind: "install"; step: "trust"; draft: SourceDraft; preview: PreviewResult; busy: boolean }
  | { kind: "sync"; step: "trust"; list: PluginsList; busy: boolean; changed?: boolean }
  | { kind: "relock"; step: "confirm"; list: PluginsList; busy: boolean; changed?: boolean }
  | { kind: "remove"; step: "confirm"; plugin: PluginEntry; revision: string | null; busy: boolean; changed?: boolean }
  | { kind: "gc"; step: "confirm"; candidates: PluginsList["gc_candidates"]; busy: boolean; changed?: boolean }
  | { kind: OpKind; step: "progress"; opId: string; title: string }
  | { kind: OpKind; step: "result"; ok: boolean; error: PluginErrorInfo | null; title: string; opId: string | null };

interface PluginsState {
  list: PluginsList | null;
  /** 목록을 읽지 못했다 (잠금이 깨짐 등) */
  loadError: { code: string | null; message: string } | null;
  ops: Record<string, OpState>;
  flow: Flow | null;
  /** 이 창이 시작해 끝을 기다리는 작업 (대화 상자를 닫아도 남는다) */
  running: { opId: string; kind: OpKind; title: string } | null;
}

export const usePlugins = create<PluginsState>(() => ({
  list: null,
  loadError: null,
  ops: {},
  flow: null,
  running: null,
}));

let generation = 0;
let onChangedHook: () => void = () => {};

function pluginError(err: unknown): PluginErrorInfo {
  const e = toRpcError(err);
  const data = e.data as { plugin_error?: PluginErrorInfo } | undefined;
  if (data?.plugin_error !== undefined) return data.plugin_error;
  return { code: e.kind ?? "internal_error", stage: null, message: e.message };
}

export async function reloadPlugins(): Promise<void> {
  const mine = ++generation;
  try {
    const list = await client().call("plugins.list", {});
    if (mine !== generation) return;
    usePlugins.setState({ list, loadError: null });
    settleOrphan(list);
    refreshCard(list);
  } catch (err) {
    if (mine !== generation) return;
    const e = pluginError(err);
    usePlugins.setState({ list: null, loadError: { code: e.code, message: e.message } });
  }
}

/** 프로젝트가 바뀌었다 */
export function resetPlugins(): void {
  generation++;
  usePlugins.setState({ list: null, loadError: null, ops: {}, flow: null, running: null });
}

function opState(id: string): OpState {
  return usePlugins.getState().ops[id] ?? { stages: [], message: null, done: null };
}

function putOp(id: string, next: OpState): void {
  usePlugins.setState((s) => ({ ops: { ...s.ops, [id]: next } }));
}

export function onProgress(p: { op_id: string; stage: string; message: string }): void {
  const cur = opState(p.op_id);
  putOp(p.op_id, { ...cur, stages: [...cur.stages, p.stage], message: p.message });
}

export function onDone(p: DoneParams): void {
  putOp(p.op_id, { ...opState(p.op_id), done: p });
  const { running, flow } = usePlugins.getState();
  if (running?.opId !== p.op_id) {
    // 다른 창·이 창이 승인 전에 취소한 미리보기의 끝: 결과 대화 상자는 띄우지 않고 목록(busy)만 다시 읽는다.
    // 잠금이 바뀌지 않은 끝(취소·실패)은 plugins.changed가 오지 않는다 (B5 검수 Mid)
    void reloadPlugins();
    return;
  }
  usePlugins.setState({ running: null });
  // 대화 상자를 닫아 두었어도 결과는 다시 띄운다 (성공·실패를 놓치지 않게)
  if (flow === null || (flow.step === "progress" && flow.opId === p.op_id)) {
    showResult(p.kind, running.title, p.ok, p.error ?? null, p.op_id);
  }
  void reloadPlugins();
}

function showResult(kind: OpKind, title: string, ok: boolean, error: PluginErrorInfo | null, opId: string | null): void {
  usePlugins.setState({ flow: { kind, step: "result", ok, error, title, opId } });
}

/** 작업을 시작했다 (op_id를 받았다): 진행 화면. 끝 알림이 먼저 왔으면 곧바로 결과 */
function started(kind: OpKind, opId: string, title: string): void {
  usePlugins.setState({ running: { opId, kind, title }, flow: { kind, step: "progress", opId, title } });
  const done = opState(opId).done;
  if (done !== null) onDone(done);
}

/**
 * 연결이 바뀐 사이 끝난 작업 (끝 알림을 받지 못함): 목록에 그 작업이 없으면 결과를 "확인 필요"로 닫는다.
 * 승인 대기 미리보기는 연결이 끊기면 daemon이 취소한다 (B4) — 다시 미리보기
 */
function settleOrphan(list: PluginsList): void {
  const { running, flow } = usePlugins.getState();
  if (running !== null && list.busy === null && opState(running.opId).done === null) {
    usePlugins.setState({ running: null });
    showResult(running.kind, running.title, false, {
      code: "connection_lost",
      stage: null,
      message: "연결이 바뀌는 사이 작업이 끝났어요. 목록에서 결과를 확인해 주세요.",
    }, running.opId);
    return;
  }
  if (flow?.step === "trust" && flow.kind === "install" && list.busy?.op_id !== flow.preview.op_id) {
    usePlugins.setState({
      flow: { kind: "install", step: "source", draft: flow.draft, error: "연결이 바뀌어 미리보기가 취소됐어요. 다시 미리보기 해 주세요." },
    });
  }
}

/**
 * 열린 확인 카드가 본 잠금이 바뀌었다(plugins.changed·다시 읽기): 카드 내용을 새 목록으로 바꾸고 "잠금이 바뀌었어요 —
 * 다시 확인해 주세요"를 띄운다. 확인 단추는 그 새 카드의 해시·revision·후보만 보낸다 (daemon이 거래 안에서 다시
 * 비교한다 — 화면 갱신은 사람에게 알리는 일). 제거할 플러그인이 잠금에서 없어졌으면 카드를 닫는다
 */
function refreshCard(list: PluginsList): void {
  const flow = usePlugins.getState().flow;
  if (flow === null || (flow.step !== "trust" && flow.step !== "confirm") || flow.busy) return;
  if ((flow.kind === "sync" || flow.kind === "relock") && flow.list.lock_sha256 !== list.lock_sha256) {
    if (list.lock_sha256 === null) {
      usePlugins.setState({ flow: null });
      return;
    }
    usePlugins.setState({ flow: { ...flow, list, changed: true } });
  } else if (flow.kind === "remove" && flow.revision !== list.revision) {
    const plugin = list.plugins.find((p) => p.id === flow.plugin.id);
    usePlugins.setState({ flow: plugin === undefined ? null : { ...flow, plugin, revision: list.revision, changed: true } });
  } else if (flow.kind === "gc" && !sameCandidates(flow.candidates, list.gc_candidates)) {
    usePlugins.setState({ flow: { ...flow, candidates: list.gc_candidates, changed: true } });
  }
}

function sameCandidates(a: PluginsList["gc_candidates"], b: PluginsList["gc_candidates"]): boolean {
  const key = (c: PluginsList["gc_candidates"]) => JSON.stringify([c.envs, c.wheels, c.staging]);
  return key(a) === key(b);
}

/** daemon 알림 구독 (앱 시작 때 한 번). onChanged: 잠금이 바뀜 → 노드 목록·워크스페이스 정보·열린 그래프 검증 */
export function initPlugins(onChanged: () => void): void {
  onChangedHook = onChanged;
  client().on("plugins.progress", (p) => onProgress(p));
  client().on("plugins.done", (p) => onDone(p));
  client().on("plugins.changed", () => {
    void reloadPlugins();
    onChangedHook();
  });
}

// ── 흐름 ──────────────────────────────────────────────────────────

export function openAddDialog(): void {
  usePlugins.setState({ flow: { kind: "install", step: "source", draft: EMPTY_DRAFT, error: null } });
}

export async function submitSource(draft: SourceDraft): Promise<void> {
  const parsed = previewParams(draft);
  if ("error" in parsed) {
    usePlugins.setState({ flow: { kind: "install", step: "source", draft, error: parsed.error } });
    return;
  }
  usePlugins.setState({ flow: { kind: "install", step: "previewing", draft } });
  try {
    const preview = await client().call("plugins.preview", parsed.params);
    const flow = usePlugins.getState().flow;
    if (flow?.step !== "previewing") {
      // 기다리는 사이 대화 상자를 닫았다: 미리보기를 취소한다 (승인 없이 남기지 않는다)
      void client().call("plugins.cancel", { op_id: preview.op_id }).catch(() => {});
      return;
    }
    usePlugins.setState({ flow: { kind: "install", step: "trust", draft, preview, busy: false } });
  } catch (err) {
    if (usePlugins.getState().flow?.step !== "previewing") return;
    const view = errorView(pluginError(err));
    usePlugins.setState({ flow: { kind: "install", step: "source", draft, error: [view.summary, ...view.detail.slice(1)].join("\n") } });
  }
}

function titleOf(flow: Flow): string {
  switch (flow.kind) {
    case "install":
      return flow.step === "trust" ? (flow.preview.title ?? flow.preview.id) : "플러그인";
    case "remove":
      return flow.step === "confirm" ? (typeof flow.plugin.manifest.title === "string" ? flow.plugin.manifest.title : flow.plugin.id) : "플러그인";
    default:
      return "플러그인";
  }
}

/** 신뢰·확인 카드의 확인 단추. 카드가 보인 그 미리보기·잠금·revision으로만 진행한다 */
export async function confirmFlow(): Promise<void> {
  const flow = usePlugins.getState().flow;
  if (flow === null || (flow.step !== "trust" && flow.step !== "confirm") || flow.busy) return;
  usePlugins.setState({ flow: { ...flow, busy: true } as Flow });
  const title = titleOf(flow);
  try {
    let opId: string;
    if (flow.kind === "install" && flow.step === "trust") {
      opId = (await client().call("plugins.install", { op_id: flow.preview.op_id })).op_id;
    } else if (flow.kind === "sync") {
      const sha = flow.list.lock_sha256;
      if (sha === null) throw new Error("잠금이 없어요");
      opId = (await client().call("plugins.sync", { lock_sha256: sha })).op_id;
    } else if (flow.kind === "relock") {
      // 카드가 본 잠금일 때만 (daemon이 거래 안에서 비교 — 다르면 revision_conflict, B5 검수 H)
      const sha = flow.list.lock_sha256;
      if (sha === null) throw new Error("잠금이 없어요");
      opId = (await client().call("plugins.relock", { lock_sha256: sha })).op_id;
    } else if (flow.kind === "remove") {
      opId = (await client().call("plugins.remove", { id: flow.plugin.id, base_revision: flow.revision })).op_id;
    } else if (flow.kind === "gc") {
      // 카드에서 본 후보 안의 것만 지운다
      opId = (await client().call("plugins.gc", { candidates: flow.candidates })).op_id;
    } else {
      return;
    }
    started(flow.kind, opId, title);
  } catch (err) {
    showResult(flow.kind, title, false, pluginError(err), null);
    void reloadPlugins();
  }
}

/** 대화 상자 닫기. 승인 전 미리보기는 취소한다(아무 코드도 돌지 않음). 진행 중이면 숨기기만 (작업은 계속) */
export function closeFlow(): void {
  const flow = usePlugins.getState().flow;
  usePlugins.setState({ flow: null });
  if (flow?.kind === "install" && flow.step === "trust") {
    // 끝 알림(cancelled)이 목록을 다시 읽는다. 알림을 놓쳐도 busy가 남지 않게 취소 응답 뒤에도 읽는다
    void client()
      .call("plugins.cancel", { op_id: flow.preview.op_id })
      .catch(() => {})
      .then(() => reloadPlugins());
  }
}

/** 진행 중인 작업 취소 (설치 작업 Job을 끝낸다 — 커밋 뒤면 효과 없음). 결과는 plugins.done으로 */
export async function cancelRunning(): Promise<void> {
  const running = usePlugins.getState().running;
  if (running === null) return;
  try {
    await client().call("plugins.cancel", { op_id: running.opId });
  } catch {
    // 이미 끝났다: 끝 알림이 결과를 보인다
  }
}

/** 진행 화면으로 돌아가기 (대화 상자를 닫아 둔 작업) */
export function showRunning(): void {
  const running = usePlugins.getState().running;
  if (running === null) return;
  usePlugins.setState({ flow: { kind: running.kind, step: "progress", opId: running.opId, title: running.title } });
}

/** 준비… (U2): 이 PC가 신뢰한 잠금이면 곧바로 sync, 아니면 신뢰 카드 */
export async function startPrepare(): Promise<void> {
  await reloadPlugins();
  const list = usePlugins.getState().list;
  if (list === null || list.lock_sha256 === null) return;
  usePlugins.setState({ flow: { kind: "sync", step: "trust", list, busy: false } });
  if (list.trusted) await confirmFlow();
}

export async function startRelock(): Promise<void> {
  await reloadPlugins();
  const list = usePlugins.getState().list;
  if (list === null) return;
  usePlugins.setState({ flow: { kind: "relock", step: "confirm", list, busy: false } });
}

export function startRemove(plugin: PluginEntry): void {
  const list = usePlugins.getState().list;
  usePlugins.setState({ flow: { kind: "remove", step: "confirm", plugin, revision: list?.revision ?? null, busy: false } });
}

export async function startGc(): Promise<void> {
  await reloadPlugins();
  const list = usePlugins.getState().list;
  if (list === null) return;
  usePlugins.setState({ flow: { kind: "gc", step: "confirm", candidates: list.gc_candidates, busy: false } });
}

/** 결과 화면에서 다시 원천 입력으로 (설치 실패 → 고쳐서 다시) */
export function retryAdd(): void {
  openAddDialog();
}
