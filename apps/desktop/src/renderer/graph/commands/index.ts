// 편집 명령 (M2 계획 2.6, T9). 명령은 값 → 새 값 순수 함수이고, 실행 취소 단위는 명령 하나다(history.ts)
import type { GraphValue } from "../model";
import { disconnect, parseEdgeId } from "./edges";
import { deleteNodes } from "./nodes";

export { connect, connectData, connectExec, disconnect, parseEdgeId, type Connection, type EdgeRef } from "./edges";
export { addNode, deleteNodes, moveNodes, roundCoord, type Move, type NewNode } from "./nodes";
export {
  clearNodeValue,
  graphFocus,
  nodeFocus,
  replaceNodeObject,
  setGraphFocus,
  setNodeFocus,
  setNodeTitle,
  setNodeValue,
  type NodeField,
} from "./setPin";

/**
 * 고른 것 지우기 (명령 하나): 연결선을 먼저 끊고 노드를 지운다. 지우는 노드에 닿은 연결은 노드 지우기가
 * 정리한다
 */
export function deleteSelection(value: GraphValue, nodeIds: readonly string[], edgeIds: readonly string[]): GraphValue {
  let out = value;
  for (const id of edgeIds) {
    const edge = parseEdgeId(id);
    if (edge !== null) out = disconnect(out, edge);
  }
  return deleteNodes(out, nodeIds);
}
