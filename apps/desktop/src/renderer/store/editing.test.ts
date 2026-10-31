// 닫기·떠나기 저장 확인 (M2 계획 T9, 검수 1차 repro_T9_1.ts close_during_save). 실제 store에 가짜 다리만 끼워
// RPC 응답 순서를 정한다
import { beforeEach, describe, expect, test } from "vitest";
import { moveNodes } from "../graph/commands";
import { finish, useDialog, useEditLock } from "./dialog";
import { applyEdit, getDoc, openDoc, resetDocuments, setDocumentsConnection } from "./documents";
import { confirmLeaveDirty, requestCloseTab } from "./editing";
import { openTab, useTabs } from "./tabs";

interface Call {
  method: string;
  params: Record<string, unknown>;
  resolve(v: unknown): void;
  reject(e: unknown): void;
}

const calls: Call[] = [];
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc(method: string, params: Record<string, unknown>) {
    return new Promise((resolve, reject) => calls.push({ method, params, resolve, reject }));
  },
  on() {
    return () => {};
  },
};

const PATH = "tests/close.graph.json";
const tick = () => new Promise((r) => setTimeout(r, 0));
const saves = () => calls.filter((c) => c.method === "graph.save");
const layoutOf = (v: unknown) => (v as { layout?: { nodes?: Record<string, unknown> } }).layout?.nodes?.n_a;

async function ready(): Promise<void> {
  useTabs.setState({ tabs: [], active: null });
  resetDocuments();
  calls.length = 0;
  setDocumentsConnection("s:1");
  openTab({ path: PATH, kind: "graph", graphKind: "test" });
  await tick();
  calls
    .find((c) => c.method === "graph.open")!
    .resolve({
      doc_id: "doc",
      revision: "r1",
      value: { nodes: { n_a: { type: "core.flow.delay", version: 1 } } },
      canonical: true,
      diagnostics: [],
      shapes: {},
    });
  await tick();
  expect(getDoc(PATH)?.status).toBe("ready");
}

beforeEach(async () => {
  if (useDialog.getState().current !== null) finish({ value: "cancel", text: "" });
  await ready();
});

describe("저장하고 닫기", () => {
  test("저장 응답을 기다리는 동안 편집은 잠기고, 저장이 끝나면 저장한 값으로 닫힌다", async () => {
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    const closing = requestCloseTab(PATH);
    await tick();
    finish({ value: "save", text: "" });
    await tick();
    expect(useEditLock.getState().locks).toBe(1);
    // 대기 중 편집 시도는 거부된다 (repro: 999,999 이동이 사라지던 경로)
    expect(applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 999, y: 999 }]))).toBe(false);
    const save = saves()[0];
    expect(layoutOf(save.params.value)).toEqual({ x: 1, y: 2 });
    save.resolve({ revision: "r2", wrote: true, canonicalized: false, diagnostics: [] });
    expect(await closing).toBe(true);
    expect(getDoc(PATH)).toBeUndefined();
    expect(useTabs.getState().tabs).toHaveLength(0);
    expect(useEditLock.getState().locks).toBe(0);
  });

  test("저장이 실패하면 닫지 않고 편집은 남는다", async () => {
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    const closing = requestCloseTab(PATH);
    await tick();
    finish({ value: "save", text: "" });
    await tick();
    saves()[0].reject({ code: -32100, message: "c", data: { code: "revision_conflict", revision: "disk" } });
    expect(await closing).toBe(false);
    expect(getDoc(PATH)?.dirty).toBe(true);
    expect(useTabs.getState().tabs).toHaveLength(1);
    expect(useEditLock.getState().locks).toBe(0);
  });

  test("취소·저장 안 함", async () => {
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    let closing = requestCloseTab(PATH);
    await tick();
    finish({ value: "cancel", text: "" });
    expect(await closing).toBe(false);
    expect(useTabs.getState().tabs).toHaveLength(1);
    closing = requestCloseTab(PATH);
    await tick();
    finish({ value: "discard", text: "" });
    expect(await closing).toBe(true);
    expect(saves()).toHaveLength(0);
    expect(useTabs.getState().tabs).toHaveLength(0);
  });
});

describe("떠나기 확인 (프로젝트 전환·창 닫기)", () => {
  test("모두 저장 동안 편집이 잠기고, 다 저장되면 떠난다", async () => {
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 3, y: 4 }]));
    const leaving = confirmLeaveDirty();
    await tick();
    finish({ value: "save", text: "" });
    await tick();
    expect(applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 9, y: 9 }]))).toBe(false);
    saves()[0].resolve({ revision: "r2", wrote: true, canonicalized: false, diagnostics: [] });
    expect(await leaving).toBe(true);
    expect(getDoc(PATH)?.dirty).toBe(false);
    expect(layoutOf(getDoc(PATH)!.value)).toEqual({ x: 3, y: 4 });
  });

  test("저장 안 된 문서가 없으면 묻지 않는다, 취소면 떠나지 않는다", async () => {
    expect(await confirmLeaveDirty()).toBe(true);
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 3, y: 4 }]));
    const leaving = confirmLeaveDirty();
    await tick();
    expect(useDialog.getState().current?.title).toContain("1개");
    finish({ value: "cancel", text: "" });
    expect(await leaving).toBe(false);
  });
});
