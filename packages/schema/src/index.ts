// 메타스키마에서 생성한 타입. 같은 이름($defs)이 여러 파일에 있어 파일 종류별 이름공간으로 낸다
export * as breakpoints from "./generated/breakpoints.js";
export * as daemonRpc from "./generated/daemon-rpc.js";
export * as events from "./generated/events.js";
export * as explore from "./generated/explore.js";
export * as graph from "./generated/graph.js";
export * as local from "./generated/local.js";
export * as nodeSchema from "./generated/node-schema.js";
export * as pluginLock from "./generated/plugin-lock.js";
export * as recorderFragment from "./generated/recorder-fragment.js";
export * as recorderHook from "./generated/recorder-hook.js";
export * as recorderScript from "./generated/recorder-script.js";
export * as rpc from "./generated/rpc.js";
export * as run from "./generated/run.js";
export * as runIndex from "./generated/run-index.js";
export * as screen from "./generated/screen.js";
export * as session from "./generated/session.js";
export * as target from "./generated/target.js";
export * as userSettings from "./generated/user-settings.js";
export * as videoIndex from "./generated/video-index.js";
export * as workspace from "./generated/workspace.js";
export { DEFAULT_COLOR_TOLERANCE, DEFAULT_MATCH_THRESHOLD } from "./generated/constants.js";

// daemon 전송 코덱과 런타임 검사 (M2 계획 2.6·2.10)
export { WireValueError, wireStringify } from "./wire.js";
export {
  MAX_DEPTH,
  METHODS,
  NOTIFICATIONS,
  checkDef,
  checkMessage,
  checkNotification,
  checkParams,
  checkResult,
  isMethodName,
  isNotificationName,
} from "./rpcCheck.js";
export type {
  MethodInfo,
  MethodName,
  NotificationName,
  NotificationParamsOf,
  ParamsOf,
  ResultOf,
  SchemaIssue,
} from "./rpcCheck.js";
