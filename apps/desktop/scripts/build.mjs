// 앱 빌드: 렌더러 = Vite, main·preload = esbuild (M2 계획 2.1).
// `--release`(또는 KOOKABUG_RELEASE=1) = 배포 빌드: E2E 검사 전용 훅을 번들에서 뺀다 (build-options.mjs)
// 끝에 번들 입력 패키지 목록 dist/bundle-meta.json을 쓴다 (2.2 감사 범위 대조용)
import fs from "node:fs";
import path from "node:path";
import * as esbuild from "esbuild";
import { build as viteBuild } from "vite";
import { APP_DIR as appDir, mainOptions, preloadOptions } from "./build-options.mjs";

const dist = path.join(appDir, "dist");
const release = process.argv.includes("--release") || process.env.KOOKABUG_RELEASE === "1";

fs.rmSync(dist, { recursive: true, force: true });

const main = await esbuild.build(mainOptions({ release }));
const preload = await esbuild.build(preloadOptions());

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
