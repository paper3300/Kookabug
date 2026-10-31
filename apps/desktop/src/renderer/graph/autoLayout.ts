// 좌표 없는 노드의 보기용 배치 (M2 계획 2.6 "열기는 값을 바꾸지 않는다"). 결과는 화면에만 쓰고 값에는
// 넣지 않는다. 사용자가 그 노드를 옮기기 전까지 파일은 그대로다.
// 흐름(next)을 따라 깊이별 열로 놓는다. 좌표가 있는 노드가 있으면 그 아래에 놓는다
import type { GraphNodeValue, Point } from "./model";

export const GRID_X = 260;
export const GRID_Y = 180;
/** 좌표 있는 노드들 아래로 띄우는 거리 */
const BELOW = 220;

const ENTRY = "core.graph.entry";

/** 모든 노드의 화면 좌표. placed에 있는 노드는 그 좌표 그대로다 */
export function autoLayout(nodes: readonly GraphNodeValue[], placed: ReadonlyMap<string, Point>): Map<string, Point> {
  const out = new Map<string, Point>(placed);
  const missing = nodes.filter((n) => !placed.has(n.id));
  if (missing.length === 0) return out;

  const ids = new Set(nodes.map((n) => n.id));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const targeted = new Set(nodes.flatMap((n) => n.next.map(([, to]) => to)).filter((to) => ids.has(to)));
  // 시작점: 시작 노드, 그다음 아무도 가리키지 않는 노드 (파일 순서)
  const roots = [
    ...nodes.filter((n) => n.type === ENTRY),
    ...nodes.filter((n) => n.type !== ENTRY && !targeted.has(n.id)),
  ];
  const depth = new Map<string, number>();
  const queue: string[] = [];
  const visit = (id: string, d: number) => {
    if (depth.has(id)) return;
    depth.set(id, d);
    queue.push(id);
  };
  for (const root of roots) visit(root.id, 0);
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    for (const [, to] of byId.get(id)!.next) if (ids.has(to)) visit(to, depth.get(id)! + 1);
  }
  // 고리만 있는 노드
  for (const n of nodes) visit(n.id, 0);

  let origin: Point = { x: 0, y: 0 };
  if (placed.size > 0) {
    const ps = [...placed.values()];
    origin = { x: Math.min(...ps.map((p) => p.x)), y: Math.max(...ps.map((p) => p.y)) + BELOW };
  }
  const rows = new Map<number, number>();
  for (const id of queue) {
    if (placed.has(id)) continue;
    const d = depth.get(id)!;
    const row = rows.get(d) ?? 0;
    rows.set(d, row + 1);
    out.set(id, { x: origin.x + d * GRID_X, y: origin.y + row * GRID_Y });
  }
  return out;
}
