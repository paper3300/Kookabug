// 플러그인 위젯 세션 (M6 계획 3.10): 인스펙터 config 항목의 값 편집 위젯과 주고받는 규칙. DOM 없이 검사한다
// - 마운트 조건: config 항목에 ui.widget, 그 노드의 플러그인 위젯이고, 플러그인이 잠금에 있고 환경이 준비됨(호스트 있음).
//   비밀값 타입·비밀값 참조 항목에는 절대 마운트하지 않는다
// - 위젯 → 앱 메시지는 지금 iframe(contentWindow)에서 온 것 **그리고** 세션 nonce가 맞을 때만. iframe이 두 번째로
//   load되면(재적재) 세션 끝 → 기본 편집기. 5초 안 ready가 없어도 기본 편집기
// - change는 그 항목 스키마로 검사하고, 읽기 전용(실행 중·기록 보기)이면 버린다. 맞으면 기존 편집 경로로
import { isObject, specialTag } from "../graph/model";
import { elementType, formatJson, splitUnion, valueMode, SAFE_INT_TEXT, type FieldSpec } from "./fields";

export const WIDGET_API = 1;
export const WIDGET_READY_TIMEOUT_MS = 5000;
export const WIDGET_MIN_HEIGHT = 28;
export const WIDGET_MAX_HEIGHT = 480;
/** 위젯이 보낼 수 있는 값의 JSON 크기 상한 */
export const WIDGET_VALUE_MAX = 64 * 1024;

export type WidgetEndReason = "timeout" | "reloaded";

/** 위젯 호스트 (plugins.list 항목의 ui) */
export interface WidgetHostInfo {
  host: string;
  widgets: string[];
}

export interface WidgetPlugin {
  id: string;
  env_status: string;
  ui?: WidgetHostInfo;
}

export type WidgetBlock = "none" | "not_config" | "secret" | "foreign" | "not_ready" | "unknown_widget";

/** 위젯 껍데기 주소 (주 프로세스 security.ts widgetUrl과 같은 모양) */
export function widgetUrl(host: string, widget: string, session: string): string {
  return `kbplugin://${host}/__widget.html?w=${widget}&s=${session}`;
}

/** 세션 nonce: 16바이트 무작위 hex */
export function newSessionNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** 타입 어디에든(유니온 항·list·dict 원소의 유니온 포함) secret이 있는가 */
export function hasSecretTerm(type: string): boolean {
  return type.split(/[[\],|\s]+/).includes("secret");
}

/**
 * 위젯을 마운트할 수 없는 까닭 (마운트하면 null). `nodePlugin`은 그 노드 타입의 플러그인 ID — 위젯은 자기
 * 플러그인 것만. 비밀값 타입·비밀값 참조 값에는 위젯을 절대 쓰지 않는다
 */
export function widgetBlock(
  spec: FieldSpec,
  field: "in" | "config",
  value: unknown,
  plugin: WidgetPlugin | undefined,
  nodePlugin: string | null,
): WidgetBlock | null {
  const widget = spec.widget;
  if (widget === undefined) return "none";
  if (field !== "config") return "not_config";
  if (hasSecretTerm(spec.type) || valueMode(value) === "secret" || containsSecretRef(value)) return "secret";
  const owner = widget.split(".", 1)[0];
  if (nodePlugin === null || owner !== nodePlugin) return "foreign";
  if (plugin === undefined || plugin.id !== owner || plugin.env_status !== "ready" || plugin.ui === undefined) {
    return "not_ready";
  }
  if (!plugin.ui.widgets.includes(widget)) return "unknown_widget";
  return null;
}

function containsSecretRef(value: unknown, depth = 0): boolean {
  if (depth > 32) return true;
  if (specialTag(value) === "$secret") return true;
  if (Array.isArray(value)) return value.some((v) => containsSecretRef(v, depth + 1));
  if (isObject(value)) return Object.keys(value).some((k) => containsSecretRef(value[k], depth + 1));
  return false;
}

/** 구조적 복제로 온 값이 JSON 값인가: null·bool·문자열·유한 수·배열·평범한 객체, 깊이 64 */
function isJsonValue(v: unknown, depth = 0): boolean {
  if (depth > 64) return false;
  if (v === null || typeof v === "boolean" || typeof v === "string") return true;
  if (typeof v === "number") return Number.isFinite(v) && (!Number.isInteger(v) || Number.isSafeInteger(v));
  if (Array.isArray(v)) return v.every((x) => isJsonValue(x, depth + 1));
  if (typeof v === "object") {
    const proto = Object.getPrototypeOf(v);
    if (proto !== Object.prototype && proto !== null) return false;
    return Object.keys(v).every((k) => isJsonValue((v as Record<string, unknown>)[k], depth + 1));
  }
  return false;
}

/** 위젯이 보낸 값을 그 항목 스키마로 검사한다. 맞으면 null, 아니면 까닭 */
export function checkWidgetValue(spec: FieldSpec, value: unknown): string | null {
  if (!isJsonValue(value)) return "JSON 값이 아니에요 (유한한 수·정수 범위 " + SAFE_INT_TEXT + ")";
  if (formatJson(value).length > WIDGET_VALUE_MAX) return "값이 너무 커요";
  if (specialTag(value) !== null) return "특수 값($…)은 받지 않아요";
  if (Array.isArray(spec.enum) && spec.enum.length > 0) {
    return spec.enum.some((o) => formatJson(o) === formatJson(value)) ? null : "목록에 없는 값이에요";
  }
  if (containsSecretRef(value)) return "비밀값 참조는 받지 않아요";
  // 편집기 모양(유니온 첫 상수 항)이 아니라 선언 타입 전체로 검사한다 (B6 검수 Mid)
  if (!valueFitsType(spec.type, value)) return `${spec.type} 값이 아니에요`;
  if (typeof value === "number") {
    if (spec.minimum !== undefined && value < spec.minimum) return `${spec.minimum} 이상이어야 해요`;
    if (spec.maximum !== undefined && value > spec.maximum) return `${spec.maximum} 이하여야 해요`;
  }
  return null;
}

/**
 * 값이 선언 타입에 맞는가 (재귀): 유니온은 한 항이라도, `list[T]`는 원소 전부, `dict[str,T]`는 값 전부. point·rect는
 * 정수 칸(사각형 너비·높이 1 이상), `any`·플러그인 타입(`<플러그인>.<Type>`)은 JSON 값이면. 상수로 쓸 수 없는
 * 타입(target·secret·match·image·window·process)과 모르는 타입은 거부한다
 */
export function valueFitsType(type: string, value: unknown, depth = 0): boolean {
  if (depth > 32) return false;
  return splitUnion(type).some((term) => termFits(term, value, depth));
}

function termFits(term: string, value: unknown, depth: number): boolean {
  switch (term) {
    case "any":
      return true;
    case "bool":
      return typeof value === "boolean";
    case "int":
      return Number.isSafeInteger(value);
    case "float":
      return typeof value === "number" && Number.isFinite(value);
    case "string":
      return typeof value === "string";
    case "point":
    case "rect": {
      const size = term === "point" ? 2 : 4;
      if (!Array.isArray(value) || value.length !== size || !value.every((n) => Number.isSafeInteger(n))) return false;
      return term === "point" || ((value[2] as number) >= 1 && (value[3] as number) >= 1);
    }
  }
  if (term.startsWith("list[")) {
    const element = elementType(term);
    return element !== null && Array.isArray(value) && value.every((v) => valueFitsType(element, v, depth + 1));
  }
  if (term.startsWith("dict[")) {
    const element = elementType(term);
    return (
      element !== null &&
      isObject(value) &&
      specialTag(value) === null &&
      Object.keys(value).every((k) => valueFitsType(element, value[k], depth + 1))
    );
  }
  // 플러그인 타입 `<플러그인>.<Type>`: 모양을 모르므로 JSON 값이면 (편집기도 JSON 상자다)
  return /^[a-z][a-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$/.test(term);
}

/** 위젯에 넘기는 항목 선언 (값 검사 재료만) */
export function widgetSchema(spec: FieldSpec): Record<string, unknown> {
  const out: Record<string, unknown> = { name: spec.name, type: spec.type, required: spec.required };
  for (const key of ["default", "enum", "minimum", "maximum", "description"] as const) {
    if (spec[key] !== undefined) out[key] = spec[key];
  }
  return out;
}

export interface WidgetTheme {
  dark: boolean;
  colors: Record<string, string>;
}

export interface WidgetSessionOptions {
  session: string;
  widget: string;
  spec: FieldSpec;
  value: unknown;
  readOnly: boolean;
  theme: WidgetTheme;
  /** 앱 → 위젯 (지금 iframe의 contentWindow.postMessage) */
  post(message: Record<string, unknown>): void;
  /** 검사를 통과한 값 → 기존 편집 경로 (되돌리기·저장) */
  commit(value: unknown): void;
  end(reason: WidgetEndReason): void;
  resize(height: number): void;
}

/** 마운트 하나의 세션. 상태: loading(ready 기다림) → ready → ended (기본 편집기로) */
export class WidgetSession {
  state: "loading" | "ready" | "ended" = "loading";
  private loads = 0;
  private value: unknown;
  private readOnly: boolean;

  constructor(private readonly o: WidgetSessionOptions) {
    this.value = o.value;
    this.readOnly = o.readOnly;
  }

  /** iframe load. 두 번째부터는 재적재(자기 문서를 다시 씀 등)라 세션을 끝낸다 */
  frameLoaded(): void {
    this.loads += 1;
    if (this.loads > 1) this.finish("reloaded");
  }

  /** ready가 기한 안에 오지 않음 */
  timeout(): void {
    if (this.state === "loading") this.finish("timeout");
  }

  /**
   * window message. `source`는 event.source, `frame`은 지금 iframe의 contentWindow. 다른 창·다른 세션·끝난 세션의
   * 메시지는 버린다
   */
  receive(source: unknown, frame: unknown, data: unknown): void {
    if (this.state === "ended" || frame === null || frame === undefined || source !== frame) return;
    if (!isObject(data) || data.session !== this.o.session || typeof data.kb !== "string") return;
    switch (data.kb) {
      case "ready":
        if (this.state !== "loading") return;
        this.state = "ready";
        this.o.post({
          kb: "init",
          api: WIDGET_API,
          session: this.o.session,
          widget: this.o.widget,
          value: this.value,
          schema: widgetSchema(this.o.spec),
          readOnly: this.readOnly,
          theme: this.o.theme,
        });
        return;
      case "change": {
        if (this.state !== "ready" || !Object.hasOwn(data, "value")) return;
        const accepted = !this.readOnly && checkWidgetValue(this.o.spec, data.value) === null;
        if (accepted && formatJson(data.value) !== formatJson(this.value)) {
          this.value = data.value;
          this.o.commit(data.value);
        }
        // 위젯 표시를 앱 값에 맞춘다: 받았으면 새 값, 버렸으면(읽기 전용·틀린 값) 지금 값
        this.o.post({ kb: "value", session: this.o.session, value: this.value, readOnly: this.readOnly });
        return;
      }
      case "resize": {
        if (this.state !== "ready" || typeof data.height !== "number" || !Number.isFinite(data.height)) return;
        this.o.resize(Math.min(WIDGET_MAX_HEIGHT, Math.max(WIDGET_MIN_HEIGHT, Math.ceil(data.height))));
        return;
      }
    }
  }

  /** 앱 쪽 값·읽기 전용이 바뀜 (되돌리기·실행 시작 등) */
  update(value: unknown, readOnly: boolean): void {
    const same = formatJson(value) === formatJson(this.value) && readOnly === this.readOnly;
    this.value = value;
    this.readOnly = readOnly;
    if (this.state === "ready" && !same) this.o.post({ kb: "value", session: this.o.session, value, readOnly });
  }

  setTheme(theme: WidgetTheme): void {
    if (this.state === "ready") this.o.post({ kb: "theme", session: this.o.session, theme });
  }

  /** 언마운트: 더 받지 않는다 */
  dispose(): void {
    this.state = "ended";
  }

  private finish(reason: WidgetEndReason): void {
    if (this.state === "ended") return;
    this.state = "ended";
    this.o.end(reason);
  }
}
