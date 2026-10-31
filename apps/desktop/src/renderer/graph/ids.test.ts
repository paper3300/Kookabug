// 노드 ID (M2 계획 2.6 "편집 규칙", T9 완료 기준 ids.test.ts)
import { expect, test } from "vitest";
import { readCorpus } from "./corpus.testutil";
import { NODE_ID_PATTERN, newNodeId, takenIds, type RandomBytes } from "./ids";

const ALPHABET = "abcdefghijklmnopqrstuvwxyz234567";

/** 정해 둔 ID들을 차례로 내는 무작위 바이트 */
function scripted(ids: string[]): RandomBytes & { calls: number } {
  const fn = Object.assign(
    (n: number) => {
      const id = ids[fn.calls++];
      expect(n).toBe(8);
      return Uint8Array.from([...id.slice(2)].map((c) => ALPHABET.indexOf(c)));
    },
    { calls: 0 },
  );
  return fn;
}

test("test_id_format_and_collision_retry", () => {
  // 노드·접힌 그룹·주석 ID를 모두 피한다
  const value = {
    nodes: { n_aaaaaaaa: { type: "core.test.pass", version: 1 } },
    layout: {
      collapsed: { n_bbbbbbbb: { nodes: [], x: 0, y: 0 } },
      comments: { n_cccccccc: { rect: [0, 0, 10, 10], text: "" } },
    },
  };
  const taken = takenIds(value);
  expect([...taken].sort()).toEqual(["n_aaaaaaaa", "n_bbbbbbbb", "n_cccccccc"]);
  const random = scripted(["n_aaaaaaaa", "n_bbbbbbbb", "n_cccccccc", "n_d2345677"]);
  expect(newNodeId(taken, random)).toBe("n_d2345677");
  expect(random.calls).toBe(4);

  // 형식: n_ + 소문자 base32 8자 (스키마 NodeId 패턴 안)
  const seen = new Set<string>();
  for (let i = 0; i < 2000; i++) {
    const id = newNodeId(seen);
    expect(id).toMatch(NODE_ID_PATTERN);
    expect(id).toMatch(/^[A-Za-z_][A-Za-z0-9_-]{0,63}$/);
    expect(seen.has(id)).toBe(false);
    seen.add(id);
  }

  // 말뭉치의 그룹·주석 ID도 모은다
  const groups = readCorpus("fixtures/graph-corpus/groups-comments.graph.json");
  const ids = takenIds(groups);
  const layout = groups.layout as { collapsed: object; comments: object };
  for (const id of [...Object.keys(groups.nodes as object), ...Object.keys(layout.collapsed), ...Object.keys(layout.comments)]) {
    expect(ids.has(id), id).toBe(true);
  }
});
