import fs from "node:fs";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const root = path.resolve(import.meta.dirname, "src/renderer");
const outDir = path.resolve(import.meta.dirname, "dist/renderer");

// 번들에 들어간 모듈·자산의 원래 경로를 남긴다. scripts/build.mjs가 이것으로 번들 입력 패키지
// 목록(dist/bundle-meta.json)을 만들고, 라이선스 감사 검사가 prod 의존성과 대조한다 (M2 계획 2.2)
function bundleInputs(): Plugin {
  return {
    name: "kookabug-bundle-inputs",
    apply: "build",
    generateBundle(_options, bundle) {
      const files = new Set<string>(this.getModuleIds());
      for (const item of Object.values(bundle)) {
        if (item.type === "chunk") item.moduleIds.forEach((id) => files.add(id));
        else item.originalFileNames?.forEach((name) => files.add(path.resolve(root, name)));
      }
      fs.mkdirSync(outDir, { recursive: true });
      fs.writeFileSync(
        path.join(outDir, "..", "renderer-inputs.json"),
        JSON.stringify([...files].sort(), null, 2),
      );
    },
  };
}

export default defineConfig({
  root,
  base: "./",
  plugins: [react(), bundleInputs()],
  build: {
    outDir,
    emptyOutDir: true,
    // 글꼴 파일을 data: URL로 넣지 않는다 (font-src 'self', 감사 대상 파일 그대로)
    assetsInlineLimit: 0,
    target: "chrome140",
  },
});
