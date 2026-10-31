import { describe, expect, test } from "vitest";
import {
  badgeOf,
  buildTree,
  defaultExpanded,
  displayName,
  filterQuickOpen,
  glyphOf,
  quickOpenItems,
  visibleRows,
  type TreeEntry,
} from "./tree";

// workspace.tree 결과 모양 (경로순 평평한 목록)
const ENTRIES: TreeEntry[] = [
  { path: ".kookabug", type: "dir", name_only: true, git_ignored: true },
  { path: "AGENTS.md", type: "file", kind: "agents" },
  { path: "kookabug.json", type: "file", kind: "workspace" },
  { path: "kookabug.lock", type: "file", kind: "lock" },
  { path: "runs", type: "dir", name_only: true, git_ignored: true },
  { path: "screens", type: "dir" },
  { path: "screens/title.screen.json", type: "file", kind: "screen" },
  { path: "subgraphs", type: "dir" },
  { path: "subgraphs/login.graph.json", type: "file", kind: "graph", graph_kind: "subgraph" },
  { path: "targets", type: "dir" },
  { path: "targets/login", type: "dir" },
  { path: "targets/login/button.png", type: "file", kind: "other" },
  { path: "targets/login/button.target.json", type: "file", kind: "target" },
  { path: "targets/title.target.json", type: "file", kind: "target" },
  { path: "tests", type: "dir" },
  { path: "tests/enchant", type: "dir" },
  { path: "tests/enchant/장비 강화 반복.graph.json", type: "file", kind: "graph", graph_kind: "test" },
  { path: "tests/broken.graph.json", type: "file", kind: "graph", problem: "JSON이 아니다 (3:1)" },
  { path: "tests/smoke.graph.json", type: "file", kind: "graph", graph_kind: "test" },
];

describe("탐색기 트리", () => {
  test("최상위는 시안 순서, .kookabug는 숨긴다, 폴더 먼저", () => {
    const nodes = buildTree(ENTRIES);
    expect(nodes.map((n) => n.name)).toEqual([
      "tests",
      "subgraphs",
      "targets",
      "screens",
      "runs",
      "kookabug.json",
      "kookabug.lock",
      "AGENTS.md",
    ]);
    const tests = nodes[0];
    expect(tests.children.map((n) => n.name)).toEqual(["enchant", "broken.graph.json", "smoke.graph.json"]);
  });

  test("펼친 폴더만 줄로 나온다 (처음에는 tests만 펼침)", () => {
    const nodes = buildTree(ENTRIES);
    const expanded = defaultExpanded(nodes);
    expect([...expanded]).toEqual(["tests"]);
    const rows = visibleRows(nodes, expanded);
    expect(rows.slice(0, 5).map((r) => [r.node.name, r.depth])).toEqual([
      ["tests", 0],
      ["enchant", 1],
      ["broken.graph.json", 1],
      ["smoke.graph.json", 1],
      ["subgraphs", 0],
    ]);
    const deeper = visibleRows(nodes, new Set(["tests", "tests/enchant"]));
    expect(deeper[2]).toMatchObject({ depth: 2, node: { name: "장비 강화 반복.graph.json" } });
  });

  test("앞 글자·배지", () => {
    const nodes = buildTree(ENTRIES);
    const byPath = new Map(visibleRows(nodes, new Set(["tests", "subgraphs", "targets", "screens"])).map((r) => [r.node.path, r.node]));
    expect(glyphOf(byPath.get("tests/smoke.graph.json")!)).toEqual({ glyph: "T", tone: "test" });
    expect(glyphOf(byPath.get("subgraphs/login.graph.json")!)).toEqual({ glyph: "S", tone: "test" });
    expect(glyphOf(byPath.get("kookabug.json")!)).toEqual({ glyph: "{}", tone: "json" });
    expect(glyphOf(byPath.get("AGENTS.md")!)).toEqual({ glyph: "MD", tone: "md" });
    expect(glyphOf(byPath.get("tests")!)).toBeNull();
    // 읽을 수 없는 그래프는 빨강·오류 배지(이유는 툴팁)
    expect(glyphOf(byPath.get("tests/broken.graph.json")!)?.tone).toBe("error");
    expect(badgeOf(byPath.get("tests/broken.graph.json")!, false)).toEqual({
      text: "오류",
      tone: "error",
      title: "JSON이 아니다 (3:1)",
    });
    expect(badgeOf(byPath.get("runs")!, true)).toEqual({ text: "Git 제외", tone: "muted" });
    expect(badgeOf(byPath.get("targets")!, true)).toEqual({ text: "2", tone: "muted" });
    expect(badgeOf(byPath.get("tests")!, true)).toBeNull();
  });

  test("Ctrl+P 목록은 그래프·target만, 이름 일치를 먼저", () => {
    const items = quickOpenItems(ENTRIES);
    expect(items.map((i) => i.path)).toEqual([
      "subgraphs/login.graph.json",
      "targets/login/button.target.json",
      "targets/title.target.json",
      "tests/broken.graph.json",
      "tests/enchant/장비 강화 반복.graph.json",
      "tests/smoke.graph.json",
    ]);
    expect(filterQuickOpen(items, "LOGIN").map((i) => i.path)).toEqual([
      "subgraphs/login.graph.json", // 이름에 맞음
      "targets/login/button.target.json", // 경로에만 맞음
    ]);
    expect(filterQuickOpen(items, "강화").map((i) => i.name)).toEqual(["장비 강화 반복"]);
    expect(filterQuickOpen(items, "  ")).toHaveLength(items.length);
    expect(displayName("targets/login/button.target.json")).toBe("button");
  });
});
