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
 * 스텝 결과. 이 줄이 없는 스텝은 중단된 것이다
 */
export interface StepEndEvent {
  artifacts?: string[];
  attempt: number;
  duration_ms: number;
  error?: {
    code: string;
    message: string;
  };
  event: "step.end";
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
 * 정책으로 남기지 않은 증거와 그 이유
 */
export interface Omitted {
  /**
   * 증거 종류 (screenshot 등)
   */
  kind: string;
  name?: string;
  reason: "capture_policy" | "policy_off" | "secret_input";
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
 * 멈춤 확정
 */
export interface DebugPauseEvent {
  event: "debug.pause";
  run: RunId;
  seq: Seq;
  step?: StepId;
  t: Timestamp;
}
/**
 * 재개
 */
export interface DebugResumeEvent {
  event: "debug.resume";
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
  reason?: "killed_after_grace" | "shutdown" | "start_timeout" | "unexpected";
  run: RunId;
  seq: Seq;
  t: Timestamp;
}
/**
 * 실행 결과. runner가 쓰거나, runner가 죽으면 감독자가 쓴다 (runner_died)
 */
export interface RunEndEvent {
  cancel_reason?: CancelReason;
  code: string;
  duration_ms: number | null;
  event: "run.end";
  failure_path: CallPath | null;
  failure_step: StepId | null;
  finalized_by: FinalizedBy;
  input_recovery?: InputRecovery;
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
