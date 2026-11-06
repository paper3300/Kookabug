// 녹화 임시 파일 정리 실패·지난 세션 알림 (M5 SECFIX, 검수 review_SECFIX_2 렌더러 재현을 회귀로)
// - recorder_store_unclean: 바뀐 스텝을 다시 읽고 오류 띠를 남긴다. 비밀값 만들기는 다시 만들지 않고 스텝·키 목록을 읽는다
// - 지난 세션의 recorder.changed는 지금 녹화 상태를 바로 덮지 않는다 (daemon 상태를 다시 읽는다)
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { RpcError } from "../rpc/client";
import { createSecret, onRecorderChanged, updateStep, useRecorder } from "./recorderStore";

const { call } = vi.hoisted(() => ({ call: vi.fn() }));
vi.mock("../rpc/client", async (original) => ({
  ...(await original<typeof import("../rpc/client")>()),
  client: () => ({ call }),
}));
vi.mock("../store/tabs", () => ({ closeTab: vi.fn(), openRecTab: vi.fn(), REC_TAB_PATH: "recorder" }));

const unclean = () => new RpcError(-32100, "정리 실패", { code: "recorder_store_unclean" });

beforeEach(() => {
  call.mockReset();
  useRecorder.setState({ state: null, steps: [], rev: -1, notice: null, secrets: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

test("스텝 고치기가 정리 실패로 응답하면 바뀐 스텝을 다시 읽고 오류 띠를 남긴다", async () => {
  const steps = [{ step: "rs1", text_state: "secret" }];
  call.mockRejectedValueOnce(unclean()).mockResolvedValueOnce({ rev: 3, steps });
  expect(await updateStep("rs1", { text_state: "secret" })).toBe(false);
  expect(call.mock.calls.map(([method]) => method)).toEqual(["recorder.step.update", "recorder.steps"]);
  expect(useRecorder.getState().steps).toEqual(steps);
  expect(useRecorder.getState().notice?.text).toContain("정리하지 못했어요");
});

test("비밀값 만들기 뒤 정리 실패는 다시 만들지 않고 스텝·키 목록을 읽는다", async () => {
  const steps = [{ step: "rs1", text_state: "secret", secret_key: "review.test" }];
  const keys = [{ key: "review.test", source: "credential" }];
  call.mockImplementation(async (method: string) => {
    if (method === "secrets.create") throw unclean();
    if (method === "recorder.steps") return { rev: 3, steps };
    if (method === "secrets.list") return { keys, env_note: "" };
    throw new Error(method);
  });
  expect(await createSecret("rs1", "review.test")).toBe(true);
  expect(call.mock.calls.map(([method]) => method)).toEqual(["secrets.create", "recorder.steps", "secrets.list"]);
  expect(useRecorder.getState().secrets).toEqual(keys);
  expect(useRecorder.getState().notice?.text).toContain("정리하지 못했어요");
});

test("지난 세션의 늦은 끝 알림은 지금 녹화 상태를 덮지 않고 daemon 상태를 다시 읽는다", async () => {
  vi.useFakeTimers();
  const live = { owned: true, state: "recording" as const, session: "newsess1", started_at: "", elapsed_ms: 0 };
  useRecorder.setState({ state: live });
  call.mockResolvedValue(live);
  onRecorderChanged({ state: "discarded", session: "oldsess1" });
  expect(useRecorder.getState().state?.state).toBe("recording");
  await vi.runAllTimersAsync();
  expect(call.mock.calls[0]?.[0]).toBe("recorder.state");
  expect(useRecorder.getState().state?.state).toBe("recording");
  // 같은 세션이면 바로 비춘다
  onRecorderChanged({ state: "paused", session: "newsess1" });
  expect(useRecorder.getState().state?.state).toBe("paused");
});
