// 디버그 툴바 가로 자리 (M3 계획 2.9 "끌기·자리 기억", 검수 T9-1). 기억하는 값은 사용자가 끈 자리(가운데 기준
// px)이고, 화면에 쓰는 값은 지금 영역 안으로 들인 값이다: 창을 줄이면 화면에서만 안으로 들이고 기억한 자리는
// 그대로 둔다(다시 넓히면 돌아간다). 순수 함수 (position.test.ts)

/** 영역 양쪽에 남길 여백 */
export const TOOLBAR_MARGIN = 8;

/** 기억한 자리 x를 영역(area) 안에 툴바(width)가 다 보이게 들인 값 */
export function clampX(x: number, area: number, width: number): number {
  const max = Math.max(0, (area - width) / 2 - TOOLBAR_MARGIN);
  return Math.round(Math.min(max, Math.max(-max, x)));
}
