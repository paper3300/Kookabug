import fc from "fast-check";
import { describe, expect, test } from "vitest";
import { WireValueError, wireStringify } from "./wire.js";

test("test_unsafe_integral_numbers_exponent", () => {
  // 원래 Python float였던 큰 실수는 지수 표기로 나가 float로 돌아온다 (M2 계획 2.6, 검수 H1)
  expect(wireStringify(1e20)).toBe("1e+20");
  expect(wireStringify(2 ** 53)).toBe("9.007199254740992e+15");
  expect(wireStringify(1.2345678901234567e19)).toBe("1.2345678901234567e+19");
  expect(wireStringify(-1e20)).toBe("-1e+20");
  expect(wireStringify(Number.MAX_VALUE)).toBe("1.7976931348623157e+308");
  expect(wireStringify({ a: [1e20, { b: 2 ** 60 }] })).toBe(
    '{"a":[1e+20,{"b":1.152921504606847e+18}]}',
  );
  // JSON.stringify는 범위 밖 정수 토큰을 만든다 (Python에서 int로 읽혀 거부됨)
  expect(JSON.stringify(1e20)).toBe("100000000000000000000");
});

test("test_safe_and_fractional_same_as_json_stringify", () => {
  const values: unknown[] = [
    0,
    -0,
    1,
    -1,
    Number.MAX_SAFE_INTEGER,
    -Number.MAX_SAFE_INTEGER,
    1.5,
    1e-7,
    1e21 + 0.5,
    0.1,
    "é 한글 \ud800 \u0000",
    true,
    false,
    null,
    [],
    {},
    { b: 1, a: [1, "x", null], "10": 2, __proto__x: 3 },
    [undefined, () => 1, Symbol("s")],
    { skip: undefined, f: () => 1 },
    JSON.parse('{"__proto__": {"x": 1}, "constructor": 2}'),
  ];
  for (const value of values) {
    expect(wireStringify(value)).toBe(JSON.stringify(value));
  }
});

test("test_shortest_roundtrip_digits", () => {
  fc.assert(
    fc.property(fc.double({ noNaN: true, noDefaultInfinity: true }), (n) => {
      const text = wireStringify(n);
      expect(JSON.parse(text)).toBe(n === 0 ? 0 : n);
      // 범위 안 정수·실수는 JSON.stringify와 같은 토큰이다
      if (!(Number.isInteger(n) && Math.abs(n) > Number.MAX_SAFE_INTEGER)) {
        expect(text).toBe(JSON.stringify(n));
      }
    }),
    { numRuns: 20000 },
  );
});

describe("test_non_finite_rejected_with_pointer", () => {
  const cases = [
    ["NaN", Number.NaN],
    ["Infinity", Number.POSITIVE_INFINITY],
    ["-Infinity", Number.NEGATIVE_INFINITY],
  ] as const;
  const places: [string, (n: number) => unknown, string][] = [
    ["최상위", (n) => n, ""],
    ["객체 안", (n) => ({ nodes: { "a/b~c": { in: { x: n } } } }), "/nodes/a~1b~0c/in/x"],
    ["배열 안", (n) => ({ list: [1, [2, n]] }), "/list/1/1"],
  ];
  for (const [label, n] of cases) {
    for (const [where, wrap, pointer] of places) {
      test(`[${label}, ${where}]`, () => {
        let error: unknown;
        try {
          wireStringify(wrap(n));
        } catch (e) {
          error = e;
        }
        // JSON.stringify처럼 null로 보내지 않는다 (2차 검수 N3)
        expect(error).toBeInstanceOf(WireValueError);
        expect((error as WireValueError).pointer).toBe(pointer);
      });
    }
  }
});

test("test_sparse_arrays_same_as_json_stringify", () => {
  // 빈 칸은 null. 길이가 바뀌거나 `[,]` 같은 틀린 JSON이 되면 안 된다 (T2 검수 1)
  const cases: unknown[] = [
    { values: Array(1) },
    { values: Array(2) },
    { values: [1, , 3] },
    { nested: [[, 1], Array(3), [[, ,]]] },
    Array(4),
  ];
  for (const value of cases) {
    const text = wireStringify(value);
    expect(text).toBe(JSON.stringify(value));
    expect(() => JSON.parse(text)).not.toThrow();
  }
  expect(wireStringify({ values: Array(1) })).toBe('{"values":[null]}');
  expect(wireStringify({ values: [1, , 3] })).toBe('{"values":[1,null,3]}');
});

test("test_cycle_and_bigint_rejected", () => {
  const cyclic: Record<string, unknown> = {};
  cyclic.self = cyclic;
  expect(() => wireStringify(cyclic)).toThrow(WireValueError);
  expect(() => wireStringify({ n: 1n })).toThrow(WireValueError);
  expect(() => wireStringify(undefined)).toThrow(WireValueError);
});
