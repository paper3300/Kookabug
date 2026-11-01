/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "StepId".
 */
export type StepId = string;
/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * 실행 ID: 소문자·숫자 8자
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "RunId".
 */
export type RunId = string;
/**
 * step.end의 status, 또는 step.end가 없는 스텝: running(진행 중 실행), aborted(끝난 실행에서 중단)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "StepStatus".
 */
export type StepStatus = "aborted" | "cancelled" | "error" | "fail" | "running" | "success";
/**
 * 호출 경로: 테스트부터의 호출 노드들 + 노드
 *
 * @minItems 1
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CallPath".
 */
export type CallPath = [string, ...string[]];
/**
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "Sha256".
 */
export type Sha256 = string;
/**
 * [x, y, w, h] 픽셀
 *
 * @minItems 4
 * @maxItems 4
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "Rect".
 */
export type Rect = [number, number, number, number];

/**
 * 실행 색인 (run.index 결과). 코어 record/index.py가 events.jsonl을 한 번 훑어 만든다. 최상위 스텝과 실패 사슬의 스텝만 담고, 그 밖의 스텝은 run.children으로 쪽마다 읽는다
 */
export interface RunIndex {
  /**
   * 루트부터 실패 스텝(run.end.failure_step)까지의 스텝 (실패가 없으면 빈 목록)
   */
  failure_chain: StepId[];
  /**
   * 색인에 넣은 마지막 이벤트 seq (진행 중 실행은 구독 커서와 맞춘다)
   */
  last_seq: number;
  pauses: PauseSpan[];
  /**
   * run.json 내용 그대로 (형식은 run.schema.json, 아직 없으면 null)
   */
  run: null | {
    [k: string]: unknown | undefined;
  };
  /**
   * 실행 폴더 (워크스페이스 기준, kbimg://ws/<run_dir>/<파일>로 연다)
   */
  run_dir: string;
  run_id: RunId;
  state: "ended" | "running";
  stats: NodeStat[];
  /**
   * 최상위 스텝과 실패 사슬의 스텝 (step 번호 순)
   */
  steps: StepNode[];
  /**
   * video/ 폴더가 없으면 null
   */
  video: VideoView | null;
}
/**
 * 멈춘 구간 (debug.pause ~ debug.resume, 재개 없이 끝났으면 t_end null)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "PauseSpan".
 */
export interface PauseSpan {
  mode?: "continue" | "step_into" | "step_out" | "step_over";
  reason?: "breakpoint" | "request" | "step";
  step: StepId | null;
  t_end: Timestamp | null;
  t_start: Timestamp;
  where?: "boundary" | "poll";
}
/**
 * 노드별 통계 (그래프·노드마다, 끝난 스텝만)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "NodeStat".
 */
export interface NodeStat {
  count: number;
  error: number;
  fail: number;
  graph: string;
  last_failure_step: StepId | null;
  max_ms: number;
  mean_ms: number;
  node: string;
  p95_ms: number;
  success: number;
}
/**
 * 색인의 스텝 하나 (events.jsonl의 step.start·attempt.end·step.end를 합친 것)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "StepNode".
 */
export interface StepNode {
  /**
   * 멈춘 시간을 뺀 경과 (step.end에 있을 때만)
   */
  active_duration_ms?: number;
  /**
   * 실행 폴더 기준 증거 파일 (step.end.artifacts)
   */
  artifacts?: string[];
  attempt: number;
  /**
   * 서브그래프 호출이면 부른 그래프 (워크스페이스 기준)
   */
  calls?: string;
  /**
   * 바로 아래 스텝 수 (반복이면 모든 회차 합)
   */
  children: number;
  duration_ms: number | null;
  /**
   * step.end.evidence가 있다 (run.step으로 읽는다)
   */
  evidence: boolean;
  exit: null | string;
  /**
   * 노드가 든 그래프 (워크스페이스 기준. 실행 때 쓴 스냅샷은 실행 폴더 snapshot/ 아래 같은 경로)
   */
  graph: string;
  /**
   * parent가 반복 스텝일 때 그 회차 (본문 스텝은 events의 iteration, 되돌아옴은 방금 끝난 회차)
   */
  iteration?: number;
  /**
   * 반복 스텝이면 회차별 요약 (회차 순)
   */
  iterations?: IterationSummary[];
  message?: string;
  node: string;
  omitted?: import("./events.js").Omitted[];
  /**
   * 색인 부모: 호출 스텝, 또는 반복 스텝(반복 노드에 처음 도착한 스텝). 반복은 실행기에서 깊이를 더하지 않아 events의 parent와 다를 수 있다: 본문 스텝과 본문이 끝나 반복 노드로 되돌아온 스텝이 반복 스텝 아래 회차로 묶인다. 최상위는 null
   */
  parent: StepId | null;
  path: CallPath;
  /**
   * 재시도 끝에 성공 (step.end.retried)
   */
  retried?: boolean;
  status: StepStatus;
  step: StepId;
  t_end: Timestamp | null;
  t_start: Timestamp;
  /**
   * 썸네일 파일이 있다 (thumbs/<스텝>.jpg, 파일 유무가 기준)
   */
  thumbnail?: boolean;
}
/**
 * 반복 스텝의 회차 하나 (회차 안 스텝은 run.children으로 읽는다). status는 회차 안 스텝 중 가장 나쁜 결과 (error > fail > cancelled > aborted > running > success)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "IterationSummary".
 */
export interface IterationSummary {
  duration_ms: number | null;
  iteration: number;
  status: StepStatus;
  /**
   * 회차 안 스텝 수 (안쪽 호출 포함)
   */
  steps: number;
  t_start: Timestamp;
}
/**
 * 뷰어가 쓰는 영상 정보: video/index.json이 있으면 그 내용, 없으면 segments.jsonl에서 읽은 조각·빈 구간 (finalized false)
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "VideoView".
 */
export interface VideoView {
  /**
   * index.json(마무리 결과)에서 읽었다
   */
  finalized: boolean;
  gaps: import("./video-index.js").Gap[];
  reason?: import("./video-index.js").VideoReason;
  segments: import("./video-index.js").Segment[];
  status: import("./video-index.js").VideoStatus;
}
/**
 * 환경 차이 한 줄 (같은 값은 넣지 않는다). key는 observed.dpi·conditions.profile·conditions.settings.<키>·packages.<이름>·plugins.<ID>·game_build 같은 점 경로. 비밀값 설정은 값 없이 키만
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CompareEnvDiff".
 */
export interface CompareEnvDiff {
  /**
   * 기준 실행의 값 (없으면 null)
   */
  baseline: {
    [k: string]: unknown | undefined;
  };
  key: string;
  /**
   * 이 실행의 값 (없으면 null)
   */
  run: {
    [k: string]: unknown | undefined;
  };
}
/**
 * 스냅샷 비교: 스냅샷 폴더의 상대 경로·바이트를 정렬해 만든 sha256
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CompareGraph".
 */
export interface CompareGraph {
  baseline_hash: Sha256;
  changed: {
    change: "added" | "modified" | "removed";
    /**
     * 스냅샷 안 경로 (워크스페이스 기준)
     */
    path: string;
  }[];
  hash: Sha256;
  same: boolean;
}
/**
 * run.compare 결과: 지난 성공(기준 실행)과의 차이. 기준 실행이 없으면 baseline이 null이고 나머지 비교는 없다
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CompareResult".
 */
export interface CompareResult {
  baseline: RunId | null;
  /**
   * auto: 같은 테스트·같은 프로필·pass·디버거 개입 아님 중 가장 최근, user: 요청이 고름
   */
  baseline_picked?: "auto" | "user";
  env?: CompareEnvDiff[];
  graph?: CompareGraph;
  /**
   * 기준 실행이 없을 때의 안내 (예: 비교할 성공 실행 없음)
   */
  message?: string;
  run_id: RunId;
  screen?: CompareScreen;
  time?: CompareTime;
}
/**
 * 화면 차이: 실패 스텝(또는 고른 스텝)의 증거와 기준 실행의 같은 호출 경로·같은 노드 썸네일을 같은 크기 회색조로 줄여 비교. 한쪽이 없으면 reason
 *
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CompareScreen".
 */
export interface CompareScreen {
  /**
   * 기준 실행 폴더 기준 파일 (thumbs/<스텝>.jpg)
   */
  baseline_file: null | string;
  baseline_step: StepId | null;
  /**
   * 달라진 픽셀 비율 (0~1)
   */
  diff_ratio?: number;
  /**
   * 이 실행 폴더 기준 파일 (steps/<스텝>_fail.png 등)
   */
  file: null | string;
  /**
   * 비교하지 못한 이유. policy_omitted: 정책으로 남기지 않음, no_thumbnail: 기준 실행에 썸네일 없음, no_evidence: 이 실행에 증거 없음, no_matching_step: 기준 실행에 같은 노드 스텝 없음
   */
  reason?: "no_evidence" | "no_matching_step" | "no_thumbnail" | "policy_omitted";
  /**
   * 차이 영역 상자 (이 실행 증거 이미지 좌표)
   *
   * @maxItems 5
   */
  regions?:
    | []
    | [Rect]
    | [Rect, Rect]
    | [Rect, Rect, Rect]
    | [Rect, Rect, Rect, Rect]
    | [Rect, Rect, Rect, Rect, Rect];
  step: StepId;
}
/**
 * This interface was referenced by `RunIndex`'s JSON-Schema
 * via the `definition` "CompareTime".
 */
export interface CompareTime {
  /**
   * 반복 노드(step)에서 앞 절반 중앙값의 2배를 넘는 경과가 이어지기 시작한 첫 회차
   */
  inflections: {
    after_ms: number;
    before_ms: number;
    from_iteration: number;
    graph: string;
    node: string;
    step: StepId;
  }[];
  /**
   * 노드별 평균 경과 비교 (한쪽에만 있으면 그쪽 값은 null)
   */
  nodes: {
    baseline_count: number;
    baseline_mean_ms: null | number;
    count: number;
    graph: string;
    mean_ms: null | number;
    node: string;
  }[];
}
