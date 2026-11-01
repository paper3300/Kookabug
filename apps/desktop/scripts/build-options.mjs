// main·preload esbuild 설정 (build.mjs와 배포 번들 검사 e2e-hooks.test.ts가 같이 쓴다).
// release = 배포 빌드: E2E 검사 전용 훅(src/main/e2e-hooks.ts)을 번들에서 뺀다. T13 패키징은 배포 빌드를 쓴다
import path from "node:path";
import { fileURLToPath } from "node:url";

export const APP_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

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

export function mainOptions({ release = false, outfile = path.join(APP_DIR, "dist/main/main.cjs") } = {}) {
  return {
    ...common,
    entryPoints: [path.join(APP_DIR, "src/main/main.ts")],
    outfile,
    define: { __KOOKABUG_E2E_HOOKS__: release ? "false" : "true" },
    // 함수 안의 `if (false) {…}`는 문법 줄이기를 켜야 번들에서 빠진다 (이름·공백은 그대로)
    ...(release ? { minifySyntax: true } : {}),
  };
}

// 샌드박스 preload는 CommonJS 한 파일이어야 한다
export function preloadOptions({ outfile = path.join(APP_DIR, "dist/preload/preload.cjs") } = {}) {
  return {
    ...common,
    entryPoints: [path.join(APP_DIR, "src/preload/preload.ts")],
    outfile,
  };
}
