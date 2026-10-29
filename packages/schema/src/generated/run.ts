/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * 실행을 마무리한 쪽: runner 자신, 또는 runner가 죽은 뒤 감독자
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "FinalizedBy".
 */
export type FinalizedBy = "runner" | "supervisor";
/**
 * 실행 ID: 소문자·숫자 8자
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "RunId".
 */
export type RunId = string;
/**
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Verdict".
 */
export type Verdict = "error" | "fail" | "pass" | "skipped";
/**
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "SettingKey".
 */
export type SettingKey = string;

/**
 * 실행 정보·결과 (실행 폴더의 run.json). 원자적 교체로만 쓴다
 */
export interface Run {
  code?: string;
  conditions?: Conditions;
  /**
   * 디버거가 개입한 실행
   */
  debug_intervened?: boolean;
  diagnostics?: Diagnostic[];
  ended_at?: Timestamp;
  failure_path?: [string, ...string[]] | null;
  failure_step?: null | string;
  finalized_by?: FinalizedBy;
  format: "kookabug.run/0";
  game_build?: null | string;
  /**
   * 실행한 테스트 그래프 (워크스페이스 기준)
   */
  graph: string;
  /**
   * 패키지 이름 → 버전
   */
  packages?: {
    [k: string]: string | undefined;
  };
  pause_count?: number;
  /**
   * 멈춰 있던 시간 (M3부터 기한에서 뺀다)
   */
  paused_ms?: number;
  plugins?: Plugin[];
  reason?: string;
  run_id: RunId;
  /**
   * 감독자가 run.end에서 다시 만든 파일
   */
  run_json_repaired?: true;
  runner?: RunnerInfo;
  runner_exit_code?: number;
  started_at: Timestamp;
  status: "finished" | "running";
  verdict?: Verdict;
}
/**
 * 실행 조건
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Conditions".
 */
export interface Conditions {
  deadline_ms: number;
  /**
   * 플랫폼 종류 (none·fake·windows)
   */
  platform: string;
  profile: null | string;
  /**
   * 이 실행이 쓴 $setting 키 → 값·계층. 비밀값은 키만
   */
  settings: {
    [k: string]: SettingUse | undefined;
  };
}
/**
 * 설정값과 그 값을 준 계층. 비밀값(secret: true)은 값을 남기지 않는다
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "SettingUse".
 */
export interface SettingUse {
  layer: "local" | "options" | "profile" | "workspace";
  secret?: true;
  value?: unknown;
}
/**
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Diagnostic".
 */
export interface Diagnostic {
  code: string;
  file?: null | string;
  message: string;
  node?: null | string;
  pointer?: null | string;
  severity: "error" | "warning";
}
/**
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Plugin".
 */
export interface Plugin {
  id: string;
  version: string;
}
/**
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "RunnerInfo".
 */
export interface RunnerInfo {
  pid: number;
  python: string;
  version: string;
}
/**
 * 디버거 개입 정보 (스키마 v0 6장)
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "DebugInfo".
 */
export interface DebugInfo {
  /**
   * 디버거가 개입한 실행
   */
  debug_intervened?: boolean;
  pause_count?: number;
  /**
   * 멈춰 있던 시간 (M3부터 기한에서 뺀다)
   */
  paused_ms?: number;
}
