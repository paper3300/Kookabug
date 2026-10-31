// 노드 분류 표 (M2 계획 2.7 "팔레트"): 코어 `category` → 시안의 표시 분류, 노드 머리 색, 팔레트 분류 점 색.
// 시안 분류는 창·입력·화면 인식·흐름·판정·Agent·엔진 연동이다. 처음 보는 분류(플러그인)는 "플러그인"이고 팔레트
// 오른쪽에 플러그인 이름을 붙인다(시안 "src" 칸). Agent 분류는 노드가 생기는 M5 전까지 비어 있어 보이지 않는다.
// 머리 색은 시안 Main 노드에서 왔다: 창 파랑, 입력·화면 인식 초록, 반복·분기 보라, 시작·기록 같은 나머지 회색.
// 점 색은 시안 Main·MainLight 팔레트(토큰 --kb-cat-*)다

export type HeadTone = "neutral" | "blue" | "green" | "purple";
export type DotTone = "window" | "input" | "vision" | "flow" | "judge" | "plugin";

export interface CategoryInfo {
  group: string;
  head: HeadTone;
}

/** 팔레트 분류 순서와 점 색 (시안 Main 팔레트) */
export const PALETTE_GROUPS: readonly { group: string; dot: DotTone }[] = [
  { group: "창", dot: "window" },
  { group: "입력", dot: "input" },
  { group: "화면 인식", dot: "vision" },
  { group: "흐름", dot: "flow" },
  { group: "판정", dot: "judge" },
];

export const PLUGIN_GROUP = "플러그인";
export const PLUGIN_DOT: DotTone = "plugin";

export const CORE_CATEGORIES: Readonly<Record<string, CategoryInfo>> = {
  window: { group: "창", head: "blue" },
  app: { group: "창", head: "blue" },
  input: { group: "입력", head: "green" },
  image: { group: "화면 인식", head: "green" },
  ocr: { group: "화면 인식", head: "green" },
  screen: { group: "화면 인식", head: "green" },
  flow: { group: "흐름", head: "purple" },
  graph: { group: "흐름", head: "neutral" },
  value: { group: "흐름", head: "neutral" },
  log: { group: "흐름", head: "neutral" },
  test: { group: "판정", head: "neutral" },
};

export const PLUGIN_CATEGORY: CategoryInfo = { group: PLUGIN_GROUP, head: "neutral" };

export function categoryInfo(category: string | null | undefined): CategoryInfo {
  if (category !== null && category !== undefined && Object.hasOwn(CORE_CATEGORIES, category)) {
    return CORE_CATEGORIES[category];
  }
  return PLUGIN_CATEGORY;
}

export function dotColor(dot: DotTone): string {
  return `var(--kb-cat-${dot})`;
}
