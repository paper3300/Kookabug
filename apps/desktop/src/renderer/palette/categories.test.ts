// 분류 표가 코어 노드의 모든 category를 담는다 (M2 계획 2.7 "팔레트"), 팔레트 묶음·검색 (T9)
import { describe, expect, test } from "vitest";
import { readCoreSchema } from "../graph/corpus.testutil";
import { indexNodeTypes } from "../graph/mapping";
import { CORE_CATEGORIES, PALETTE_GROUPS, PLUGIN_CATEGORY, categoryInfo } from "./categories";
import { groupKey, matches, paletteGroups } from "./groups";

const core = readCoreSchema() as { nodes: { category: string; type: string; engine?: string }[] };

test("test_all_core_categories_mapped", () => {
  const categories = new Set(core.nodes.map((n) => n.category));
  expect(categories.size).toBeGreaterThan(5);
  for (const c of categories) expect(Object.hasOwn(CORE_CATEGORIES, c), c).toBe(true);
  // 표의 분류는 모두 팔레트 묶음에 있다
  const groups = new Set(PALETTE_GROUPS.map((g) => g.group));
  for (const c of Object.values(CORE_CATEGORIES)) expect(groups.has(c.group), c.group).toBe(true);
  // 처음 보는 분류는 플러그인
  expect(categoryInfo("acme_vision")).toBe(PLUGIN_CATEGORY);
  expect(categoryInfo("constructor")).toBe(PLUGIN_CATEGORY);
});

describe("팔레트 묶음", () => {
  const plugin = {
    format: "kookabug.nodes/0",
    plugin: { id: "acme", title: "Acme 비전", version: "2.0.0" },
    nodes: [
      { type: "acme.vision.magic", version: 2, title: "마법 찾기", category: "acme_vision", description: "무늬를 찾는다" },
      { type: "acme.input.tap", version: 1, title: "탭", category: "input" },
    ],
  };
  const types = indexNodeTypes([core, plugin]);

  test("시안 분류 순서, 플러그인 분류는 플러그인 이름, 시작 노드는 뺀다", () => {
    const groups = paletteGroups(types);
    expect(groups.map((g) => g.group)).toEqual(["창", "입력", "화면 인식", "흐름", "판정", "플러그인"]);
    const all = groups.flatMap((g) => g.items.map((i) => i.type));
    const entries = core.nodes.filter((n) => n.engine === "graph_entry").map((n) => n.type);
    expect(entries.length).toBe(1);
    for (const t of entries) expect(all).not.toContain(t);
    // 시작 노드 말고 코어 노드는 다 있다
    expect(all.filter((t) => t.startsWith("core.")).length).toBe(core.nodes.length - entries.length);
    // 플러그인의 코어 분류 노드는 그 분류로
    expect(groups.find((g) => g.group === "입력")!.items.map((i) => i.type)).toContain("acme.input.tap");
    const pluginGroup = groups.at(-1)!;
    expect(pluginGroup.items).toHaveLength(1);
    expect(pluginGroup.items[0].src).toBe("Acme 비전");
    expect(groupKey(pluginGroup)).toBe("플러그인:acme");
    expect(types.get("acme.vision.magic")!.pluginVersion).toBe("2.0.0");
  });

  test("검색: title·type·description 부분 일치, 한글 그대로", () => {
    const titles = (q: string) => paletteGroups(types, q).flatMap((g) => g.items.map((i) => i.title));
    expect(titles("이미지 클릭")).toEqual(["이미지 클릭"]);
    expect(titles("IMAGE.WAIT_ANY")).toEqual(["여러 대상 중 먼저 보이는 것"]);
    expect(titles("무늬")).toEqual(["마법 찾기"]);
    expect(titles("없는 노드 이름")).toEqual([]);
    expect(paletteGroups(types, "클릭").every((g) => g.items.length > 0)).toBe(true);
    expect(matches(types.get("core.flow.delay")!, "  ")).toBe(true);
  });
});
