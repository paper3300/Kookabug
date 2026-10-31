import { defineConfig } from "vitest/config";

// 렌더러 순수 로직과 주 프로세스 검사 함수. 컴포넌트는 Playwright E2E로 본다 (M2 계획 2.13)
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts"],
    environment: "node",
  },
});
