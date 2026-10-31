import path from "node:path";
import { defineConfig } from "@playwright/test";

const repoBuild = path.resolve(import.meta.dirname, "../../build");

// Electron E2E (Playwright _electron). 앱은 미리 `pnpm build`로 만든다 (M2 계획 2.13)
export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.spec.ts",
  outputDir: path.join(repoBuild, "e2e", "test-results"),
  // 창·daemon을 띄우는 검사라 한 번에 하나
  workers: 1,
  fullyParallel: false,
  timeout: 60_000,
  reporter: [["list"], ["html", { open: "never", outputFolder: path.join(repoBuild, "e2e", "report") }]],
  use: {
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
});
