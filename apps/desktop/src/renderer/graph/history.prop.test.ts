// 무작위 편집 열 (M2 계획 T9 완료 기준 history.prop.test.ts, fast-check).
// 편집기 쪽(명령 + 실행 취소 기록)과 따로 짠 기준 모형(Map 트리를 고치는 단순 구현)에 같은 명령 열을 주고 매 걸음
// 값이 같은지 본다. 노드 ID는 바뀌지 않고, 모르는 노드·모르는 키는 그대로이며, 전부 실행 취소하면 열었을 때의
// 값으로 돌아온다
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { addNode, connectData, connectExec, deleteNodes, disconnect, moveNodes, type EdgeRef } from "./commands";
import { CORPUS_FILES, deepFreeze, readCorpus } from "./corpus.testutil";
import { EMPTY_HISTORY, record, redo, undo, type History } from "./history";
import { newNodeId, takenIds } from "./ids";
import { findLinks, isObject, type GraphValue } from "./model";
import { jsonEqual } from "./valueOps";

// ── 기준 모형: 객체 = Map (키 순서 보존, `__proto__`도 보통 키) ───────────────

type M = Map<string, unknown>;

function toModel(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(toModel);
  if (isObject(v)) return new Map(Object.keys(v).map((k) => [k, toModel(v[k])]));
  return v;
}

function fromModel(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(fromModel);
  if (v instanceof Map) {
    const out: Record<string, unknown> = {};
    for (const [k, x] of v) Object.defineProperty(out, k, { value: fromModel(x), enumerable: true, writable: true, configurable: true });
    return out;
  }
  return v;
}

const mapAt = (m: unknown, k: string): M | undefined => {
  const v = m instanceof Map ? m.get(k) : undefined;
  return v instanceof Map ? (v as M) : undefined;
};

function ensure(m: M, k: string): M {
  const v = m.get(k);
  if (v instanceof Map) return v as M;
  const fresh: M = new Map();
  m.set(k, fresh);
  return fresh;
}

const node = (root: M, id: string) => mapAt(mapAt(root, "nodes"), id);

function mAdd(root: M, id: string, type: string, version: number, x: number, y: number, plugin: [string, string] | null) {
  ensure(root, "nodes").set(id, new Map<string, unknown>([["type", type], ["version", version]]));
  ensure(ensure(root, "layout"), "nodes").set(id, new Map<string, unknown>([["x", x], ["y", y]]));
  if (plugin !== null) {
    const plugins = ensure(root, "plugins");
    if (!plugins.has(plugin[0])) plugins.set(plugin[0], plugin[1]);
  }
}

function mMove(root: M, id: string, x: number, y: number) {
  if (node(root, id) === undefined) return;
  const nodes = ensure(ensure(root, "layout"), "nodes");
  const at = nodes.get(id);
  if (at instanceof Map) {
    at.set("x", x);
    at.set("y", y);
  } else nodes.set(id, new Map<string, unknown>([["x", x], ["y", y]]));
}

function mConnectExec(root: M, from: string, exit: string, to: string) {
  const a = node(root, from);
  if (a === undefined || node(root, to) === undefined) return;
  ensure(a, "next").set(exit, to);
}

function mConnectData(root: M, from: string, output: string, to: string, pin: string) {
  const b = node(root, to);
  if (b === undefined || node(root, from) === undefined) return;
  ensure(b, "in").set(pin, new Map([["$link", `${from}.${output}`]]));
}

function mRemoveKey(n: M, map: "next" | "in", key: string) {
  const m = mapAt(n, map);
  if (m === undefined || !m.has(key)) return;
  m.delete(key);
  if (m.size === 0) n.delete(map);
}

function mDisconnect(root: M, e: EdgeRef) {
  const n = node(root, e.node);
  if (n === undefined) return;
  if (e.kind === "exec") mRemoveKey(n, "next", e.exit);
  else mRemoveKey(n, "in", e.pin);
}

function mDelete(root: M, ids: string[]) {
  const nodes = mapAt(root, "nodes");
  if (nodes === undefined) return;
  const gone = new Set(ids.filter((id) => nodes.get(id) instanceof Map));
  if (gone.size === 0) return;
  for (const [id, n] of nodes) {
    if (gone.has(id) || !(n instanceof Map)) continue;
    const next = mapAt(n, "next");
    if (next !== undefined) for (const [exit, to] of [...next]) if (typeof to === "string" && gone.has(to)) mRemoveKey(n, "next", exit);
    const inputs = mapAt(n, "in");
    if (inputs !== undefined) {
      for (const [pin, v] of [...inputs]) if (findLinks(fromModel(v)).some((l) => gone.has(l.node))) mRemoveKey(n, "in", pin);
    }
  }
  for (const id of gone) {
    nodes.delete(id);
    mapAt(mapAt(root, "layout"), "nodes")?.delete(id);
  }
  const groups = mapAt(mapAt(root, "layout"), "collapsed");
  for (const g of groups?.values() ?? []) {
    if (!(g instanceof Map)) continue;
    const members = g.get("nodes");
    if (Array.isArray(members) && members.some((m) => typeof m === "string" && gone.has(m))) {
      g.set("nodes", members.filter((m) => !(typeof m === "string" && gone.has(m))));
    }
  }
}

function cloneModel(v: unknown): unknown {
  return toModel(fromModel(v));
}

// ── 무작위 명령 ───────────────────────────────────────────────────

type Op = "add" | "move" | "exec" | "data" | "cut" | "delete" | "undo" | "redo";

interface Intent {
  op: Op;
  a: number;
  b: number;
  c: number;
  x: number;
  y: number;
  seed: number[];
}

const TYPES: [string, number, [string, string] | null][] = [
  ["core.flow.delay", 1, ["core", "0.1.0"]],
  ["core.log.message", 1, ["core", "0.1.0"]],
  ["acme.vision.magic", 2, ["acme", "9.9.9"]],
  ["zeta.unknown.node", 1, null],
];
const EXITS = ["done", "found", "x_exit", "__proto__"];
const PINS = ["text", "ms", "x_pin", "constructor"];
const OUTPUTS = ["match", "value", "x_out"];

const intent = fc.record({
  op: fc.constantFrom<Op>("add", "move", "exec", "data", "cut", "delete", "undo", "redo"),
  a: fc.nat(),
  b: fc.nat(),
  c: fc.nat(),
  x: fc.integer({ min: -2000, max: 2000 }),
  y: fc.integer({ min: -2000, max: 2000 }),
  seed: fc.array(fc.nat({ max: 255 }), { minLength: 8, maxLength: 8 }),
});

function nodeIds(value: GraphValue): string[] {
  const nodes = value.nodes;
  return isObject(nodes) ? Object.keys(nodes).filter((id) => isObject(nodes[id])) : [];
}

/** 지금 값의 연결 (흐름 출구, 데이터 핀) */
function edges(value: GraphValue): EdgeRef[] {
  const out: EdgeRef[] = [];
  const nodes = value.nodes as Record<string, unknown>;
  for (const id of nodeIds(value)) {
    const n = nodes[id] as Record<string, unknown>;
    if (isObject(n.next) && Object.hasOwn(n, "next")) {
      for (const exit of Object.keys(n.next)) if (typeof n.next[exit] === "string") out.push({ kind: "exec", node: id, exit });
    }
    if (isObject(n.in) && Object.hasOwn(n, "in")) {
      for (const pin of Object.keys(n.in)) if (findLinks(n.in[pin]).length > 0) out.push({ kind: "data", node: id, pin, path: [] });
    }
  }
  return out;
}

const pick = <T,>(list: readonly T[], i: number): T | undefined => (list.length === 0 ? undefined : list[i % list.length]);

interface State {
  value: GraphValue;
  history: History;
  model: M;
  past: unknown[];
  future: unknown[];
  added: Set<string>;
  deleted: Set<string>;
}

/** 편집기 쪽 명령 (값 → 새 값)과 같은 일을 하는 모형 쪽 함수 */
function plan(s: State, it: Intent): { edit: (v: GraphValue) => GraphValue; model: (m: M) => void; adds?: string; dels?: string[] } | null {
  const ids = nodeIds(s.value);
  switch (it.op) {
    case "add": {
      const [type, version, plugin] = TYPES[it.a % TYPES.length];
      let k = 0;
      const id = newNodeId(takenIds(s.value), () => Uint8Array.from(it.seed.map((b) => (b + 37 * k++) & 255)));
      return {
        edit: (v) => addNode(v, { id, type, version, x: it.x, y: it.y, plugin: plugin && { id: plugin[0], version: plugin[1] } }),
        model: (m) => mAdd(m, id, type, version, it.x, it.y, plugin),
        adds: id,
      };
    }
    case "move": {
      const id = pick(ids, it.a);
      if (id === undefined) return null;
      return { edit: (v) => moveNodes(v, [{ id, x: it.x, y: it.y }]), model: (m) => mMove(m, id, it.x, it.y) };
    }
    case "exec": {
      const from = pick(ids, it.a);
      const to = pick(ids, it.b);
      const exit = EXITS[it.c % EXITS.length];
      if (from === undefined || to === undefined) return null;
      return { edit: (v) => connectExec(v, from, exit, to), model: (m) => mConnectExec(m, from, exit, to) };
    }
    case "data": {
      const from = pick(ids, it.a);
      const to = pick(ids, it.b);
      if (from === undefined || to === undefined) return null;
      const pin = PINS[it.c % PINS.length];
      const output = OUTPUTS[it.x & 1 ? 0 : (it.c >> 2) % OUTPUTS.length];
      return { edit: (v) => connectData(v, from, output, to, pin), model: (m) => mConnectData(m, from, output, to, pin) };
    }
    case "cut": {
      const e = pick(edges(s.value), it.a);
      if (e === undefined) return null;
      return { edit: (v) => disconnect(v, e), model: (m) => mDisconnect(m, e) };
    }
    case "delete": {
      if (ids.length === 0) return null;
      const chosen = [...new Set([pick(ids, it.a)!, ...(it.b % 3 === 0 ? [pick(ids, it.c)!] : [])])];
      return { edit: (v) => deleteNodes(v, chosen), model: (m) => mDelete(m, chosen), dels: chosen };
    }
    default:
      return null;
  }
}

function step(s: State, it: Intent): void {
  if (it.op === "undo" || it.op === "redo") {
    const moved = (it.op === "undo" ? undo : redo)(s.history, s.value);
    if (it.op === "undo" && s.past.length > 0) {
      s.future.unshift(cloneModel(s.model));
      s.model = s.past.pop() as M;
    } else if (it.op === "redo" && s.future.length > 0) {
      s.past.push(cloneModel(s.model));
      s.model = s.future.shift() as M;
    }
    if (moved !== null) {
      s.value = moved.value;
      s.history = moved.history;
    }
    return;
  }
  const p = plan(s, it);
  if (p === null) return;
  const next = p.edit(s.value);
  if (next === s.value) {
    // 바뀐 것이 없는 명령은 기록하지 않는다. 모형도 그대로여야 한다
    const before = cloneModel(s.model);
    p.model(s.model);
    expect(jsonEqual(fromModel(s.model), fromModel(before))).toBe(true);
    return;
  }
  applied[it.op] = (applied[it.op] ?? 0) + 1;
  s.history = record(s.history, s.value);
  s.past.push(cloneModel(s.model));
  s.future = [];
  s.value = next;
  p.model(s.model);
  if (p.adds !== undefined) s.added.add(p.adds);
  for (const d of p.dels ?? []) s.deleted.add(d);
}

const VALUES = CORPUS_FILES.map((rel) => ({ rel, value: deepFreeze(readCorpus(rel)) }));
/** 실제로 값을 바꾼 명령 수 (검사가 빈 열만 돌지 않았는지) */
const applied: Partial<Record<Op, number>> = {};
const STRUCTURAL = new Set(["in", "next"]);

describe("무작위 편집 열", () => {
  test("history.prop: 모형과 같은 값, ID 불변, 모르는 노드·키 보존, 전부 실행 취소하면 처음 값", () => {
    fc.assert(
      fc.property(fc.constantFrom(...VALUES), fc.array(intent, { maxLength: 40 }), ({ value: opened }, intents) => {
        const s: State = {
          value: opened,
          history: EMPTY_HISTORY,
          model: toModel(opened) as M,
          past: [],
          future: [],
          added: new Set(),
          deleted: new Set(),
        };
        for (const it of intents) {
          step(s, it);
          expect(jsonEqual(s.value, fromModel(s.model))).toBe(true);
        }
        // 노드 ID는 만들 때 정하고 바뀌지 않는다: 지금 노드는 처음 노드나 더한 노드
        const start = new Set(nodeIds(opened));
        for (const id of nodeIds(s.value)) expect(start.has(id) || s.added.has(id), id).toBe(true);
        // 처음 노드가 남아 있으면 in·next 말고는 처음 그대로 (type·version·config·title·모르는 키)
        const before = opened.nodes as Record<string, Record<string, unknown>>;
        const after = s.value.nodes as Record<string, Record<string, unknown>>;
        for (const id of nodeIds(s.value)) {
          if (!start.has(id)) continue;
          for (const k of new Set([...Object.keys(before[id]), ...Object.keys(after[id])])) {
            if (STRUCTURAL.has(k)) continue;
            expect(jsonEqual(after[id][k], before[id][k]), `${id}.${k}`).toBe(true);
          }
        }
        // 최상위 모르는 키·형식 키는 그대로
        for (const k of Object.keys(opened)) {
          if (k === "nodes" || k === "layout" || k === "plugins") continue;
          expect(s.value[k]).toBe(opened[k]);
        }
        // 전부 실행 취소하면 열었을 때의 값 (같은 참조)
        let h = s.history;
        let v = s.value;
        for (let u = undo(h, v); u !== null; u = undo(h, v)) ({ history: h, value: v } = u);
        expect(v).toBe(opened);
      }),
      { numRuns: 300 },
    );
    for (const op of ["add", "move", "exec", "data", "cut", "delete"] as const) {
      expect(applied[op] ?? 0, op).toBeGreaterThan(50);
    }
  });
});
