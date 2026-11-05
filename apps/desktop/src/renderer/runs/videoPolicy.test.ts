// 기록 뷰어 상태 바의 실효 영상 정책 문구 (M4 T12, STATE ⑦)
import { describe, expect, test } from "vitest";
import { videoPolicyText } from "./runListStore";

describe("영상 정책 문구", () => {
  test("값과 그 값을 정한 층 (# 앞 파일, 없으면 워크스페이스 기본값)", () => {
    expect(videoPolicyText({ mode: "failed_only", source: null })).toBe("영상: 실패만 (워크스페이스 기본값)");
    expect(videoPolicyText({ mode: "off", source: "kookabug.json#/record" })).toBe("영상: 끔 (kookabug.json)");
    expect(videoPolicyText({ mode: "failed_only", source: "tests/login.graph.json#/record" })).toBe(
      "영상: 실패만 (tests/login.graph.json)",
    );
    // 워크스페이스에서 켠 것은 daemon이 kookabug.json을 출처로 준다 (B4 검수 Mid 2)
    expect(videoPolicyText({ mode: "on", source: "kookabug.json#/record" })).toBe("영상: 켬 (kookabug.json)");
  });

  test("옛 실행(정책 없음)은 문구 없음", () => {
    expect(videoPolicyText(undefined)).toBeNull();
  });
});
