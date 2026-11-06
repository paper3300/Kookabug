// 녹화 상태 문구 (M4 계획 T9 완료 기준 statusText.test.ts): 시안에 없는 상태 — 준비 중·일시정지·정지 뒤·오류 셋·
// 판정 중·확인 필요·다른 창에서 녹화 중 (검수 M10)
import { describe, expect, test } from "vitest";
import { runAvailability } from "../run/commands";
import {
  formatRecTime,
  recorderErrorText,
  sidebarStateText,
  statusBarItems,
  statusBarRecording,
  stepLabel,
  stepMarks,
  stopReasonText,
  warningText,
  type RecorderStateResult,
  type RecorderStep,
} from "./labels";
import { elapsedNow, recordingBlocksRun } from "./recorderStore";

const WINDOW = { title: "SampleRPG", client_size: [1280, 720] as [number, number], dpi: 96, handle: 1, process: "python.exe" };
const COUNTS = { steps: 6, targets: 4, ignored_injected: 0, ignored_outside: 0, ignored_popup: 0 };

function st(state: RecorderStateResult["state"], over: Partial<RecorderStateResult> = {}): RecorderStateResult {
  return { owned: true, state, window: WINDOW, counts: COUNTS, elapsed_ms: 134_000, ...over };
}

describe("사이드바 상태 줄", () => {
  test("시안 REC 02:14와 시안에 없는 상태", () => {
    expect(sidebarStateText(st("recording"), 134_000)).toBe("REC 02:14");
    expect(sidebarStateText(st("starting"), 0)).toBe("녹화 준비 중…");
    expect(sidebarStateText(st("paused"), 0)).toBe("⏸ 일시정지 · 게임 입력을 녹화하지 않아요");
    expect(sidebarStateText(st("stopped"), 0)).toBe("녹화 끝 · 스텝 6");
    expect(sidebarStateText(st("committing"), 0)).toBe("저장 중…");
    expect(sidebarStateText(st("idle"), 0)).toBeNull();
    expect(sidebarStateText({ owned: false, state: "recording" }, 0)).toBe("다른 창에서 녹화 중이에요");
    expect(sidebarStateText({ owned: false, state: "idle" }, 0)).toBeNull();
  });

  test("오류로 멈춤 셋 (+저장소 상한): 이유와 그 뒤 입력 문구, 사람이 멈춘 것은 없음", () => {
    expect(stopReasonText("hook_lost")).toBe("녹화가 끊겼어요 — 그 뒤 입력은 녹화되지 않았어요");
    expect(stopReasonText("input_overflow")).toContain("그 뒤 입력은 녹화되지 않았어요");
    expect(stopReasonText("window_gone")).toContain("게임 창이 닫혀");
    expect(stopReasonText("storage_full")).toContain("저장 공간");
    expect(stopReasonText("user")).toBeNull();
    expect(stopReasonText(undefined)).toBeNull();
  });

  test("판정 중·확인 필요 메모", () => {
    const pending = { step: "a", kind: "text", t_ms: 0, text_state: "pending", text_len: 3, badges: [], needs_review: [], node: { title: "", type: "" } } as RecorderStep;
    const review = { ...pending, step: "b", text_state: "needs_review", needs_review: ["ime_unknown"] } as RecorderStep;
    expect(stepLabel(pending, stepMarks([pending]), false).note).toBe("판정 중");
    expect(stepLabel(review, stepMarks([review]), false)).toMatchObject({ note: "입력기 상태를 확인하지 못했어요", tone: "review" });
  });

  test("녹화 알림 문구", () => {
    expect(warningText({ code: "injected_ignored", count: 3 })).toBe("다른 프로그램이 보낸 입력 3개는 녹화하지 않았어요");
    expect(warningText({ code: "not_foreground" })).toBe("게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중");
    expect(warningText({ code: "x", message: "그대로" })).toBe("그대로");
  });

  test("녹화 임시 파일 정리 실패 (SECFIX): 오류 문구와 알림 띠", () => {
    expect(recorderErrorText("recorder_store_unclean", "daemon 문구")).toBe(
      "바꾼 내용은 반영했지만 녹화 임시 파일을 정리하지 못했어요 — 다시 시도하는 중이에요",
    );
    expect(warningText({ code: "store_unclean", message: "녹화 임시 파일을 정리하지 못했어요 — 다시 시도하는 중이에요" })).toContain("정리하지 못했어요");
  });
});

describe("상태 바", () => {
  test("녹화 중 빨강 항목 (시안 문구 그대로)", () => {
    expect(statusBarRecording(st("recording"))).toBe(true);
    expect(statusBarItems(st("recording"), 134_000)).toEqual({
      left: ["녹화 중 02:14", "SampleRPG 1280×720 · DPI 100%", "스텝 6 · 템플릿 4"],
      right: ["녹화 정지 Ctrl+Shift+R", "캡처 WGC · 훅 저수준"],
    });
  });

  test("일시정지는 빨강 유지, 정지 뒤는 기본 색 '녹화 끝 · 스텝 N'", () => {
    expect(statusBarRecording(st("paused"))).toBe(true);
    expect(statusBarItems(st("paused"), 5_000)?.left[0]).toBe("⏸ 일시정지 00:05");
    expect(statusBarRecording(st("stopped"))).toBe(false);
    expect(statusBarItems(st("stopped"), 0)?.left[0]).toBe("녹화 끝 · 스텝 6");
    expect(statusBarItems(st("stopped"), 0)?.right).toEqual([]);
    expect(statusBarRecording(st("starting"))).toBe(true);
    expect(statusBarItems(st("idle"), 0)).toBeNull();
  });

  test("다른 창 녹화: 빨강 아님, 항목 하나", () => {
    expect(statusBarRecording({ owned: false, state: "recording" })).toBe(false);
    expect(statusBarItems({ owned: false, state: "recording" }, 0)).toEqual({ left: ["다른 창에서 녹화 중"], right: [] });
  });

  test("경과 시간: 녹화 중이면 받은 뒤 흐른 시간을 더하고 일시정지면 멈춘다", () => {
    expect(elapsedNow({ state: st("recording", { elapsed_ms: 1000 }), stateAt: 10_000 }, 12_500)).toBe(3500);
    expect(elapsedNow({ state: st("paused", { elapsed_ms: 1000 }), stateAt: 10_000 }, 12_500)).toBe(1000);
    expect(formatRecTime(3_725_000)).toBe("1:02:05");
  });
});

describe("녹화 중 실행 단추 (2.11)", () => {
  const tab = { path: "tests/a.graph.json", kind: "graph" as const, graphKind: "test" };
  test("starting·recording·paused는 끄고, stopped(다듬는 중)는 켠다 — 다른 창 녹화도 끈다", () => {
    for (const state of ["starting", "recording", "paused"] as const) {
      const r = runAvailability({ tab, connected: true, running: false, starting: null, recording: recordingBlocksRun(st(state)) });
      expect(r).toMatchObject({ canRun: false, runTitle: "녹화 중에는 실행할 수 없어요" });
    }
    expect(runAvailability({ tab, connected: true, running: false, starting: null, recording: recordingBlocksRun(st("stopped")) }).canRun).toBe(true);
    expect(recordingBlocksRun({ owned: false, state: "recording" })).toBe(true);
    expect(recordingBlocksRun(null)).toBe(false);
  });
});
