// M3 계약을 TS에서 실제로 쓰는 검사 (M3 T1 검수 2). 타입이 생성되지 않으면 typecheck가 실패한다
import { expect, test } from "vitest";
import type { Breakpoint } from "./generated/breakpoints.js";
import type { RunBreakpointsParams, RunResumeParams, RunSpec } from "./generated/rpc.js";
import type { DeletedSegment, Segment } from "./generated/video-index.js";
import { rpc } from "./index.js";
import { checkResult } from "./rpcCheck.js";

const T = "2026-10-29T06:02:11.104Z";

test("test_runner_control_types_generated", () => {
  const bp: Breakpoint = { graph: "subgraphs/enter_world.graph.json", node: "n_wait_title" };
  const resume: RunResumeParams = { mode: "step_over" };
  const continueOnly: RunResumeParams = {};
  const breakpoints: RunBreakpointsParams = { breakpoints: [bp] };
  const spec: Pick<RunSpec, "breakpoints" | "graph"> = {
    breakpoints: [bp],
    graph: "tests/inventory_open.graph.json",
  };
  const viaIndex: rpc.RunResumeParams = resume;
  expect([resume, continueOnly, breakpoints, spec, viaIndex]).toHaveLength(5);
});

test("test_part_mp4_not_a_closed_segment", () => {
  const segment: Segment = {
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
  const deleted: DeletedSegment = { file: "seg-0002.part.mp4", reason: "interrupted" };
  const index = (segments: Segment[]) => ({
    failure_chain: [],
    last_seq: 0,
    pauses: [],
    run: null,
    run_dir: "runs/x",
    run_id: "r8k2x7qm",
    state: "ended",
    stats: [],
    steps: [],
    video: { finalized: true, gaps: [], segments, status: "recorded" },
  });
  expect(checkResult("run.index", index([segment]))).toEqual([]);
  // 쓰는 중 파일은 완성 조각 목록에 올 수 없다 (지운 조각 기록에만)
  const part = checkResult("run.index", index([{ ...segment, file: "seg-0001.part.mp4" }]));
  expect(part).not.toEqual([]);
  expect(part[0]!.pointer).toBe("/video/segments/0/file");
  expect(deleted.file).toContain(".part.");
});
