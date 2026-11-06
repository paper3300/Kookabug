// 팔레트 목록 (M2 계획 2.7 "팔레트", T9). 노드 스키마(nodes.list)를 시안 분류로 묶고 검색한다. 순수 함수다
import type { NodeTypeInfo, TypeIndex } from "../graph/mapping";
import { categoryInfo, PALETTE_GROUPS, PLUGIN_DOT, PLUGIN_GROUP, type DotTone } from "./categories";

export interface PaletteItem {
  type: string;
  title: string;
  /** 오른쪽 칸 (플러그인 분류면 플러그인 이름, 코어는 빈칸) */
  src: string;
  info: NodeTypeInfo;
}

export interface PaletteGroup {
  group: string;
  dot: DotTone;
  /** 묶음 줄 오른쪽 칸 (코어 묶음의 고정 글, 예: Agent "CLI · API 키") */
  src?: string;
  items: PaletteItem[];
}

/** 노드를 끌 때 dataTransfer 형식 */
export const PALETTE_MIME = "application/x-kookabug-node";

/** 팔레트에 두지 않는 노드: 그래프 시작점(새 그래프 틀에 이미 있고 둘이면 검증 오류) */
function hidden(info: NodeTypeInfo): boolean {
  return info.entry;
}

/** 검색: title·type·description 부분 일치 (영문은 대소문자 무시, 한글은 그대로) */
export function matches(info: NodeTypeInfo, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (q === "") return true;
  return [info.title, info.type, info.description ?? ""].some((s) => s.toLowerCase().includes(q));
}

export function paletteGroups(types: TypeIndex, query = ""): PaletteGroup[] {
  const groups = new Map<string, PaletteGroup>(
    PALETTE_GROUPS.map((g) => [g.group, { group: g.group, dot: g.dot, src: g.src, items: [] }]),
  );
  const plugins = new Map<string, PaletteGroup>();
  for (const info of types.values()) {
    if (hidden(info) || !matches(info, query)) continue;
    const { group } = categoryInfo(info.category);
    if (group === PLUGIN_GROUP) {
      // 플러그인 분류는 플러그인마다 한 묶음 (오른쪽에 플러그인 이름)
      let g = plugins.get(info.plugin);
      if (g === undefined) plugins.set(info.plugin, (g = { group: PLUGIN_GROUP, dot: PLUGIN_DOT, items: [] }));
      g.items.push({ type: info.type, title: info.title, src: info.pluginTitle || info.plugin, info });
    } else {
      groups.get(group)!.items.push({ type: info.type, title: info.title, src: "", info });
    }
  }
  const byTitle = (a: PaletteItem, b: PaletteItem) => a.title.localeCompare(b.title, "ko") || (a.type < b.type ? -1 : 1);
  const out = [...groups.values(), ...[...plugins.entries()].sort(([a], [b]) => (a < b ? -1 : 1)).map(([, g]) => g)];
  for (const g of out) g.items.sort(byTitle);
  return out.filter((g) => g.items.length > 0);
}

/** 묶음 열쇠 (플러그인 묶음은 플러그인마다 다르다) */
export function groupKey(g: PaletteGroup): string {
  return g.group === PLUGIN_GROUP ? `${PLUGIN_GROUP}:${g.items[0]?.info.plugin ?? ""}` : g.group;
}

/** 처음 펼친 묶음 (시안 Main: 창·입력·화면 인식) */
export const DEFAULT_OPEN: readonly string[] = ["창", "입력", "화면 인식"];
