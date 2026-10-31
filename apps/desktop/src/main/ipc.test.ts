// IPC 다리의 메서드·params·알림 런타임 검사 (M2 계획 2.10, 검수 M9, 2차 검수 N3)
import { METHODS, NOTIFICATIONS } from "@kookabug/schema";
import { describe, expect, test } from "vitest";
import { createNotificationForwarder, createRpcHandler } from "./ipc";
import { INTERNAL_METHODS, RENDERER_EVENTS, RENDERER_METHODS } from "./ipc-guard";
import { RpcConnection, RpcFailure, type SocketLike } from "./rpc-connection";

const REV = "a".repeat(64);

function recorder(result: unknown = { ok: 1 }) {
  const sent: [string, unknown, string][] = [];
  const handler = createRpcHandler(async (method, params, text) => {
    sent.push([method, params, text]);
    return result;
  });
  return { sent, handler };
}

class FakeSocket implements SocketLike {
  readonly frames: string[] = [];
  closed = false;
  private messageCb: (d: string | null) => void = () => {};
  private closeCb: () => void = () => {};
  send(text: string) {
    this.frames.push(text);
  }
  close() {
    this.closed = true;
    this.closeCb();
  }
  onMessage(cb: (d: string | null) => void) {
    this.messageCb = cb;
  }
  onClose(cb: () => void) {
    this.closeCb = cb;
  }
  receive(data: string | null) {
    this.messageCb(data);
  }
}

describe("메서드 표", () => {
  test("렌더러 허용 목록 = 계약 표의 renderer 메서드, 내부 메서드 제외", () => {
    const fromSchema = Object.entries(METHODS)
      .filter(([, info]) => info.renderer)
      .map(([name]) => name)
      .sort();
    expect([...RENDERER_METHODS].sort()).toEqual(fromSchema);
    for (const m of INTERNAL_METHODS) expect(METHODS[m as keyof typeof METHODS].renderer).toBe(false);
    // 알림 허용 목록은 계약의 알림 이름 안에 있다
    for (const n of RENDERER_EVENTS) expect(Object.keys(NOTIFICATIONS)).toContain(n);
  });
});

describe("rpc 처리기", () => {
  test("test_params_schema_checked_per_method", async () => {
    const { sent, handler } = recorder();
    // 메서드마다 그 params 스키마로 본다
    const cases: [string, unknown, boolean][] = [
      ["graph.open", { path: "tests/a.graph.json" }, true],
      ["graph.open", { path: "" }, false], // minLength
      ["graph.open", { path: 3 }, false],
      ["graph.open", {}, false], // required
      ["workspace.tree", undefined, true], // 생략 = 빈 객체
      ["workspace.tree", { extra: 1 }, false], // additionalProperties
      ["run.subscribe", { run_id: "abcd1234", after_seq: 0 }, true],
      ["run.subscribe", { run_id: "abcd1234", after_seq: -1 }, false],
      ["run.subscribe", { run_id: "ABCD1234", after_seq: 0 }, false], // pattern
      ["run.subscribe", { run_id: "abcd1234", after_seq: 1.5 }, false], // integer
      ["graph.save", { doc_id: "d1", value: {}, base_revision: REV }, true],
      ["graph.save", { doc_id: "d1", value: {}, base_revision: "x" }, false],
      ["graph.save", { doc_id: "d1", value: [], base_revision: REV }, false],
    ];
    for (const [method, params, ok] of cases) {
      const reply = await handler(method, params);
      expect(reply.ok, `${method} ${JSON.stringify(params)}`).toBe(ok);
      if (!reply.ok) {
        expect(reply.error).toMatchObject({ code: -32602, data: { code: "invalid_params" } });
        expect((reply.error.data as { issues: unknown[] }).issues.length).toBeGreaterThan(0);
      }
    }
    expect(sent.map(([m]) => m)).toEqual(["graph.open", "workspace.tree", "run.subscribe", "graph.save"]);
  });

  test("test_invalid_params_rejected_not_forwarded", async () => {
    const { sent, handler } = recorder();
    const bad: [unknown, unknown][] = [
      ["graph.open", { path: "a", extra: true }],
      ["graph.open", "tests/a.graph.json"],
      ["graph.open", null],
      ["target.save", { path: "targets/a.target.json", spec: {}, base_revision: null, crop: { frame_id: "f", rect: [0, 0] } }],
      ["session.hello", { token: "x" }], // 내부 메서드
      ["daemon.shutdown", {}],
      ["nope.method", {}],
      [42, {}],
    ];
    for (const [method, params] of bad) {
      const reply = await handler(method, params);
      expect(reply.ok, String(method)).toBe(false);
    }
    expect(sent).toEqual([]);
    // 함수·undefined 값·빈 칸 배열처럼 JSON이 아닌 값도 보내지 않는다
    expect((await handler("graph.save", { doc_id: "d", value: { f: () => 1 }, base_revision: REV })).ok).toBe(false);
    expect((await handler("graph.save", { doc_id: "d", value: { a: [1, , 3] }, base_revision: REV })).ok).toBe(false);
    expect(sent).toEqual([]);
  });

  test("test_non_finite_value_not_sent_error_returned", async () => {
    // 실제 RpcConnection까지 이어 붙여 소켓에 아무것도 가지 않는지 본다
    const socket = new FakeSocket();
    const conn = new RpcConnection(socket);
    const handler = createRpcHandler((method, params, text) => conn.call(method, params, text));
    for (const [bad, pointer] of [
      [Number.NaN, "/value/nodes/n_1/in/x"],
      [Number.POSITIVE_INFINITY, "/value/nodes/n_1/in/x"],
      [Number.NEGATIVE_INFINITY, "/value/nodes/n_1/in/x"],
    ] as const) {
      const value = { format: "kookabug.graph/0", nodes: { n_1: { type: "core.wait", in: { x: bad } } } };
      const reply = await handler("graph.save", { doc_id: "d1", value, base_revision: REV });
      expect(reply).toMatchObject({ ok: false, error: { code: -32602, data: { code: "number_not_finite", pointer } } });
    }
    // 배열 안
    const inArray = await handler("graph.validate", { doc_id: "d1", value: { list: [1, [2, Number.NaN]] }, seq: 1 });
    expect(inArray).toMatchObject({ ok: false, error: { data: { code: "number_not_finite", pointer: "/value/list/1/1" } } });
    expect(socket.frames).toEqual([]);
  });

  test("큰 실수는 지수 표기로 보낸다 (전송 코덱)", async () => {
    const socket = new FakeSocket();
    const conn = new RpcConnection(socket);
    const handler = createRpcHandler((method, params, text) => conn.call(method, params, text));
    const pending = handler("graph.validate", { doc_id: "d1", value: { big: 1e20, max: 2 ** 53 }, seq: 7 });
    await Promise.resolve();
    expect(socket.frames).toHaveLength(1);
    expect(socket.frames[0]).toContain('"big":1e+20');
    expect(socket.frames[0]).toContain('"max":9.007199254740992e+15');
    const id = (JSON.parse(socket.frames[0]) as { id: number }).id;
    socket.receive(JSON.stringify({ jsonrpc: "2.0", id, result: { seq: 7, diagnostics: [], shapes: {} } }));
    expect(await pending).toEqual({ ok: true, result: { seq: 7, diagnostics: [], shapes: {} } });
  });

  test("daemon 오류는 code·data 그대로 렌더러에 간다", async () => {
    const handler = createRpcHandler(async () => {
      throw new RpcFailure(-32100, "충돌", { code: "revision_conflict", revision: REV });
    });
    expect(await handler("graph.save", { doc_id: "d", value: {}, base_revision: REV })).toEqual({
      ok: false,
      error: { code: -32100, message: "충돌", data: { code: "revision_conflict", revision: REV } },
    });
  });
});

describe("알림", () => {
  test("test_only_allowlisted_notifications_forwarded", () => {
    const sent: [string, unknown][] = [];
    const forward = createNotificationForwarder((name, params) => sent.push([name, params]));
    for (const name of RENDERER_EVENTS) expect(forward(name, { x: 1 })).toBe(true);
    for (const name of ["session.hello", "daemon.state", "kb:rpc", "__proto__", "run.events", ""]) {
      expect(forward(name, {}), name).toBe(false);
    }
    expect(sent.map(([n]) => n).sort()).toEqual([...RENDERER_EVENTS].sort());
  });
});

describe("RpcConnection 수신 검사", () => {
  function open() {
    const socket = new FakeSocket();
    const conn = new RpcConnection(socket);
    const notes: [string, unknown][] = [];
    conn.onNotification((m, p) => notes.push([m, p]));
    return { socket, conn, notes };
  }

  test("계약에 맞지 않는 알림 params는 버리고, 맞는 것만 넘긴다", () => {
    const { socket, notes, conn } = open();
    socket.receive(JSON.stringify({ jsonrpc: "2.0", method: "workspace.changed", params: { paths: ["a"] } }));
    socket.receive(JSON.stringify({ jsonrpc: "2.0", method: "workspace.changed", params: { paths: "a" } }));
    expect(notes).toEqual([["workspace.changed", { paths: ["a"] }]]);
    expect(conn.isOpen).toBe(true);
  });

  test("result가 계약에 맞지 않으면 거부한다", async () => {
    const { socket, conn } = open();
    const p = conn.call("workspace.tree", {});
    socket.receive(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { entries: "x" } }));
    await expect(p).rejects.toMatchObject({ code: -32603 });
  });

  test("바이너리·JSON 아님·봉투 위반은 연결을 닫고 기다리던 요청을 끝낸다", async () => {
    for (const frame of [null, "{nope", JSON.stringify({ jsonrpc: "1.0", id: 1, result: {} })]) {
      const { socket, conn } = open();
      const p = conn.call("workspace.info", {});
      socket.receive(frame);
      expect(socket.closed).toBe(true);
      await expect(p).rejects.toMatchObject({ kind: "not_connected" });
      expect(conn.isOpen).toBe(false);
    }
  });
});
