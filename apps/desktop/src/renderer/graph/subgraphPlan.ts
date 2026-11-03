// 서브그래프 호출 노드 → 열 탭 정하기 (다듬기 P1-B, 사용자 요청 ⑧). 순수 함수라 vitest로 본다. 여는 동작은 openSubgraph.ts
import type { TreeEntry } from "../explorer/tree";
import type { EditorTab } from "../store/tabs";
import { graphNodes, own, type GraphValue } from "./model";

export const GRAPH_CALL_TYPE = "core.graph.call";
const GRAPH_SUFFIX = ".graph.json";

/** 그 노드가 서브그래프 호출이면 config.graph (문자열이 아니면 ""), 호출 노드가 아니면 null */
export function callTargetOf(value: GraphValue | null, nodeId: string): string | null {
  if (value === null) return null;
  const node = graphNodes(value).find((n) => n.id === nodeId);
  if (node === undefined || node.type !== GRAPH_CALL_TYPE) return null;
  const graph = own(node.config, "graph");
  return typeof graph === "string" ? graph : "";
}

export type SubgraphFailure = "empty" | "bad_path" | "not_graph" | "missing";

export type SubgraphPlan =
  | { ok: false; reason: SubgraphFailure; target: string }
  /** 탐색기 목록에 있는 그래프: 바로 연다 */
  | { ok: true; open: "tab"; path: string; graphKind: TreeEntry["graph_kind"] | null }
  /** 목록 밖(감시 폴더 밖·실행 스냅샷): 읽어 본 뒤 연다 */
  | { ok: true; open: "probe"; path: string; snapshot: { runId: string; shortId: string } | null };

/** 실행 스냅샷 그래프 경로 `runs/<실행 폴더>/snapshot/<그래프>`의 앞부분 (스냅샷이 아니면 null) */
export function snapshotRoot(path: string): string | null {
  const parts = path.split("/");
  return parts.length > 3 && parts[0] === "runs" && parts[2] === "snapshot" ? parts.slice(0, 3).join("/") : null;
}

/** 스냅샷 탭 제목 "<그래프> · #<실행>"에서 실행 짧은 번호 */
function shortIdOf(title: string, runId: string): string {
  const at = title.lastIndexOf(" · #");
  return at >= 0 ? title.slice(at + 4) : runId.slice(0, 4);
}

/** 워크스페이스 루트 기준 '/' 경로인가 (daemon resolve_path와 같은 모양 규칙) */
function validPath(target: string): boolean {
  if (target.includes("\\") || target.startsWith("/") || target.includes(":") || target.includes("\0")) return false;
  return target.split("/").every((p) => p !== "" && p !== "." && p !== "..");
}

/** 어디를 어떻게 열지 정한다. from = 호출 노드가 있는 탭 */
export function planSubgraph(
  target: string,
  from: Pick<EditorTab, "path" | "title" | "runId" | "snapshot">,
  entries: readonly TreeEntry[],
): SubgraphPlan {
  if (target.trim() === "") return { ok: false, reason: "empty", target };
  if (!validPath(target)) return { ok: false, reason: "bad_path", target };
  if (!target.toLowerCase().endsWith(GRAPH_SUFFIX)) return { ok: false, reason: "not_graph", target };
  const root = from.snapshot === true ? snapshotRoot(from.path) : null;
  if (root !== null && from.runId !== undefined) {
    return {
      ok: true,
      open: "probe",
      path: `${root}/${target}`,
      snapshot: { runId: from.runId, shortId: shortIdOf(from.title, from.runId) },
    };
  }
  // Windows 경로는 대소문자를 가리지 않는다: 목록의 실제 이름으로 연다 (같은 파일을 두 탭으로 열지 않게)
  const lower = target.toLowerCase();
  const entry =
    entries.find((e) => e.type === "file" && e.path === target) ??
    entries.find((e) => e.type === "file" && e.path.toLowerCase() === lower);
  if (entry !== undefined) {
    if (entry.kind !== "graph") return { ok: false, reason: "not_graph", target };
    return { ok: true, open: "tab", path: entry.path, graphKind: entry.graph_kind ?? null };
  }
  return { ok: true, open: "probe", path: target, snapshot: null };
}

export const FAILURE_TEXT: Record<SubgraphFailure, string> = {
  empty: "호출할 서브그래프 경로(config.graph)가 비어 있어요.",
  bad_path: "서브그래프 경로가 틀렸어요. 워크스페이스 루트 기준 '/' 경로여야 해요.",
  not_graph: "그래프 파일(*.graph.json)이 아니에요.",
  missing: "서브그래프 파일이 없어요.",
};
