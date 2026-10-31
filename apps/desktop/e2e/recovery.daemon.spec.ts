// 다시 붙은 뒤 문서 복구를 실제 daemon으로 확인한다 (검수 T7_2). Electron 없이 주 프로세스 연결 코드
// (connectDaemon)와 렌더러 복구 모듈(SessionRecovery)을 실제 daemon·WebSocket에 붙인다.
// daemon은 연결이 끝나면 그 연결이 연 문서 참조를 풀고 문서를 지우므로, 새 연결마다 열린 문서를 모두
// 다시 열어야 검증·저장이 된다
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { connectDaemon, nodeDeps, type Connection } from "../src/main/daemon";
import { notConnected } from "../src/main/rpc-connection";
import type { RpcCall } from "../src/renderer/rpc/client";
import { SessionRecovery, type DocHost, type GraphOpenResult } from "../src/renderer/rpc/recovery";
import { REPO_CLI } from "./helpers/app";
import { cleanupWorkspace, copySampleWorkspace, readSession } from "./helpers/daemon";

const CLIENT = { kind: "ui" as const, name: "recovery-test", version: "0.1.0" };
const FILES = ["tests/smoke_headless.graph.json", "tests/inventory_open.graph.json"];

interface Buffer {
  docId: string;
  value: Record<string, unknown>;
  base: string;
  dirty: boolean;
  undo: string[];
}

let root: string;
let conn: Connection;

async function startDaemon(): Promise<{ port: number; token: string; startId: string }> {
  nodeDeps({ client: CLIENT, locateCli: () => ({ path: REPO_CLI, tried: [REPO_CLI] }) }).spawn(REPO_CLI, root);
  await expect.poll(() => readSession(root)?.port ?? null, { timeout: 30_000 }).not.toBeNull();
  const s = JSON.parse(fs.readFileSync(path.join(root, ".kookabug", "session.json"), "utf8")) as {
    port: number;
    token: string;
    start_id: string;
  };
  return { port: s.port, token: s.token, startId: s.start_id };
}

/** 렌더러 문서 표 흉내: 버퍼(값·dirty·실행 취소·base_revision)는 여기 있고 doc_id만 바뀐다 */
function makeHost(buffers: Map<string, Buffer>): DocHost & { validated: number } {
  const host = {
    validated: 0,
    docs: () => [...buffers].map(([p, b]) => ({ path: p, baseRevision: b.base, dirty: b.dirty })),
    rebind: (p: string, r: GraphOpenResult) => {
      buffers.get(p)!.docId = r.doc_id;
    },
    conflict: (p: string) => {
      throw new Error(`디스크가 같아 충돌이 아니다: ${p}`);
    },
    reload: (p: string) => {
      throw new Error(`디스크가 같아 다시 열지 않는다: ${p}`);
    },
    failed: (p: string, e: { message: string }) => {
      throw new Error(`다시 열기 실패: ${p} ${e.message}`);
    },
    validateAll: () => {
      host.validated++;
    },
  };
  return host;
}

/** 지금 연결(conn)로 보내는 호출. interruptAt 경로를 처음 열 때 소켓을 실제로 닫는다 */
function routedCall(calls: string[], interruptAt: string | null): RpcCall {
  let interrupted = false;
  return (async (method: string, params: { path: string }) => {
    calls.push(params.path);
    if (params.path === interruptAt && !interrupted) {
      interrupted = true;
      conn.close();
      await conn.closed;
      throw notConnected().toShape();
    }
    return conn.call(method, params);
  }) as unknown as RpcCall;
}

/** 모든 버퍼를 지금 연결에서 검증하고, dirty 버퍼는 기준 revision으로 저장해 본다 */
async function usable(buffers: Map<string, Buffer>): Promise<Record<string, string>> {
  const out: Record<string, string> = {};
  for (const [p, b] of buffers) {
    try {
      await conn.call("graph.validate", { doc_id: b.docId, value: b.value, seq: 1 });
      if (b.dirty) await conn.call("graph.save", { doc_id: b.docId, value: b.value, base_revision: b.base });
      out[p] = "ok";
    } catch (err) {
      out[p] = String((err as { kind?: string }).kind ?? (err as Error).message);
    }
  }
  return out;
}

test.beforeEach(() => {
  root = copySampleWorkspace("recovery");
});

test.afterEach(async () => {
  try {
    await conn?.call("daemon.shutdown", { force: true });
  } catch {
    // 이미 끝남
  }
  conn?.close();
  await cleanupWorkspace(root);
});

/** 첫 연결에서 문서를 열고 하나는 편집 중으로 만든다 */
async function openBuffers(): Promise<Map<string, Buffer>> {
  const buffers = new Map<string, Buffer>();
  for (const p of FILES) {
    const r = (await conn.call("graph.open", { path: p })) as GraphOpenResult;
    buffers.set(p, { docId: r.doc_id, value: r.value as Record<string, unknown>, base: r.revision, dirty: false, undo: [] });
  }
  const first = buffers.get(FILES[0])!;
  first.value = { ...first.value, meta: { ...(first.value.meta as object), title: "편집한 제목" } };
  first.dirty = true;
  first.undo.push("제목 바꾸기");
  return buffers;
}

test("test_same_daemon_new_connection_reopens_all_docs_real_daemon", async () => {
  const s = await startDaemon();
  conn = await connectDaemon(s.port, s.token, CLIENT);
  const buffers = await openBuffers();
  const before = new Map([...buffers].map(([p, b]) => [p, b.docId]));
  const calls: string[] = [];
  const recovery = new SessionRecovery(routedCall(calls, null));
  const host = makeHost(buffers);
  recovery.addDocs(host);
  expect(await recovery.connected({ root, startId: s.startId, connection: 1 })).toBe("first");

  // 일시적인 끊김: 같은 daemon(같은 start_id)에 새 연결로 다시 붙는다
  conn.close();
  await conn.closed;
  conn = await connectDaemon(s.port, s.token, CLIENT);
  // 옛 doc_id는 daemon이 지웠다
  await expect(conn.call("graph.validate", { doc_id: before.get(FILES[1]), value: {}, seq: 1 })).rejects.toMatchObject({
    kind: "doc_not_open",
  });
  expect(await recovery.connected({ root, startId: s.startId, connection: 2 })).toBe("same_daemon");
  expect(calls).toEqual(FILES);
  expect(host.validated).toBe(1);
  expect(await usable(buffers)).toEqual({ [FILES[0]]: "ok", [FILES[1]]: "ok" });
  expect(buffers.get(FILES[0])).toMatchObject({ dirty: true, undo: ["제목 바꾸기"] });
});

test("test_reopen_interrupted_then_next_connection_all_docs_usable_real_daemon", async () => {
  const s = await startDaemon();
  conn = await connectDaemon(s.port, s.token, CLIENT);
  const buffers = await openBuffers();
  const calls: string[] = [];
  const recovery = new SessionRecovery(routedCall(calls, FILES[1]));
  const host = makeHost(buffers);
  recovery.addDocs(host);
  // 앞 daemon(다른 start_id)에서 이 daemon으로 바뀐 것으로 시작한다: 첫 문서는 열리고 둘째 문서 직전에 끊긴다
  await recovery.connected({ root, startId: "0".repeat(32), connection: 1 });
  expect(await recovery.connected({ root, startId: s.startId, connection: 2 })).toBe("daemon_replaced");
  expect(calls).toEqual([FILES[0], FILES[1]]);
  expect(host.validated).toBe(0);

  conn = await connectDaemon(s.port, s.token, CLIENT);
  expect(await recovery.connected({ root, startId: s.startId, connection: 3 })).toBe("same_daemon");
  // 앞 연결에서 성공했던 문서도 이 연결에서 다시 연다
  expect(calls).toEqual([FILES[0], FILES[1], FILES[0], FILES[1]]);
  expect(host.validated).toBe(1);
  // 먼저 성공한 문서와 나중에 다시 연 문서 모두 실제 daemon에서 검증·저장된다
  expect(await usable(buffers)).toEqual({ [FILES[0]]: "ok", [FILES[1]]: "ok" });
  expect(buffers.get(FILES[0])).toMatchObject({ dirty: true, undo: ["제목 바꾸기"] });
  expect(fs.readFileSync(path.join(root, FILES[0]), "utf8")).toContain("편집한 제목");
});
