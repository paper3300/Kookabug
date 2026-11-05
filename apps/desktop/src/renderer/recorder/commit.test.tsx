// 녹화 커밋·REC 초안·변환 옵션 (M4 B5 2라운드, 검수 review_B5_1 반례를 올바른 결과로 단언)
// - H1: 삽입~저장~복구 동안 그 문서의 사용자 편집을 잠근다. 저장 실패면 넣은 편집만 되돌리고, 되돌리지 못했으면
//   다시 넣지 않는다 ("다시 넣으세요" 안내 없음) — 사용자 파일 손상 엄격
// - M2: 정지 뒤 확인 넣기 영역 고르기는 마지막 스텝을 바꾸지 않는다
// - M3: 사람이 바꾼 변환 옵션을 상태 갱신이 덮지 않는다
// - M4: 재사용 target을 고치면 찾은 자리로 새 초안이 된다(파일은 그대로), 못 찾으면 고치지 않고 안내
// 렌더러 저장소를 그대로 쓰고 RPC(window.kookabug)만 바꿔 끼운다
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { finish as finishDialog } from "../store/dialog";
import { adoptCreated, applyEdit, applySystemEdit, getDoc, resetDocuments, selectNode, undoEdit } from "../store/documents";
import { closeAllTabs, openTab } from "../store/tabs";
import { commitInsert, STUCK_TEXT } from "./commit";
import { FILE_TARGET_NOTE, loadRecFrame, recAdapter, resetRecDoc, useRecDoc } from "./recAdapter";
import { refreshState, resetRecorder, setOption, useRecorder } from "./recorderStore";

type Json = Record<string, unknown>;

const PATH = "tests/review.graph.json";
const BASE = {
  format: "kookabug.graph/0",
  kind: "test",
  plugins: { core: "0.1.0" },
  title: "사용자 원본",
  extra: { preserved: [1, 2, 3] },
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_pass" } },
    n_pass: { type: "core.test.pass", version: 1 },
  },
};
const FRAGMENT = {
  mode: "insert",
  nodes: [{ local_id: "r1", type: "core.flow.delay", version: 1, title: "녹화 동작", in: { ms: 100 } }],
  chain: ["r1"],
  open_end: { node: "r1", exit: "done" },
  warnings: [],
};
const STOPPED = {
  state: "stopped",
  owned: true,
  session: "s1",
  elapsed_ms: 0,
  options: { wait_as_appear: true, crop_targets: true },
  counts: { steps: 1, targets: 0, ignored_injected: 0, ignored_outside: 0, ignored_popup: 0 },
  warnings: [],
};

let calls: { method: string; params: Json }[] = [];
let saveHandler: (p: Json) => Promise<unknown>;
let previewFound = true;

(globalThis as unknown as { kookabug: unknown }).kookabug = {
  on: () => () => {},
  app: { recorderArm: async () => ({ ok: true, hotkeys: [] }), recorderDisarm: async () => {} },
  rpc: async (method: string, params: Json) => {
    calls.push({ method, params });
    switch (method) {
      case "recorder.commit_prepare":
        return { fragment: FRAGMENT, token: "token", targets: [] };
      case "graph.save":
        return saveHandler(params);
      case "recorder.state":
        return STOPPED;
      case "recorder.steps":
        return { steps: [], rev: 1 };
      case "recorder.frame":
        return { frame: { frame_id: "frame", client_size: [1024, 640], width: 1024, height: 640, dpi: 96, image: { cache: "c" } }, protected: [], which: "pre_click" };
      case "target.open":
        return { spec: { format: "kookabug.target/0", image: "a.png", match: { threshold: 0.85 } }, image: { workspace: "targets/a.png", width: 30, height: 20 }, revision: "r", diagnostics: [] };
      case "target.preview":
        return previewFound
          ? { found: true, seq: params.seq, match: { rect: [100, 120, 30, 20], score: 0.99, scale: 1, click: [115, 130] }, peaks: [] }
          : { found: false, seq: params.seq, best: null };
      case "recorder.step.update":
        return { rev: 2, step: null };
      case "graph.validate":
        return { diagnostics: [], shapes: {}, seq: params.seq };
      case "recorder.commit_abort":
      case "recorder.commit_finish":
      case "graph.close":
        return {};
    }
    throw new Error(`검사가 모르는 메서드 ${method}`);
  },
};

function nodesOf(value: unknown): Json[] {
  return Object.values((value as { nodes: Record<string, Json> }).nodes);
}

beforeEach(() => {
  vi.useFakeTimers();
  calls = [];
  previewFound = true;
  resetDocuments();
  closeAllTabs();
  resetRecorder();
  resetRecDoc();
  finishDialog({ value: "cancel", text: "" });
  adoptCreated(PATH, {
    doc_id: "doc",
    value: structuredClone(BASE),
    revision: "rev",
    canonical: true,
    diagnostics: [],
    shapes: { n_entry: { exits: [{ name: "start", kind: "ok", outputs: [] }], inputs: [], outputs: [], unknown: false } },
  } as never);
  openTab({ path: PATH, kind: "graph", graphKind: "test" });
  selectNode(PATH, "n_entry");
  useRecorder.setState({ state: STOPPED as never });
  saveHandler = async () => ({ wrote: true, revision: "new", diagnostics: [] });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});

test("성공 삽입은 한 번 되돌리기로 사용자 그래프를 복구", async () => {
  const original = structuredClone(getDoc(PATH)!.value);
  expect(await commitInsert()).toBe(true);
  expect(nodesOf(getDoc(PATH)!.value)).toHaveLength(3);
  expect(undoEdit(PATH)).toBe(true);
  expect(getDoc(PATH)!.value).toEqual(original);
});

test("저장 실패는 넣은 편집만 되돌리고 삽입 전 미저장 사용자 편집은 남긴다", async () => {
  applyEdit(PATH, (v) => ({ ...v, title: "미저장 사용자 제목" }));
  const original = structuredClone(getDoc(PATH)!.value);
  saveHandler = async () => {
    throw { code: -32000, message: "검사용 저장 실패", data: { code: "io_error" } };
  };
  expect(await commitInsert()).toBe(false);
  expect(getDoc(PATH)!.value).toEqual(original);
  expect(getDoc(PATH)!.dirty).toBe(true);
  expect(calls.map((c) => c.method)).toContain("recorder.commit_abort");
});

test("H1: 저장을 기다리는 동안 사용자 편집은 잠기고, 실패 뒤 다시 넣어도 녹화 동작은 한 번만 저장된다", async () => {
  let rejectSave: (e: unknown) => void = () => {};
  let started = false;
  saveHandler = () =>
    new Promise((_resolve, reject) => {
      started = true;
      rejectSave = reject;
    });
  const committing = commitInsert();
  for (let i = 0; i < 50 && !started; i++) await Promise.resolve();
  expect(started).toBe(true);
  // 저장 중 사용자 편집은 거부된다 (그래서 되돌리기가 늘 가능하다)
  expect(applyEdit(PATH, (v) => ({ ...v, title: "저장 중 사용자 편집" }))).toBe(false);
  rejectSave({ code: -32000, message: "검사용 디스크 쓰기 실패", data: { code: "io_error" } });
  expect(await committing).toBe(false);
  expect(nodesOf(getDoc(PATH)!.value)).toHaveLength(2);
  expect((getDoc(PATH)!.value as Json).title).toBe("사용자 원본");
  // 잠금이 풀려 사용자 편집이 다시 된다
  expect(applyEdit(PATH, (v) => ({ ...v, title: "뒤 편집" }))).toBe(true);
  let saved: Json | null = null;
  saveHandler = async (params) => {
    saved = structuredClone(params.value as Json);
    return { wrote: true, revision: "retry", diagnostics: [] };
  };
  expect(await commitInsert()).toBe(true);
  const delays = (v: unknown) => nodesOf(v).filter((n) => n.type === "core.flow.delay");
  expect(delays(getDoc(PATH)!.value)).toHaveLength(1);
  expect(delays(saved)).toHaveLength(1);
  expect((saved as unknown as Json).title).toBe("뒤 편집");
});

test("H1: 되돌리지 못했으면(앱 편집이 끼어듦) 다시 넣지 않고 '다시 넣으세요'라고 하지 않는다", async () => {
  let rejectSave: (e: unknown) => void = () => {};
  let started = false;
  saveHandler = () =>
    new Promise((_resolve, reject) => {
      started = true;
      rejectSave = reject;
    });
  const committing = commitInsert();
  for (let i = 0; i < 50 && !started; i++) await Promise.resolve();
  // 잠금을 넘는 앱 편집 (예: 새 target 핀 채우기)이 끼면 값이 우리가 넣은 것과 달라진다
  expect(applySystemEdit(PATH, (v) => ({ ...v, title: "앱 편집" }))).toBe(true);
  rejectSave({ code: -32000, message: "검사용 실패", data: { code: "io_error" } });
  expect(await committing).toBe(false);
  expect(useRecorder.getState().notice?.text).toBe(STUCK_TEXT);
  expect(useRecorder.getState().notice?.text).not.toContain("다시 넣으세요");
  expect(calls.map((c) => c.method)).not.toContain("recorder.commit_abort");
  expect(useRecorder.getState().retryBlocked).toBe(true);
  const before = calls.length;
  expect(await commitInsert()).toBe(false);
  expect(calls.slice(before).map((c) => c.method)).not.toContain("recorder.commit_prepare");
  expect(nodesOf(getDoc(PATH)!.value).filter((n) => n.type === "core.flow.delay")).toHaveLength(1);
});

test("M3: 정지 뒤 바꾼 변환 옵션은 상태 갱신이 덮지 않는다 (새 세션만 서버 값)", async () => {
  await refreshState();
  expect(useRecorder.getState().options.crop_targets).toBe(true);
  setOption("crop_targets", false);
  await refreshState();
  await refreshState();
  expect(useRecorder.getState().options.crop_targets).toBe(false);
});

test("M4: 재사용 target을 고치면 찾은 자리로 새 초안(사양 전체)을 보내고 파일은 건드리지 않는다", async () => {
  await loadRecFrame({ step: "rs1", target: { source: "file", path: "targets/a.target.json" } } as never, "pre_click");
  await vi.advanceTimersByTimeAsync(500);
  expect(useRecDoc.getState().doc.preview?.found).toBe(true);
  recAdapter.editSpec((s) => ({ ...s, match: { ...(s.match as Json), threshold: 0.65 } }));
  await vi.advanceTimersByTimeAsync(500);
  const sent = calls.filter((c) => c.method === "recorder.step.update");
  expect(sent).toHaveLength(1);
  const patch = sent[0].params.patch as { frame_id: string; target: Json };
  expect(patch.frame_id).toBe("frame");
  expect(patch.target).toMatchObject({ rect: [100, 120, 30, 20], threshold: 0.65 });
  expect(calls.map((c) => c.method)).not.toContain("target.save");
});

test("M4: 재사용 target을 이 화면에서 못 찾으면 고치지 않고 영역을 다시 고르라고 안내", async () => {
  previewFound = false;
  await loadRecFrame({ step: "rs1", target: { source: "file", path: "targets/a.target.json" } } as never, "pre_click");
  await vi.advanceTimersByTimeAsync(500);
  recAdapter.editSpec((s) => ({ ...s, match: { ...(s.match as Json), threshold: 0.65 } }));
  await vi.advanceTimersByTimeAsync(500);
  expect(calls.map((c) => c.method)).not.toContain("recorder.step.update");
  expect(useRecDoc.getState().doc.refusal).toBe(FILE_TARGET_NOTE);
  expect((useRecDoc.getState().doc.spec.match as Json).threshold).toBe(0.85);
});

test("M2: 확인 넣기에 빌린 마지막 스텝 화면에서 영역을 골라도 그 스텝을 고치지 않는다", async () => {
  const last = { step: "rs9", kind: "click", frames: ["pre_click"], target: { source: "draft", spec: { rect: [1, 2, 30, 20] } } };
  await loadRecFrame(last as never, "pre_click", { bind: false });
  expect(useRecDoc.getState().doc.step).toBeNull();
  expect(useRecDoc.getState().doc.template).toBeNull();
  recAdapter.setTemplate([400, 100, 200, 60]);
  await vi.advanceTimersByTimeAsync(1000);
  expect(useRecDoc.getState().doc.template).toEqual([400, 100, 200, 60]);
  expect(calls.map((c) => c.method)).not.toContain("recorder.step.update");
});
