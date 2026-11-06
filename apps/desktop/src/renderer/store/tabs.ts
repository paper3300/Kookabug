// 에디터 탭 (M2 계획 2.11 "에디터 탭"). 탭 내용(캔버스·target 편집기)은 T8·T12가 붙인다.
// M3 T10: 기록 뷰어 RUN 탭(경로 자리는 `run:<run_id>`)과 실행 폴더의 스냅샷 그래프 탭(읽기 전용, SNAPSHOT 글자)
// 다듬기 P1-B: 전용 편집기가 없는 탐색기 파일(화면 지도·설정·문서·이미지 등)의 읽기 전용 보기 탭(kind "file")
import { create } from "zustand";
import { displayName, type TreeEntry } from "../explorer/tree";

/** 보기 탭이 내용을 그리는 방식 */
export type FileViewKind = "json" | "text" | "image";

const IMAGE_EXTENSIONS = [".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"];

export function fileViewKind(path: string): FileViewKind {
  const lower = path.toLowerCase();
  if (IMAGE_EXTENSIONS.some((e) => lower.endsWith(e))) return "image";
  if (lower.endsWith(".json") || lower === "kookabug.lock") return "json";
  return "text";
}

/** 보기 탭 글자 (화면 지도 SCREEN, JSON, MD, 이미지 IMAGE, 그 밖 TEXT) */
export function fileBadgeText(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".screen.json")) return "SCREEN";
  const kind = fileViewKind(path);
  if (kind === "image") return "IMAGE";
  if (kind === "json") return "JSON";
  return lower.endsWith(".md") ? "MD" : "TEXT";
}

export interface EditorTab {
  /** 파일 탭은 워크스페이스 기준 경로, RUN 탭은 `run:<run_id>` */
  path: string;
  kind: "graph" | "target" | "run" | "file" | "rec" | "settings" | "plugin";
  graphKind: TreeEntry["graph_kind"] | null;
  title: string;
  /** RUN 탭의 실행, 스냅샷 그래프 탭이면 그 그래프를 돈 실행 */
  runId?: string;
  /** 실행 폴더(runs/ 아래)의 스냅샷 그래프: 읽기 전용 */
  snapshot?: boolean;
  /** 에이전트 확인 요청의 "캔버스에서 보기" (M5 U10): 승인하면 쓰일 그래프 값, 읽기 전용·파일 없음 */
  preview?: boolean;
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

/** 탐색기 파일 보기 탭 (읽기 전용, 이미 열려 있으면 그 탭으로 간다). 제목은 파일 이름 그대로 */
export function openFileTab(path: string): void {
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === path)) return { active: path };
    const tab: EditorTab = { path, kind: "file", graphKind: null, title: path.slice(path.lastIndexOf("/") + 1) };
    return { tabs: [...s.tabs, tab], active: path };
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

/** 승인 미리보기 탭 자리 (`preview:<확인 요청 ID>`) */
export const PREVIEW_PREFIX = "preview:";

export function isPreviewPath(path: string): boolean {
  return path.startsWith(PREVIEW_PREFIX);
}

/** 승인 미리보기 탭 (읽기 전용 그래프, 문서는 부르는 쪽이 adoptPreview로 먼저 넣는다) */
export function openPreviewTab(path: string, title: string): void {
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === path)) return { active: path };
    const tab: EditorTab = { path, kind: "graph", graphKind: null, title, preview: true };
    return { tabs: [...s.tabs, tab], active: path };
  });
}

/** 설정 탭 자리 (M5 B5 권한 설정 화면, 시안 Permissions) */
export const SETTINGS_TAB_PATH = "settings:permissions";

export function openSettingsTab(): void {
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === SETTINGS_TAB_PATH)) return { active: SETTINGS_TAB_PATH };
    const tab: EditorTab = { path: SETTINGS_TAB_PATH, kind: "settings", graphKind: null, title: "설정" };
    return { tabs: [...s.tabs, tab], active: SETTINGS_TAB_PATH };
  });
}

/** 플러그인 상세 탭 자리 (M6 B5, `plugin:<id>`) */
export const PLUGIN_TAB_PREFIX = "plugin:";

export function pluginTabPath(id: string): string {
  return `${PLUGIN_TAB_PREFIX}${id}`;
}

/** 플러그인 상세 탭 (제목 "<이름> 플러그인"). 이미 열려 있으면 제목만 고치고 앞으로 */
export function openPluginTab(id: string, title: string): void {
  const path = pluginTabPath(id);
  const text = `${title} 플러그인`;
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === path)) {
      return { tabs: s.tabs.map((t) => (t.path === path ? { ...t, title: text } : t)), active: path };
    }
    return { tabs: [...s.tabs, { path, kind: "plugin", graphKind: null, title: text }], active: path };
  });
}

/** 녹화 REC 탭 자리 (M4 T10, 녹화 세션 하나에 하나 — 세션이 끝나면 닫힌다) */
export const REC_TAB_PATH = "rec:capture";

/** REC 탭 (제목 "<창 제목> 캡처"). 이미 열려 있으면 제목만 고치고 앞으로 */
export function openRecTab(windowTitle: string | null, focus = true): void {
  const title = `${windowTitle ?? "게임"} 캡처`;
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === REC_TAB_PATH)) {
      return { tabs: s.tabs.map((t) => (t.path === REC_TAB_PATH ? { ...t, title } : t)), active: focus ? REC_TAB_PATH : s.active };
    }
    const tab: EditorTab = { path: REC_TAB_PATH, kind: "rec", graphKind: null, title };
    return { tabs: [...s.tabs, tab], active: focus ? REC_TAB_PATH : (s.active ?? REC_TAB_PATH) };
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

/** 탭 왼쪽 종류 글자 (시안: TEST·SUB·TARGET·RUN, 스냅샷 그래프는 SNAPSHOT, 보기 탭은 fileBadgeText) */
export function tabBadge(
  tab: Pick<EditorTab, "kind" | "graphKind"> & { snapshot?: boolean; preview?: boolean; path?: string },
): { text: string; tone: "test" | "target" | "run" | "file" | "rec" } {
  if (tab.kind === "settings") return { text: "SETTINGS", tone: "file" };
  if (tab.kind === "plugin") return { text: "PLUGIN", tone: "file" };
  if (tab.preview === true) return { text: "PREVIEW", tone: "run" };
  if (tab.kind === "target") return { text: "TARGET", tone: "target" };
  if (tab.kind === "rec") return { text: "REC", tone: "rec" };
  if (tab.kind === "run") return { text: "RUN", tone: "run" };
  if (tab.kind === "file") return { text: fileBadgeText(tab.path ?? ""), tone: "file" };
  if (tab.snapshot === true) return { text: "SNAPSHOT", tone: "run" };
  return { text: tab.graphKind === "subgraph" ? "SUB" : "TEST", tone: "test" };
}
