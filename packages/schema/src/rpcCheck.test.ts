import { expect, test } from "vitest";
import {
  METHODS,
  NOTIFICATIONS,
  checkDef,
  checkMessage,
  checkNotification,
  checkParams,
  checkResult,
} from "./rpcCheck.js";

const REVISION = "a".repeat(64);

test("test_method_table_tools_and_internal_methods", () => {
  // M2 계획 2.5 권한 표, 2.10 렌더러 표면에서 빼는 내부 메서드
  expect(METHODS["graph.save"]).toEqual({
    params: "GraphSaveParams",
    result: "GraphSaveResult",
    tool: "kb_graph_patch",
    renderer: true,
  });
  expect(METHODS["run.subscribe"].tool).toBe("kb_run_events");
  const internal = Object.entries(METHODS)
    .filter(([, info]) => !info.renderer)
    .map(([name]) => name);
  // M3: run.export의 dest는 주 프로세스 저장 대화 상자가 정한다
  expect(internal.sort()).toEqual(["daemon.shutdown", "run.export", "session.hello"]);
  expect(Object.keys(NOTIFICATIONS).sort()).toEqual([
    "debug.breakpoints.changed",
    "graph.changed",
    "lease.changed",
    "run.ended",
    "run.event",
    "run.lagged",
    "workspace.changed",
  ]);
});

test("test_params_checked_against_method_schema", () => {
  const value = { format: "kookabug.graph/0" };
  expect(checkParams("graph.save", { doc_id: "d1", value, base_revision: REVISION })).toEqual([]);
  expect(checkParams("graph.save", { doc_id: "d1", value, base_revision: "x" })).toEqual([
    { pointer: "/base_revision", message: "형식에 맞지 않는다 (규칙 ^[0-9a-f]{64}$)" },
  ]);
  const extra = checkParams("graph.open", { path: "tests/a.graph.json", evil: 1 });
  expect(extra).toEqual([{ pointer: "/evil", message: "알 수 없는 필드 'evil'" }]);
  expect(checkParams("graph.open", {})).toHaveLength(1);
  expect(checkParams("workspace.info", undefined)).toEqual([]);
  expect(checkParams("nope.method", {})[0]!.message).toContain("모르는 메서드");
  // NaN은 어느 자리에서도 JSON 숫자가 아니다
  expect(checkParams("run.list", { limit: Number.NaN })).toHaveLength(1);
});

test("test_preview_template_crop_or_image", () => {
  const base = { frame_id: "f1", seq: 3, spec: {} };
  const crop = { crop: { frame_id: "f1", rect: [0, 0, 10, 10] } };
  expect(checkParams("target.preview", { ...base, template: crop })).toEqual([]);
  expect(checkParams("target.preview", { ...base, template: { image: "a.png" } })).toEqual([]);
  expect(
    checkParams("target.preview", { ...base, template: { ...crop, image: "a.png" } }).length,
  ).toBeGreaterThan(0);
  // target.save의 base_revision은 필수(새 파일이면 null)
  const save = { path: "targets/a.target.json", spec: {}, crop: crop.crop };
  expect(checkParams("target.save", save)).toHaveLength(1);
  expect(checkParams("target.save", { ...save, base_revision: null })).toEqual([]);
  expect(checkParams("target.save", { ...save, base_revision: `${REVISION}:missing` })).toEqual(
    [],
  );
  // crop은 선택: 없으면 지금 이미지 그대로 JSON만 저장
  const noCrop = { path: save.path, spec: save.spec };
  expect(checkParams("target.save", { ...noCrop, base_revision: `${REVISION}:missing` })).toEqual(
    [],
  );
});

const STEP_END = {
  event: "step.end",
  run: "abcd1234",
  seq: 7,
  t: "2026-10-29T06:02:11.104Z",
  attempt: 1,
  duration_ms: 12,
  exit: "done",
  outputs: { text: "x", big: 1e20 },
  status: "success",
  step: "s2",
};

test("test_notifications_and_envelope", () => {
  const event = { run_id: "abcd1234", seq: 7, event: STEP_END };
  expect(checkNotification("run.event", event)).toEqual([]);
  expect(checkNotification("run.event", { ...event, run_id: "ABC", seq: 0 })).toHaveLength(2);
  expect(checkNotification("evil.event", {})[0]!.message).toContain("모르는 알림");
  expect(checkMessage({ jsonrpc: "2.0", id: 1, method: "graph.open", params: {} })).toEqual([]);
  expect(checkMessage({ jsonrpc: "2.0", id: 1, result: null })).toEqual([]);
  const error = { code: -32100, message: "x", data: { code: "revision_conflict", revision: null } };
  expect(checkMessage({ jsonrpc: "2.0", id: null, error })).toEqual([]);
  expect(checkDef("RequestFailedData", error.data)).toEqual([]);
  expect(checkMessage({ jsonrpc: "2.0", id: 1, error: { code: -32601, message: "없음" } })).toEqual(
    [],
  );
  expect(checkMessage({ jsonrpc: "1.0", id: 1, method: "x" }).length).toBeGreaterThan(0);
  expect(checkResult("graph.save", { revision: REVISION, wrote: false })).toHaveLength(2);
});

test("test_run_event_body_checked_by_events_schema", () => {
  // 이벤트 본문은 events.schema.json으로 검사한다 (T2 검수 2)
  const wrap = (event: unknown) => ({ run_id: "abcd1234", seq: 7, event });
  expect(checkNotification("run.event", wrap({ ...STEP_END, outputs: "not-an-object" }))).not.toEqual(
    [],
  );
  expect(checkNotification("run.event", wrap({}))).not.toEqual([]);
  expect(checkNotification("run.event", wrap({ ...STEP_END, event: "step.nope" }))).not.toEqual([]);
  const { step: _, ...noStep } = STEP_END;
  expect(checkNotification("run.event", wrap(noStep))).not.toEqual([]);
  const log = { event: "log", run: "abcd1234", seq: 2, t: STEP_END.t, level: "info", message: "m" };
  expect(checkNotification("run.event", wrap({ ...log, node: null, step: null }))).toEqual([]);
});

test("test_request_failed_error_requires_data", () => {
  // -32100이면 data(RequestFailedData)가 반드시 있고 모양이 맞아야 한다 (T2 검수 3)
  const bad = [
    { code: -32100, message: "failed" },
    { code: -32100, message: "failed", data: { code: "unknown_failure", diagnostics: "bad" } },
    { code: -32100, message: "failed", data: { code: "revision_conflict", diagnostics: "bad" } },
    { code: -32100, message: "failed", data: 123 },
    { code: -32001, message: "내부 코드" },
  ];
  for (const error of bad) {
    expect(checkMessage({ jsonrpc: "2.0", id: 1, error })).not.toEqual([]);
  }
});

test("test_agent_hello_requires_id", () => {
  // agent 연결은 주체 id가 필수, ui는 id 없이 (T2 검수 5)
  const hello = (client: object) => ({ token: "a".repeat(64), protocol: 1, client });
  const agent = { kind: "agent", name: "probe", version: "1" };
  expect(checkParams("session.hello", hello(agent))).not.toEqual([]);
  expect(checkParams("session.hello", hello({ ...agent, id: "" }))).not.toEqual([]);
  expect(checkParams("session.hello", hello({ ...agent, id: "codex-1" }))).toEqual([]);
  expect(checkParams("session.hello", hello({ ...agent, id: "a", attended: true }))).toEqual([]);
  const ui = { kind: "ui", name: "desktop", version: "0.1.0" };
  expect(checkParams("session.hello", hello(ui))).toEqual([]);
  expect(checkParams("session.hello", hello({ ...ui, id: "x" }))).not.toEqual([]);
});

test("test_whole_value_json_rules", () => {
  // 스키마가 안쪽 모양을 정하지 않은 값도 유한한 수·JSON 타입·128단을 지킨다 (T2 검수 4)
  const params = (value: unknown) => ({ doc_id: "d1", seq: 1, value });
  expect(checkParams("graph.validate", params({ nodes: { n: { in: { x: Infinity } } } }))).toEqual([
    { pointer: "/value/nodes/n/in/x", message: "Infinity는 JSON 숫자가 아니다 (NaN·Infinity)" },
  ]);
  expect(checkParams("graph.validate", params({ a: [1, Number.NaN] }))).toHaveLength(1);
  expect(checkParams("graph.validate", params({ a: undefined }))).toHaveLength(1);
  expect(checkParams("graph.validate", params({ a: new Date(0) }))).toHaveLength(1);
  expect(checkParams("graph.validate", params({ a: [1, , 3] }))).toEqual([
    { pointer: "/value/a/1", message: "배열에 빈 칸이 있다" },
  ]);
  // 큰 유한 실수는 그대로 허용 (전송 코덱이 float로 돌려보내는 값)
  expect(checkParams("graph.validate", params({ big: 1e20, x: 2 ** 53 }))).toEqual([]);
  // 받은 JSON: 1e400은 Infinity가 되므로 거부
  const overflow: unknown = JSON.parse('{"jsonrpc":"2.0","id":1,"result":{"x":1e400}}');
  expect(checkMessage(overflow)).toEqual([
    { pointer: "/result/x", message: "Infinity는 JSON 숫자가 아니다 (NaN·Infinity)" },
  ]);
  // 중첩: 메시지 최상위를 0단으로 128단까지
  const nest = (levels: number) => {
    let value: object = {};
    for (let i = 0; i < levels; i++) value = { c: value };
    return value;
  };
  expect(checkMessage({ jsonrpc: "2.0", id: 1, result: nest(126) })).toEqual([]);
  expect(checkMessage({ jsonrpc: "2.0", id: 1, result: nest(127) })[0]!.message).toContain(
    "128단",
  );
  expect(checkMessage({ jsonrpc: "2.0", id: 1, result: nest(140) })).toHaveLength(1);
});

test("test_m3_methods_resolve_other_schemas", () => {
  // M3 계획 2.11: 디버거·기록 읽기 메서드가 breakpoints·run-index·events·video-index를 참조한다
  const T = "2026-10-29T06:02:11.104Z";
  const bp = { graph: "subgraphs/enter_world.graph.json", node: "n_wait_title" };
  expect(checkParams("debug.breakpoints.set", { breakpoints: [bp] })).toEqual([]);
  expect(checkParams("debug.breakpoints.set", { breakpoints: [{ node: "n" }] })).not.toEqual([]);
  expect(checkParams("run.resume", { run_id: "abcd1234", mode: "step_into" })).toEqual([]);
  expect(checkParams("run.resume", { run_id: "abcd1234", mode: "jump" })).not.toEqual([]);
  expect(checkResult("run.pause", { state: "pausing" })).toEqual([]);
  const node = {
    attempt: 1,
    children: 0,
    duration_ms: null,
    evidence: false,
    exit: null,
    graph: "tests/a.graph.json",
    node: "n_wait",
    parent: null,
    path: ["n_wait"],
    status: "running",
    step: "s2",
    t_end: null,
    t_start: T,
  };
  const segment = {
    bytes: 1,
    file: "seg-0001.mp4",
    frame_ms: 200,
    frames: 5,
    mode: "on",
    size: [1280, 720],
    t0: T,
    t_end: T,
    window: "w1",
  };
  const index = {
    failure_chain: [],
    last_seq: 3,
    pauses: [],
    run: null,
    run_dir: "runs/x",
    run_id: "abcd1234",
    state: "running",
    stats: [],
    steps: [node],
    video: { finalized: false, gaps: [], segments: [segment], status: "recorded" },
  };
  expect(checkResult("run.index", index)).toEqual([]);
  expect(checkResult("run.index", { ...index, steps: [{ ...node, status: "lost" }] })).not.toEqual(
    [],
  );
  const badVideo = { ...index.video, segments: [{ ...segment, frame_ms: 0 }] };
  expect(checkResult("run.index", { ...index, video: badVideo })).not.toEqual([]);
  const stepEnd = {
    event: "step.end",
    run: "abcd1234",
    seq: 4,
    t: T,
    attempt: 1,
    duration_ms: 3,
    exit: "timeout",
    outputs: {},
    status: "success",
    step: "s2",
    evidence: { mid: null, mid_missing: "no_sample_near_mid" },
  };
  const step = { events: [stepEnd], ocr_text: null, run_dir: "runs/x", step: node, thumbnail: null };
  expect(checkResult("run.step", step)).toEqual([]);
  const noReason = { ...stepEnd, evidence: { mid: null } };
  expect(checkResult("run.step", { ...step, events: [noReason] })).not.toEqual([]);
  expect(checkResult("run.compare", { baseline: null, run_id: "abcd1234" })).toEqual([]);
  expect(checkNotification("debug.breakpoints.changed", { breakpoints: [bp] })).toEqual([]);
});
