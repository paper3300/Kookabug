// 고른 노드 → 속성 편집기 항목 (M2 계획 2.7·2.11, T10). 핀 목록은 daemon 모양(동적 출구·interface 핀을 푼 결과)이
// 먼저고, 응답 전이면 노드 스키마의 정적 모양이다(캔버스와 같은 규칙). 모양에 없는 enum·min/max·기본값·설명은 노드
// 스키마 선언에서 채운다. config는 노드 스키마 config 선언으로 그린다
import { fallbackShape, staticShape, type NodeTypeInfo, type TypeIndex } from "../graph/mapping";
import {
  isObject,
  own,
  parsePointer,
  type Diagnostic,
  type GraphNodeValue,
  type NodeShape,
  type NodeShapes,
} from "../graph/model";
import { belongsTo } from "../problems/locate";
import type { FieldSpec } from "./fields";

export interface FieldDiagnostics {
  node: Diagnostic[];
  in: Map<string, Diagnostic[]>;
  config: Map<string, Diagnostic[]>;
}

export interface NodeInspector {
  node: GraphNodeValue;
  info: NodeTypeInfo | undefined;
  /** 레지스트리에 없는 타입·판, 또는 daemon이 대체 모양을 준 노드: in·config를 JSON 상자로 고친다 */
  unknown: boolean;
  /** 제목이 없을 때 보이는 이름 (노드 스키마 제목) */
  defaultTitle: string;
  inputs: FieldSpec[];
  /** in에 있지만 모양에 없는 키 (선언에 없는 입력) */
  extraInputs: string[];
  config: FieldSpec[];
  extraConfig: string[];
  diagnostics: FieldDiagnostics;
}

function num(v: unknown): number | undefined {
  return typeof v === "number" ? v : undefined;
}

/** 선언(InputPin·ConfigDecl)의 값 검사 항목. 모양에 같은 항목이 있으면 모양이 이긴다 */
function specFrom(name: string, decl: unknown, shape?: Partial<FieldSpec> & { optional?: boolean }): FieldSpec {
  const type = shape?.type ?? own(decl, "type");
  const hasDefault = isObject(decl) && Object.hasOwn(decl, "default");
  const enumValues = shape?.enum ?? own(decl, "enum");
  const description = shape?.description ?? own(decl, "description");
  const spec: FieldSpec = {
    name,
    type: typeof type === "string" ? type : "any",
    required: shape?.required ?? (!hasDefault && own(decl, "optional") !== true),
  };
  if (Array.isArray(enumValues) && enumValues.length > 0) spec.enum = enumValues;
  const minimum = shape?.minimum ?? num(own(decl, "minimum"));
  const maximum = shape?.maximum ?? num(own(decl, "maximum"));
  if (minimum !== undefined) spec.minimum = minimum;
  if (maximum !== undefined) spec.maximum = maximum;
  if (shape !== undefined && Object.hasOwn(shape, "default")) spec.default = shape.default;
  else if (hasDefault) spec.default = (decl as { default: unknown }).default;
  if (typeof description === "string" && description !== "") spec.description = description;
  return spec;
}

function declMap(v: unknown): Record<string, unknown> | null {
  return isObject(v) && !Object.hasOwn(v, "from_interface") ? v : null;
}

function groupDiagnostics(diagnostics: readonly Diagnostic[], docPath: string, id: string): FieldDiagnostics {
  const out: FieldDiagnostics = { node: [], in: new Map(), config: new Map() };
  const push = (m: Map<string, Diagnostic[]>, k: string, d: Diagnostic) => m.set(k, [...(m.get(k) ?? []), d]);
  for (const d of diagnostics) {
    if (!belongsTo(d, docPath)) continue;
    const parts = typeof d.pointer === "string" ? parsePointer(d.pointer) : null;
    const mine = parts !== null && parts[0] === "nodes" && parts[1] === id;
    if (!mine && d.node !== id) continue;
    if (mine && (parts[2] === "in" || parts[2] === "config") && parts[3] !== undefined) {
      push(out[parts[2]], parts[3], d);
    } else {
      out.node.push(d);
    }
  }
  return out;
}

export function inspectNode(
  node: GraphNodeValue,
  shapes: NodeShapes,
  types: TypeIndex,
  diagnostics: readonly Diagnostic[],
  docPath: string,
): NodeInspector {
  const info = types.get(node.type);
  const known = info !== undefined && info.version === node.version;
  const shape: NodeShape =
    (Object.hasOwn(shapes, node.id) ? shapes[node.id] : undefined) ??
    (known ? staticShape(info, node, []) : fallbackShape(node, []));
  const unknown = shape.unknown || !known;
  const declInputs = known ? declMap(info.decl.inputs) : null;
  const inputs = unknown
    ? []
    : shape.inputs.map((p) => specFrom(p.name, declInputs !== null ? own(declInputs, p.name) : undefined, p));
  const declConfig = known ? declMap(info.decl.config) : null;
  const config = unknown || declConfig === null ? [] : Object.keys(declConfig).map((k) => specFrom(k, declConfig[k]));
  const inputNames = new Set(inputs.map((p) => p.name));
  const configNames = new Set(config.map((p) => p.name));
  return {
    node,
    info,
    unknown,
    defaultTitle: info?.title ?? (node.type === "" ? node.id : node.type),
    inputs,
    extraInputs: unknown ? [] : Object.keys(node.in).filter((k) => !inputNames.has(k)),
    config,
    extraConfig: unknown ? [] : Object.keys(node.config).filter((k) => !configNames.has(k)),
    diagnostics: groupDiagnostics(diagnostics, docPath, node.id),
  };
}
