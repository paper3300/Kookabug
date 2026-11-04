// M4 계약을 TS에서 실제로 쓰는 검사 (M4 계획 2.12). 타입이 생성되지 않으면 typecheck가 실패한다
import { expect, test } from "vitest";
import type {
  LeaseChangedParams,
  LeaseOwner,
  RecorderStateResult,
  RecorderStep,
  RecorderStepsResult,
  RecorderTargetSpec,
} from "./generated/daemon-rpc.js";
import type { RecorderFragment } from "./generated/recorder-fragment.js";
import type { HookEventsParams } from "./generated/recorder-hook.js";
import type { InputLine } from "./generated/recorder-script.js";
import { checkNotification, checkParams, checkResult } from "./rpcCheck.js";

const fragment: RecorderFragment = {
  mode: "insert",
  nodes: [
    {
      local_id: "r1",
      type: "core.image.wait",
      version: 1,
      title: "나타날 때까지 대기",
      in: { target: { $target: "targets/rec/a/01_bag.target.json" } },
      next: { found: "r2" },
    },
    {
      local_id: "r2",
      type: "core.input.drag",
      version: 1,
      title: "끌기",
      in: { start: { $link: "r1.match" }, end: [400, 300] },
    },
  ],
  chain: ["r1", "r2"],
  open_end: { node: "r2", exit: "ok" },
  warnings: [],
};

test("test_recorder_types_and_runtime_check", () => {
  const owner: LeaseOwner = { kind: "recorder", pid: 7, created: "133000000000000000" };
  const lease: LeaseChangedParams = { owner };
  expect(checkNotification("lease.changed", lease)).toEqual([]);
  // 상태 바 "입력: 녹화"는 kind로 고른다
  expect(owner.kind).toBe("recorder");

  const secret: RecorderStep = {
    step: "rs4",
    kind: "text",
    t_ms: 1100,
    node: { type: "core.input.type_text", title: "글자 입력" },
    needs_review: [],
    badges: [{ code: "secret_key_required", severity: "review" }],
    text_state: "secret",
    text_len: 6,
    secret_key: null,
  };
  const steps: RecorderStepsResult = { rev: 1, steps: [secret] };
  expect(checkResult("recorder.steps", steps)).toEqual([]);
  // 비밀값 스텝에 원문이 실리면 주 프로세스 검사가 응답을 거부한다
  const leaked = checkResult("recorder.steps", { rev: 1, steps: [{ ...secret, text: "hunter" }] });
  expect(leaked).not.toEqual([]);

  const other: RecorderStateResult = { state: "recording", owned: false, elapsed_ms: 1000 };
  expect(checkResult("recorder.state", other)).toEqual([]);
  expect(checkResult("recorder.state", { ...other, counts: {} })).not.toEqual([]);

  // daemon-rpc가 참조하는 조각 스키마도 런타임 검사기가 푼다
  const prepared = { token: "t".repeat(24), fragment, targets: [] };
  expect(checkResult("recorder.commit_prepare", prepared)).toEqual([]);
  const noEnd = { ...prepared, fragment: { ...fragment, open_end: undefined } };
  delete noEnd.fragment.open_end;
  expect(checkResult("recorder.commit_prepare", noEnd)).not.toEqual([]);

  expect(
    checkParams("recorder.start", { window: 1, hotkeys: [{ keys: "ctrl+shift+r", role: "stop" }] }),
  ).toEqual([]);
  expect(checkParams("recorder.frame", { which: "pre_click" })).not.toEqual([]);
});

// 검수 1차(review_T1_1) 회귀: 실제 주 프로세스 검사기(rpcCheck)로
test("test_review_t1_1_options_draft_frame_fragment", () => {
  // R1: 녹화 뒤 바꾼 변환 옵션을 커밋 때 보낸다
  const prepare = { mode: "new_test", graph_path: "tests/login.graph.json" };
  expect(checkParams("recorder.commit_prepare", { ...prepare, options: { crop_targets: false } })).toEqual([]);
  expect(checkParams("recorder.commit_prepare", { ...prepare, options: { guess: 1 } })).not.toEqual([]);

  // R2: 초안 사양(기본값이 아닌 값)을 응답으로 읽고 같은 모양으로 고친다
  const spec: RecorderTargetSpec = {
    rect: [10, 10, 80, 40],
    anchor: "top_left",
    offset: [8, 9],
    threshold: 0.92,
    rgb: false,
    methods: ["template"],
    color_tolerance: 20,
    sensitive: true,
  };
  const clicked: RecorderStep = {
    step: "rs1",
    kind: "click",
    t_ms: 10,
    node: { type: "core.image.click", title: "click" },
    needs_review: [],
    badges: [],
    target: { source: "draft", frame: "pre_click", spec },
  };
  expect(checkResult("recorder.steps", { rev: 1, steps: [clicked] })).toEqual([]);
  expect(checkParams("recorder.step.update", { step: "rs1", patch: { target: spec } })).toEqual([]);

  // R3: 편집기에서 고른 프레임은 고정된 frame_id로
  expect(checkParams("recorder.step.update", { step: "rs1", patch: { frame_id: "f123" } })).toEqual([]);
  expect(checkParams("recorder.step.update", { step: "rs1", patch: { frame: "live" } })).not.toEqual([]);
  expect(
    checkParams("recorder.step.update", { step: "rs1", patch: { frame: "pre_click", frame_id: "f1" } }),
  ).not.toEqual([]);

  // R5: 그래프 Value 규칙에 어긋난 조각 값은 커밋 결과 검사가 거부한다
  for (const start of [{ $link: 7 }, { $link: "r1" }, { $literal: 1, $link: "r999.match" }, { $secret: 42 }]) {
    const bad = {
      ...fragment,
      nodes: [fragment.nodes[0]!, { ...fragment.nodes[1]!, in: { start } }],
    };
    expect(checkResult("recorder.commit_prepare", { token: "t".repeat(24), fragment: bad, targets: [] }))
      .not.toEqual([]);
  }
});

test("test_hook_and_script_types_generated", () => {
  const batch: HookEventsParams = {
    batch_no: 1,
    events: [
      {
        event_id: 3,
        crit_seq: 1,
        t_ns: 1_000_000,
        kind: "mouse_down",
        x: 1,
        y: 2,
        button: "left",
        injected: false,
        injected_lower_il: false,
        extra_info: 0,
      },
    ],
    crit_first: 1,
    crit_last: 1,
    dropped_marker: 0,
    coalesced_moves: 2,
    overflow: 0,
  };
  const line: InputLine = {
    kind: "input",
    t_ns: 0,
    input: { kind: "key_down", vk: 65, scan: 30, extended: false, injected: false, injected_lower_il: false, extra_info: 0 },
  };
  expect([batch, line]).toHaveLength(2);
});
