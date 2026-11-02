// 실패 노드로 바로 이동 (M3 계획 2.10 "실패 노드로 바로 이동", 완료 기준 1).
// - 실패 사슬(run.index failure_chain, 루트 → run.end.failure_step)이 있으면 사슬의 앞 원소를 모두 펼치고
//   (반복이면 다음 원소의 회차) 끝 스텝을 고른다. 입력 계산 실패도 그 스텝의 step.start·step.end가 있어 사슬
//   끝이다 (2차 N1)
// - 사슬이 없으면(중단·취소·진행 중) 끝나지 않은 스텝 중 가장 안쪽 마지막을 찾아 내려간다. 회차 안 스텝은
//   쪽으로 읽는다 (load)
import type { runIndex } from "@kookabug/schema";

type RunIndex = runIndex.RunIndex;
type StepNode = runIndex.StepNode;

export interface JumpStep {
  step: string;
  /** 반복 스텝이면 열 회차 */
  iteration: number | null;
}

export interface JumpPlan {
  expand: JumpStep[];
  select: string | null;
}

/** 그 부모(반복이면 회차) 바로 아래 스텝 (step 순) */
export type ChildLoader = (parent: StepNode, iteration: number | null) => Promise<StepNode[]>;

const OPEN = new Set<string>(["aborted", "running"]);
/** 사슬을 따라 내려갈 깊이 상한 (서브그래프 호출 깊이보다 넉넉히) */
const MAX_DEPTH = 64;

export function stepNumber(step: string): number {
  const n = Number.parseInt(step.slice(1), 10);
  return Number.isFinite(n) ? n : 0;
}

/** 실패 사슬로 이동 (사슬이 없거나 사슬 스텝이 색인에 없으면 null) */
export function failurePlan(index: RunIndex): JumpPlan | null {
  const chain = index.failure_chain;
  if (chain.length === 0) return null;
  const byId = new Map(index.steps.map((s) => [s.step, s]));
  if (!chain.every((id) => byId.has(id))) return null;
  const expand: JumpStep[] = [];
  for (let i = 0; i < chain.length - 1; i++) {
    const parent = byId.get(chain[i])!;
    const next = byId.get(chain[i + 1])!;
    expand.push({ step: parent.step, iteration: parent.iterations !== undefined ? (next.iteration ?? null) : null });
  }
  return { expand, select: chain[chain.length - 1] };
}

function lastOpen(steps: readonly StepNode[]): StepNode | undefined {
  return [...steps].sort((a, b) => stepNumber(a.step) - stepNumber(b.step)).reverse().find((s) => OPEN.has(s.status));
}

/** 끝나지 않은 스텝 중 가장 안쪽 마지막 (중단된 실행·진행 중 실행) */
export async function openStepPlan(index: RunIndex, load: ChildLoader): Promise<JumpPlan> {
  const expand: JumpStep[] = [];
  let select: string | null = null;
  let level: readonly StepNode[] = index.steps.filter((s) => s.parent === null);
  for (let depth = 0; depth < MAX_DEPTH; depth++) {
    const open = lastOpen(level);
    if (open === undefined) break;
    select = open.step;
    if (open.children === 0) break;
    let iteration: number | null = null;
    if (open.iterations !== undefined && open.iterations.length > 0) {
      const iters = [...open.iterations].reverse();
      iteration = (iters.find((i) => OPEN.has(i.status)) ?? iters[0]).iteration;
    }
    expand.push({ step: open.step, iteration });
    level = await load(open, iteration);
  }
  return { expand, select };
}

/** 실행을 열 때 갈 자리: 실패 사슬, 없으면 끝나지 않은 가장 안쪽 스텝, 그것도 없으면 아무것도 고르지 않음 */
export async function planJump(index: RunIndex, load: ChildLoader): Promise<JumpPlan> {
  return failurePlan(index) ?? (await openStepPlan(index, load));
}
