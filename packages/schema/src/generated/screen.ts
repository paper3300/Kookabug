/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 화면 판정 파일 (*.screen.json). 화면 ID는 파일 이름 줄기
 */
export interface Screen {
  detect: ScreenDetect;
  format: "kookabug.screen/0";
  /**
   * 사람이 읽는 화면 이름
   */
  title?: string;
}
/**
 * all은 전부 보여야, none은 하나도 보이지 않아야 이 화면이다. 적어도 하나
 *
 * This interface was referenced by `Screen`'s JSON-Schema
 * via the `definition` "ScreenDetect".
 */
export interface ScreenDetect {
  /**
   * @minItems 1
   */
  all?: [ScreenCondition, ...ScreenCondition[]];
  /**
   * @minItems 1
   */
  none?: [ScreenCondition, ...ScreenCondition[]];
}
/**
 * 조건 하나. M1은 찾기 대상($target)만
 *
 * This interface was referenced by `Screen`'s JSON-Schema
 * via the `definition` "ScreenCondition".
 */
export interface ScreenCondition {
  /**
   * 워크스페이스 루트 기준 *.target.json 경로 ('/' 구분)
   */
  $target: string;
}
