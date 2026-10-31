// 에디터 탭 (M2 계획 2.11 "에디터 탭"). 탭 내용(캔버스·target 편집기)은 T8·T12가 붙인다
import { create } from "zustand";
import { displayName, type TreeEntry } from "../explorer/tree";

export interface EditorTab {
  path: string;
  kind: "graph" | "target";
  graphKind: TreeEntry["graph_kind"] | null;
  title: string;
}

interface TabsState {
  tabs: EditorTab[];
  active: string | null;
}

export const useTabs = create<TabsState>(() => ({ tabs: [], active: null }));

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

/** 탭 왼쪽 종류 글자 (시안: TEST·SUB·TARGET) */
export function tabBadge(tab: Pick<EditorTab, "kind" | "graphKind">): { text: string; tone: "test" | "target" } {
  if (tab.kind === "target") return { text: "TARGET", tone: "target" };
  return { text: tab.graphKind === "subgraph" ? "SUB" : "TEST", tone: "test" };
}
