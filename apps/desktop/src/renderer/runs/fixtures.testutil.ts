// 기록 뷰어 검사용 색인 조각 (run-index.schema.json 모양). 실제 runner 색인과 같은 규칙:
// 반복 스텝 아래 회차로 본문·되돌아옴이 묶이고, run.index steps는 최상위 + 실패 사슬만이다
import type { RunIndex, StepNode } from "./runIndexStore";

let clock = Date.parse("2026-11-02T01:00:00.000Z");

export function step(id: string, over: Partial<StepNode> = {}): StepNode {
  const t = new Date((clock += 100)).toISOString();
  return {
    step: id,
    parent: null,
    node: `n_${id}`,
    graph: "tests/t.graph.json",
    path: [`n_${id}`],
    attempt: 1,
    status: "success",
    exit: "done",
    t_start: t,
    t_end: t,
    duration_ms: 100,
    children: 0,
    evidence: false,
    ...over,
  };
}

export function index(steps: StepNode[], over: Partial<RunIndex> = {}): RunIndex {
  return {
    run_id: "ab12cd34",
    run_dir: "runs/20261102T010000_ab12cd34",
    state: "ended",
    last_seq: 100,
    run: { graph: "tests/t.graph.json", started_at: "2026-11-02T01:00:00.000Z" },
    steps,
    failure_chain: [],
    stats: [],
    pauses: [],
    video: null,
    ...over,
  };
}
