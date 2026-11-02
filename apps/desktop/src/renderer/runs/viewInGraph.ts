// "그래프에서 보기" (M3 계획 2.10): 실행 스냅샷 그래프를 읽기 전용 탭으로 열어 그 노드로 옮긴다. 서브그래프 안
// 스텝이면 그 서브그래프 스냅샷이다. 워크스페이스 그래프가 스냅샷과 같으면(같은 값) 워크스페이스 그래프를 연다.
// "같다"는 사용자가 실제로 보게 될 값으로 본다: 그 그래프 탭이 열려 있으면 편집 버퍼(저장 안 된 편집 포함), 아니면
// 디스크 파일. 그래서 실패 노드를 지우고 저장하지 않은 버퍼로 가지 않는다 (버퍼는 건드리지 않는다)
import { jsonEqual } from "../graph/valueOps";
import { client } from "../rpc/client";
import { getDoc, requestFocus } from "../store/documents";
import { openSnapshotTab, openTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";

export function snapshotPath(runDir: string, graph: string): string {
  return `${runDir}/snapshot/${graph}`;
}

async function readValue(path: string): Promise<{ ok: true; value: unknown } | { ok: false }> {
  const call = client().call;
  try {
    const r = await call("graph.open", { path });
    void call("graph.close", { doc_id: r.doc_id }).catch(() => {});
    return { ok: true, value: r.value };
  } catch {
    return { ok: false };
  }
}

/** 워크스페이스 그래프(열린 버퍼, 없으면 디스크)가 스냅샷과 같은 값인가 (읽지 못하면 다르다고 본다) */
export async function sameAsSnapshot(snapshot: string, graph: string): Promise<boolean> {
  const open = getDoc(graph);
  const buffer = open !== undefined && open.status === "ready" && open.value !== null ? open.value : null;
  const [snap, disk] = await Promise.all([readValue(snapshot), buffer === null ? readValue(graph) : Promise.resolve(null)]);
  if (!snap.ok) return false;
  // 기다리는 동안 탭이 열렸거나 편집됐을 수 있다: 지금 버퍼로 다시 본다
  const now = getDoc(graph);
  if (now !== undefined && now.status === "ready" && now.value !== null) return jsonEqual(snap.value, now.value);
  if (disk === null || !disk.ok) return false;
  return jsonEqual(snap.value, disk.value);
}

/** 그 실행의 그 그래프·노드로 간다. 연 탭 경로를 돌려준다 */
export async function viewInGraph(run: { runId: string; runDir: string; shortId: string }, graph: string, node: string): Promise<string> {
  const snapshot = snapshotPath(run.runDir, graph);
  if (await sameAsSnapshot(snapshot, graph)) {
    const entry = useWorkspace.getState().entries.find((e) => e.path === graph);
    openTab({ path: graph, kind: "graph", graphKind: entry?.graph_kind ?? null });
    requestFocus(graph, { node });
    return graph;
  }
  openSnapshotTab(snapshot, run.runId, run.shortId);
  requestFocus(snapshot, { node });
  return snapshot;
}
