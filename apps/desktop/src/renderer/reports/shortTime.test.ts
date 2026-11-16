// 보고함 목록 줄 시작 시각 (UX9 D): UTC 표기를 이 PC 시각으로
import { afterEach, describe, expect, test } from "vitest";
import { activityTime, shortTime } from "./activity";

const saved = process.env.TZ;

afterEach(() => {
  if (saved === undefined) delete process.env.TZ;
  else process.env.TZ = saved;
});

describe("목록 줄 시각", () => {
  test("UTC 문자열이 고정한 시간대의 로컬 시각으로 보인다", () => {
    process.env.TZ = "Asia/Seoul";
    expect(shortTime("2026-11-16T05:10:00Z")).toBe("11-16 14:10");
    expect(shortTime("2026-11-16T05:10:00.123Z")).toBe("11-16 14:10");
    // 날짜가 넘어가는 경우
    expect(shortTime("2026-12-31T20:05:00Z")).toBe("01-01 05:05");
    expect(activityTime("2026-11-16T05:10:07Z")).toBe("14:10:07");
  });

  test("다른 시간대·읽을 수 없는 값", () => {
    process.env.TZ = "UTC";
    expect(shortTime("2026-11-16T05:10:00Z")).toBe("11-16 05:10");
    expect(shortTime("모름")).toBe("모름");
  });
});
