// 보기 탭의 JSON 들여쓰기·구문 색 (다듬기 P1-B). 값으로 바꾸지 않고 낱말만 다시 늘어놓는다: JSON.parse는 큰 정수를
// 잃고 숫자 같은 키 순서를 바꾸지만, 여기서는 원문 낱말(숫자·문자열 글자)과 키 순서를 그대로 둔다.
// 순수 함수라 vitest로 본다

export type SegKind = "key" | "string" | "number" | "literal" | "punct";

export interface Seg {
  kind: SegKind;
  text: string;
}

export interface JsonLine {
  depth: number;
  segs: Seg[];
}

type Token = { kind: "string" | "number" | "literal" | "punct"; text: string };

const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const STRING = /"(?:[^"\\\u0000-\u001f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"/y;
const LITERAL = /true|false|null/y;
const SPACE = /[ \t\n\r]*/y;
/** 이보다 깊으면 색 없이 원문으로 보인다 (스택 보호) */
export const MAX_DEPTH = 256;

function tokenize(text: string): Token[] | null {
  const tokens: Token[] = [];
  let i = text.charCodeAt(0) === 0xfeff ? 1 : 0;
  const match = (re: RegExp): string | null => {
    re.lastIndex = i;
    const m = re.exec(text);
    if (m === null || m[0] === "") return null;
    i += m[0].length;
    return m[0];
  };
  for (;;) {
    SPACE.lastIndex = i;
    SPACE.exec(text);
    i = SPACE.lastIndex;
    if (i >= text.length) return tokens;
    const c = text[i];
    if ("{}[]:,".includes(c)) {
      tokens.push({ kind: "punct", text: c });
      i++;
      continue;
    }
    let t: string | null;
    if (c === '"') {
      if ((t = match(STRING)) === null) return null;
      tokens.push({ kind: "string", text: t });
    } else if (c === "-" || (c >= "0" && c <= "9")) {
      if ((t = match(NUMBER)) === null) return null;
      tokens.push({ kind: "number", text: t });
    } else if ((t = match(LITERAL)) !== null) {
      tokens.push({ kind: "literal", text: t });
    } else {
      return null;
    }
  }
}

/**
 * JSON 원문 → 두 칸 들여쓴 줄. 빈 객체·배열은 한 줄(`{}`·`[]`)이다. JSON이 아니면(문법 오류·너무 깊음) null
 */
export function formatJson(text: string): JsonLine[] | null {
  const tokens = tokenize(text);
  if (tokens === null || tokens.length === 0) return null;
  const lines: JsonLine[] = [{ depth: 0, segs: [] }];
  let i = 0;
  const add = (kind: SegKind, t: string) => lines[lines.length - 1].segs.push({ kind, text: t });
  const newLine = (depth: number) => lines.push({ depth, segs: [] });
  const isPunct = (t: Token | undefined, p: string) => t !== undefined && t.kind === "punct" && t.text === p;

  const value = (depth: number): boolean => {
    if (depth > MAX_DEPTH) return false;
    const t = tokens[i++];
    if (t === undefined) return false;
    if (t.kind !== "punct") {
      add(t.kind, t.text);
      return true;
    }
    if (t.text !== "{" && t.text !== "[") return false;
    const object = t.text === "{";
    const close = object ? "}" : "]";
    add("punct", t.text);
    if (isPunct(tokens[i], close)) {
      i++;
      add("punct", close);
      return true;
    }
    for (;;) {
      newLine(depth + 1);
      if (object) {
        const key = tokens[i++];
        if (key === undefined || key.kind !== "string" || !isPunct(tokens[i], ":")) return false;
        i++;
        add("key", key.text);
        add("punct", ": ");
      }
      if (!value(depth + 1)) return false;
      const next = tokens[i++];
      if (isPunct(next, ",")) {
        add("punct", ",");
        continue;
      }
      if (!isPunct(next, close)) return false;
      newLine(depth);
      add("punct", close);
      return true;
    }
  };

  if (!value(0) || i !== tokens.length) return null;
  return lines;
}
