// 서브그래프 호출 노드에서 그 서브그래프 탭으로 가기 (다듬기 P1-B, 사용자 요청 ⑧). 캔버스 노드 더블클릭과 속성 편집기
// "서브그래프 열기"가 쓴다. config.graph는 워크스페이스 루트 기준 경로다(로더와 같다). 열 곳은 subgraphPlan.ts가 정한다.
// - 워크스페이스 그래프 탭: 이미 열려 있으면 그 탭으로 간다. 탐색기 목록에 있으면 그 종류(SUB·TEST)로 열고, 목록 밖이면
//   daemon에서 읽어 본 뒤 연다. 실행 중·멈춤 중에도 같다 — 강조(멈춘 노드 노란 테두리 등)는 탭 경로로 정해진다
// - 실행 스냅샷 탭(읽기 전용)에서는 같은 실행 스냅샷 안의 서브그래프를 스냅샷 탭으로 연다
// - 경로가 비었거나 틀렸거나 파일이 없으면 대화 상자로 알린다
import { client, toRpcError } from "../rpc/client";
import { ask } from "../store/dialog";
import { getDoc } from "../store/documents";
import { activateTab, openSnapshotTab, openTab, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { own } from "./model";
import { FAILURE_TEXT, planSubgraph } from "./subgraphPlan";

async function notify(message: string, target: string): Promise<void> {
  await ask({
    title: "서브그래프를 열 수 없어요",
    message: target === "" ? message : `${message} (${target})`,
    buttons: [{ label: "확인", value: "ok", primary: true }],
    cancelValue: "ok",
  });
}

/** 그래프 파일을 읽어 본다 (열린 문서면 읽지 않는다). 그래프 kind 또는 실패 이유 */
async function probe(path: string): Promise<{ ok: true; kind: unknown } | { ok: false; message: string }> {
  const open = getDoc(path);
  if (open !== undefined && open.value !== null) return { ok: true, kind: own(open.value, "kind") };
  const call = client().call;
  try {
    const r = await call("graph.open", { path });
    void call("graph.close", { doc_id: r.doc_id }).catch(() => {});
    return { ok: true, kind: own(r.value, "kind") };
  } catch (err) {
    const e = toRpcError(err);
    return { ok: false, message: e.kind === "not_found" ? FAILURE_TEXT.missing : `서브그래프를 읽지 못했어요: ${e.message}` };
  }
}

/**
 * 호출 노드가 있는 탭(fromPath)에서 config.graph 서브그래프 탭으로 간다. 열었으면 그 탭 경로, 못 열었으면(알림을 띄움)
 * null
 */
export async function openSubgraph(fromPath: string, target: string): Promise<string | null> {
  const from = useTabs.getState().tabs.find((t) => t.path === fromPath) ?? { path: fromPath, title: fromPath };
  const plan = planSubgraph(target, from, useWorkspace.getState().entries);
  if (!plan.ok) {
    await notify(FAILURE_TEXT[plan.reason], plan.target);
    return null;
  }
  if (plan.open === "tab") {
    openTab({ path: plan.path, kind: "graph", graphKind: plan.graphKind });
    return plan.path;
  }
  // 이미 열린 탭이면 읽지 않고 그 탭으로 간다
  if (useTabs.getState().tabs.some((t) => t.path === plan.path)) {
    activateTab(plan.path);
    return plan.path;
  }
  const found = await probe(plan.path);
  if (!found.ok) {
    await notify(found.message, target);
    return null;
  }
  if (plan.snapshot !== null) {
    openSnapshotTab(plan.path, plan.snapshot.runId, plan.snapshot.shortId);
  } else {
    const kind = found.kind === "subgraph" || found.kind === "test" ? found.kind : null;
    openTab({ path: plan.path, kind: "graph", graphKind: kind });
  }
  return plan.path;
}
