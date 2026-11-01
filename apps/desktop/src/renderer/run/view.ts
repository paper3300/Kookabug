// 실행 화면 공용: 열린 문서 버퍼로 그래프 따라가기, 반복 노드 한도 이름, 흐르는 시간, 캔버스 노드 상태 맥락
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { TypeIndex } from "../graph/mapping";
import type { GraphValue } from "../graph/model";
import { useDocuments, type GraphDoc } from "../store/documents";
import { useRegistry } from "../store/registry";
import { tabRunView, type GraphLookup, type NodeRunView, type TabRunView } from "./highlight";
import { useRun, type RunView } from "./runStore";

export function docLookup(docs: ReadonlyMap<string, GraphDoc>): GraphLookup {
  return (path) => docs.get(path)?.value ?? null;
}

export function loopLimitOf(types: TypeIndex): (type: string) => string | null {
  return (type) => types.get(type)?.loopLimit ?? null;
}

export function typeTitleOf(types: TypeIndex): (type: string) => string | null {
  return (type) => types.get(type)?.title ?? null;
}

/** active면 interval마다 지금 시각으로 다시 그린다 (실행 중 흐르는 시간) */
export function useNow(active: boolean, interval = 100): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    setNow(Date.now());
    const timer = setInterval(() => setNow(Date.now()), interval);
    return () => clearInterval(timer);
  }, [active, interval]);
  return now;
}

/** 이 문서 탭의 실행 상태 (지금 실행이 없으면 null) */
export function useTabRunView(path: string, value: GraphValue | null): TabRunView | null {
  const current = useRun((s) => s.current);
  const types = useRegistry((s) => s.types);
  // 어느 파일의 노드인지는 실행 스냅샷의 호출 관계로 정한다 (다른 탭 버퍼·조상 탭 열림과 무관)
  return useMemo(
    () =>
      current === null || value === null
        ? null
        : tabRunView(current.trace, { path, value }, current.calls, loopLimitOf(types)),
    [current, types, path, value],
  );
}

/** 지금 실행이 이 경로의 그래프를 돌았고 실행 뒤 버퍼·디스크가 바뀌었다 ("실행은 저장된 버전 기준") */
export function editedSinceRun(run: RunView | null, doc: GraphDoc | undefined): boolean {
  if (run === null || doc === undefined || run.phase !== "running" || run.graph !== doc.path) return false;
  return doc.dirty || (run.revision !== null && doc.baseRevision !== run.revision);
}

export const TabRunContext = createContext<TabRunView | null>(null);

export interface NodeRunState {
  view: NodeRunView | null;
  /** 실행 중인데 아직 이 노드에 닿지 않음 */
  idle: boolean;
}

export function useNodeRun(id: string): NodeRunState | null {
  const tab = useContext(TabRunContext);
  if (tab === null) return null;
  const view = tab.nodes.get(id) ?? null;
  return { view, idle: view === null && tab.running };
}
