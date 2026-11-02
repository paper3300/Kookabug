// "에디터에서 재현" (M3 계획 2.10, 사용자 결정 U11): 워크스페이스 테스트 그래프를 열고, 실패 노드(그 노드 ID가 지금
// 파일에 있으면, 서브그래프 안이면 그 서브그래프 파일)에 브레이크포인트를 걸고, 프로필을 그 실행 것으로 고른다.
// **실행은 사용자가 F5로 한다** — 게임 입력이 나가는 동작을 단추 하나에 숨기지 않는다.
// 스냅샷과 지금 파일(열린 버퍼, 없으면 디스크)이 다르면 열기 전에 "그래프가 실행 때와 다릅니다"를 묻는다
import { breakpointModel, hasBreakpoint, normalize } from "../debug/breakpoints";
import { graphNodes, type GraphValue } from "../graph/model";
import { client } from "../rpc/client";
import { runModel } from "../run/runStore";
import { ask } from "../store/dialog";
import { getDoc, requestFocus } from "../store/documents";
import { openTab } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import type { RunViewState, StepNode } from "./runIndexStore";
import { findStep } from "./runIndexStore";
import { sameAsSnapshot, snapshotPath } from "./viewInGraph";

export interface ReproducePlan {
  /** 열 테스트 그래프 (워크스페이스 기준) */
  test: string;
  /** 브레이크포인트를 걸 실패 노드 (실패가 없으면 null) */
  failure: { graph: string; node: string } | null;
  /** 테스트 그래프 안에서 보이게 할 노드: 실패 노드, 서브그래프 안이면 그 호출 노드 */
  focus: string | null;
  /** 그 실행의 프로필 (null = 기본) */
  profile: string | null;
  /** 스냅샷과 비교할 그래프 (테스트·실패 노드가 든 그래프) */
  graphs: string[];
}

export type ReproduceResult =
  | {
      ok: true;
      /** daemon이 저장을 확인했다 */
      breakpoint: boolean;
      /** 걸려고 했지만 저장이 실패했다 */
      breakpointFailed: boolean;
      profile: string | null;
      profileMissing: string | null;
      changed: boolean;
      nodeMissing: boolean;
    }
  | { ok: false; reason: "canceled" | "no_graph"; message?: string };

/** 실패 사슬에서 재현할 자리를 정한다 (색인만 본다) */
export function planReproduce(view: RunViewState): ReproducePlan | null {
  const index = view.index;
  const test = typeof index?.run?.graph === "string" ? index.run.graph : null;
  if (index === null || test === null) return null;
  const chain = index.failure_chain.map((id) => findStep(view, id)).filter((s): s is StepNode => s !== null);
  const last = chain.at(-1) ?? null;
  const inTest = [...chain].reverse().find((s) => s.graph === test) ?? null;
  const conditions = index.run?.conditions as { profile?: unknown } | undefined;
  const profile = typeof conditions?.profile === "string" ? conditions.profile : null;
  const failure = last === null ? null : { graph: last.graph, node: last.node };
  return {
    test,
    failure,
    focus: inTest?.node ?? null,
    profile,
    graphs: [...new Set([test, ...(failure === null ? [] : [failure.graph])])],
  };
}

/** 지금 파일(열린 버퍼, 없으면 디스크)에 그 노드가 있는가 */
async function nodeExists(graph: string, node: string): Promise<boolean> {
  const open = getDoc(graph);
  let value: GraphValue | null = open !== undefined && open.status === "ready" ? (open.value as GraphValue | null) : null;
  if (value === null) {
    try {
      const r = await client().call("graph.open", { path: graph });
      void client()
        .call("graph.close", { doc_id: r.doc_id })
        .catch(() => {});
      value = r.value as GraphValue | null;
    } catch {
      return false;
    }
  }
  return value !== null && graphNodes(value).some((n) => n.id === node);
}

export async function reproduce(view: RunViewState): Promise<ReproduceResult> {
  const plan = planReproduce(view);
  if (plan === null) return { ok: false, reason: "no_graph", message: "실행한 테스트 그래프를 모른다" };
  const runDir = view.index!.run_dir;
  const same = await Promise.all(plan.graphs.map((g) => sameAsSnapshot(snapshotPath(runDir, g), g)));
  const changed = same.some((s) => !s);
  if (changed) {
    const answer = await ask({
      title: "그래프가 실행 때와 다릅니다",
      message: `지금 파일이 실행 때 스냅샷과 달라요 (${plan.graphs.filter((_, i) => !same[i]).join(", ")}). 실패 노드가 바뀌었거나 없을 수 있어요.`,
      buttons: [
        { label: "그래도 열기", value: "open", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (answer.value !== "open") return { ok: false, reason: "canceled" };
  }
  let breakpoint = false;
  let breakpointFailed = false;
  let nodeMissing = false;
  if (plan.failure !== null) {
    const { graph, node } = plan.failure;
    if (await nodeExists(graph, node)) {
      // 저장이 끝나고 daemon이 확인한 목록에 있어야 걸린 것이다 (저장 실패면 모델이 확인된 목록으로 돌아간다)
      const list = breakpointModel.list;
      if (!hasBreakpoint(list, graph, node)) await breakpointModel.set(normalize([...list, plan.failure]));
      else await breakpointModel.settled();
      breakpoint = hasBreakpoint(breakpointModel.confirmedList, graph, node);
      breakpointFailed = !breakpoint;
    } else {
      nodeMissing = true;
    }
  }
  const profiles = useWorkspace.getState().info?.profiles ?? [];
  let profileMissing: string | null = null;
  if (plan.profile !== null && !profiles.includes(plan.profile)) {
    profileMissing = plan.profile;
    runModel.setProfile(null);
  } else {
    runModel.setProfile(plan.profile);
  }
  const entry = useWorkspace.getState().entries.find((e) => e.path === plan.test);
  openTab({ path: plan.test, kind: "graph", graphKind: entry?.graph_kind ?? "test" });
  if (plan.focus !== null) requestFocus(plan.test, { node: plan.focus });
  return { ok: true, breakpoint, breakpointFailed, profile: profileMissing === null ? plan.profile : null, profileMissing, changed, nodeMissing };
}

/** 결과 알림 글 (RUN 탭 머리 아래) */
export function reproduceNotice(result: ReproduceResult, failureTitle: string | null): { tone: "info" | "warn"; text: string } | null {
  if (!result.ok) return result.reason === "canceled" ? null : { tone: "warn", text: `재현하지 못했어요: ${result.message ?? ""}` };
  const parts: string[] = ["그래프를 열었어요"];
  if (result.breakpoint) parts.push(`'${failureTitle ?? "실패 노드"}'에 브레이크포인트`);
  if (result.breakpointFailed) parts.push(`'${failureTitle ?? "실패 노드"}'에 브레이크포인트를 저장하지 못했어요`);
  if (result.nodeMissing) parts.push("실패 노드가 지금 파일에 없어 브레이크포인트를 걸지 않았어요");
  parts.push(result.profile === null ? "프로필 기본" : `프로필 ${result.profile}`);
  if (result.profileMissing !== null) parts.push(`프로필 '${result.profileMissing}'이 없어 기본으로`);
  parts.push("F5로 실행하세요");
  const warn = result.changed || result.nodeMissing || result.breakpointFailed || result.profileMissing !== null;
  return { tone: warn ? "warn" : "info", text: parts.join(" · ") };
}
