import { readFileSync } from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { wireStringify } from "./wire.js";

// 그래프 원문 말뭉치 (fixtures/graph-corpus/corpus.json). Python·E2E와 같은 목록을 쓴다
const repo = path.resolve(import.meta.dirname, "../../..");
const manifest = JSON.parse(
  readFileSync(path.join(repo, "fixtures/graph-corpus/corpus.json"), "utf8"),
) as { files: string[] };

/** JSON 값으로 같은가 (+0과 -0은 같다. JSON.stringify가 -0을 0으로 쓴다) */
function sameJson(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return a === b;
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => sameJson(x, b[i]));
  }
  if (a !== null && b !== null && typeof a === "object" && typeof b === "object") {
    const ka = Object.keys(a);
    return (
      ka.length === Object.keys(b).length &&
      ka.every(
        (k) =>
          Object.hasOwn(b, k) &&
          sameJson((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k]),
      )
    );
  }
  return a === b;
}

test.each(manifest.files)("test_corpus_roundtrip_through_codec[%s]", (rel) => {
  const value: unknown = JSON.parse(readFileSync(path.join(repo, rel), "utf8"));
  const sent = wireStringify(value);
  expect(sameJson(JSON.parse(sent), value)).toBe(true);
});

test("test_corpus_numbers_sent_as_exponent", () => {
  const text = readFileSync(path.join(repo, "fixtures/graph-corpus/numbers.graph.json"), "utf8");
  const sent = wireStringify(JSON.parse(text));
  expect(sent).toContain('"big":1e+20');
  expect(sent).toContain('"two_53_float":9.007199254740992e+15');
  expect(sent).toContain('"big_digits":1.2345678901234567e+19');
  expect(sent).not.toMatch(/[0-9]{17,}/);
  // __proto__ 키는 JSON.parse가 자기 속성으로 만들고 코덱이 그대로 보낸다
  const proto = readFileSync(path.join(repo, "fixtures/graph-corpus/proto-keys.graph.json"), "utf8");
  const nodes = (JSON.parse(wireStringify(JSON.parse(proto))) as { nodes: object }).nodes;
  expect(Object.keys(nodes).sort()).toEqual(["__proto__", "constructor", "n_entry"]);
});
