// 녹화 단축키 (M4 계획 2.4·2.9 "시작 순서", T9). Electron globalShortcut으로 녹화 중에만 등록한다.
// - 등록(arm): 정지 Ctrl+Shift+R·비밀값 표시 Ctrl+Shift+P 둘 다 성공해야 한다. 하나라도 실패하면 이미 한 것을 풀고
//   실패로 돌려준다 — 렌더러는 recorder.start를 보내지 않는다
// - recorder.start 문지기(guardRecorderCall): 주 프로세스가 등록에 성공한 상태가 아니면 daemon에 보내지 않고
//   거부한다(hotkey_unavailable). 보낼 때 hotkeys는 주 프로세스가 등록한 목록으로 바꿔 넣는다. 시작이 실패하면 푼다
// - 해제: 녹화가 끝남(recorder.changed state가 starting·recording·paused가 아님)·daemon 연결 끊김·앱 종료
// 등록한 단축키는 다른 앱(게임)에 가지 않는다. 저수준 훅은 그 전에 보므로 daemon 변환기가 그 조합을 지운다 (C13).
// 비밀값 표시는 daemon이 훅 이벤트로 처리한다(받은 hotkeys의 mark_secret) — 여기서는 게임에 가지 않게만 잡는다.
// electron을 import하지 않는다 (vitest)
import { LOCAL_ERROR, RpcFailure } from "./rpc-connection";

export interface RecorderHotkey {
  keys: string;
  role: "stop" | "mark_secret";
}

export const RECORDER_HOTKEYS: readonly (RecorderHotkey & { accelerator: string; label: string })[] = [
  { accelerator: "CommandOrControl+Shift+R", keys: "ctrl+shift+r", role: "stop", label: "Ctrl+Shift+R" },
  { accelerator: "CommandOrControl+Shift+P", keys: "ctrl+shift+p", role: "mark_secret", label: "Ctrl+Shift+P" },
];

/** 녹화 중(단축키를 쥐는) 상태 */
const LIVE_STATES: ReadonlySet<string> = new Set(["starting", "recording", "paused"]);

export interface ShortcutHost {
  /** 등록 (Electron globalShortcut.register: 다른 앱이 쥐고 있으면 false) */
  register(accelerator: string, callback: () => void): boolean;
  unregister(accelerator: string): void;
}

export type ArmResult = { ok: true; hotkeys: RecorderHotkey[] } | { ok: false; failed: string; message: string };

export class RecorderShortcuts {
  private readonly registered = new Set<string>();

  constructor(
    private readonly host: ShortcutHost,
    private readonly onStop: () => void,
  ) {}

  get armed(): boolean {
    return this.registered.size === RECORDER_HOTKEYS.length;
  }

  /** 등록한 단축키 (recorder.start hotkeys) */
  hotkeys(): RecorderHotkey[] {
    return RECORDER_HOTKEYS.filter((h) => this.registered.has(h.accelerator)).map(({ keys, role }) => ({ keys, role }));
  }

  /** 지금 등록된 가속기 (E2E 확인용) */
  accelerators(): string[] {
    return [...this.registered];
  }

  /**
   * 등록했고 recorder.start 응답을 아직 받지 않음: 그사이 도착한 앞 세션의 끝 알림(discarded 등)으로 풀지 않는다.
   * 시작 응답·실패·연결 끊김·disarm이 이 표시를 지운다
   */
  private startPending = false;

  setStartPending(on: boolean): void {
    this.startPending = on && this.armed;
  }

  /**
   * 등록을 쥔 녹화 세션 (recorder.start 응답의 session). 알면 그 세션의 알림·결과만 해제를 정한다 —
   * 지난 세션의 늦은 알림(임시 파일 정리 등)이 새 녹화 단축키를 풀지 않게 (SECFIX 3)
   */
  private session: string | null = null;

  setSession(session: unknown): void {
    this.session = typeof session === "string" ? session : null;
  }

  arm(): ArmResult {
    if (this.armed) {
      this.startPending = true;
      return { ok: true, hotkeys: this.hotkeys() };
    }
    for (const h of RECORDER_HOTKEYS) {
      if (this.registered.has(h.accelerator)) continue;
      let ok = false;
      try {
        ok = this.host.register(h.accelerator, h.role === "stop" ? () => this.onStop() : () => {});
      } catch {
        ok = false;
      }
      if (!ok) {
        this.disarm();
        return {
          ok: false,
          failed: h.keys,
          message: `단축키 ${h.label}을(를) 다른 프로그램이 쓰고 있어 녹화를 시작하지 않았어요`,
        };
      }
      this.registered.add(h.accelerator);
    }
    this.startPending = true;
    return { ok: true, hotkeys: this.hotkeys() };
  }

  disarm(): void {
    this.startPending = false;
    this.session = null;
    for (const accelerator of [...this.registered]) {
      try {
        this.host.unregister(accelerator);
      } catch {
        // 이미 풀림
      }
      this.registered.delete(accelerator);
    }
  }

  /** recorder.changed·recorder.* 결과의 state(와 session): 쥔 녹화가 끝났으면 푼다. 쥔 세션을 알면 다른 세션 알림은 무시 */
  onRecorderState(state: unknown, session?: unknown): void {
    if (this.startPending) return;
    if (this.session !== null && session !== this.session) return;
    if (typeof state === "string" && !LIVE_STATES.has(state)) this.disarm();
  }

  /** daemon 연결 상태: 연결이 끊기면 세션은 버려진다(U9) — 푼다 */
  onConnection(status: string): void {
    if (status !== "connected") this.disarm();
  }
}

export type RecorderCall = (method: string, params: unknown, paramsText: string) => Promise<unknown>;

/**
 * daemon 호출 앞의 녹화 문지기. recorder.start는 단축키가 등록된 상태에서만 보내고(hotkeys는 등록 목록으로),
 * 실패하면 등록을 푼다. 녹화 메서드 결과의 state로도 해제를 판단한다
 */
export function guardRecorderCall(call: RecorderCall, shortcuts: RecorderShortcuts, stringify: (v: unknown) => string): RecorderCall {
  return async (method, params, paramsText) => {
    if (method !== "recorder.start") {
      const result = await call(method, params, paramsText);
      if (method.startsWith("recorder.") && typeof result === "object" && result !== null && "state" in result) {
        const r = result as { state: unknown; session?: unknown };
        shortcuts.onRecorderState(r.state, r.session);
      }
      return result;
    }
    if (!shortcuts.armed) {
      throw new RpcFailure(LOCAL_ERROR, "녹화 단축키를 등록하지 않아 녹화를 시작하지 않았어요", { code: "hotkey_unavailable" });
    }
    const base = typeof params === "object" && params !== null ? (params as Record<string, unknown>) : {};
    const sent = { ...base, hotkeys: shortcuts.hotkeys() };
    try {
      const result = await call(method, sent, stringify(sent));
      const r = result as { state?: unknown; session?: unknown } | null;
      shortcuts.setStartPending(false);
      shortcuts.setSession(r?.session);
      shortcuts.onRecorderState(r?.state, r?.session);
      return result;
    } catch (err) {
      shortcuts.disarm();
      throw err;
    }
  };
}
