// 보기 상태 (파일에 쓰지 않는다): 빠른 열기, 하단 패널 탭, 탐색기 펼침·선택, 창 최대화, 속성 패널 펼침
import { create } from "zustand";

export type PanelTab = "problems" | "output" | "runlog";

/** 사이드바 보기 (액티비티 바): 탐색기·실행 기록 (M3 T10)·녹화 (M4 T9)·플러그인 (M6 B5) */
export type SideView = "explorer" | "screens" | "runs" | "recorder" | "plugins";

interface UiState {
  quickOpen: boolean;
  sideView: SideView;
  panelTab: PanelTab;
  expanded: Set<string> | null;
  selected: string | null;
  maximized: boolean;
  /** 오른쪽 속성 패널 (접기 가능, U1) */
  inspectorOpen: boolean;
  /** 오른쪽 패널 탭: 속성 | 에이전트 (M5 B5, 시안 Main) */
  rightTab: "props" | "agent";
  /**
   * 하단 패널 펼침 (M4 B5 조율자 결정): 정지 화면을 다루는 탭(REC·TARGET)이 앞에 있으면 기본 접힘, 그 밖은 기본
   * 펼침. 사람이 바꾸면 그 쪽 값을 기억한다
   */
  panelOpenEditor: boolean;
  panelOpenOther: boolean;
  /** 왼쪽 사이드바 펼침 (액티비티 아이콘 다시 누르기·Ctrl+B로 접기) */
  sidebarOpen: boolean;
  /** 끌어서 바꾼 폭 px (null = 기본 폭). 녹화 사이드바는 따로 */
  sidebarWidth: number | null;
  recorderSidebarWidth: number | null;
  /** 오른쪽 패널 폭: 그래프·그 밖 탭은 inspectorWidth, 나머지 탭 종류(RUN·보고함·REC 등)는 inspectorWidths[종류] (UX6) */
  inspectorWidth: number | null;
  inspectorWidths: Record<string, number>;
}

export const useUi = create<UiState>(() => ({
  quickOpen: false,
  sideView: "explorer",
  panelTab: "output",
  expanded: null,
  selected: null,
  maximized: false,
  rightTab: "props",
  panelOpenEditor: false,
  panelOpenOther: true,
  ...defaultLayout(),
}));

// ── 패널 배치 (앱 설정 userData/settings.json의 layout — App.tsx가 읽고 쓴다) ─────────
export type Layout = Pick<
  UiState,
  "sidebarOpen" | "sidebarWidth" | "recorderSidebarWidth" | "inspectorWidth" | "inspectorWidths" | "inspectorOpen"
>;

function defaultLayout(): Layout {
  return { sidebarOpen: true, sidebarWidth: null, recorderSidebarWidth: null, inspectorWidth: null, inspectorWidths: {}, inspectorOpen: true };
}

/** 오른쪽 패널 폭을 따로 기억하는 탭 종류 (UX6). 그 밖은 inspectorWidth 하나 */
const WIDTH_KINDS = ["run", "reports", "rec", "target", "map"] as const;

/**
 * 앱 설정에 쓰는 배치: 주 프로세스가 작은 평평한 객체(값은 수·참거짓·null)만 받으므로 탭별 폭은 `inspectorWidth_<종류>` 칸으로
 * 펴서 쓴다
 */
export type StoredLayout = Record<string, number | boolean | null>;

/** 저장된 값(모양 모름)을 배치로. 틀린 칸은 기본값 */
export function parseLayout(v: unknown): Layout {
  const o = typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
  const width = (x: unknown) => (typeof x === "number" && Number.isFinite(x) && x > 0 && x < 10_000 ? Math.round(x) : null);
  const widths: Record<string, number> = {};
  for (const k of WIDTH_KINDS) {
    const w = width(o[`inspectorWidth_${k}`]);
    if (w !== null) widths[k] = w;
  }
  return {
    sidebarOpen: o.sidebarOpen !== false,
    sidebarWidth: width(o.sidebarWidth),
    recorderSidebarWidth: width(o.recorderSidebarWidth),
    inspectorWidth: width(o.inspectorWidth),
    inspectorWidths: widths,
    inspectorOpen: o.inspectorOpen !== false,
  };
}

export function layoutOf(s: UiState): StoredLayout {
  const out: StoredLayout = {
    sidebarOpen: s.sidebarOpen,
    sidebarWidth: s.sidebarWidth,
    recorderSidebarWidth: s.recorderSidebarWidth,
    inspectorWidth: s.inspectorWidth,
    inspectorOpen: s.inspectorOpen,
  };
  for (const k of WIDTH_KINDS) out[`inspectorWidth_${k}`] = s.inspectorWidths[k] ?? null;
  return out;
}

/** 오른쪽 패널 폭을 기억하는 칸: 그래프·탭 없음·보기 탭 등은 하나(inspectorWidth), RUN·보고함·REC·TARGET·지도는 따로 */
export function widthKey(kind: string | undefined): string | null {
  return (WIDTH_KINDS as readonly string[]).includes(kind ?? "") ? kind! : null;
}

export function inspectorWidthOf(s: Pick<UiState, "inspectorWidth" | "inspectorWidths">, kind: string | undefined): number | null {
  const key = widthKey(kind);
  return key === null ? s.inspectorWidth : (s.inspectorWidths[key] ?? null);
}

export function setInspectorWidth(kind: string | undefined, width: number | null): void {
  const key = widthKey(kind);
  if (key === null) {
    useUi.setState({ inspectorWidth: width });
    return;
  }
  useUi.setState((s) => {
    const next = { ...s.inspectorWidths };
    if (width === null) delete next[key];
    else next[key] = width;
    return { inspectorWidths: next };
  });
}

/** 사이드바 접기·펼치기 (Ctrl+B, 보기 메뉴) */
export function toggleSidebar(): void {
  useUi.setState((s) => ({ sidebarOpen: !s.sidebarOpen }));
}

/** 하단 패널 펼침을 정하는 쪽: 정지 화면 탭(REC·TARGET)·설정 탭(시안 Permissions — 하단 패널 없음)인가 */
export function panelSide(kind: string | undefined): "panelOpenEditor" | "panelOpenOther" {
  return kind === "rec" || kind === "target" || kind === "settings" || kind === "plugin" || kind === "map"
    ? "panelOpenEditor"
    : "panelOpenOther";
}

export function toggleExpanded(path: string, current: ReadonlySet<string>): void {
  const next = new Set(current);
  if (next.has(path)) next.delete(path);
  else next.add(path);
  useUi.setState({ expanded: next });
}

/**
 * 무언가를 골랐다: 오른쪽 패널을 펴고 "속성" 탭으로 (UX4·UX6 — 고른 것의 정보·동작은 모두 속성 탭).
 * 에이전트 탭을 보고 있었어도 바꾼다. 승인 대기 배지는 에이전트 탭 머리에 그대로 남는다
 */
export function showProps(): void {
  const s = useUi.getState();
  if (s.inspectorOpen && s.rightTab === "props") return;
  useUi.setState({ inspectorOpen: true, rightTab: "props" });
}

/** 오른쪽 패널의 에이전트 탭을 연다 (RUN 탭 "에이전트에게 분석 요청"·상태 바 "에이전트 N") */
export function openAgentPanel(): void {
  useUi.setState({ inspectorOpen: true, rightTab: "agent" });
}
