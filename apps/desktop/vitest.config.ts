import { defineConfig } from "vitest/config";

// 렌더러 순수 로직과 주 프로세스 검사 함수. 컴포넌트는 Playwright E2E로 본다 (M2 계획 2.13)
// *.test.tsx: 렌더러 저장소(window를 쓰는 모듈)까지 불러오는 검사 — 타입은 렌더러(DOM) 설정으로 본다
export default defineConfig({
  test: {
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    environment: "node",
  },
});
