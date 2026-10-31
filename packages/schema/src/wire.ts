// 전송 코덱 (M2 계획 2.6). JS 값을 daemon으로 보내는 JSON 텍스트로 바꾸는 곳은 모두 이것 하나를 쓴다.
//
// - 비유한 수(NaN·±Infinity)는 먼저 거부한다. JSON.stringify처럼 null로 바꾸지 않는다
// - 안전 범위(±(2^53-1)) 밖의 정수값인 수는 지수 표기(`1e+20`)로 쓴다. JS에는 그런 정수가 정확히 있을
//   수 없고 파일 규칙상 금지이므로 원래 실수다. Python json.loads가 지수 토큰을 float로 읽어 타입이
//   돌아온다 (canonical의 "2^53보다 큰 정수 값의 실수는 지수 표기"와 같다)
// - 그 밖의 값은 JSON.stringify와 같다
//
// Python 검사가 Node로 이 파일을 직접 불러 쓴다(타입 제거 실행). 지울 수 있는 타입 문법만 쓴다.

/** 보낼 수 없는 값. `pointer`는 값 안 위치(JSON 포인터, 최상위는 ""). */
export class WireValueError extends Error {
  readonly pointer: string;

  constructor(pointer: string, message: string) {
    super(`${pointer || "/"}: ${message}`);
    this.name = "WireValueError";
    this.pointer = pointer;
  }
}

function escapeToken(key: string): string {
  return key.replace(/~/g, "~0").replace(/\//g, "~1");
}

function numberToken(n: number, pointer: string): string {
  if (!Number.isFinite(n)) {
    throw new WireValueError(pointer, `${n}는 JSON 숫자가 아니다 (NaN·Infinity)`);
  }
  if (Number.isInteger(n) && Math.abs(n) > Number.MAX_SAFE_INTEGER) {
    // toExponential()은 값을 되살리는 가장 짧은 자릿수를 쓴다 (9.007199254740992e+15)
    return n.toExponential();
  }
  return JSON.stringify(n);
}

/** JSON.stringify가 그 자리에서 빼거나 null로 바꾸는 값 */
function isSkipped(value: unknown): boolean {
  return value === undefined || typeof value === "function" || typeof value === "symbol";
}

function encode(value: unknown, pointer: string, stack: Set<object>): string | undefined {
  if (value !== null && typeof value === "object" && "toJSON" in value) {
    const toJSON = (value as { toJSON: unknown }).toJSON;
    if (typeof toJSON === "function") value = toJSON.call(value, pointer.split("/").pop() ?? "");
  }
  if (value === null) return "null";
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      return numberToken(value, pointer);
    case "string":
      return JSON.stringify(value);
    case "bigint":
      throw new WireValueError(pointer, "BigInt는 JSON 값이 아니다");
    case "undefined":
    case "function":
    case "symbol":
      return undefined;
  }
  const object = value as object;
  if (stack.has(object)) throw new WireValueError(pointer, "값이 자기 자신을 담고 있다 (순환)");
  stack.add(object);
  try {
    if (Array.isArray(object)) {
      // map·forEach는 빈 칸(희소 배열)을 건너뛰므로 길이만큼 직접 돈다. 빈 칸은 JSON.stringify처럼 null
      const items: string[] = [];
      for (let i = 0; i < object.length; i++) {
        const item: unknown = object[i];
        const out = isSkipped(item) ? undefined : encode(item, `${pointer}/${i}`, stack);
        items.push(out ?? "null");
      }
      return `[${items.join(",")}]`;
    }
    if (object instanceof Number) return numberToken(object.valueOf(), pointer);
    if (object instanceof String) return JSON.stringify(object.valueOf());
    if (object instanceof Boolean) return object.valueOf() ? "true" : "false";
    const parts: string[] = [];
    for (const key of Object.keys(object)) {
      const out = encode((object as Record<string, unknown>)[key], `${pointer}/${escapeToken(key)}`, stack);
      if (out !== undefined) parts.push(`${JSON.stringify(key)}:${out}`);
    }
    return `{${parts.join(",")}}`;
  } finally {
    stack.delete(object);
  }
}

/**
 * JS 값 → daemon으로 보내는 JSON 텍스트. 보낼 수 없는 값이면 `WireValueError`를 던지고 아무것도
 * 만들지 않는다.
 */
export function wireStringify(value: unknown): string {
  const out = encode(value, "", new Set());
  if (out === undefined) throw new WireValueError("", "JSON 값이 아니다 (undefined·함수·심볼)");
  return out;
}
