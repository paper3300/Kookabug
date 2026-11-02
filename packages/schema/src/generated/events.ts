/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * events.jsonl 한 줄 (실행 이벤트 하나). event 값으로 종류를 고른다
 */
export type Event =
  | RunStartEvent
  | StepStartEvent
  | AttemptEndEvent
  | StepEndEvent
  | LogEvent
  | InputDownEvent
  | InputUpEvent
  | InputRecoveredEvent
  | CancelRequestedEvent
  | ControlLostEvent
  | DebugPauseEvent
  | DebugResumeEvent
  | WorkerStartEvent
  | WorkerExitEvent
  | RunEndEvent;
/**
 * 실행 ID: 소문자·숫자 8자
 */
export type RunId = string;
/**
 * 저널 안 순번. 1부터 빈틈 없이
 */
export type Seq = number;
/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 */
export type Timestamp = string;
export type StepId = string;
/**
 * 호출 경로: 테스트부터의 호출 노드들 + 노드
 *
 * @minItems 1
 */
export type CallPath = [string, ...string[]];
/**
 * 취소 사유: 외부 취소, 테스트 전체 기한 초과, 감독자 사망
 */
export type CancelReason = "cancelled" | "deadline_exceeded" | "supervisor_lost";
/**
 * 재개 방식: continue 다음 브레이크포인트·일시정지 요청까지, step_over 호출 깊이가 같거나 얕은 다음 경계, step_into 다음 경계, step_out 더 얕은 다음 경계
 */
export type ResumeMode = "continue" | "step_into" | "step_out" | "step_over";
/**
 * 실행을 마무리한 쪽: runner 자신, 또는 runner가 죽은 뒤 감독자
 */
export type FinalizedBy = "runner" | "supervisor";
/**
 * 눌렸을 수 있는 키 복구 결과: 복구함, 다른 쪽이 이미 복구함(복구 표시 파일), 복구할 키 없음, 임대권을 얻지 못함, 복구 수단 없음
 */
export type InputRecovery =
  "already_recovered" | "lease_busy" | "not_needed" | "recovered" | "unavailable";
export type Verdict = "error" | "fail" | "pass" | "skipped";

/**
 * 실행 시작. runner가 저널의 첫 줄로 쓴다
 */
export interface RunStartEvent {
  event: "run.start";
  /**
   * 실행한 테스트 그래프 (워크스페이스 기준)
   */
  graph: string;
  protocol: number;
  run: RunId;
  runner: ProcessInfo;
  seq: Seq;
  t: Timestamp;
}
export interface ProcessInfo {
  /**
   * 프로세스 생성 시각 (Unix 기준 UTC 마이크로초). PID 재사용을 가린다
   */
  created: number;
  pid: number;
  version: string;
}
/**
 * 스텝 시작. 재시도해도 스텝 하나에 한 번
 */
export interface StepStartEvent {
  attempt: number;
  event: "step.start";
  /**
   * 반복 안 스텝의 회차 (0부터)
   */
  iteration?: number;
  node: string;
  parent: StepId | null;
  path: CallPath;
  run: RunId;
  seq: Seq;
  step: StepId;
  t: Timestamp;
}
/**
 * 재시도할 중간 시도의 실패. 판정에는 들어가지 않는다
 */
export interface AttemptEndEvent {
  attempt: number;
  duration_ms: number;
  event: "attempt.end";
  exit: null | string;
  /**
   * 반복 안 스텝의 회차 (0부터)
   */
  iteration?: number;
  message?: string;
  outputs: {
    [k: string]: unknown | undefined;
  };
  run: RunId;
  seq: Seq;
  status: "fail";
  step: StepId;
  t: Timestamp;
}
/**
 * 스텝 결과. 이 줄이 없는 스텝은 중단된 것이다. active_duration_ms·evidence는 M3부터
 */
export interface StepEndEvent {
  /**
   * 멈춘 시간을 뺀 경과. 그 스텝 구간에 멈춤이 있었을 때만 쓴다 (duration_ms는 실제 경과)
   */
  active_duration_ms?: number;
  artifacts?: string[];
  attempt: number;
  duration_ms: number;
  error?: {
    code: string;
    message: string;
  };
  event: "step.end";
  evidence?: StepEvidence;
  exit: null | string;
  /**
   * 서브그래프 호출이면 이번 실행에 쓴 스냅샷 파일
   */
  graph?: string;
  /**
   * 반복 안 스텝의 회차 (0부터)
   */
  iteration?: number;
  message?: string;
  omitted?: Omitted[];
  outputs: {
    [k: string]: unknown | undefined;
  };
  retried?: true;
  run: RunId;
  seq: Seq;
  status: "cancelled" | "error" | "fail" | "success";
  step: StepId;
  t: Timestamp;
}
/**
 * fail·error·stale_observation으로 끝난 스텝의 증거 (스키마 v0 6장). 파일은 artifacts에도 있다. 시각(*_at_ms)은 스텝 시작 기준 벽시계 ms. mid는 표본 중 (시작 + 끝)/2에 가장 가까운 캡처이고 최선 노력이다: 편차가 경과의 1/4을 넘거나 첫·마지막 말고 표본이 없으면 null과 mid_missing. 매칭 후보(target·threshold·candidates)는 찾기·대기 노드가 fail 출구로 끝났을 때 그 스텝이 마지막으로 찾은 캡처의 서로 다른 자리 점수 상위 3개(그 캡처에서 여러 target을 찾았으면 최고점이 가장 높은 target)
 */
export interface StepEvidence {
  /**
   * @maxItems 3
   */
  candidates?:
    | []
    | [EvidenceCandidate]
    | [EvidenceCandidate, EvidenceCandidate]
    | [EvidenceCandidate, EvidenceCandidate, EvidenceCandidate];
  /**
   * 그 스텝의 첫 캡처 (steps/<스텝>_first.png)
   */
  first?: string;
  first_at_ms?: number;
  /**
   * 그 스텝의 마지막 캡처 (steps/<스텝>_fail.png 또는 _error.png)
   */
  last?: string;
  last_at_ms?: number;
  /**
   * 중간 캡처 (steps/<스텝>_mid.png), 없으면 null
   */
  mid?: null | string;
  /**
   * 고른 중간 캡처의 실제 캡처 시각
   */
  mid_at_ms?: number;
  /**
   * 중간 장면이 없는 이유
   */
  mid_missing?: "no_sample_near_mid";
  /**
   * 고른 캡처와 (시작 + 끝)/2의 차이 (절댓값)
   */
  mid_offset_ms?: number;
  /**
   * 마지막으로 찾은 target (스냅샷 안 워크스페이스 기준 경로)
   */
  target?: string;
  threshold?: number;
}
/**
 * 매칭 후보 하나. rect는 찾은 이미지 좌표(코어 노드는 창 전체 캡처라 _fail과 같다). 후보끼리는 서로 다른 자리다(점수 지도 봉우리에서 고르면 겹치지 않는다. 프레임 저장소가 없거나 봉우리 다시 고르기를 못 한 경우의 대체 경로는 크게 겹치는 것(IoU 0.3 초과)만 하나로 줄여 조금 겹칠 수 있다)
 */
export interface EvidenceCandidate {
  /**
   * [x, y, w, h] 픽셀
   *
   * @minItems 4
   * @maxItems 4
   */
  rect: [number, number, number, number];
  scale: number;
  score: number;
}
/**
 * 정책으로 남기지 않은 증거와 그 이유
 */
export interface Omitted {
  /**
   * 증거 종류: screenshot(스크린샷·실패 증거), text(OCR 글자), thumbnail(스텝 썸네일, M3)
   */
  kind: "screenshot" | "text" | "thumbnail";
  name?: string;
  /**
   * sensitive_target = sensitive target 영역에서 읽은 OCR 글자
   */
  reason: "capture_policy" | "policy_off" | "secret_input" | "sensitive_target";
  /**
   * 정책을 끈 곳
   */
  source?: string;
}
/**
 * 노드·runner 로그
 */
export interface LogEvent {
  event: "log";
  level: "debug" | "error" | "info" | "warn";
  message: string;
  node: null | string;
  run: RunId;
  seq: Seq;
  step: StepId | null;
  t: Timestamp;
}
/**
 * 입력 액터가 백엔드에 누르기를 보내기 전에 쓴다
 */
export interface InputDownEvent {
  button?: string;
  device: "keyboard" | "mouse";
  event: "input.down";
  key?: string;
  run: RunId;
  seq: Seq;
  step?: StepId;
  t: Timestamp;
}
/**
 * 입력 액터가 백엔드에 떼기를 보낸 뒤에 쓴다
 */
export interface InputUpEvent {
  button?: string;
  device: "keyboard" | "mouse";
  event: "input.up";
  key?: string;
  run: RunId;
  seq: Seq;
  step?: StepId;
  t: Timestamp;
}
/**
 * 앞 실행(from_run)에서 눌렸을 수 있는 키·버튼을 뗐다
 */
export interface InputRecoveredEvent {
  by: {
    kind: "runner" | "supervisor";
    run?: RunId;
  };
  event: "input.recovered";
  from_run: RunId;
  inputs: InputRef[];
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 키보드 키 또는 마우스 버튼
 */
export interface InputRef {
  button?: string;
  device: "keyboard" | "mouse";
  key?: string;
}
/**
 * runner가 취소 순서를 시작했다
 */
export interface CancelRequestedEvent {
  event: "cancel.requested";
  reason: CancelReason;
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 제어 채널이 끊겼다. 감독자는 살아 있으므로 취소가 아니다
 */
export interface ControlLostEvent {
  error?: string;
  event: "control.lost";
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 멈춤 확정. step은 경계 멈춤이면 다음에 시작할 스텝(아직 step.start 전), 폴링 멈춤이면 기다리던 스텝. node·graph·path·reason·where는 M3부터 (M0b 기록에는 없다)
 */
export interface DebugPauseEvent {
  event: "debug.pause";
  /**
   * 멈춘 노드가 든 그래프 (워크스페이스 기준, 브레이크포인트 열쇠와 같은 경로)
   */
  graph?: string;
  node?: string;
  path?: CallPath;
  /**
   * breakpoint: 브레이크포인트 적중, step: Step 목표 경계, request: 일시정지 요청
   */
  reason?: "breakpoint" | "request" | "step";
  run: RunId;
  seq: Seq;
  step?: StepId;
  t: Timestamp;
  /**
   * boundary: 스텝 시작 직전, poll: 코어 노드의 멈출 수 있는 기다림 안 (일시정지 요청만)
   */
  where?: "boundary" | "poll";
}
/**
 * 재개. mode·epoch·paused_ms는 M3부터 (M0b 기록에는 없다)
 */
export interface DebugResumeEvent {
  /**
   * 재개 뒤의 관측 세대 (재개마다 1 오른다. 이보다 오래된 관측값으로는 입력·분기하지 않는다)
   */
  epoch?: number;
  event: "debug.resume";
  mode?: ResumeMode;
  /**
   * 이번 멈춤의 길이 (멈춤 확정부터 재개까지, 기한에서 뺀 시간)
   */
  paused_ms?: number;
  run: RunId;
  seq: Seq;
  step?: StepId;
  t: Timestamp;
}
/**
 * 워커 프로세스 시작
 */
export interface WorkerStartEvent {
  event: "worker.start";
  pid: number;
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 워커 프로세스 종료
 */
export interface WorkerExitEvent {
  event: "worker.exit";
  exit_code?: number;
  pid: number;
  /**
   * shutdown: 마무리에서 정상 종료, killed_after_grace: 취소·shutdown 유예를 넘겨 끝냄, unexpected: 스스로 죽음(실행 중 kill·크래시, hello 전 종료 포함), start_timeout: hello 기한 초과로 끝냄, start_failed: hello 실패(import 오류·프로토콜 불일치)로 끝냄, cancelled: 시작 중 취소·전체 기한으로 끝냄
   */
  reason?:
    | "cancelled"
    | "killed_after_grace"
    | "shutdown"
    | "start_failed"
    | "start_timeout"
    | "unexpected";
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 실행 결과. runner가 쓰거나, runner가 죽으면 감독자가 쓴다 (runner_died). active_duration_ms·paused_ms·debug_intervened·omitted는 M3부터
 */
export interface RunEndEvent {
  /**
   * 멈춘 시간을 뺀 경과 (duration_ms는 실제 경과)
   */
  active_duration_ms?: number;
  cancel_reason?: CancelReason;
  code: string;
  /**
   * 디버거로 한 번이라도 멈췄다 (브레이크포인트 적중·일시정지 모두)
   */
  debug_intervened?: boolean;
  duration_ms: number | null;
  event: "run.end";
  failure_path: CallPath | null;
  failure_step: StepId | null;
  finalized_by: FinalizedBy;
  input_recovery?: InputRecovery;
  /**
   * 실행 단위로 남기지 않은 기록
   *
   * @minItems 1
   */
  omitted?: [RunOmitted, ...RunOmitted[]];
  /**
   * 멈춰 있던 시간 합
   */
  paused_ms?: number;
  reason: string;
  run: RunId;
  runner_exit_code?: number;
  seq: Seq;
  t: Timestamp;
  /**
   * 감독자가 마무리 전에 잘라 낸 저널 끝 바이트 수
   */
  truncated_bytes?: number;
  verdict: Verdict;
}
/**
 * 실행 단위로 남기지 않은 기록 (스텝 Omitted와 같은 모양). video/encoder_stuck: 녹화 스레드가 3초 안에 끝나지 않아 runner가 영상 파일을 건드리지 않고 포기했다 — runner 종료를 확인한 감독자가 video/를 지운다
 */
export interface RunOmitted {
  kind: "video";
  reason: "encoder_stuck";
}
