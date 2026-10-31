// 문서 표 (M2 계획 2.3·2.6, T8 검수 1차 반례). 실제 store/documents.ts에 가짜 다리만 끼워 RPC 응답 순서를 정한다
import { beforeEach, describe, expect, test } from "vitest";
import { RpcError } from "../rpc/client";
import { SessionRecovery } from "../rpc/recovery";
import {
  closeDoc,
  documentsHost,
  getDoc,
  openDoc,
  requestFocus,
  resetDocuments,
  setDocumentsConnection,
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
