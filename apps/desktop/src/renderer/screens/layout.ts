// 화면 지도 카드 배치 (M7 계획 3.14, B5). 순수 함수 — vitest(layout.test.ts)로 본다.
// - 자동 배치: 시작 화면에서 이동 간선을 따라 넓이 우선으로 단(열)을 정하고, 단 안은 발견 순서대로 줄을 쌓는다.
//   닿지 않는 카드(다른 세션 후보·고립된 화면)는 마지막 단 뒤에 같은 규칙으로 이어 붙인다. 단이 MAX_COLS를 넘으면
//   아래 묶음으로 접는다 (시안처럼 2~3줄 — 가로로 끝없이 길어지지 않게)
// - 처음 열 때(저장한 확대가 없을 때) 화면에 맞춘다 (fitZoom)
// - 사람이 옮긴 자리(.kookabug/screen-map.json positions)가 자동 배치보다 먼저다. 없는 카드의 자리는 버린다
// - 간선 경로: 원본 카드 오른쪽 가운데 → 대상 카드 왼쪽 가운데 베지어. 대상이 왼쪽에 있으면 아래로 돌아간다

export interface Point {
  x: number;
  y: number;
}

export interface EdgeLike {
  from: string;
  to: string | null;
}

export const CARD_W = 200;
export const CARD_H = 162;
export const COL_GAP = 110;
export const ROW_GAP = 60;
export const MARGIN = 40;

/** 한 묶음의 단 수 (넘으면 아래 묶음으로 접는다) */
export const MAX_COLS = 4;

/** 자동 배치: 노드 → 왼쪽 위 자리 */
export function autoLayout(
  nodes: readonly string[],
  edges: readonly EdgeLike[],
  start: string | null,
  maxCols = MAX_COLS,
): Map<string, Point> {
  const known = new Set(nodes);
  const out = new Map<string, string[]>();
  const into = new Map<string, string[]>();
  for (const e of edges) {
    if (e.to === null || !known.has(e.from) || !known.has(e.to) || e.from === e.to) continue;
    (out.get(e.from) ?? out.set(e.from, []).get(e.from)!).push(e.to);
    (into.get(e.to) ?? into.set(e.to, []).get(e.to)!).push(e.from);
  }
  const depth = new Map<string, number>();
  const order: string[] = [];
  const visit = (root: string, base: number) => {
    if (depth.has(root)) return;
    depth.set(root, base);
    order.push(root);
    const queue = [root];
    while (queue.length > 0) {
      const node = queue.shift()!;
      const d = depth.get(node)!;
      // 나가는 간선이 먼저, 들어오는 간선(되돌아가는 이동)은 같은 단 다음으로
      for (const next of out.get(node) ?? []) {
        if (depth.has(next)) continue;
        depth.set(next, d + 1);
        order.push(next);
        queue.push(next);
      }
      for (const prev of into.get(node) ?? []) {
        if (depth.has(prev)) continue;
        depth.set(prev, d + 1);
        order.push(prev);
        queue.push(prev);
      }
    }
  };
  if (start !== null && known.has(start)) visit(start, 0);
  for (const node of nodes) {
    if (depth.has(node)) continue;
    const max = depth.size === 0 ? -1 : Math.max(...depth.values());
    visit(node, max + 1);
  }
  // 단 maxCols개마다 다음 묶음으로 접는다 (시안처럼 가로로 너무 길지 않게): 묶음 높이 = 그 묶음 단 중 가장 긴 줄 수
  const rowOf = new Map<string, number>();
  const rows = new Map<number, number>();
  for (const node of order) {
    const col = depth.get(node)!;
    const row = rows.get(col) ?? 0;
    rows.set(col, row + 1);
    rowOf.set(node, row);
  }
  const bandRows = new Map<number, number>();
  for (const [col, count] of rows) {
    const band = Math.floor(col / maxCols);
    bandRows.set(band, Math.max(bandRows.get(band) ?? 0, count));
  }
  const bandTop = new Map<number, number>();
  let top = MARGIN;
  const bands = bandRows.size === 0 ? 0 : Math.max(...bandRows.keys()) + 1;
  for (let band = 0; band < bands; band++) {
    bandTop.set(band, top);
    top += (bandRows.get(band) ?? 0) * (CARD_H + ROW_GAP) + ROW_GAP;
  }
  const result = new Map<string, Point>();
  for (const node of order) {
    const col = depth.get(node)!;
    const band = Math.floor(col / maxCols);
    result.set(node, {
      x: MARGIN + (col % maxCols) * (CARD_W + COL_GAP),
      y: bandTop.get(band)! + rowOf.get(node)! * (CARD_H + ROW_GAP),
    });
  }
  return result;
}

/** 처음 열 때 화면에 맞추는 확대 (확대 단계 중 들어가는 가장 큰 값, 30%~100%) */
export function fitZoom(size: { width: number; height: number }, view: { width: number; height: number }): number {
  if (size.width <= 0 || size.height <= 0 || view.width <= 0 || view.height <= 0) return 0.7;
  const want = Math.min(1, view.width / size.width, view.height / size.height);
  return [...ZOOM_STEPS].reverse().find((z) => z <= want + 1e-6 && z <= 1) ?? ZOOM_STEPS[0]!;
}

/** 저장한 자리가 자동 배치보다 먼저 (지금 없는 카드의 자리는 버린다) */
export function mergeLayout(
  auto: ReadonlyMap<string, Point>,
  saved: Readonly<Record<string, readonly number[]>> | undefined,
): Map<string, Point> {
  const merged = new Map(auto);
  for (const [node, xy] of Object.entries(saved ?? {})) {
    if (!merged.has(node) || xy.length !== 2 || !xy.every(Number.isFinite)) continue;
    merged.set(node, { x: xy[0]!, y: xy[1]! });
  }
  return merged;
}

/** 저장할 자리: 자동 배치와 다른 것만 (자동 배치가 바뀌어도 사람이 옮긴 카드만 고정) */
export function positionsToSave(
  current: ReadonlyMap<string, Point>,
  auto: ReadonlyMap<string, Point>,
  previous: Readonly<Record<string, readonly number[]>> | undefined,
): Record<string, [number, number]> {
  const out: Record<string, [number, number]> = {};
  for (const [node, p] of current) {
    const a = auto.get(node);
    const kept = previous?.[node] !== undefined;
    if (kept || a === undefined || a.x !== p.x || a.y !== p.y) out[node] = [Math.round(p.x), Math.round(p.y)];
  }
  return out;
}

export function bounds(points: Iterable<Point>): { width: number; height: number } {
  let width = 0;
  let height = 0;
  for (const p of points) {
    width = Math.max(width, p.x + CARD_W + MARGIN);
    height = Math.max(height, p.y + CARD_H + MARGIN);
  }
  return { width, height };
}

/** 간선 경로와 이름표 자리 */
export function edgePath(from: Point, to: Point): { d: string; label: Point } {
  const sx = from.x + CARD_W;
  const sy = from.y + CARD_H / 2;
  const tx = to.x;
  const ty = to.y + CARD_H / 2;
  if (tx >= sx) {
    const mid = (sx + tx) / 2;
    return { d: `M${sx} ${sy} C${mid} ${sy} ${mid} ${ty} ${tx} ${ty}`, label: { x: mid, y: (sy + ty) / 2 } };
  }
  // 대상이 왼쪽(되돌아가는 이동): 두 카드 아래로 돌아 들어간다
  const low = Math.max(from.y, to.y) + CARD_H + ROW_GAP / 2;
  const d = `M${sx} ${sy} C${sx + 60} ${sy} ${sx + 60} ${low} ${(sx + tx) / 2} ${low} S${tx - 60} ${ty} ${tx} ${ty}`;
  return { d, label: { x: (sx + tx) / 2, y: low } };
}

/** 줌 단계 (시안: 확대 단추 −/+, 70% 기본) */
export const ZOOM_STEPS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.25, 1.5];

export function nextZoom(current: number, dir: 1 | -1): number {
  if (dir > 0) return ZOOM_STEPS.find((z) => z > current + 1e-6) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]!;
  return [...ZOOM_STEPS].reverse().find((z) => z < current - 1e-6) ?? ZOOM_STEPS[0]!;
}
