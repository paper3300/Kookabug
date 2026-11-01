import { EventEmitter } from "node:events";
import { describe, expect, test, vi } from "vitest";
import { createBridge, type IpcRendererLike } from "../preload/bridge";
import {
  APP_ACTIONS,
  APP_CHANNEL,
  checkRendererMethod,
  checkSender,
  EVENT_CHANNEL,
  INTERNAL_METHODS,
  IpcGuardError,
  RENDERER_METHODS,
  RPC_CHANNEL,
  type FrameLike,
} from "./ipc-guard";

const ORIGIN = "app://app";
const mainFrame: FrameLike = { url: `${ORIGIN}/index.html`, processId: 4, routingId: 1 };

class FakeIpc extends EventEmitter implements IpcRendererLike {
  calls: unknown[][] = [];
  constructor() {
    super();
    this.setMaxListeners(0);
  }
  invoke(channel: string, ...args: unknown[]): Promise<unknown> {
    this.calls.push([channel, ...args]);
    // 주 프로세스 처리기는 결과를 봉투로 돌려준다 (ipc.ts)
    if (channel === APP_CHANNEL) return Promise.resolve("app-ok");
    return Promise.resolve({ ok: true, result: "ok" });
  }
}

describe("sender", () => {
  test("accepts the app main frame", () => {
    expect(() => checkSender(mainFrame, mainFrame, ORIGIN)).not.toThrow();
    // 같은 프레임을 가리키는 다른 래퍼 객체
    expect(() => checkSender({ ...mainFrame }, mainFrame, ORIGIN)).not.toThrow();
  });

  test("test_rejects_non_main_frame_sender", () => {
    const iframe: FrameLike = { url: `${ORIGIN}/index.html`, processId: 4, routingId: 7 };
    const otherProcess: FrameLike = { url: `${ORIGIN}/index.html`, processId: 9, routingId: 1 };
    const noIds = { url: `${ORIGIN}/index.html` } as unknown as FrameLike;
    expect(() => checkSender(noIds, { ...noIds }, ORIGIN)).toThrow(IpcGuardError);
    for (const frame of [iframe, otherProcess, null, undefined]) {
      expect(() => checkSender(frame, mainFrame, ORIGIN)).toThrow(IpcGuardError);
    }
    // 창이 없으면(닫힘) 거부
    expect(() => checkSender(mainFrame, null, ORIGIN)).toThrow(IpcGuardError);
  });

  test("test_rejects_non_app_url_sender", () => {
    for (const url of [
      "https://example.com/",
      "file:///C:/index.html",
      "app://other/index.html",
      "app://application/index.html",
      "about:blank",
      "",
    ]) {
      const frame = { ...mainFrame, url };
      expect(() => checkSender(frame, { ...mainFrame, url }, ORIGIN), url).toThrow(IpcGuardError);
    }
  });
});

describe("bridge", () => {
  test("test_internal_methods_not_exposed", async () => {
    const ipc = new FakeIpc();
    const bridge = createBridge(ipc);
    expect(Object.keys(bridge).sort()).toEqual(["app", "on", "rpc"]);
    for (const method of ["session.hello", "daemon.shutdown", "run.export"]) {
      expect(INTERNAL_METHODS.has(method)).toBe(true);
      expect(RENDERER_METHODS.has(method)).toBe(false);
      expect(() => checkRendererMethod(method)).toThrow(IpcGuardError);
      await expect(bridge.rpc(method, {})).rejects.toThrow(IpcGuardError);
    }
    await expect(bridge.rpc("nope.method")).rejects.toThrow(IpcGuardError);
    await expect(bridge.rpc(42 as unknown as string)).rejects.toThrow(IpcGuardError);
    expect(ipc.calls).toEqual([]);

    await expect(bridge.rpc("graph.open", { path: "tests/a.graph.json" })).resolves.toBe("ok");
    expect(ipc.calls).toEqual([[RPC_CHANNEL, "graph.open", { path: "tests/a.graph.json" }]]);
  });

  test("test_unknown_event_name_rejected", () => {
    const ipc = new FakeIpc();
    const bridge = createBridge(ipc);
    for (const name of ["kb:rpc", "session.hello", "run.events", "", "__proto__"]) {
      expect(() => bridge.on(name, () => {}), name).toThrow(IpcGuardError);
    }
    expect(ipc.listenerCount(EVENT_CHANNEL)).toBe(0);
  });

  test("test_callback_gets_data_only_and_off_removes_listener", () => {
    const ipc = new FakeIpc();
    const bridge = createBridge(ipc);
    const cb = vi.fn();
    const off = bridge.on("run.event", cb);
    const sender = { send: () => {}, id: 1 };
    ipc.emit(EVENT_CHANNEL, { sender, ports: [] }, "run.event", { run_id: "r1", seq: 3 });
    ipc.emit(EVENT_CHANNEL, { sender }, "run.ended", { run_id: "r1" }); // 다른 알림
    expect(cb).toHaveBeenCalledTimes(1);
    expect(cb.mock.calls[0]).toEqual([{ run_id: "r1", seq: 3 }]);
    off();
    off(); // 두 번 불러도 다른 리스너를 지우지 않는다
    expect(ipc.listenerCount(EVENT_CHANNEL)).toBe(0);

    // 같은 콜백 100번 등록·해제
    const offs = Array.from({ length: 100 }, () => bridge.on("run.event", cb));
    expect(ipc.listenerCount(EVENT_CHANNEL)).toBe(100);
    for (const o of offs) o();
    expect(ipc.listenerCount(EVENT_CHANNEL)).toBe(0);
    ipc.emit(EVENT_CHANNEL, { sender }, "run.event", { seq: 4 });
    expect(cb).toHaveBeenCalledTimes(1);
  });

  test("rpc 오류 봉투는 평범한 객체로 거부된다 (contextBridge 복제)", async () => {
    const ipc = new FakeIpc();
    ipc.invoke = async () => ({ ok: false, error: { code: -32100, message: "충돌", data: { code: "revision_conflict" } } });
    const bridge = createBridge(ipc);
    const err = await bridge.rpc("graph.open", { path: "a" }).catch((e: unknown) => e);
    expect(err).toEqual({ code: -32100, message: "충돌", data: { code: "revision_conflict" } });
    expect(err).not.toBeInstanceOf(Error);
  });

  test("앱 API는 허용한 동작만 앱 채널로 보낸다", async () => {
    const ipc = new FakeIpc();
    const bridge = createBridge(ipc);
    expect(Object.keys(bridge.app).sort()).toEqual([...APP_ACTIONS].sort());
    await expect(bridge.app.themeSet("dark")).resolves.toBe("app-ok");
    expect(ipc.calls).toEqual([[APP_CHANNEL, "themeSet", "dark"]]);
    // 앱 알림은 구독할 수 있다
    expect(() => bridge.on("daemon.state", () => {})).not.toThrow();
  });
});
