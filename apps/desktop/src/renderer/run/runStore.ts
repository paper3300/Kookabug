// 실행 화면 상태 (M2 계획 2.8, T11): 실행 시작·취소, 구독(적용한 마지막 seq 커서), 다시 붙은 뒤·앱을 다시 연
// 뒤 진행 중 실행 다시 구독, 입력 임대권 소유자.
// - 워크스페이스에서 실행은 한 번에 하나다(daemon run_busy). 화면은 지금 실행 하나(current)를 따라간다
// - 문서가 저장되지 않았으면 먼저 저장한 뒤 실행한다 (U2 기본값: 실행은 디스크 파일의 스냅샷으로 돈다).
//   저장이 안 되면(충돌·실패) 실행하지 않는다
// - 검증 오류면 daemon이 validation_failed로 거부한다: 문제 패널을 열고 실행 단추 옆에 "검증 오류 N개"
// - 이벤트 적용 순서·빈틈·lagged는 RunCursors(rpc/runCursor.ts)가 정하고, 여기는 받은 순서대로 기록에 더한다
import type { NotificationParamsOf, ResultOf } from "@kookabug/schema";
import { create } from "zustand";
import { client, toRpcError, type RpcCall } from "../rpc/client";
import { RunCursors } from "../rpc/runCursor";
import { getDoc, saveDoc } from "../store/documents";
import { useUi, type PanelTab } from "../store/ui";
import type { Diagnostic } from "../graph/model";
import type { events } from "@kookabug/schema";
import { applyPause, NO_PAUSE, pauseNeedsCalls, type PauseState } from "../debug/pauseState";
import { applyEvent, emptyTrace, unresolvedCall, type CallMap, type RunEvent, type RunTrace } from "./highlight";

export type RunOutcome = NotificationParamsOf<"run.ended">["outcome"];
export type ResumeMode = events.ResumeMode;
type RunSummary = ResultOf<"run.list">["runs"][number];

/** 입력 임대권 옆 파일의 소유자 (lease.changed) */
export interface LeaseOwner {
  kind?: unknown;
  run_id?: unknown;
  [key: string]: unknown;
}

export interface RunView {
  runId: string;
  /** 실행한 테스트 그래프 (워크스페이스 기준) */
  graph: string;
  runDir: string | null;
  phase: "running" | "ended";
  trace: RunTrace;
  outcome: RunOutcome | null;
  /** 시작할 때 그 문서의 base revision. 붙기만 한 실행(다시 연 앱·CLI)은 null */
  revision: string | null;
  /** 실행 스냅샷의 호출 관계 (run.status calls). 스냅샷 전이거나 아직 받지 않았으면 빈 객체. 받은 것은 합친다 */
  calls: CallMap;
  /** 성공한 조회가 덮는 마지막 seq (그 뒤에 시작한 스텝이 모르는 호출을 지나면 다시 묻는다) */
  callsAsOf: number;
  /** 디버거 멈춤 (이벤트로만 안다, M3 2.1) */
  pause: PauseState;
  /** 일시정지를 요청했고 아직 경계·폴링 확인 지점에 닿지 않음 (run.pause 응답 pausing) */
  pausing: boolean;
}

/** 노드 ID가 `__proto__`여도 자기 속성으로 둔다 (2.6 키 규칙) */
function put(obj: object, key: string, value: unknown): void {
  Object.defineProperty(obj, key, { value, enumerable: true, writable: true, configurable: true });
}

/**
 * 호출 관계 합치기: 실행 스냅샷에 고정된 관계라 앞서 받은 것을 지우지 않는다. 늦게 온 앞 조회(스냅샷 전의
 * 빈 결과 등)가 나중 결과를 덮지 않는다 (T11 검수 2차)
 */
export function mergeCalls(base: CallMap, raw: Readonly<Record<string, Readonly<Record<string, unknown>> | undefined>>): CallMap {
  const out: Record<string, Record<string, string>> = {};
  for (const [graph, nodes] of Object.entries(base)) {
    const copy: Record<string, string> = {};
    for (const [node, callee] of Object.entries(nodes)) put(copy, node, callee);
    put(out, graph, copy);
  }
  for (const [graph, nodes] of Object.entries(raw)) {
    if (nodes === undefined) continue;
    const into = Object.hasOwn(out, graph) ? out[graph] : {};
    for (const [node, callee] of Object.entries(nodes)) if (typeof callee === "string" && !Object.hasOwn(into, node)) put(into, node, callee);
    put(out, graph, into);
  }
  return out;
}

export interface RunBlocked {
  path: string;
  kind: "validation" | "busy" | "save" | "error";
  /** 검증 오류 수 (validation) */
  errors: number;
  message: string;
  /**
   * 실행 전 검증 진단 (validation_failed). 고른 프로필의 설정으로 검사한 것이라 편집 버퍼 진단(문서 검증)과
   * 다를 수 있다. 문제 패널이 따로 보이고, 다음 실행 시도·프로필 바꾸기·프로젝트 바꾸기까지 남는다
   */
  diagnostics: Diagnostic[];
  /** 그때 고른 프로필 (null = 기본) */
  profile: string | null;
}

export interface RunState {
  current: RunView | null;
  /** 시작 중인 그래프 경로 (저장·run.start 응답 대기) */
  starting: string | null;
  blocked: RunBlocked | null;
  lease: LeaseOwner | null;
  /** 실행 프로필 (kookabug.json profiles). null = 기본 */
  profile: string | null;
}

const INITIAL: RunState = { current: null, starting: null, blocked: null, lease: null, profile: null };

export interface RunHooks {
  /** 출력 패널 줄 */
  note(level: "info" | "warn" | "error", message: string): void;
  showPanel(tab: PanelTab): void;
  save(path: string): Promise<string>;
  revision(path: string): { dirty: boolean; revision: string | null } | null;
}

const defaultHooks: RunHooks = {
  note: () => {},
  showPanel: (tab) => useUi.setState({ panelTab: tab }),
  save: (path) => saveDoc(path),
  revision: (path) => {
    const doc = getDoc(path);
    return doc === undefined ? null : { dirty: doc.dirty, revision: doc.baseRevision };
  },
};

function diagnosticsOf(data: unknown): Diagnostic[] {
  const diags = (data as { diagnostics?: unknown } | undefined)?.diagnostics;
  return Array.isArray(diags) ? diags.filter((d): d is Diagnostic => typeof d === "object" && d !== null) : [];
}

export class RunModel {
  readonly store = create<RunState>(() => ({ ...INITIAL }));
  readonly cursors: RunCursors;
  private hooks: RunHooks;
  /** 프로젝트를 바꿀 때마다 올린다 (앞 프로젝트 응답을 쓰지 않는다) */
  private generation = 0;

  constructor(
    private readonly call: RpcCall,
    hooks: Partial<RunHooks> = {},
  ) {
    this.hooks = { ...defaultHooks, ...hooks };
    this.cursors = new RunCursors(call, (runId, _seq, event) => this.apply(runId, event));
  }

  setHooks(hooks: Partial<RunHooks>): void {
    this.hooks = { ...this.hooks, ...hooks };
  }

  private get state(): RunState {
    return this.store.getState();
  }

  /** 커서가 순서대로 넘긴 이벤트 하나 */
  private apply(runId: string, event: unknown): void {
    const current = this.state.current;
    if (current === null || current.runId !== runId) return;
    const e = event as RunEvent;
    const trace = applyEvent(current.trace, e);
    if (trace === current.trace) return;
    const pause = applyPause(current.pause, e);
    // 멈춤 확정·재개·실행 끝이면 "멈추는 중"이 끝났다
    const pausing = e.event === "debug.pause" || e.event === "debug.resume" || e.event === "run.end" ? false : current.pausing;
    this.store.setState({ current: { ...current, trace, pause, pausing } });
    // 서브그래프 안 스텝인데 호출 관계를 모르면 스냅샷 호출 관계를 받는다 (스냅샷은 첫 스텝 전에 만들어진다).
    // 서브그래프 안에서 멈췄으면 멈춘 자리까지 따라갈 호출 관계도 받는다
    if ((e.event === "step.start" || e.event === "debug.pause") && Array.isArray(e.path) && e.path.length > 1) this.syncCalls();
  }

  // ── 실행 스냅샷 호출 관계 (run.status calls) ───────────────────────
  // T11 검수 2차: 조회 실패를 끝난 것으로 보지 않고(다음 서브그래프 스텝·다시 붙을 때 다시), 늦게 온 앞
  // 조회의 빈·덜 찬 결과가 이미 받은 관계를 지우지 않는다(실행에 고정된 관계라 합친다). 한 실행에 조회는
  // 한 번에 하나이고, 조회 중에 필요가 생기면 끝난 뒤 다시 본다

  /** 조회 중인 실행 */
  private readonly callsInflight = new Set<string>();
  /** 조회 중에 다시 볼 일이 생긴 실행 */
  private readonly callsAgain = new Set<string>();

  /** 호출 관계를 모르는 서브그래프 스텝 중, 지금 관계를 받은 조회보다 뒤에 시작한 것이 있는가 */
  private callsNeeded(current: RunView): boolean {
    const steps = [...current.trace.open.values(), ...current.trace.latest.values()];
    const paused = current.pause.paused;
    return (
      steps.some(
        (rec) =>
          rec.path.length > 1 &&
          rec.startSeq > current.callsAsOf &&
          unresolvedCall(current.trace.graph, rec.path, current.calls) !== null,
      ) ||
      (paused !== null && paused.seq > current.callsAsOf && pauseNeedsCalls(current.trace.graph, paused, current.calls))
    );
  }

  /** 필요하면 호출 관계를 받는다 (서브그래프 스텝·다시 붙기·조회가 끝난 뒤) */
  private syncCalls(): void {
    const current = this.state.current;
    if (current === null) return;
    if (this.callsInflight.has(current.runId)) {
      this.callsAgain.add(current.runId);
      return;
    }
    if (this.callsNeeded(current)) void this.loadCalls(current.runId);
  }

  private async loadCalls(runId: string): Promise<void> {
    if (this.callsInflight.has(runId)) {
      this.callsAgain.add(runId);
      return;
    }
    const gen = this.generation;
    // 이 조회는 지금까지 적용한 이벤트의 스텝을 덮는다 (스냅샷은 첫 스텝 전에 만들어진다)
    const asOf = this.state.current?.runId === runId ? this.state.current.trace.lastSeq : 0;
    this.callsInflight.add(runId);
    this.callsAgain.delete(runId);
    let raw: ResultOf<"run.status">["calls"];
    try {
      raw = (await this.call("run.status", { run_id: runId })).calls;
    } catch (err) {
      // 실패는 끝난 것이 아니다: callsAsOf를 올리지 않아 다음 서브그래프 스텝·다시 붙을 때 다시 묻는다
      // (끊긴 동안 곧바로 다시 묻지 않는다)
      this.callsAgain.delete(runId);
      if (gen === this.generation) this.hooks.note("warn", `실행 ${runId}의 호출 관계를 읽지 못했다: ${toRpcError(err).message}`);
      return;
    } finally {
      if (gen === this.generation) this.callsInflight.delete(runId);
    }
    const current = this.state.current;
    if (gen !== this.generation || current === null || current.runId !== runId) return;
    this.store.setState({
      current: { ...current, calls: mergeCalls(current.calls, raw), callsAsOf: Math.max(current.callsAsOf, asOf) },
    });
    // 조회하는 동안 들어온 스텝이 아직 모르는 호출을 지나면 한 번 더 (그 스텝은 이 조회보다 뒤라 끝이 있다)
    this.callsAgain.delete(runId);
    this.syncCalls();
  }

  // ── 알림 ──────────────────────────────────────────────────────

  event(p: NotificationParamsOf<"run.event">): void {
    this.cursors.event(p.run_id, p.seq, p.event);
  }

  lagged(p: NotificationParamsOf<"run.lagged">): void {
    this.cursors.lagged(p.run_id);
  }

  ended(p: NotificationParamsOf<"run.ended">): void {
    this.cursors.ended(p.run_id);
    const current = this.state.current;
    if (current === null || current.runId !== p.run_id) return;
    const pause = current.pause.paused === null ? current.pause : { ...current.pause, paused: null };
    this.store.setState({ current: { ...current, phase: "ended", outcome: p.outcome, pause, pausing: false } });
  }

  lease(p: NotificationParamsOf<"lease.changed">): void {
    this.store.setState({ lease: p.owner as LeaseOwner | null });
  }

  // ── 동작 ──────────────────────────────────────────────────────

  setProfile(profile: string | null): void {
    // 실행 전 검증 진단은 그 프로필의 것이다: 프로필을 바꾸면 버린다
    const blocked = this.state.blocked;
    this.store.setState({ profile, ...(blocked !== null && blocked.profile !== profile ? { blocked: null } : {}) });
  }

  dismissBlocked(): void {
    this.store.setState({ blocked: null });
  }

  /** 지금 실행이 이 그래프를 돌고 있는가 */
  running(): boolean {
    return this.state.current?.phase === "running";
  }

  /** ▶: 저장 안 된 문서는 먼저 저장하고 실행한다 */
  async start(path: string): Promise<boolean> {
    const s = this.state;
    if (s.starting !== null || this.running()) return false;
    const gen = this.generation;
    this.store.setState({ starting: path, blocked: null });
    try {
      const before = this.hooks.revision(path);
      if (before?.dirty === true) {
        const saved = await this.hooks.save(path);
        if (gen !== this.generation) return false;
        if (saved !== "saved" && saved !== "unchanged") {
          this.block({ path, kind: "save", errors: 0, message: "저장하지 못해 실행하지 않았어요", diagnostics: [], profile: this.state.profile });
          return false;
        }
      }
      const revision = this.hooks.revision(path)?.revision ?? null;
      const profile = this.state.profile;
      let result: ResultOf<"run.start">;
      try {
        result = await this.call("run.start", { path, ...(profile === null ? {} : { profile }) });
      } catch (err) {
        if (gen !== this.generation) return false;
        this.refused(path, profile, err);
        return false;
      }
      if (gen !== this.generation) return false;
      this.follow({ runId: result.run_id, graph: result.graph, runDir: result.run_dir, revision });
      this.hooks.showPanel("runlog");
      this.hooks.note("info", `실행 ${result.run_id} 시작: ${result.graph}`);
      await this.subscribe(result.run_id);
      return true;
    } finally {
      if (gen === this.generation) this.store.setState({ starting: null });
    }
  }

  /** ■: 취소를 보낸다. 끝은 run.ended로 안다 */
  async cancel(): Promise<void> {
    const current = this.state.current;
    if (current === null || current.phase !== "running") return;
    try {
      await this.call("run.cancel", { run_id: current.runId });
    } catch (err) {
      this.hooks.note("error", `실행을 취소하지 못했다: ${toRpcError(err).message}`);
    }
  }

  // ── 디버거 (M3 2.3): 판단은 runner, 화면은 이벤트로 안다 ───────────────

  /** 일시정지 (F6): 다음 경계·폴링 확인 지점에서 멈춘다 */
  async pause(): Promise<void> {
    const current = this.state.current;
    if (current === null || current.phase !== "running" || current.pause.paused !== null || current.pausing) return;
    // 요청 때의 마지막 멈춤·재개 이벤트. 응답 전에 멈춤(또는 멈춤 뒤 재개까지)이 지나갔으면 그 응답은 낡았다
    const mark = current.pause.debugSeq;
    try {
      const { state } = await this.call("run.pause", { run_id: current.runId });
      const now = this.state.current;
      if (
        state === "pausing" &&
        now?.runId === current.runId &&
        now.phase === "running" &&
        now.pause.paused === null &&
        now.pause.debugSeq === mark
      ) {
        this.store.setState({ current: { ...now, pausing: true } });
      }
    } catch (err) {
      this.hooks.note("error", `일시정지하지 못했다: ${toRpcError(err).message}`);
    }
  }

  /** 계속·Step (F5·F10·F11·Shift+F11). 멈춘 동안만 */
  async resume(mode: ResumeMode): Promise<void> {
    const current = this.state.current;
    if (current === null || current.phase !== "running" || current.pause.paused === null) return;
    try {
      await this.call("run.resume", { run_id: current.runId, mode });
    } catch (err) {
      this.hooks.note("error", `재개하지 못했다: ${toRpcError(err).message}`);
    }
  }

  /**
   * 다시 시작 (Ctrl+Shift+F5): daemon run.restart 하나로 취소 → 같은 인자로 새 실행 (원자적, 2.3). 디스크 파일로
   * 다시 돌므로 저장은 하지 않는다. 새 실행을 따라간다
   */
  async restart(): Promise<boolean> {
    const current = this.state.current;
    if (current === null || current.phase !== "running" || this.state.starting !== null) return false;
    const gen = this.generation;
    this.store.setState({ starting: current.graph });
    try {
      let result: ResultOf<"run.restart">;
      try {
        result = await this.call("run.restart", { run_id: current.runId });
      } catch (err) {
        if (gen === this.generation) this.hooks.note("error", `다시 시작하지 못했다: ${toRpcError(err).message}`);
        return false;
      }
      if (gen !== this.generation) return false;
      this.follow({
        runId: result.run_id,
        graph: result.graph,
        runDir: result.run_dir,
        revision: this.hooks.revision(result.graph)?.revision ?? null,
      });
      this.hooks.note("info", `실행 ${result.run_id} 다시 시작: ${result.graph}`);
      await this.subscribe(result.run_id);
      return true;
    } finally {
      if (gen === this.generation) this.store.setState({ starting: null });
    }
  }

  /**
   * daemon에 붙을 때마다: 따라가는 실행이 없거나 끝났으면 진행 중 실행(run.list)을 찾아 처음부터 구독한다
   * (앱을 다시 열었을 때·CLI 실행). 따라가던 실행은 recovery가 적용한 마지막 seq부터 다시 구독한다
   */
  async syncActive(): Promise<void> {
    if (this.running()) {
      // 따라가던 실행: 앞 조회가 끊겨 실패했으면 다음 스텝을 기다리지 않고 지금 다시 받는다 (긴 대기 중에도)
      this.syncCalls();
      return;
    }
    if (this.state.starting !== null) return;
    const gen = this.generation;
    let runs: RunSummary[];
    try {
      runs = (await this.call("run.list", { limit: 20 })).runs;
    } catch (err) {
      if (gen === this.generation) this.hooks.note("warn", `실행 목록을 읽지 못했다: ${toRpcError(err).message}`);
      return;
    }
    if (gen !== this.generation || this.running() || this.state.starting !== null) return;
    const active = runs.find((r) => r.state === "running");
    if (active === undefined || active.run_id === this.state.current?.runId) return;
    this.follow({ runId: active.run_id, graph: active.graph, runDir: active.run_dir, revision: null });
    this.hooks.note("info", `진행 중인 실행 ${active.run_id}을(를) 다시 따라간다: ${active.graph}`);
    // 이미 돌고 있는 실행은 스냅샷이 있다: 호출 관계를 먼저 받는다 (조상 탭이 안 열려 있어도 강조)
    await Promise.all([this.loadCalls(active.run_id), this.subscribe(active.run_id)]);
  }

  /** 프로젝트를 바꿨다 */
  reset(): void {
    this.generation++;
    this.cursors.reset();
    this.callsInflight.clear();
    this.callsAgain.clear();
    this.store.setState({ ...INITIAL });
  }

  private follow(run: { runId: string; graph: string; runDir: string | null; revision: string | null }): void {
    this.store.setState({
      blocked: null,
      current: {
        ...run,
        phase: "running",
        trace: emptyTrace(run.runId, run.graph),
        outcome: null,
        calls: {},
        callsAsOf: 0,
        pause: NO_PAUSE,
        pausing: false,
      },
    });
  }

  private async subscribe(runId: string): Promise<void> {
    try {
      await this.cursors.subscribe(runId, 0);
    } catch (err) {
      // 끊겼으면 다음 연결에서 recovery가 적용한 seq부터 다시 구독한다
      this.hooks.note("warn", `실행 ${runId}을(를) 구독하지 못했다: ${toRpcError(err).message}`);
    }
  }

  private block(blocked: RunBlocked): void {
    this.store.setState({ blocked });
  }

  private refused(path: string, profile: string | null, err: unknown): void {
    const error = toRpcError(err);
    const base = { path, profile, diagnostics: [] as Diagnostic[] };
    switch (error.kind) {
      case "validation_failed": {
        // 진단을 보관해 문제 패널에 실행 전 검증으로 보인다 (프로필 설정 오류는 문서 검증에 나오지 않는다)
        const diagnostics = diagnosticsOf(error.data);
        const errors = diagnostics.filter((d) => d.severity === "error").length;
        this.block({ ...base, kind: "validation", errors, message: `검증 오류 ${errors}개`, diagnostics });
        this.hooks.showPanel("problems");
        return;
      }
      case "run_busy":
        this.block({ ...base, kind: "busy", errors: 0, message: "다른 실행이 진행 중이에요" });
        void this.syncActive();
        return;
      default:
        this.block({ ...base, kind: "error", errors: 0, message: `실행하지 못했어요: ${error.message}` });
        this.hooks.note("error", `실행하지 못했다 (${error.kind ?? error.code}): ${error.message}`);
    }
  }
}

/** 앱 전체가 쓰는 실행 화면 상태 (workspace.ts가 알림·다시 붙기에 잇는다) */
export const runModel = new RunModel((method, params) => client().call(method, params));
export const useRun = runModel.store;
