// 첫 실행 흐름에서 뺀 7(자동화 정책)·8(기록) 단계의 기본값 저장 (UX5 설정·Init 간소화 4절). 9단계가 새 프로젝트 순서에서
// 한 번 부른다. 팀 `kookabug.json`에 그 블록이 아직 없을 때만 지금 기본값을 쓴다 — 사람이 이미 정한 값(설정 도우미·옛
// 마법사)은 건드리지 않는다. 저장은 7·8단계와 같은 사람 전용 메서드(sha 대조)
import { client } from "../rpc/client";

/** 금지 동작 기본값: 빈 목록 (개발 환경에는 보통 막을 동작이 없다 — 필요하면 설정 도우미에서 더한다) */
export const FORBIDDEN_DEFAULT: readonly unknown[] = [];
export const BUDGET_DEFAULT = { minutes: 60, runs: 30 } as const;
export const RECORD_DEFAULT = { screenshots: "on", video: "failed_only" } as const;
export const RETENTION_DEFAULT = { passed_days: 14, failed_days: 60 } as const;

export interface MissingBlocks {
  automation: boolean;
  cheats: boolean;
  record: boolean;
  retention: boolean;
}

/** `kookabug.json`에 아직 없는 블록 (있으면 사람이 정한 값 — 그대로 둔다) */
export function missingBlocks(config: Record<string, unknown>): MissingBlocks {
  return {
    automation: !("automation" in config),
    cheats: !("cheats" in config),
    record: !("record" in config),
    retention: !("retention" in config),
  };
}

/** 자동화 블록 기본값: 실효값(빠진 키는 제품 기본)에서 금지 동작만 빈 목록으로 */
export function automationDefault(effective: Record<string, unknown>): Record<string, unknown> {
  const repair = (effective.auto_repair ?? {}) as Record<string, unknown>;
  const budget = (effective.budget ?? {}) as Record<string, unknown>;
  return {
    format: "kookabug.automation/0",
    auto_repair: { ...repair, enabled: repair.enabled ?? true, scope: repair.scope ?? ["tests/"] },
    forbidden: [...FORBIDDEN_DEFAULT],
    budget: { minutes: budget.minutes ?? BUDGET_DEFAULT.minutes, runs: budget.runs ?? BUDGET_DEFAULT.runs },
  };
}

/** 없는 블록만 기본값으로 쓴다. 쓴 블록 이름 */
export async function saveSkippedDefaults(): Promise<string[]> {
  const w = await client().call("wizard.get", {});
  const raw = JSON.parse((await client().call("workspace.read", { path: "kookabug.json" })).text) as Record<string, unknown>;
  const missing = missingBlocks(raw);
  let sha = w.config_sha256;
  const wrote: string[] = [];
  if (missing.automation) {
    const info = await client().call("project.qa_info", {});
    sha = (await client().call("project.automation.set", { base_sha256: sha, value: automationDefault(info.automation as Record<string, unknown>) })).sha256;
    wrote.push("automation");
  }
  if (missing.cheats) {
    // U2 기본값: 치트 사용 켬 (분류가 없으면 무인 사용은 어차피 0) — 7단계 "다음"과 같은 값
    sha = (await client().call("cheats.categories.set", { base_sha256: sha, categories: [], enabled: true })).sha256;
    wrote.push("cheats");
  }
  if (missing.record || missing.retention) {
    const record = w.record as Record<string, unknown>;
    const retention = w.retention as Record<string, unknown>;
    await client().call("project.setup.set", {
      base_sha256: sha,
      record: { ...RECORD_DEFAULT, ...record },
      retention: { ...RETENTION_DEFAULT, ...retention },
    });
    wrote.push("record");
  }
  return wrote;
}
