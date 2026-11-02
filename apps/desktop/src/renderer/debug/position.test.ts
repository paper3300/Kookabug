// 디버그 툴바 가로 자리 (검수 T9-1 REPRO 4: 영역 1000 → 400px, 툴바 220px, 기억한 x=300)
import { describe, expect, test } from "vitest";
import { clampX } from "./position";

describe("툴바 자리", () => {
  test("test_toolbar_clamped_inside_shrunk_area_keeps_preference", () => {
    expect(clampX(300, 1000, 220)).toBe(300);
    // 영역을 줄이면 툴바가 영역 안(왼쪽 172 ~ 오른쪽 392)에 들어온다
    const x = clampX(300, 400, 220);
    expect(x).toBe(82);
    const left = 400 / 2 + x - 220 / 2;
    expect(left).toBe(172);
    expect(left + 220).toBeLessThanOrEqual(400 - 8);
    // 왼쪽으로 끈 자리도 같다
    expect(clampX(-300, 400, 220)).toBe(-82);
    // 영역이 툴바보다 좁으면 가운데
    expect(clampX(300, 200, 220)).toBe(0);
  });
});
