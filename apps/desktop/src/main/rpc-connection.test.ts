// 받는 쪽을 달기 전에 온 알림 (T11 검수 1차 Mid): daemon은 hello 응답 바로 뒤에 지금 임대권 소유자를 한 번
// 보낸다. 주 프로세스는 hello 응답을 기다린 다음에 연결을 채택하고 받는 쪽을 단다. 두 프레임이 연달아 와도
// 알림을 잃지 않고, 채택하는 쪽의 동기 구간(연결됨 상태 알리기) 뒤에 넘긴다
import { describe, expect, test } from "vitest";
import { RpcConnection, type SocketLike } from "./rpc-connection";

class FakeSocket implements SocketLike {
  sent: string[] = [];
  private message: (data: string | null) => void = () => {};
  private closed: () => void = () => {};
  send(text: string): void {
    this.sent.push(text);
  }
  close(): void {
    this.closed();
  }
  onMessage(cb: (data: string | null) => void): void {
    this.message = cb;
  }
  onClose(cb: () => void): void {
    this.closed = cb;
  }
  deliver(message: unknown): void {
    this.message(JSON.stringify(message));
  }
}

const HELLO = { protocol: 1, daemon_version: "0", start_id: "s", workspace: "C:/ws", principal: { kind: "user", id: "ui:1", attended: true } };
const OWNER = { kind: "runner", run_id: "abcd1234", pid: 7, created: "133000000000000000" };

describe("받는 쪽이 생기기 전 알림", () => {
  test("test_lease_right_after_hello_delivered_after_adopt", async () => {
    const socket = new FakeSocket();
    const rpc = new RpcConnection(socket);
    const hello = rpc.call("session.hello", { token: "t", protocol: 1, client: { kind: "ui", name: "x", version: "0" } });
    const id = (JSON.parse(socket.sent[0]) as { id: number }).id;
    // 응답과 알림이 같은 틈에 연달아 온다 (받는 쪽은 아직 없다)
    socket.deliver({ jsonrpc: "2.0", id, result: HELLO });
    socket.deliver({ jsonrpc: "2.0", method: "lease.changed", params: { owner: OWNER } });
    await hello;
    // 채택: 받는 쪽을 달고 같은 동기 구간에서 연결됨을 알린다 (DaemonManager.adopt 순서)
    const order: string[] = [];
    rpc.onNotification((method, params) => order.push(`${method}:${JSON.stringify(params)}`));
    order.push("state:connected");
    expect(order).toEqual(["state:connected"]);
    await Promise.resolve();
    expect(order).toEqual(["state:connected", `lease.changed:${JSON.stringify({ owner: OWNER })}`]);
    // 받는 쪽이 생긴 뒤 알림은 바로 넘긴다 (한 번씩만)
    socket.deliver({ jsonrpc: "2.0", method: "lease.changed", params: { owner: null } });
    expect(order).toHaveLength(3);
    expect(order[2]).toBe(`lease.changed:${JSON.stringify({ owner: null })}`);
    expect(rpc.dropped).toEqual([]);
  });

  test("닫힌 뒤에는 쌓인 알림을 넘기지 않는다", async () => {
    const socket = new FakeSocket();
    const rpc = new RpcConnection(socket);
    socket.deliver({ jsonrpc: "2.0", method: "lease.changed", params: { owner: null } });
    const got: string[] = [];
    rpc.onNotification((m) => got.push(m));
    rpc.close();
    await Promise.resolve();
    expect(got).toEqual([]);
  });
});
