/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * 가짜 녹화 각본 JSONL의 한 줄 (검사·E2E 공용, M4 계획 2.15). 첫 줄은 header, 나머지는 시각 차례. 가짜 훅 원천(FakeHookSource)·가짜 프레임 원천(FakeFrameSource)·가짜 사람(FakeHuman)이 같은 각본을 읽는다: 입력·관측 상태·IME·기하 시간표·장면 신호·프레임 도착·훅 고장
 */
export type RecorderScriptLine =
  | HeaderLine
  | InputLine
  | ObserveLine
  | ImeLine
  | GeometryLine
  | SceneLine
  | FrameLine
  | FaultLine
  | MarkLine;
/**
 * [x, y] 물리 픽셀
 *
 * @minItems 2
 * @maxItems 2
 */
export type Point = [number, number];
/**
 * [w, h] 물리 픽셀
 *
 * @minItems 2
 * @maxItems 2
 */
export type Size = [number, number];
/**
 * [x, y, w, h] 물리 픽셀
 *
 * @minItems 4
 * @maxItems 4
 */
export type Rect = [number, number, number, number];
/**
 * 녹화 기준 시각부터 잰 단조 시계 ns (recorder-hook MonoNs와 같다)
 */
export type MonoNs = number;

/**
 * 각본 첫 줄: 대상 창(제목·처음 기하)과 처음 장면
 */
export interface HeaderLine {
  format: "kookabug.recorder-script/0";
  geometry: Geometry;
  kind: "header";
  scene: string;
  title: string;
}
/**
 * 대상 창 기하 (물리 화면 좌표). frame_bounds = DWM 프레임 경계(WGC 버퍼 크기), client_origin = 클라이언트 (0,0)의 화면 점
 */
export interface Geometry {
  client_origin: Point;
  client_size: Size;
  dpi: number;
  frame_bounds: Rect;
}
/**
 * t_ns에 들어온 원시 입력 하나. 가짜 훅 원천이 훅 프로세스 규칙(event_id·우리 표식 제외·crit_seq·이동 합치기·묶음)을 그대로 적용하고, 가짜 사람(FakeHuman)이 같은 시각에 가짜 게임 장면에 적용한다
 */
export interface InputLine {
  input: RawInput;
  kind: "input";
  t_ns: MonoNs;
}
/**
 * 번호(event_id·crit_seq)·시각을 매기기 전 원시 입력 = recorder-hook HookEvent에서 event_id·crit_seq·t_ns를 뺀 모양. 종류별 필드 규칙은 HookEvent와 같은 BadInputShape를 쓴다 (두 정의의 수용 여부가 같은지는 계약 검사가 본다). x·y는 물리 화면 좌표
 */
export interface RawInput {
  button?: "left" | "middle" | "right" | "x1" | "x2";
  delta?: number;
  extended?: boolean;
  extra_info: import("./recorder-hook.js").ExtraInfo;
  horizontal?: boolean;
  injected: boolean;
  injected_lower_il: boolean;
  kind: "key_down" | "key_up" | "mouse_down" | "mouse_move" | "mouse_up" | "wheel";
  scan?: number;
  vk?: number;
  x?: number;
  y?: number;
}
/**
 * t_ns부터 관측 스레드가 보는 창 상태. fg·point: 대상 창(target)·우리 앱(app)·대상의 소유 팝업(popup)·다른 창(other), null이면 읽지 못함. delay_ms = 이벤트 뒤 즉시 관측까지 걸리는 시간 (50 ms를 넘으면 그 이벤트는 판정 불가)
 */
export interface ObserveLine {
  delay_ms?: number;
  fg?: "app" | "other" | "popup" | "target" | null;
  focus_password?: boolean | null;
  hkl?: import("./recorder-hook.js").Hkl | null;
  kind: "observe";
  point?: "app" | "other" | "popup" | "target" | null;
  t_ns: MonoNs;
}
/**
 * t_ns부터 대상의 IME 상태와 조회 응답. status가 ok가 아니면 그동안의 표본 조회가 그 상태로 끝난다 (respond_ms 뒤)
 */
export interface ImeLine {
  kind: "ime";
  mode: "alphanumeric" | "native";
  /**
   * 표본 조회가 끝나는 데 걸리는 시간 (기본 0, timeout이면 50)
   */
  respond_ms?: number;
  status?: "failed" | "no_ime" | "ok" | "timeout";
  t_ns: MonoNs;
}
/**
 * 대상 창 기하가 t_ns에 실제로 바뀌고, 가짜 원천은 notify_ns에 알게 된다 (늦은 알림 경합). notify_ns를 빼면 t_ns
 */
export interface GeometryLine {
  geometry: Geometry;
  kind: "geometry";
  notify_ns?: MonoNs;
  t_ns: MonoNs;
}
/**
 * 게임이 스스로 장면을 바꾼다 (입력 없이, 예: 로딩 뒤 로비). 입력으로 바뀌는 장면은 가짜 사람이 장면 규칙으로 바꾼다
 */
export interface SceneLine {
  kind: "scene";
  scene: string;
  t_ns: MonoNs;
}
/**
 * 프레임 도착을 정해 둔다 (없으면 가짜 원천이 장면이 바뀔 때마다 낸다). buffer_size를 주면 그 크기 버퍼(기하와 다르면 검증 안 된 프레임)
 */
export interface FrameLine {
  arrival_ns: MonoNs;
  buffer_size?: Size;
  kind: "frame";
}
/**
 * 가짜 훅 고장: hook_exit(훅 프로세스 종료·파이프 EOF), health_stop(hook.health가 끊김), hook_detached(OS가 훅을 뗌 — 입력은 계속 오지만 훅 이벤트가 없음), overflow(중요 큐가 차서 다음 중요 이벤트 count개를 버림), batch_gap(다음 묶음 하나를 보내지 않음)
 */
export interface FaultLine {
  count?: number;
  fault: "batch_gap" | "health_stop" | "hook_detached" | "hook_exit" | "overflow";
  kind: "fault";
  t_ns: MonoNs;
}
/**
 * 검사가 가리키는 표지 (동작 없음)
 */
export interface MarkLine {
  kind: "mark";
  label: string;
  t_ns: MonoNs;
}
