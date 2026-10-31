// 보기 상태 (파일에 쓰지 않는다): 빠른 열기, 하단 패널 탭, 탐색기 펼침·선택, 창 최대화
import { create } from "zustand";

export type PanelTab = "problems" | "output" | "runlog" | "result";

interface UiState {
  quickOpen: boolean;
  panelTab: PanelTab;
  expanded: Set<string> | null;
  selected: string | null;
  maximized: boolean;
}

export const useUi = create<UiState>(() => ({
  quickOpen: false,
  panelTab: "output",
  expanded: null,
  selected: null,
  maximized: false,
}));

export function toggleExpanded(path: string, current: ReadonlySet<string>): void {
  const next = new Set(current);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  useUi.setState({ expanded: next });
}
