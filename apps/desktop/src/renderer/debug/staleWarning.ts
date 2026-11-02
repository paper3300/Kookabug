// 재개 경고 (M3 계획 2.9 "재개 경고", 2.4 스텝 입력 검사). 경계에서 멈춘 노드의 입력이 관측 노드(capture
// 효과) 출력에서 오면, 재개하면 세대가 올라 그 값은 멈추기 전 화면 값이 되어 runner가 stale_observation으로
// 실패시킨다. 그걸 미리 알리는 안내다. 판정은 그래프 모양으로 대충 하고 실제 판정은 runner가 한다
// - 순수 노드는 따라 올라간다 (OCR 글자 → logic.compare → branch)
// - 예외는 runner와 같다: 옮기기·기록용 코어 노드(STALE_EXEMPT), input 효과 노드가 받은 Match(입력 서비스가
//   target으로 다시 찾는다)
// - 한계: 서브그래프 입력(graph.entry 출력)·변수(var.get)로 들어온 관측값은 보지 않는다
import type { NodeTypeInfo, TypeIndex } from "../graph/mapping";
import { findLinks, graphNodes, isObject, type GraphNodeValue, type GraphValue } from "../graph/model";

/** runner engine/provenance.py STALE_EXEMPT와 같은 목록 */
export const STALE_EXEMPT: ReadonlySet<string> = new Set([
  "core.log.message",
  "core.var.set",
  "core.graph.call",
  "core.graph.exit",
  "core.test.pass",
  "core.test.skip",
  "core.test.fail",
]);

export interface StaleSource {
  /** 경고가 걸린 입력 핀 */
  pin: string;
  /** 관측 노드 ID와 그 출력 */
  node: string;
  output: string;
}

function pinType(info: NodeTypeInfo | undefined, pin: string): string {
  const inputs = info?.decl.inputs;
  if (!isObject(inputs)) return "";
  const spec = inputs[pin];
  return isObject(spec) && typeof spec.type === "string" ? spec.type : "";
}

/**
 * 멈춘 노드의 입력 중 재개하면 오래된 관측값이 되는 것. 없으면 빈 배열. 핀 이름 순서
 */
export function staleInputs(value: GraphValue, nodeId: string, types: TypeIndex): StaleSource[] {
  const nodes = new Map(graphNodes(value).map((n) => [n.id, n]));
  const node = nodes.get(nodeId);
  if (node === undefined || STALE_EXEMPT.has(node.type)) return [];
  const info = types.get(node.type);
  const inputEffect = info?.effects.includes("input") === true;

  // 값이 어느 관측 노드 출력에서 오는가 (순수 노드를 따라 올라간다). 처음 만난 관측 출처 하나
  const memo = new Map<string, { node: string; output: string } | null>();
  const observed = (from: GraphNodeValue, output: string, seen: Set<string>): { node: string; output: string } | null => {
    const fromInfo = types.get(from.type);
    if (fromInfo?.effects.includes("capture") === true) return { node: from.id, output };
    if (fromInfo?.pure !== true || seen.has(from.id)) return null;
    if (memo.has(from.id)) return memo.get(from.id)!;
    seen.add(from.id);
    let found: { node: string; output: string } | null = null;
    for (const pin of Object.keys(from.in).sort()) {
      for (const link of findLinks(from.in[pin])) {
        const src = nodes.get(link.node);
        if (src === undefined) continue;
        found = observed(src, outputName(link.output), seen);
        if (found !== null) break;
      }
      if (found !== null) break;
    }
    memo.set(from.id, found);
    return found;
  };

  const out: StaleSource[] = [];
  for (const pin of Object.keys(node.in).sort()) {
    // input 효과 노드의 Match 입력은 입력 서비스가 다시 찾는다
    if (inputEffect && /\bmatch\b/.test(pinType(info, pin))) continue;
    for (const link of findLinks(node.in[pin])) {
      const src = nodes.get(link.node);
      if (src === undefined) continue;
      const hit = observed(src, outputName(link.output), new Set());
      if (hit !== null) {
        out.push({ pin, ...hit });
        break;
      }
    }
  }
  return out;
}

/** `$link`의 출력 부분에서 핀 이름 (`match.point` → `match`, `items[0]` → `items`) */
function outputName(ref: string): string {
  const m = /^[^.[]+/.exec(ref);
  return m === null ? ref : m[0];
}

/** 멈춤 띠 문구 */
export function staleWarningText(nodeTitle: string, sources: readonly StaleSource[], titleOf: (id: string) => string): string {
  const outputs = sources.map((s) => `${titleOf(s.node)}.${s.output}`).join(", ");
  return `재개하면 '${nodeTitle}'는 멈추기 전 화면 값(${outputs})을 쓸 수 없어 실패합니다`;
}
