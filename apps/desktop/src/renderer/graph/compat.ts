// 연결 끌기 중 핀 호환 (M2 계획 2.11 "끌어 놓기 중 핀 호환 표시", T9). 호환 핀은 강조하고 아니면 흐리게
// 그리며, 호환하지 않는 핀에는 놓을 수 없다. 타입 규칙은 코어 `validate/types.assignable`과 같다. 최종 판정은
// daemon 검증이다 (타입을 모르는 핀은 막지 않는다)

export interface PinEnd {
  node: string;
  handle: string;
  /** source = 오른쪽(출구·출력), target = 왼쪽(흐름 입력·데이터 입력) */
  side: "source" | "target";
  kind: "exec" | "data";
  /** 데이터 핀 타입 (모르면 null) */
  type: string | null;
}

type PinType =
  | { t: "named"; name: string }
  | { t: "list"; item: PinType }
  | { t: "dict"; value: PinType }
  | { t: "union"; options: PinType[] };

/** 최상위 `|`·`,`로 나눈다 (괄호 안은 나누지 않는다) */
function splitTop(text: string, sep: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "[") depth++;
    else if (c === "]") depth--;
    else if (c === sep && depth === 0) {
      out.push(text.slice(start, i));
      start = i + 1;
    }
  }
  out.push(text.slice(start));
  return out.map((s) => s.trim());
}

export function parsePinType(text: string): PinType {
  const parts = splitTop(text, "|");
  if (parts.length > 1) return { t: "union", options: parts.map(parsePinType) };
  const t = parts[0];
  const m = /^(list|dict)\[(.*)\]$/.exec(t);
  if (m !== null) {
    if (m[1] === "list") return { t: "list", item: parsePinType(m[2]) };
    const args = splitTop(m[2], ",");
    return { t: "dict", value: parsePinType(args[args.length - 1]) };
  }
  return { t: "named", name: t };
}

/** 출력 타입 src를 입력 타입 dst에 연결할 수 있는가 (코어 assignable) */
export function assignable(src: PinType, dst: PinType): boolean {
  if (src.t === "union") return src.options.every((o) => assignable(o, dst));
  if (dst.t === "union") return dst.options.some((o) => assignable(src, o));
  if ((dst.t === "named" && dst.name === "any") || (src.t === "named" && src.name === "any")) return true;
  if (src.t === "named" && dst.t === "named") {
    return src.name === dst.name || (src.name === "int" && dst.name === "float");
  }
  if (src.t === "list" && dst.t === "list") return assignable(src.item, dst.item);
  if (src.t === "dict" && dst.t === "dict") return assignable(src.value, dst.value);
  return false;
}

/** 두 핀을 이을 수 있는가 (어느 쪽에서 끌기 시작했든) */
export function compatible(a: PinEnd, b: PinEnd): boolean {
  if (a.node === b.node || a.side === b.side || a.kind !== b.kind) return false;
  if (a.kind === "exec") return true;
  const src = a.side === "source" ? a : b;
  const dst = a.side === "source" ? b : a;
  if (src.type === null || dst.type === null) return true;
  return assignable(parsePinType(src.type), parsePinType(dst.type));
}
