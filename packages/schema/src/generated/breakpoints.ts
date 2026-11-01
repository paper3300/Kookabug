/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 브레이크포인트 목록 (순서 무관, 같은 항목은 하나로 본다)
 *
 * @maxItems 1000
 *
 * This interface was referenced by `Breakpoints`'s JSON-Schema
 * via the `definition` "BreakpointList".
 */
export type BreakpointList = Breakpoint[];

/**
 * 브레이크포인트 파일 (.kookabug/breakpoints.json, 개인 파일). daemon이 원자적 교체로 쓰고, 사람이 UI에서 시작한 실행에만 넣는다
 */
export interface Breakpoints {
  breakpoints: BreakpointList;
  format: "kookabug.breakpoints/0";
}
/**
 * 브레이크포인트 열쇠: 그래프 파일 + 노드 ID (노드 ID는 바뀌지 않는다). exec 노드에만 건다. 서브그래프 파일에 건 것은 어느 호출에서든, 반복 본문 노드에 건 것은 회차마다 적중한다
 *
 * This interface was referenced by `Breakpoints`'s JSON-Schema
 * via the `definition` "Breakpoint".
 */
export interface Breakpoint {
  /**
   * 노드가 든 그래프 파일 (워크스페이스 루트 기준 '/' 구분 경로, 스냅샷 접두 없음)
   */
  graph: string;
  /**
   * 노드 ID (graph.schema.json NodeId)
   */
  node: string;
}
