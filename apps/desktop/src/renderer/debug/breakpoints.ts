// 브레이크포인트 (M3 계획 2.3·2.9, 사용자 결정 U1). 열쇠는 {그래프 파일, 노드 ID}다: 노드 ID는 바뀌지 않으므로
// 옮기기·제목 바꾸기·입력 편집 뒤에도 그대로 남는다. exec 노드에만 건다(순수 노드는 스텝이 없다).
// - 목록은 daemon이 워크스페이스 단위로 든다(`.kookabug/breakpoints.json`). 화면은 debug.breakpoints.get으로 받고,
//   바꾸면 목록 전체를 debug.breakpoints.set으로 보낸다(진행 중인 UI 실행에는 daemon이 다음 경계부터 밀어 넣는다).
//   다른 연결이 바꾸면 debug.breakpoints.changed로 받는다
// - 토글은 화면에 먼저 반영하고(낙관), 저장은 하나씩 보낸다 (BreakpointModel 설명)
import type { NotificationParamsOf } from "@kookabug/schema";
import { create } from "zustand";
import { client, toRpcError, type RpcCall } from "../rpc/client";
import type { TypeIndex } from "../graph/mapping";
import { graphNodes, type GraphValue } from "../graph/model";

export interface Breakpoint {
  graph: string;
  node: string;
}

export const bpKey = (graph: string, node: string): string => JSON.stringify([graph, node]);

/** 순서 무관 같은 항목은 하나로 (스키마 BreakpointList) */
export function normalize(list: readonly Breakpoint[]): Breakpoint[] {
  const seen = new Set<string>();
  const out: Breakpoint[] = [];
  for (const bp of list) {
    if (typeof bp?.graph !== "string" || typeof bp.node !== "string") continue;
    const key = bpKey(bp.graph, bp.node);
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ graph: bp.graph, node: bp.node });
  }
  return out;
}

export function hasBreakpoint(list: readonly Breakpoint[], graph: string, node: string): boolean {
  return list.some((bp) => bp.graph === graph && bp.node === node);
}

/**
 * 이 노드에 브레이크포인트를 걸 수 있는가: 그래프에 있는 노드이고 순수 노드가 아니다. 노드 타입을 모르면(플러그인
 * 없음) 건다 — 실행 검증이 따로 막는다
 */
export function canBreak(value: GraphValue | null, node: string, types: TypeIndex): boolean {
  if (value === null) return false;
  const found = graphNodes(value).find((n) => n.id === node);
  if (found === undefined) return false;
  return types.get(found.type)?.pure !== true;
}

/** 노드 하나 토글. 걸 수 없는 노드면 null(목록 그대로) */
export function toggleBreakpoint(
  list: readonly Breakpoint[],
  graph: string,
  node: string,
  value: GraphValue | null,
  types: TypeIndex,
): Breakpoint[] | null {
  if (hasBreakpoint(list, graph, node)) return list.filter((bp) => !(bp.graph === graph && bp.node === node));
  if (!canBreak(value, node, types)) return null;
  return [...list, { graph, node }];
}

/**
 * 고른 노드들(F9·메뉴): 걸 수 있는 노드 중 하나라도 없으면 모두 걸고, 모두 있으면 모두 푼다. 바꿀 것이 없으면 null
 */
export function toggleMany(
  list: readonly Breakpoint[],
  graph: string,
  nodes: readonly string[],
  value: GraphValue | null,
  types: TypeIndex,
): Breakpoint[] | null {
  const targets = nodes.filter((n) => hasBreakpoint(list, graph, n) || canBreak(value, n, types));
  if (targets.length === 0) return null;
  const allSet = targets.every((n) => hasBreakpoint(list, graph, n));
  if (allSet) return list.filter((bp) => !(bp.graph === graph && targets.includes(bp.node)));
  return normalize([...list, ...targets.map((node) => ({ graph, node }))]);
}

/** 이 탭(그래프 파일)의 버퍼에 있는 노드 중 브레이크포인트가 걸린 노드 ID */
export function breakpointsIn(list: readonly Breakpoint[], graph: string, value: GraphValue | null): ReadonlySet<string> {
  if (value === null) return new Set();
  const ids = new Set(graphNodes(value).map((n) => n.id));
  return new Set(list.filter((bp) => bp.graph === graph && ids.has(bp.node)).map((bp) => bp.node));
}

// ── 상태 ─────────────────────────────────────────────────────────

export interface BreakpointState {
  list: Breakpoint[];
  loaded: boolean;
}

/**
 * daemon 목록과 화면 목록 (검수 T9-1 Mid): daemon은 요청마다 따로 저장하므로 보낸 순서대로 쓰인다는 보장이 없다.
 * 그래서 한 연결의 set은 **하나씩** 보낸다. 보내는 동안 바뀐 것은 최신 희망 목록 하나로 합쳐 다음에 보낸다
 * (토글은 늘 화면 목록에서 계산하므로 앞 토글을 잃지 않는다). 화면 목록(희망)과 마지막으로 daemon이 확인한
 * 목록(`confirmed`)을 따로 들고, 저장이 실패하면 확인된 목록으로 돌아간다 — 확정되지 않은 낙관 값으로 돌아가지 않는다
 */
export class BreakpointModel {
  readonly store = create<BreakpointState>(() => ({ list: [], loaded: false }));
  /** daemon이 마지막으로 확인한 목록 (get·set 응답·changed 알림) */
  private confirmed: Breakpoint[] = [];
  /** 아직 보내지 않은 최신 희망 목록 */
  private pending: Breakpoint[] | null = null;
  /** 보내는 중인 저장 (하나뿐). 끝나면 pending을 이어 보낸다 */
  private draining: Promise<void> | null = null;
  /** 시작한 저장 수 (그 사이 시작한 get 응답은 쓰지 않는다) */
  private writes = 0;
  private generation = 0;

  constructor(
    private readonly call: RpcCall,
    private note: (message: string) => void = () => {},
  ) {}

  setNote(note: (message: string) => void): void {
    this.note = note;
  }

  get list(): Breakpoint[] {
    return this.store.getState().list;
  }

  /** daemon이 확인한 목록 (저장이 끝났는지·성공했는지는 이것으로 본다) */
  get confirmedList(): readonly Breakpoint[] {
    return this.confirmed;
  }

  /** 보내는 중인 저장이 다 끝날 때 (없으면 바로) */
  settled(): Promise<void> {
    return this.draining ?? Promise.resolve();
  }

  /** 저장 중이거나 보낼 것이 남았다 (화면 목록이 아직 확인되지 않음) */
  private get busy(): boolean {
    return this.draining !== null || this.pending !== null;
  }

  /** daemon이 확인한 목록. 보낼 것이 없을 때만 화면에 쓴다 (있으면 그 저장이 끝날 때 맞춘다) */
  private confirm(list: readonly Breakpoint[]): void {
    this.confirmed = normalize(list);
    if (!this.busy) this.store.setState({ list: this.confirmed, loaded: true });
  }

  /** daemon에 붙을 때마다 파일 값을 받는다 */
  async load(): Promise<void> {
    const gen = this.generation;
    const writes = this.writes;
    try {
      const result = await this.call("debug.breakpoints.get", {});
      // 그 사이 시작한 저장이 있으면 그 응답이 더 새 값이다
      if (gen !== this.generation || writes !== this.writes || this.busy) return;
      this.confirm(result.breakpoints);
    } catch (err) {
      if (gen === this.generation) this.note(`브레이크포인트를 읽지 못했다: ${toRpcError(err).message}`);
    }
  }

  /**
   * 다른 연결이 바꿨다. 우리 저장이 남아 있으면 그것이 나중에 쓰여 이긴다(파일 = 마지막 쓰기)
   */
  changed(p: NotificationParamsOf<"debug.breakpoints.changed">): void {
    this.confirm(p.breakpoints);
  }

  /** 목록 전체를 바꾼다 (화면 먼저). 보낼 것이 다 쓰이면(또는 실패하면) 끝난다 */
  set(list: readonly Breakpoint[]): Promise<void> {
    this.pending = normalize(list);
    this.store.setState({ list: this.pending });
    this.draining ??= this.drain(this.generation);
    return this.draining;
  }

  private async drain(gen: number): Promise<void> {
    try {
      while (this.pending !== null && gen === this.generation) {
        const next = this.pending;
        this.pending = null;
        this.writes++;
        try {
          const result = await this.call("debug.breakpoints.set", { breakpoints: next });
          if (gen !== this.generation) return;
          this.confirmed = normalize(result.breakpoints);
        } catch (err) {
          if (gen !== this.generation) return;
          this.note(`브레이크포인트를 저장하지 못했다: ${toRpcError(err).message}`);
        }
      }
    } finally {
      if (gen === this.generation) {
        this.draining = null;
        // 다 보냈다: 화면 = daemon이 확인한 목록 (실패했으면 확정되지 않은 낙관 값이 아니라 확인된 값으로)
        this.store.setState({ list: this.confirmed, loaded: true });
      }
    }
  }

  reset(): void {
    this.generation++;
    this.pending = null;
    this.draining = null;
    this.confirmed = [];
    this.writes = 0;
    this.store.setState({ list: [], loaded: false });
  }
}

/** 앱 전체가 쓰는 브레이크포인트 (workspace.ts가 연결·알림에 잇는다) */
export const breakpointModel = new BreakpointModel((method, params) => client().call(method, params));
export const useBreakpoints = breakpointModel.store;
