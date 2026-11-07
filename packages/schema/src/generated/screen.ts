/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 화면 판정 파일 (*.screen.json). 화면 ID는 파일 이름 줄기. kookabug.screen/0(M1)·/1(M7 화면 지도)
 */
export type Screen = Screen0 | Screen1;
/**
 * 조건 하나: $target 또는 ocr
 */
export type ScreenCondition1 = ScreenCondition | OcrCondition;
/**
 * 정규화 사각형 [x, y, w, h] (클라이언트 영역 기준 0~1)
 *
 * @minItems 4
 * @maxItems 4
 */
export type NormRect = [number, number, number, number];
/**
 * 화면 ID(파일 이름 줄기) 또는 후보 키
 */
export type ScreenRef = string;
/**
 * 이동 입력: 요소 클릭·점 클릭·키
 */
export type ScreenVia =
  | {
      click: {
        element: string;
      };
    }
  | {
      click: {
        point: NormPoint;
      };
    }
  | {
      key: string;
    };
/**
 * 정규화 점 [x, y] (클라이언트 영역 기준 0~1)
 *
 * @minItems 2
 * @maxItems 2
 */
export type NormPoint = [number, number];
/**
 * 화면 ID(파일 이름 줄기) 또는 후보 키
 */
export type ScreenRef1 = string;

/**
 * M1 최소 형식: 판정 조건은 $target만
 */
export interface Screen0 {
  detect: ScreenDetect;
  format: "kookabug.screen/0";
  /**
   * 사람이 읽는 화면 이름
   */
  title?: string;
}
/**
 * all은 전부 보여야, none은 하나도 보이지 않아야 이 화면이다. 적어도 하나
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
 * 찾기 대상 조건($target)
 */
export interface ScreenCondition {
  /**
   * 워크스페이스 루트 기준 *.target.json 경로 ('/' 구분)
   */
  $target: string;
}
/**
 * 화면 지도 형식 (M7): OCR 조건·설명·UI 요소·이동·대표 스크린샷·출처. screens/의 확정 화면은 detect가 있어야 하고, of는 screens/_explored/의 후보만 쓴다
 */
export interface Screen1 {
  description?: string;
  detect?: ScreenDetect1;
  /**
   * @maxItems 200
   */
  elements?: ScreenElement[];
  format: "kookabug.screen/1";
  kind?: "popup" | "screen";
  /**
   * @maxItems 200
   */
  moves?: ScreenMove[];
  of?: ScreenRef1;
  origin?: ScreenOrigin;
  shot?: ScreenShot;
  title?: string;
}
/**
 * ScreenDetect와 같고 조건에 ocr을 쓸 수 있다
 */
export interface ScreenDetect1 {
  /**
   * @minItems 1
   */
  all?: [ScreenCondition1, ...ScreenCondition1[]];
  /**
   * @minItems 1
   */
  none?: [ScreenCondition1, ...ScreenCondition1[]];
}
/**
 * OCR 조건 (M7): 그 영역에서 읽은 글자에 text가 들어 있다 (공백·대소문자 무시)
 */
export interface OcrCondition {
  ocr: {
    match?: "contains";
    rect: NormRect;
    text: string;
  };
}
/**
 * UI 요소 하나. 이름은 카드 안에서 겹치지 않는다
 */
export interface ScreenElement {
  kind: "button" | "field" | "list" | "text";
  name: string;
  rect: NormRect;
}
/**
 * 이동 하나: via 입력으로 to 화면에 간다. tried면 to가 있어야 한다
 */
export interface ScreenMove {
  note?: string;
  status: "tried" | "untried";
  /**
   * 화면 ID 또는 같은 세션의 후보 키. untried면 null 가능
   */
  to?: ScreenRef | null;
  via: ScreenVia;
}
/**
 * 출처. 없으면 사람이 직접 쓴 화면
 */
export interface ScreenOrigin {
  agent?: string;
  /**
   * UTC ISO 8601
   */
  at?: string;
  kind: "explored";
  session: string;
}
/**
 * 대표 스크린샷 (워크스페이스 루트 기준 PNG 경로, 찍을 때 클라이언트 크기·배율)
 */
export interface ScreenShot {
  /**
   * @minItems 2
   * @maxItems 2
   */
  client_size: [number, number];
  image: string;
  scale?: number;
}
