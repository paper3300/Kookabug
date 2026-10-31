// 문서 표 (M2 계획 2.3·2.6, T8 검수 1차 반례). 실제 store/documents.ts에 가짜 다리만 끼워 RPC 응답 순서를 정한다
import { beforeEach, describe, expect, test } from "vitest";
import { RpcError } from "../rpc/client";
import { SessionRecovery } from "../rpc/recovery";
import { connectExec, deleteNodes, moveNodes } from "../graph/commands";
import { ask, finish, lockEdits } from "./dialog";
import type { GraphValue } from "../graph/model";
import {
  applyEdit,
  canUndo,
  closeDoc,
  CONFLICT_DELETED,
  documentsHost,
  getDoc,
  onGraphChanged,
  openDoc,
  redoEdit,
  reloadDoc,
  requestFocus,
  resetDocuments,
  saveDoc,
  setDocumentsConnection,
  setSelection,
  undoEdit,
} from "./documents";

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

const PATH = "tests/a.graph.json";
const tick = () => new Promise((r) => setTimeout(r, 0));
const opens = () => calls.filter((c) => c.method === "graph.open");
const closes = () => calls.filter((c) => c.method === "graph.close").map((c) => c.params.doc_id);

function result(title: string, revision: string, docId = "doc", nodes: Record<string, unknown> = {}) {
  return { doc_id: docId, revision, value: { nodes, meta: { title } }, canonical: true, diagnostics: [], shapes: {} };
}
const titleOf = () => (getDoc(PATH)!.value!.meta as { title: string }).title;

beforeEach(() => {
  resetDocuments();
  calls.length = 0;
  setDocumentsConnection("s:1");
});

describe("응답 순서를 가정하지 않는다", () => {
  test("닫았다 다시 연 탭에 앞 열기 응답이 늦게 와도 쓰지 않는다", async () => {
    const first = openDoc(PATH);
    closeDoc(PATH);
    const second = openDoc(PATH);
    const [old, fresh] = opens();
    fresh.resolve(result("new disk", "new"));
    await second;
    old.resolve(result("stale disk", "old"));
    await first;
    expect(titleOf()).toBe("new disk");
    expect(getDoc(PATH)!.baseRevision).toBe("new");
    expect(getDoc(PATH)!.refs).toBe(1);
    // 쓰지 않은 응답이 만든 참조(같은 연결)는 푼다
    expect(closes()).toEqual(["doc"]);
  });

  test("앞 열기의 실패 응답이 새 문서를 오류로 바꾸지 않는다", async () => {
    const first = openDoc(PATH);
    closeDoc(PATH);
    const second = openDoc(PATH);
    const [old, fresh] = opens();
    fresh.resolve(result("new disk", "new"));
    await second;
    old.reject({ code: -32100, message: "없음", data: { code: "not_found" } });
    await first;
    expect(getDoc(PATH)!.status).toBe("ready");
    expect(getDoc(PATH)!.error).toBeNull();
  });

  test("연결이 바뀐 뒤 온 쓰지 않을 응답은 닫지 않는다 (앞 연결의 참조는 daemon이 풀었다)", async () => {
    const first = openDoc(PATH);
    closeDoc(PATH);
    setDocumentsConnection("s:2");
    opens()[0].resolve(result("x", "r"));
    await first;
    expect(closes()).toEqual([]);
  });

  test("닫기는 지금 연결에서 연 횟수만큼만", async () => {
    const p = openDoc(PATH);
    opens()[0].resolve(result("a", "r"));
    await p;
    closeDoc(PATH);
    expect(closes()).toEqual(["doc"]);
    // 다른 연결에서 연 문서는 닫기를 보내지 않는다
    calls.length = 0;
    const q = openDoc(PATH);
    opens()[0].resolve(result("a", "r", "doc2"));
    await q;
    setDocumentsConnection("s:3");
    closeDoc(PATH);
    expect(closes()).toEqual([]);
  });
});

describe("다시 붙은 뒤 복구 (실제 documentsHost)", () => {
  test("한 번 다시 열기에 실패한 문서가 다음 연결에서 열리면 오류를 지우고 다시 검증한다", async () => {
    const p = openDoc(PATH);
    opens()[0].resolve(result("initial", "r"));
    await p;
    let fail = true;
    const recovery = new SessionRecovery((async (method: string) => {
      if (method !== "graph.open") throw new Error(method);
      if (fail) throw new RpcError(-32100, "missing", { code: "not_found" });
      return result("recovered", "r", "doc-new");
    }) as never);
    recovery.addDocs(documentsHost);
    await recovery.connected({ root: "w", startId: "d", connection: 1 });
    setDocumentsConnection("d:2");
    await recovery.connected({ root: "w", startId: "d", connection: 2 });
    expect(getDoc(PATH)!.status).toBe("error");
    fail = false;
    setDocumentsConnection("d:3");
    await recovery.connected({ root: "w", startId: "d", connection: 3 });
    const doc = getDoc(PATH)!;
    expect(doc.status).toBe("ready");
    expect(doc.error).toBeNull();
    expect(doc.docId).toBe("doc-new");
    expect(doc.refsConnection).toBe("d:3");
    // 버퍼는 그대로 (revision이 같아 다시 붙이기만)
    expect(titleOf()).toBe("initial");
    // 다시 붙은 뒤 검증이 간다
    await tick();
    const validate = calls.find((c) => c.method === "graph.validate");
    expect(validate?.params.doc_id).toBe("doc-new");
  });
});

describe("다른 파일 문제로 옮겨 가기", () => {
  test("열리는 중인 문서는 준비된 뒤 진단 노드를 고르고 접힌 그룹을 펼친다", async () => {
    const p = openDoc(PATH);
    requestFocus(PATH, { node: null, pointer: "/nodes/n_b/in/target" });
    expect(getDoc(PATH)!.view.focus).toBeNull();
    const value = result("g", "r", "doc", {
      n_a: { type: "core.flow.delay", version: 1 },
      n_b: { type: "core.flow.delay", version: 1 },
    });
    (value.value as Record<string, unknown>).layout = { collapsed: { g1: { nodes: ["n_b"], title: "묶음" } } };
    opens()[0].resolve(value);
    await p;
    const view = getDoc(PATH)!.view;
    expect(view.selected).toBe("n_b");
    expect(view.expanded).toEqual(["g1"]);
    expect(view.focus?.node).toBe("n_b");
  });

  test("이미 열린 문서는 바로 옮겨 간다", async () => {
    const p = openDoc(PATH);
    opens()[0].resolve(result("g", "r", "doc", { n_a: { type: "core.flow.delay", version: 1 } }));
    await p;
    requestFocus(PATH, { node: "n_a" });
    expect(getDoc(PATH)!.view.selected).toBe("n_a");
  });
});

describe("편집·실행 취소·저장 (T9)", () => {
  const NODES = { n_a: { type: "core.flow.delay", version: 1 }, n_b: { type: "core.flow.delay", version: 1 } };
  async function ready(): Promise<GraphValue> {
    const p = openDoc(PATH);
    opens()[0].resolve(result("t", "r1", "doc", NODES));
    await p;
    return getDoc(PATH)!.value!;
  }
  const saves = () => calls.filter((c) => c.method === "graph.save");

  test("편집은 dirty, 전부 실행 취소하면 dirty가 꺼지고 처음 값, 다시 실행", async () => {
    const opened = await ready();
    expect(applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 10, y: 20 }]))).toBe(true);
    expect(applyEdit(PATH, (v) => deleteNodes(v, ["n_b"]), [])).toBe(true);
    // 바꾸지 않는 명령은 기록하지 않는다
    expect(applyEdit(PATH, (v) => v)).toBe(false);
    let doc = getDoc(PATH)!;
    expect(doc.dirty).toBe(true);
    expect(doc.history.past).toHaveLength(2);
    expect(canUndo(doc)).toBe(true);
    expect(undoEdit(PATH)).toBe(true);
    expect(undoEdit(PATH)).toBe(true);
    expect(undoEdit(PATH)).toBe(false);
    doc = getDoc(PATH)!;
    expect(doc.value).toBe(opened);
    expect(doc.dirty).toBe(false);
    expect(redoEdit(PATH)).toBe(true);
    expect(getDoc(PATH)!.dirty).toBe(true);
    // 고른 노드는 지워지면 빠진다
    setSelection(PATH, ["n_a", "n_b"]);
    applyEdit(PATH, (v) => deleteNodes(v, ["n_b"]));
    expect(getDoc(PATH)!.view.selection).toEqual(["n_a"]);
  });

  test("저장: 값 전체 + base_revision. 성공하면 저장한 값이 새 기준", async () => {
    await ready();
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    const saving = saveDoc(PATH);
    const call = saves()[0];
    expect(call.params).toMatchObject({ doc_id: "doc", base_revision: "r1" });
    expect(call.params.force).toBeUndefined();
    expect(call.params.value).toBe(getDoc(PATH)!.value);
    call.resolve({ revision: "r2", wrote: true, canonicalized: false, diagnostics: [] });
    expect(await saving).toBe("saved");
    const doc = getDoc(PATH)!;
    expect(doc.dirty).toBe(false);
    expect(doc.baseRevision).toBe("r2");
    expect(doc.savedValue).toBe(doc.value);
    // 실행 취소 기록은 남고, 되돌리면 다시 dirty
    undoEdit(PATH);
    expect(getDoc(PATH)!.dirty).toBe(true);
  });

  test("저장 충돌은 충돌 띠, 덮어쓰기는 force", async () => {
    await ready();
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    const first = saveDoc(PATH);
    saves()[0].reject({ code: -32100, message: "conflict", data: { code: "revision_conflict", revision: "disk" } });
    expect(await first).toBe("conflict");
    expect(getDoc(PATH)!.conflict).toBe("disk");
    expect(getDoc(PATH)!.dirty).toBe(true);
    const forced = saveDoc(PATH, { force: true });
    expect(saves()[1].params).toMatchObject({ force: true, base_revision: "r1" });
    saves()[1].resolve({ revision: "r3", wrote: true, canonicalized: false, diagnostics: [] });
    await forced;
    expect(getDoc(PATH)!.conflict).toBeNull();
    expect(getDoc(PATH)!.baseRevision).toBe("r3");
  });

  test("저장 실패(비유한 수)는 문구, 파일은 그대로 두고 dirty 유지", async () => {
    await ready();
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    const p = saveDoc(PATH);
    saves()[0].reject({ code: -32602, message: "x", data: { code: "number_not_finite", pointer: "/value/nodes/n_a/in/ms" } });
    expect(await p).toBe("failed");
    expect(getDoc(PATH)!.saveError).toContain("/value/nodes/n_a/in/ms");
    expect(getDoc(PATH)!.dirty).toBe(true);
  });

  test("graph.changed: 편집하지 않았으면 다시 열고, 편집 중이면 충돌 띠", async () => {
    await ready();
    onGraphChanged("doc", "r1");
    expect(opens()).toHaveLength(1);
    onGraphChanged("doc", "r2");
    expect(opens()).toHaveLength(2);
    opens()[1].resolve(result("밖에서 바뀜", "r2", "doc", NODES));
    await tick();
    expect(titleOf()).toBe("밖에서 바뀜");
    expect(getDoc(PATH)!.baseRevision).toBe("r2");
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 2 }]));
    onGraphChanged("doc", "r3");
    expect(opens()).toHaveLength(2);
    expect(getDoc(PATH)!.conflict).toBe("r3");
    onGraphChanged("doc", null);
    expect(getDoc(PATH)!.conflict).toBe(CONFLICT_DELETED);
  });
});

describe("다시 열기 경쟁 (T9 검수 1차 repro_T9_1.ts)", () => {
  const NODES = { n_a: { type: "core.flow.delay", version: 1 }, n_unknown: { type: "plugin.unknown", version: 3 } };
  async function ready(): Promise<void> {
    const p = openDoc(PATH);
    opens()[0].resolve(result("t", "r1", "doc", NODES));
    await p;
  }
  const nextOf = () => ((getDoc(PATH)!.value!.nodes as Record<string, { next?: unknown }>).n_a.next ?? null);

  test("다시 열기 응답을 기다리는 동안 생긴 편집·실행 취소 기록은 남고 충돌 띠가 된다", async () => {
    await ready();
    onGraphChanged("doc", "r2");
    applyEdit(PATH, (v) => connectExec(moveNodes(v, [{ id: "n_a", x: 123, y: 456 }]), "n_a", "done", "n_unknown"));
    opens()[1].resolve(result("밖", "r2", "doc", NODES));
    await tick();
    const doc = getDoc(PATH)!;
    expect(nextOf()).toEqual({ done: "n_unknown" });
    expect(doc.value!.layout).toEqual({ nodes: { n_a: { x: 123, y: 456 } } });
    expect(doc.dirty).toBe(true);
    expect(canUndo(doc)).toBe(true);
    expect(doc.conflict).toBe("r2");
    expect(doc.baseRevision).toBe("r1");
    expect(doc.refs).toBe(2);
    // 저장은 편집을 담고 기준 revision은 그대로라 충돌로 답받는다 (덮어쓰기는 force)
    const saving = saveDoc(PATH);
    const call = calls.find((c) => c.method === "graph.save")!;
    expect((call.params.value as GraphValue & { nodes: { n_a: { next: unknown } } }).nodes.n_a.next).toEqual({ done: "n_unknown" });
    expect(call.params.base_revision).toBe("r1");
    call.reject({ code: -32100, message: "c", data: { code: "revision_conflict", revision: "r2" } });
    expect(await saving).toBe("conflict");
  });

  test("다시 열기 응답이 역순으로 오면 늦게 온 옛 응답은 버리고 참조를 푼다", async () => {
    await ready();
    onGraphChanged("doc", "r2");
    onGraphChanged("doc", "r3");
    opens()[2].resolve(result("r3 값", "r3", "doc", NODES));
    await tick();
    opens()[1].resolve(result("r2 값", "r2", "doc", NODES));
    await tick();
    expect(getDoc(PATH)!.baseRevision).toBe("r3");
    expect(titleOf()).toBe("r3 값");
    expect(closes()).toEqual(["doc"]);
    expect(getDoc(PATH)!.refs).toBe(2);
  });

  test("명시적 다시 열기도 요청 뒤 편집은 버리지 않는다", async () => {
    await ready();
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 1 }]));
    const p = reloadDoc(PATH);
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 2, y: 2 }]));
    opens()[1].resolve(result("디스크", "r1", "doc", NODES));
    await p;
    const doc = getDoc(PATH)!;
    expect(doc.dirty).toBe(true);
    expect(doc.history.past).toHaveLength(2);
    expect(doc.conflict).toBeNull();
  });

  test("복구가 clean으로 본 뒤 다시 여는 사이 편집이 생기면 다시 열기 대신 충돌", async () => {
    await ready();
    const recovery = new SessionRecovery((async (method: string) => {
      if (method !== "graph.open") throw new Error(method);
      applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 5, y: 5 }]));
      return result("디스크", "r9", "doc-new", NODES);
    }) as never);
    recovery.addDocs(documentsHost);
    await recovery.connected({ root: "w", startId: "d", connection: 1 });
    setDocumentsConnection("d:2");
    await recovery.connected({ root: "w", startId: "d", connection: 2 });
    const doc = getDoc(PATH)!;
    expect(doc.dirty).toBe(true);
    expect(doc.conflict).toBe("r9");
    expect(doc.docId).toBe("doc-new");
    expect(titleOf()).toBe("t");
  });
});

describe("대화 상자·잠금 중 편집 거부 (T9 검수 1차)", () => {
  test("대화 상자가 떠 있거나 잠금 중이면 편집·실행 취소를 하지 않는다", async () => {
    const p = openDoc(PATH);
    opens()[0].resolve(result("t", "r1", "doc", { n_a: { type: "core.flow.delay", version: 1 } }));
    await p;
    applyEdit(PATH, (v) => moveNodes(v, [{ id: "n_a", x: 1, y: 1 }]));
    const asked = ask({ title: "?", buttons: [{ label: "취소", value: "cancel" }], cancelValue: "cancel" });
    expect(applyEdit(PATH, (v) => deleteNodes(v, ["n_a"]))).toBe(false);
    expect(undoEdit(PATH)).toBe(false);
    finish({ value: "cancel", text: "" });
    await asked;
    const unlock = lockEdits();
    expect(applyEdit(PATH, (v) => deleteNodes(v, ["n_a"]))).toBe(false);
    unlock();
    unlock();
    expect(undoEdit(PATH)).toBe(true);
  });
});
