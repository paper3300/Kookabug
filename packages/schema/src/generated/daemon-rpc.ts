/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * MCP 툴셋 (구현 계획 7장). core는 늘 켜져 있다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Toolset".
 */
export type Toolset =
  "cases" | "control" | "core" | "graph_edit" | "knowledge" | "observe" | "run" | "screens";
/**
 * 그래프 파일 revision: 디스크 바이트의 sha256 hex
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Revision".
 */
export type Revision = string;
/**
 * 사람 확인 답 (M5 3.6). allow_always는 프로젝트 계층(.kookabug/local.json)에 그 도구·인자에만 맞는 allow 규칙을 더한 뒤 실행한다. control 도구에는 받지 않는다(always_not_allowed). allow_session(M7 3.11)은 요청 연결의 지금 탐색 세션 동안 같은 도구·권한 인자(control은 창 제목, screens는 도구 전체)의 ask를 다시 묻지 않는다 — 메모리에만, 세션 끝·연결 끊김·예산 초과·daemon 재시작에 사라지고 deny 규칙이 먼저다. 요청에 session이 없으면 session_not_allowed
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalAnswer".
 */
export type ApprovalAnswer = "allow_always" | "allow_once" | "allow_session" | "deny";
/**
 * 사람 확인 요청 ID
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalId".
 */
export type ApprovalId = string;
/**
 * 점으로 나눈 소문자 이름 (예: graph.open)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "MethodName".
 */
export type MethodName = string;
/**
 * 권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon의 AGENT_DENIED 목록 — daemon.shutdown, M3 디버그 메서드 debug.breakpoints.get·set·run.pause·run.resume·run.restart, run.export, M4 녹화·비밀값 메서드 recorder.*·secrets.*·target.read_text — 를 판정 전에 거부)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ToolName".
 */
export type ToolName =
  | "kb_adopt_request"
  | "kb_app_launch"
  | "kb_case_get"
  | "kb_case_list"
  | "kb_case_open"
  | "kb_case_update"
  | "kb_evidence_pin"
  | "kb_explore_end"
  | "kb_explore_start"
  | "kb_graph_create"
  | "kb_graph_get"
  | "kb_graph_list"
  | "kb_graph_patch"
  | "kb_graph_validate"
  | "kb_image_find"
  | "kb_input_click"
  | "kb_input_key"
  | "kb_input_type"
  | "kb_knowledge_apply"
  | "kb_knowledge_get"
  | "kb_knowledge_search"
  | "kb_log_search"
  | "kb_node_search"
  | "kb_ocr_read"
  | "kb_project_info"
  | "kb_report_note"
  | "kb_run_artifact_get"
  | "kb_run_cancel"
  | "kb_run_compare"
  | "kb_run_events"
  | "kb_run_start"
  | "kb_run_status"
  | "kb_screen_capture"
  | "kb_screen_get"
  | "kb_screen_identify"
  | "kb_screen_list"
  | "kb_screen_save"
  | "kb_target_create"
  | "kb_toolset_enable"
  | "kb_triage_signals"
  | "kb_wiki_write"
  | "ui_only";
/**
 * 워크스페이스 루트 기준 경로 ('/' 구분). daemon이 루트 밖·.kookabug/ 안을 거부한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "WorkspacePath".
 */
export type WorkspacePath = string;
/**
 * 그래프 파일 값 전체 (JSON 트리). 편집 중이라 형식이 틀릴 수 있다. JS에서 보낼 때는 반드시 wireStringify로 직렬화한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphValue".
 */
export type GraphValue = {[key: string]: unknown};
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ClientInfo".
 */
export type ClientInfo = UiClientInfo | AgentClientInfo;
/**
 * 실행 ID: 소문자·숫자 8자
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunId".
 */
export type RunId = string;
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Verdict".
 */
export type Verdict = "error" | "fail" | "pass" | "skipped";
/**
 * 비밀값 키 (그래프 $secret 키와 같은 규칙)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "SecretKey".
 */
export type SecretKey = string;
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
 * -32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로. M3: read_only(스냅샷 그래프 저장), not_paused(멈추지 않은 실행에 Step), run_not_debuggable(이 daemon이 띄운 UI 실행이 아님). M4 녹화: recording_active(이 daemon이 녹화 중이라 실행 거부 — starting 포함), input_lease_busy(입력 임대권을 다른 주체가 쥠), not_owner(녹화 세션을 연 연결이 아님), recorder_state_invalid(지금 녹화 상태에 맞지 않는 조작·없는 커밋 토큰), hook_failed(훅 프로세스를 띄우지 못함), hook_lost·input_overflow(훅이 끊김·중요 입력 유실로 녹화가 멈춤), no_frame(고를 프레임이 없음), 커밋 거부 classification_pending(비밀 판정 중)·text_review_required(확인 필요 입력)·secret_unresolved(키 없는 비밀값)·target_missing(대상 없는 클릭)·secret_region_overlap(비밀번호 칸과 겹치는 영역). M5: toolset_disabled(agent 연결이 켜지 않은 툴셋의 메서드 — 판정 전), force_not_allowed(agent 연결의 graph.save force), patch_invalid(graph.patch 연산이 틀림), agent_use_safe_api(agent 연결의 기록 원문 경로 — run.index·children·step·file·compare·subscribe, runs/ 이미지의 target.load_image·preview), secret_step(비밀값 스텝·agent_withhold 증거), unclassified_run(비밀값 분류 없는 옛 기록의 파일), not_evidence(그 실행의 증거 파일이 아님), video_not_served(영상 조각), recorder_frame(녹화 세션 프레임), sensitive_region(sensitive target이 보이는 화면의 OCR), frame_not_owned(agent 연결이 다른 연결이 만든 정지 화면을 씀). M5 B3: approval_required(사람 확인 필요 — data.reason no_approver면 확인할 사람 연결 없음), approval_denied(사람이 거부), approval_timeout(120초 안에 답 없음), always_not_allowed(control 도구에 항상 허용), settings_invalid(형식이 틀린 설정 파일 — 고치지 않음). M5 SECFIX: recorder_store_unclean(녹화 임시 파일을 정리하지 못함 — 메모리 스텝은 바뀌었고 daemon이 다시 정리한다). M6: plugin_failed(플러그인 작업 오류 — data.plugin_error의 code·stage·message, plugin_busy 포함), op_not_found(승인·취소할 플러그인 작업·미리보기가 없음 — 5분 지남·끝남). M7: frame_protected(보호 판정을 통과하지 못한 정지 화면 — data.reason 사유·message 안내, 민감 target 사유는 sensitive_region 그대로), protect_record_failed(비밀값 입력 전 보호 기록을 쓰지 못함 — 입력을 보내지 않았다). M7 탐색: agent_only(에이전트 연결 전용 메서드), explore_active(이 연결에 탐색 세션이 이미 있음), explore_not_active(탐색 세션 없음), explore_budget_exhausted(스텝 예산 다 씀 — 판정 전), screen_exists(확정 화면과 같은 키), detect_not_matching(판정 조건이 그 정지 화면에서 맞지 않음), secret_in_text(글자 필드에 비밀값 — data.field), secret_unchecked(비밀값 검사 불가 — 키를 못 읽음·보호 기록 손상), screens_busy(화면 지도 잠금) M8 B4: job_token_invalid(작업 토큰이 틀림·만료·폐기 — 연결 거부), job_only(작업 토큰 연결 전용 메서드), forbidden_visible(금지 문구·target·화면이 보여 입력하지 않음 — data.kind·value), forbidden_unverifiable(화면·OCR·target 확인 실패로 입력하지 않음), stalled_repeat(같은 작업에서 같은 실패 3번 — 그 테스트를 다시 돌리지 않음), case_resolution_reserved(사건 resolved·closed는 Kookabug·사람만), case_closed(닫힌 사건), verification_active(자동 채택 검증 실행 중이라 게임 입력을 받지 않음), 지식 연산 거부(duplicate_id·basis_required·basis_unknown·basis_hash_mismatch·basis_derived·human_basis_reserved·adoption_reserved·answer_reserved·too_large·path_alias)
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
  | "window_not_found"
  | "toolset_disabled"
  | "force_not_allowed"
  | "patch_invalid"
  | "agent_use_safe_api"
  | "secret_step"
  | "unclassified_run"
  | "not_evidence"
  | "video_not_served"
  | "recorder_frame"
  | "sensitive_region"
  | "frame_not_owned"
  | "approval_denied"
  | "approval_timeout"
  | "always_not_allowed"
  | "settings_invalid"
  | "recorder_store_unclean"
  | "plugin_failed"
  | "op_not_found"
  | "frame_protected"
  | "protect_record_failed"
  | "agent_only"
  | "explore_active"
  | "explore_not_active"
  | "explore_budget_exhausted"
  | "screen_exists"
  | "detect_not_matching"
  | "secret_in_text"
  | "secret_unchecked"
  | "screens_busy"
  | "session_not_allowed"
  | "approval_cancelled"
  | "recovery_pending"
  | "basis_denied"
  | "policy_path"
  | "knowledge_busy"
  | "already_reverted"
  | "change_not_active"
  | "nothing_to_revert"
  | "evidence_missing"
  | "job_token_invalid"
  | "job_only"
  | "forbidden_visible"
  | "forbidden_unverifiable"
  | "stalled_repeat"
  | "case_resolution_reserved"
  | "verification_active"
  | "duplicate_id"
  | "basis_required"
  | "basis_unknown"
  | "basis_hash_mismatch"
  | "basis_derived"
  | "human_basis_reserved"
  | "adoption_reserved"
  | "answer_reserved"
  | "too_large"
  | "path_alias"
  | "case_closed"
  | "job_budget_exhausted"
  | "job_ended"
  | "job_active";
/**
 * 플러그인 작업 ID (= 설치 거래 ID, 작업 로그 이름)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginOpId".
 */
export type PluginOpId = string;
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
 * graph.patch 연산 하나 (M5 계획 3.4). 노드 ID는 바꿀 수 없다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchOp".
 */
export type GraphPatchOp =
  | GraphPatchOpAddNode
  | GraphPatchOpSetNode
  | GraphPatchOpRemoveNode
  | GraphPatchOpConnect
  | GraphPatchOpDisconnect
  | GraphPatchOpLink
  | GraphPatchOpUnlink
  | GraphPatchOpMove
  | GraphPatchOpSetMeta;
/**
 * 노드 ID 또는 같은 묶음의 add_node ref
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchNodeRef".
 */
export type GraphPatchNodeRef = string;
/**
 * 요청 순번 (graph.validate·target.preview). 응답이 같은 값을 돌려주고, 클라이언트는 마지막으로 보낸 seq의 응답만 쓴다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestSeq".
 */
export type RequestSeq = number;
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatAdoption".
 */
export type Kb8CheatAdoption = Kb8CheatAdoptionValue | null;
/**
 * ready 준비됨 · missing 환경 없음([준비…]) · stale 조건(Python·SDK)이 앱과 다름([다시 잠그기…]) · broken 환경이 깨짐([준비…]로 새로)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginEnvStatus".
 */
export type PluginEnvStatus = "ready" | "missing" | "stale" | "broken";
/**
 * 권한 판정 값
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionVerdict".
 */
export type PermissionVerdict = "allow" | "ask" | "deny";
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginOpKind".
 */
export type PluginOpKind = "install" | "upgrade" | "remove" | "sync" | "relock" | "gc";
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginIsolation".
 */
export type PluginIsolation = "auto" | "shared" | "isolated";
/**
 * 그래프 파일 revision: 디스크 바이트의 sha256 hex
 */
export type Revision1 = string;
/**
 * 그래프 파일 revision: 디스크 바이트의 sha256 hex
 */
export type Revision2 = string;
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
 * image = 이 영역을 잘라 이미지 조건으로, ocr = 이 영역에 text가 있어야 (프레임 물리 픽셀)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensSaveCondition".
 */
export type ScreensSaveCondition =
  | {
      image: Rect;
    }
  | {
      ocr: Rect;
      text: string;
    };
/**
 * 이동 입력: 요소 클릭·점 클릭(프레임 물리 픽셀)·키
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensSaveVia".
 */
export type ScreensSaveVia =
  | {
      click: {
        element: string;
      };
    }
  | {
      click: {
        /**
         * @minItems 2
         * @maxItems 2
         */
        point: [number, number];
      };
    }
  | {
      key: string;
    };
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
 * UI·에이전트 ↔ daemon JSON-RPC 2.0 메시지 하나 (WebSocket 텍스트 프레임 하나, UTF-8 JSON, 최대 16 MiB). 값 규칙은 M0b와 같다: NaN·무한 금지, 정수 ±(2^53-1), 중첩 128단. 메서드·알림 모양은 $defs의 Methods·Notifications 표
 */
export interface DaemonRpcMessageDefs {}
/**
 * 감지 표의 에이전트 하나 (kookabug_core.agents.detect). 경로에서 찾기만 하고 설치하지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentCandidate".
 */
export interface AgentCandidate {
  args: string[];
  command: string;
  id: string;
  installed: boolean;
  name: string;
  /**
   * 찾은 실행 파일 (없으면 null)
   */
  path: null | string;
}
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
  /**
   * M8 3.14·R7: agent-job이 준 작업 토큰. 살아 있는 작업이면 주체에 그 작업이 붙고, 틀리거나 만료·폐기됐거나 다른 작업·주체의 토큰이면 job_token_invalid로 연결을 닫는다
   */
  job_token?: string;
  kind: "agent";
  name: string;
  version: string;
}
/**
 * daemon에 붙은 agent 연결 하나 (kookabug mcp)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentConnection".
 */
export interface AgentConnection {
  attended: boolean;
  connection: number;
  id: string;
  name: string;
  since: Timestamp;
  toolsets: Toolset[];
}
/**
 * agent 연결이 붙거나 끊기거나 툴셋을 켬 (ui 연결에만). 목록은 agent.connections로 다시 읽는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentConnectionsChangedParams".
 */
export interface AgentConnectionsChangedParams {}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentConnectionsResult".
 */
export interface AgentConnectionsResult {
  connections: AgentConnection[];
}
/**
 * M7: 에이전트 보호 기록 파일이 손상돼 에이전트에게 창 이미지를 보내지 않는다 (ui 연결에만, daemon 수명에 한 번 — 값 없음). 사람이 파일을 고치거나 지우고 daemon을 다시 시작해야 풀린다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentProtectCorruptParams".
 */
export interface AgentProtectCorruptParams {
  /**
   * 워크스페이스 기준 보호 기록 파일
   */
  path: string;
}
/**
 * 비밀값 저장소의 키 (값은 실행 때 찾는다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentSecretRef".
 */
export interface AgentSecretRef {
  $secret: string;
}
/**
 * 판단 노드·에이전트 패널이 띄우는 ACP 에이전트 하나. env의 비밀값은 {"$secret": 키}로만 쓴다 (실행 때 찾음)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentSpec".
 */
export interface AgentSpec {
  args?: string[];
  command: string;
  /**
   * 환경 변수 (이름 규칙은 사용자 설정 스키마가 쓰기 때 본다 — 틀리면 settings_invalid)
   */
  env?: {
    [k: string]: string | AgentSecretRef | undefined;
  };
  id: string;
  name: string;
}
/**
 * 툴셋을 켠다 (끄기는 없다). 켜도 각 도구의 권한 판정은 그대로다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentToolsetsEnableParams".
 */
export interface AgentToolsetsEnableParams {
  /**
   * @minItems 1
   */
  toolsets: [Toolset, ...Toolset[]];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentToolsetsEnableResult".
 */
export interface AgentToolsetsEnableResult {
  enabled: Toolset[];
  /**
   * 이번에 새로 쓸 수 있게 된 도구 이름 (권한 표 이름)
   */
  tools: string[];
}
/**
 * 자기 연결의 켜진 툴셋 (M5 계획 D3). ui 연결은 툴셋과 무관해 모두 켜짐으로 답한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentToolsetsResult".
 */
export interface AgentToolsetsResult {
  available: Toolset[];
  enabled: Toolset[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentsDetectResult".
 */
export interface AgentsDetectResult {
  candidates: AgentCandidate[];
}
/**
 * 사용자 설정의 에이전트 목록 (M5 계획 3.12). 파일이 없으면 빈 목록·revision null
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentsGetResult".
 */
export interface AgentsGetResult {
  agents: AgentSpec[];
  default_agent: null | string;
  /**
   * 파일 형식이 틀려 목록을 읽지 못했으면 그 이유 (agents.set도 settings_invalid로 거부)
   */
  problem: null | string;
  /**
   * 사용자 설정 파일 revision (없으면 null)
   */
  revision: Revision | null;
  /**
   * 사용자 설정 파일 경로 (정할 수 없으면 null)
   */
  source: null | string;
}
/**
 * 사용자 설정의 agents·default_agent만 바꾼다. 다른 키·순서는 보존, revision이 다르면 revision_conflict, 형식이 틀린 파일은 settings_invalid (permissions.set과 같은 쓰기 규칙)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentsSetParams".
 */
export interface AgentsSetParams {
  agents: AgentSpec[];
  /**
   * 읽은 때의 파일 revision (파일이 없었으면 null)
   */
  base_revision: Revision | null;
  /**
   * null이면 키를 지운다
   */
  default_agent: null | string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AgentsSetResult".
 */
export interface AgentsSetResult {
  revision: Revision;
}
/**
 * 게임을 띄운다 (설정 game.executable·game.args·game.cwd, 프로필 계층 포함). 실행·녹화 중이면 거부. 실행 Job 밖
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AppLaunchParams".
 */
export interface AppLaunchParams {
  profile?: null | string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "AppLaunchResult".
 */
export interface AppLaunchResult {
  pid: number;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalIdParams".
 */
export interface ApprovalIdParams {
  id: ApprovalId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalListResult".
 */
export interface ApprovalListResult {
  requests: ApprovalRequest[];
}
/**
 * 에이전트의 ask 판정 요청 하나 (approval.requested·approval.list). 기다리는 동안 daemon은 아무것도 쓰지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalRequest".
 */
export interface ApprovalRequest {
  agent: ApprovalAgent;
  /**
   * "항상 허용"을 고르면 저장할 규칙 글자. control 도구·규칙으로 쓸 수 없는 인자면 null(단추 없음)
   */
  always_rule: null | string;
  /**
   * 권한 인자 (그래프·target 경로, 실행 그래프 경로, 창 제목 등)
   */
  arg: string;
  /**
   * 요청한 agent 연결 번호
   */
  connection: number;
  expires_at: Timestamp;
  id: ApprovalId;
  method: MethodName;
  /**
   * approval.preview로 바뀔 그래프 값을 볼 수 있다 (graph.patch·graph.save·graph.create)
   */
  previewable: boolean;
  /**
   * M7 3.11: "이 탐색 동안 허용"(allow_session)을 쓸 수 있으면 요청 연결의 지금 탐색 세션, 아니면 null(단추 없음). control 도구와 screens 변경 도구에만
   */
  session: null | ApprovalSession;
  /**
   * 사람이 읽는 요약 줄
   */
  summary: string[];
  tool: ToolName;
}
export interface ApprovalAgent {
  id: string;
  name: string;
}
export interface ApprovalSession {
  id: string;
  title: string;
}
/**
 * 승인하면 쓰일 그래프 값 (쓰지 않는다, "캔버스에서 보기" U10)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalPreviewResult".
 */
export interface ApprovalPreviewResult {
  path: WorkspacePath;
  /**
   * 기준 디스크 revision (새 파일이면 null)
   */
  revision: Revision | null;
  value: GraphValue;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalResolvedParams".
 */
export interface ApprovalResolvedParams {
  /**
   * 답한 ui 연결(ui:<번호>) 또는 daemon(시간 초과·요청 연결 끊김·탐색 세션 끝)
   */
  by: string;
  id: ApprovalId;
  verdict: "allow_always" | "allow_once" | "allow_session" | "cancelled" | "deny" | "timeout";
}
/**
 * 사람 확인 답. 끝난(답함·시간 초과·취소) 요청이면 not_found
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ApprovalRespondParams".
 */
export interface ApprovalRespondParams {
  id: ApprovalId;
  verdict: ApprovalAnswer;
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
 * 창을 클릭한다 (point와 target 중 하나). daemon이 한 스텝짜리 제어 실행으로 돌린다 (M5 3.9)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlClickParams".
 */
export interface ControlClickParams {
  button?: "left" | "middle" | "right";
  count?: number;
  /**
   * [x, y] 클라이언트 영역 물리 픽셀
   *
   * @minItems 2
   * @maxItems 2
   */
  point?: [number, number];
  target?: WorkspacePath;
  /**
   * 창 제목 (정확히 같은 제목의 창, 권한 인자)
   */
  window: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlKeyParams".
 */
export interface ControlKeyParams {
  /**
   * 키 하나나 조합 (ctrl+a). 누르고 바로 뗀다
   */
  keys: string;
  /**
   * 창 제목 (정확히 같은 제목의 창, 권한 인자)
   */
  window: string;
}
/**
 * 제어 실행 결과 (runs/ 아래 source agent_control 기록). 실패면 error (메시지는 3.8로 가림)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlResult".
 */
export interface ControlResult {
  error?: ControlError;
  run_id: RunId;
  verdict: Verdict;
}
export interface ControlError {
  code: string;
  message?: string;
}
/**
 * 글자 입력 (text와 secret 중 하나). secret은 비밀값 키 — 값은 runner가 찾고 결과·기록·오류에 원문이 없다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ControlTypeParams".
 */
export interface ControlTypeParams {
  secret?: SecretKey;
  text?: string;
  /**
   * 창 제목 (정확히 같은 제목의 창, 권한 인자)
   */
  window: string;
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
 * error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found·run_not_debuggable·not_paused → run_id, read_only → path, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message. M4: input_lease_busy → owner(살아 있음이 확인된 소유자, 모르면 null), recording_active·not_owner·recorder_state_invalid → state, classification_pending·text_review_required·secret_unresolved·target_missing·secret_region_overlap → steps(걸린 스텝). M5: toolset_disabled → toolset, patch_invalid → index·message. M5 B3: approval_required → decision·reason. M6: plugin_failed → plugin_error, op_not_found → op_id. M7: frame_protected·sensitive_region → reason·message(안내), secret_in_text → field, secret_unchecked → reason(못 읽은 키 이름). M8: forbidden_visible·forbidden_unverifiable → kind·value·reason(고정 사유), job_token_invalid → message 없음, permission_denied → reason job_scope(작업 허용 범위 밖)
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
  /**
   * M7 secret_in_text: 비밀값이 든 글자 필드 이름 (값 없음)
   */
  field?: string;
  /**
   * patch_invalid: 틀린 연산의 순번 (0부터)
   */
  index?: number;
  /**
   * M7 B4 recovery_pending: 남은 승격 거래 저널 ID
   */
  journals?: string[];
  /**
   * M8 forbidden_visible·forbidden_unverifiable: 걸린 금지 항목 종류 (text·target·screen, 모르면 null)
   */
  kind?: string | null;
  line?: number | null;
  message?: string;
  op_id?: string;
  owner?: LeaseOwner | null;
  path?: string;
  /**
   * M7 B4 revision_conflict·recovery_pending: 걸린 화면 지도 파일들 (워크스페이스 기준)
   */
  paths?: string[];
  plugin_error?: PluginErrorInfo;
  protocol?: number;
  /**
   * approval_required: no_approver(사람 연결 없음). M6: permission_denied: dev_modules_agent(개발 모듈 daemon의 에이전트 실행)
   */
  reason?: string;
  revision?: string | null;
  run_id?: RunId;
  state?: RecorderState;
  steps?: RecorderStepId[];
  toolset?: Toolset;
  /**
   * M8 forbidden_*: 걸린 금지 항목 값 (정책의 문구·target 경로·화면 ID — 화면 글자가 아니다, 모르면 null)
   */
  value?: string | null;
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
 * 플러그인 작업 오류 요약 (kookabug_core.plugins.PluginError.to_json — 인증 정보를 가린 값). code는 설치 거래 오류 코드(M6 3.5)·plugin_busy·internal_error, 원문은 작업 로그(.kookabug/plugins/logs/<op_id>.log)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginErrorInfo".
 */
export interface PluginErrorInfo {
  code: string;
  conflicts?: string[];
  env?: string;
  message: string;
  op_id?: PluginOpId;
  packages?: string[];
  plugin?: string;
  stage: null | string;
  [k: string]: unknown | undefined;
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
 * M7: 탐색 세션·후보가 바뀜 (ui 연결에만)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreChangedParams".
 */
export interface ExploreChangedParams {
  sessions: ExploreSessionInfo[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreSessionInfo".
 */
export interface ExploreSessionInfo {
  agent: string;
  counts: ExploreCounts;
  id: string;
  max_steps: number;
  started_at: string;
  status: "active" | "ended" | "interrupted";
  steps: number;
  title: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreCounts".
 */
export interface ExploreCounts {
  moves: number;
  screens: number;
  untried: number;
}
/**
 * explore.end (kb_explore_end): 이 연결의 탐색 세션을 끝낸다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreEndParams".
 */
export interface ExploreEndParams {}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreEndResult".
 */
export interface ExploreEndResult {
  counts: ExploreCounts;
  session: string;
}
/**
 * explore.list (사람 화면용): screens/_explored/의 탐색 세션들
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreListParams".
 */
export interface ExploreListParams {}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreListResult".
 */
export interface ExploreListResult {
  sessions: ExploreSessionInfo[];
}
/**
 * explore.start (kb_explore_start, M7 3.4): 탐색 세션 (에이전트 연결마다 하나)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreStartParams".
 */
export interface ExploreStartParams {
  goal?: string;
  max_steps?: number;
  title: string;
  window?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ExploreStartResult".
 */
export interface ExploreStartResult {
  folder: WorkspacePath;
  max_steps: number;
  session: string;
}
/**
 * 편집기 정지 화면 (daemon 프레임 캐시, 최대 16장. 사라지면 frame_expired)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Frame".
 */
export interface Frame {
  /**
   * agent 연결의 target.capture만 (M5 kb_screen_capture): 긴 변 1568·1 MiB 이하 PNG를 .kookabug/cache/agent/<cache>에 썼다 (읽은 쪽이 지운다)
   */
  agent_image?: {
    cache: string;
    height: number;
    width: number;
  };
  client_size: Size;
  dpi: number;
  frame_id: string;
  height: number;
  image: ImageRef;
  /**
   * agent 연결의 target.capture만 (M7 3.5a): 이 정지 화면은 보호 판정을 통과하지 못해 이미지를 어디에도 쓰지 않았다(agent_image 없음, image.cache 파일 없음). 사유와 안내만
   */
  protected?: {
    hint: string;
    reason:
      | "guard_error"
      | "protect_state_unknown"
      | "secret_field"
      | "secret_field_unknown"
      | "sensitive_unchecked"
      | "sensitive_visible"
      | "window_unknown";
  };
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
 * 경로로 검증 (kb_graph_validate로 판정, M5). value가 없으면 디스크 값, 있으면 그 값(쓰지 않음)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphCheckParams".
 */
export interface GraphCheckParams {
  path: WorkspacePath;
  value?: GraphValue;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphCheckResult".
 */
export interface GraphCheckResult {
  diagnostics: Diagnostic[];
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
  /**
   * 만들 틀에 적용할 graph.patch 연산 (M5). 틀리면 파일을 만들지 않는다
   *
   * @maxItems 1000
   */
  ops?: GraphPatchOp[];
  path: WorkspacePath;
  title?: string;
}
/**
 * 새 노드. ID는 daemon이 만든다 (n_ + 8자)
 */
export interface GraphPatchOpAddNode {
  config?: {
    [k: string]: unknown | undefined;
  };
  in?: {
    [k: string]: unknown | undefined;
  };
  op: "add_node";
  position?: GraphPatchPosition;
  /**
   * 이 묶음 안 임시 이름 (결과 created에 ref → 새 ID)
   */
  ref: string;
  title?: string;
  type: string;
  version?: number;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchPosition".
 */
export interface GraphPatchPosition {
  x: number;
  y: number;
}
/**
 * 노드 고치기 (type·id는 바꿀 수 없다)
 */
export interface GraphPatchOpSetNode {
  /**
   * 키 단위 병합. 값이 null이면 그 키를 지운다
   */
  config?: {
    [k: string]: unknown | undefined;
  };
  id: GraphPatchNodeRef;
  /**
   * 키 단위 병합. 값이 null이면 그 키를 지운다
   */
  in?: {
    [k: string]: unknown | undefined;
  };
  op: "set_node";
  record?: {
    [k: string]: unknown | undefined;
  } | null;
  title?: string | null;
}
/**
 * 노드와 그 노드를 가리키는 next·$link를 지운다
 */
export interface GraphPatchOpRemoveNode {
  id: GraphPatchNodeRef;
  op: "remove_node";
}
/**
 * exec 연결 (next)
 */
export interface GraphPatchOpConnect {
  exit: string;
  from: GraphPatchNodeRef;
  op: "connect";
  to: GraphPatchNodeRef;
}
/**
 * exec 연결 끊기
 */
export interface GraphPatchOpDisconnect {
  exit: string;
  from: GraphPatchNodeRef;
  op: "disconnect";
}
/**
 * 데이터 연결 ($link)
 */
export interface GraphPatchOpLink {
  from: GraphPatchNodeRef;
  op: "link";
  output: string;
  pin: string;
  to: GraphPatchNodeRef;
}
/**
 * 데이터 연결 끊기 (그 핀 값을 지운다)
 */
export interface GraphPatchOpUnlink {
  op: "unlink";
  pin: string;
  to: GraphPatchNodeRef;
}
/**
 * 레이아웃만
 */
export interface GraphPatchOpMove {
  id: GraphPatchNodeRef;
  op: "move";
  position: GraphPatchPosition;
}
/**
 * 그래프 머리 (null이면 지운다)
 */
export interface GraphPatchOpSetMeta {
  description?: string | null;
  op: "set_meta";
  title?: string | null;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphListEntry".
 */
export interface GraphListEntry {
  kind?: "subgraph" | "test";
  path: WorkspacePath;
  problem?: string;
  title?: string;
}
/**
 * 그래프 파일 목록 (kb_graph_list로 판정, M5). 범위는 workspace.tree와 같다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphListParams".
 */
export interface GraphListParams {
  /**
   * 이 폴더 아래만 (예: tests). 권한 인자
   */
  under?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphListResult".
 */
export interface GraphListResult {
  graphs: GraphListEntry[];
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
   * M8 3.6: 작업 연결이 본 작업 기준 사본이면 working
   */
  basis?: "working";
  /**
   * 원문이 canonical 형식인가
   */
  canonical: boolean;
  /**
   * M8 3.6: 그 작업 기준 변경 ID
   */
  change?: string;
  /**
   * graph.create ops의 add_node ref → 새 노드 ID (M5, ops를 줬을 때만)
   */
  created?: {
    [k: string]: string | undefined;
  };
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
 * 경로로 그래프를 고친다 (M5 계획 3.4). 모두 적용하거나 하나도 안 한다. 디스크가 base_revision과 다르면 revision_conflict, 연산이 틀리면 patch_invalid, 적용한 값이 그래프 형식에 맞지 않으면 validation_failed
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchParams".
 */
export interface GraphPatchParams {
  base_revision: Revision;
  /**
   * @minItems 1
   * @maxItems 1000
   */
  ops: [GraphPatchOp, ...GraphPatchOp[]];
  path: WorkspacePath;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchRemovedRef".
 */
export interface GraphPatchRemovedRef {
  from: string;
  /**
   * next면 출구 이름, link면 핀 이름
   */
  key: string;
  kind: "link" | "next";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "GraphPatchResult".
 */
export interface GraphPatchResult {
  /**
   * M8 E3: 작업 기준으로 썼으면 working (팀 파일은 그대로)
   */
  basis?: "working";
  /**
   * M8 E3: 쓴 작업 기준 변경 ID
   */
  change?: string;
  /**
   * add_node ref → 새 노드 ID
   */
  created: {
    [k: string]: string | undefined;
  };
  diagnostics: Diagnostic[];
  /**
   * remove_node가 함께 지운 연결
   */
  removed_refs: GraphPatchRemovedRef[];
  revision: Revision;
  wrote: boolean;
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
 * adopt.request: 사건의 작업 기준 변경 하나를 자동 채택 조건 1~8로 검사해 팀에 게시 (M8 3.8·R1). 검증 실행은 Kookabug가 고른다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8AdoptRequestParams".
 */
export interface Kb8AdoptRequestParams {
  case: string;
  change: string;
  /**
   * @maxItems 16
   */
  negatives?:
    | []
    | [
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ]
    | [
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        },
        {
          frame_id: string;
          note: string;
        }
      ];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8AdoptRequestResult".
 */
export interface Kb8AdoptRequestResult {
  adopted: boolean;
  adoption: string | null;
  failed: {
    code: string;
    condition: number;
    detail: string;
  } | null;
  kept: "working";
  manifest: string | null;
  negatives: string[];
  runs: string[];
}
/**
 * adopt.revert: 채택(자동·수락)을 한 번 되돌린다 (사람 전용). 팀 파일이 채택 뒤 바이트일 때만
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8AdoptRevertParams".
 */
export interface Kb8AdoptRevertParams {
  adoption: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8AdoptRevertResult".
 */
export interface Kb8AdoptRevertResult {
  adoption: string;
  files: string[];
  reverted: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8AdoptionsListResult".
 */
export interface Kb8AdoptionsListResult {
  adoptions: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CaseGetResult".
 */
export interface Kb8CaseGetResult {
  case: {
    [k: string]: unknown | undefined;
  };
  sha256: string;
}
/**
 * 사건 하나 (cases.get·cases.signals)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CaseIdParams".
 */
export interface Kb8CaseIdParams {
  id: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CaseRevisionResult".
 */
export interface Kb8CaseRevisionResult {
  case: string;
  revision: number;
}
/**
 * cases.signals (kb_triage_signals): 판단 재료만 모은다. 원인을 판정하지 않는다 (3.13)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CaseSignalsResult".
 */
export interface Kb8CaseSignalsResult {
  case: string;
  claims: {
    [k: string]: unknown | undefined;
  }[];
  diff: {
    [k: string]: unknown | undefined;
  } | null;
  not_comparable: {
    [k: string]: unknown | undefined;
  }[];
  reruns: {
    [k: string]: unknown | undefined;
  };
  screen: {
    [k: string]: unknown | undefined;
  };
  sources: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CaseSummary".
 */
export interface Kb8CaseSummary {
  id: string;
  revision: number;
  runs: number;
  signature: string;
  state: string;
  symptom: {
    [k: string]: unknown | undefined;
  };
  title: string;
}
/**
 * cases.close (사람 전용): 사건을 resolved·closed로 (resolution by human)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesCloseParams".
 */
export interface Kb8CasesCloseParams {
  base_revision: number;
  id: string;
  note?: string;
  state?: "closed" | "resolved";
}
/**
 * cases.list (kb_case_list): 사건 목록
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesListParams".
 */
export interface Kb8CasesListParams {
  state?: "closed" | "needs_info" | "open" | "resolved" | "watching";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesListResult".
 */
export interface Kb8CasesListResult {
  cases: Kb8CaseSummary[];
}
/**
 * cases.open (kb_case_open): 실패 실행으로 사건을 연다. 같은 시그니처 사건이 있으면 새로 열지 않고 그 사건 runs에 붙인다(attached). 원래 실패 증거는 Kookabug가 고정한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesOpenParams".
 */
export interface Kb8CasesOpenParams {
  run: string;
  title?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesOpenResult".
 */
export interface Kb8CasesOpenResult {
  attached: boolean;
  case: string;
  evidence: string | null;
  hypotheses: {
    [k: string]: unknown | undefined;
  }[];
  revision: number;
  signature: string;
}
/**
 * cases.update (kb_case_update): 제목·상태(open·needs_info·watching)·가설·조치·필요 정보·재확인·연결. resolved·closed는 case_resolution_reserved, original·runs·signature·symptom·resolution은 바꾸지 못한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CasesUpdateParams".
 */
export interface Kb8CasesUpdateParams {
  base_revision: number;
  changes: {
    [k: string]: unknown | undefined;
  };
  id: string;
}
export interface Kb8CheatAdoptionValue {
  at: string;
  by: "human";
  category: string;
  digest: string;
}
/**
 * cheats.categories.set: kookabug.json cheats 블록 (사람 전용). base_sha256은 지금 kookabug.json 바이트의 sha256 (다르면 revision_conflict)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatCategoriesSetParams".
 */
export interface Kb8CheatCategoriesSetParams {
  base_sha256: string;
  categories: Kb8CheatCategory[];
  enabled: boolean;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatCategory".
 */
export interface Kb8CheatCategory {
  description?: string;
  id: string;
  title: string;
  unattended?: boolean;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatCategoriesSetResult".
 */
export interface Kb8CheatCategoriesSetResult {
  sha256: string;
}
/**
 * cheats.list 항목: 정의 요약과 채택 상태 (adopted: 채택 digest가 지금 정의·구현과 같다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatSummary".
 */
export interface Kb8CheatSummary {
  adopted: boolean;
  adoption: Kb8CheatAdoption;
  args: {
    [k: string]: unknown | undefined;
  };
  category: null | string;
  effect: string;
  id: string;
  /**
   * 채택할 수 없거나 채택이 무효인 까닭 (없으면 null)
   */
  problem: null | string;
  rev: number;
  title: string;
}
/**
 * cheats.adopt: 그 rev 정의를 분류와 함께 채택 (사람 전용)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatsAdoptParams".
 */
export interface Kb8CheatsAdoptParams {
  category: string;
  id: string;
  rev: number;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatsAdoptResult".
 */
export interface Kb8CheatsAdoptResult {
  adoption: Kb8CheatAdoption;
  id: string;
  revision: number;
}
/**
 * cheats.list: knowledge/cheats.json 치트와 kookabug.json 치트 정책
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatsListResult".
 */
export interface Kb8CheatsListResult {
  categories: Kb8CheatCategory[];
  cheats: Kb8CheatSummary[];
  enabled: boolean;
  revision: number;
}
/**
 * cheats.unadopt: 채택 풀기 (사람 전용)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8CheatsUnadoptParams".
 */
export interface Kb8CheatsUnadoptParams {
  id: string;
  rev: number;
}
/**
 * project.automation.set·project.sources.set (사람 전용): kookabug.json의 그 블록만 바꾼다. 지금 sha가 다르면 revision_conflict
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ConfigBlockParams".
 */
export interface Kb8ConfigBlockParams {
  base_sha256: string;
  value:
    | unknown[]
    | {
        [k: string]: unknown | undefined;
      };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ConfigBlockResult".
 */
export interface Kb8ConfigBlockResult {
  sha256: string;
}
/**
 * evidence.pin: 실행 기록에서 가림 처리한 최소 증거 묶음을 knowledge/evidence/에 고정 (지우거나 고치는 도구 없음)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8EvidencePinParams".
 */
export interface Kb8EvidencePinParams {
  note: string;
  run: string;
  step?: string | null;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8EvidencePinResult".
 */
export interface Kb8EvidencePinResult {
  files: string[];
  id: string;
  omitted: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * job.begin (사람 전용, agent-job CLI): 작업을 만들고 작업 토큰을 준다. 토큰은 이 응답에만 있고 daemon은 해시만 둔다. 부른 연결이 소유 연결이다(R8 — job.heartbeat, 끊기면 작업 끝). 사람 입력 임대권·녹화 중이면 토큰 없이 prep_failed
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobBeginParams".
 */
export interface Kb8JobBeginParams {
  /**
   * Agent 프로필 이름 (보고 표시용)
   */
  agent?: string;
  basis?: "team" | "working";
  budget?: {
    minutes?: number;
    runs?: number;
  };
  playbook: "author" | "explore" | "init" | "lint" | "probe" | "repair" | "triage";
  toolsets?: Toolset[];
  trigger?: "ci" | "manual" | "schedule";
  ttl_s?: number;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobBeginResult".
 */
export interface Kb8JobBeginResult {
  agent_id?: string;
  expires_at?: string;
  job: string;
  reason?: "input_lease" | "recording" | "shutting_down";
  report?: string | null;
  started_at?: string;
  state: "prep_failed" | "running";
  token?: string;
}
/**
 * M8: 작업 예산 상한에 닿음 (ui 연결에만)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobBudgetParams".
 */
export interface Kb8JobBudgetParams {
  job: string;
  limit: {
    [k: string]: unknown | undefined;
  };
  used: {
    [k: string]: unknown | undefined;
  };
}
/**
 * M8: 작업 상태가 바뀜 (ui 연결에만)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobChangedParams".
 */
export interface Kb8JobChangedParams {
  job: string;
  state: string;
  used: {
    [k: string]: unknown | undefined;
  };
}
/**
 * job.end (사람 전용): 작업 토큰을 먼저 폐기하고 그 작업의 실행을 취소한다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobEndParams".
 */
export interface Kb8JobEndParams {
  job: string;
  reason: "budget_exhausted" | "cancelled" | "done" | "failed" | "interrupted" | "timeout";
}
/**
 * 작업 종료 경로(R8) 결과: 토큰 폐기 → 실행·채택 검증 취소 → 감독자 입력 복구 완료 → 보고. 같은 작업을 다시 끝내면 첫 결과. 입력 복구를 확인하지 못했으면 state ending·settled false·report null (보고·끝 알림 없음, 작업 슬롯 유지 — 다시 부르면 같은 완료를 기다린다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobEndResult".
 */
export interface Kb8JobEndResult {
  cancelled: string[];
  job: string;
  /**
   * 작업 연결이 kb_project_info를 불렀다 (agent-job probe)
   */
  probe_ok?: boolean;
  report?: string | null;
  settled?: boolean;
  state?:
    "budget_exhausted" | "cancelled" | "done" | "ending" | "failed" | "interrupted" | "prep_failed";
  used?: Kb8JobUsed;
}
/**
 * 작업이 쓴 예산 (실행 수는 run.start·자동 채택 검증 실행, 도구 호출 수는 작업 연결 요청)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobUsed".
 */
export interface Kb8JobUsed {
  minutes: number;
  runs: number;
  tool_calls: number;
}
/**
 * job.finish (사람 전용): CLI가 끝났다 → 같은 종료 경로로 끝내고 보고를 만든다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobFinishParams".
 */
export interface Kb8JobFinishParams {
  exit_code?: number | null;
  job: string;
  /**
   * prep_failed 사유 (고정 코드, 값·경로 없음)
   */
  prep_reason?: string;
  state?: "budget_exhausted" | "cancelled" | "done" | "failed" | "interrupted" | "prep_failed";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobHeartbeatResult".
 */
export interface Kb8JobHeartbeatResult {
  job: string;
  state: "running";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobIdParams".
 */
export interface Kb8JobIdParams {
  job: string;
}
/**
 * job.note (kb_report_note): 작업 토큰 연결 전용. 보고의 Agent 요약 글 (4 KB, 글자 검사)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobNoteParams".
 */
export interface Kb8JobNoteParams {
  text: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobNoteResult".
 */
export interface Kb8JobNoteResult {
  bytes: number;
  job: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8JobsListResult".
 */
export interface Kb8JobsListResult {
  jobs: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * knowledge.apply (kb_knowledge_apply): 제한 변경 연산 묶음 (M8 3.3, kookabug.knowledge-ops/0). 전부 적용하거나 아무것도 쓰지 않는다. 같은 request_id 재요청은 지난 결과
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeApplyParams".
 */
export interface Kb8KnowledgeApplyParams {
  /**
   * @minItems 1
   * @maxItems 200
   */
  ops: [
    {
      [k: string]: unknown | undefined;
    },
    ...{
      [k: string]: unknown | undefined;
    }[]
  ];
  request_id: string;
}
/**
 * 적용 결과 (코어 knowledge.ops.apply 그대로): applied·conflicts·working 등
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeApplyResult".
 */
export interface Kb8KnowledgeApplyResult {
  [k: string]: unknown | undefined;
}
/**
 * M8: knowledge/·wiki/가 바뀜 (ui 연결에만)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeChangedParams".
 */
export interface Kb8KnowledgeChangedParams {
  files: string[];
}
/**
 * knowledge.get (kb_knowledge_get): 지식 파일(features/<기능>·lessons·cheats·unknowns) 또는 그 항목 하나. 주장 파일은 작업 기준 덧씌움(working)도 함께 준다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeGetParams".
 */
export interface Kb8KnowledgeGetParams {
  file: string;
  id?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeGetResult".
 */
export interface Kb8KnowledgeGetResult {
  doc?: {
    [k: string]: unknown | undefined;
  };
  file: string;
  item?: {
    [k: string]: unknown | undefined;
  };
  revision: number;
  sha256: string | null;
  working: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * knowledge.search (kb_knowledge_search): 지식 항목(주장·경험칙·치트·미지수)의 ID·글자에서 찾는다 (대소문자·공백 무시 포함)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeSearchParams".
 */
export interface Kb8KnowledgeSearchParams {
  /**
   * @maxItems 64
   */
  files?: string[];
  limit?: number;
  query: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8KnowledgeSearchResult".
 */
export interface Kb8KnowledgeSearchResult {
  matches: {
    file: string;
    id: string;
    kind: string | null;
    rev: number | null;
    status: string | null;
    text: string;
  }[];
  truncated: boolean;
}
/**
 * local.settings.set (사람 전용, B7 마법사 2단계): .kookabug/local.json settings의 게임 실행 키만 바꾼다 (이 PC). null이면 키를 지운다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8LocalSettingsSetParams".
 */
export interface Kb8LocalSettingsSetParams {
  /**
   * 주면 local.json revision 대조 (화면을 채울 때 wizard.get local_revision으로 읽은 값, 파일이 없었으면 null). 다르면 revision_conflict
   */
  base_revision?: string | null;
  settings?: {
    "game.args"?: string[] | null;
    "game.cwd"?: string | null;
    "game.executable"?: string | null;
  };
  /**
   * 원본 ID → 이 PC 경로 (local.json sources.<id>.path, 6단계 local 원본). null이면 지운다
   */
  sources?: {
    [k: string]: string | null | undefined;
  };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8LocalSettingsSetResult".
 */
export interface Kb8LocalSettingsSetResult {
  revision: string;
}
/**
 * M8 다음 묶음(B5·B7)이 모양을 정하는 결과
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8LooseResult".
 */
export interface Kb8LooseResult {
  [k: string]: unknown | undefined;
}
/**
 * project.qa_info (kb_project_info): 플레이북 판·원본 상태·자동화 정책·치트 설정·경고 (M8 3.4·3.10·3.12)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ProjectQaInfoResult".
 */
export interface Kb8ProjectQaInfoResult {
  automation: {
    [k: string]: unknown | undefined;
  };
  cheats: {
    [k: string]: unknown | undefined;
  };
  job: {
    [k: string]: unknown | undefined;
  } | null;
  playbooks: {
    [k: string]: number | undefined;
  };
  sources: {
    [k: string]: unknown | undefined;
  }[];
  warnings: string[];
}
/**
 * project.setup.set (사람 전용, B7 마법사 2·8단계): kookabug.json의 record·retention 블록과 게임 설정 키(game.title·game.client_size)를 한 번에 바꾼다. 지금 sha가 다르면 revision_conflict
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ProjectSetupSetParams".
 */
export interface Kb8ProjectSetupSetParams {
  base_sha256: string;
  record?: {
    [k: string]: unknown | undefined;
  };
  retention?: {
    [k: string]: unknown | undefined;
  };
  settings?: {
    "game.client_size"?: Size;
    "game.title"?: string;
  };
}
/**
 * report.decide (사람 전용, B5): 보고 묶음 결정 → working.accept/reject
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ReportDecideParams".
 */
export interface Kb8ReportDecideParams {
  decision: "accept" | "reject";
  group: string;
  job: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ReportDecideResult".
 */
export interface Kb8ReportDecideResult {
  decision: "accept" | "reject";
  group: string;
  job: string;
  result: {
    [k: string]: unknown | undefined;
  };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ReportGetResult".
 */
export interface Kb8ReportGetResult {
  report: {
    [k: string]: unknown | undefined;
  };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8ReportsListResult".
 */
export interface Kb8ReportsListResult {
  reports: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8SourcesCheckResult".
 */
export interface Kb8SourcesCheckResult {
  sources: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * unknowns.answer (사람 전용): 미지수에 사람 답을 단다 (basis.type human으로 쓸 수 있다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8UnknownsAnswerParams".
 */
export interface Kb8UnknownsAnswerParams {
  base_rev: number;
  id: string;
  text: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8UnknownsAnswerResult".
 */
export interface Kb8UnknownsAnswerResult {
  id: string;
  rev: number;
}
/**
 * wiki.write (kb_wiki_write): 산문 위키 페이지 하나 (wiki/** /*.md, index·log·reports 제외)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WikiWriteParams".
 */
export interface Kb8WikiWriteParams {
  base_sha256: string | null;
  path: string;
  text: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WikiWriteResult".
 */
export interface Kb8WikiWriteResult {
  path: string;
  rendered_claims: boolean;
  sha256: string;
  warnings: string[];
}
/**
 * wizard.get (사람 전용, B7): 마법사 진행과 단계 판정에 쓰는 지금 설정. team_setup = 팀이 첫 설정을 마친 프로젝트(wiki/index.md 있음) — 짧은 마법사 자동 띄우기 조건
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WizardGetResult".
 */
export interface Kb8WizardGetResult {
  config_sha256: string;
  /**
   * 실효 게임 설정 (local.json이 kookabug.json보다 먼저)
   */
  game: {
    args: string[] | null;
    client_size: Size | null;
    cwd: null | string;
    executable: null | string;
    title: null | string;
  };
  /**
   * .kookabug/local.json revision (없으면 null) — local.settings.set base_revision에 쓴다
   */
  local_revision: string | null;
  /**
   * 이 PC 원본 경로 (local.json sources.<id>.path, 6단계). 경로만 — 비밀값 없음
   */
  local_sources: {
    [k: string]: string | undefined;
  };
  record: {
    [k: string]: unknown | undefined;
  };
  retention: {
    [k: string]: unknown | undefined;
  };
  /**
   * 팀 원본 정의 (kookabug.json sources, config_sha256과 같은 읽기)
   */
  sources: {
    [k: string]: unknown | undefined;
  }[];
  team_setup: boolean;
  wizard: Kb8WizardState | null;
}
/**
 * 마법사 진행 (.kookabug/wizard.json, kookabug.wizard/0, 이 PC). 단계 상태만 둔다 — 입력 값·비밀값·경로를 두지 않는다 (M8 3.17)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WizardState".
 */
export interface Kb8WizardState {
  done: number[];
  format: "kookabug.wizard/0";
  skipped: number[];
  step: number;
  /**
   * @maxItems 50
   */
  warnings: {
    code: string;
    step: number;
  }[];
}
/**
 * wizard.set (사람 전용, B7): 마법사 진행을 .kookabug/wizard.json에 원자 쓰기
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WizardSetParams".
 */
export interface Kb8WizardSetParams {
  wizard: Kb8WizardState;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WizardSetResult".
 */
export interface Kb8WizardSetResult {
  wizard: Kb8WizardState;
}
/**
 * working.accept·working.reject: 작업 기준 변경(파일)과 작업 주장 rev를 한 거래로 수락하거나 덧씌움에서 뺀다 (사람 전용). claims의 rev는 보고가 가리킨 작업 rev — 지금과 다르면 revision_conflict
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WorkingDecideParams".
 */
export interface Kb8WorkingDecideParams {
  /**
   * @maxItems 200
   */
  changes?: string[];
  /**
   * @maxItems 200
   */
  claims?: {
    id: string;
    rev: number;
  }[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WorkingDecideResult".
 */
export interface Kb8WorkingDecideResult {
  adoption: string | null;
  changes: string[];
  claims: {
    [k: string]: unknown | undefined;
  }[];
  conflicts: {
    [k: string]: unknown | undefined;
  }[];
  files: string[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Kb8WorkingListResult".
 */
export interface Kb8WorkingListResult {
  changes: {
    [k: string]: unknown | undefined;
  }[];
  claims: {
    [k: string]: unknown | undefined;
  }[];
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
  "adopt.request": {
    params: Kb8AdoptRequestParams;
    renderer: false;
    result: Kb8AdoptRequestResult;
    tool: "kb_adopt_request";
  };
  "adopt.revert": {
    params: Kb8AdoptRevertParams;
    renderer: true;
    result: Kb8AdoptRevertResult;
    tool: "ui_only";
  };
  "adoptions.list": {
    params: EmptyParams;
    renderer: true;
    result: Kb8AdoptionsListResult;
    tool: "ui_only";
  };
  "agent.connections": {
    params: EmptyParams;
    renderer: true;
    result: AgentConnectionsResult;
    tool: "ui_only";
  };
  "agent.toolsets.enable": {
    params: AgentToolsetsEnableParams;
    renderer: false;
    result: AgentToolsetsEnableResult;
    tool: "kb_toolset_enable";
  };
  "agent.toolsets.get": {
    params: EmptyParams;
    renderer: false;
    result: AgentToolsetsResult;
    tool: "kb_toolset_enable";
  };
  "agents.detect": {
    params: EmptyParams;
    renderer: true;
    result: AgentsDetectResult;
    tool: "ui_only";
  };
  "agents.get": {
    params: EmptyParams;
    renderer: true;
    result: AgentsGetResult;
    tool: "ui_only";
  };
  "agents.set": {
    params: AgentsSetParams;
    renderer: true;
    result: AgentsSetResult;
    tool: "ui_only";
  };
  "app.launch": {
    params: AppLaunchParams;
    renderer: false;
    result: AppLaunchResult;
    tool: "kb_app_launch";
  };
  "approval.list": {
    params: EmptyParams;
    renderer: true;
    result: ApprovalListResult;
    tool: "ui_only";
  };
  "approval.preview": {
    params: ApprovalIdParams;
    renderer: true;
    result: ApprovalPreviewResult;
    tool: "ui_only";
  };
  "approval.respond": {
    params: ApprovalRespondParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "cases.close": {
    params: Kb8CasesCloseParams;
    renderer: true;
    result: Kb8CaseRevisionResult;
    tool: "ui_only";
  };
  "cases.get": {
    params: Kb8CaseIdParams;
    renderer: true;
    result: Kb8CaseGetResult;
    tool: "kb_case_get";
  };
  "cases.list": {
    params: Kb8CasesListParams;
    renderer: true;
    result: Kb8CasesListResult;
    tool: "kb_case_list";
  };
  "cases.open": {
    params: Kb8CasesOpenParams;
    renderer: false;
    result: Kb8CasesOpenResult;
    tool: "kb_case_open";
  };
  "cases.signals": {
    params: Kb8CaseIdParams;
    renderer: false;
    result: Kb8CaseSignalsResult;
    tool: "kb_triage_signals";
  };
  "cases.update": {
    params: Kb8CasesUpdateParams;
    renderer: false;
    result: Kb8CaseRevisionResult;
    tool: "kb_case_update";
  };
  "cheats.adopt": {
    params: Kb8CheatsAdoptParams;
    renderer: false;
    result: Kb8CheatsAdoptResult;
    tool: "ui_only";
  };
  "cheats.categories.set": {
    params: Kb8CheatCategoriesSetParams;
    renderer: true;
    result: Kb8CheatCategoriesSetResult;
    tool: "ui_only";
  };
  "cheats.list": {
    params: EmptyParams;
    renderer: true;
    result: Kb8CheatsListResult;
    tool: "ui_only";
  };
  "cheats.unadopt": {
    params: Kb8CheatsUnadoptParams;
    renderer: false;
    result: Kb8CheatsAdoptResult;
    tool: "ui_only";
  };
  "control.click": {
    params: ControlClickParams;
    renderer: false;
    result: ControlResult;
    tool: "kb_input_click";
  };
  "control.key": {
    params: ControlKeyParams;
    renderer: false;
    result: ControlResult;
    tool: "kb_input_key";
  };
  "control.type": {
    params: ControlTypeParams;
    renderer: false;
    result: ControlResult;
    tool: "kb_input_type";
  };
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
  "evidence.pin": {
    params: Kb8EvidencePinParams;
    renderer: false;
    result: Kb8EvidencePinResult;
    tool: "kb_evidence_pin";
  };
  "explore.end": {
    params: ExploreEndParams;
    renderer: false;
    result: ExploreEndResult;
    tool: "kb_explore_end";
  };
  "explore.list": {
    params: ExploreListParams;
    renderer: true;
    result: ExploreListResult;
    tool: "ui_only";
  };
  "explore.start": {
    params: ExploreStartParams;
    renderer: false;
    result: ExploreStartResult;
    tool: "kb_explore_start";
  };
  "graph.check": {
    params: GraphCheckParams;
    renderer: false;
    result: GraphCheckResult;
    tool: "kb_graph_validate";
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
  "graph.list": {
    params: GraphListParams;
    renderer: false;
    result: GraphListResult;
    tool: "kb_graph_list";
  };
  "graph.open": {
    params: GraphOpenParams;
    renderer: true;
    result: GraphOpenResult;
    tool: "kb_graph_get";
  };
  "graph.patch": {
    params: GraphPatchParams;
    renderer: false;
    result: GraphPatchResult;
    tool: "kb_graph_patch";
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
  "job.begin": {
    params: Kb8JobBeginParams;
    renderer: false;
    result: Kb8JobBeginResult;
    tool: "ui_only";
  };
  "job.end": {
    params: Kb8JobEndParams;
    renderer: true;
    result: Kb8JobEndResult;
    tool: "ui_only";
  };
  "job.finish": {
    params: Kb8JobFinishParams;
    renderer: false;
    result: Kb8JobEndResult;
    tool: "ui_only";
  };
  "job.heartbeat": {
    params: Kb8JobIdParams;
    renderer: false;
    result: Kb8JobHeartbeatResult;
    tool: "ui_only";
  };
  "job.note": {
    params: Kb8JobNoteParams;
    renderer: false;
    result: Kb8JobNoteResult;
    tool: "kb_report_note";
  };
  "jobs.list": {
    params: EmptyParams;
    renderer: true;
    result: Kb8JobsListResult;
    tool: "ui_only";
  };
  "knowledge.apply": {
    params: Kb8KnowledgeApplyParams;
    renderer: false;
    result: Kb8KnowledgeApplyResult;
    tool: "kb_knowledge_apply";
  };
  "knowledge.get": {
    params: Kb8KnowledgeGetParams;
    renderer: true;
    result: Kb8KnowledgeGetResult;
    tool: "kb_knowledge_get";
  };
  "knowledge.search": {
    params: Kb8KnowledgeSearchParams;
    renderer: true;
    result: Kb8KnowledgeSearchResult;
    tool: "kb_knowledge_search";
  };
  "local.settings.set": {
    params: Kb8LocalSettingsSetParams;
    renderer: true;
    result: Kb8LocalSettingsSetResult;
    tool: "ui_only";
  };
  "nodes.list": {
    params: EmptyParams;
    renderer: true;
    result: NodesListResult;
    tool: "kb_node_search";
  };
  "permissions.get": {
    params: EmptyParams;
    renderer: true;
    result: PermissionsGetResult;
    tool: "kb_project_info";
  };
  "permissions.set": {
    params: PermissionsSetParams;
    renderer: true;
    result: PermissionsSetResult;
    tool: "ui_only";
  };
  "plugins.cancel": {
    params: PluginsOpIdParams;
    renderer: true;
    result: EmptyResult;
    tool: "ui_only";
  };
  "plugins.gc": {
    params: PluginsGcParams;
    renderer: true;
    result: PluginsOpResult;
    tool: "ui_only";
  };
  "plugins.install": {
    params: PluginsOpIdParams;
    renderer: true;
    result: PluginsOpResult;
    tool: "ui_only";
  };
  "plugins.list": {
    params: EmptyParams;
    renderer: true;
    result: PluginsListResult;
    tool: "kb_project_info";
  };
  "plugins.preview": {
    params: PluginsPreviewParams;
    renderer: true;
    result: PluginsPreviewResult;
    tool: "ui_only";
  };
  "plugins.relock": {
    params: PluginsRelockParams;
    renderer: true;
    result: PluginsOpResult;
    tool: "ui_only";
  };
  "plugins.remove": {
    params: PluginsRemoveParams;
    renderer: true;
    result: PluginsOpResult;
    tool: "ui_only";
  };
  "plugins.sync": {
    params: PluginsSyncParams;
    renderer: true;
    result: PluginsOpResult;
    tool: "ui_only";
  };
  "plugins.upgrade": {
    params: PluginsUpgradeParams;
    renderer: true;
    result: PluginsPreviewResult;
    tool: "ui_only";
  };
  "project.automation.set": {
    params: Kb8ConfigBlockParams;
    renderer: true;
    result: Kb8ConfigBlockResult;
    tool: "ui_only";
  };
  "project.qa_info": {
    params: EmptyParams;
    renderer: true;
    result: Kb8ProjectQaInfoResult;
    tool: "kb_project_info";
  };
  "project.setup.set": {
    params: Kb8ProjectSetupSetParams;
    renderer: true;
    result: Kb8ConfigBlockResult;
    tool: "ui_only";
  };
  "project.sources.set": {
    params: Kb8ConfigBlockParams;
    renderer: true;
    result: Kb8ConfigBlockResult;
    tool: "ui_only";
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
  "report.decide": {
    params: Kb8ReportDecideParams;
    renderer: true;
    result: Kb8ReportDecideResult;
    tool: "ui_only";
  };
  "reports.get": {
    params: Kb8JobIdParams;
    renderer: true;
    result: Kb8ReportGetResult;
    tool: "ui_only";
  };
  "reports.list": {
    params: EmptyParams;
    renderer: true;
    result: Kb8ReportsListResult;
    tool: "ui_only";
  };
  "run.artifact": {
    params: RunArtifactParams;
    renderer: false;
    result: RunArtifactResult;
    tool: "kb_run_artifact_get";
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
  "run.diff": {
    params: RunDiffParams;
    renderer: false;
    result: RunDiffResult;
    tool: "kb_run_compare";
  };
  "run.events": {
    params: RunEventsParams;
    renderer: false;
    result: RunEventsResult;
    tool: "kb_run_events";
  };
  "run.export": {
    params: RunExportParams;
    renderer: false;
    result: RunExportResult;
    tool: "ui_only";
  };
  "run.failure": {
    params: RunIdParams;
    renderer: false;
    result: RunFailureResult;
    tool: "kb_run_status";
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
  "run.search": {
    params: RunSearchParams;
    renderer: false;
    result: RunSearchResult;
    tool: "kb_log_search";
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
  "screen.read_text": {
    params: ScreenReadTextParams;
    renderer: false;
    result: TargetReadTextResult;
    tool: "kb_ocr_read";
  };
  "screens.check": {
    params: ScreensCheckParams;
    renderer: true;
    result: ScreensCheckResult;
    tool: "ui_only";
  };
  "screens.discard": {
    params: ScreensDiscardParams;
    renderer: true;
    result: ScreensDiscardResult;
    tool: "ui_only";
  };
  "screens.get": {
    params: ScreensGetParams;
    renderer: false;
    result: ScreensGetResult;
    tool: "kb_screen_get";
  };
  "screens.identify": {
    params: ScreensIdentifyParams;
    renderer: false;
    result: ScreensIdentifyResult;
    tool: "kb_screen_identify";
  };
  "screens.layout_get": {
    params: EmptyParams;
    renderer: true;
    result: ScreensLayout;
    tool: "ui_only";
  };
  "screens.layout_set": {
    params: ScreensLayoutSetParams;
    renderer: true;
    result: ScreensLayout;
    tool: "ui_only";
  };
  "screens.list": {
    params: ScreensListParams;
    renderer: false;
    result: ScreensListResult;
    tool: "kb_screen_list";
  };
  "screens.map": {
    params: EmptyParams;
    renderer: true;
    result: ScreensMapResult;
    tool: "kb_screen_list";
  };
  "screens.promote": {
    params: ScreensPromoteParams;
    renderer: true;
    result: ScreensPromoteResult;
    tool: "ui_only";
  };
  "screens.save": {
    params: ScreensSaveParams;
    renderer: false;
    result: ScreensSaveResult;
    tool: "kb_screen_save";
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
  "sources.check": {
    params: EmptyParams;
    renderer: true;
    result: Kb8SourcesCheckResult;
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
  "unknowns.answer": {
    params: Kb8UnknownsAnswerParams;
    renderer: true;
    result: Kb8UnknownsAnswerResult;
    tool: "ui_only";
  };
  "wiki.write": {
    params: Kb8WikiWriteParams;
    renderer: false;
    result: Kb8WikiWriteResult;
    tool: "kb_wiki_write";
  };
  "windows.list": {
    params: EmptyParams;
    renderer: true;
    result: WindowsListResult;
    tool: "kb_screen_capture";
  };
  "wizard.get": {
    params: EmptyParams;
    renderer: true;
    result: Kb8WizardGetResult;
    tool: "ui_only";
  };
  "wizard.set": {
    params: Kb8WizardSetParams;
    renderer: true;
    result: Kb8WizardSetResult;
    tool: "ui_only";
  };
  "working.accept": {
    params: Kb8WorkingDecideParams;
    renderer: false;
    result: Kb8WorkingDecideResult;
    tool: "ui_only";
  };
  "working.list": {
    params: EmptyParams;
    renderer: false;
    result: Kb8WorkingListResult;
    tool: "ui_only";
  };
  "working.reject": {
    params: Kb8WorkingDecideParams;
    renderer: false;
    result: Kb8WorkingDecideResult;
    tool: "ui_only";
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
 * 팔레트: 레지스트리의 플러그인마다 노드 스키마 문서 하나 (kookabug_core.palette.export). M6: plugins = 설치 플러그인 요약 (잠금이 없거나 깨졌으면 빈 목록)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "NodesListResult".
 */
export interface NodesListResult {
  plugins?: PluginInstalled[];
  /**
   * Items: 노드 스키마 문서 (node-schema 형식 kookabug.nodes/0 그대로)
   */
  schemas: {
    [k: string]: unknown | undefined;
  }[];
}
/**
 * nodes.list의 설치 플러그인 요약 (kb_node_search가 노드마다 보인다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginInstalled".
 */
export interface PluginInstalled {
  env: string;
  env_status: PluginEnvStatus;
  id: string;
  permissions: string[];
  title?: string;
  version: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionsGetResult".
 */
export interface PermissionsGetResult {
  /**
   * 계층별 파일 값 (ui 연결만. agent 연결에는 자기 판정 요약 tools만)
   */
  layers?: PermissionsLayer[];
  principal: Principal;
  /**
   * 도구별 실효 판정. agent 연결은 자기 주체, ui 연결은 사람이 지켜보는 에이전트(attended) 기준
   */
  tools: PermissionsToolDecision[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionsLayer".
 */
export interface PermissionsLayer {
  diagnostics: Diagnostic[];
  /**
   * permissions.set으로 고칠 수 있는 계층 (team은 false — kookabug.json에서 편집)
   */
  editable: boolean;
  layer: "project" | "team" | "user";
  /**
   * 그 파일의 permissions 값 그대로 (없으면 null)
   */
  permissions: null | {
    [k: string]: unknown | undefined;
  };
  /**
   * 그 파일 바이트의 sha256 (파일이 없으면 null). permissions.set의 base_revision
   */
  revision: Revision | null;
  /**
   * 파일 경로 (표시용, 정할 수 없으면 null)
   */
  source: null | string;
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
  /**
   * M8: 작업 토큰으로 묶인 연결이면 그 작업 ID (없으면 키 없음)
   */
  job?: string;
  kind: "agent" | "user";
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionsToolDecision".
 */
export interface PermissionsToolDecision {
  final: PermissionVerdict;
  layer: ("default" | "project" | "team" | "user") | null;
  mutating: boolean;
  reason: string;
  source: string;
  /**
   * 권한 표 도구 이름 (M7 kb_screen_save 포함)
   */
  tool: string;
  toolset: Toolset;
  verdict: PermissionVerdict;
}
/**
 * 권한 계층 하나의 permissions만 바꾼다. 다른 키·순서는 보존, 같은 폴더 임시 파일 → 교체. 형식이 틀린 파일은 고치지 않고 settings_invalid
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionsSetParams".
 */
export interface PermissionsSetParams {
  /**
   * 읽은 때의 파일 revision (파일이 없었으면 null). 다르면 revision_conflict
   */
  base_revision: Revision | null;
  layer: "project" | "user";
  /**
   * 새 permissions 값 (메타스키마 Permissions)
   */
  permissions: {
    [k: string]: unknown | undefined;
  };
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PermissionsSetResult".
 */
export interface PermissionsSetResult {
  revision: Revision;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsOpIdParams".
 */
export interface PluginsOpIdParams {
  op_id: PluginOpId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsGcParams".
 */
export interface PluginsGcParams {
  candidates: PluginGcCandidates;
}
/**
 * 사람이 확인 카드에서 본 후보 (plugins.list gc_candidates). 그 안의 것만 지운다 — 그 사이 생긴 후보는 남는다
 */
export interface PluginGcCandidates {
  envs: string[];
  staging: string[];
  wheels: string[];
}
/**
 * 작업을 시작했다. 진행은 plugins.progress, 끝은 plugins.done
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsOpResult".
 */
export interface PluginsOpResult {
  op_id: PluginOpId;
}
/**
 * 플러그인 목록 (M6 3.8, 읽기만). lock_sha256 = 정규 잠금 해시 — 준비(plugins.sync)에 그대로 넘긴다. trusted = 이 PC에서 신뢰 확인한 잠금
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsListResult".
 */
export interface PluginsListResult {
  busy: PluginJob | null;
  environments: {
    [k: string]: PluginEnvInfo | undefined;
  };
  gc_candidates: PluginGcCandidates1;
  lock_sha256: Revision | null;
  plugins: PluginListEntry[];
  /**
   * 잠금 파일 revision (plugins.remove의 base_revision)
   */
  revision: Revision | null;
  stale_reason: null | string;
  trusted: boolean;
}
/**
 * 이 daemon에서 진행 중인 플러그인 작업 (waiting = 미리보기가 승인을 기다림). 승인을 기다리는 미리보기의 op_id는 그 미리보기를 연 연결에만 보이고 다른 연결에는 null (승인·취소는 연 연결만)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginJob".
 */
export interface PluginJob {
  kind: PluginOpKind;
  op_id: PluginOpId | null;
  stage: null | string;
  waiting: boolean;
}
/**
 * 잠금의 환경 하나의 상태 (M6 3.8). folder = runner가 고를 폴더 이름 (검증 없이 찾은 것)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginEnvInfo".
 */
export interface PluginEnvInfo {
  /**
   * 잠금의 환경 지문 (위젯 호스트 <id>-<지문 12자>)
   */
  fingerprint?: string;
  folder: null | string;
  plugins: string[];
  status: PluginEnvStatus;
}
/**
 * gc가 지울 후보 이름 (확인 카드용 — 실제 gc는 검증한 선택으로 다시 판정하고, plugins.gc candidates로 받은 것 안에서만 지운다)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginGcCandidates".
 */
export interface PluginGcCandidates1 {
  envs: string[];
  staging: string[];
  wheels: string[];
}
/**
 * 잠금의 플러그인 항목(plugin-lock LockPlugin) + 환경 상태 + 노드 (커밋된 wheel의 스키마)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginListEntry".
 */
export interface PluginListEntry {
  conflicts?: string[];
  dist?: string;
  env: string;
  env_status: PluginEnvStatus;
  id: string;
  isolated_because?: null | string;
  /**
   * 잠금의 manifest (title·modules·permissions·min_core·isolation·ui)
   */
  manifest: {
    [k: string]: unknown | undefined;
  };
  nodes: PluginNodeInfo[];
  requires?: string[];
  schema_sha256?: string;
  /**
   * 원천 출처 (git·wheel·path — 인증 정보 없음)
   */
  source: {
    [k: string]: unknown | undefined;
  };
  ui?: PluginWidgetHost;
  version: string;
  wheel?: string;
  wheel_sha256?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginNodeInfo".
 */
export interface PluginNodeInfo {
  effects: string[];
  title?: string;
  type: string;
  /**
   * config 이름 → 위젯 ID (<플러그인>.<이름>, M6 3.10)
   */
  ui?: {
    [k: string]: string | undefined;
  };
}
/**
 * 위젯 호스트 (M6 3.10): 머리에 ui가 있고 환경이 준비된 플러그인만. kbplugin://<host>/가 path(워크스페이스 기준, 환경 안 ui 폴더) 아래 파일만 준다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginWidgetHost".
 */
export interface PluginWidgetHost {
  /**
   * <플러그인 ID('_'는 '-')>-<환경 지문 12자> (CSP 호스트 문법에 '_'가 없다)
   */
  host: string;
  /**
   * 워크스페이스 기준 '/' 경로 (.kookabug/plugins/envs/<폴더>/Lib/site-packages/<패키지>/<ui>)
   */
  path: string;
  widgets: string[];
}
/**
 * 원천: git+<url>[@ref] · *.whl 경로·https URL(sha256 필수) · 폴더. 받고 정적으로 읽기만 한다 (코드 실행 없음)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsPreviewParams".
 */
export interface PluginsPreviewParams {
  isolation?: PluginIsolation;
  ref?: string;
  sha256?: string;
  source: string;
}
/**
 * 신뢰 확인 재료 (설치 거래 ①②). expires_in_s 안에 plugins.install {op_id}로 승인, plugins.cancel로 취소. untrusted = 이 PC에서 신뢰 확인하지 않은 잠금이면 함께 신뢰할 기존 플러그인 ID 전체
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsPreviewResult".
 */
export interface PluginsPreviewResult {
  dependencies: string[];
  dist: string;
  expires_in_s: number;
  id: string;
  isolation: PluginIsolation;
  op_id: PluginOpId;
  permissions: string[];
  /**
   * upgrade면 바꾸는 판
   */
  replaces: null | string;
  /**
   * 원천 출처 (인증 정보 없음)
   */
  source: {
    [k: string]: unknown | undefined;
  };
  title: null | string;
  untrusted: string[];
  version: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsRelockParams".
 */
export interface PluginsRelockParams {
  lock_sha256: Revision1;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsRemoveParams".
 */
export interface PluginsRemoveParams {
  /**
   * 확인할 때 본 잠금 revision (plugins.list). null = 확인할 때 잠금이 없었다 (비교 생략이 아님). 거래 안에서 읽은 잠금과 null까지 비교해 다르면 revision_conflict
   */
  base_revision: Revision | null;
  id: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsSyncParams".
 */
export interface PluginsSyncParams {
  lock_sha256: Revision2;
}
/**
 * 잠금의 원천을 다시 받아 미리보기 (plugins.preview와 같은 흐름 — plugins.install {op_id}로 승인)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsUpgradeParams".
 */
export interface PluginsUpgradeParams {
  id: string;
  isolation?: PluginIsolation;
  ref?: string;
  sha256?: string;
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
 * run.artifact (kb_run_artifact_get, M5 3.8): 실행 폴더의 증거 파일 하나 (steps/·thumbs/ 아래 그 스텝의 증거, video/index.json). 비밀값 스텝(안쪽 포함)·agent_withhold 증거는 secret_step, 분류 없는 기록은 unclassified_run, 영상 조각은 video_not_served. max_side는 이미지 긴 변 상한(≤1568), as_frame이면 정지 화면으로
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunArtifactParams".
 */
export interface RunArtifactParams {
  as_frame?: boolean;
  max_side?: number;
  path: string;
  run_id: RunId;
}
/**
 * kind image: 줄인 PNG를 .kookabug/cache/agent/<cache>에 썼다 (긴 변 ≤1568, ≤1 MiB — 읽은 쪽이 지운다). kind text: 글자 (256 KiB에서 자름). kind frame: 정지 화면 frame_id
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunArtifactResult".
 */
export interface RunArtifactResult {
  bytes?: number;
  cache?: string;
  frame_id?: string;
  height?: number;
  kind: "frame" | "image" | "text";
  path: string;
  text?: string;
  truncated?: boolean;
  width?: number;
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
 * run.diff (kb_run_compare, M5): run.compare와 같은 비교를 두 실행에 3.8(비밀값 분류)을 적용해 준다. baseline을 빼면 지난 성공
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunDiffParams".
 */
export interface RunDiffParams {
  baseline?: RunId;
  run_id: RunId;
}
/**
 * run.compare 결과(CompareResult)와 같은 모양 + classified. 비밀값 스텝·분류 없는 기록의 화면 파일은 null이고 reason이 secret_step·agent_withheld
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunDiffResult".
 */
export interface RunDiffResult {
  [k: string]: unknown | undefined;
}
/**
 * run.events (kb_run_events, M5 3.8): after_seq 뒤 이벤트 (secret_paths 자리는 ***, 분류 없는 기록은 안전 필드만). step·kinds로 거른다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunEventsParams".
 */
export interface RunEventsParams {
  after_seq?: number;
  kinds?: string[];
  limit?: number;
  run_id: RunId;
  step?: StepId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunEventsResult".
 */
export interface RunEventsResult {
  classified: boolean;
  events: {
    [k: string]: unknown | undefined;
  }[];
  next_seq: number;
  truncated: boolean;
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
 * run.failure (kb_run_status, M5): 실패 요약 — 판정·실패 위치(스텝·노드·출구·오류)·증거 파일(에이전트에게 줄 수 있는 것만)·영상 요약·지난 성공. 사유·메시지는 3.8대로 가린다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunFailureResult".
 */
export interface RunFailureResult {
  chain: {
    [k: string]: unknown | undefined;
  }[];
  classified: boolean;
  code?: null | string;
  evidence: string[];
  failure: null | {
    [k: string]: unknown | undefined;
  };
  failure_path?: string[] | null;
  failure_step?: null | string;
  last_success: RunId | null;
  reason?: string;
  run_id: RunId;
  state: "ended" | "running";
  verdict?: null | string;
  video?: null | {
    [k: string]: unknown | undefined;
  };
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
  /**
   * 배지 "에이전트 제어": source agent_control 실행 (M5 3.9, run.json에서)
   */
  source?: "agent_control";
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
 * run.search (kb_log_search, M5): 가린 뒤의 메시지·오류·사유에서 글자 찾기 (대소문자 무시). runs를 빼면 최근 20개, 분류 없는 기록은 건너뛴다(skipped)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSearchParams".
 */
export interface RunSearchParams {
  limit?: number;
  query: string;
  runs?: RunId[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSearchResult".
 */
export interface RunSearchResult {
  matches: {
    kind: null | string;
    run: RunId;
    seq: number | null;
    step: null | string;
    text: string;
  }[];
  skipped: string[];
  truncated: boolean;
}
/**
 * 디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy. 이 daemon의 녹화 세션이 starting·recording·paused면 runner를 띄우기 전에 recording_active (M4, 같은 시작 잠금 안에서 판정)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStartParams".
 */
export interface RunStartParams {
  /**
   * M8 3.6 실행 기준: team(팀 파일만) | working(시작 때 작업 기준 덧씌움 고정). 생략하면 작업 연결은 working, 그 밖은 team
   */
  basis?: "team" | "working";
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
 * screen.read_text (kb_ocr_read, M5): 정지 화면(창 캡처) 영역의 글자. rect를 빼면 전체. 녹화 세션 프레임은 recorder_frame, sensitive target이 보이는 영역과 겹치면 sensitive_region
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreenReadTextParams".
 */
export interface ScreenReadTextParams {
  frame_id: string;
  rect?: Rect;
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
 * screens.check (사람만, M7 3.7): 후보 하나를 승격하기 전에 확인 (쓰지 않음). 승격과 같은 mode·id·folder·replace_*를 주면 그 승격이 고칠 파일의 revision을 준다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensCheckParams".
 */
export interface ScreensCheckParams {
  folder?: string;
  id?: string;
  key: string;
  mode?: "merge" | "new";
  replace_detect?: boolean;
  replace_shot?: boolean;
  session: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensCheckResult".
 */
export interface ScreensCheckResult {
  /**
   * 승격할 수 없을 때 그 이유의 오류 코드 (screen_exists·validation_failed·not_found·exists)
   */
  code?: string;
  /**
   * 승격될 화면 ID (new는 새 ID, merge는 합칠 화면)
   */
  id?: string;
  /**
   * 후보 판정 조건이 자기 스크린샷에서 맞고 승격을 막는 것이 없다
   */
  ok: boolean;
  /**
   * 승격 뒤 화면 파일 (워크스페이스 기준)
   */
  path?: string;
  /**
   * 승격을 막는 것 (있으면 ok는 false)
   */
  problems: string[];
  /**
   * 승격이 고칠 파일 → 지금 revision (없는 파일은 null). screens.promote의 base_revisions로 그대로 넘긴다
   */
  revisions: {
    [k: string]: null | string | undefined;
  };
  /**
   * 후보 판정 조건을 그 대표 스크린샷에서 평가한 결과 (matched·not_matched·unknown·none = 스크린샷 없음)
   */
  shot?: "matched" | "none" | "not_matched" | "unknown";
  warnings: string[];
}
/**
 * screens.discard (사람만, M7 3.7): 끝난 탐색 세션의 후보 하나(key) 또는 세션 전체를 지운다. 처리기는 B4
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensDiscardParams".
 */
export interface ScreensDiscardParams {
  key?: string;
  session: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensDiscardResult".
 */
export interface ScreensDiscardResult {
  /**
   * 지운 파일 (워크스페이스 기준)
   */
  removed: string[];
}
/**
 * screens.get (kb_screen_get, M5): screens/ 아래 *.screen.json 하나
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensGetParams".
 */
export interface ScreensGetParams {
  path: WorkspacePath;
}
/**
 * 읽을 수 없거나 형식이 틀리면 problem
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensGetResult".
 */
export interface ScreensGetResult {
  path: WorkspacePath;
  problem?: string;
  value?: unknown;
}
/**
 * screens.identify (kb_screen_identify, M7 3.6): 정지 화면이 어느 화면인지 (확정 화면 + 자기 탐색 세션 후보)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensIdentifyParams".
 */
export interface ScreensIdentifyParams {
  frame_id: string;
}
/**
 * matches 맞는 화면, unknown 확인하지 못한 조건이 남은 화면(보호 프레임의 OCR 조건 등). 읽은 글자는 넣지 않는다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensIdentifyResult".
 */
export interface ScreensIdentifyResult {
  checked: number;
  matches: ScreensIdentifyMatch[];
  problems: {
    node: string;
    problem: string;
  }[];
  unknown: ScreensIdentifyMatch[];
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensIdentifyMatch".
 */
export interface ScreensIdentifyMatch {
  id?: string;
  key?: string;
  node: string;
  state: "confirmed" | "explored";
  title: string | null;
}
/**
 * screens.layout_get/set (사람만, M7 3.8): 화면 지도 카드 배치 .kookabug/screen-map.json. 처리기는 B5
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensLayout".
 */
export interface ScreensLayout {
  /**
   * 화면 ID·후보 → 카드 자리
   */
  layout: {
    [k: string]: unknown | undefined;
  };
  revision: null | string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensLayoutSetParams".
 */
export interface ScreensLayoutSetParams {
  base_revision: null | string;
  layout: {
    [k: string]: unknown | undefined;
  };
}
/**
 * screens.list (kb_screen_list, M5): under(screens/ 기준 또는 워크스페이스 기준 폴더) 아래 화면 지도
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensListParams".
 */
export interface ScreensListParams {
  under?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensListResult".
 */
export interface ScreensListResult {
  screens: {
    explored?: true;
    id: string;
    path: WorkspacePath;
    problem?: string;
    title?: string;
  }[];
}
/**
 * screens.map (kb_screen_list, M7 3.3): 화면 지도 카드·이동 그래프·탐색 세션
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensMapResult".
 */
export interface ScreensMapResult {
  edges: ScreenMapEdge[];
  /**
   * M7 B5: 카드로 그리지 않는 합치기 후보(of) — 확정 카드의 "탐색 추가 N"과 "확인 전" 묶음
   */
  merges?: ScreenMapMerge[];
  revision: string;
  screens: ScreenMapCard[];
  sessions: ExploreSessionInfo[];
  /**
   * 배치 시작 화면 (들어오는 tried 간선이 없는 확정 화면 중 첫째)
   */
  start: null | string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreenMapEdge".
 */
export interface ScreenMapEdge {
  from: string;
  label: string;
  note?: string;
  /**
   * 확인 전 간선 (of 후보의 이동)
   */
  pending?: boolean;
  sources: {
    [k: string]: unknown | undefined;
  }[];
  status: "tried" | "untried";
  to: null | string;
  /**
   * to를 찾지 못한 이름 (to는 null)
   */
  unresolved?: string;
  via: {
    [k: string]: unknown | undefined;
  };
}
export interface ScreenMapMerge {
  counts: {
    elements: number;
    moves: number;
  };
  key: string;
  node: string;
  of: string;
  path: string;
  session: string;
  title: null | string;
}
/**
 * 화면 지도 카드: 확정 화면(node = ID) 또는 탐색 후보(node = x:<세션>/<키>)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreenMapCard".
 */
export interface ScreenMapCard {
  counts: {
    elements: number;
    moves: number;
  };
  /**
   * M7 B5: 화면 설명 (사이드바 선택 섹션)
   */
  description?: string;
  /**
   * 판정 조건 한 줄 (image("이름") && !image("이름") && text("글자"))
   */
  detect_text: string;
  elements: {
    kind: string;
    name: string;
    /**
     * @minItems 4
     * @maxItems 4
     */
    rect: [number, number, number, number];
  }[];
  /**
   * 확정 카드: 이 화면에 합칠 탐색 후보(of) 수 — "탐색 추가 N" 배지
   */
  explored_adds?: number;
  id?: string;
  /**
   * 후보: 판정 조건도 합칠 화면도 없음 (승격 불가, 사람이 채운다)
   */
  incomplete?: boolean;
  key?: string;
  kind: "popup" | "screen";
  node: string;
  of?: null | string;
  origin: null | {
    [k: string]: unknown | undefined;
  };
  path: string;
  problem: null | string;
  promotable?: boolean;
  session?: string;
  state: "confirmed" | "explored";
  /**
   * 대표 스크린샷 썸네일 캐시 이름 (사람 연결만 — 에이전트는 늘 null)
   */
  thumb: null | string;
  title: null | string;
}
/**
 * screens.promote (사람만, M7 3.7): 후보를 확정 화면으로 옮기거나(new) 기존 화면에 합친다(merge). screens.lock 안 저널 거래. 처리기는 B4
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensPromoteParams".
 */
export interface ScreensPromoteParams {
  /**
   * screens.check가 준 revisions 그대로. 하나라도 다르면 revision_conflict
   */
  base_revisions: {
    [k: string]: null | string | undefined;
  };
  description?: string;
  folder?: string;
  id?: string;
  key: string;
  mode: "merge" | "new";
  replace_detect?: boolean;
  replace_shot?: boolean;
  session: string;
  title?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensPromoteResult".
 */
export interface ScreensPromoteResult {
  /**
   * 커밋은 됐고 마무리(후보 지우기·explore.json)가 남았다 — 다음 잠금 때 끝낸다
   */
  cleanup_pending: boolean;
  id: string;
  /**
   * 승격된 화면 파일 (워크스페이스 기준)
   */
  path: string;
  warnings: string[];
}
/**
 * screens.save (kb_screen_save, M7 3.5): 자기 탐색 세션 폴더의 후보 카드 하나를 저장·갱신. 글자 필드는 비밀값 검사(3.5b)를 지난다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensSaveParams".
 */
export interface ScreensSaveParams {
  description?: string;
  detect?: {
    all?: ScreensSaveCondition[];
    none?: ScreensSaveCondition[];
  };
  elements?: {
    kind: "button" | "field" | "list" | "text";
    name: string;
    rect: Rect;
  }[];
  frame_id: string;
  key: string;
  kind?: "popup" | "screen";
  moves?: {
    note?: string;
    status: "tried" | "untried";
    to?: string | null;
    via: ScreensSaveVia;
  }[];
  of?: string;
  title?: string;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensSaveResult".
 */
export interface ScreensSaveResult {
  also_matches: {
    node: string;
    title: string | null;
  }[];
  incomplete?: true;
  key: string;
  path: WorkspacePath;
  /**
   * shot omitted의 보호 사유
   */
  reason?: string;
  revision: string;
  shot: "omitted" | "saved";
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
 * 새 파일이면 base_revision null(파일이 있으면 exists), 기존 파일이면 target.open의 revision (M2 계획 2.9 저장 단계). crop이 없으면 이미지를 새로 만들지 않고 지금 image·recorded를 그대로 둔 채 JSON만 저장한다(기존 파일만, 검색 범위는 recorded.client_size 기준)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetSaveParams".
 */
export interface TargetSaveParams {
  base_revision: TargetRevision | null;
  crop?: CropRef | RunCropRef;
  path: WorkspacePath;
  spec: {
    [k: string]: unknown | undefined;
  };
}
/**
 * 실행 증거 이미지에서 자른 영역 (kb_target_create의 {run, file} 출처, M5). 에이전트용 비밀값 분류를 지난 이미지만 (아니면 secret_step·unclassified_run·not_evidence)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunCropRef".
 */
export interface RunCropRef {
  /**
   * 실행 폴더 기준 경로 ('/')
   */
  file: string;
  rect: Rect;
  run_id: RunId;
}
/**
 * preview = 저장한 파일을 다시 읽어 crop의 정지 화면에서 찾은 결과 (바로 매칭). crop 없이 저장했으면 찾을 정지 화면이 없어 null
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetSaveResult".
 */
export interface TargetSaveResult {
  /**
   * M8 E3: 작업 기준으로 썼으면 working (팀 파일은 그대로)
   */
  basis?: "working";
  /**
   * M8 E3: 쓴 작업 기준 변경 ID
   */
  change?: string;
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
   * AGENTS.md의 Kookabug 관리 구간 (없으면 null, M5 3.12)
   */
  agents_md?: null | string;
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
  "agent.connections.changed": {
    params: AgentConnectionsChangedParams;
  };
  "agent.protect_corrupt": {
    params: AgentProtectCorruptParams;
  };
  "approval.requested": {
    params: ApprovalRequest;
  };
  "approval.resolved": {
    params: ApprovalResolvedParams;
  };
  "debug.breakpoints.changed": {
    params: BreakpointsResult;
  };
  "explore.changed": {
    params: ExploreChangedParams;
  };
  "graph.changed": {
    params: GraphChangedParams;
  };
  "job.budget": {
    params: Kb8JobBudgetParams;
  };
  "job.changed": {
    params: Kb8JobChangedParams;
  };
  "knowledge.changed": {
    params: Kb8KnowledgeChangedParams;
  };
  "lease.changed": {
    params: LeaseChangedParams;
  };
  "plugins.changed": {
    params: PluginsChangedParams;
  };
  "plugins.done": {
    params: PluginsDoneParams;
  };
  "plugins.progress": {
    params: PluginsProgressParams;
  };
  "recorder.changed": {
    params: RecorderChangedParams;
  };
  "reports.changed": {
    params: EmptyParams;
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
  "screens.changed": {
    params: ScreensChangedParams;
  };
  "workspace.changed": {
    params: WorkspaceChangedParams;
  };
}
/**
 * kookabug.lock이 바뀌었다 (daemon 작업이든 밖에서든). daemon은 레지스트리를 다시 만들었다 — nodes.list·검증을 다시 부른다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsChangedParams".
 */
export interface PluginsChangedParams {
  /**
   * 잠금 파일 바이트 sha256 (없어졌으면 null)
   */
  revision: Revision | null;
}
/**
 * 플러그인 작업이 끝났다 (ui 연결에만). ok가 거짓이면 error, 참이면 result (작업별 결과)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsDoneParams".
 */
export interface PluginsDoneParams {
  error?: PluginErrorInfo;
  kind: PluginOpKind;
  ok: boolean;
  op_id: PluginOpId;
  result?: {
    [k: string]: unknown | undefined;
  };
}
/**
 * 플러그인 작업 진행 (ui 연결에만). stage = 거래 단계 (kookabug_core.plugins.STAGES)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "PluginsProgressParams".
 */
export interface PluginsProgressParams {
  message: string;
  op_id: PluginOpId;
  stage: string;
}
/**
 * recorder.changed: 녹화 상태·스텝이 바뀜. 소유 연결에는 rev·counts·warnings도 (스텝 목록은 rev로 recorder.steps를 다시 부른다), 다른 연결에는 state만. 글자는 싣지 않는다. session은 그 알림의 녹화 세션(idle이면 없음) — 받는 쪽은 아는 지금 세션과 다른 알림으로 상태를 바꾸지 않는다 (M5 SECFIX)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RecorderChangedParams".
 */
export interface RecorderChangedParams {
  counts?: RecorderCounts;
  rev?: number;
  session?: RecorderSessionId;
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
 * M7: screens/ 아래 화면 지도 파일이 바뀜 (ui 연결에만). 화면 지도 탭은 screens.map을 다시 부른다
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "ScreensChangedParams".
 */
export interface ScreensChangedParams {
  revision: string;
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
