/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * runner 상태 (제어 요청의 응답): running 실행 중, pausing 다음 경계에서 멈출 것, paused 멈춤, cancelling 취소 순서 진행 중
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlState".
 */
export type ControlState = "cancelling" | "paused" | "pausing" | "running";
/**
 * 노드 입력·출력·ctx 값 (kookabug_sdk.codec). JSON 값은 그대로, SDK 타입은 {"$kb": 태그, ...}(secret·rect·point·window·process·image·match·target), $kb 키를 가진 사용자 객체는 {"$kb": "dict", "value": ...}
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "WireValue".
 */
export type WireValue = unknown;
/**
 * 노드 실행 번호 (runner가 워커마다 1부터 붙인다). 워커의 ctx 요청은 자기를 부른 node.invoke의 번호를 싣고, runner는 지금 기다리는 실행의 번호가 아니면 처리하지 않는다(context_violation)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "InvokeId".
 */
export type InvokeId = number;
/**
 * 관측 요청의 노드 기한 남은 시간 (밀리초, 0 이상). runner는 min(설정 기한, 이것, 전체 기한 남은 시간)으로 관측하고, 이것 때문에 끝나면 observation_timeout으로 답한다. 없으면 노드 기한 없음
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "DeadlineMs".
 */
export type DeadlineMs = number;
/**
 * 시간 길이 (밀리초, 0 이상)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "Millis".
 */
export type Millis = number;
/**
 * 표준: -32700 parse_error, -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32001 cancelled, -32002 node_error, -32003 context_violation, -32004 node_contract, -32005 protocol_version, -32006 observation_timeout(관측이 노드 기한 안에 끝나지 않음 — 워커에서 ObservationTimeout), -32007 stale_observation(입력 직전 재검증 실패 — 워커에서 StaleObservation, 처리되지 않은 fail)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ErrorCode".
 */
export type ErrorCode =
  | -32700
  | -32600
  | -32601
  | -32602
  | -32603
  | -32001
  | -32002
  | -32003
  | -32004
  | -32005
  | -32006
  | -32007;
/**
 * 보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다 (양쪽이 따로 센다)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestId".
 */
export type RequestId = number;
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "JsonRpcVersion".
 */
export type JsonRpcVersion = "2.0";
/**
 * 점으로 나눈 소문자 이름 (예: node.invoke, run.cancel)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "MethodName".
 */
export type MethodName = string;

/**
 * 감독자 ↔ runner, runner ↔ 워커 사이 JSON-RPC 2.0 메시지 하나 (named pipe 프레임 본문, UTF-8 JSON). 메서드별 params·result는 쓰는 작업에서 $defs에 더한다
 */
export interface RpcMessageDefs {}
/**
 * cancel 알림 (runner → 워커): 이후 ctx 호출·sleep·check_cancel이 Cancelled
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CancelParams".
 */
export interface CancelParams {}
/**
 * run.cancel·run.pause·run.resume·run.breakpoints (감독자 → runner)의 결과. 노드가 실행 중이어도 받는 즉시 답한다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlStateResult".
 */
export interface ControlStateResult {
  state: ControlState;
}
/**
 * ctx.artifacts.save (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxArtifactsSaveParams".
 */
export interface CtxArtifactsSaveParams {
  image: WireValue;
  invoke: InvokeId;
  name: string;
}
/**
 * 실행 폴더 기준 경로. 기록 정책으로 생략하면 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxArtifactsSaveResult".
 */
export interface CtxArtifactsSaveResult {
  path: string | null;
}
/**
 * ctx.capture (워커 → runner). region은 rect 또는 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxCaptureParams".
 */
export interface CtxCaptureParams {
  deadline_ms?: DeadlineMs;
  invoke: InvokeId;
  region: WireValue;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxCaptureResult".
 */
export interface CtxCaptureResult {
  image: WireValue;
}
/**
 * ctx.input.click (워커 → runner). at은 point·rect·match, count는 클릭 횟수(생략하면 1)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxInputClickParams".
 */
export interface CtxInputClickParams {
  at: WireValue;
  button: string;
  count?: number;
  invoke: InvokeId;
}
/**
 * ctx.input.drag (워커 → runner). start·end는 point·rect·match
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxInputDragParams".
 */
export interface CtxInputDragParams {
  button: string;
  duration_ms: Millis;
  end: WireValue;
  invoke: InvokeId;
  start: WireValue;
}
/**
 * ctx.input.key (워커 → runner). hold_ms는 누르고 있는 시간(생략하면 0)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxInputKeyParams".
 */
export interface CtxInputKeyParams {
  hold_ms?: Millis;
  invoke: InvokeId;
  key: string;
}
/**
 * ctx.input.scroll (워커 → runner). at은 point·rect·match, amount는 휠 칸 수(양수 = 위)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxInputScrollParams".
 */
export interface CtxInputScrollParams {
  amount: number;
  at: WireValue;
  invoke: InvokeId;
}
/**
 * ctx.input.type_text (워커 → runner). text는 문자열이나 비밀값
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxInputTypeTextParams".
 */
export interface CtxInputTypeTextParams {
  invoke: InvokeId;
  text: WireValue;
}
/**
 * ctx.log (워커 → runner). message는 str()로 만든 문자열, 비밀값·비밀값 메시지면 그 wire 값({"$kb": "secret"|"secret_message", ...}) — 가릴지는 runner가 기록 정책(record.redact_secrets)으로 정한다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxLogParams".
 */
export interface CtxLogParams {
  invoke: InvokeId;
  level: "debug" | "info" | "warn" | "error";
  message: WireValue;
}
/**
 * ctx.ocr.read (워커 → runner). image는 참조 이미지나 파일·바이트 이미지, region은 rect 또는 null, sensitive면 글자가 비밀값으로 온다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxOcrReadParams".
 */
export interface CtxOcrReadParams {
  deadline_ms?: DeadlineMs;
  image: WireValue;
  invoke: InvokeId;
  region: WireValue;
  sensitive: boolean;
}
/**
 * result는 ocr_result 값
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxOcrReadResult".
 */
export interface CtxOcrReadResult {
  result: WireValue;
}
/**
 * ctx.process.close (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxProcessCloseParams".
 */
export interface CtxProcessCloseParams {
  force_after_ms: Millis;
  invoke: InvokeId;
  process: WireValue;
}
/**
 * closed: 강제 종료 없이 끝났는가
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxProcessCloseResult".
 */
export interface CtxProcessCloseResult {
  closed: boolean;
}
/**
 * ctx.process.find_window (워커 → runner). deadline_ms가 있으면 창이 뜰 때까지 기다린다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxProcessFindWindowParams".
 */
export interface CtxProcessFindWindowParams {
  deadline_ms?: DeadlineMs;
  invoke: InvokeId;
  process: WireValue;
  title: string | null;
}
/**
 * ctx.process.launch (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxProcessLaunchParams".
 */
export interface CtxProcessLaunchParams {
  args: string[];
  cwd: string | null;
  invoke: InvokeId;
  path: string;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxProcessLaunchResult".
 */
export interface CtxProcessLaunchResult {
  process: WireValue;
}
/**
 * ctx.setting (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxSettingParams".
 */
export interface CtxSettingParams {
  invoke: InvokeId;
  key: string;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxSettingResult".
 */
export interface CtxSettingResult {
  value: WireValue;
}
/**
 * ctx.vars.get·has (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVarsGetParams".
 */
export interface CtxVarsGetParams {
  invoke: InvokeId;
  name: string;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVarsGetResult".
 */
export interface CtxVarsGetResult {
  found: boolean;
  value: WireValue;
}
/**
 * ctx.vars.set (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVarsSetParams".
 */
export interface CtxVarsSetParams {
  invoke: InvokeId;
  name: string;
  value: WireValue;
}
/**
 * ctx.vision.diff (워커 → runner). a·b는 이미지, region은 rect 또는 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVisionDiffParams".
 */
export interface CtxVisionDiffParams {
  a: WireValue;
  b: WireValue;
  invoke: InvokeId;
  region: WireValue;
}
/**
 * 채널 평균 절대 차이 / 255 (0 = 같음, 1 = 완전히 다름)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVisionDiffResult".
 */
export interface CtxVisionDiffResult {
  value: number;
}
/**
 * ctx.vision.find (워커 → runner). image는 이미지, target은 target 값, region은 rect 또는 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVisionFindParams".
 */
export interface CtxVisionFindParams {
  deadline_ms?: DeadlineMs;
  image: WireValue;
  invoke: InvokeId;
  region: WireValue;
  target: WireValue;
}
/**
 * match는 match 값, 못 찾으면 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxVisionFindResult".
 */
export interface CtxVisionFindResult {
  match: WireValue;
}
/**
 * 창 하나를 받는 요청 (워커 → runner): ctx.windows.info·activate, ctx.set_window
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowParams".
 */
export interface CtxWindowParams {
  invoke: InvokeId;
  window: WireValue;
}
/**
 * ctx.windows.find·ctx.process.find_window의 결과. window는 window 값, 없으면 null
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowResult".
 */
export interface CtxWindowResult {
  window: WireValue;
}
/**
 * ctx.windows.find (워커 → runner). title은 부분 일치 또는 /정규식/
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowsFindParams".
 */
export interface CtxWindowsFindParams {
  invoke: InvokeId;
  owned: boolean;
  process_name: string | null;
  title: string | null;
}
/**
 * info는 window_info 값
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowsInfoResult".
 */
export interface CtxWindowsInfoResult {
  info: WireValue;
}
/**
 * ctx.windows.set_client_size (워커 → runner)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowsSetClientSizeParams".
 */
export interface CtxWindowsSetClientSizeParams {
  height: number;
  invoke: InvokeId;
  width: number;
  window: WireValue;
}
/**
 * ok: 다시 읽은 크기가 요청과 같은가
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "CtxWindowsSetClientSizeResult".
 */
export interface CtxWindowsSetClientSizeResult {
  ok: boolean;
}
/**
 * 결과 없음 (ctx.log·ctx.vars.set·ctx.input.*·ctx.windows.activate·ctx.set_window·worker.shutdown)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "EmptyResult".
 */
export interface EmptyResult {}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ErrorObject".
 */
export interface ErrorObject {
  code: ErrorCode;
  /**
   * 오류별 추가 정보 (node_error: 예외 이름·메시지·traceback)
   */
  data?: unknown;
  message: string;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ErrorResponse".
 */
export interface ErrorResponse {
  error: ErrorObject;
  /**
   * 요청을 읽지 못했으면(JSON 아님·id 없음) null
   */
  id: RequestId | null;
  jsonrpc: JsonRpcVersion;
}
/**
 * node.invoke (runner → 워커): 노드 하나 실행. pure·effects는 runner가 아는 선언(워커 선언과 다르면 node_contract), deadline_remaining_ms는 테스트 전체 기한까지 남은 시간
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodeInvokeParams".
 */
export interface NodeInvokeParams {
  config: WireValue;
  deadline_remaining_ms: number;
  effects: ("capture" | "input" | "process")[];
  inputs: WireValue;
  invoke: InvokeId;
  node_id: string;
  pure: boolean;
  step: string | null;
  type: string;
  window: WireValue;
}
/**
 * 노드 결과. 순수 노드는 exit·kind가 null. 오류는 오류 응답(cancelled·node_error·context_violation·node_contract)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodeInvokeResult".
 */
export interface NodeInvokeResult {
  exit: string | null;
  kind: "ok" | "fail" | null;
  /**
   * 노드 메시지. 비밀값이 든 메시지(SDK SecretMessage)는 가린 글·원문을 둘 다 싣고, 무엇을 기록할지는 runner가 record.redact_secrets로 정한다
   */
  message: (string | null) | SecretMessageWire;
  outputs: WireValue;
}
/**
 * 비밀값이 든 메시지 (kookabug_sdk.codec, SDK SecretMessage): 가린 글(masked)과 원문(raw). 원문은 인증된 파이프로만 간다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretMessageWire".
 */
export interface SecretMessageWire {
  $kb: "secret_message";
  masked: string;
  raw: string;
}
/**
 * 응답이 없는 알림 (예: 취소)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "Notification".
 */
export interface Notification {
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
/**
 * 이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "Params".
 */
export interface Params {
  [k: string]: unknown | undefined;
}
/**
 * 프로세스 식별 (PID + 생성 시각). created는 Windows FILETIME(100ns 단위)을 10진 문자열로 — RPC 정수 범위(2^53)를 넘는다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "ProcessIdent".
 */
export interface ProcessIdent {
  created: string;
  pid: number;
}
/**
 * 응답을 기다리는 요청
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "Request".
 */
export interface Request {
  id: RequestId;
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
/**
 * run.breakpoints (감독자 → runner, M3): 브레이크포인트 목록 전체를 바꾼다. 다음 스텝 경계부터 적용. 결과는 ControlStateResult
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunBreakpointsParams".
 */
export interface RunBreakpointsParams {
  breakpoints: import("./breakpoints.js").BreakpointList;
}
/**
 * run.cancel (감독자 → runner) params: 감독자가 이미 건 하드 종료 타이머의 기한. 타이머는 미루지 않는다(영상 마무리 단계로 다시 건 타이머는 지금 + 유예로 당긴다 — RunnerVideoFinishingResult). runner는 이 기한에서 기록 여유를 뺀 때까지만 녹화를 기다리고 그 전에 run.end·run.json을 쓴다. hard_stop_at_mono: 하드 종료 시각의 단조 시계 초(Python time.monotonic). 감독자·runner는 같은 Windows PC의 프로세스이고 time.monotonic은 시스템 전역 QueryPerformanceCounter라 원점이 같다는 것이 계약이다 — 전달 지연과 상관없이 정확한 기한이다. hard_stop_in_ms: 보내기 직전에 잰 남은 실제 시간(ms). runner는 min(hard_stop_at_mono, 꺼낸 시각 + hard_stop_in_ms)를 기한으로 쓰고(어느 쪽도 늦게 잡지 않게), hard_stop_at_mono가 이미 지났거나 꺼낸 시각 + 마무리 유예보다 멀면(시계 원점이 다르다고 본다) 녹화를 기다리지 않고 바로 기록한다. hard_stop_at_mono 없이 hard_stop_in_ms만 오면 꺼낸 시각 + 남은 시간을 쓰지만 전달 지연만큼 늦게 잡힐 수 있다(상한 없음). params가 없으면 runner.stopping 시각 + shutdown_grace_ms로 본다 (M0b 호출과 같다)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunCancelParams".
 */
export interface RunCancelParams {
  hard_stop_at_mono?: number;
  hard_stop_in_ms?: number;
}
/**
 * run.resume (감독자 → runner) params. mode를 빼거나 params가 없으면 continue (M0b 호출과 같다). Step 목표는 멈춘 자리의 호출 깊이로 정한다 (M3). 멈춰 있지 않은데 step_*이면 runner는 아무것도 바꾸지 않고 invalid_params 오류(data {reason: not_paused, state})로 답한다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunResumeParams".
 */
export interface RunResumeParams {
  mode?: import("./events.js").ResumeMode;
}
/**
 * 실행 사양: 감독자가 runner의 stdin에 JSON 하나로 주고 닫는다 (제어 채널 키를 명령줄·실행 폴더에 남기지 않는다). 시간 값을 빼면 runner 기본값(취소 유예 2000, 워커 시작 30000, 마무리 유예 5000, 자기 종료 여유 10000 ms)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSpec".
 */
export interface RunSpec {
  /**
   * 그 실행을 낸 에이전트 (M5 에이전트 제어 실행)
   */
  agent?: {
    id: string;
  };
  /**
   * 시작할 때의 브레이크포인트 (M3). 사람이 UI에서 시작한 실행만 daemon이 채운다. 없으면 빈 목록
   */
  breakpoints?: import("./breakpoints.js").BreakpointList;
  /**
   * 관측 호출(캡처·찾기·OCR) 하나의 설정 기한. 넘으면 capture_timeout. 없으면 2000
   */
  capture_timeout_ms?: number;
  /**
   * 제어 채널: 감독자가 연 파이프 이름과 상호 인증 키(32바이트 hex)
   */
  control: {
    key: string;
    pipe: string;
  };
  /**
   * 테스트 전체 기한 (runner 시작부터)
   */
  deadline_ms: number;
  /**
   * 프레임 저장소 바이트 예산 (MiB). 넘으면 출력 참조 프레임부터 버린다. 없으면 512
   */
  frame_budget_mib?: number;
  /**
   * 스텝 출력으로 나간 캡처를 남기는 개수. 없으면 32
   */
  frame_output_refs?: number;
  /**
   * 실행할 테스트 그래프 (워크스페이스 기준 경로)
   */
  graph: string;
  /**
   * 루트 그래프 값 (M5 에이전트 제어 실행 — daemon 내부 진입점만 채운다). 있으면 graph 자리의 워크스페이스 파일 대신 이 값을 스냅샷에 쓴다
   */
  graph_value?: {
    [k: string]: unknown | undefined;
  };
  /**
   * 감독자가 만든 실행 Job 이름. runner는 어떤 자식도 띄우기 전에 자기를 넣는다
   */
  job_name: string;
  platform: RunSpecPlatform;
  /**
   * 워커가 import할 플러그인 모듈 (개발용 --plugin-module). 비면 워커를 띄우지 않는다
   */
  plugin_modules: string[];
  profile: null | string;
  /**
   * 감독자가 만든 실행 폴더 (절대 경로)
   */
  run_dir: string;
  run_id: string;
  /**
   * 감독자가 살아 있을 때 자기 종료 감시자가 마무리 유예 뒤 더 기다리는 시간 (내부 값, 사용자 설정 아님)
   */
  self_kill_margin_ms?: number;
  /**
   * --set 설정값 (옵션 계층)
   */
  settings: {
    [k: string]: unknown | undefined;
  };
  /**
   * 마무리 유예: 감독자 하드 종료·감독자 사망 뒤 자기 종료까지
   */
  shutdown_grace_ms?: number;
  /**
   * 실행 출처 (M5: agent_control = 에이전트 게임 조작). run.json에 남는다
   */
  source?: "agent_control";
  supervisor: ProcessIdent;
  worker_cancel_grace_ms?: number;
  worker_start_timeout_ms?: number;
  workspace_root: string;
}
/**
 * 플랫폼: none(캡처·입력 없음), fake(frames를 차례로 캡처하거나 scenario 장면 전이 표를 따름, 입력은 input_log JSONL에 기록) 또는 windows(WGC 캡처·SendInput 입력·창·프로세스). hooks는 어느 종류에서나 입력 백엔드에 씌우는 키별 훅(숨은 테스트 기능)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSpecPlatform".
 */
export interface RunSpecPlatform {
  frames?: string[];
  hooks?: {
    after_down?: {
      [k: string]: string | undefined;
    };
    before_down?: {
      [k: string]: string | undefined;
    };
    before_up?: {
      [k: string]: string | undefined;
    };
  };
  input_log?: string;
  kind: "fake" | "none" | "windows";
  /**
   * fake: 장면 전이 표 파일(kookabug.fake-scenario/0, 절대 경로). 있으면 frames 대신 이 장면·가짜 창·프로세스를 쓴다
   */
  scenario?: string;
}
/**
 * runner.hello (runner → 감독자): 제어 채널에 붙은 직후. runner는 자기 식별을 스스로 알린다 (venv 런처를 거쳐 띄웠어도 실제 runner 프로세스)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunnerHelloParams".
 */
export interface RunnerHelloParams {
  protocol: number;
  run_id: string;
  runner: ProcessIdent;
}
/**
 * runner.stopping 알림 (runner → 감독자): 종료 단계에 들어갔다 (정상 마무리 finish 또는 취소 사유). 감독자는 처음 받은 때부터 마무리 유예가 지나도 runner가 살아 있으면 하드 종료한다 — 외부 취소 없이 기한 초과·정상 마무리에서 멈춘 runner도 같은 규칙
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunnerStoppingParams".
 */
export interface RunnerStoppingParams {
  reason: "cancelled" | "deadline_exceeded" | "finish" | "supervisor_lost";
}
/**
 * runner.video_finishing 요청 (runner → 감독자): run.end를 쓴 뒤 영상 인코더 준비가 아직이라 실행 중 모은 프레임을 쓰려고 영상 마무리 단계를 청한다 (M3 사람 확인 R1 F1). 판정·run.end는 이미 정해졌고 바뀌지 않는다. wait_ms: 인코더를 더 기다리려는 실제 시간 (감독자는 30000 ms보다 길게 허락하지 않는다)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunnerVideoFinishingParams".
 */
export interface RunnerVideoFinishingParams {
  wait_ms: number;
}
/**
 * runner.video_finishing 결과. granted: 허락. 감독자는 실행마다 한 번만 하드 종료 타이머를 지금 + wait_ms + shutdown_grace_ms로 다시 걸고, 외부 취소를 받았거나 이미 허락했거나 하드 종료했으면 거절한다. 단계 중 외부 취소가 오면 타이머를 지금 + 유예로 당긴다(run.cancel 기한). hard_stop_at_mono·hard_stop_in_ms: 지금 걸린 하드 종료 타이머의 기한 (RunCancelParams와 같은 뜻, 타이머를 쓰지 않는 감독자는 보내지 않는다). runner는 거절되면 모은 프레임을 버리고(starting 빈 구간 reason encoder_not_ready) 바로 마무리한다
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunnerVideoFinishingResult".
 */
export interface RunnerVideoFinishingResult {
  granted: boolean;
  hard_stop_at_mono?: number;
  hard_stop_in_ms?: number;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "SuccessResponse".
 */
export interface SuccessResponse {
  id: RequestId;
  jsonrpc: JsonRpcVersion;
  /**
   * 메서드별 결과 (JSON 값)
   */
  result: unknown;
}
/**
 * worker.hello (runner → 워커): 프로토콜, import할 플러그인 모듈, 실행 ID, 원본 워크스페이스(표시용), ctx.path() 루트(실행 스냅샷)
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkerHelloParams".
 */
export interface WorkerHelloParams {
  files_root: string;
  modules: string[];
  protocol: number;
  run_id: string;
  workspace_id: string;
}
/**
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkerHelloResult".
 */
export interface WorkerHelloResult {
  /**
   * M6: 워커의 실제 인터프리터 PID (기록용 — venv 런처를 거쳐 띄웠어도)
   */
  pid?: number;
  plugins: WorkerPlugin[];
  protocol: number;
}
/**
 * 워커가 읽은 플러그인 하나. schema는 노드 스키마 문서(node-schema.schema.json). M6: digest = schema_digest(schema) — 머리는 설치된 스키마 파일, 노드는 코드 선언
 *
 * This interface was referenced by `RpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkerPlugin".
 */
export interface WorkerPlugin {
  digest?: string;
  id: string;
  schema: {
    [k: string]: unknown | undefined;
  };
  version: string;
}

/**
 * 감독자 ↔ runner, runner ↔ 워커 사이 JSON-RPC 2.0 메시지 하나 (named pipe 프레임 본문, UTF-8 JSON). 메서드별 params·result는 쓰는 작업에서 $defs에 더한다
 */
export type RpcMessage = Request | Notification | SuccessResponse | ErrorResponse;
