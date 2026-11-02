// 탭 하나의 디버거 표시 (M3 계획 2.9): 브레이크포인트 점과 멈춘 노드. 캔버스가 맥락으로 노드에 넘긴다
// (값 사상과 따로 — 이벤트마다 사상을 다시 하지 않는다)
import { createContext, useContext, useMemo } from "react";
import { graphNodes, type GraphValue } from "../graph/model";
import { useRun } from "../run/runStore";
import { breakpointsIn, useBreakpoints } from "./breakpoints";
import { pausedNodeIn, type PausePoint } from "./pauseState";

export interface TabDebugView {
  /** 브레이크포인트가 걸린 노드 ID (이 탭 버퍼에 있는 것만) */
  breakpoints: ReadonlySet<string>;
  /** 이 탭에서 멈춤으로 표시할 노드와 멈춘 자리 */
  paused: { node: string; point: PausePoint } | null;
}

export function useTabDebugView(path: string, value: GraphValue | null): TabDebugView {
  const list = useBreakpoints((s) => s.list);
  const current = useRun((s) => s.current);
  return useMemo(() => {
    const breakpoints = breakpointsIn(list, path, value);
    const point = current?.phase === "running" ? current.pause.paused : null;
    let paused: TabDebugView["paused"] = null;
    if (point !== null && point !== undefined && value !== null) {
      const ids = new Set(graphNodes(value).map((n) => n.id));
      const node = pausedNodeIn(current!.trace.graph, point, current!.calls, path, (id) => ids.has(id));
      if (node !== null) paused = { node, point };
    }
    return { breakpoints, paused };
  }, [list, current, path, value]);
}

export const TabDebugContext = createContext<TabDebugView | null>(null);

export interface NodeDebugState {
  breakpoint: boolean;
  paused: PausePoint | null;
}

export function useNodeDebug(id: string): NodeDebugState | null {
  const tab = useContext(TabDebugContext);
  if (tab === null) return null;
  return { breakpoint: tab.breakpoints.has(id), paused: tab.paused?.node === id ? tab.paused.point : null };
}
