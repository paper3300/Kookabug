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
  /**
   * 멈춘 시간을 뺀 경과 (M3)
   */
  active_duration_ms?: number;
  /**
   * 에이전트 제어 실행을 낸 에이전트 (source agent_control)
   */
  agent?: {
    id: string;
  };
  /**
   * 에이전트용 비밀값 분류(이벤트 secret_paths·스텝 secret·agent_withhold)를 남긴 기록 (M5 3.8). 없으면 daemon은 에이전트에게 안전 필드(판정·스텝·노드·출구·상태·오류 코드·시각·기간)만 준다
   */
  agent_mask?: 1;
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
  observed?: Observed;
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
  /**
   * M8 그래프 qa 결과: 검증 노드가 실제로 실행·통과했나, 쓴 치트, 설정 오류
   */
  qa?: {
    cheats_used: {
      calls: number;
      cheat: string;
      digest: string;
      rev: number;
    }[];
    claims: {
      assertions: string[];
      executed: string[];
      id: string;
      passed: string[];
      rev: number;
    }[];
    config_errors: string[];
    /**
     * qa.profiles가 이번 프로필을 담지 않아 판정 skipped (qa_not_applicable)
     */
    not_applicable?: string;
  };
  reason?: string;
  /**
   * 실행별 기록 강제 (M7 R2): 에이전트 제어 실행은 스크린샷·영상을 끄고 비밀값을 가렸다. 그래프·워크스페이스 기록 정책과 별개
   */
  record_override?: {
    by: "agent_control";
    redact_secrets: true;
    screenshots: "off";
    video: "off";
  };
  /**
   * 재시도 끝에 성공한 스텝 수 (step.end.retried). pass인데 0보다 크면 "불안정" (M3)
   */
  retried_steps?: number;
  run_id: RunId;
  /**
   * 감독자가 run.end에서 다시 만든 파일
   */
  run_json_repaired?: true;
  runner?: RunnerInfo;
  runner_exit_code?: number;
  /**
   * run.end.secret_paths 그대로 (reason에 비밀값이 있으면 ["/reason"], M5 3.8)
   *
   * @minItems 1
   */
  secret_paths?: [string, ...string[]];
  /**
   * 실행 출처 (M5 3.9). agent_control = 에이전트의 게임 조작(kb_input_*)을 daemon이 한 스텝짜리 실행으로 돌린 것. 없으면 일반 실행
   */
  source?: "agent_control";
  started_at: Timestamp;
  status: "finished" | "running";
  verdict?: Verdict;
  video?: VideoSummary;
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
  /**
   * 실행이 읽은 kookabug.lock의 정규 잠금 해시 (설치 플러그인을 쓴 실행, M6)
   */
  plugin_lock_sha256?: string;
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
 * 실행에서 처음 관측한 창의 캡처 방식·클라이언트 크기·DPI (지난 성공과 비교의 환경, M3)
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Observed".
 */
export interface Observed {
  /**
   * 캡처 방식 (wgc·gdi·fake 등)
   */
  backend: string;
  /**
   * [w, h] 물리 픽셀
   *
   * @minItems 2
   * @maxItems 2
   */
  client_size: [number, number];
  dpi: number;
}
/**
 * 실행이 쓴 플러그인. 설치 플러그인(kookabug.lock)은 env·wheel_sha256·schema_sha256까지 (M6)
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "Plugin".
 */
export interface Plugin {
  /**
   * 설치 플러그인이 돈 환경 이름 (shared·iso-<id>)
   */
  env?: string;
  id: string;
  schema_sha256?: string;
  version: string;
  wheel_sha256?: string;
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
 * 영상 요약 (video/index.json에서 읽는다, M3). kept·deleted는 조각 수, bytes는 남은 조각 바이트 합. 실행 판정은 바꾸지 않는다
 *
 * This interface was referenced by `Run`'s JSON-Schema
 * via the `definition` "VideoSummary".
 */
export interface VideoSummary {
  bytes: number;
  deleted: number;
  kept: number;
  reason?: import("./video-index.js").VideoReason;
  status: import("./video-index.js").VideoStatus;
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
