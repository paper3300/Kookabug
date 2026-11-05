// 보기 상태 (파일에 쓰지 않는다): 빠른 열기, 하단 패널 탭, 탐색기 펼침·선택, 창 최대화, 속성 패널 펼침
import { create } from "zustand";

export type PanelTab = "problems" | "output" | "runlog" | "result";

/** 사이드바 보기 (액티비티 바): 탐색기·실행 기록 (M3 T10)·녹화 (M4 T9) */
export type SideView = "explorer" | "runs" | "recorder";

interface UiState {
  quickOpen: boolean;
  sideView: SideView;
  panelTab: PanelTab;
  expanded: Set<string> | null;
  selected: string | null;
  maximized: boolean;
  /** 오른쪽 속성 패널 (접기 가능, U1) */
  inspectorOpen: boolean;
  /**
   * 하단 패널 펼침 (M4 B5 조율자 결정): 정지 화면을 다루는 탭(REC·TARGET)이 앞에 있으면 기본 접힘, 그 밖은 기본
   * 펼침. 사람이 바꾸면 그 쪽 값을 기억한다
   */
  panelOpenEditor: boolean;
  panelOpenOther: boolean;
}

export const useUi = create<UiState>(() => ({
  quickOpen: false,
  sideView: "explorer",
  panelTab: "output",
  expanded: null,
  selected: null,
  maximized: false,
  inspectorOpen: true,
  panelOpenEditor: false,
  panelOpenOther: true,
}));

/** 하단 패널 펼침을 정하는 쪽: 정지 화면 탭(REC·TARGET)인가 */
export function panelSide(kind: string | undefined): "panelOpenEditor" | "panelOpenOther" {
  return kind === "rec" || kind === "target" ? "panelOpenEditor" : "panelOpenOther";
}

export function toggleExpanded(path: string, current: ReadonlySet<string>): void {
  const next = new Set(current);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  useUi.setState({ expanded: next });
}
