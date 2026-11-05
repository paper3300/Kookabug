// 녹화 단축키 (M4 계획 T9 완료 기준 shortcuts.test.ts): 녹화 중에만 등록, 정지·연결 끊김·앱 종료에 해제, 등록 실패면
// recorder.start를 보내지 않음, 시작 실패면 등록 해제 — 입력 안전(단축키가 남아 다른 앱 입력을 먹지 않게)
import { describe, expect, test } from "vitest";
import { RpcFailure } from "./rpc-connection";
import { guardRecorderCall, RECORDER_HOTKEYS, RecorderShortcuts, type ShortcutHost } from "./shortcuts";

class FakeHost implements ShortcutHost {
  readonly held = new Map<string, () => void>();
  /** 다른 앱이 쥔 가속기 (등록 실패) */
  readonly busy = new Set<string>();
  register(accelerator: string, callback: () => void): boolean {
    if (this.busy.has(accelerator) || this.held.has(accelerator)) return false;
    this.held.set(accelerator, callback);
    return true;
  }
  unregister(accelerator: string): void {
    this.held.delete(accelerator);
  }
  press(accelerator: string): void {
    this.held.get(accelerator)?.();
  }
}

function rig() {
  const host = new FakeHost();
  let stops = 0;
  const shortcuts = new RecorderShortcuts(host, () => stops++);
  const sent: { method: string; params: unknown }[] = [];
  let reply: (method: string) => unknown = () => ({ state: "recording", owned: true });
  const call = guardRecorderCall(
    async (method, params) => {
      sent.push({ method, params });
      const r = reply(method);
      if (r instanceof Error) throw r;
      return r;
    },
    shortcuts,
    JSON.stringify,
  );
  return {
    host,
    shortcuts,
    sent,
    call,
    stops: () => stops,
    setReply(fn: (method: string) => unknown) {
      reply = fn;
    },
  };
}

const STOP = RECORDER_HOTKEYS[0].accelerator;
const SECRET = RECORDER_HOTKEYS[1].accelerator;

describe("녹화 단축키", () => {
  test("녹화 전에는 등록하지 않고, 시작 순서는 등록 → recorder.start(등록한 목록)", async () => {
    const r = rig();
    expect(r.host.held.size).toBe(0);
    const armed = r.shortcuts.arm();
    expect(armed).toEqual({
      ok: true,
      hotkeys: [
        { keys: "ctrl+shift+r", role: "stop" },
        { keys: "ctrl+shift+p", role: "mark_secret" },
      ],
    });
    expect([...r.host.held.keys()]).toEqual([STOP, SECRET]);
    // 렌더러가 다른 hotkeys를 보내도 주 프로세스가 등록한 목록으로 바꾼다
    await r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}");
    expect(r.sent[0]).toEqual({ method: "recorder.start", params: { launch: {}, hotkeys: armed.ok ? armed.hotkeys : [] } });
  });

  test("등록 실패면 recorder.start를 보내지 않고 이미 등록한 것도 푼다", async () => {
    const r = rig();
    r.host.busy.add(SECRET);
    const armed = r.shortcuts.arm();
    expect(armed.ok).toBe(false);
    if (!armed.ok) expect(armed.message).toContain("Ctrl+Shift+P");
    expect(r.host.held.size).toBe(0);
    await expect(r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}")).rejects.toMatchObject({
      data: { code: "hotkey_unavailable" },
    });
    expect(r.sent).toEqual([]);
  });

  test("register가 던져도 실패로 보고 남기지 않는다", () => {
    const host: ShortcutHost = {
      register: (a) => {
        if (a === SECRET) throw new Error("잘못된 가속기");
        return true;
      },
      unregister: () => {},
    };
    const s = new RecorderShortcuts(host, () => {});
    expect(s.arm().ok).toBe(false);
    expect(s.armed).toBe(false);
    expect(s.accelerators()).toEqual([]);
  });

  test("시작 실패면 등록을 푼다", async () => {
    const r = rig();
    r.shortcuts.arm();
    r.setReply(() => new RpcFailure(-32000, "다른 실행이 입력을 쥐고 있다", { code: "input_lease_busy" }));
    await expect(r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}")).rejects.toBeInstanceOf(RpcFailure);
    expect(r.host.held.size).toBe(0);
    expect(r.shortcuts.armed).toBe(false);
  });

  test("정지 단축키 → 정지 콜백, 비밀값 표시는 잡기만 한다", () => {
    const r = rig();
    r.shortcuts.arm();
    r.host.press(SECRET);
    expect(r.stops()).toBe(0);
    r.host.press(STOP);
    expect(r.stops()).toBe(1);
  });

  test("정지(state stopped)·recorder.changed 끝 상태에 푼다, 일시정지는 유지", async () => {
    const r = rig();
    r.shortcuts.arm();
    await r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}");
    r.setReply(() => ({ state: "paused", owned: true }));
    await r.call("recorder.pause", {}, "{}");
    expect(r.shortcuts.armed).toBe(true);
    r.setReply(() => ({ state: "stopped", owned: true }));
    await r.call("recorder.stop", {}, "{}");
    expect(r.host.held.size).toBe(0);
    // 알림 경로 (오류 정지 hook_lost 등은 응답 없이 알림으로만 온다)
    r.setReply(() => ({ state: "recording", owned: true }));
    r.shortcuts.arm();
    await r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}");
    r.shortcuts.onRecorderState("recording");
    expect(r.shortcuts.armed).toBe(true);
    r.shortcuts.onRecorderState("stopped");
    expect(r.host.held.size).toBe(0);
  });

  test("등록 뒤 시작 응답 전에 온 앞 세션의 끝 알림으로는 풀지 않는다", async () => {
    const r = rig();
    r.shortcuts.arm();
    r.shortcuts.onRecorderState("discarded");
    r.shortcuts.onRecorderState("idle");
    expect(r.shortcuts.armed).toBe(true);
    await r.call("recorder.start", { launch: {}, hotkeys: [] }, "{}");
    expect(r.sent).toHaveLength(1);
  });

  test("연결 끊김·앱 종료(disarm)에 푼다", () => {
    const r = rig();
    r.shortcuts.arm();
    r.shortcuts.onConnection("connected");
    expect(r.shortcuts.armed).toBe(true);
    r.shortcuts.onConnection("disconnected");
    expect(r.host.held.size).toBe(0);
    r.shortcuts.arm();
    r.shortcuts.disarm();
    expect(r.host.held.size).toBe(0);
    // 두 번 풀어도 괜찮다
    r.shortcuts.disarm();
  });

  test("녹화 메서드가 아닌 호출은 그대로 지나간다", async () => {
    const r = rig();
    r.setReply(() => ({ state: "stopped" }));
    r.shortcuts.arm();
    await r.call("run.status", { run_id: "x" }, "{}");
    expect(r.shortcuts.armed).toBe(true);
  });
});
