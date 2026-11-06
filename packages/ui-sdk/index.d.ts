// @kookabug/ui-sdk 타입 (index.js)

export declare const API_VERSION: 1;

export interface WidgetTheme {
  dark?: boolean;
  /** 앱 색 토큰. 위젯 문서에 `--kb-<이름>` CSS 변수로도 들어간다 */
  colors?: Record<string, string>;
}

export interface WidgetInit {
  /** 위젯 ID `<플러그인 ID>.<이름>` */
  widget: string;
  value: unknown;
  /** 그 config 항목의 선언 (type·default·enum·minimum·maximum·description) */
  schema: Record<string, unknown>;
  readOnly: boolean;
  theme: WidgetTheme;
}

export interface WidgetHandlers {
  onInit?(init: WidgetInit): void;
  onValue?(value: unknown, readOnly: boolean): void;
  onTheme?(theme: WidgetTheme): void;
  /** 문서 높이를 자동으로 앱에 알린다 (기본 true) */
  autoHeight?: boolean;
}

export interface Widget {
  setValue(value: unknown): void;
  setHeight(height: number): void;
}

export declare function defineWidget(handlers?: WidgetHandlers): Widget;
