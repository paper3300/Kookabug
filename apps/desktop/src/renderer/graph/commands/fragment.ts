// 녹화 조각 넣기 (M4 계획 2.9 "그래프는 렌더러가 만든다", T10). 새 테스트·커서 위치 삽입 공용 순수 명령.
// - 로컬 ID(r1…)를 새 노드 ID(newNodeId)로 바꾸고 in 안 모든 $link(배열·객체 안쪽까지, $literal 안은 그대로)와
//   next의 로컬 ID도 같이 바꾼다
// - 삽입 지점: 고른 노드의 고른 ok 출구. 그 출구의 원래 대상을 조각의 열린 끝(open_end)으로 옮기고, 고른 출구는
//   조각 첫 노드로 잇는다. 종료 노드(출구 없음)는 거부한다
// - 배치(2.7): 실행 사슬을 왼쪽 → 오른쪽 260 px, 6개마다 다음 줄(180 px 아래). 기존 노드는 옮기지 않는다
// 다른 노드·키는 건드리지 않는다 (setIn은 바뀐 경로만 새로 만든다). 실행 취소는 부르는 쪽의 applyEdit 한 번이다
import type { recorderFragment } from "@kookabug/schema";
import { newNodeId, takenIds, cryptoBytes, type RandomBytes } from "../ids";
import { isObject, own, type ExitShape, type GraphValue, type JsonObject, type Point } from "../model";
import { getIn, setIn } from "../valueOps";
import { roundCoord } from "./nodes";

export type Fragment = recorderFragment.RecorderFragment;

export const FRAGMENT_STEP_X = 260;
export const FRAGMENT_STEP_Y = 180;
export const FRAGMENT_ROW = 6;

/** 출구 없는 종료 노드 (그 뒤에는 넣지 않는다) */
export const TERMINAL_TYPES: ReadonlySet<string> = new Set([
  "core.test.pass",
  "core.test.fail",
  "core.test.skip",
  "core.graph.exit",
]);

export class FragmentInsertError extends Error {
  override name = "FragmentInsertError";
}

export interface InsertOptions {
  /** 이 노드의 이 출구 뒤에 넣는다 (없으면 이어지지 않은 사슬) */
  after?: { node: string; exit: string } | null;
  /** 조각 첫 노드 자리. 없으면 고른 노드 오른쪽 아래(after), 그것도 없으면 (0, 0) */
  at?: Point | null;
  /** 그래프 plugins에 없는 플러그인 판 (노드 타입 앞부분 → 판). 있는 것은 그대로 */
  plugins?: Readonly<Record<string, string>>;
  random?: RandomBytes;
}

export interface InsertResult {
  value: GraphValue;
  /** 로컬 ID → 새 노드 ID */
  ids: Map<string, string>;
  /** 조각 사슬 차례의 새 노드 ID */
  nodes: string[];
}

/** 고른 노드 뒤에 넣을 수 있는 출구: 종료 노드면 terminal, ok 출구가 여럿이면 고르게 한다 */
export function insertExits(
  type: string,
  exits: readonly ExitShape[] | undefined,
): { kind: "terminal" } | { kind: "one"; exit: string } | { kind: "many"; exits: string[] } {
  const ok = (exits ?? []).filter((e) => e.kind === "ok").map((e) => e.name);
  if (TERMINAL_TYPES.has(type) || ok.length === 0) return { kind: "terminal" };
  return ok.length === 1 ? { kind: "one", exit: ok[0] } : { kind: "many", exits: ok };
}

/** $link 로컬 ID를 새 ID로 (배열·객체 안쪽까지 재귀, $literal 안은 값이라 그대로) */
export function remapLinks(value: unknown, ids: ReadonlyMap<string, string>): unknown {
  if (Array.isArray(value)) return value.map((v) => remapLinks(v, ids));
  if (!isObject(value)) return value;
  const keys = Object.keys(value);
  if (keys.length === 1 && keys[0] === "$literal") return value;
  if (keys.length === 1 && keys[0] === "$link") {
    const link = value.$link;
    if (typeof link !== "string") return value;
    const dot = link.indexOf(".");
    if (dot <= 0) return value;
    const node = ids.get(link.slice(0, dot));
    return node === undefined ? value : { $link: `${node}${link.slice(dot)}` };
  }
  const out: JsonObject = {};
  for (const k of keys) Object.defineProperty(out, k, { value: remapLinks(value[k], ids), writable: true, enumerable: true, configurable: true });
  return out;
}

function pointOf(value: GraphValue, id: string): Point | null {
  const p = getIn(value, ["layout", "nodes", id]);
  const x = own(p, "x");
  const y = own(p, "y");
  return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y) ? { x, y } : null;
}

/** 사슬 차례 i번째 노드 자리 (6개마다 다음 줄) */
export function fragmentSlot(origin: Point, i: number): Point {
  return {
    x: roundCoord(origin.x + (i % FRAGMENT_ROW) * FRAGMENT_STEP_X),
    y: roundCoord(origin.y + Math.floor(i / FRAGMENT_ROW) * FRAGMENT_STEP_Y),
  };
}

/**
 * 조각을 그래프에 넣은 새 값. 넣을 수 없으면(고른 노드가 없음·종료 노드·열린 끝 없이 원래 다음 노드가 있음·
 * 조각 모양이 틀림) FragmentInsertError — 그때 값은 바뀌지 않는다
 */
export function insertFragment(value: GraphValue, fragment: Fragment, options: InsertOptions = {}): InsertResult {
  const random = options.random ?? cryptoBytes;
  const frag = fragment.nodes;
  const locals = new Set(frag.map((n) => n.local_id));
  if (locals.size !== frag.length) throw new FragmentInsertError("조각에 같은 로컬 ID가 둘 있다");
  for (const id of fragment.chain) if (!locals.has(id)) throw new FragmentInsertError(`사슬의 노드가 조각에 없다: ${id}`);
  const after = options.after ?? null;
  let anchorPoint: Point | null = null;
  let oldTarget: string | null = null;
  if (after !== null) {
    const anchor = own(own(value, "nodes"), after.node);
    if (!isObject(anchor)) throw new FragmentInsertError("넣을 자리의 노드가 없어요");
    const type = own(anchor, "type");
    if (typeof type === "string" && TERMINAL_TYPES.has(type)) throw new FragmentInsertError("끝 노드 뒤에는 넣을 수 없어요");
    const old = getIn(anchor, ["next", after.exit]);
    oldTarget = typeof old === "string" ? old : null;
    if (oldTarget !== null && fragment.open_end === undefined) {
      throw new FragmentInsertError("조각에 열린 끝이 없어 원래 다음 노드를 이을 수 없어요");
    }
    anchorPoint = pointOf(value, after.node) ?? { x: 0, y: 0 };
  }
  const taken = takenIds(value);
  const ids = new Map<string, string>();
  for (const n of frag) {
    const id = newNodeId(taken, random);
    taken.add(id);
    ids.set(n.local_id, id);
  }
  const origin = options.at ?? (anchorPoint === null ? { x: 0, y: 0 } : { x: anchorPoint.x + FRAGMENT_STEP_X, y: anchorPoint.y + FRAGMENT_STEP_Y });
  const order = [...fragment.chain, ...frag.map((n) => n.local_id).filter((id) => !fragment.chain.includes(id))];
  let out = value;
  for (const n of frag) {
    const id = ids.get(n.local_id) as string;
    const node: JsonObject = { type: n.type, version: n.version };
    if (n.title !== "") node.title = n.title;
    if (Object.keys(n.in).length > 0) node.in = remapLinks(n.in, ids);
    if (n.config !== undefined) node.config = structuredClone(n.config);
    const next: JsonObject = {};
    for (const [exit, to] of Object.entries(n.next ?? {})) {
      if (typeof to !== "string") continue;
      const target = ids.get(to);
      if (target === undefined) throw new FragmentInsertError(`조각 밖 노드로 잇는다: ${to}`);
      next[exit] = target;
    }
    if (Object.keys(next).length > 0) node.next = next;
    out = setIn(out, ["nodes", id], node);
    out = setIn(out, ["layout", "nodes", id], fragmentSlot(origin, order.indexOf(n.local_id)));
  }
  for (const n of frag) {
    const plugin = n.type.split(".")[0];
    const version = options.plugins?.[plugin];
    if (version !== undefined && own(own(out, "plugins"), plugin) === undefined) out = setIn(out, ["plugins", plugin], version);
  }
  if (after !== null) {
    const first = ids.get(fragment.chain[0]) as string;
    out = setIn(out, ["nodes", after.node, "next", after.exit], first);
    if (oldTarget !== null && fragment.open_end !== undefined) {
      const end = ids.get(fragment.open_end.node);
      if (end === undefined) throw new FragmentInsertError("열린 끝 노드가 조각에 없다");
      out = setIn(out, ["nodes", end, "next", fragment.open_end.exit], oldTarget);
    }
  }
  return { value: out, ids, nodes: fragment.chain.map((id) => ids.get(id) as string) };
}
