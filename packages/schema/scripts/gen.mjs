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
  "rpc",
  "screen",
  "daemon-rpc",
  "session",
  "breakpoints",
  "video-index",
  "run-index",
  "recorder-hook",
  "recorder-script",
  "recorder-fragment",
  "plugin-lock",
  "explore",
];

const banner =
  "/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */";

// 런타임 검사(src/rpcCheck.ts)가 읽는 스키마 값도 내는 종류. daemon-rpc가 events·breakpoints·
// run-index·recorder-fragment를, run-index가 events·video-index를 참조한다. 검사기가 아는 키워드만 쓴다
const CHECKED = {
  "daemon-rpc": "daemonRpcSchema",
  events: "eventsSchema",
  breakpoints: "breakpointsSchema",
  "run-index": "runIndexSchema",
  "video-index": "videoIndexSchema",
  "recorder-fragment": "recorderFragmentSchema",
};
// 최상위가 oneOf(메시지 종류)라 $defs를 빈 객체 틀로 내보내는 종류. 그러지 않으면 메시지 봉투가
// 참조하지 않는 정의(rpc의 RunSpec·메서드별 params 등)가 TS에서 빠진다
const DEFS_ROOT = new Set(["daemon-rpc", "rpc"]);
const KEYWORDS = new Set([
  "$defs", "$id", "$ref", "$schema", "additionalProperties", "anyOf", "const", "description",
  "else", "enum", "if", "items", "maxItems", "maximum", "minItems", "minLength", "minimum", "not",
  "oneOf", "pattern", "properties", "required", "then", "title", "tsType", "type",
]);

function checkKeywords(node, where) {
  if (Array.isArray(node)) {
    node.forEach((item, i) => checkKeywords(item, `${where}/${i}`));
    return;
  }
  if (node === null || typeof node !== "object") return;
  for (const [key, value] of Object.entries(node)) {
    if (!KEYWORDS.has(key)) throw new Error(`${where}: 검사기가 모르는 키워드 ${key}`);
    const external = key === "$ref" ? URN.exec(value) : null;
    if (external && !(external[1] in CHECKED)) {
      throw new Error(`${where}: 검사기에 스키마 값이 없는 참조 ${value} (CHECKED에 더한다)`);
    }
    if (key === "properties" || key === "$defs") {
      for (const [name, sub] of Object.entries(value)) checkKeywords(sub, `${where}/${key}/${name}`);
    } else if (!["const", "enum", "description", "title", "tsType", "required"].includes(key)) {
      checkKeywords(value, `${where}/${key}`);
    }
  }
}

// 다른 메타스키마 참조: 파일 전체(urn:kookabug:<종류>:0) 또는 그 파일의 정의(…:0#/$defs/<이름>)
const URN = /^urn:kookabug:([a-z-]+):0(?:#\/\$defs\/([A-Za-z0-9_]+))?$/;
const titles = {};
const defTitles = {};
for (const kind of kinds) {
  const schema = JSON.parse(await readFile(path.join(root, `${kind}.schema.json`), "utf8"));
  titles[kind] = schema.title;
  defTitles[kind] = Object.fromEntries(
    Object.entries(schema.$defs ?? {}).map(([name, def]) => [name, def.title ?? name]),
  );
}

function externalType(kind, def) {
  const name = def === undefined ? titles[kind] : defTitles[kind]?.[def];
  if (name === undefined) throw new Error(`없는 참조 urn:kookabug:${kind}:0#/$defs/${def}`);
  return `import("./${kind}.js").${name}`;
}

// 다른 메타스키마 참조는 생성기가 풀지 못한다. TS에서는 그 파일의 최상위 타입(또는 그 정의의 타입)을
// import 타입으로 쓴다 (검사기와 Python은 참조를 그대로 따라간다)
function externalToTs(node) {
  if (Array.isArray(node)) return node.map(externalToTs);
  if (node === null || typeof node !== "object") return node;
  const match = typeof node.$ref === "string" ? URN.exec(node.$ref) : null;
  if (match) {
    const { $ref: _, ...rest } = node;
    return { ...rest, tsType: externalType(match[1], match[2]) };
  }
  return Object.fromEntries(Object.entries(node).map(([k, v]) => [k, externalToTs(v)]));
}

await mkdir(outDir, { recursive: true });
const expected = new Set();
for (const kind of kinds) {
  const schema = JSON.parse(await readFile(path.join(root, `${kind}.schema.json`), "utf8"));
  // 생성기는 최상위가 객체일 때만 $defs를 다 내보낸다. 최상위가 oneOf(메시지 종류)인 daemon-rpc·rpc는
  // 빈 객체 틀로 $defs를 내보내고 최상위 합 타입은 직접 붙인다 (메서드 표 등을 렌더러가 쓴다)
  const union = DEFS_ROOT.has(kind) ? schema.oneOf.map((s) => s.$ref.split("/").pop()) : null;
  let input = externalToTs(schema);
  if (union) {
    const { oneOf: _, ...rest } = input;
    input = { ...rest, type: "object", properties: {}, additionalProperties: false, title: `${schema.title}Defs` };
  }
  let ts = await compile(input, input.title, {
    bannerComment: banner,
    cwd: root,
    // $defs에 있는 이름 있는 타입은 참조되지 않아도 내보낸다 (에디터가 핀 타입 등을 쓴다)
    unreachableDefinitions: true,
    strictIndexSignatures: true,
    format: true,
    style: { endOfLine: "lf", printWidth: 100 },
  });
  if (union) {
    ts += `\n/**\n * ${schema.description}\n */\nexport type ${schema.title} = ${union.join(" | ")};\n`;
  }
  const file = `${kind}.ts`;
  expected.add(file);
  await writeFile(path.join(outDir, file), ts.replace(/\r\n/g, "\n"), "utf8");
  if (kind in CHECKED) {
    checkKeywords(schema, kind);
    const data = `${kind}.data.ts`;
    expected.add(data);
    const body = `${banner}\n\nexport const ${CHECKED[kind]}: unknown = ${JSON.stringify(schema, null, 2)};\n`;
    await writeFile(path.join(outDir, data), body, "utf8");
  }
}
// 매칭 기본값 상수 (M4 T12): target.schema.json의 default 하나가 출처다. Python은 같은 스키마 값을 읽는다
// (kookabug_platform.vision.DEFAULT_THRESHOLD)
{
  const target = JSON.parse(await readFile(path.join(root, "target.schema.json"), "utf8"));
  const match = target.$defs.Match.properties;
  const threshold = match.threshold.default;
  const tolerance = match.color_tolerance.default;
  if (typeof threshold !== "number" || typeof tolerance !== "number") throw new Error("target.schema.json Match 기본값이 없다");
  const file = "constants.ts";
  expected.add(file);
  const body =
    `${banner}\n\n` +
    `/** 매칭 기본 임계값 (target.schema.json $defs.Match.threshold.default) */\n` +
    `export const DEFAULT_MATCH_THRESHOLD = ${JSON.stringify(threshold)};\n` +
    `/** 색 허용치 기본값 (target.schema.json $defs.Match.color_tolerance.default) */\n` +
    `export const DEFAULT_COLOR_TOLERANCE = ${JSON.stringify(tolerance)};\n`;
  await writeFile(path.join(outDir, file), body, "utf8");
}
for (const file of await readdir(outDir)) {
  if (!expected.has(file)) await rm(path.join(outDir, file));
}
