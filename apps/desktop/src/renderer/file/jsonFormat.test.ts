// 보기 탭 JSON 들여쓰기·구문 색 (다듬기 P1-B)
import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { formatJson, MAX_DEPTH, type JsonLine } from "./jsonFormat";

/** 줄을 글로 (들여쓰기 두 칸) */
function render(lines: JsonLine[]): string {
  return lines.map((l) => "  ".repeat(l.depth) + l.segs.map((s) => s.text).join("")).join("\n");
}

describe("formatJson", () => {
  test("두 칸 들여쓰기와 낱말 종류", () => {
    const lines = formatJson('{"a":1,"b":[true,null,"x"],"c":{}, "d":[]}')!;
    expect(render(lines)).toBe(
      ['{', '  "a": 1,', '  "b": [', "    true,", "    null,", '    "x"', "  ],", '  "c": {},', '  "d": []', "}"].join("\n"),
    );
    const kinds = lines[1].segs.map((s) => s.kind);
    expect(kinds).toEqual(["key", "punct", "number", "punct"]);
    expect(lines[3].segs[0]).toEqual({ kind: "literal", text: "true" });
    expect(lines[5].segs[0]).toEqual({ kind: "string", text: '"x"' });
  });

  test("원문 낱말을 그대로 둔다 (큰 정수·지수·숫자 키 순서·이스케이프)", () => {
    const text = '{"2":"b","1":"a","big":12345678901234567890,"e":1.5E+3,"s":"\\u00e9\\n\\"q\\""}';
    const out = render(formatJson(text)!);
    expect(out).toContain('"2": "b",\n  "1": "a"');
    expect(out).toContain('"big": 12345678901234567890');
    expect(out).toContain('"e": 1.5E+3');
    expect(out).toContain('"s": "\\u00e9\\n\\"q\\""');
  });

  test("BOM·앞뒤 공백·맨 값 하나", () => {
    expect(render(formatJson('﻿  \r\n{"a": 1}\n')!)).toBe('{\n  "a": 1\n}');
    expect(render(formatJson(" 42 ")!)).toBe("42");
    expect(render(formatJson('"글자"')!)).toBe('"글자"');
  });

  test.each([
    ["", "빈 글"],
    ["{", "닫지 않음"],
    ['{"a" 1}', "콜론 없음"],
    ['{"a":1,}', "끝 쉼표"],
    ["[1 2]", "쉼표 없음"],
    ["{a:1}", "따옴표 없는 키"],
    ["[1]]", "남는 낱말"],
    ["01", "앞 0"],
    ['"a\u0001"', "제어 문자"],
    ["// x\n{}", "주석"],
    ["[tru]", "틀린 리터럴"],
  ])("JSON이 아니면 null: %j (%s)", (text) => {
    expect(formatJson(text)).toBeNull();
  });

  test("너무 깊으면 null (색 없이 원문)", () => {
    expect(formatJson("[".repeat(MAX_DEPTH) + "]".repeat(MAX_DEPTH))).not.toBeNull();
    expect(formatJson("[".repeat(MAX_DEPTH + 2) + "]".repeat(MAX_DEPTH + 2))).toBeNull();
  });

  test("들여쓴 결과는 같은 값이고 JSON.stringify 두 칸 들여쓰기와 같다 (속성)", () => {
    // 키는 숫자 같지 않은 이름만 (JSON.parse가 순서를 바꾸지 않게), 숫자는 정수·안전 범위
    const key = fc.string({ minLength: 1, maxLength: 6 }).filter((k) => !/^\d+$/.test(k));
    const leaf = fc.oneof(fc.boolean(), fc.constant(null), fc.integer(), fc.string({ maxLength: 8 }));
    const value = fc.letrec((tie) => ({
      node: fc.oneof({ depthSize: "small" }, leaf, tie("array"), tie("object")),
      array: fc.array(tie("node"), { maxLength: 4 }),
      object: fc.dictionary(key, tie("node"), { maxKeys: 4 }),
    })).node;
    fc.assert(
      fc.property(value, (v) => {
        const lines = formatJson(JSON.stringify(v));
        expect(lines).not.toBeNull();
        const out = render(lines!);
        expect(JSON.parse(out)).toEqual(v);
        expect(out).toBe(JSON.stringify(v, null, 2));
      }),
      { numRuns: 300 },
    );
  });
});
