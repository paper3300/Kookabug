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
 * -32100 request_failed의 종류 (M2 계획 2.4 오류 표). 캡처·창 오류는 M1 플랫폼 코드 그대로
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RequestFailedCode".
 */
export type RequestFailedCode =
  | "approval_required"
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
  | "ocr_model_corrupt"
  | "ocr_model_missing"
  | "path_outside_workspace"
  | "permission_denied"
  | "platform_unavailable"
  | "point_obscured"
  | "private_path"
  | "protocol_mismatch"
  | "revision_conflict"
  | "run_active"
  | "run_busy"
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
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * target revision: sha256(JSON 바이트) + ':' + sha256(image가 가리키는 파일 바이트). 이미지가 없으면 'missing' (M2 계획 2.9)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "TargetRevision".
 */
export type TargetRevision = string;
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
 * 권한 판정에 쓰는 도구 이름 (구현 계획 7장). ui_only는 판정하지 않는 메서드 (agent 연결이면 daemon.shutdown만 거부)
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
 * error.data (code -32100). 종류별 추가 필드: unauthenticated·protocol_mismatch → protocol, not_found·path_outside_workspace·private_path → path, invalid_json → message·line·column(위치를 모르면 null), doc_not_open·revision_conflict·exists → revision(지금 디스크, 없으면 null), idempotency_conflict·run_busy·run_active·run_not_found → run_id, validation_failed·frame_expired·target_invalid → diagnostics, permission_denied·approval_required → decision, io_error·shutting_down → message
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
  path?: string;
  protocol?: number;
  revision?: string | null;
  run_id?: RunId;
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
 * 입력 임대권 소유자 (없으면 null)
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "LeaseChangedParams".
 */
export interface LeaseChangedParams {
  owner: {
    [k: string]: unknown | undefined;
  } | null;
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
  "run.cancel": {
    params: RunIdParams;
    renderer: true;
    result: EmptyResult;
    tool: "kb_run_cancel";
  };
  "run.list": {
    params: RunListParams;
    renderer: true;
    result: RunListResult;
    tool: "kb_run_status";
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
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunIdParams".
 */
export interface RunIdParams {
  run_id: RunId;
}
/**
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunListParams".
 */
export interface RunListParams {
  limit?: number;
}
/**
 * 최근 실행부터
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunListResult".
 */
export interface RunListResult {
  runs: RunSummary[];
}
/**
 * 실행 요약 (record.reader.read_run). outcome은 끝난 실행만
 *
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunSummary".
 */
export interface RunSummary {
  graph: WorkspacePath;
  last_seq: number;
  outcome: RunOutcome | null;
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
 * 디스크 파일로 실행 (M2 계획 2.8 시작 순서). 진행 중인 실행이 있으면 run_busy
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
 * This interface was referenced by `DaemonRpcMessageDefs`'s JSON-Schema
 * via the `definition` "RunStartResult".
 */
export interface RunStartResult {
  graph: WorkspacePath;
  run_dir: string;
  run_id: RunId;
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
  search: number[];
  search_rect_px: Rect;
  seq: RequestSeq;
  threshold: number;
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
  diagnostics: Diagnostic[];
  plugins: PluginSummary[];
  profiles: string[];
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
  "graph.changed": {
    params: GraphChangedParams;
  };
  "lease.changed": {
    params: LeaseChangedParams;
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
