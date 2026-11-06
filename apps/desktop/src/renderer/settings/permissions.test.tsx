// 권한 설정 화면의 계층 값 읽기 (검수 B5 M1): 형식이 틀린 원본은 null — 화면이 진단을 보이고 편집을 막는다
import { describe, expect, test } from "vitest";
import { parsePerms } from "./PermissionsView";

describe("parsePerms", () => {
  test("맞는 값·없는 값", () => {
    expect(parsePerms(null)).toEqual({});
    expect(parsePerms(undefined)).toEqual({});
    const ok = { preset: "runner", toolsets: { control: "deny" }, rules: [{ rule: "kb_run_start", verdict: "allow" }] };
    expect(parsePerms(ok)).toEqual(ok);
  });

  test("틀린 값은 null", () => {
    for (const bad of [
      "x",
      [],
      { rules: "손상된 규칙" },
      { rules: [{ rule: 3, verdict: "allow" }] },
      { rules: [{ rule: "a", verdict: "maybe" }] },
      { preset: "everything" },
      { toolsets: { input: "deny" } },
      { toolsets: { control: "no" } },
      { extra: 1 },
    ]) {
      expect(parsePerms(bad), JSON.stringify(bad)).toBeNull();
    }
  });
});
