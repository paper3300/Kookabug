// 기록 뷰어 RUN 탭 상태 (M3 계획 2.7·2.10, T10). 렌더러는 events.jsonl을 다 받지 않는다: daemon 색인
// (run.index: 최상위·실패 사슬 스텝)과 쪽 읽기(run.children)만 들고, 고른 스텝의 자세한 기록은 run.step으로 읽는다.
// - 펼친 스텝 아래 스텝은 쪽(부모·회차마다)으로 모으고 step 순으로 합친다. 색인이 이미 아는 스텝(실패 사슬)도
//   합친다. "더 보기"는 처음부터 이어 읽은 개수(loaded)부터 읽는다 — 이동 계산이 읽은 마지막 쪽은 그 사이를 메우지
//   않는다
// - 진행 중 실행: 실행 화면이 적용한 마지막 seq(run/runStore)가 색인의 last_seq보다 크면 색인과 읽은 쪽을 다시
//   읽는다(묶어서 한 번에 하나). 응답은 last_seq가 줄지 않을 때만 쓴다 — seq 순서대로만 늘어난다
// - 자세한 기록(run.step)은 step.end가 들어 있어야 끝난 것이다. 끝나지 않은 기록은 다시 고르거나 다시 읽을 때
//   새로 읽는다 (실행 중 고른 스텝이 끝나면 증거·썸네일이 생긴다)
// - 처음 열면 실패 노드로 바로 이동한다 (failureJump.ts). 목록·"실패 보기"로 다시 열면 이미 열린 탭에서도 최신
//   실패 사슬로 다시 이동한다 (open(runId, true))
// - 노드 제목은 실행 스냅샷 그래프에서 읽는다 (편집 중인 버퍼·지금 파일과 무관)
// - 탭을 닫았다 다시 열면 새 보기(instance)다: 닫기 전 요청의 늦은 응답은 새 보기에 쓰지 않는다
import type { ResultOf, runIndex } from "@kookabug/schema";
import { create } from "zustand";
import { client, toRpcError, type RpcCall } from "../rpc/client";
import { planJump, stepNumber, type JumpPlan } from "./failureJump";

export type RunIndex = runIndex.RunIndex;
export type StepNode = runIndex.StepNode;
export type StepDetail = ResultOf<"run.step">;

/** 한 번에 읽는 쪽 크기 (daemon 상한 500) */
export const PAGE = 200;
/** 진행 중 실행을 다시 읽는 간격 */
export const LIVE_REFRESH_MS = 250;

export interface ChildPage {
  steps: StepNode[];
  total: number;
  /** offset 0부터 빈틈없이 읽은 스텝 수 ("더 보기"의 다음 offset) */
  loaded: number;
  loading: boolean;
  error: string | null;
}

export interface NodeInfo {
  title: string | null;
  type: string | null;
}

export interface RunViewState {
  runId: string;
  /** 탭을 열 때마다 새 번호 (닫았다 다시 열면 다르다) */
  instance: number;
  status: "loading" | "ready" | "error";
  error: string | null;
  index: RunIndex | null;
  /** pageKey(부모, 회차) → 읽은 쪽 */
  pages: ReadonlyMap<string, ChildPage>;
  expanded: ReadonlySet<string>;
  /** 반복 스텝 → 보고 있는 회차 */
  iteration: ReadonlyMap<string, number>;
  selected: string | null;
  /** 이 스텝이 보이게 옮기라는 요청 (nonce가 바뀔 때마다 한 번) */
  reveal: { step: string; nonce: number } | null;
  details: ReadonlyMap<string, StepDetail | "loading" | "error">;
  /** 스냅샷 그래프 → 노드 ID → 제목·종류 */
  nodes: ReadonlyMap<string, ReadonlyMap<string, NodeInfo>>;
  /** 테스트 그래프 제목 (스냅샷 meta.title) */
  testTitle: string | null;
  view: "timeline" | "stats" | "compare" | "runjson";
  /** run.json 원문 (run.json 탭을 열 때 읽는다) */
  runJson: { text: string; truncated: boolean } | "loading" | "error" | null;
  /** 실패(또는 끝나지 않은 스텝)로 이동했다 */
  jumped: boolean;
  /** 스크린샷 줄 머리 "스크린샷 | 영상" (U8) */
  media: "shots" | "video";
  /** 쪽을 다 읽지 않고 고른 스텝과 그 조상 (노드별 통계 → 마지막 실패). 부모 아래 줄에 합쳐 보인다 */
  pinned: StepNode[];
  /** 사용자가 고른 기준 실행 (null = 자동: 지난 성공) */
  baseline: string | null;
  /** 비교 결과 (key = 기준|스텝) */
  compare: { key: string; result: CompareResult | "loading" | { error: string } } | null;
  /** 머리 아래 알림 (내보내기·재현 결과) */
  notice: { tone: "info" | "warn" | "error"; text: string } | null;
}

export type CompareResult = ResultOf<"run.compare">;

export function pageKey(parent: string, iteration: number | null): string {
  return iteration === null ? parent : `${parent}#${iteration}`;
}

/** 스텝 목록 합치기: 같은 스텝은 새 것, step 순 */
export function mergeSteps(base: readonly StepNode[], incoming: readonly StepNode[]): StepNode[] {
  const byId = new Map(base.map((s) => [s.step, s]));
  for (const s of incoming) byId.set(s.step, s);
  return [...byId.values()].sort((a, b) => stepNumber(a.step) - stepNumber(b.step));
}

/** 자세한 기록이 끝난 스텝 것인가 (step.end가 있다) */
export function detailComplete(detail: StepDetail | "loading" | "error" | undefined): detail is StepDetail {
  return typeof detail === "object" && detail.events.some((e) => e.event === "step.end");
}

/** 그 부모(·회차) 아래에 보일 스텝: 고정한 스텝 < 읽은 쪽 < 색인이 아는 스텝(실패 사슬) 순으로 새 값 */
export function childrenOf(view: RunViewState, parent: StepNode): StepNode[] {
  const iteration = parent.iterations !== undefined ? (view.iteration.get(parent.step) ?? null) : null;
  const page = view.pages.get(pageKey(parent.step, iteration))?.steps ?? [];
  const under = (s: StepNode) => s.parent === parent.step && (iteration === null || s.iteration === iteration);
  const known = (view.index?.steps ?? []).filter(under);
  return mergeSteps(mergeSteps(view.pinned.filter(under), page), known);
}

export function topSteps(view: RunViewState): StepNode[] {
  return (view.index?.steps ?? []).filter((s) => s.parent === null);
}

/** 색인이 아는 스텝 (최상위·사슬·읽은 쪽 전부에서) */
export function findStep(view: RunViewState, step: string): StepNode | null {
  const hit = view.index?.steps.find((s) => s.step === step);
  if (hit !== undefined) return hit;
  for (const page of view.pages.values()) {
    const found = page.steps.find((s) => s.step === step);
    if (found !== undefined) return found;
  }
  return view.pinned.find((s) => s.step === step) ?? null;
}

/** 비교 결과 열쇠 (기준 실행·화면을 비교할 스텝) */
export function compareKey(baseline: string | null, step: string | null): string {
  return `${baseline ?? "auto"}|${step ?? ""}`;
}

const EMPTY_PAGE: ChildPage = { steps: [], total: 0, loaded: 0, loading: false, error: null };

let nextInstance = 0;

function emptyView(runId: string): RunViewState {
  return {
    runId,
    instance: ++nextInstance,
    status: "loading",
    error: null,
    index: null,
    pages: new Map(),
    expanded: new Set(),
    iteration: new Map(),
    selected: null,
    reveal: null,
    details: new Map(),
    nodes: new Map(),
    testTitle: null,
    view: "timeline",
    runJson: null,
    jumped: false,
    media: "shots",
    pinned: [],
    baseline: null,
    compare: null,
    notice: null,
  };
}

interface Live {
  /** 실행 화면이 적용한 마지막 seq */
  seq: number;
  timer: ReturnType<typeof setTimeout> | null;
  inflight: boolean;
  again: boolean;
}

let revealNonce = 0;

export class RunIndexModel {
  readonly store = create<{ runs: ReadonlyMap<string, RunViewState> }>(() => ({ runs: new Map() }));
  private generation = 0;
  private readonly live = new Map<string, Live>();
  /** 제목을 읽기 시작한 `<보기 번호>|<그래프>` */
  private readonly titleLoads = new Set<string>();
  /** 읽는 중인 스텝 기록 `<보기 번호>|<스텝>` → 끝난 뒤 다시 읽을지 */
  private readonly detailInflight = new Map<string, { again: boolean }>();
  /** 실행별 마지막 비교 요청 번호 (늦게 온 옛 응답 버림) */
  private readonly compareSeq = new Map<string, number>();

  constructor(
    private readonly call: RpcCall,
    private readonly delay: (fn: () => void, ms: number) => ReturnType<typeof setTimeout> = (fn, ms) => setTimeout(fn, ms),
  ) {}

  get(runId: string): RunViewState | undefined {
    return this.store.getState().runs.get(runId);
  }

  /** 그 보기(instance)가 아직 있을 때만 고친다 (instance를 주지 않으면 지금 보기) */
  private patch(runId: string, fn: (v: RunViewState) => Partial<RunViewState> | null, instance?: number): void {
    this.store.setState((s) => {
      const v = s.runs.get(runId);
      if (v === undefined || (instance !== undefined && v.instance !== instance)) return s;
      const p = fn(v);
      if (p === null) return s;
      return { runs: new Map(s.runs).set(runId, { ...v, ...p }) };
    });
  }

  private alive(runId: string, instance: number, gen: number): boolean {
    return gen === this.generation && this.get(runId)?.instance === instance;
  }

  /**
   * RUN 탭을 연다. 처음이면 색인을 읽고 실패 노드로 이동한다. 이미 열려 있으면 그대로 두되, toFailure면(실행 목록·
   * "실패 보기") 최신 색인을 읽어 실패 사슬로 다시 이동한다
   */
  async open(runId: string, toFailure = false): Promise<void> {
    const existing = this.get(runId);
    if (existing !== undefined) {
      if (toFailure && existing.index !== null) await this.focusFailure(runId);
      return;
    }
    this.store.setState((s) => ({ runs: new Map(s.runs).set(runId, emptyView(runId)) }));
    await this.loadIndex(runId);
    const view = this.get(runId);
    if (view?.index == null) return;
    await this.jump(runId);
  }

  /** 열린 탭에서 실패(또는 끝나지 않은 스텝)로 다시 간다: 타임라인 보기·펼침·선택·보이게 */
  async focusFailure(runId: string): Promise<void> {
    this.patch(runId, () => ({ view: "timeline" }));
    await this.loadIndex(runId);
    await this.jump(runId, true);
  }

  close(runId: string): void {
    const live = this.live.get(runId);
    if (live?.timer != null) clearTimeout(live.timer);
    this.live.delete(runId);
    const view = this.get(runId);
    if (view !== undefined) {
      for (const key of [...this.titleLoads]) if (key.startsWith(`${view.instance}|`)) this.titleLoads.delete(key);
    }
    this.store.setState((s) => {
      if (!s.runs.has(runId)) return s;
      const runs = new Map(s.runs);
      runs.delete(runId);
      return { runs };
    });
  }

  /** 프로젝트를 바꿨다 */
  reset(): void {
    this.generation++;
    for (const l of this.live.values()) if (l.timer !== null) clearTimeout(l.timer);
    this.live.clear();
    this.titleLoads.clear();
    this.detailInflight.clear();
    this.compareSeq.clear();
    this.store.setState({ runs: new Map() });
  }

  private async loadIndex(runId: string): Promise<boolean> {
    const gen = this.generation;
    const instance = this.get(runId)?.instance;
    if (instance === undefined) return false;
    let index: RunIndex;
    try {
      index = await this.call("run.index", { run_id: runId });
    } catch (err) {
      if (this.alive(runId, instance, gen)) {
        this.patch(runId, (v) => (v.index === null ? { status: "error", error: toRpcError(err).message } : null), instance);
      }
      return false;
    }
    if (!this.alive(runId, instance, gen)) return false;
    let applied = false;
    this.patch(
      runId,
      (v) => {
        // seq 순서: 앞서 받은 색인보다 오래된 응답은 쓰지 않는다
        if (v.index !== null && index.last_seq < v.index.last_seq) return null;
        applied = true;
        return { status: "ready", error: null, index };
      },
      instance,
    );
    if (applied) this.loadTitles(runId, index);
    return applied;
  }

  /** 실패 사슬(없으면 끝나지 않은 가장 안쪽 스텝)로 간다. force면 이미 이동한 보기도 다시 */
  private async jump(runId: string, force = false): Promise<void> {
    const view = this.get(runId);
    if (view?.index == null || (view.jumped && !force)) return;
    const index = view.index;
    const instance = view.instance;
    let plan: JumpPlan;
    try {
      plan = await planJump(index, async (parent, iteration) => this.loadAll(runId, parent, iteration));
    } catch {
      return;
    }
    const now = this.get(runId);
    if (now === undefined || now.instance !== instance || (now.jumped && !force)) return;
    const expanded = new Set(now.expanded);
    const iterations = new Map(now.iteration);
    for (const e of plan.expand) {
      expanded.add(e.step);
      if (e.iteration !== null) iterations.set(e.step, e.iteration);
    }
    this.patch(runId, () => ({ expanded, iteration: iterations, jumped: true }), instance);
    // 펼친 부모의 쪽 (실패 사슬은 색인이 아는 스텝만으로도 보이지만 형제도 보이게)
    await Promise.all(
      plan.expand.map((e) => {
        const v = this.get(runId);
        const parent = v === undefined ? null : findStep(v, e.step);
        return parent === null ? Promise.resolve() : this.ensurePage(runId, parent, e.iteration);
      }),
    );
    if (plan.select !== null && this.get(runId)?.instance === instance) this.select(runId, plan.select, true);
  }

  /** 그 부모(·회차) 아래 스텝 전부 (첫 쪽, 넘치면 마지막 쪽까지). 이동 계산용 */
  private async loadAll(runId: string, parent: StepNode, iteration: number | null): Promise<StepNode[]> {
    await this.loadChildren(runId, parent.step, iteration, 0);
    let page = this.get(runId)?.pages.get(pageKey(parent.step, iteration));
    if (page !== undefined && page.total > page.steps.length) {
      await this.loadChildren(runId, parent.step, iteration, Math.max(0, page.total - PAGE));
      page = this.get(runId)?.pages.get(pageKey(parent.step, iteration));
    }
    return page?.steps ?? [];
  }

  private async ensurePage(runId: string, parent: StepNode, iteration: number | null): Promise<void> {
    if (this.get(runId)?.pages.has(pageKey(parent.step, iteration))) return;
    await this.loadChildren(runId, parent.step, iteration, 0);
  }

  /** 쪽 하나를 읽어 합친다. offset이 이어 읽은 곳 안이면 loaded를 늘린다 */
  async loadChildren(runId: string, parent: string, iteration: number | null, offset: number, limit = PAGE): Promise<void> {
    const key = pageKey(parent, iteration);
    const gen = this.generation;
    const instance = this.get(runId)?.instance;
    if (instance === undefined) return;
    this.patch(runId, (v) => ({ pages: new Map(v.pages).set(key, { ...(v.pages.get(key) ?? EMPTY_PAGE), loading: true }) }), instance);
    let result: ResultOf<"run.children">;
    try {
      result = await this.call("run.children", {
        run_id: runId,
        parent,
        offset,
        limit,
        ...(iteration === null ? {} : { iteration }),
      });
    } catch (err) {
      if (!this.alive(runId, instance, gen)) return;
      const message = toRpcError(err).message;
      this.patch(
        runId,
        (v) => ({ pages: new Map(v.pages).set(key, { ...(v.pages.get(key) ?? EMPTY_PAGE), loading: false, error: message }) }),
        instance,
      );
      return;
    }
    if (!this.alive(runId, instance, gen)) return;
    this.patch(
      runId,
      (v) => {
        const page = v.pages.get(key) ?? EMPTY_PAGE;
        const total = Math.max(result.total, 0);
        const steps = mergeSteps(page.steps, result.steps);
        // 다 모였으면(앞·뒤 쪽이 만남) 이어 읽은 것으로 본다
        const loaded =
          steps.length >= total ? total : offset <= page.loaded ? Math.max(page.loaded, offset + result.steps.length) : page.loaded;
        const next: ChildPage = {
          steps,
          total,
          loaded: Math.min(loaded, total),
          loading: false,
          error: null,
        };
        return { pages: new Map(v.pages).set(key, next) };
      },
      instance,
    );
    const v = this.get(runId);
    if (v?.index != null) this.loadTitles(runId, v.index, result.steps);
  }

  /** "더 보기": 이어 읽은 곳부터 다음 쪽 */
  async loadMore(runId: string, parent: string, iteration: number | null): Promise<void> {
    const page = this.get(runId)?.pages.get(pageKey(parent, iteration));
    if (page === undefined || page.loading) return;
    await this.loadChildren(runId, parent, iteration, page.loaded);
  }

  /** 펼치기·접기. 펼칠 때 쪽이 없으면 읽는다 (반복은 보고 있는 회차, 처음이면 마지막 회차) */
  toggle(runId: string, step: string): void {
    const view = this.get(runId);
    if (view === undefined) return;
    const node = findStep(view, step);
    if (node === null) return;
    const expanded = new Set(view.expanded);
    if (expanded.has(step)) {
      expanded.delete(step);
      this.patch(runId, () => ({ expanded }));
      return;
    }
    expanded.add(step);
    let iteration: number | null = null;
    const iterations = new Map(view.iteration);
    if (node.iterations !== undefined && node.iterations.length > 0) {
      iteration = iterations.get(step) ?? node.iterations[node.iterations.length - 1].iteration;
      iterations.set(step, iteration);
    }
    this.patch(runId, () => ({ expanded, iteration: iterations }));
    void this.ensurePage(runId, node, iteration);
  }

  /** 회차 막대를 눌렀다: 그 회차 스텝을 연다 */
  setIteration(runId: string, loopStep: string, iteration: number): void {
    const view = this.get(runId);
    if (view === undefined) return;
    const node = findStep(view, loopStep);
    if (node === null) return;
    const expanded = new Set(view.expanded).add(loopStep);
    this.patch(runId, () => ({ expanded, iteration: new Map(view.iteration).set(loopStep, iteration) }));
    void this.ensurePage(runId, node, iteration);
  }

  /** 스텝을 고르고 자세한 기록(증거)을 읽는다. reveal이면 그 줄이 보이게 옮긴다 */
  select(runId: string, step: string, reveal = false): void {
    this.patch(runId, () => ({
      selected: step,
      ...(reveal ? { reveal: { step, nonce: ++revealNonce } } : {}),
    }));
    void this.loadDetail(runId, step);
  }

  /**
   * 자세한 기록을 읽는다. 이미 끝난 스텝의 기록이 있으면 다시 읽지 않는다. 한 스텝에 요청은 한 번에 하나다: 읽는
   * 중에 다시 읽을 일이 생기면(진행 중 갱신·실행 끝) 기억했다가 그 요청이 끝난 뒤 한 번 더 읽는다. 받은 기록이
   * 끝나지 않은 것인데 색인은 그 스텝이 끝났다고 하면(늦게 온 옛 응답) 한 번 더 읽는다. 끝나지 않은 기록이 이미 받은
   * 끝난 기록을 덮지 않는다
   */
  private async loadDetail(runId: string, step: string, force = false, retried = false): Promise<void> {
    const view = this.get(runId);
    if (view === undefined) return;
    const have = view.details.get(step);
    if (!force && detailComplete(have)) return;
    const key = `${view.instance}|${step}`;
    const inflight = this.detailInflight.get(key);
    if (inflight !== undefined) {
      inflight.again = true;
      return;
    }
    const track = { again: false };
    this.detailInflight.set(key, track);
    const gen = this.generation;
    const instance = view.instance;
    if (typeof have !== "object") this.patch(runId, (v) => ({ details: new Map(v.details).set(step, "loading") }), instance);
    let detail: StepDetail | "error";
    try {
      detail = await this.call("run.step", { run_id: runId, step });
    } catch {
      detail = "error";
    } finally {
      this.detailInflight.delete(key);
    }
    if (!this.alive(runId, instance, gen)) return;
    this.patch(
      runId,
      (v) => {
        const current = v.details.get(step);
        if (detail === "error" && typeof current === "object") return null;
        if (!detailComplete(detail) && detailComplete(current)) return null;
        return { details: new Map(v.details).set(step, detail) };
      },
      instance,
    );
    if (detailComplete(detail)) return;
    const now = this.get(runId);
    const node = now === undefined ? null : findStep(now, step);
    const ended = node !== null && node.status !== "running" && node.status !== "aborted";
    if (track.again) await this.loadDetail(runId, step, true, retried);
    else if (ended && !retried) await this.loadDetail(runId, step, true, true);
  }

  setView(runId: string, view: RunViewState["view"]): void {
    this.patch(runId, () => ({ view }));
    if (view === "runjson") void this.loadRunJson(runId);
  }

  setMedia(runId: string, media: RunViewState["media"]): void {
    this.patch(runId, () => ({ media }));
  }

  setNotice(runId: string, notice: RunViewState["notice"]): void {
    this.patch(runId, () => ({ notice }));
  }

  /** 기준 실행을 고른다 (null = 자동) */
  setBaseline(runId: string, baseline: string | null): void {
    this.patch(runId, () => ({ baseline }));
  }

  /**
   * 지난 성공과 비교 (run.compare). step = 화면을 비교할 스텝 (null = 실패 스텝). 같은 열쇠는 다시 읽지 않는다(진행
   * 중 실행은 끝난 뒤 다시). 늦게 온 다른 열쇠의 응답은 쓰지 않는다
   */
  async loadCompare(runId: string, step: string | null, force = false): Promise<void> {
    const view = this.get(runId);
    if (view?.index == null) return;
    const key = compareKey(view.baseline, step);
    const have = view.compare;
    if (!force && have !== null && have.key === key && have.result !== "loading" && !("error" in have.result)) return;
    if (!force && have !== null && have.key === key && have.result === "loading") return;
    const gen = this.generation;
    const instance = view.instance;
    // 마지막 요청만 반영한다: 실행 끝 뒤 강제 재요청보다 늦게 온 진행 중 응답, A→B→A의 첫 A 응답은 버린다
    const seqKey = `${instance}|${runId}`;
    const seq = (this.compareSeq.get(seqKey) ?? 0) + 1;
    this.compareSeq.set(seqKey, seq);
    this.patch(runId, () => ({ compare: { key, result: "loading" } }), instance);
    let result: CompareResult | { error: string };
    try {
      result = await this.call("run.compare", {
        run_id: runId,
        ...(view.baseline === null ? {} : { baseline: view.baseline }),
        ...(step === null ? {} : { step }),
      });
    } catch (err) {
      result = { error: toRpcError(err).message };
    }
    if (!this.alive(runId, instance, gen) || this.compareSeq.get(seqKey) !== seq) return;
    this.patch(runId, (v) => (v.compare?.key === key ? { compare: { key, result } } : null), instance);
  }

  /**
   * 아무 스텝으로나 간다 (노드별 통계 → 그 노드의 마지막 실패): 색인·읽은 쪽에 없는 조상은 run.step으로 부모를 따라
   * 올라가며 읽고, 조상을 모두 펼친 뒤(반복이면 그 회차) 고르고 보이게 한다. 쪽을 다 읽지 않아도 줄이 보이게 그
   * 사슬을 고정한다(pinned)
   */
  async revealStep(runId: string, step: string): Promise<boolean> {
    const start = this.get(runId);
    if (start?.index == null) return false;
    const instance = start.instance;
    const gen = this.generation;
    this.patch(runId, () => ({ view: "timeline" }), instance);
    const chain: StepNode[] = [];
    let id: string | null = step;
    for (let depth = 0; id !== null && depth < 64; depth++) {
      const v = this.get(runId);
      if (v === undefined || v.instance !== instance) return false;
      let node: StepNode | null = findStep(v, id);
      if (node === null) {
        try {
          const detail: StepDetail = await this.call("run.step", { run_id: runId, step: id });
          node = detail.step;
          const sid = id;
          if (detailComplete(detail)) this.patch(runId, (x) => ({ details: new Map(x.details).set(sid, detail) }), instance);
        } catch {
          return false;
        }
      }
      chain.unshift(node);
      id = node.parent;
    }
    if (!this.alive(runId, instance, gen)) return false;
    const unknown = chain.filter((n) => {
      const v = this.get(runId)!;
      return !(v.index?.steps ?? []).some((s) => s.step === n.step);
    });
    const expanded = new Set(this.get(runId)!.expanded);
    const iterations = new Map(this.get(runId)!.iteration);
    for (let i = 0; i < chain.length - 1; i++) {
      expanded.add(chain[i].step);
      if (chain[i].iterations !== undefined && chain[i + 1].iteration !== undefined) iterations.set(chain[i].step, chain[i + 1].iteration!);
    }
    this.patch(runId, (v) => ({ expanded, iteration: iterations, pinned: mergeSteps(v.pinned, unknown) }), instance);
    await Promise.all(
      chain.slice(0, -1).map((parent) => this.ensurePage(runId, parent, parent.iterations !== undefined ? (iterations.get(parent.step) ?? null) : null)),
    );
    if (!this.alive(runId, instance, gen)) return false;
    this.select(runId, step, true);
    return true;
  }

  private async loadRunJson(runId: string): Promise<void> {
    const gen = this.generation;
    const instance = this.get(runId)?.instance;
    if (instance === undefined) return;
    this.patch(runId, (v) => (v.runJson !== null && v.runJson !== "error" ? null : { runJson: "loading" }), instance);
    try {
      const r = await this.call("run.file", { run_id: runId, name: "run.json" });
      if (this.alive(runId, instance, gen)) this.patch(runId, () => ({ runJson: { text: r.text, truncated: r.truncated } }), instance);
    } catch {
      if (this.alive(runId, instance, gen)) this.patch(runId, () => ({ runJson: "error" }), instance);
    }
  }

  // ── 진행 중 실행 ───────────────────────────────────────────────

  /** 실행 화면이 그 실행의 이벤트를 seq까지 적용했다 (ended: run.ended를 받음) */
  noteSeq(runId: string, seq: number, ended = false): void {
    const view = this.get(runId);
    if (view === undefined) return;
    const live = this.live.get(runId) ?? { seq: 0, timer: null, inflight: false, again: false };
    this.live.set(runId, live);
    const known = view.index?.last_seq ?? 0;
    const wasRunning = view.index === null || view.index.state === "running";
    live.seq = Math.max(live.seq, seq);
    if (!wasRunning) return;
    if (live.seq <= known && !ended) return;
    this.schedule(runId, live);
  }

  private schedule(runId: string, live: Live): void {
    if (live.inflight) {
      live.again = true;
      return;
    }
    if (live.timer !== null) return;
    live.timer = this.delay(() => {
      live.timer = null;
      void this.refresh(runId);
    }, LIVE_REFRESH_MS);
  }

  /** 색인과 읽은 쪽, 끝나지 않은 고른 스텝 기록을 다시 읽는다 (진행 중 실행) */
  async refresh(runId: string): Promise<void> {
    const live = this.live.get(runId) ?? { seq: 0, timer: null, inflight: false, again: false };
    this.live.set(runId, live);
    if (live.inflight) {
      live.again = true;
      return;
    }
    live.inflight = true;
    live.again = false;
    try {
      await this.loadIndex(runId);
      const view = this.get(runId);
      if (view === undefined) return;
      // 펼친 부모의 쪽을 다시 (처음부터 이어 읽은 만큼)
      const reloads: Promise<void>[] = [];
      for (const [key, page] of view.pages) {
        const [parent, iter] = key.split("#");
        const iteration = iter === undefined ? null : Number(iter);
        if (!view.expanded.has(parent)) continue;
        reloads.push(this.loadChildren(runId, parent, iteration, 0, Math.min(500, Math.max(PAGE, page.loaded))));
      }
      // 고른 스텝의 기록이 끝나지 않은 것이면(실행 중에 읽음) 다시: 끝났으면 증거·썸네일이 생겼다
      const selected = view.selected;
      if (selected !== null && !detailComplete(view.details.get(selected))) reloads.push(this.loadDetail(runId, selected, true));
      await Promise.all(reloads);
      if (!view.jumped) await this.jump(runId);
    } finally {
      live.inflight = false;
    }
    const view = this.get(runId);
    const known = view?.index?.last_seq ?? 0;
    if (view !== undefined && view.index?.state === "running" && (live.again || live.seq > known)) this.schedule(runId, live);
  }

  // ── 노드 제목 (실행 스냅샷) ─────────────────────────────────────

  private loadTitles(runId: string, index: RunIndex, extra: readonly StepNode[] = []): void {
    const view = this.get(runId);
    if (view === undefined) return;
    const graphs = new Set<string>([...index.steps, ...extra].map((s) => s.graph).filter((g) => g !== ""));
    const test = typeof index.run?.graph === "string" ? index.run.graph : null;
    if (test !== null) graphs.add(test);
    for (const g of [...graphs, ...[...index.steps, ...extra].flatMap((s) => (s.calls === undefined ? [] : [s.calls]))]) {
      const key = `${view.instance}|${g}`;
      if (this.titleLoads.has(key)) continue;
      this.titleLoads.add(key);
      void this.loadGraphTitles(runId, view.instance, index.run_dir, g, g === test);
    }
  }

  private async loadGraphTitles(runId: string, instance: number, runDir: string, graph: string, isTest: boolean): Promise<void> {
    const gen = this.generation;
    let result: ResultOf<"graph.open">;
    try {
      result = await this.call("graph.open", { path: `${runDir}/snapshot/${graph}` });
    } catch {
      this.titleLoads.delete(`${instance}|${graph}`);
      return;
    }
    void this.call("graph.close", { doc_id: result.doc_id }).catch(() => {});
    if (!this.alive(runId, instance, gen)) return;
    const value = result.value as { nodes?: Record<string, { title?: unknown; type?: unknown }>; meta?: { title?: unknown } } | null;
    const info = new Map<string, NodeInfo>();
    for (const [id, node] of Object.entries(value?.nodes ?? {})) {
      info.set(id, {
        title: typeof node?.title === "string" ? node.title : null,
        type: typeof node?.type === "string" ? node.type : null,
      });
    }
    const title = typeof value?.meta?.title === "string" ? value.meta.title : null;
    this.patch(
      runId,
      (v) => ({
        nodes: new Map(v.nodes).set(graph, info),
        ...(isTest && title !== null ? { testTitle: title } : {}),
      }),
      instance,
    );
  }
}

/** 앱 전체가 쓰는 기록 뷰어 상태 */
export const runIndexModel = new RunIndexModel((method, params) => client().call(method, params));
export const useRunIndex = runIndexModel.store;
