// 권한 설정 화면의 계층 값 읽기 (검수 B5 M1): 형식이 틀린 원본은 null — 화면이 진단을 보이고 편집을 막는다
import { describe, expect, test } from "vitest";
import type { local } from "@kookabug/schema";
import { parsePerms, PRESETS } from "./PermissionsView";

type Preset = NonNullable<local.Permissions["preset"]>;
/** 계약의 프리셋 전부 (하나라도 빠지거나 더해지면 타입 검사가 실패한다) */
const PRESET_SET: Record<Preset, true> = {
  curator: true,
  explorer: true,
  full: true,
  graph_author: true,
  qa_runner: true,
  read_only: true,
  runner: true,
};
const PRESET_ENUM = Object.keys(PRESET_SET);

describe("parsePerms", () => {
  test("맞는 값·없는 값", () => {
    expect(parsePerms(null)).toEqual({});
    expect(parsePerms(undefined)).toEqual({});
    const ok = { preset: "runner", toolsets: { control: "deny" }, rules: [{ rule: "kb_run_start", verdict: "allow" }] };
    expect(parsePerms(ok)).toEqual(ok);
    // M7 3.11 U1 탐색 프리셋
    expect(parsePerms({ preset: "explorer" })).toEqual({ preset: "explorer" });
  });

  test("프리셋 줄은 계약의 프리셋 전부 (탐색 포함)", () => {
    expect(PRESETS.map(([id]) => id).sort()).toEqual([...PRESET_ENUM].sort());
    expect(PRESETS.find(([id]) => id === "explorer")?.[1]).toMatch(/^탐색 — /);
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
