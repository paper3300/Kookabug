// 연결 만들기·지우기 (M2 계획 2.6, T9). 흐름 = 출구 하나에 다음 노드 하나(`next`), 데이터 = 입력 핀 하나에
// `$link` 하나(`in`). 새 연결은 그 자리의 앞 연결을 바꾼다
import { EXEC_IN } from "../mapping";
import { isObject, own, type GraphValue, type ValuePath } from "../model";

type ValuePathKey = ValuePath[number];
import { deleteIn, setIn } from "../valueOps";

export interface Connection {
  source: string;
  sourceHandle: string | null | undefined;
  target: string;
  targetHandle: string | null | undefined;
}

export type EdgeRef =
  | { kind: "exec"; node: string; exit: string }
  | { kind: "data"; node: string; pin: string; path: ValuePathKey[] };

/** 연결선 ID(mapping.execEdgeId·dataEdgeId) → 값 안 자리. 형식이 틀리면 null */
export function parseEdgeId(id: string): EdgeRef | null {
  const kind = id.slice(0, 2);
  if (kind !== "x:" && kind !== "d:") return null;
  let parts: unknown;
  try {
    parts = JSON.parse(id.slice(2));
  } catch {
    return null;
  }
  if (!Array.isArray(parts)) return null;
  if (kind === "x:") {
    const [node, exit] = parts as unknown[];
    return parts.length === 2 && typeof node === "string" && typeof exit === "string"
      ? { kind: "exec", node, exit }
      : null;
  }
  const [node, pin, ...path] = parts as unknown[];
  if (typeof node !== "string" || typeof pin !== "string") return null;
  if (!path.every((p) => typeof p === "string" || typeof p === "number")) return null;
  return { kind: "data", node, pin, path: path as ValuePathKey[] };
}

function nodeExists(value: GraphValue, id: string): boolean {
  return isObject(own(own(value, "nodes"), id));
}

/** 흐름 연결: from의 출구 exit → to. 같은 출구의 앞 연결은 바뀐다 */
export function connectExec(value: GraphValue, from: string, exit: string, to: string): GraphValue {
  if (!nodeExists(value, from) || !nodeExists(value, to)) return value;
  return setIn(value, ["nodes", from, "next", exit], to);
}

/** 데이터 연결: to의 입력 pin ← from의 출력 output. 핀 값 전체가 `$link` 하나로 바뀐다 */
export function connectData(value: GraphValue, from: string, output: string, to: string, pin: string): GraphValue {
  if (!nodeExists(value, from) || !nodeExists(value, to)) return value;
  return setIn(value, ["nodes", to, "in", pin], { $link: `${from}.${output}` });
}

/** React Flow 연결(손잡이 ID) → 값. 흐름 출구 → 흐름 입력, 출력 → 입력만 받는다 */
export function connect(value: GraphValue, c: Connection): GraphValue {
  const s = c.sourceHandle ?? "";
  const t = c.targetHandle ?? "";
  if (s.startsWith("x:") && t === EXEC_IN) return connectExec(value, c.source, s.slice(2), c.target);
  if (s.startsWith("o:") && t.startsWith("i:")) return connectData(value, c.source, s.slice(2), c.target, t.slice(2));
  return value;
}

/**
 * 연결 하나를 지운다. 흐름은 그 출구 키만, 데이터는 그 핀 키 전체를 지운다(배열·객체 안쪽 `$link`도 원소를
 * null로 두지 않고 그 핀을 지운다. 노드 지우기 규칙과 같다). 비게 된 `next`·`in`은 함께 지운다
 */
export function disconnect(value: GraphValue, edge: EdgeRef): GraphValue {
  if (edge.kind === "exec") return deleteIn(value, ["nodes", edge.node, "next", edge.exit], 1);
  return deleteIn(value, ["nodes", edge.node, "in", edge.pin], 1);
}
