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
  /**
   * 워크스페이스 ID (UUID 소문자). 자격 증명 관리자 비밀값 이름 kookabug:<ID>:<키>의 접두라 팀이 같은 값을 쓴다. 없으면 처음 비밀값을 만들 때(secrets.create) 만들어 넣는다 (M4)
   */
  id?: string;
  ocr?: OcrSettings;
  permissions?: Permissions;
  profiles?: {
    [k: string]: Profile | undefined;
  };
  record?: WorkspaceRecordPolicy;
  retention?: Retention;
  run?: RunConditions;
  settings?: Settings;
}
/**
 * OCR 엔진과 그 설정. engine이 없으면 rapidocr
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "OcrSettings".
 */
export interface OcrSettings {
  /**
   * rapidocr 검출 크기 설정 (없는 값은 기본값)
   */
  det?: {
    /**
     * 짧은 변이 이보다 작을 때만 검출 입력을 늘린다. 기본 64
     */
    limit_side_len?: number;
    /**
     * 긴 변이 이보다 크면 줄인다. 기본 4096
     */
    max_side_len?: number;
    /**
     * 픽셀 수가 이 이하면 한 번에 검출, 넘으면 타일로 나눈다. 기본 655360
     */
    single_max_pixels?: number;
    /**
     * 이웃 타일이 겹치는 픽셀. 기본 128
     */
    tile_overlap?: number;
    /**
     * 타일 한 변 (32의 배수). 기본 640
     */
    tile_side?: number;
  };
  engine?: "rapidocr";
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
 * 워크스페이스 기록 정책: 그래프 RecordPolicy(screenshots·video)에 비밀값 가림 스위치를 더한 것. 상위에서 끈 것은 하위에서 켤 수 없다
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "WorkspaceRecordPolicy".
 */
export interface WorkspaceRecordPolicy {
  /**
   * 비밀값 가림. true면 비밀값을 받은 스텝의 스크린샷·영상과 민감 target의 OCR 글자를 남기지 않고 이벤트·로그·실행 기록의 비밀값을 ***로 가린다. 없으면 false(개발 환경 도구라 그대로 남긴다)
   */
  redact_secrets?: boolean;
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
 * 실행 조건 기본값 (시간은 밀리초). CLI 옵션이 이 값보다 우선한다
 *
 * This interface was referenced by `Workspace`'s JSON-Schema
 * via the `definition` "RunConditions".
 */
export interface RunConditions {
  /**
   * 관측 호출(캡처·찾기·OCR) 하나의 설정 기한. 넘으면 capture_timeout. 없으면 2000
   */
  capture_timeout_ms?: number;
  /**
   * 실행 전체 기한. 없으면 30분
   */
  deadline_ms?: number;
  /**
   * 프레임 저장소 바이트 예산 (MiB). 넘으면 스텝 출력으로 나간 프레임부터 버린다. 없으면 512
   */
  frame_budget_mib?: number;
  /**
   * 스텝 출력(이미지·찾기 결과)으로 나간 프레임을 남기는 개수. 없으면 32
   */
  frame_output_refs?: number;
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
