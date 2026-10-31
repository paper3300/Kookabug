// 분류 표가 코어 노드의 모든 category를 담는다 (M2 계획 2.7 "팔레트")
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";
import { CORE_CATEGORIES, PLUGIN_CATEGORY, categoryInfo } from "./categories";

const REPO = path.resolve(import.meta.dirname, "..", "..", "..", "..", "..");
const CORE_SCHEMA = path.join(REPO, "python", "kookabug_nodes", "src", "kookabug_nodes", "kookabug.schema.json");

test("test_all_core_categories_mapped", () => {
  const doc = JSON.parse(fs.readFileSync(CORE_SCHEMA, "utf8").replace(/^﻿/, "")) as {
    nodes: { category: string }[];
  };
  const categories = new Set(doc.nodes.map((n) => n.category));
  expect(categories.size).toBeGreaterThan(5);
  for (const c of categories) expect(Object.hasOwn(CORE_CATEGORIES, c), c).toBe(true);
  // 처음 보는 분류는 플러그인
  expect(categoryInfo("acme_vision")).toBe(PLUGIN_CATEGORY);
  expect(categoryInfo("constructor")).toBe(PLUGIN_CATEGORY);
});
