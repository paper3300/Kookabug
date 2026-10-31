// daemon-rpc 런타임 검사 (M2 계획 2.10). 생성 TS 타입은 검사기가 아니므로, 주 프로세스가 렌더러에서
// 받은 params와 daemon에서 받은 응답·알림을 메타스키마(daemon-rpc.schema.json)로 직접 검사한다.
//
// - 먼저 값 전체가 JSON 값 규칙에 맞는지 본다: JSON 타입만, 유한한 수, 중첩 128단까지 (M0b 봉투 규칙).
//   스키마가 안쪽 모양을 정하지 않은 값(그래프 값·이벤트 출력 등)도 여기서 걸린다. 큰 유한 실수
//   (`1e20`)는 허용한다 (전송 코덱이 float로 돌려보내는 값)
// - 그다음 스키마 모양. 메타스키마가 쓰는 키워드만 안다 (scripts/gen.mjs가 다른 키워드를 쓰면 생성을
//   멈춘다). $ref는 같은 파일의 "#/..."와 다른 메타스키마 "urn:kookabug:<종류>:0[#/...]"(events)를 푼다
import { daemonRpcSchema } from "./generated/daemon-rpc.data.js";
import type { Methods, Notifications } from "./generated/daemon-rpc.js";
import { eventsSchema } from "./generated/events.data.js";

type Schema = { readonly [key: string]: unknown } | boolean;
type Document = { readonly $id: string; readonly $defs: Record<string, Schema> };

export type MethodName = keyof Methods;
export type NotificationName = keyof Notifications;
export type ParamsOf<M extends MethodName> = Methods[M]["params"];
export type ResultOf<M extends MethodName> = Methods[M]["result"];
export type NotificationParamsOf<N extends NotificationName> = Notifications[N]["params"];

/** 검사에서 걸린 곳 하나. `pointer`는 값 안 위치(JSON 포인터). */
export interface SchemaIssue {
  pointer: string;
  message: string;
}

export interface MethodInfo {
  params: string;
  result: string;
  tool: string;
  /** false면 Electron 주 프로세스 내부용 (렌더러 표면에 내놓지 않는다) */
  renderer: boolean;
}

/** 중첩 한도 (M0b `kookabug_sdk.rpc.MAX_DEPTH`와 같다: 객체·배열 128단) */
export const MAX_DEPTH = 128;

const root = daemonRpcSchema as Document;
const documents = new Map<string, Document>(
  [root, eventsSchema as Document].map((doc) => [doc.$id, doc]),
);
const defs = root.$defs;

function defName(schema: Schema): string {
  const ref = (schema as { $ref: string }).$ref;
  return ref.slice("#/$defs/".length);
}

function tableOf(name: string): Record<string, Record<string, Schema>> {
  const table = defs[name] as { properties: Record<string, { properties: Record<string, Schema> }> };
  return Object.fromEntries(
    Object.entries(table.properties).map(([key, entry]) => [key, entry.properties]),
  );
}

/** 메서드 표 (daemon-rpc.schema.json의 Methods). */
export const METHODS: Readonly<Record<MethodName, MethodInfo>> = Object.fromEntries(
  Object.entries(tableOf("Methods")).map(([name, row]) => [
    name,
    {
      params: defName(row.params!),
      result: defName(row.result!),
      tool: (row.tool as { const: string }).const,
      renderer: (row.renderer as { const: boolean }).const,
    },
  ]),
) as Record<MethodName, MethodInfo>;

/** 알림 이름 → params 정의 이름 (Notifications 표). */
export const NOTIFICATIONS: Readonly<Record<NotificationName, string>> = Object.fromEntries(
  Object.entries(tableOf("Notifications")).map(([name, row]) => [name, defName(row.params!)]),
) as Record<NotificationName, string>;

export function isMethodName(name: unknown): name is MethodName {
  return typeof name === "string" && Object.hasOwn(METHODS, name);
}

export function isNotificationName(name: unknown): name is NotificationName {
  return typeof name === "string" && Object.hasOwn(NOTIFICATIONS, name);
}

function token(key: string | number): string {
  return String(key).replace(/~/g, "~0").replace(/\//g, "~1");
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return false;
  const proto: unknown = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}

/** 값 전체의 JSON 값 규칙 (스키마와 무관). 문제가 있으면 첫 문제만 담는다 */
function checkJsonValue(value: unknown, out: SchemaIssue[]): void {
  // 재귀하지 않는다: 아주 깊은 값에서도 스택이 넘치지 않고, 한도에서 멈춘다
  const stack: [unknown, string, number][] = [[value, "", 0]];
  while (stack.length > 0) {
    const [item, pointer, depth] = stack.pop()!;
    if (item === null || typeof item === "boolean" || typeof item === "string") continue;
    if (typeof item === "number") {
      if (!Number.isFinite(item)) {
        out.push({ pointer, message: `${item}는 JSON 숫자가 아니다 (NaN·Infinity)` });
        return;
      }
      continue;
    }
    if (Array.isArray(item) || isPlainObject(item)) {
      if (depth >= MAX_DEPTH) {
        out.push({ pointer, message: `중첩이 ${MAX_DEPTH}단을 넘는다` });
        return;
      }
      if (Array.isArray(item)) {
        for (let i = 0; i < item.length; i++) {
          if (!(i in item)) {
            out.push({ pointer: `${pointer}/${i}`, message: "배열에 빈 칸이 있다" });
            return;
          }
          stack.push([item[i], `${pointer}/${i}`, depth + 1]);
        }
      } else {
        for (const [key, child] of Object.entries(item)) {
          stack.push([child, `${pointer}/${token(key)}`, depth + 1]);
        }
      }
      continue;
    }
    out.push({ pointer, message: `JSON 값이 아니다 (${typeOf(item)})` });
    return;
  }
}

function hasType(value: unknown, type: string): boolean {
  switch (type) {
    case "null":
      return value === null;
    case "boolean":
      return typeof value === "boolean";
    case "string":
      return typeof value === "string";
    case "number":
      return typeof value === "number" && Number.isFinite(value);
    case "integer":
      return typeof value === "number" && Number.isInteger(value);
    case "array":
      return Array.isArray(value);
    case "object":
      return typeOf(value) === "object";
    default:
      throw new Error(`모르는 타입 ${type}`);
  }
}

function jsonEqual(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (typeOf(a) === "object" && typeOf(b) === "object") {
    const ka = Object.keys(a as object);
    const kb = Object.keys(b as object);
    return (
      ka.length === kb.length &&
      ka.every(
        (k) =>
          Object.hasOwn(b as object, k) &&
          jsonEqual((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
      )
    );
  }
  return a === b;
}

const patterns = new Map<string, RegExp>();

function regex(pattern: string): RegExp {
  let found = patterns.get(pattern);
  if (found === undefined) {
    found = new RegExp(pattern, "u");
    patterns.set(pattern, found);
  }
  return found;
}

/** $ref → (그 스키마, 그 스키마가 속한 문서). */
function resolve(ref: string, doc: Document): [Schema, Document] {
  const hash = ref.indexOf("#");
  const base = hash < 0 ? ref : ref.slice(0, hash);
  const fragment = hash < 0 ? "" : ref.slice(hash + 1);
  const target = base === "" ? doc : documents.get(base);
  if (target === undefined) throw new Error(`풀 수 없는 참조 ${ref}`);
  let node: unknown = target;
  for (const part of fragment.split("/").slice(1)) {
    node = (node as Record<string, unknown>)[part.replace(/~1/g, "/").replace(/~0/g, "~")];
    if (node === undefined) throw new Error(`없는 정의 ${ref}`);
  }
  return [node as Schema, target];
}

function check(
  schema: Schema,
  value: unknown,
  pointer: string,
  out: SchemaIssue[],
  doc: Document,
): void {
  if (schema === true) return;
  if (schema === false) {
    out.push({ pointer, message: "값을 둘 수 없다" });
    return;
  }
  const issue = (message: string, at = pointer) => out.push({ pointer: at, message });
  const s = schema as Record<string, unknown>;
  if (typeof s.$ref === "string") {
    const [target, targetDoc] = resolve(s.$ref, doc);
    check(target, value, pointer, out, targetDoc);
  }
  if (s.type !== undefined) {
    const types = Array.isArray(s.type) ? (s.type as string[]) : [s.type as string];
    if (!types.some((t) => hasType(value, t))) {
      issue(`타입이 틀렸다. 기대: ${types.join("|")}, 실제: ${typeOf(value)}`);
      return;
    }
  }
  if ("const" in s && !jsonEqual(value, s.const)) {
    issue(`${JSON.stringify(s.const)}이어야 한다`);
  }
  if (Array.isArray(s.enum) && !s.enum.some((e) => jsonEqual(value, e))) {
    issue(`쓸 수 없는 값. 가능한 값: ${s.enum.map((e) => JSON.stringify(e)).join(", ")}`);
  }
  if (typeof value === "number") {
    if (typeof s.minimum === "number" && value < s.minimum) issue(`${s.minimum} 이상이어야 한다`);
    if (typeof s.maximum === "number" && value > s.maximum) issue(`${s.maximum} 이하여야 한다`);
  }
  if (typeof value === "string") {
    if (typeof s.minLength === "number" && [...value].length < s.minLength) {
      issue(`${s.minLength}글자 이상이어야 한다`);
    }
    if (typeof s.pattern === "string" && !regex(s.pattern).test(value)) {
      issue(`형식에 맞지 않는다 (규칙 ${s.pattern})`);
    }
  }
  if (Array.isArray(value)) {
    if (typeof s.minItems === "number" && value.length < s.minItems) {
      issue(`항목이 ${s.minItems}개 이상이어야 한다`);
    }
    if (typeof s.maxItems === "number" && value.length > s.maxItems) {
      issue(`항목이 ${s.maxItems}개 이하여야 한다`);
    }
    if (s.items !== undefined) {
      value.forEach((item, i) => check(s.items as Schema, item, `${pointer}/${i}`, out, doc));
    }
  }
  if (typeOf(value) === "object") {
    const obj = value as Record<string, unknown>;
    const props = (s.properties ?? {}) as Record<string, Schema>;
    for (const name of (s.required ?? []) as string[]) {
      if (!Object.hasOwn(obj, name)) issue(`필수 필드 '${name}'가 없다`);
    }
    for (const [key, item] of Object.entries(obj)) {
      const at = `${pointer}/${token(key)}`;
      if (Object.hasOwn(props, key)) {
        check(props[key]!, item, at, out, doc);
      } else if (s.additionalProperties === false) {
        issue(`알 수 없는 필드 '${key}'`, at);
      } else if (s.additionalProperties !== undefined) {
        check(s.additionalProperties as Schema, item, at, out, doc);
      }
    }
  }
  const passes = (sub: Schema) => {
    const found: SchemaIssue[] = [];
    check(sub, value, pointer, found, doc);
    return found;
  };
  if (s.if !== undefined) {
    const branch = passes(s.if as Schema).length === 0 ? s.then : s.else;
    if (branch !== undefined) check(branch as Schema, value, pointer, out, doc);
  }
  if (s.not !== undefined && passes(s.not as Schema).length === 0) {
    issue("허용되지 않는 모양이다 (not)");
  }
  for (const [keyword, needOne] of [
    ["anyOf", false],
    ["oneOf", true],
  ] as const) {
    const branches = s[keyword];
    if (!Array.isArray(branches)) continue;
    const results = branches.map((branch: Schema) => passes(branch));
    const passed = results.filter((r) => r.length === 0).length;
    if (passed === 0) {
      // 가장 덜 틀린 갈래의 이유를 보여 준다
      const best = results.reduce((a, b) => (b.length < a.length ? b : a));
      out.push(...best);
    } else if (needOne && passed > 1) {
      issue("둘 이상의 모양에 맞는다 (oneOf)");
    }
  }
}

function checkAgainst(schema: Schema, value: unknown): SchemaIssue[] {
  const out: SchemaIssue[] = [];
  checkJsonValue(value, out);
  if (out.length === 0) check(schema, value, "", out, root);
  return out;
}

/** `$defs`의 정의 하나로 값을 검사한다. 문제가 없으면 빈 목록. */
export function checkDef(name: string, value: unknown): SchemaIssue[] {
  const schema = defs[name];
  if (schema === undefined) throw new Error(`daemon-rpc에 정의 ${name}이(가) 없다`);
  return checkAgainst(schema, value);
}

/** 메서드의 params 검사. 모르는 메서드도 문제로 돌려준다. params 생략은 빈 객체로 본다. */
export function checkParams(method: string, params: unknown): SchemaIssue[] {
  if (!isMethodName(method)) return [{ pointer: "", message: `모르는 메서드 '${method}'` }];
  return checkDef(METHODS[method].params, params === undefined ? {} : params);
}

/** 메서드의 result 검사. */
export function checkResult(method: string, result: unknown): SchemaIssue[] {
  if (!isMethodName(method)) return [{ pointer: "", message: `모르는 메서드 '${method}'` }];
  return checkDef(METHODS[method].result, result);
}

/** 알림의 params 검사. 모르는 알림도 문제로 돌려준다. */
export function checkNotification(name: string, params: unknown): SchemaIssue[] {
  if (!isNotificationName(name)) return [{ pointer: "", message: `모르는 알림 '${name}'` }];
  return checkDef(NOTIFICATIONS[name], params === undefined ? {} : params);
}

/** 메시지 봉투 검사 (Request·Notification·SuccessResponse·DaemonErrorResponse 중 하나). */
export function checkMessage(message: unknown): SchemaIssue[] {
  return checkAgainst(root as unknown as Schema, message);
}
