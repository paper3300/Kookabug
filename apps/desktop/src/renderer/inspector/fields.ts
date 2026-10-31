// 속성 편집기 순수 규칙 (M2 계획 2.11 "속성 편집기", T10): 핀 타입 → 입력 모양, 값 → 표시 방식, 입력 글자 → 값.
// 값 검사(정수 범위·유한 수·enum·min/max)는 여기서 즉시 하고, 최종 판정은 daemon 진단이다.
// - 상수 모양은 스키마 1장 "상수"를 따른다: point = [x, y], rect = [x, y, w, h] (정수 픽셀, 너비·높이 1 이상)
// - `$literal` 안은 해석하지 않는다 (2.6). 연결($link)은 캔버스에서 만들고 여기서는 읽기·끊기만 한다
import { findLinks, isObject, own, specialTag, type JsonObject } from "../graph/model";

/** 상수를 고치는 입력 모양 */
export type ConstKind = "number" | "text" | "bool" | "enum" | "point" | "rect" | "list" | "dict" | "json";

/** 핀 하나의 입력 모양. target·secret은 상수가 없는 타입, link-only는 연결로만 받는 타입(match·image 등) */
export type EditorKind = ConstKind | "target" | "secret" | "link-only";

export interface FieldSpec {
  name: string;
  type: string;
  enum?: unknown[];
  minimum?: number;
  maximum?: number;
  default?: unknown;
  description?: string;
  required: boolean;
}

export interface FieldEditor {
  kind: EditorKind;
  /** number일 때 정수만 */
  integer: boolean;
  /** list·dict의 원소 타입 */
  element: string | null;
  /** 값 대신 고를 수 있는 특수 값 */
  allowTarget: boolean;
  allowSecret: boolean;
  allowSetting: boolean;
}

/** 깊이 0의 `|`로 나눈다 (`list[string]|list[point]`, `dict[str,target]|rect`) */
export function splitUnion(type: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < type.length; i++) {
    const c = type[i];
    if (c === "[") depth++;
    else if (c === "]") depth--;
    else if (c === "|" && depth === 0) {
      out.push(type.slice(start, i).trim());
      start = i + 1;
    }
  }
  out.push(type.slice(start).trim());
  return out.filter((t) => t !== "");
}

/** `list[T]` → T, `dict[str,T]` → T. 아니면 null */
export function elementType(term: string): string | null {
  const list = /^list\[(.*)\]$/.exec(term);
  if (list !== null) return list[1].trim();
  const dict = /^dict\[\s*str\s*,(.*)\]$/.exec(term);
  if (dict !== null) return dict[1].trim();
  return null;
}

/** 상수로 쓸 수 있는 타입 항의 입력 모양. 연결로만 받는 타입(target·secret·match·image·window·process)은 null */
function constKindOf(term: string): { kind: ConstKind; integer: boolean; element: string | null } | null {
  switch (term) {
    case "bool":
      return { kind: "bool", integer: false, element: null };
    case "int":
      return { kind: "number", integer: true, element: null };
    case "float":
      return { kind: "number", integer: false, element: null };
    case "string":
      return { kind: "text", integer: false, element: null };
    case "point":
      return { kind: "point", integer: true, element: null };
    case "rect":
      return { kind: "rect", integer: true, element: null };
    case "any":
      return { kind: "json", integer: false, element: null };
    case "target":
    case "secret":
    case "match":
    case "image":
    case "window":
    case "process":
      return null;
  }
  if (term.startsWith("list[")) return { kind: "list", integer: false, element: elementType(term) };
  if (term.startsWith("dict[")) return { kind: "dict", integer: false, element: elementType(term) };
  // 플러그인 타입(<플러그인>.<Type>): 모양을 모르므로 JSON으로 고친다
  return { kind: "json", integer: false, element: null };
}

/**
 * 핀 타입 → 입력 모양. enum이 있으면 선택 상자. 유니온이면 상수로 쓸 수 있는 첫 항의 모양이고, target·secret
 * 항은 특수 값 고르기로 둔다 (예: `string|secret` = 한 줄 상자 + 비밀 키, `target|rect` = 숫자 4칸 + 대상)
 */
export function editorFor(spec: Pick<FieldSpec, "type" | "enum">, options: { specials?: boolean } = {}): FieldEditor {
  const specials = options.specials !== false;
  const terms = splitUnion(spec.type);
  const allowTarget = specials && terms.includes("target");
  const allowSecret = specials && terms.includes("secret");
  const first = terms.map(constKindOf).find((k) => k !== null) ?? null;
  if (Array.isArray(spec.enum) && spec.enum.length > 0) {
    return { kind: "enum", integer: false, element: null, allowTarget, allowSecret, allowSetting: specials };
  }
  if (first !== null) return { ...first, allowTarget, allowSecret, allowSetting: specials };
  const kind: EditorKind = terms.includes("target") ? "target" : terms.includes("secret") ? "secret" : "link-only";
  return { kind, integer: false, element: null, allowTarget, allowSecret, allowSetting: false };
}

/** 지금 값을 어떻게 보이는가 */
export type ValueMode =
  | "unset"
  | "link"
  /** 배열·객체 안쪽에 연결이 있음 (읽기 전용, 끊으면 핀 전체) */
  | "linked-inside"
  | "target"
  | "setting"
  | "secret"
  /** `$literal`: 안을 해석하지 않고 보여 주기만 한다 */
  | "literal"
  | "constant";

export function valueMode(value: unknown): ValueMode {
  if (value === undefined) return "unset";
  const tag = specialTag(value);
  if (tag !== null) {
    const inner = own(value, tag);
    if (tag === "$literal") return "literal";
    if (typeof inner === "string") {
      if (tag === "$link") return inner.includes(".") ? "link" : "constant";
      if (tag === "$target") return "target";
      if (tag === "$setting") return "setting";
      if (tag === "$secret") return "secret";
    }
    // 틀린 특수 값(`{"$link": 1}`·모르는 `$` 키): JSON으로 보여 고칠 수 있게 한다
    return "constant";
  }
  return findLinks(value).length > 0 ? "linked-inside" : "constant";
}

/**
 * 특수 값을 해석하는 자리면 valueMode, 아니면 상수로만 본다. 특수 값은 입력 핀(in) 안에서만 뜻이 있다(스키마 1장
 * "특수 값"). config 안의 `$link`처럼 생긴 값은 보통 데이터라 연결로 보지 않는다 (T10 검수 2)
 */
export function valueModeFor(value: unknown, specials: boolean): ValueMode {
  if (specials) return valueMode(value);
  return value === undefined ? "unset" : "constant";
}

/** 상수 입력 모양이 이 값을 그대로 보여 줄 수 있는가. 아니면 JSON 상자로 보여 값을 잃지 않는다 */
export function fits(kind: EditorKind, value: unknown): boolean {
  switch (kind) {
    case "number":
      return typeof value === "number";
    case "text":
      return typeof value === "string";
    case "bool":
      return typeof value === "boolean";
    case "enum":
      return true;
    case "point":
      return Array.isArray(value) && value.length === 2 && value.every((n) => typeof n === "number");
    case "rect":
      return Array.isArray(value) && value.length === 4 && value.every((n) => typeof n === "number");
    case "list":
      return Array.isArray(value);
    case "dict":
      return isObject(value) && specialTag(value) === null;
    case "json":
      return true;
    default:
      return false;
  }
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

const INT_RE = /^[+-]?\d+$/;
const FLOAT_RE = /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/;
export const SAFE_INT_TEXT = "±9007199254740991";

/** 숫자 칸 글자 → 수. 정수 범위·유한 수·min/max를 바로 본다 */
export function parseNumber(
  text: string,
  rule: { integer: boolean; minimum?: number; maximum?: number },
): Parsed<number> {
  const t = text.trim();
  if (t === "") return { ok: false, error: "값을 넣으세요" };
  if (rule.integer) {
    if (!INT_RE.test(t)) return { ok: false, error: "정수를 넣으세요" };
    const n = Number(t);
    if (!Number.isSafeInteger(n)) return { ok: false, error: `정수 범위(${SAFE_INT_TEXT}) 밖이에요` };
    return withinRange(n + 0, rule);
  }
  if (!FLOAT_RE.test(t)) return { ok: false, error: "수를 넣으세요" };
  const n = Number(t);
  if (!Number.isFinite(n)) return { ok: false, error: "유한한 수를 넣으세요" };
  return withinRange(n + 0, rule);
}

function withinRange(n: number, rule: { minimum?: number; maximum?: number }): Parsed<number> {
  if (rule.minimum !== undefined && n < rule.minimum) return { ok: false, error: `${rule.minimum} 이상이어야 해요` };
  if (rule.maximum !== undefined && n > rule.maximum) return { ok: false, error: `${rule.maximum} 이하여야 해요` };
  return { ok: true, value: n };
}

/** 점·사각형 칸 → 배열 상수. 정수 픽셀이고 사각형의 너비·높이는 1 이상 (스키마 1장 "상수") */
export function parseCells(cells: readonly string[], kind: "point" | "rect"): Parsed<number[]> {
  const size = kind === "point" ? 2 : 4;
  if (cells.length !== size) return { ok: false, error: `칸 ${size}개가 필요해요` };
  const out: number[] = [];
  for (let i = 0; i < size; i++) {
    const r = parseNumber(cells[i], { integer: true, ...(kind === "rect" && i >= 2 ? { minimum: 1 } : {}) });
    if (!r.ok) return { ok: false, error: `${CELL_NAMES[kind][i]}: ${r.error}` };
    out.push(r.value);
  }
  return { ok: true, value: out };
}

export const CELL_NAMES = { point: ["x", "y"], rect: ["x", "y", "w", "h"] } as const;

/** 정수 모양 수 토큰(소수점·지수 없음)이 정수 범위 밖인가. 문자열 안은 건너뛴다 */
function bigIntegerToken(text: string): string | null {
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    if (c === '"') {
      i++;
      while (i < text.length && text[i] !== '"') i += text[i] === "\\" ? 2 : 1;
      i++;
      continue;
    }
    if (c === "-" || (c >= "0" && c <= "9")) {
      const m = /^-?\d+(\.\d+)?([eE][+-]?\d+)?/.exec(text.slice(i));
      if (m !== null) {
        if (m[1] === undefined && m[2] === undefined && !Number.isSafeInteger(Number(m[0]))) return m[0];
        i += m[0].length;
        continue;
      }
    }
    i++;
  }
  return null;
}

function firstNonFinite(v: unknown): boolean {
  if (typeof v === "number") return !Number.isFinite(v);
  if (Array.isArray(v)) return v.some(firstNonFinite);
  if (isObject(v)) return Object.keys(v).some((k) => firstNonFinite(v[k]));
  return false;
}

/**
 * JSON 상자 글자 → 값. 정수 범위 밖 정수 토큰(`9007199254740993`)과 유한하지 않은 수(`1e400`)는 바로 거부한다
 * (2.6 값 규칙: 파일에 쓸 수 없다). `1e20`처럼 지수·소수점이 있는 큰 수는 실수라 받는다
 */
export function parseJson(text: string): Parsed<unknown> {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (e) {
    return { ok: false, error: `JSON이 아니에요: ${e instanceof Error ? e.message : String(e)}` };
  }
  const big = bigIntegerToken(text);
  if (big !== null) return { ok: false, error: `정수 범위(${SAFE_INT_TEXT}) 밖이에요: ${big}` };
  if (firstNonFinite(value)) return { ok: false, error: "유한하지 않은 수(NaN·무한)는 쓸 수 없어요" };
  return { ok: true, value };
}

/** JSON 객체 상자 (모르는 노드의 in·config) */
export function parseJsonObject(text: string): Parsed<JsonObject> {
  const r = parseJson(text.trim() === "" ? "{}" : text);
  if (!r.ok) return r;
  if (!isObject(r.value)) return { ok: false, error: "객체({ … })여야 해요" };
  return { ok: true, value: r.value };
}

function numberText(n: number): string {
  // 정수 범위 밖 정수값은 원래 실수다: 지수 표기로 보여 다시 읽어도 실수가 되게 한다 (2.6 전송 코덱과 같은 규칙)
  return Number.isInteger(n) && Math.abs(n) > Number.MAX_SAFE_INTEGER ? n.toExponential() : JSON.stringify(n);
}

/** 값 → JSON 글자. indent가 있으면 펼친다. 큰 실수는 지수 표기 */
export function formatJson(value: unknown, indent = 0, depth = 0): string {
  if (typeof value === "number") return numberText(value);
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  const pad = indent > 0 ? `\n${" ".repeat(indent * (depth + 1))}` : "";
  const end = indent > 0 ? `\n${" ".repeat(indent * depth)}` : "";
  const sep = indent > 0 ? ": " : ":";
  if (Array.isArray(value)) {
    if (value.length === 0) return "[]";
    return `[${value.map((v) => pad + formatJson(v, indent, depth + 1)).join(",")}${end}]`;
  }
  const obj = value as JsonObject;
  const keys = Object.keys(obj);
  if (keys.length === 0) return "{}";
  return `{${keys.map((k) => `${pad}${JSON.stringify(k)}${sep}${formatJson(obj[k], indent, depth + 1)}`).join(",")}${end}}`;
}

/** 숫자 칸에 보일 글자 */
export function formatNumber(n: number): string {
  return numberText(n);
}

/** 연결 표시 "노드.출력" */
export function linkText(value: unknown): { node: string; output: string } | null {
  if (specialTag(value) !== "$link") return null;
  const ref = own(value, "$link");
  if (typeof ref !== "string") return null;
  const dot = ref.indexOf(".");
  return dot < 0 ? null : { node: ref.slice(0, dot), output: ref.slice(dot + 1) };
}

/** 새 원소의 처음 값 (줄 편집의 "추가") */
export function emptyElement(type: string | null): unknown {
  if (type === null) return null;
  const e = editorFor({ type });
  switch (e.kind) {
    case "number":
      return 0;
    case "text":
      return "";
    case "bool":
      return false;
    case "point":
      return [0, 0];
    case "rect":
      return [0, 0, 1, 1];
    case "list":
      return [];
    case "dict":
      return {};
    default:
      return null;
  }
}

/** 사전 원소 목록 → 객체 (`__proto__` 키도 자기 속성으로) */
export function dictFromEntries(entries: readonly (readonly [string, unknown])[]): JsonObject {
  const out: JsonObject = {};
  for (const [k, v] of entries) Object.defineProperty(out, k, { value: v, writable: true, enumerable: true, configurable: true });
  return out;
}

/** 원소 순서 바꾸기 (from → to 자리). 범위 밖이면 그대로 */
export function moveItem<T>(items: readonly T[], from: number, to: number): T[] {
  if (from < 0 || from >= items.length || to < 0 || to >= items.length || from === to) return [...items];
  const out = [...items];
  const [x] = out.splice(from, 1);
  out.splice(to, 0, x);
  return out;
}
