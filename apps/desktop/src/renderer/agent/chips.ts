// 입력창 @칩 (M5 계획 3.10): `@run #N` → 실행 폴더 경로 글자, `@node` → 그래프 경로·노드 ID 글자.
// 에이전트는 이 글자를 보고 kb_run_status·kb_graph_get 등으로 읽는다 (내용을 직접 싣지 않는다 — 비밀값 가림은 daemon)
import { getDoc } from "../store/documents";
import { shortIdOf } from "../runs/open";
import type { Chip } from "./agentStore";

export function runChip(runId: string): Chip {
  const short = shortIdOf(runId);
  return {
    kind: "run",
    label: `@run #${short}`,
    text: `[첨부: 실행 기록 #${short} — 실행 ID ${runId}, 실행 폴더 runs/${runId}]`,
  };
}

export function nodeChip(graph: string, node: string): Chip {
  const value = getDoc(graph)?.value as { nodes?: Record<string, { title?: unknown }> } | null | undefined;
  const title = value?.nodes?.[node]?.title;
  const name = typeof title === "string" && title !== "" ? title : node;
  return {
    kind: "node",
    label: `@node ${name}`,
    text: `[첨부: 그래프 ${graph}의 노드 ${node}${name !== node ? ` (${name})` : ""}]`,
  };
}
