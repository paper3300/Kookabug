// 앱 빌드: 렌더러 = Vite, main·preload = esbuild (M2 계획 2.1).
// 끝에 번들 입력 패키지 목록 dist/bundle-meta.json을 쓴다 (2.2 감사 범위 대조용)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";
import { build as viteBuild } from "vite";

const appDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const dist = path.join(appDir, "dist");

fs.rmSync(dist, { recursive: true, force: true });

// Electron 44 = Node 24.22, Chromium 152
const common = {
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node24",
  external: ["electron"],
  sourcemap: "linked",
  metafile: true,
  logLevel: "warning",
};
const main = await esbuild.build({
  ...common,
  entryPoints: [path.join(appDir, "src/main/main.ts")],
  outfile: path.join(dist, "main/main.cjs"),
});
// 샌드박스 preload는 CommonJS 한 파일이어야 한다
const preload = await esbuild.build({
  ...common,
  entryPoints: [path.join(appDir, "src/preload/preload.ts")],
  outfile: path.join(dist, "preload/preload.cjs"),
});

await viteBuild({ configFile: path.join(appDir, "vite.config.ts"), logLevel: "warn" });

const rendererInputs = JSON.parse(fs.readFileSync(path.join(dist, "renderer-inputs.json"), "utf8"));
const inputs = [
  ...Object.keys(main.metafile.inputs).map((p) => path.resolve(appDir, p)),
  ...Object.keys(preload.metafile.inputs).map((p) => path.resolve(appDir, p)),
  ...rendererInputs,
];

fs.writeFileSync(
  path.join(dist, "bundle-meta.json"),
  JSON.stringify({ packages: packagesOf(inputs) }, null, 2) + "\n",
);

// 모듈 경로 → 그 경로가 든 npm 패키지(이름·판). 워크스페이스 자기 코드는 빼지 않고 그대로 둔다:
// 감사 쪽이 @kookabug/* 를 제1자 코드로 따로 다룬다
function packagesOf(files) {
  const found = new Map();
  for (const raw of files) {
    const file = raw.replace(/^\0+/, "").split("?")[0];
    const norm = file.replaceAll("\\", "/");
    const at = norm.lastIndexOf("/node_modules/");
    if (at < 0) continue;
    const rest = norm.slice(at + "/node_modules/".length).split("/");
    const name = rest[0].startsWith("@") ? `${rest[0]}/${rest[1]}` : rest[0];
    const dir = norm.slice(0, at + "/node_modules/".length) + name;
    const key = `${dir}`;
    if (found.has(key)) continue;
    const pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
    found.set(key, { name: pkg.name, version: pkg.version });
  }
  const unique = new Map([...found.values()].map((p) => [`${p.name}@${p.version}`, p]));
  return [...unique.values()].sort((a, b) =>
    a.name === b.name ? a.version.localeCompare(b.version) : a.name.localeCompare(b.name),
  );
}
