// 메타스키마 → TS 타입 (src/generated/<종류>.ts). `pnpm -r run gen`이 부른다
import { readFile, writeFile, mkdir, readdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { compile } from "json-schema-to-typescript";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outDir = path.join(root, "src", "generated");
const kinds = [
  "graph",
  "target",
  "workspace",
  "local",
  "node-schema",
  "events",
  "run",
  "user-settings",
];

const banner =
  "/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */";

await mkdir(outDir, { recursive: true });
const expected = new Set();
for (const kind of kinds) {
  const schema = JSON.parse(await readFile(path.join(root, `${kind}.schema.json`), "utf8"));
  const ts = await compile(schema, schema.title, {
    bannerComment: banner,
    cwd: root,
    // $defs에 있는 이름 있는 타입은 참조되지 않아도 내보낸다 (에디터가 핀 타입 등을 쓴다)
    unreachableDefinitions: true,
    strictIndexSignatures: true,
    format: true,
    style: { endOfLine: "lf", printWidth: 100 },
  });
  const file = `${kind}.ts`;
  expected.add(file);
  await writeFile(path.join(outDir, file), ts.replace(/\r\n/g, "\n"), "utf8");
}
for (const file of await readdir(outDir)) {
  if (!expected.has(file)) await rm(path.join(outDir, file));
}
