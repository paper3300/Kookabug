/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "PermissionVerdict".
 */
export type PermissionVerdict = "allow" | "ask" | "deny";
/**
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "SettingKey".
 */
export type SettingKey = string;

/**
 * 팀 공용 워크스페이스 설정 (kookabug.json)
 */
export interface Workspace {
  format: "kookabug.workspace/0";
  permissions?: Permissions;
  profiles?: {
    [k: string]: Profile | undefined;
  };
  record?: RecordPolicy;
  retention?: Retention;
  run?: RunConditions;
  settings?: Settings;
}
/**
 * 에이전트 권한. 이 파일(kookabug.json)의 툴셋·프리셋 값은 상한이다 (사용자·프로젝트 계층이 더 풀 수 없다)
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Permissions".
 */
export interface Permissions {
  preset?: "full" | "graph_author" | "read_only" | "runner";
  rules?: PermissionRule[];
  toolsets?: {
    [k: string]: PermissionVerdict | undefined;
  };
}
/**
 * 권한 규칙 하나. rule은 "도구" 또는 "도구(인자 패턴)". 도구·인자 모두 glob(*, ?), 대소문자 구분
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "PermissionRule".
 */
export interface PermissionRule {
  rule: string;
  verdict: PermissionVerdict;
}
/**
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Profile".
 */
export interface Profile {
  settings?: Settings;
}
/**
 * 설정 키 → 값. null은 사람마다 .kookabug/local.json에 넣어야 하는 값
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Settings".
 */
export interface Settings {
  [k: string]: unknown | undefined;
}
/**
 * 기록 정책. 상위(워크스페이스 → 테스트 → 서브그래프 → 노드)에서 끈 것은 하위에서 켤 수 없다
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "RecordPolicy".
 */
export interface RecordPolicy {
  screenshots?: "off" | "on";
  video?: "failed_only" | "off" | "on";
}
/**
 * 실행 기록 보관
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "Retention".
 */
export interface Retention {
  failed_days?: number;
  keep_last?: number;
  passed_days?: number;
}
/**
 * 실행 조건 기본값 (밀리초). CLI 옵션이 이 값보다 우선한다
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "RunConditions".
 */
export interface RunConditions {
  /**
   * 실행 전체 기한. 없으면 30분
   */
  deadline_ms?: number;
  /**
   * 취소·마무리를 시작한 runner가 끝나기를 기다리는 시간. 넘으면 감독자가 끝낸다. 없으면 5000
   */
  shutdown_grace_ms?: number;
  /**
   * 취소한 워커 노드가 끝나기를 기다리는 시간. 넘으면 워커를 끝낸다. 없으면 2000
   */
  worker_cancel_grace_ms?: number;
  /**
   * 워커가 시작 인사에 답하기까지의 기한. 없으면 30000
   */
  worker_start_timeout_ms?: number;
}
