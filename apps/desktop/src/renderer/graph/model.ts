// 그래프 값 읽기 (M2 계획 2.6·2.7). 렌더러는 값(JSON 트리)을 그대로 들고, 이 파일은 읽기만 한다.
// 값은 편집 중이라 형식이 틀릴 수 있다: 틀린 자리는 없는 것으로 보고 던지지 않는다.
// 키 읽기는 Object.hasOwn·Object.keys만 쓴다 (`__proto__`·`constructor`도 보통 키다)
import type { daemonRpc } from "@kookabug/schema";

export type GraphValue = { [key: string]: unknown };
export type Diagnostic = daemonRpc.Diagnostic;
export type NodeShape = daemonRpc.NodeShape;
export type NodeShapes = daemonRpc.NodeShapes;
export type PinShape = daemonRpc.PinShape;
export type ExitShape = daemonRpc.ExitShape;
export type OutputShape = daemonRpc.OutputShape;

export type JsonObject = { [key: string]: unknown };

export function isObject(v: unknown): v is JsonObject {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** 자기 속성만 읽는다 (프로토타입 쪽 이름을 값으로 보지 않는다) */
export function own(obj: unknown, key: string): unknown {
  return isObject(obj) && Object.hasOwn(obj, key) ? obj[key] : undefined;
}

function objectAt(obj: unknown, key: string): JsonObject {
  const v = own(obj, key);
  return isObject(v) ? v : {};
}

export interface GraphNodeValue {
  id: string;
  type: string;
  version: number | null;
  title: string | null;
  in: JsonObject;
  config: JsonObject;
  /** 출구 이름 → 다음 노드 ID (문자열만) */
  next: [string, string][];
  raw: JsonObject;
}

/** `nodes`의 객체 항목. 객체가 아닌 항목은 노드로 보지 않는다 */
export function graphNodes(value: GraphValue): GraphNodeValue[] {
  const nodes = objectAt(value, "nodes");
  const out: GraphNodeValue[] = [];
  for (const id of Object.keys(nodes)) {
    const raw = nodes[id];
    if (!isObject(raw)) continue;
    const type = own(raw, "type");
    const version = own(raw, "version");
    const title = own(raw, "title");
    const next = objectAt(raw, "next");
    out.push({
      id,
      type: typeof type === "string" ? type : "",
      version: typeof version === "number" ? version : null,
      title: typeof title === "string" && title !== "" ? title : null,
      in: objectAt(raw, "in"),
      config: objectAt(raw, "config"),
      next: Object.keys(next)
        .filter((exit) => typeof next[exit] === "string")
        .map((exit) => [exit, next[exit] as string]),
      raw,
    });
  }
  return out;
}

export interface Point {
  x: number;
  y: number;
}

function pointOf(v: unknown): Point | null {
  const x = own(v, "x");
  const y = own(v, "y");
  return typeof x === "number" && Number.isFinite(x) && typeof y === "number" && Number.isFinite(y) ? { x, y } : null;
}

/** `layout.nodes`의 좌표. 좌표가 없거나 틀린 노드는 빠진다 (보기용 자동 배치 대상) */
export function layoutPositions(value: GraphValue): Map<string, Point> {
  const nodes = objectAt(objectAt(value, "layout"), "nodes");
  const out = new Map<string, Point>();
  for (const id of Object.keys(nodes)) {
    const p = pointOf(nodes[id]);
    if (p !== null) out.set(id, p);
  }
  return out;
}

export interface CollapsedGroup {
  id: string;
  title: string;
  /** 있는 노드만 (없는 ID는 무시) */
  nodes: string[];
  position: Point | null;
}

export function collapsedGroups(value: GraphValue, nodeIds: ReadonlySet<string>): CollapsedGroup[] {
  const groups = objectAt(objectAt(value, "layout"), "collapsed");
  const out: CollapsedGroup[] = [];
  for (const id of Object.keys(groups)) {
    const raw = groups[id];
    if (!isObject(raw)) continue;
    const members = own(raw, "nodes");
    const title = own(raw, "title");
    out.push({
      id,
      title: typeof title === "string" && title !== "" ? title : id,
      nodes: Array.isArray(members)
        ? [...new Set(members.filter((m): m is string => typeof m === "string" && nodeIds.has(m)))]
        : [],
      position: pointOf(raw),
    });
  }
  return out;
}

export interface CommentValue {
  id: string;
  text: string;
  rect: [number, number, number, number];
}

export function comments(value: GraphValue): CommentValue[] {
  const all = objectAt(objectAt(value, "layout"), "comments");
  const out: CommentValue[] = [];
  for (const id of Object.keys(all)) {
    const raw = all[id];
    const rect = own(raw, "rect");
    const text = own(raw, "text");
    if (
      !Array.isArray(rect) ||
      rect.length !== 4 ||
      !rect.every((n) => typeof n === "number" && Number.isFinite(n))
    ) {
      continue;
    }
    out.push({ id, text: typeof text === "string" ? text : "", rect: rect as [number, number, number, number] });
  }
  return out;
}

/** 핀 값 안의 위치: 객체 키 또는 배열 원소 번호 */
export type ValuePath = (string | number)[];

export interface LinkRef {
  /** 핀 값 안에서의 위치. 핀 값 자체가 `$link`면 빈 배열 */
  path: ValuePath;
  node: string;
  output: string;
}

/**
 * 핀 값 안의 `$link`. 코어 `shapes._links`와 같은 규칙이다: 키 하나짜리 `{"$link": "노드.출력"}`이 연결이고,
 * `$literal` 키가 있는 객체 안은 보지 않는다. 문자열에 점이 없으면 연결이 아니다(검증 오류로 나온다)
 */
export function findLinks(value: unknown, path: ValuePath = []): LinkRef[] {
  if (Array.isArray(value)) return value.flatMap((item, i) => findLinks(item, [...path, i]));
  if (!isObject(value)) return [];
  const keys = Object.keys(value);
  if (keys.length === 1 && keys[0] === "$link") {
    const ref = value.$link;
    if (typeof ref !== "string") return [];
    const dot = ref.indexOf(".");
    return dot < 0 ? [] : [{ path, node: ref.slice(0, dot), output: ref.slice(dot + 1) }];
  }
  if (Object.hasOwn(value, "$literal")) return [];
  return keys.flatMap((k) => findLinks(value[k], [...path, k]));
}

/** 연결선 위에 쓸 원소 위치 (`[0]`, `.error`) */
export function formatValuePath(path: ValuePath): string {
  return path.map((p) => (typeof p === "number" ? `[${p}]` : `.${p}`)).join("");
}

/** 특수 값 하나짜리 객체의 태그 (`$target` 등). 아니면 null */
export function specialTag(value: unknown): string | null {
  if (!isObject(value)) return null;
  const keys = Object.keys(value);
  return keys.length === 1 && keys[0].startsWith("$") ? keys[0] : null;
}

/** JSON pointer 조각 → 문자열 배열 (`~1`·`~0` 풀기). 형식이 틀리면 null */
export function parsePointer(pointer: string): string[] | null {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) return null;
  return pointer
    .slice(1)
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
}
