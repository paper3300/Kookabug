// 값 편집 도우미 (M2 계획 2.6 "`__proto__` 키", T9 완료 기준 valueOps.test.ts)
import { describe, expect, test } from "vitest";
import { deepFreeze, readCorpus } from "./corpus.testutil";
import { copyObject, deleteIn, getIn, jsonEqual, setIn } from "./valueOps";

describe("valueOps", () => {
  test("test_proto_and_constructor_keys_safe", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/proto-keys.graph.json"));
    const nodes = value.nodes as Record<string, unknown>;
    expect(Object.hasOwn(nodes, "__proto__")).toBe(true);

    // 자기 키 `__proto__`·`constructor` 안쪽을 고쳐도 프로토타입은 그대로다
    const a = setIn(value, ["nodes", "__proto__", "in", "constructor"], "바뀜");
    const aNodes = a.nodes as Record<string, unknown>;
    expect(Object.getPrototypeOf(aNodes)).toBe(Object.prototype);
    expect(Object.hasOwn(aNodes, "__proto__")).toBe(true);
    expect(getIn(a, ["nodes", "__proto__", "in", "constructor"])).toBe("바뀜");
    expect(getIn(a, ["nodes", "__proto__", "in", "__proto__"])).toBe(1);
    expect(getIn(a, ["nodes", "__proto__", "config", "constructor", "prototype"])).toBe(3);

    // 없는 `__proto__` 키를 새로 쓰면 자기 속성이 된다 (프로토타입을 바꾸지 않음)
    const b = setIn({ nodes: {} }, ["nodes", "__proto__"], { polluted: true });
    expect(Object.getPrototypeOf(b.nodes)).toBe(Object.prototype);
    expect(Object.keys(b.nodes)).toEqual(["__proto__"]);
    expect(({} as Record<string, unknown>).polluted).toBeUndefined();

    // constructor는 프로토타입 쪽 이름이라 없는 것으로 읽는다
    expect(getIn({}, ["constructor"])).toBeUndefined();
    const c = setIn({}, ["constructor", "x"], 1);
    expect(Object.hasOwn(c, "constructor")).toBe(true);
    expect(getIn(c, ["constructor", "x"])).toBe(1);

    // 사본·지우기도 자기 키 그대로
    const copy = copyObject(nodes);
    expect(Object.keys(copy)).toEqual(Object.keys(nodes));
    expect(Object.getPrototypeOf(copy)).toBe(Object.prototype);
    const d = deleteIn(value, ["nodes", "__proto__"]);
    expect(Object.keys(d.nodes as object)).toEqual(["constructor", "n_entry"]);
    expect(Object.getPrototypeOf(d.nodes)).toBe(Object.prototype);
    expect(jsonEqual(value, readCorpus("fixtures/graph-corpus/proto-keys.graph.json"))).toBe(true);
  });

  test("test_set_only_touches_path", () => {
    const value = deepFreeze(readCorpus("fixtures/graph-corpus/unknown-keys.graph.json"));
    const next = setIn(value, ["nodes", "n_pass", "in", "reason"], "바뀜");
    // 지나간 경로만 새 객체, 나머지는 같은 참조 (구조 공유)
    expect(next).not.toBe(value);
    expect(next.nodes).not.toBe(value.nodes);
    expect(next.layout).toBe(value.layout);
    expect(next.x_editor).toBe(value.x_editor);
    expect(getIn(next, ["nodes", "n_entry"])).toBe(getIn(value, ["nodes", "n_entry"]));
    expect(getIn(next, ["nodes", "n_pass", "config"])).toBe(getIn(value, ["nodes", "n_pass", "config"]));
    expect(getIn(next, ["nodes", "n_pass", "in", "x_unknown_pin"])).toBe(
      getIn(value, ["nodes", "n_pass", "in", "x_unknown_pin"]),
    );
    expect(getIn(next, ["nodes", "n_pass", "x_note"])).toBe("노드의 모르는 키");
    // 바뀐 것은 그 키 하나
    expect(jsonEqual(setIn(next, ["nodes", "n_pass", "in", "reason"], "끝"), value)).toBe(true);
    // 같은 값을 쓰면 같은 루트
    expect(setIn(value, ["nodes", "n_pass", "in", "reason"], "끝")).toBe(value);
    // 키 순서는 그대로, 새 키는 끝에
    expect(Object.keys(getIn(next, ["nodes", "n_pass"]) as object)).toEqual(Object.keys(getIn(value, ["nodes", "n_pass"]) as object));
    const added = setIn(value, ["nodes", "n_pass", "title"], "t");
    expect(Object.keys(getIn(added, ["nodes", "n_pass"]) as object).at(-1)).toBe("title");

    // 지우기와 빈 부모 정리
    const cut = deleteIn(value, ["nodes", "n_entry", "next", "start"], 1);
    expect(Object.hasOwn(getIn(cut, ["nodes", "n_entry"]) as object, "next")).toBe(false);
    expect(getIn(cut, ["nodes", "n_entry", "type"])).toBe("core.graph.entry");
    const kept = deleteIn(value, ["nodes", "n_entry", "next", "start"]);
    expect(getIn(kept, ["nodes", "n_entry", "next"])).toEqual({});
    expect(deleteIn(value, ["nodes", "없음"])).toBe(value);

    // 배열 원소
    const arr = setIn({ a: [1, 2, 3] }, ["a", 1], 9);
    expect(arr.a).toEqual([1, 9, 3]);
    expect(() => setIn({ a: [1] }, ["a", 5], 0)).toThrow(RangeError);
  });

  test("jsonEqual: 키 순서 무관, 수는 값 비교", () => {
    expect(jsonEqual({ a: 1, b: [1, { c: null }] }, { b: [1, { c: null }], a: 1.0 })).toBe(true);
    expect(jsonEqual(-0, 0)).toBe(true);
    expect(jsonEqual({ a: 1 }, { a: 1, b: undefined })).toBe(false);
    expect(jsonEqual([1, 2], [2, 1])).toBe(false);
    expect(jsonEqual({ a: true }, { a: 1 })).toBe(false);
    expect(jsonEqual(null, {})).toBe(false);
  });
});
