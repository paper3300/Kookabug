/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 감독자 ↔ runner, runner ↔ 워커 사이 JSON-RPC 2.0 메시지 하나 (named pipe 프레임 본문, UTF-8 JSON). 메서드별 params·result는 쓰는 작업에서 $defs에 더한다
 */
export type RpcMessage = Request | Notification | SuccessResponse | ErrorResponse;
/**
 * 보낸 쪽이 1부터 붙이는 요청 번호. 응답은 같은 번호로 짝짓는다 (양쪽이 따로 센다)
 */
export type RequestId = number;
export type JsonRpcVersion = "2.0";
/**
 * 점으로 나눈 소문자 이름 (예: node.invoke, run.cancel)
 */
export type MethodName = string;
/**
 * 표준: -32700 parse_error, -32600 invalid_request, -32601 method_not_found, -32602 invalid_params, -32603 internal_error. Kookabug: -32001 cancelled, -32002 node_error, -32003 context_violation, -32004 node_contract, -32005 protocol_version
 */
export type ErrorCode =
  -32700 | -32600 | -32601 | -32602 | -32603 | -32001 | -32002 | -32003 | -32004 | -32005;

/**
 * 응답을 기다리는 요청
 */
export interface Request {
  id: RequestId;
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
/**
 * 이름 있는 인자만 쓴다 (배열 params는 쓰지 않는다)
 */
export interface Params {
  [k: string]: unknown | undefined;
}
/**
 * 응답이 없는 알림 (예: 취소)
 */
export interface Notification {
  jsonrpc: JsonRpcVersion;
  method: MethodName;
  params?: Params;
}
export interface SuccessResponse {
  id: RequestId;
  jsonrpc: JsonRpcVersion;
  /**
   * 메서드별 결과 (JSON 값)
   */
  result: unknown;
}
export interface ErrorResponse {
  error: ErrorObject;
  /**
   * 요청을 읽지 못했으면(JSON 아님·id 없음) null
   */
  id: RequestId | null;
  jsonrpc: JsonRpcVersion;
}
export interface ErrorObject {
  code: ErrorCode;
  /**
   * 오류별 추가 정보 (node_error: 예외 이름·메시지·traceback)
   */
  data?: unknown;
  message: string;
}
