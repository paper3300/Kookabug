/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 찾기 대상 파일 (*.target.json): 이미지, 임계값, 검색 범위, 클릭 지점
 */
export interface Target {
  click?: Click;
  format: "kookabug.target/0";
  /**
   * 이 target 파일 기준 상대 경로 ('/' 구분)
   */
  image: string;
  match?: Match;
  recorded?: Recorded;
  search?: Search;
  /**
   * true면 이 대상으로 읽은 OCR 결과와 그 파생값이 secret이 된다
   */
  sensitive?: boolean;
}
/**
 * This interface was referenced by `Target`'s JSON-Schema
 * via the `definition` "Click".
 */
export interface Click {
  /**
   * 9분할 클릭 지점
   */
  anchor?:
    | "bottom"
    | "bottom_left"
    | "bottom_right"
    | "center"
    | "left"
    | "right"
    | "top"
    | "top_left"
    | "top_right";
  /**
   * anchor에서 더하는 [x, y] (픽셀)
   *
   * @minItems 2
   * @maxItems 2
   */
  offset?: [number, number];
}
/**
 * This interface was referenced by `Target`'s JSON-Schema
 * via the `definition` "Match".
 */
export interface Match {
  /**
   * 앞에서부터 시도한다. 각 방법은 threshold를 넘어야 성공
   *
   * @minItems 1
   */
  methods?: ["template" | "template_multiscale", ...("template" | "template_multiscale")[]];
  rgb?: boolean;
  threshold?: number;
}
/**
 * 녹화 당시 클라이언트 영역 크기와 DPI
 *
 * This interface was referenced by `Target`'s JSON-Schema
 * via the `definition` "Recorded".
 */
export interface Recorded {
  /**
   * @minItems 2
   * @maxItems 2
   */
  client_size?: [number, number];
  dpi?: number;
}
/**
 * This interface was referenced by `Target`'s JSON-Schema
 * via the `definition` "Search".
 */
export interface Search {
  /**
   * 클라이언트 영역 기준 정규화 좌표 [x, y, w, h]
   *
   * @minItems 4
   * @maxItems 4
   */
  region?: [number, number, number, number];
}
