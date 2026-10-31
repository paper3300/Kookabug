// 노드 분류 표 (M2 계획 2.7 "팔레트"): 코어 `category` → 시안의 표시 분류와 노드 머리 색.
// 시안 분류는 창·입력·화면 인식·흐름·판정·Agent·엔진 연동이다. 처음 보는 분류(플러그인)는 "플러그인".
// 머리 색은 시안 Main 노드에서 왔다: 창 파랑, 입력·화면 인식 초록, 반복·분기 보라, 시작·기록 같은 나머지 회색.
// 팔레트 목록·검색·끌어 놓기는 T9가 이 표로 만든다

export type HeadTone = "neutral" | "blue" | "green" | "purple";

export interface CategoryInfo {
  group: string;
  head: HeadTone;
}

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

export const PLUGIN_CATEGORY: CategoryInfo = { group: "플러그인", head: "neutral" };

export function categoryInfo(category: string | null | undefined): CategoryInfo {
  if (category !== null && category !== undefined && Object.hasOwn(CORE_CATEGORIES, category)) {
    return CORE_CATEGORIES[category];
  }
  return PLUGIN_CATEGORY;
}
