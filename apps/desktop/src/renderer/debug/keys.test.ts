// 디버거 단축키 (M3 계획 2.9, VS Code 관례)
import { describe, expect, test } from "vitest";
import { debugKey, type KeyLike } from "./keys";

const k = (key: string, mods: Partial<KeyLike> = {}): KeyLike => ({
  key,
  shiftKey: false,
  ctrlKey: false,
  altKey: false,
  metaKey: false,
  ...mods,
});

describe("단축키", () => {
  test("VS Code 관례 표", () => {
    expect(debugKey(k("F5"))).toBe("run_or_continue");
    expect(debugKey(k("F5", { shiftKey: true }))).toBe("stop");
    expect(debugKey(k("F5", { ctrlKey: true, shiftKey: true }))).toBe("restart");
    expect(debugKey(k("F6"))).toBe("pause");
    expect(debugKey(k("F9"))).toBe("toggle_breakpoint");
    expect(debugKey(k("F10"))).toBe("step_over");
    expect(debugKey(k("F11"))).toBe("step_into");
    expect(debugKey(k("F11", { shiftKey: true }))).toBe("step_out");
  });

  test("다른 조합·다른 키는 디버거 것이 아니다", () => {
    expect(debugKey(k("F5", { ctrlKey: true }))).toBeNull();
    expect(debugKey(k("F5", { altKey: true }))).toBeNull();
    expect(debugKey(k("F10", { shiftKey: true }))).toBeNull();
    expect(debugKey(k("F11", { ctrlKey: true }))).toBeNull();
    expect(debugKey(k("F6", { metaKey: true }))).toBeNull();
    expect(debugKey(k("s", { ctrlKey: true }))).toBeNull();
    expect(debugKey(k("F7"))).toBeNull();
  });
});
