// 진행 중 표시 CSS (UX1 U1): 움직임 줄이기 설정이면 돌지 않는다
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "vitest";

test("prefers-reduced-motion이면 animation: none", () => {
  const text = fs.readFileSync(path.join(import.meta.dirname, "spinner.module.css"), "utf8");
  const at = text.indexOf("@media (prefers-reduced-motion: reduce)");
  expect(at).toBeGreaterThan(0);
  expect(text.slice(at)).toContain("animation: none");
});
