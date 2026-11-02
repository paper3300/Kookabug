// 에디터 탭 (M2 계획 2.11 "에디터 탭"). 탭 내용(캔버스·target 편집기)은 T8·T12가 붙인다.
// M3 T10: 기록 뷰어 RUN 탭(경로 자리는 `run:<run_id>`)과 실행 폴더의 스냅샷 그래프 탭(읽기 전용, SNAPSHOT 글자)
import { create } from "zustand";
import { displayName, type TreeEntry } from "../explorer/tree";

export interface EditorTab {
  /** 파일 탭은 워크스페이스 기준 경로, RUN 탭은 `run:<run_id>` */
  path: string;
  kind: "graph" | "target" | "run";
  graphKind: TreeEntry["graph_kind"] | null;
  title: string;
  /** RUN 탭의 실행, 스냅샷 그래프 탭이면 그 그래프를 돈 실행 */
  runId?: string;
  /** 실행 폴더(runs/ 아래)의 스냅샷 그래프: 읽기 전용 */
  snapshot?: boolean;
}

interface TabsState {
  tabs: EditorTab[];
  active: string | null;
}

export const useTabs = create<TabsState>(() => ({ tabs: [], active: null }));

export const RUN_TAB_PREFIX = "run:";

export function runTabPath(runId: string): string {
  return `${RUN_TAB_PREFIX}${runId}`;
}

/** 실행 폴더 아래 경로인가 (스냅샷 그래프) */
export function isRunsPath(path: string): boolean {
  return path.startsWith("runs/");
}

/** 이미 열려 있으면 그 탭으로 간다 */
export function openTab(entry: { path: string; kind: "graph" | "target"; graphKind?: TreeEntry["graph_kind"] | null }): void {
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === entry.path)) return { active: entry.path };
    const tab: EditorTab = {
      path: entry.path,
      kind: entry.kind,
      graphKind: entry.graphKind ?? null,
      title: displayName(entry.path),
    };
    return { tabs: [...s.tabs, tab], active: entry.path };
  });
}

/** 기록 뷰어 RUN 탭 (이미 열려 있으면 그 탭으로 가고 제목만 고친다) */
export function openRunTab(runId: string, title: string): void {
  const path = runTabPath(runId);
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === path)) {
      return { tabs: s.tabs.map((t) => (t.path === path ? { ...t, title } : t)), active: path };
    }
    return { tabs: [...s.tabs, { path, kind: "run", graphKind: null, title, runId }], active: path };
  });
}

/** 실행 스냅샷 그래프 탭 (읽기 전용). 제목은 "<그래프> · #<실행>" */
export function openSnapshotTab(path: string, runId: string, shortId: string): void {
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === path)) return { active: path };
    const tab: EditorTab = {
      path,
      kind: "graph",
      graphKind: null,
      title: `${displayName(path)} · #${shortId}`,
      runId,
      snapshot: true,
    };
    return { tabs: [...s.tabs, tab], active: path };
  });
}

/** 열린 탭의 제목만 바꾼다 (RUN 탭: 스냅샷에서 테스트 제목을 읽은 뒤) */
export function renameTab(path: string, title: string): void {
  useTabs.setState((s) =>
    s.tabs.some((t) => t.path === path && t.title !== title)
      ? { tabs: s.tabs.map((t) => (t.path === path ? { ...t, title } : t)) }
      : s,
  );
}

export function activateTab(path: string): void {
  useTabs.setState({ active: path });
}

export function closeTab(path: string): void {
  useTabs.setState((s) => {
    const index = s.tabs.findIndex((t) => t.path === path);
    if (index < 0) return s;
    const tabs = s.tabs.filter((t) => t.path !== path);
    const active = s.active !== path ? s.active : (tabs[Math.min(index, tabs.length - 1)]?.path ?? null);
    return { tabs, active };
  });
}

export function closeAllTabs(): void {
  useTabs.setState({ tabs: [], active: null });
}

/** 탭 왼쪽 종류 글자 (시안: TEST·SUB·TARGET·RUN, 스냅샷 그래프는 SNAPSHOT) */
export function tabBadge(
  tab: Pick<EditorTab, "kind" | "graphKind"> & { snapshot?: boolean },
): { text: string; tone: "test" | "target" | "run" } {
  if (tab.kind === "target") return { text: "TARGET", tone: "target" };
  if (tab.kind === "run") return { text: "RUN", tone: "run" };
  if (tab.snapshot === true) return { text: "SNAPSHOT", tone: "run" };
  return { text: tab.graphKind === "subgraph" ? "SUB" : "TEST", tone: "test" };
}
