/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ClientInfo".
 */
export type ClientInfo = UiClientInfo | AgentClientInfo;
/**
 * [x, y, w, h] 물리 픽셀
 *
 * @minItems 4
 * @maxItems 4
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Rect".
 */
export type Rect = [number, number, number, number];
/**
 * JSON-RPC 표준: -32700 parse_error(읽은 뒤 연결을 닫는다), -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32100 request_failed (종류는 error.data.code)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonErrorCode".
 */
export type DaemonErrorCode = -32700 | -32600 | -32601 | -32602 | -32603 | -32100;
/**
 * 표준 오류 또는 -32100 (DaemonErrorCode)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonErrorObject".
 */
export type DaemonErrorObject = DaemonStandardError | DaemonRequestFailedError;
/**
 * -32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로. M3: read_only(스냅샷 그래프 저장), not_paused(멈추지 않은 실행에 Step), run_not_debuggable(이 daemon이 띄운 UI 실행이 아님). M4 녹화: recording_active(이 daemon이 녹화 중이라 실행 거부 — starting 포함), input_lease_busy(입력 임대권을 다른 주체가 쥠), not_owner(녹화 세션을 연 연결이 아님), recorder_state_invalid(지금 녹화 상태에 맞지 않는 조작·없는 커밋 토큰), hook_failed(훅 프로세스를 띄우지 못함), hook_lost·input_overflow(훅이 끊김·중요 입력 유실로 녹화가 멈춤), no_frame(고를 프레임이 없음), 커밋 거부 classification_pending(비밀 판정 중)·text_review_required(확인 필요 입력)·secret_unresolved(키 없는 비밀값)·target_missing(대상 없는 클릭)·secret_region_overlap(비밀번호 칸과 겹치는 영역)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestFailedCode".
 */
export type RequestFailedCode =
  | "approval_required"
  | "classification_pending"
  | "hook_failed"
  | "hook_lost"
  | "input_lease_busy"
  | "input_overflow"
  | "no_frame"
  | "not_owner"
  | "recorder_state_invalid"
  | "recording_active"
  | "secret_region_overlap"
  | "secret_unresolved"
  | "target_missing"
  | "text_review_required"
  | "capture_failed"
  | "capture_timeout"
  | "capture_unsupported"
  | "doc_not_open"
  | "dpi_awareness_unavailable"
  | "exists"
  | "frame_expired"
  | "idempotency_conflict"
  | "input_desktop_unavailable"
  | "invalid_json"
  | "io_error"
  | "key_unknown"
  | "launch_failed"
  | "not_found"
  | "not_paused"
  | "ocr_model_corrupt"
  | "ocr_model_missing"
  | "path_outside_workspace"
  | "permission_denied"
  | "platform_unavailable"
  | "point_obscured"
  | "private_path"
  | "protocol_mismatch"
  | "read_only"
  | "revision_conflict"
  | "run_active"
  | "run_busy"
  | "run_not_debuggable"
  | "run_not_found"
  | "shutting_down"
  | "target_elevated"
  | "target_image_invalid"
  | "target_invalid"
  | "unauthenticated"
  | "validation_failed"
  | "window_gone"
  | "window_minimized"
  | "window_mismatch"
  | "window_not_foreground"
  | "window_not_found";
/**
 * 실행 ID: 소문자·숫자 8자
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunId".
 */
export type RunId = string;
/**
 * 녹화 세션 상태: idle → starting → recording ⇄ paused → stopped → committing → committed | stopped, 또는 discarded. 오류로 멈춤(hook_lost·input_overflow·window_gone·storage_full)도 stopped (stop_reason)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderState".
 */
export type RecorderState =
  | "committed"
  | "committing"
  | "discarded"
  | "idle"
  | "paused"
  | "recording"
  | "starting"
  | "stopped";
/**
 * 녹화 스텝 ID (세션 안에서 바뀌지 않음)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepId".
 */
export type RecorderStepId = string;
/**
 * 보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestId".
 */
export type RequestId = number;
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "JsonRpcVersion".
 */
export type JsonRpcVersion = "2.0";
/**
 * daemon이 연 문서 번호 (연결과 무관)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DocId".
 */
export type DocId = string;
/**
 * [w, h] 물리 픽셀
 *
 * @minItems 2
 * @maxItems 2
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Size".
 */
export type Size = [number, number];
/**
 * 이미지는 RPC에 싣지 않는다. cache는 .kookabug/cache/editor/<이름>(kbimg://cache/<이름>), workspace는 워크스페이스 파일(kbimg://ws/<경로>)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ImageRef".
 */
export type ImageRef =
  | {
      cache: string;
      height: number;
      width: number;
    }
  | {
      height: number;
      width: number;
      workspace: WorkspacePath;
    };
/**
 * 워크스페이스 루트 기준 경로 ('/' 구분). daemon이 루트 밖·.kookabug/ 안을 거부한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspacePath".
 */
export type WorkspacePath = string;
/**
 * 그래프 파일 revision: 디스크 바이트의 sha256 hex
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Revision".
 */
export type Revision = string;
/**
 * 그래프 파일 값 전체 (JSON 트리). 편집 중이라 형식이 틀릴 수 있다. JS에서 보낼 때는 반드시 wireStringify로 직렬화한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphValue".
 */
export type GraphValue = {[key: string]: unknown};
/**
 * 요청 순번 (graph.validate·target.preview). 응답이 같은 값을 돌려주고, 클라이언트는 마지막으로 보낸 seq의 응답만 쓴다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestSeq".
 */
export type RequestSeq = number;
/**
 * 점으로 나눈 소문자 이름 (예: graph.open)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "MethodName".
 */
export type MethodName = string;
/**
 * 커밋 토큰 (commit_prepare가 주고 commit_finish·commit_abort가 받는다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCommitToken".
 */
export type RecorderCommitToken = string;
/**
 * target revision: sha256(JSON 바이트) + ':' + sha256(image가 가리키는 파일 바이트). 이미지가 없으면 'missing' (M2 계획 2.9)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetRevision".
 */
export type TargetRevision = string;
/**
 * 녹화 세션 ID: 소문자·숫자 8자
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderSessionId".
 */
export type RecorderSessionId = string;
/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * 녹화가 멈춘 까닭: user(정지 단추·단축키·커밋), hook_lost(훅 끊김), input_overflow(중요 입력 유실), window_gone(대상 창 닫힘), storage_full(세션 저장소 상한)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStopReason".
 */
export type RecorderStopReason =
  "hook_lost" | "input_overflow" | "storage_full" | "user" | "window_gone";
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderFrameWhich".
 */
export type RecorderFrameWhich = "live" | "pre_click" | "pre_hover" | "pre_next";
/**
 * 스텝을 사람이 확인해야 하는 이유 (커밋 전 남기거나 지움). geometry_unresolved 클릭과 프레임의 기하 세대가 확정적으로 같지 않음, no_frame 클릭 직전 프레임이 없음, window_undetermined 어느 창에 들어간 입력인지 판정 불가, ime_unknown 입력기 상태 판정 불가, cursor_moved_in_field 칸 안에서 커서를 옮김, field_box_unknown 칸 상자를 못 정함, no_evidence 비밀 근거도 일반 근거도 없음, cut_by_stop 정지·끊김 순간의 입력, secret_overlap 비밀번호 칸과 겹쳐 대상을 못 만듦, wait_target_unknown 기다릴 화면을 못 정함
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderNeedsReviewReason".
 */
export type RecorderNeedsReviewReason =
  | "cursor_moved_in_field"
  | "cut_by_stop"
  | "field_box_unknown"
  | "geometry_unresolved"
  | "ime_unknown"
  | "no_evidence"
  | "no_frame"
  | "secret_overlap"
  | "wait_target_unknown"
  | "window_undetermined";
/**
 * 비밀값 키 (그래프 $secret 키와 같은 규칙)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretKey".
 */
export type SecretKey = string;
/**
 * 입력 칸 구간의 글자 판정: pending(판정 중) → ordinary(일반 글자 — 긍정 근거 또는 사람 확인) | secret(비밀값, 끈적) | needs_review(근거 없음 — 사람이 고를 때까지 커밋 거부)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderTextState".
 */
export type RecorderTextState = "needs_review" | "ordinary" | "pending" | "secret";
/**
 * recorder.start: 떠 있는 창(window 핸들)에 붙어 녹화하거나, 워크스페이스 game.* 설정으로 게임을 띄워 녹화(launch, profile은 설정 계층). hotkeys는 주 프로세스가 등록에 성공한 단축키. 오류: input_lease_busy·recording_active·window_gone·capture_unsupported·hook_failed
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStartParams".
 */
export type RecorderStartParams = RecorderStartParams1 & RecorderStartParams2;
export type RecorderStartParams1 = {
  [k: string]: unknown | undefined;
};
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "StepId".
 */
export type StepId = string;
/**
 * run.compare 결과 (run-index.schema.json CompareResult)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunCompareResult".
 */
export type RunCompareResult = import("./run-index.js").CompareResult;
/**
 * run.index 결과: 실행 색인 (run-index.schema.json)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunIndexResult".
 */
export type RunIndexResult = import("./run-index.js").RunIndex;
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Verdict".
 */
export type Verdict = "error" | "fail" | "pass" | "skipped";
/**
 * crop = 편집 중 새로 고른 영역, image = 기존 target 이미지(target 기준 경로)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PreviewTemplate".
 */
export type PreviewTemplate =
  | {
      crop: CropRef;
    }
  | {
      image: WorkspacePath;
    };
/**
 * 저널 안 순번
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Seq".
 */
export type Seq = number;
/**
 * 권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon의 AGENT_DENIED 목록 — daemon.shutdown, M3 디버그 메서드 debug.breakpoints.get·set·run.pause·run.resume·run.restart, run.export, M4 녹화·비밀값 메서드 recorder.*·secrets.*·target.read_text — 를 판정 전에 거부)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ToolName".
 */
export type ToolName =
  | "kb_graph_create"
  | "kb_graph_get"
  | "kb_graph_patch"
  | "kb_graph_validate"
  | "kb_image_find"
  | "kb_node_search"
  | "kb_project_info"
  | "kb_run_cancel"
  | "kb_run_events"
  | "kb_run_start"
  | "kb_run_status"
  | "kb_screen_capture"
  | "kb_target_create"
  | "ui_only";

/**
 * UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표
 */
export interface DaemonRpcMessageDefs {}
/**
 * 에이전트 연결 → 그 에이전트 주체 (id 필수)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentClientInfo".
 */
export interface AgentClientInfo {
  /**
   * 사람이 지켜보는 연결인가 (생략하면 false)
   */
  attended?: boolean;
  /**
   * 에이전트 주체 ID
   */
  id: string;
  kind: "agent";
  name: string;
  version: string;
}
/**
 * debug.breakpoints.get·set 결과, debug.breakpoints.changed 알림 (다른 연결이 바꿨을 때)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "BreakpointsResult".
 */
export interface BreakpointsResult {
  breakpoints: import("./breakpoints.js").BreakpointList;
}
/**
 * 목록 전체를 바꾼다: .kookabug/breakpoints.json에 원자적으로 쓰고, 진행 중인 UI 실행에 밀어 넣는다(다음 경계부터)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "BreakpointsSetParams".
 */
export interface BreakpointsSetParams {
  breakpoints: import("./breakpoints.js").BreakpointList;
}
/**
 * UI 연결 → 판정하지 않는 사용자 주체
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "UiClientInfo".
 */
export interface UiClientInfo {
  kind: "ui";
  name: string;
  version: string;
}
/**
 * 정지 화면에서 자른 영역 (저장 전 템플릿)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "CropRef".
 */
export interface CropRef {
  frame_id: string;
  rect: Rect;
}
/**
 * JSON-RPC 표준 오류
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonStandardError".
 */
export interface DaemonStandardError {
  code: -32700 | -32600 | -32601 | -32602 | -32603;
  /**
   * 생략하거나 사람이 읽는 정보
   */
  data?: unknown;
  message: string;
}
/**
 * 앱 오류 -32100 request_failed. data(종류 data.code와 추가 필드)가 반드시 있다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonRequestFailedError".
 */
export interface DaemonRequestFailedError {
  code: -32100;
  data: RequestFailedData;
  message: string;
}
/**
 * error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found·run_not_debuggable·not_paused → run_id, read_only → path, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message. M4: input_lease_busy → owner(살아 있음이 확인된 소유자, 모르면 null), recording_active·not_owner·recorder_state_invalid → state, classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap → steps(걸린 스텝)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestFailedData".
 */
export interface RequestFailedData {
  code: RequestFailedCode;
  column?: number | null;
  /**
   * 권한 판정 결과 (permission_denied·approval_required). kookabug_core.permissions.Decision 그대로
   */
  decision?: {
    [k: string]: unknown | undefined;
  };
  diagnostics?: Diagnostic[];
  line?: number | null;
  message?: string;
  owner?: LeaseOwner | null;
  path?: string;
  protocol?: number;
  revision?: string | null;
  run_id?: RunId;
  state?: RecorderState;
  steps?: RecorderStepId[];
}
/**
 * 검증 진단 (kookabug_core.diagnostics.Diagnostic.to_dict)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
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
 * 입력 임대권 소유자 (옆 파일 input-lease.json의 owner, lease.changed 알림, input_lease_busy 오류). 예전 옆 파일(M0b: kind 둘·device 없음)도 맞는다. created는 FILETIME이라 옆 파일은 정수, 알림·오류는 10진 문자열. 녹화 소유자(recorder)는 실행이 없어 run_id·run_dir이 null(또는 없음)이고 장치는 none
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "LeaseOwner".
 */
export interface LeaseOwner {
  /**
   * 프로세스 생성 시각 (Windows FILETIME, 100ns 단위)
   */
  created: number | string;
  device?: LeaseDevice | null;
  kind: import("./events.js").LeaseOwnerKind;
  pid: number;
  run_dir?: null | string;
  run_id?: null | string;
  workspace?: null | string;
}
/**
 * 소유자가 입력을 보내는 장치. 다음 획득자가 앞 소유자의 키를 이 장치로 뗀다. none은 입력 장치가 없는 소유자(녹화) — 뗄 것이 없다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "LeaseDevice".
 */
export interface LeaseDevice {
  /**
   * fake 장치의 입력 기록 파일 (절대 경로)
   */
  input_log?: string;
  kind: "fake" | "none" | "windows";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonErrorResponse".
 */
export interface DaemonErrorResponse {
  error: DaemonErrorObject;
  /**
   * 요청을 읽지 못했으면(JSON 아님·id 없음) null
   */
  id: RequestId | null;
  jsonrpc: JsonRpcVersion;
}
/**
 * 진행 중인 실행이 있으면 run_active로 거부. force면 실행을 취소하고 마무리를 기다린 뒤 끝낸다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "DaemonShutdownParams".
 */
export interface DaemonShutdownParams {
  force?: boolean;
}
/**
 * 인자 없음
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "EmptyParams".
 */
export interface EmptyParams {}
/**
 * 결과 없음
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "EmptyResult".
 */
export interface EmptyResult {}
/**
 * 출구. outputs는 그 출구로 나갈 때 값이 있는 출력 이름
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExitShape".
 */
export interface ExitShape {
  kind: "fail" | "ok";
  name: string;
  outputs: string[];
}
/**
 * 편집기 정지 화면 (daemon 프레임 캐시, 최대 16장. 사라지면 frame_expired)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Frame".
 */
export interface Frame {
  client_size: Size;
  dpi: number;
  frame_id: string;
  height: number;
  image: ImageRef;
  width: number;
}
/**
 * 열린 문서의 디스크 revision이 바뀜 (파일이 없어졌으면 null)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphChangedParams".
 */
export interface GraphChangedParams {
  doc_id: DocId;
  revision: Revision | null;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphCloseParams".
 */
export interface GraphCloseParams {
  doc_id: DocId;
}
/**
 * 새 그래프 (canonical 틀). 파일이 있으면 exists. 결과는 graph.open과 같다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphCreateParams".
 */
export interface GraphCreateParams {
  kind: "subgraph" | "test";
  path: WorkspacePath;
  title?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphOpenParams".
 */
export interface GraphOpenParams {
  path: WorkspacePath;
}
/**
 * value는 Python이 읽은 값. 원문 텍스트는 보내지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphOpenResult".
 */
export interface GraphOpenResult {
  /**
   * 원문이 canonical 형식인가
   */
  canonical: boolean;
  diagnostics: Diagnostic[];
  doc_id: DocId;
  /**
   * 실행 폴더(runs/ 아래)의 스냅샷 그래프라 읽기만 한다. graph.save는 read_only로 거부 (M3, 없으면 false)
   */
  read_only?: boolean;
  revision: Revision;
  shapes: NodeShapes;
  value: GraphValue;
}
/**
 * 노드 ID → 모양
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodeShapes".
 */
export interface NodeShapes {
  [k: string]: NodeShape | undefined;
}
/**
 * 노드 하나의 핀·출구 (daemon이 계산, 에디터는 계산하지 않는다). unknown이면 레지스트리에 없는 타입·버전이거나 서브그래프를 읽지 못한 호출이라 JSON 키(in·next·다른 노드의 $link)로 만든 대체 모양이다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodeShape".
 */
export interface NodeShape {
  exits: ExitShape[];
  inputs: PinShape[];
  outputs: OutputShape[];
  unknown: boolean;
}
/**
 * 입력 핀. required = 기본값도 optional도 없음. 모르는 노드의 핀은 type 'any'
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PinShape".
 */
export interface PinShape {
  default?: unknown;
  description?: string;
  enum?: unknown[];
  maximum?: number;
  min_items?: number;
  minimum?: number;
  name: string;
  nullable: boolean;
  optional: boolean;
  required: boolean;
  type: string;
}
/**
 * 출력 핀
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "OutputShape".
 */
export interface OutputShape {
  name: string;
  nullable: boolean;
  type: string;
}
/**
 * 값 전체 저장 (M2 계획 2.6). 디스크가 base_revision과 다르면 revision_conflict(force면 덮어씀). 수 규칙(number_out_of_range·number_not_finite)에 걸리면 validation_failed
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphSaveParams".
 */
export interface GraphSaveParams {
  base_revision: Revision;
  doc_id: DocId;
  force?: boolean;
  value: GraphValue;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphSaveResult".
 */
export interface GraphSaveResult {
  /**
   * canonical이 아니던 원문을 처음 편집해 저장해서 파일 전체가 canonical이 됨
   */
  canonicalized: boolean;
  diagnostics: Diagnostic[];
  revision: Revision;
  /**
   * false면 지금 디스크 바이트와 같아 쓰지 않음 (mtime 그대로)
   */
  wrote: boolean;
}
/**
 * 편집 버퍼 값으로 검증 (루트만 버퍼, 서브그래프·target·화면은 디스크)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphValidateParams".
 */
export interface GraphValidateParams {
  doc_id: DocId;
  seq: RequestSeq;
  value: GraphValue;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphValidateResult".
 */
export interface GraphValidateResult {
  diagnostics: Diagnostic[];
  seq: RequestSeq;
  shapes: NodeShapes;
}
/**
 * 입력 임대권 소유자 (없으면 null). 녹화 세션이면 kind recorder (상태 바 '입력: 녹화')
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "LeaseChangedParams".
 */
export interface LeaseChangedParams {
  owner: LeaseOwner | null;
}
/**
 * 입력 임대권 옆 파일 (%LOCALAPPDATA%\Kookabug\input-lease.json, kookabug_core.inputs.lease). 쥔 동안 {owner, clean: false}, 깨끗하게 놓으면 {owner: null, clean: true, last_owner}
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "LeaseFile".
 */
export interface LeaseFile {
  clean: boolean;
  last_owner?: LeaseOwner;
  owner: LeaseOwner | null;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "MatchInfo".
 */
export interface MatchInfo {
  /**
   * @minItems 2
   * @maxItems 2
   */
  click: [number, number];
  method: string;
  rect: Rect;
  scale: number;
  score: number;
}
/**
 * 메서드 표 (단일 출처). 메시지가 아니라 타입 표다: params·result 모양, 권한 도구, 렌더러 표면에 내놓는지(false = Electron 주 프로세스 내부용)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Methods".
 */
export interface Methods {
  "daemon.shutdown": {
    params: DaemonShutdownParams;
    renderer: false;
    result: EmptyResult;
    tool: "ui_only";
  };
  "debug.breakpoints.get": {
    params: EmptyParams;
    renderer: true;
    result: BreakpointsResult;
    tool: "ui_only";
  };
  "debug.breakpoints.set": {
    params: BreakpointsSetParams;
    renderer: true;
    result: BreakpointsResult;
    tool: "ui_only";
  };
  "graph.close": {
    params: GraphCloseParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "graph.create": {
    params: GraphCreateParams;
    renderer: true;
    result: GraphOpenResult;
    tool: "kb_graph_create";
  };
  "graph.open": {
    params: GraphOpenParams;
    renderer: true;
    result: GraphOpenResult;
    tool: "kb_graph_get";
  };
  "graph.save": {
    params: GraphSaveParams;
    renderer: true;
    result: GraphSaveResult;
    tool: "kb_graph_patch";
  };
  "graph.validate": {
    params: GraphValidateParams;
    renderer: true;
    result: GraphValidateResult;
    tool: "kb_graph_validate";
  };
  "nodes.list": {
    params: EmptyParams;
    renderer: true;
    result: NodesListResult;
    tool: "kb_node_search";
  };
  "recorder.commit_abort": {
    params: RecorderCommitTokenParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "recorder.commit_finish": {
    params: RecorderCommitFinishParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "recorder.commit_prepare": {
    params: RecorderCommitPrepareParams;
    renderer: true;
    result: RecorderCommitPrepareResult;
    tool: "ui_only";
  };
  "recorder.discard": {
    params: EmptyParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.frame": {
    params: RecorderFrameParams;
    renderer: true;
    result: RecorderFrameResult;
    tool: "ui_only";
  };
  "recorder.insert_check": {
    params: RecorderInsertCheckParams;
    renderer: true;
    result: RecorderStepResult;
    tool: "ui_only";
  };
  "recorder.pause": {
    params: EmptyParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.resume": {
    params: EmptyParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.start": {
    params: RecorderStartParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.state": {
    params: EmptyParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.step.update": {
    params: RecorderStepUpdateParams;
    renderer: true;
    result: RecorderStepResult;
    tool: "ui_only";
  };
  "recorder.steps": {
    params: RecorderStepsParams;
    renderer: true;
    result: RecorderStepsResult;
    tool: "ui_only";
  };
  "recorder.stop": {
    params: EmptyParams;
    renderer: true;
    result: RecorderStateResult;
    tool: "ui_only";
  };
  "recorder.target.materialize": {
    params: RecorderMaterializeParams;
    renderer: true;
    result: RecorderWrittenTarget;
    tool: "ui_only";
  };
  "run.cancel": {
    params: RunIdParams;
    renderer: true;
    result: EmptyResult;
    tool: "kb_run_cancel";
  };
  "run.children": {
    params: RunChildrenParams;
    renderer: true;
    result: RunChildrenResult;
    tool: "kb_run_events";
  };
  "run.compare": {
    params: RunCompareParams;
    renderer: true;
    result: RunCompareResult;
    tool: "kb_run_events";
  };
  "run.export": {
    params: RunExportParams;
    renderer: false;
    result: RunExportResult;
    tool: "ui_only";
  };
  "run.file": {
    params: RunFileParams;
    renderer: true;
    result: RunFileResult;
    tool: "kb_run_events";
  };
  "run.index": {
    params: RunIdParams;
    renderer: true;
    result: RunIndexResult;
    tool: "kb_run_events";
  };
  "run.list": {
    params: RunListParams;
    renderer: true;
    result: RunListResult;
    tool: "kb_run_status";
  };
  "run.pause": {
    params: RunIdParams;
    renderer: true;
    result: RunControlResult;
    tool: "ui_only";
  };
  "run.restart": {
    params: RunIdParams;
    renderer: true;
    result: RunStartResult;
    tool: "ui_only";
  };
  "run.resume": {
    params: RunResumeIdParams;
    renderer: true;
    result: RunControlResult;
    tool: "ui_only";
  };
  "run.start": {
    params: RunStartParams;
    renderer: true;
    result: RunStartResult;
    tool: "kb_run_start";
  };
  "run.status": {
    params: RunIdParams;
    renderer: true;
    result: RunStatusResult;
    tool: "kb_run_status";
  };
  "run.step": {
    params: RunStepParams;
    renderer: true;
    result: RunStepResult;
    tool: "kb_run_events";
  };
  "run.subscribe": {
    params: RunSubscribeParams;
    renderer: true;
    result: EmptyResult;
    tool: "kb_run_events";
  };
  "run.unsubscribe": {
    params: RunIdParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "secrets.create": {
    params: SecretsCreateParams;
    renderer: true;
    result: SecretKeyInfo;
    tool: "ui_only";
  };
  "secrets.list": {
    params: EmptyParams;
    renderer: true;
    result: SecretsListResult;
    tool: "ui_only";
  };
  "session.hello": {
    params: SessionHelloParams;
    renderer: false;
    result: SessionHelloResult;
    tool: "ui_only";
  };
  "target.capture": {
    params: TargetCaptureParams;
    renderer: true;
    result: Frame;
    tool: "kb_screen_capture";
  };
  "target.load_image": {
    params: TargetLoadImageParams;
    renderer: true;
    result: Frame;
    tool: "kb_image_find";
  };
  "target.open": {
    params: TargetOpenParams;
    renderer: true;
    result: TargetOpenResult;
    tool: "kb_image_find";
  };
  "target.preview": {
    params: TargetPreviewParams;
    renderer: true;
    result: PreviewResult;
    tool: "kb_image_find";
  };
  "target.read_text": {
    params: TargetReadTextParams;
    renderer: true;
    result: TargetReadTextResult;
    tool: "ui_only";
  };
  "target.save": {
    params: TargetSaveParams;
    renderer: true;
    result: TargetSaveResult;
    tool: "kb_target_create";
  };
  "windows.list": {
    params: EmptyParams;
    renderer: true;
    result: WindowsListResult;
    tool: "kb_screen_capture";
  };
  "workspace.info": {
    params: EmptyParams;
    renderer: true;
    result: WorkspaceInfoResult;
    tool: "kb_project_info";
  };
  "workspace.read": {
    params: WorkspaceReadParams;
    renderer: true;
    result: WorkspaceReadResult;
    tool: "kb_project_info";
  };
  "workspace.tree": {
    params: EmptyParams;
    renderer: true;
    result: WorkspaceTreeResult;
    tool: "kb_project_info";
  };
}
/**
 * 팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodesListResult".
 */
export interface NodesListResult {
  /**
   * Items: 노드 스키마 문서 (node-schema 형식 kookabug.nodes/0 그대로)
   */
  schemas: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * recorder.commit_abort: 그래프 단계가 실패 → stopped로 돌아가 다른 이름·위치로 다시 commit_prepare (써진 target 재사용)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCommitTokenParams".
 */
export interface RecorderCommitTokenParams {
  token: RecorderCommitToken;
}
/**
 * recorder.commit_finish: 렌더러가 조각을 넣은 그래프를 저장했다 → 세션 committed, 정리
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCommitFinishParams".
 */
export interface RecorderCommitFinishParams {
  graph_path: WorkspacePath;
  token: RecorderCommitToken;
}
/**
 * recorder.commit_prepare: 녹화를 멈추고(아직이면) 검사(classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap) → target 파일 쓰기(멱등: 이미 쓴 초안은 다시 쓰지 않음) → 조각. graph_path는 새 테스트면 만들 파일, 삽입이면 열린 그래프 파일 (target 폴더 이름 targets/rec/<줄기>/). options는 이 커밋에 적용할 변환 옵션(녹화 뒤 사이드바에서 바꾼 값). 빼면 세션 옵션(recorder.start의 options, recorder.state가 보임). 옵션이 다르면 다른 조각이다(같은 옵션으로 다시 부를 때만 같은 조각)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCommitPrepareParams".
 */
export interface RecorderCommitPrepareParams {
  base_revision?: Revision | null;
  graph_path: WorkspacePath;
  mode: "insert" | "new_test";
  options?: RecorderOptions;
}
/**
 * 변환 옵션 (시안 체크). 커밋 때 적용하므로 녹화 뒤에 바꿔도 된다. 없는 값은 켬. 'Kookabug가 보낸 입력은 녹화하지 않기'는 항상 켬이라 옵션이 아니다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderOptions".
 */
export interface RecorderOptions {
  /**
   * 클릭 직전 화면에서 클릭 지점 주변을 잘라 찾기 대상 만들기 (끄면 core.input.click 픽셀 좌표)
   */
  crop_targets?: boolean;
  /**
   * 기다린 시간을 '나타날 때까지 대기'로 바꾸기 (끄면 core.flow.delay)
   */
  wait_as_appear?: boolean;
}
/**
 * 조각과 토큰 (세션 committing). 같은 요청을 다시 부르면 같은 조각(같은 로컬 ID·경로)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCommitPrepareResult".
 */
export interface RecorderCommitPrepareResult {
  fragment: import("./recorder-fragment.js").RecorderFragment;
  targets: RecorderWrittenTarget[];
  token: RecorderCommitToken;
}
/**
 * 커밋이 쓴(또는 재사용한) target 파일
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderWrittenTarget".
 */
export interface RecorderWrittenTarget {
  path: WorkspacePath;
  reused: boolean;
  revision: TargetRevision;
}
/**
 * 녹화 상태. owned = 부른 연결이 세션을 연 연결인가. 다른 연결(owned false)에는 상태·시작 시각·경과만 준다 (스텝·창 제목 없음 — '다른 창에서 녹화 중'). options = 세션 변환 옵션(recorder.start에서 받은 값, 없는 값은 켬) — 커밋 때 바꾸려면 commit_prepare의 options
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStateResult".
 */
export interface RecorderStateResult {
  counts?: RecorderCounts;
  elapsed_ms?: number;
  /**
   * 대상 창이 앞에 있는가 (false면 '게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중')
   */
  foreground?: boolean;
  /**
   * 게임을 띄워서 녹화 (그래프가 core.app.launch로 시작)
   */
  launched?: boolean;
  options?: RecorderOptions;
  owned: boolean;
  session?: RecorderSessionId;
  started_at?: Timestamp;
  state: RecorderState;
  stop_reason?: RecorderStopReason;
  warnings?: RecorderWarning[];
  window?: RecorderWindow;
}
/**
 * 스텝·만든 target 수와 녹화하지 않은 입력 수 (다른 프로그램이 보낸 입력, 게임 창 밖, 게임의 팝업 창)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderCounts".
 */
export interface RecorderCounts {
  ignored_injected: number;
  ignored_outside: number;
  ignored_popup: number;
  steps: number;
  targets: number;
}
/**
 * 녹화 알림 (예: injected_ignored '다른 프로그램이 보낸 입력 N개는 녹화하지 않았어요', popup_ignored, not_foreground, no_assertion)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderWarning".
 */
export interface RecorderWarning {
  code: string;
  count?: number;
  message?: string;
}
/**
 * 녹화 대상 창 (시작 때의 값)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderWindow".
 */
export interface RecorderWindow {
  client_size: Size;
  dpi: number;
  handle: number;
  process: string;
  title: string;
}
/**
 * recorder.frame: 그 스텝이 붙잡은 프레임(pre_click 클릭 직전·pre_hover 커서 들어오기 전·pre_next 다음 동작 직전) 또는 live(링의 지금 프레임, step 없음, stopped에서는 no_frame)를 편집기 프레임 캐시에 올린다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderFrameParams".
 */
export interface RecorderFrameParams {
  step?: RecorderStepId;
  which: RecorderFrameWhich;
}
/**
 * 정지 화면과 그 프레임에서 유효한 보호 영역(비밀값·판정 대기·확인 필요 입력 칸 상자, 클라이언트 물리 픽셀 — 편집기가 빗금으로 보이고 그 영역과 겹치는 저장은 secret_region_overlap)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderFrameResult".
 */
export interface RecorderFrameResult {
  frame: Frame;
  protected: Rect[];
  which: RecorderFrameWhich;
}
/**
 * recorder.insert_check: 녹화 중 '화면 확인 삽입'(visible → core.assert.visible) · '값 확인 삽입'(text → core.assert.text, 영역 OCR 글자를 기댓값으로 제안). rect는 그 frame_id 정지 화면의 클라이언트 물리 픽셀 영역 (보호 영역과 겹치면 secret_region_overlap)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderInsertCheckParams".
 */
export interface RecorderInsertCheckParams {
  frame_id: string;
  kind: "text" | "visible";
  rect: Rect;
}
/**
 * 바뀐(또는 새) 스텝과 스텝 목록 판. 지운 스텝이면 step은 null
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepResult".
 */
export interface RecorderStepResult {
  rev: number;
  step: RecorderStep | null;
}
/**
 * 녹화된 스텝 하나 = 재생 동작 하나 (노드는 하나 이상). 글자 규칙(M4 계획 2.8): text는 text_state가 ordinary일 때만(근거로 일반 글자로 판정됐거나 사람이 확인 — 그때 reveal_confirmed) 있다. pending·secret·needs_review는 text_len만. secret_key는 secret에만. node.title·badges에는 비밀값·판정 대기·확인 필요 원문을 넣지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStep".
 */
export interface RecorderStep {
  badges: RecorderBadge[];
  /**
   * 값 확인(check_text) 스텝의 기댓값 (영역 OCR 제안 또는 사람이 고친 값). 비밀값 원문과 겹치면 daemon이 비운다
   */
  equals?: string;
  /**
   * recorder.frame으로 열 수 있는 이 스텝의 프레임
   */
  frames?: RecorderFrameWhich[];
  input?: RecorderStepInput;
  kind:
    | "check_text"
    | "check_visible"
    | "click"
    | "delay"
    | "drag"
    | "key"
    | "scroll"
    | "text"
    | "wait";
  needs_review: RecorderNeedsReviewReason[];
  /**
   * 노드 초안 요약 (시안 '이미지 클릭 "강화"')
   */
  node: {
    title: string;
    type: string;
  };
  /**
   * 사람이 '글자를 보이고 일반 글자로'를 확인했다
   */
  reveal_confirmed?: true;
  /**
   * 고른 비밀값 키 (아직 안 골랐으면 null → 커밋 secret_unresolved)
   */
  secret_key?: SecretKey | null;
  step: RecorderStepId;
  /**
   * 녹화 시작부터 그 입력까지 (일시정지 시간 포함)
   */
  t_ms: number;
  target?: RecorderTargetDraft;
  text?: string;
  /**
   * 글자 수 (UI는 비밀값이면 이 길이만큼 ●)
   */
  text_len?: number;
  text_state?: RecorderTextState;
}
/**
 * 스텝 메모 (시안 '녹화된 스텝'의 메모 줄). severity review는 확인 필요(노랑·주황). 글자 원문을 담지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderBadge".
 */
export interface RecorderBadge {
  code: string;
  message?: string;
  severity: "info" | "review" | "warning";
}
/**
 * 원래 입력 요약 (시안 'click (858, 562) · 00:09.4'). 좌표는 클라이언트 물리 픽셀. 글자는 싣지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepInput".
 */
export interface RecorderStepInput {
  amount?: number;
  button?: "left" | "middle" | "right" | "x1" | "x2";
  count?: number;
  duration_ms?: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  end?: [number, number];
  /**
   * 앞 동작부터 이 입력까지 (대기·지연 스텝)
   */
  gap_ms?: number;
  hold_ms?: number;
  keys?: string;
  /**
   * @minItems 2
   * @maxItems 2
   */
  point?: [number, number];
}
/**
 * 스텝의 찾기 대상: draft(이 세션 초안, 커밋 때 파일로) · file(기존 또는 이미 쓴 target 파일 재사용) · none(아직 없음 — 커밋 target_missing). draft는 spec(daemon이 든 초안 사양 전체 — REC 편집기가 이것으로 상태를 만들고, 고친 값은 recorder.step.update patch.target으로 같은 모양을 보낸다)이 있다. frame은 자른 프레임: 스텝이 붙잡은 프레임 종류, 또는 live(편집기에서 고른 지금 프레임 — 그때 고정된 frame_id가 함께 온다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderTargetDraft".
 */
export interface RecorderTargetDraft {
  frame?: "live" | "pre_click" | "pre_hover" | "pre_next";
  /**
   * 자른 프레임의 편집기 캐시 ID (recorder.frame·patch.frame_id로 고른 프레임)
   */
  frame_id?: string;
  path?: WorkspacePath;
  /**
   * 같은 프레임에서 임계값 이상인 자리 수 (자기 자리 포함, '같은 모양 N곳')
   */
  peaks?: number;
  reused?: boolean;
  source: "draft" | "file" | "none";
  spec?: RecorderTargetSpec;
}
/**
 * target 초안 사양 (읽기 RecorderTargetDraft.spec = 전체, 쓰기 RecorderStepPatch.target = 바꿀 필드만 — 같은 모양). rect·search는 자른 프레임의 클라이언트 물리 픽셀(search null = 검색 범위 없음). 나머지는 target 파일 필드와 같다: click.anchor·click.offset, match.threshold·rgb(색까지 확인)·methods·color_tolerance, sensitive
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderTargetSpec".
 */
export interface RecorderTargetSpec {
  anchor?:
    | "bottom"
    | "bottom_left"
    | "bottom_right"
    | "center"
    | "left"
    | "right"
    | "top"
    | "top_left"
    | "top_right";
  color_tolerance?: number;
  /**
   * @minItems 1
   * @maxItems 2
   */
  methods?:
    | ["template" | "template_multiscale"]
    | ["template" | "template_multiscale", "template" | "template_multiscale"];
  /**
   * @minItems 2
   * @maxItems 2
   */
  offset?: [number, number];
  rect?: Rect;
  rgb?: boolean;
  search?: Rect | null;
  sensitive?: boolean;
  threshold?: number;
}
export interface RecorderStartParams2 {
  hotkeys: RecorderHotkey[];
  launch?: {
    profile?: null | string;
  };
  options?: RecorderOptions;
  /**
   * 창 handle
   */
  window?: number;
}
/**
 * Electron 주 프로세스가 녹화 중에만 등록한 단축키. 변환기가 이 조합의 키 이벤트와 그 조합 때문에만 눌린 수정 키를 지운다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderHotkey".
 */
export interface RecorderHotkey {
  /**
   * 키 이름 조합 (입력 노드 keys와 같은 이름, 예: ctrl+shift+r)
   */
  keys: string;
  role: "mark_secret" | "stop";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepUpdateParams".
 */
export interface RecorderStepUpdateParams {
  patch: RecorderStepPatch;
  step: RecorderStepId;
}
/**
 * 스텝 고치기 (비어 있으면 아무것도 바꾸지 않음). text_state를 ordinary로 바꾸려면 confirm_reveal이 있어야 한다 (원문을 처음 보이는 순간). text(일반 글자 고치기)는 ordinary 스텝만, target은 REC 탭의 초안 사양 고치기(RecorderTargetDraft.spec과 같은 모양 — 준 필드만 바꾼다, 보호 영역과 겹치면 secret_region_overlap), keep은 확인 필요 입력을 그대로 남기기. 자를 프레임은 둘 중 하나로 고른다: frame(이 스텝이 붙잡은 프레임 종류) 또는 frame_id(이 세션이 recorder.frame으로 편집기 캐시에 올린 프레임 — live도 조회한 그 순간의 프레임이 고정된다. 다른 세션·다른 연결이 올린 프레임이면 not_owner, 캐시에서 사라졌으면 frame_expired, 그 프레임의 보호 영역 검사를 거친다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepPatch".
 */
export interface RecorderStepPatch {
  confirm_reveal?: true;
  delete?: true;
  /**
   * 값 확인(check_text) 스텝의 기댓값 고치기 (사람 수정·글자 읽기 결과). 세션의 비밀값·판정 대기·확인 필요 원문을 담으면 secret_region_overlap
   */
  equals?: string;
  frame?: "pre_click" | "pre_hover" | "pre_next";
  frame_id?: string;
  keep?: true;
  /**
   * 노드 종류 바꾸기 (이미지 클릭 ↔ 좌표 클릭, 대기 종류)
   */
  node_type?: string;
  secret_key?: SecretKey | null;
  target?: RecorderTargetSpec;
  text?: string;
  text_state?: "ordinary" | "secret";
  timeout_ms?: number;
}
/**
 * recorder.steps: 스텝 목록. after_rev는 마지막으로 받은 판 (같으면 steps가 그대로)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepsParams".
 */
export interface RecorderStepsParams {
  after_rev?: number;
}
/**
 * 스텝 목록 (녹화 차례). 원문 글자를 주는 유일한 곳 — ordinary 스텝의 text만
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderStepsResult".
 */
export interface RecorderStepsResult {
  rev: number;
  steps: RecorderStep[];
}
/**
 * recorder.target.materialize: REC 탭 '찾기 대상 탭으로 열기' — 그 스텝의 녹화 초안만 지금 target 파일로 쓴다(최신 보호 영역 재검사 뒤, targets/rec/<세션 ID>/). 그 스텝은 이후 그 파일을 가리키고 커밋은 다시 쓰지 않는다. 초안이 없는 스텝이면 target_missing
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderMaterializeParams".
 */
export interface RecorderMaterializeParams {
  step: RecorderStepId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunIdParams".
 */
export interface RunIdParams {
  run_id: RunId;
}
/**
 * 그 스텝 바로 아래 스텝을 쪽으로 읽는다. 반복 스텝이면 iteration으로 회차를 고른다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunChildrenParams".
 */
export interface RunChildrenParams {
  iteration?: number;
  limit: number;
  offset: number;
  parent: StepId;
  run_id: RunId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunChildrenResult".
 */
export interface RunChildrenResult {
  offset: number;
  steps: import("./run-index.js").StepNode[];
  /**
   * 그 부모(·회차) 아래 스텝 수
   */
  total: number;
}
/**
 * baseline을 빼면 기준 실행을 고른다 (같은 테스트·같은 프로필·pass·디버거 개입 아님 중 이 실행보다 먼저 시작한 가장 최근). step은 화면을 비교할 스텝 (빼면 실패 스텝)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunCompareParams".
 */
export interface RunCompareParams {
  baseline?: RunId;
  run_id: RunId;
  step?: StepId;
}
/**
 * 실행 폴더를 zip으로 내보낸다 (Electron 주 프로세스 내부용: dest는 저장 대화 상자가 고른 절대 경로). dest 옆 임시 파일에 쓰고 끝나면 replace. 진행 중 실행은 run_active
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunExportParams".
 */
export interface RunExportParams {
  dest: string;
  run_id: RunId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunExportResult".
 */
export interface RunExportResult {
  bytes: number;
  path: string;
}
/**
 * run.json 원문, 또는 events.jsonl 끝부분 (1 MiB까지)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunFileParams".
 */
export interface RunFileParams {
  name: "events_tail" | "run.json";
  run_id: RunId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunFileResult".
 */
export interface RunFileResult {
  /**
   * 파일 전체 크기
   */
  bytes: number;
  text: string;
  /**
   * 1 MiB를 넘어 앞(events_tail은 뒤만 남김)을 잘랐다
   */
  truncated: boolean;
}
/**
 * 최신순. before는 앞 쪽 결과의 next (그보다 먼저 시작한 실행부터). graph(이 테스트 그래프의 실행만)·verdict(이 판정의 끝난 실행만)는 거르기 (M3)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunListParams".
 */
export interface RunListParams {
  /**
   * 쪽 커서 (앞 결과의 next 그대로, 뜻은 daemon만 안다)
   */
  before?: string;
  graph?: WorkspacePath;
  limit?: number;
  verdict?: Verdict;
}
/**
 * 최근 실행부터. next가 null이면 마지막 쪽
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunListResult".
 */
export interface RunListResult {
  next?: null | string;
  runs: RunSummary[];
  /**
   * runs/ 폴더 합계 크기 (캐시, 1분마다 다시 잼). 모르면 없음
   */
  runs_bytes?: number;
}
/**
 * 실행 요약 (record.reader.read_run). outcome은 끝난 실행만. code부터 아래 필드는 M3 run.list가 채운다(run.json에서 읽고, 없으면 뺀다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSummary".
 */
export interface RunSummary {
  code?: string;
  /**
   * 배지 "디버거 개입"
   */
  debug_intervened?: boolean;
  duration_ms?: number;
  /**
   * 실패 위치 호출 경로 (노드 ID)
   */
  failure_path?: [string, ...string[]] | null;
  /**
   * 실패 위치를 노드 제목으로 이은 것 (예: 월드 접속 > 타이틀 대기)
   */
  failure_title?: string;
  /**
   * 배지 "불안정": 재시도 끝에 성공한 스텝이 있는 pass (run.json retried_steps)
   */
  flaky?: boolean;
  game_build?: null | string;
  graph: WorkspacePath;
  last_seq: number;
  outcome: RunOutcome | null;
  profile?: null | string;
  reason?: string;
  run_dir: string;
  run_id: RunId;
  started_at: Timestamp | null;
  state: "ended" | "running";
}
/**
 * 실행 결과 (run.end 판정·CLI 종료 코드 규칙의 값·마무리한 쪽)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunOutcome".
 */
export interface RunOutcome {
  exit_code: number;
  finalized_by: "runner" | "supervisor";
  verdict: "error" | "fail" | "pass" | "skipped";
}
/**
 * run.pause·run.resume 결과: runner가 답한 상태 (running·pausing·paused·cancelling)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunControlResult".
 */
export interface RunControlResult {
  state: "cancelling" | "paused" | "pausing" | "running";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStartResult".
 */
export interface RunStartResult {
  graph: WorkspacePath;
  run_dir: string;
  run_id: RunId;
}
/**
 * run.resume params. mode를 빼면 continue. 멈추지 않은 실행에 Step(step_*)이면 not_paused
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunResumeIdParams".
 */
export interface RunResumeIdParams {
  mode?: import("./events.js").ResumeMode;
  run_id: RunId;
}
/**
 * 디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy. 이 daemon의 녹화 세션이 starting·recording·paused면 runner를 띄우기 전에 recording_active (M4, 같은 시작 잠금 안에서 판정)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStartParams".
 */
export interface RunStartParams {
  deadline_ms?: number;
  idempotency_key?: string;
  path: WorkspacePath;
  profile?: string | null;
  /**
   * $setting 키 → 값 (CLI --set)
   */
  settings?: {
    [k: string]: unknown | undefined;
  };
}
/**
 * 실행 요약 + 실행 스냅샷의 호출 관계 (화면이 실행 중 강조를 실행한 그래프 파일에 붙인다. 편집 버퍼가 아니라 스냅샷 기준)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStatusResult".
 */
export interface RunStatusResult {
  /**
   * 스냅샷 그래프 파일(워크스페이스 기준) → 그 그래프의 호출 노드. 스냅샷을 아직 만들지 않았으면 빈 객체
   */
  calls: {
    /**
     * 호출 노드 ID → 부르는 서브그래프 (config.graph)
     */
    [k: string]:
      | {
          [k: string]: WorkspacePath | undefined;
        }
      | undefined;
  };
  graph: WorkspacePath;
  last_seq: number;
  outcome: RunOutcome | null;
  run_dir: string;
  run_id: RunId;
  started_at: Timestamp | null;
  state: "ended" | "running";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStepParams".
 */
export interface RunStepParams {
  run_id: RunId;
  step: StepId;
}
/**
 * 스텝 하나의 자세한 기록. 파일 경로는 실행 폴더 기준 ('/' 구분, kbimg://ws/<run_dir>/<경로>로 연다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStepResult".
 */
export interface RunStepResult {
  /**
   * 그 스텝의 step.start·attempt.end·step.end·log 이벤트 (seq 순)
   */
  events: import("./events.js").Event[];
  /**
   * steps/<스텝>_ocr.txt 내용 (없으면 null)
   */
  ocr_text: null | string;
  /**
   * 실행 폴더 (워크스페이스 기준)
   */
  run_dir: string;
  step: import("./run-index.js").StepNode;
  /**
   * 썸네일 파일 (thumbs/<스텝>.jpg, 없으면 null)
   */
  thumbnail: null | string;
}
/**
 * after_seq = 클라이언트가 실제로 적용한 마지막 seq (처음이면 0). 순서·커서 규칙은 M2 계획 2.8
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSubscribeParams".
 */
export interface RunSubscribeParams {
  after_seq: number;
  run_id: RunId;
}
/**
 * secrets.create: 녹화 스텝(from_step, 비밀값·확인 필요 글자 구간)의 메모리 원문을 자격 증명 관리자에 그 키로 쓴다. 값을 RPC로 받지 않는다. 키가 이미 있으면 exists
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretsCreateParams".
 */
export interface SecretsCreateParams {
  from_step: RecorderStepId;
  key: SecretKey;
}
/**
 * 비밀값 키 하나 (값 없음). source credential = 자격 증명 관리자 kookabug:<워크스페이스 ID>:<키>
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretKeyInfo".
 */
export interface SecretKeyInfo {
  key: SecretKey;
  source: "credential";
}
/**
 * secrets.list: 자격 증명 관리자의 이 워크스페이스 키 (값 없음). 환경 변수(KOOKABUG_SECRET_<키>)는 원래 키 이름을 되살릴 수 없어 목록에 없고 env_note로 안내한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretsListResult".
 */
export interface SecretsListResult {
  env_note: string;
  keys: SecretKeyInfo[];
}
/**
 * 연결의 첫 메시지 (5초 안). 토큰은 session.json의 token
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SessionHelloParams".
 */
export interface SessionHelloParams {
  client: ClientInfo;
  protocol: number;
  token: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SessionHelloResult".
 */
export interface SessionHelloResult {
  daemon_version: string;
  principal: Principal;
  protocol: number;
  start_id: string;
  workspace: string;
}
/**
 * 연결의 주체 (kookabug_core.permissions.Principal)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Principal".
 */
export interface Principal {
  attended: boolean;
  id: string;
  kind: "agent" | "user";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetCaptureParams".
 */
export interface TargetCaptureParams {
  /**
   * 창 handle
   */
  window: number;
}
/**
 * 워크스페이스·실행 폴더 PNG
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetLoadImageParams".
 */
export interface TargetLoadImageParams {
  path: WorkspacePath;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetOpenParams".
 */
export interface TargetOpenParams {
  path: WorkspacePath;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetOpenResult".
 */
export interface TargetOpenResult {
  diagnostics: Diagnostic[];
  image: ImageRef | null;
  revision: TargetRevision;
  /**
   * target 파일 값 (target 형식)
   */
  spec: {
    [k: string]: unknown | undefined;
  };
}
/**
 * 저장 전 사양으로 그 프레임에서 찾는다. base_path는 image 경로를 풀 target 파일 경로
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetPreviewParams".
 */
export interface TargetPreviewParams {
  base_path?: WorkspacePath;
  frame_id: string;
  /**
   * 다른 배율 점수 (M4 T11): 정지 화면을 이 배율로 바꿔 같은 사양으로 찾는다. 결과 scale_scores (편집기 접힌 줄 '다른 배율에서'를 펼쳤을 때만 보낸다)
   *
   * @maxItems 6
   */
  scales?:
    | []
    | [number]
    | [number, number]
    | [number, number, number]
    | [number, number, number, number]
    | [number, number, number, number, number]
    | [number, number, number, number, number, number];
  seq: RequestSeq;
  /**
   * 저장 전 target 사양
   */
  spec: {
    [k: string]: unknown | undefined;
  };
  template: PreviewTemplate;
}
/**
 * kookabug target test --json의 결과 필드(target_cmd.result_json) + 검색 범위 픽셀 + seq. 화면에는 찾음/못 찾음과 (최고) 점수만 쓴다 (candidates는 화면 안 대상 개수가 아니다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PreviewResult".
 */
export interface PreviewResult {
  best: {
    [k: string]: unknown | undefined;
  } | null;
  candidates: {
    [k: string]: unknown | undefined;
  }[];
  elapsed_ms: number;
  expected_scale: number;
  found: boolean;
  match: MatchInfo | null;
  /**
   * 임계값 이상이고 서로 겹치지 않는 자리 (점수 높은 차례, 최대 8 — '같은 모양 N곳', M4). 없으면 아직 세지 않음
   *
   * @maxItems 8
   */
  peaks?:
    | []
    | [PreviewPeak]
    | [PreviewPeak, PreviewPeak]
    | [PreviewPeak, PreviewPeak, PreviewPeak]
    | [PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak]
    | [PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak]
    | [PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak]
    | [PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak, PreviewPeak]
    | [
        PreviewPeak,
        PreviewPeak,
        PreviewPeak,
        PreviewPeak,
        PreviewPeak,
        PreviewPeak,
        PreviewPeak,
        PreviewPeak
      ];
  /**
   * params.scales 차례대로 그 배율로 바꾼 정지 화면에서 찾은 결과 (scales를 보냈을 때만)
   *
   * @maxItems 6
   */
  scale_scores?:
    | []
    | [PreviewScaleScore]
    | [PreviewScaleScore, PreviewScaleScore]
    | [PreviewScaleScore, PreviewScaleScore, PreviewScaleScore]
    | [PreviewScaleScore, PreviewScaleScore, PreviewScaleScore, PreviewScaleScore]
    | [
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore
      ]
    | [
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore,
        PreviewScaleScore
      ];
  search: number[];
  search_rect_px: Rect;
  seq: RequestSeq;
  threshold: number;
}
/**
 * 같은 사양으로 찾은 자리 하나 (target.preview peaks)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PreviewPeak".
 */
export interface PreviewPeak {
  rect: Rect;
  scale: number;
  score: number;
}
/**
 * 다른 배율 점수 한 줄: factor = 정지 화면을 바꾼 배율, found = 그 화면에서 찾음, score = 받아들인(없으면 최고) 점수 (시도한 것이 없으면 null), scale = 그 후보의 배율
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PreviewScaleScore".
 */
export interface PreviewScaleScore {
  factor: number;
  found: boolean;
  scale: number | null;
  score: number | null;
}
/**
 * target.read_text: 편집기 정지 화면 영역의 글자 (OCR). 녹화 프레임의 보호 영역과 겹치면 secret_region_overlap
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetReadTextParams".
 */
export interface TargetReadTextParams {
  frame_id: string;
  rect: Rect;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetReadTextResult".
 */
export interface TargetReadTextResult {
  lines: {
    rect: Rect;
    score: number;
    text: string;
  }[];
  text: string;
}
/**
 * 새 파일이면 base_revision null(파일이 있으면 exists), 기존 파일이면 target.open의 revision (M2 계획 2.9 저장 단계). crop이 없으면 이미지를 새로 만들지 않고 지금 image·recorded를 그대로 둔 채 JSON만 저장한다(기존 파일만, 검색 범위는 recorded.client_size 기준)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetSaveParams".
 */
export interface TargetSaveParams {
  base_revision: TargetRevision | null;
  crop?: CropRef;
  path: WorkspacePath;
  spec: {
    [k: string]: unknown | undefined;
  };
}
/**
 * preview = 저장한 파일을 다시 읽어 crop의 정지 화면에서 찾은 결과 (바로 매칭). crop 없이 저장했으면 찾을 정지 화면이 없어 null
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetSaveResult".
 */
export interface TargetSaveResult {
  image: WorkspacePath;
  preview: PreviewResult | null;
  revision: TargetRevision;
  warnings: string[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WindowsListResult".
 */
export interface WindowsListResult {
  windows: WindowInfo[];
}
/**
 * 보이는 최상위 창 하나
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WindowInfo".
 */
export interface WindowInfo {
  client_size: Size;
  dpi: number;
  handle: number;
  pid: number;
  process: string;
  title: string;
}
/**
 * 루트(절대 경로), kookabug.json 요약(프로필 이름·진단), 플러그인, 상태 바용 실행 환경
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspaceInfoResult".
 */
export interface WorkspaceInfoResult {
  /**
   * run.start에 deadline_ms를 주지 않았을 때의 실행 전체 기한 (kookabug.json run.deadline_ms, 없으면 30분). 실행 툴바의 기한 고르기가 "기본"에 보인다
   */
  deadline_ms?: number;
  diagnostics: Diagnostic[];
  plugins: PluginSummary[];
  profiles: string[];
  /**
   * 실행 기록 보관 정책 (kookabug.json retention, 없는 값은 기본값: 통과 14일·실패 60일·최근 50개). 기록 뷰어 상태 바 문구용 (M3 T11). 정리는 보류 H1
   */
  retention?: {
    failed_days: number;
    keep_last: number;
    passed_days: number;
  };
  root: string;
  runtime: {
    capture: string | null;
    ocr: string | null;
    platform: string;
    python: string;
  };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginSummary".
 */
export interface PluginSummary {
  id: string;
  title?: string;
  version: string;
}
/**
 * 탐색기에 보이는 파일 하나의 내용 (보기 탭, 읽기 전용). 범위는 workspace.tree와 같다: tests·subgraphs·targets·screens 아래와 루트의 kookabug.json·kookabug.lock·AGENTS.md
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspaceReadParams".
 */
export interface WorkspaceReadParams {
  path: WorkspacePath;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspaceReadResult".
 */
export interface WorkspaceReadResult {
  /**
   * 글자 파일이 아니다 (앞부분에 NUL 바이트가 있다). text는 빈 문자열
   */
  binary: boolean;
  /**
   * 파일 전체 크기
   */
  bytes: number;
  /**
   * UTF-8로 읽은 앞부분 (1 MiB까지, 깨진 바이트는 U+FFFD)
   */
  text: string;
  /**
   * 1 MiB를 넘어 뒤를 잘랐다
   */
  truncated: boolean;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspaceTreeResult".
 */
export interface WorkspaceTreeResult {
  entries: TreeEntry[];
}
/**
 * 탐색기 항목. 그래프는 graph_kind, 읽을 수 없으면 problem
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TreeEntry".
 */
export interface TreeEntry {
  git_ignored?: boolean;
  graph_kind?: "subgraph" | "test";
  kind?: "agents" | "graph" | "lock" | "other" | "screen" | "target" | "workspace";
  /**
   * runs/·.kookabug/처럼 이름만 보이고 안을 나열하지 않는 폴더
   */
  name_only?: boolean;
  path: WorkspacePath;
  problem?: string;
  type: "dir" | "file";
}
/**
 * 응답이 없는 알림 (daemon → 클라이언트). 이름별 모양은 Notifications 표
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Notification".
 */
export interface Notification {
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
/**
 * 이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다). 메서드별 모양은 Methods 표의 params
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Params".
 */
export interface Params {
  [k: string]: unknown | undefined;
}
/**
 * 알림 표 (daemon → 클라이언트). 타입 표다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Notifications".
 */
export interface Notifications {
  "debug.breakpoints.changed": {
    params: BreakpointsResult;
  };
  "graph.changed": {
    params: GraphChangedParams;
  };
  "lease.changed": {
    params: LeaseChangedParams;
  };
  "recorder.changed": {
    params: RecorderChangedParams;
  };
  "run.ended": {
    params: RunEndedParams;
  };
  "run.event": {
    params: RunEventParams;
  };
  "run.lagged": {
    params: RunLaggedParams;
  };
  "workspace.changed": {
    params: WorkspaceChangedParams;
  };
}
/**
 * recorder.changed: 녹화 상태·스텝이 바뀜. 소유 연결에는 rev·counts·warnings도 (스텝 목록은 rev로 recorder.steps를 다시 부른다), 다른 연결에는 state만. 글자는 싣지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderChangedParams".
 */
export interface RecorderChangedParams {
  counts?: RecorderCounts;
  rev?: number;
  state: RecorderState;
  warnings?: RecorderWarning[];
}
/**
 * 감독자 마무리와 파일 끝까지 보낸 뒤
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunEndedParams".
 */
export interface RunEndedParams {
  last_seq: number;
  outcome: RunOutcome;
  run_id: RunId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunEventParams".
 */
export interface RunEventParams {
  /**
   * events.jsonl 한 줄 (events.schema.json 형식 그대로)
   */
  event: import("./events.js").Event;
  run_id: RunId;
  seq: Seq;
}
/**
 * 송신 큐가 차서 구독을 끊음 → 다시 구독
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunLaggedParams".
 */
export interface RunLaggedParams {
  run_id: RunId;
}
/**
 * 1초 폴링으로 바뀐 파일 (mtime·크기)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspaceChangedParams".
 */
export interface WorkspaceChangedParams {
  paths: WorkspacePath[];
}
/**
 * 응답을 기다리는 요청 (클라이언트 → daemon)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Request".
 */
export interface Request {
  id: RequestId;
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
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
 * UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표
 */
export type DaemonRpcMessage = Request | Notification | SuccessResponse | DaemonErrorResponse;
