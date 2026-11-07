// 화면 지도 탭 열기 (M7 B5): 탭 하나(`map:screens`, 제목 "<워크스페이스> 화면 지도"), 탐색기의 *.screen.json →
// 지도 탭에서 그 카드 선택 (SCREEN 보기 탭은 사이드바 "원문 보기")
import { openFileTab, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { loadMap, MAP_TAB_PATH, nodeOfPath, select, useMap } from "./mapStore";

export function openMapTab(): void {
  const title = `${useWorkspace.getState().name ?? ""} 화면 지도`.trim();
  useTabs.setState((s) => {
    if (s.tabs.some((t) => t.path === MAP_TAB_PATH)) return { active: MAP_TAB_PATH };
    return { tabs: [...s.tabs, { path: MAP_TAB_PATH, kind: "map", graphKind: null, title }], active: MAP_TAB_PATH };
  });
}

/**
 * 탐색기에서 화면 파일을 열었다: 지도에 그 카드가 있으면 지도 탭에서 고르고, 없으면(screens/ 밖·같은 ID의 둘째
 * 파일·세션 폴더 밖 옛 자리 등) 원문 보기 탭 (B5 검수 Mid 1 — 이전 동작)
 */
export async function openScreenFile(path: string): Promise<void> {
  if (useMap.getState().map === null) await loadMap();
  const node = nodeOfPath(useMap.getState().map, path);
  if (node === null) {
    openFileTab(path);
    return;
  }
  openMapTab();
  select(node);
}
