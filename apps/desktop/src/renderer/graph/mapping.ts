// 그래프 값 → React Flow 노드·연결선 (M2 계획 2.6·2.7, T8).
// - 흐름 연결 = 노드 `next`(출구 → 다음 노드), 데이터 연결 = `in`의 `$link`(배열·객체 안쪽 포함,
//   안쪽이면 연결선에 원소 위치를 쓴다)
// - 핀·출구 모양은 daemon이 계산한 것(shapes)을 쓴다. 에디터는 핀 모양을 계산하지 않는다. 모양이 아직
//   없는 노드(응답 전)만 JSON 키로 대체 모양을 만든다 (코어 shapes의 대체 모양과 같은 규칙)
// - JSON에 있는 연결은 모양에 없는 핀·출구여도 그린다 (그 핀을 "모양 밖" 줄로 더한다). 검증 오류는
//   문제 패널에 나온다
// - 접힌 그룹은 보기 상태(view.expanded)에 없으면 구성원을 숨기고 그룹 노드 하나로 그린다. 구성원과
//   밖을 잇는 연결은 그룹 노드로 옮겨 그린다. 주석은 뒤에 깔리는 상자다
// 이 함수는 값을 읽기만 한다 (mapping.test.ts가 코퍼스로 확인한다)
import type { Edge, Node } from "@xyflow/react";
import { categoryInfo, type HeadTone } from "../palette/categories";
import { belongsTo, problemNode } from "../problems/locate";
import { autoLayout } from "./autoLayout";
import {
  collapsedGroups,
  comments,
  findLinks,
  formatValuePath,
  graphNodes,
  isObject,
  layoutPositions,
  own,
  type Diagnostic,
  type GraphNodeValue,
  type GraphValue,
  type NodeShape,
  type NodeShapes,
  type Point,
  type ValuePath,
} from "./model";
import { pinTone, type PinTone } from "./pinColors";
import { shortConstant, summarize } from "./summary";

/** 노드 스키마(nodes.list)에서 읽은 노드 타입 정보 */
export interface NodeTypeInfo {
  type: string;
  version: number;
  title: string;
  category: string | null;
  description: string | null;
  pure: boolean;
  /** 그래프 시작점(core.graph.entry): 흐름 입력이 없다 */
  entry: boolean;
  /** 반복 노드(engine repeat·while)면 한도 입력 이름 (실행 중 "회차 / 한도" 표시, T11) */
  loopLimit: string | null;
  /** 노드 스키마 effects (capture·input·process). 멈춤 띠의 재개 경고가 관측 노드를 알아본다 (M3 2.9) */
  effects: readonly string[];
  plugin: string;
  /** 플러그인 판·이름 (노드를 더할 때 그래프 plugins에 적는다, 팔레트 오른쪽 칸) */
  pluginVersion: string;
  pluginTitle: string;
  /** 노드 스키마의 inputs·outputs·exits 선언 그대로 (정적 모양용). config는 속성 편집기(T10)가 쓴다 */
  decl: { inputs: unknown; outputs: unknown; exits: unknown; config?: unknown };
}

export type TypeIndex = ReadonlyMap<string, NodeTypeInfo>;

export const EXEC_IN = "in";
export const exitHandle = (name: string) => `x:${name}`;
export const inputHandle = (name: string) => `i:${name}`;
export const outputHandle = (name: string) => `o:${name}`;
export const GROUP_IN = "g:in";
export const GROUP_OUT = "g:out";
export const groupNodeId = (id: string) => `group:${id}`;
/**
 * 연결선 ID. 노드·출구·핀·값 안 경로를 JSON 배열로 적어 경계와 타입(키·원소 번호)을 보존한다.
 * 화면에 쓰는 원소 위치(`.k`·`[0]`)는 키에 마침표·대괄호가 있으면 서로 같아질 수 있어 ID로 쓰지 않는다
 */
export const execEdgeId = (node: string, exit: string) => `x:${JSON.stringify([node, exit])}`;
export const dataEdgeId = (node: string, pin: string, path: ValuePath) => `d:${JSON.stringify([node, pin, ...path])}`;
/** 노드 위에 그리는 연결선 층 */
export const BACK_EDGE_Z = 1000;
/** 노드 위 층 연결선의 클래스 (canvas.module.css가 포인터를 끈다) */
export const BACK_EDGE_CLASS = "kb-edge-overlay";
export const commentNodeId = (id: string) => `comment:${id}`;

export interface PinRow {
  handle: string;
  kind: "exec" | "data";
  label: string;
  tone: PinTone;
  /** 모양에 없는 핀·출구 (JSON에만 있음) */
  extra: boolean;
  /** 데이터 핀 타입 (모양 밖 핀은 null). 연결 끌기 중 호환 표시에 쓴다 */
  type: string | null;
}

export interface NodeRow {
  left: PinRow | null;
  right: PinRow | null;
}

export type NoteTone = "plain" | "warn" | "error";

export interface KbNodeData extends Record<string, unknown> {
  id: string;
  type: string;
  title: string;
  head: HeadTone | "warn" | "error";
  rows: NodeRow[];
  note: { text: string; tone: NoteTone } | null;
  status: { text: string; tone: "warn" | "error" | "muted" } | null;
  errors: number;
  warnings: number;
  unknown: boolean;
}

export interface GroupNodeData extends Record<string, unknown> {
  id: string;
  title: string;
  count: number;
  expanded: boolean;
  errors: number;
  warnings: number;
}

export interface CommentNodeData extends Record<string, unknown> {
  id: string;
  text: string;
}

export type KbFlowNode =
  | Node<KbNodeData, "kb">
  | Node<GroupNodeData, "kbGroup">
  | Node<CommentNodeData, "kbComment">;

export interface KbEdgeData extends Record<string, unknown> {
  kind: "exec" | "data";
  tone: PinTone;
  /** 데이터 연결의 원소 위치 (`[0]`, `.error`). 핀 값 자체면 "" */
  where: string;
}

export type KbFlowEdge = Edge<KbEdgeData, "kb">;

export interface ViewState {
  /** 보기 상태로 펼친 접힌 그룹 ID */
  expanded: ReadonlySet<string>;
  /** 고른 노드 (여러 개) */
  selected: ReadonlySet<string>;
  /** 데이터 연결을 끄는 중: 숨긴 선택 입력 핀(기본값 있는 입력)도 핀 줄로 그린다 */
  revealInputs?: boolean;
  /** 좌표 없는 노드의 정해 둔 보기용 자리 (열 때 한 번 정한 자동 배치). 없으면 매번 자동 배치 */
  auto?: ReadonlyMap<string, Point>;
}

export interface FlowGraph {
  nodes: KbFlowNode[];
  edges: KbFlowEdge[];
  /** 접힌 그룹에 숨은 노드 → 그룹 ID */
  hiddenIn: Map<string, string>;
}

/** 노드 스키마 문서 목록(nodes.list) → 타입 표 */
export function indexNodeTypes(schemas: readonly unknown[]): Map<string, NodeTypeInfo> {
  const out = new Map<string, NodeTypeInfo>();
  for (const doc of schemas) {
    if (typeof doc !== "object" || doc === null) continue;
    const d = doc as { plugin?: { id?: unknown; version?: unknown; title?: unknown }; nodes?: unknown };
    const plugin = typeof d.plugin?.id === "string" ? d.plugin.id : "";
    const pluginVersion = typeof d.plugin?.version === "string" ? d.plugin.version : "";
    const pluginTitle = typeof d.plugin?.title === "string" ? d.plugin.title : plugin;
    if (!Array.isArray(d.nodes)) continue;
    for (const raw of d.nodes) {
      const n = raw as Record<string, unknown>;
      if (typeof n.type !== "string") continue;
      out.set(n.type, {
        type: n.type,
        version: typeof n.version === "number" ? n.version : 0,
        title: typeof n.title === "string" ? n.title : n.type,
        category: typeof n.category === "string" ? n.category : null,
        description: typeof n.description === "string" ? n.description : null,
        pure: n.pure === true,
        entry: n.engine === "graph_entry",
        loopLimit: n.engine === "repeat" ? "times" : n.engine === "while" ? "max_iterations" : null,
        effects: Array.isArray(n.effects) ? n.effects.filter((x): x is string => typeof x === "string") : [],
        plugin,
        pluginVersion,
        pluginTitle,
        decl: { inputs: n.inputs, outputs: n.outputs, exits: n.exits, config: n.config },
      });
    }
  }
  return out;
}

/** 모양이 아직 없는 노드의 대체 모양 (코어 shapes._fallback과 같은 규칙) */
export function fallbackShape(node: GraphNodeValue, readOutputs: readonly string[]): NodeShape {
  return {
    inputs: Object.keys(node.in).map((name) => ({ name, type: "any", nullable: true, optional: true, required: false })),
    outputs: readOutputs.map((name) => ({ name, type: "any", nullable: true })),
    exits: node.next.map(([name]) => ({ name, kind: "ok" as const, outputs: [] })),
    unknown: true,
  };
}

/**
 * daemon 모양이 아직 없는 노드의 정적 모양 (M2 계획 2.7: 응답 전에는 노드 스키마의 정적 모양). 노드 스키마에서
 * 바로 읽을 수 없는 부분(interface에서 오는 핀, config에서 오는 출구)은 JSON 키로 채운다. 의미 검증·동적 출구의
 * 최종 모양은 daemon 응답이 정한다
 */
export function staticShape(info: NodeTypeInfo, node: GraphNodeValue, readOutputs: readonly string[]): NodeShape {
  const fallback = fallbackShape(node, readOutputs);
  const decl = info.decl;
  const pins = (v: unknown) =>
    isRecord(v) && !Object.hasOwn(v, "from_interface") ? Object.keys(v).map((k) => [k, v[k]] as const) : null;
  const inputs = pins(decl.inputs);
  const outputs = pins(decl.outputs);
  let exits: NodeShape["exits"] = fallback.exits;
  if (Array.isArray(decl.exits)) {
    exits = decl.exits
      .filter((e): e is { name: string; kind?: unknown; outputs?: unknown } => isRecord(e) && typeof e.name === "string")
      .map((e) => ({ name: e.name, kind: e.kind === "fail" ? "fail" : "ok", outputs: [] }));
  } else if (isRecord(decl.exits) && typeof decl.exits.from_config === "string") {
    const dynamic = decl.exits;
    const names = own(node.config, dynamic.from_config as string);
    const extra = Array.isArray(dynamic.extra) ? dynamic.extra : [];
    const kindOf = (k: unknown) => (k === "fail" ? ("fail" as const) : ("ok" as const));
    exits = [
      ...(Array.isArray(names) ? names.filter((n): n is string => typeof n === "string") : []).map((name) => ({
        name,
        kind: kindOf(dynamic.kind),
        outputs: [],
      })),
      ...extra
        .filter((e): e is { name: string; kind?: unknown } => isRecord(e) && typeof e.name === "string")
        .map((e) => ({ name: e.name, kind: kindOf(e.kind), outputs: [] })),
    ];
  }
  return {
    inputs:
      inputs === null
        ? fallback.inputs
        : inputs.map(([name, d]) => {
            const optional = own(d, "optional") === true;
            const hasDefault = isRecord(d) && Object.hasOwn(d, "default");
            const type = own(d, "type");
            return {
              name,
              type: typeof type === "string" ? type : "any",
              nullable: own(d, "nullable") === true,
              optional,
              required: !optional && !hasDefault,
            };
          }),
    outputs:
      outputs === null
        ? fallback.outputs
        : outputs.map(([name, d]) => {
            const type = own(d, "type");
            return { name, type: typeof type === "string" ? type : "any", nullable: own(d, "nullable") === true };
          }),
    exits,
    unknown: false,
  };
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return isObject(v);
}

function shapeOf(shapes: NodeShapes, id: string): NodeShape | undefined {
  return Object.hasOwn(shapes, id) ? shapes[id] : undefined;
}

interface Built {
  rows: NodeRow[];
  rowValues: Set<string>;
  order: string[];
}

function buildRows(
  node: GraphNodeValue,
  shape: NodeShape,
  info: NodeTypeInfo | undefined,
  hasIncoming: boolean,
  readOutputs: readonly string[],
  revealInputs: boolean,
): Built {
  const left: PinRow[] = [];
  const right: PinRow[] = [];
  const rowValues = new Set<string>();
  const known = !shape.unknown && info !== undefined;
  if (!known || hasIncoming || (!info.pure && !info.entry)) {
    left.push({ handle: EXEC_IN, kind: "exec", label: "", tone: "exec", extra: false, type: null });
  }
  const declared = new Set(shape.inputs.map((p) => p.name));
  for (const pin of shape.inputs) {
    const has = Object.hasOwn(node.in, pin.name);
    const value = has ? node.in[pin.name] : undefined;
    const linked = has && findLinks(value).length > 0;
    if (!(pin.required || linked || shape.unknown || revealInputs)) continue;
    const constant = has && !linked ? shortConstant(value) : null;
    if (constant !== null) rowValues.add(pin.name);
    left.push({
      handle: inputHandle(pin.name),
      kind: "data",
      label: constant === null ? pin.name : `${pin.name} ${constant}`,
      tone: pinTone(pin.type),
      extra: false,
      type: pin.type,
    });
  }
  for (const name of Object.keys(node.in)) {
    if (declared.has(name)) continue;
    left.push({ handle: inputHandle(name), kind: "data", label: name, tone: "other", extra: true, type: null });
  }
  const exits = new Set(shape.exits.map((e) => e.name));
  const exitRow = (name: string, fail: boolean, extra: boolean): PinRow => ({
    handle: exitHandle(name),
    kind: "exec",
    label: name,
    tone: fail ? "fail" : "exec",
    extra,
    type: null,
  });
  for (const e of shape.exits) if (e.kind === "ok") right.push(exitRow(e.name, false, false));
  for (const [name] of node.next) if (!exits.has(name)) right.push(exitRow(name, false, true));
  const outputs = new Set(shape.outputs.map((o) => o.name));
  for (const o of shape.outputs) {
    right.push({
      handle: outputHandle(o.name),
      kind: "data",
      label: o.name,
      tone: pinTone(o.type),
      extra: false,
      type: o.type,
    });
  }
  for (const name of readOutputs) {
    if (!outputs.has(name)) {
      right.push({ handle: outputHandle(name), kind: "data", label: name, tone: "other", extra: true, type: null });
    }
  }
  for (const e of shape.exits) if (e.kind === "fail") right.push(exitRow(e.name, true, false));
  const rows: NodeRow[] = [];
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    rows.push({ left: left[i] ?? null, right: right[i] ?? null });
  }
  return { rows, rowValues, order: shape.inputs.map((p) => p.name) };
}

interface NodeProblems {
  errors: Diagnostic[];
  warnings: Diagnostic[];
}

function problemsByNode(diagnostics: readonly Diagnostic[], docPath: string, ids: ReadonlySet<string>) {
  const out = new Map<string, NodeProblems>();
  for (const d of diagnostics) {
    if (!belongsTo(d, docPath)) continue;
    const id = problemNode(d, docPath, ids);
    if (id === null) continue;
    let p = out.get(id);
    if (p === undefined) out.set(id, (p = { errors: [], warnings: [] }));
    (d.severity === "error" ? p.errors : p.warnings).push(d);
  }
  return out;
}

export interface MappingInput {
  path: string;
  value: GraphValue;
  shapes: NodeShapes;
  types: TypeIndex;
  diagnostics: readonly Diagnostic[];
  view: ViewState;
}

export function toFlow({ path, value, shapes, types, diagnostics, view }: MappingInput): FlowGraph {
  const nodes = graphNodes(value);
  const ids = new Set(nodes.map((n) => n.id));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const placed = layoutPositions(value);
  for (const [id, p] of view.auto ?? []) if (!placed.has(id) && ids.has(id)) placed.set(id, p);
  const positions = autoLayout(nodes, placed);
  const problems = problemsByNode(diagnostics, path, ids);

  // 다른 노드가 읽는 출력, 흐름이 들어오는 노드
  const readOutputs = new Map<string, string[]>();
  const links = nodes.flatMap((n) =>
    Object.keys(n.in).flatMap((pin) => findLinks(n.in[pin]).map((link) => ({ from: n.id, pin, link }))),
  );
  for (const { link } of links) {
    const list = readOutputs.get(link.node) ?? [];
    if (!list.includes(link.output)) list.push(link.output);
    readOutputs.set(link.node, list);
  }
  for (const list of readOutputs.values()) list.sort();
  const incoming = new Set(nodes.flatMap((n) => n.next.map(([, to]) => to)));

  // 접힌 그룹 (보기 상태로 펼치지 않은 것)
  const groups = collapsedGroups(value, ids);
  const hiddenIn = new Map<string, string>();
  for (const g of groups) {
    if (view.expanded.has(g.id)) continue;
    for (const m of g.nodes) if (!hiddenIn.has(m)) hiddenIn.set(m, g.id);
  }
  const visibleId = (id: string) => {
    const g = hiddenIn.get(id);
    return g === undefined ? id : groupNodeId(g);
  };

  const flowNodes: KbFlowNode[] = [];
  for (const c of comments(value)) {
    const [x, y, w, h] = c.rect;
    flowNodes.push({
      id: commentNodeId(c.id),
      type: "kbComment",
      position: { x, y },
      width: w,
      height: h,
      zIndex: -1,
      selectable: false,
      draggable: false,
      deletable: false,
      data: { id: c.id, text: c.text },
    });
  }
  for (const g of groups) {
    const members = g.nodes.map((m) => problems.get(m));
    const first = g.nodes.map((m) => positions.get(m)).find((p): p is Point => p !== undefined);
    flowNodes.push({
      id: groupNodeId(g.id),
      type: "kbGroup",
      position: g.position ?? first ?? { x: 0, y: 0 },
      draggable: false,
      // 고를 수 없게 하면 React Flow가 포인터를 꺼서 펼치기 단추를 누를 수 없다. 고른 그룹은 지우기·편집 대상이 아니다
      deletable: false,
      data: {
        id: g.id,
        title: g.title,
        count: g.nodes.length,
        expanded: view.expanded.has(g.id),
        errors: members.reduce((s, p) => s + (p?.errors.length ?? 0), 0),
        warnings: members.reduce((s, p) => s + (p?.warnings.length ?? 0), 0),
      },
    });
  }
  for (const node of nodes) {
    if (hiddenIn.has(node.id)) continue;
    const info = types.get(node.type);
    const reads = readOutputs.get(node.id) ?? [];
    const shape =
      shapeOf(shapes, node.id) ??
      (info !== undefined && info.version === node.version ? staticShape(info, node, reads) : fallbackShape(node, reads));
    const unknown = shape.unknown || info === undefined;
    const built = buildRows(node, shape, info, incoming.has(node.id), reads, view.revealInputs === true);
    const p = problems.get(node.id);
    const errors = p?.errors.length ?? 0;
    const warnings = p?.warnings.length ?? 0;
    const firstProblem = p?.errors[0] ?? p?.warnings[0];
    const summary = summarize(node, built.order, built.rowValues);
    flowNodes.push({
      id: node.id,
      type: "kb",
      position: positions.get(node.id) ?? { x: 0, y: 0 },
      selected: view.selected.has(node.id),
      data: {
        id: node.id,
        type: node.type,
        title: node.title ?? info?.title ?? (node.type === "" ? node.id : node.type),
        head: errors > 0 ? "error" : warnings > 0 ? "warn" : unknown ? "neutral" : categoryInfo(info?.category).head,
        rows: built.rows,
        note:
          firstProblem !== undefined
            ? { text: firstProblem.message, tone: errors > 0 ? "error" : "warn" }
            : summary === null
              ? null
              : { text: summary, tone: "plain" },
        // 모르는 노드는 늘 그 오류(unknown_node_type)가 있으므로 표시를 앞세운다. 오류 내용은 설명 줄에 나온다
        status: unknown
          ? { text: "모르는 노드", tone: errors > 0 ? "error" : "muted" }
          : errors > 0
            ? { text: errors > 1 ? `✕ 오류 ${errors}` : "✕ 오류", tone: "error" }
            : warnings > 0
              ? { text: "⚠ 경고", tone: "warn" }
              : null,
        errors,
        warnings,
        unknown,
      },
    });
  }

  const edges: KbFlowEdge[] = [];
  const shown = (id: string) => ids.has(id);
  for (const node of nodes) {
    const shape = shapeOf(shapes, node.id);
    for (const [exit, to] of node.next) {
      if (!shown(to)) continue;
      const source = visibleId(node.id);
      const target = visibleId(to);
      if (source === target && hiddenIn.has(node.id)) continue; // 그룹 안쪽 연결
      const fail = shape?.exits.some((e) => e.name === exit && e.kind === "fail") ?? false;
      edges.push({
        id: execEdgeId(node.id, exit),
        type: "kb",
        source,
        target,
        sourceHandle: hiddenIn.has(node.id) ? GROUP_OUT : exitHandle(exit),
        targetHandle: hiddenIn.has(to) ? GROUP_IN : EXEC_IN,
        data: { kind: "exec", tone: fail ? "fail" : "exec", where: "" },
      });
    }
  }
  for (const { from, pin, link } of links) {
    const producer = byId.get(link.node);
    if (producer === undefined) continue;
    const source = visibleId(link.node);
    const target = visibleId(from);
    if (source === target && hiddenIn.has(from)) continue;
    const out = shapeOf(shapes, link.node)?.outputs.find((o) => o.name === link.output);
    const into = shapeOf(shapes, from)?.inputs.find((i) => i.name === pin);
    const tone = out !== undefined ? pinTone(out.type) : into !== undefined ? pinTone(into.type) : "other";
    edges.push({
      id: dataEdgeId(from, pin, link.path),
      type: "kb",
      source,
      target,
      sourceHandle: hiddenIn.has(link.node) ? GROUP_OUT : outputHandle(link.output),
      targetHandle: hiddenIn.has(from) ? GROUP_IN : inputHandle(pin),
      data: { kind: "data", tone, where: formatValuePath(link.path) },
    });
  }
  // 뒤로 가는 연결(도착이 출발보다 왼쪽)은 노드 위 층에 그린다. 노드 밑으로 지나가 끊겨 보이지 않게.
  // 위 층 선은 그리기 전용이다: 누르기 영역을 없애고(interactionWidth 0) 포인터를 받지 않아(BACK_EDGE_CLASS)
  // 겹친 노드 누르기를 가로채지 않는다
  const at = new Map(flowNodes.map((n) => [n.id, n.position]));
  for (const e of edges) {
    const s = at.get(e.source);
    const t = at.get(e.target);
    if (s !== undefined && t !== undefined && t.x <= s.x) {
      e.zIndex = BACK_EDGE_Z;
      e.interactionWidth = 0;
      e.className = BACK_EDGE_CLASS;
    }
  }
  return { nodes: flowNodes, edges, hiddenIn };
}
