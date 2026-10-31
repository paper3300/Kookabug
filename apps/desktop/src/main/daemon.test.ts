// daemon 관리자 (M2 계획 2.3, 검수 M2·M4): 가짜 파일·프로세스·소켓·시계로 붙기·경쟁·끊김·교체를 만든다
import { describe, expect, test } from "vitest";
import type { ResultOf } from "@kookabug/schema";
import type { RpcCall } from "../renderer/rpc/client";
import { SessionRecovery, type DocHost, type GraphOpenResult, type OpenDocRef } from "../renderer/rpc/recovery";
import { RunCursors } from "../renderer/rpc/runCursor";
import {
  APP_PROTOCOL,
  BACKOFF_MS,
  DaemonManager,
  HelloRejected,
  parseSession,
  sameWorkspacePath,
  WAIT_TIMEOUT_MS,
  type Connection,
  type DaemonDeps,
  type DaemonState,
} from "./daemon";
import { RpcFailure } from "./rpc-connection";

const ROOT = "C:/ws";
const CLI = "C:/kb/bin/kookabug.exe";

const tick = () => new Promise<void>((resolve) => setImmediate(resolve));

async function until(cond: () => boolean, what: string, limit = 5000): Promise<void> {
  for (let i = 0; i < limit; i++) {
    if (cond()) return;
    await tick();
  }
  throw new Error(`기다리다 지침: ${what}`);
}

class FakeConn implements Connection {
  readonly hello: Connection["hello"];
  readonly closed: Promise<void>;
  readonly calls: [string, unknown][] = [];
  isClosed = false;
  private resolveClosed!: () => void;
  private readonly closeCbs = new Set<() => void>();
  private readonly notifyCbs = new Set<(m: string, p: unknown) => void>();

  constructor(readonly daemon: FakeDaemon) {
    this.hello = { start_id: daemon.startId, protocol: daemon.protocol, daemon_version: "0.1.0", workspace: daemon.root };
    this.closed = new Promise((r) => (this.resolveClosed = r));
  }

  async call(method: string, params: unknown): Promise<unknown> {
    if (this.isClosed) throw new RpcFailure(-32000, "끊김", { code: "not_connected" });
    this.calls.push([method, params]);
    if (method === "daemon.shutdown") {
      if (this.daemon.runActive) {
        throw new RpcFailure(-32100, "실행 중", { code: "run_active", run_id: "abcd1234" });
      }
      queueMicrotask(() => this.daemon.shutdown());
      return {};
    }
    if (this.daemon.protocol !== APP_PROTOCOL) {
      throw new RpcFailure(-32100, "판 다름", { code: "protocol_mismatch", protocol: this.daemon.protocol });
    }
    return {};
  }

  notify(method: string, params: unknown): void {
    for (const cb of this.notifyCbs) cb(method, params);
  }

  onNotification(cb: (m: string, p: unknown) => void): () => void {
    this.notifyCbs.add(cb);
    return () => this.notifyCbs.delete(cb);
  }

  onClose(cb: () => void): void {
    this.closeCbs.add(cb);
  }

  close(): void {
    this.drop();
  }

  drop(): void {
    if (this.isClosed) return;
    this.isClosed = true;
    this.daemon.conns.delete(this);
    this.resolveClosed();
    for (const cb of this.closeCbs) cb();
  }
}

class FakeDaemon {
  readonly conns = new Set<FakeConn>();
  alive = true;
  runActive = false;

  constructor(
    readonly world: World,
    readonly root: string,
    readonly pid: number,
    readonly port: number,
    readonly token: string,
    readonly startId: string,
    readonly protocol: number,
  ) {}

  /** 프로세스가 죽음: 잠금은 풀리지만 session.json은 남는다 (오래된 파일) */
  kill(): void {
    this.alive = false;
    this.world.alive.delete(this.pid);
    for (const c of [...this.conns]) c.drop();
  }

  /** daemon.shutdown: 자기 start_id인 session.json만 지운다 */
  shutdown(): void {
    const s = parseSession(this.world.sessions.get(this.root) ?? null);
    if (s?.startId === this.startId) this.world.sessions.delete(this.root);
    this.kill();
  }
}

class World {
  readonly sessions = new Map<string, string>();
  readonly alive = new Set<number>();
  readonly daemons = new Map<number, FakeDaemon>();
  readonly sleeps: number[] = [];
  readonly spawns: string[] = [];
  readonly pending: { at: number; root: string }[] = [];
  clock = 0;
  startupMs = 300;
  /** 띄워도 daemon이 올라오지 않는다 */
  spawnNeverStarts = false;
  /** 앞으로 띄우기 N번은 실패한다 */
  spawnThrows = 0;
  /** 앞으로 연결 N번은 일시적으로 실패한다 */
  connectFailures = 0;
  nextProtocol = APP_PROTOCOL;
  private nextPid = 100;
  private nextPort = 40000;

  startDaemon(root: string, protocol = this.nextProtocol): FakeDaemon {
    const pid = this.nextPid++;
    const port = this.nextPort++;
    const n = String(pid).padStart(4, "0");
    const d = new FakeDaemon(this, root, pid, port, n.repeat(16), n.repeat(8), protocol);
    this.daemons.set(port, d);
    this.alive.add(pid);
    this.sessions.set(
      root,
      JSON.stringify({
        format: "kookabug.session/0",
        pid,
        process_created: "1",
        start_id: d.startId,
        protocol,
        daemon_version: "0.1.0",
        port,
        token: d.token,
        workspace: root,
        started_at: "2026-10-31T00:00:00.000Z",
      }),
    );
    return d;
  }

  holder(root: string): FakeDaemon | undefined {
    return [...this.daemons.values()].find((d) => d.root === root && d.alive);
  }

  deps(overrides: Partial<DaemonDeps> = {}): DaemonDeps {
    return {
      readSession: (root) => this.sessions.get(root) ?? null,
      isAlive: (pid) => this.alive.has(pid),
      connect: async (port, token) => {
        await tick();
        const d = this.daemons.get(port);
        if (!d || !d.alive) throw new Error("ECONNREFUSED");
        if (this.connectFailures > 0) {
          this.connectFailures--;
          throw new Error("일시적인 연결 실패");
        }
        if (token !== d.token) throw new Error("unauthenticated");
        const conn = new FakeConn(d);
        d.conns.add(conn);
        if (d.protocol !== APP_PROTOCOL) throw new HelloRejected("protocol_mismatch", "판 다름", d.protocol, conn);
        return conn;
      },
      locateCli: () => ({ path: CLI, tried: [CLI] }),
      spawn: (_cli, root) => {
        this.spawns.push(root);
        if (this.spawnThrows > 0) {
          this.spawnThrows--;
          throw new Error("spawn EACCES");
        }
        // 잠금: 이미 살아 있거나 올라오는 중인 daemon이 있으면 새 daemon은 지고 0으로 끝난다
        if (!this.spawnNeverStarts && !this.holder(root) && !this.pending.some((p) => p.root === root)) {
          this.pending.push({ at: this.clock + this.startupMs, root });
        }
        return { logPath: `${root}/.kookabug/logs/daemon-20261031T000000-ui.log` };
      },
      sleep: async (ms) => {
        this.clock += ms;
        this.sleeps.push(ms);
        for (const p of this.pending.filter((p) => p.at <= this.clock)) {
          this.pending.splice(this.pending.indexOf(p), 1);
          this.startDaemon(p.root);
        }
        await tick();
      },
      now: () => this.clock,
      ...overrides,
    };
  }
}

function manager(world: World, overrides: Partial<DaemonDeps> = {}) {
  const states: DaemonState[] = [];
  const notes: [string, unknown][] = [];
  const mgr = new DaemonManager(world.deps(overrides), {
    state: (s) => states.push(s),
    notification: (m, p) => notes.push([m, p]),
    log: () => {},
  });
  return { mgr, states, notes };
}

describe("붙기 순서", () => {
  test("test_attach_existing_session", async () => {
    const world = new World();
    const d = world.startDaemon(ROOT);
    const { mgr, notes } = manager(world);
    const state = await mgr.open(ROOT);
    expect(state).toMatchObject({ status: "connected", root: ROOT, startId: d.startId, protocol: APP_PROTOCOL });
    expect(world.spawns).toEqual([]);
    // 알림은 연결이 살아 있는 동안 넘긴다
    [...d.conns][0].notify("workspace.changed", { paths: ["tests/a.graph.json"] });
    expect(notes).toEqual([["workspace.changed", { paths: ["tests/a.graph.json"] }]]);
    await expect(mgr.call("workspace.info", {})).resolves.toEqual({});
  });

  test("test_stale_session_spawns_new", async () => {
    const world = new World();
    const old = world.startDaemon(ROOT);
    old.kill(); // PID가 죽었고 session.json만 남음
    const { mgr } = manager(world);
    const state = await mgr.open(ROOT);
    expect(world.spawns).toEqual([ROOT]);
    expect(state.status).toBe("connected");
    expect(state.startId).not.toBe(old.startId);
    expect(state.startId).toBe(world.holder(ROOT)!.startId);
  });

  test("test_corrupt_session_spawns_new", async () => {
    for (const text of ["{not json", "[]", '{"format":"kookabug.session/0"}', ""]) {
      const world = new World();
      world.sessions.set(ROOT, text);
      const { mgr } = manager(world);
      const state = await mgr.open(ROOT);
      expect(world.spawns, text).toEqual([ROOT]);
      expect(state.status, text).toBe("connected");
    }
    // 형식은 맞지만 토큰 모양이 틀림 → 손상과 같다
    const world = new World();
    const d = world.startDaemon(ROOT);
    world.sessions.set(ROOT, world.sessions.get(ROOT)!.replace(d.token, "zz"));
    const { mgr } = manager(world);
    await mgr.open(ROOT);
    expect(world.spawns).toEqual([ROOT]);
  });

  test("test_spawn_timeout_shows_log_path", async () => {
    const world = new World();
    world.spawnNeverStarts = true;
    const { mgr, states } = manager(world);
    const state = await mgr.open(ROOT);
    expect(state).toMatchObject({
      status: "error",
      error: "timeout",
      logPath: `${ROOT}/.kookabug/logs/daemon-20261031T000000-ui.log`,
    });
    // 15초를 0.1초 간격으로 기다렸다
    expect(world.clock).toBeGreaterThanOrEqual(WAIT_TIMEOUT_MS);
    expect(world.clock).toBeLessThan(WAIT_TIMEOUT_MS + 200);
    // 기다리는 동안에도 로그 경로를 알린다
    expect(states.some((s) => s.status === "connecting" && s.logPath === state.logPath)).toBe(true);
    await expect(mgr.call("workspace.info", {})).rejects.toMatchObject({ kind: "not_connected" });
  });

  test("CLI가 없으면 찾은 경로를 모두 알린다", async () => {
    const world = new World();
    const tried = ["E:/x/kookabug.exe", "D:/repo/.venv/Scripts/kookabug.exe"];
    const { mgr } = manager(world, { locateCli: () => ({ path: null, tried }) });
    expect(await mgr.open(ROOT)).toMatchObject({ status: "error", error: "cli_not_found", tried });
    expect(world.spawns).toEqual([]);
  });

  test("test_two_windows_spawn_race_both_attach_same_start_id", async () => {
    const world = new World();
    const a = manager(world);
    const b = manager(world);
    const [sa, sb] = await Promise.all([a.mgr.open(ROOT), b.mgr.open(ROOT)]);
    // 둘 다 띄웠지만 daemon은 하나만 이겼고, 진 쪽도 이긴 쪽 세션에 붙는다 (새 start_id를 요구하지 않음)
    expect(world.spawns).toEqual([ROOT, ROOT]);
    expect([...world.daemons.values()].filter((d) => d.alive)).toHaveLength(1);
    expect(sa.status).toBe("connected");
    expect(sb.status).toBe("connected");
    expect(sa.startId).toBe(sb.startId);
  });

  test("이미 있는 daemon에 경쟁 중 늦게 공개된 세션도 기다린다", async () => {
    // 처음 읽을 때는 session.json이 없고(이긴 쪽이 아직 공개 전), 띄운 daemon은 지고 끝난다
    const world = new World();
    world.pending.push({ at: 1000, root: ROOT });
    const { mgr } = manager(world);
    const state = await mgr.open(ROOT);
    expect(state.status).toBe("connected");
    expect([...world.daemons.values()]).toHaveLength(1);
  });
});

describe("끊김과 다시 붙기", () => {
  test("test_same_start_id_reconnect_accepted", async () => {
    const world = new World();
    const d = world.startDaemon(ROOT);
    const { mgr, states } = manager(world);
    await mgr.open(ROOT);
    const recovery = new SessionRecovery(async () => {
      throw new Error("graph.open을 보내면 안 된다");
    });
    expect(mgr.state.connection).toBe(1);
    expect(await recovery.connected({ root: ROOT, startId: mgr.state.startId!, connection: 1 })).toBe("first");
    // 연결만 끊김 (daemon은 살아 있음). 다시 붙을 때 한 번 더 일시적으로 실패하면 붙기 순서대로
    // 띄우기까지 가지만, 띄운 daemon은 잠금에서 지고 끝나며 같은 start_id에 다시 붙는 것이 정상이다
    world.connectFailures = 1;
    [...d.conns][0].drop();
    await until(() => mgr.state.status === "connected", "다시 연결");
    expect(mgr.state.startId).toBe(d.startId);
    expect(world.spawns).toEqual([ROOT]);
    expect([...world.daemons.values()].filter((x) => x.alive)).toEqual([d]);
    expect(states.some((s) => s.status === "disconnected" && s.retryInMs === BACKOFF_MS[0])).toBe(true);
    // 같은 daemon이어도 연결 번호가 바뀐다 (복구가 문서를 다시 여는 기준)
    expect(mgr.state.connection).toBe(2);
    expect(await recovery.connected({ root: ROOT, startId: mgr.state.startId!, connection: 2 })).toBe("same_daemon");
  });

  test("test_reconnect_backoff_and_resubscribe_last_applied_seq", async () => {
    const world = new World();
    const d = world.startDaemon(ROOT);
    const { mgr } = manager(world);
    await mgr.open(ROOT);

    // 렌더러 쪽: 실행 구독 커서 (적용한 마지막 seq)
    const calls: [string, unknown][] = [];
    const call = (async (method: string, params: unknown) => {
      calls.push([method, params]);
      return {};
    }) as RpcCall;
    const applied: number[] = [];
    const cursors = new RunCursors(call, (_run, seq) => applied.push(seq));
    await cursors.subscribe("run00001", 0);
    for (const seq of [1, 2, 3, 3, 2]) cursors.event("run00001", seq, {});
    expect(applied).toEqual([1, 2, 3]); // 중복·역행은 버린다
    const recovery = new SessionRecovery(call);
    recovery.addRuns(cursors);
    await recovery.connected({ root: ROOT, startId: d.startId });

    // daemon이 죽고, 다시 띄우기가 여섯 번 실패한 뒤 일곱 번째에 붙는다
    world.spawnThrows = 6;
    d.kill();
    await until(() => mgr.state.status === "connected", "다시 붙기");
    const backoff = world.sleeps.filter((ms) => ms >= 500);
    expect(backoff).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000]);
    expect(world.spawns).toHaveLength(7);
    expect(mgr.state.startId).not.toBe(d.startId);

    calls.length = 0;
    expect(await recovery.connected({ root: ROOT, startId: mgr.state.startId! })).toBe("daemon_replaced");
    // daemon이 알려 주는 seq가 아니라 렌더러가 적용한 마지막 seq부터
    expect(calls).toEqual([["run.subscribe", { run_id: "run00001", after_seq: 3 }]]);
  });

  test("빈틈·lagged는 적용한 마지막 seq부터 다시 구독한다", async () => {
    const calls: unknown[] = [];
    const cursors = new RunCursors(
      (async (_m: string, p: unknown) => {
        calls.push(p);
        return {};
      }) as RpcCall,
      () => {},
    );
    await cursors.subscribe("run00002", 5);
    expect(cursors.event("run00002", 6, {})).toBe("applied");
    expect(cursors.event("run00002", 8, {})).toBe("gap");
    expect(cursors.applied("run00002")).toBe(6);
    await tick();
    cursors.lagged("run00002");
    await tick();
    expect(calls).toEqual([
      { run_id: "run00002", after_seq: 5 },
      { run_id: "run00002", after_seq: 6 },
      { run_id: "run00002", after_seq: 6 },
    ]);
    // 끝난 실행은 다시 붙어도 다시 구독하지 않는다
    cursors.ended("run00002");
    await cursors.resubscribeAll();
    expect(calls).toHaveLength(3);
  });

  test("test_protocol_mismatch_restart_only_without_runs", async () => {
    const world = new World();
    const old = world.startDaemon(ROOT, 2);
    old.runActive = true;
    const { mgr } = manager(world);
    expect(await mgr.open(ROOT)).toMatchObject({ status: "mismatch", protocol: 2, appProtocol: APP_PROTOCOL });
    // 판이 다른 연결로는 daemon.shutdown만 보낸다. 일반 호출은 연결 없음
    await expect(mgr.call("workspace.info", {})).rejects.toMatchObject({ kind: "not_connected" });

    // 진행 중인 실행이 있으면 daemon이 거부한다 → 띄우지 않고 기다리라고 알린다
    expect(await mgr.restartDaemon()).toMatchObject({ status: "mismatch", runActive: true });
    expect(old.alive).toBe(true);
    expect(world.spawns).toEqual([]);

    // 실행이 끝나면 다시 시작할 수 있다: 종료 → 새로 띄움 → 같은 판이면 붙는다
    old.runActive = false;
    const state = await mgr.restartDaemon();
    expect(old.alive).toBe(false);
    expect(world.spawns).toEqual([ROOT]);
    expect(state.status).toBe("connected");
    expect(state.startId).not.toBe(old.startId);
  });

  test("워크스페이스를 바꾸면 앞 연결의 다시 붙기가 멈춘다", async () => {
    const world = new World();
    const d = world.startDaemon(ROOT);
    const other = world.startDaemon("C:/other");
    const { mgr } = manager(world);
    await mgr.open(ROOT);
    d.kill();
    const state = await mgr.open("C:/other");
    expect(state).toMatchObject({ status: "connected", root: "C:/other", startId: other.startId });
    for (let i = 0; i < 50; i++) await tick();
    expect(mgr.state.root).toBe("C:/other");
    expect(world.spawns).toEqual([]);
  });
});

describe("워크스페이스 일치 (검수 T7_1 High)", () => {
  const B = "C:/copy-of-ws";

  test("test_copied_live_session_of_other_workspace_not_adopted", async () => {
    // A가 실행 중일 때 A 폴더를 통째로 복사한 B를 연다: B의 session.json은 A의 살아 있는 daemon을 가리킨다
    const world = new World();
    const a = world.startDaemon(ROOT);
    world.sessions.set(B, world.sessions.get(ROOT)!);
    const { mgr } = manager(world);
    const state = await mgr.open(B);
    expect(state.status).toBe("connected");
    expect(world.spawns).toEqual([B]);
    expect(state.startId).not.toBe(a.startId);
    expect(world.holder(B)!.startId).toBe(state.startId);
    expect(a.conns.size).toBe(0); // A daemon에는 붙지 않았다
  });

  test("세션에 워크스페이스가 없어도 hello의 워크스페이스로 가려낸다", async () => {
    const world = new World();
    const a = world.startDaemon(ROOT);
    const text = JSON.parse(world.sessions.get(ROOT)!) as Record<string, unknown>;
    delete text.workspace;
    world.sessions.set(B, JSON.stringify(text));
    const { mgr } = manager(world);
    const state = await mgr.open(B);
    expect(state.status).toBe("connected");
    expect(state.startId).not.toBe(a.startId);
    expect(a.conns.size).toBe(0); // hello 뒤 바로 닫았다
  });

  test("hello의 start_id가 세션과 다르면 쓰지 않는다", async () => {
    const world = new World();
    const a = world.startDaemon(ROOT);
    world.sessions.set(ROOT, world.sessions.get(ROOT)!.replace(a.startId, "f".repeat(32)));
    const { mgr } = manager(world);
    await mgr.open(ROOT);
    // 살아 있는 a가 잠금을 쥐고 있어 새 daemon은 지고, 세션은 여전히 a와 맞지 않아 기다리다 끝난다
    expect(mgr.state).toMatchObject({ status: "error", error: "timeout" });
    expect(world.spawns).toEqual([ROOT]);
  });

  test("경로 비교는 구분자·끝 구분자·대소문자를 맞춘다", () => {
    expect(sameWorkspacePath("C:\\Ws\\Project\\", "c:/ws/project")).toBe(true);
    expect(sameWorkspacePath("C:/ws/project-a", "C:/ws/project-b")).toBe(false);
  });
});

describe("취소된 연결 (검수 T7_1 Mid)", () => {
  test("test_detach_during_connect_stays_idle", async () => {
    const world = new World();
    world.startDaemon(ROOT);
    let fail!: (e: Error) => void;
    let locates = 0;
    const { mgr, states } = manager(world, {
      connect: () => new Promise((_resolve, reject) => (fail = reject)),
      locateCli: () => {
        locates++;
        return { path: CLI, tried: [CLI] };
      },
    });
    const pending = mgr.open(ROOT);
    await tick();
    mgr.detach();
    fail(new Error("늦은 연결 실패"));
    await pending;
    expect(mgr.state).toEqual({ status: "idle", root: null, appProtocol: APP_PROTOCOL });
    expect(states.at(-1)?.status).toBe("idle");
    expect(locates).toBe(0);
    expect(world.spawns).toEqual([]);
  });

  test("test_switch_late_failure_does_not_override_new_project", async () => {
    const world = new World();
    const a = world.startDaemon(ROOT);
    const b = world.startDaemon("C:/other");
    let failOld!: (e: Error) => void;
    const real = world.deps().connect;
    const { mgr } = manager(world, {
      connect: (port, token) =>
        port === a.port ? new Promise((_resolve, reject) => (failOld = reject)) : real(port, token),
    });
    const old = mgr.open(ROOT);
    await tick();
    await mgr.open("C:/other");
    failOld(new Error("앞 프로젝트 연결 실패"));
    await old;
    for (let i = 0; i < 20; i++) await tick();
    expect(mgr.state).toMatchObject({ status: "connected", root: "C:/other", startId: b.startId });
    expect(mgr.connected).toBe(true);
    expect(world.spawns).toEqual([]);
  });

  test("test_mismatch_connection_closed_then_restart", async () => {
    const world = new World();
    const old = world.startDaemon(ROOT, 2);
    const { mgr } = manager(world);
    expect((await mgr.open(ROOT)).status).toBe("mismatch");
    // 판이 다른 연결이 끊기면 다시 붙기 순서를 돈다 → 같은 daemon이면 다시 판 다름
    [...old.conns][0].drop();
    await until(() => mgr.state.status === "disconnected", "끊김");
    await until(() => mgr.state.status === "mismatch", "다시 판 다름");
    expect(old.conns.size).toBe(1);
    // 실행 중이면 여전히 거부
    old.runActive = true;
    expect(await mgr.restartDaemon()).toMatchObject({ status: "mismatch", runActive: true });
    expect(old.alive).toBe(true);

    // 거부된 다시 시작 뒤에 연결이 끊겨도 다시 붙기를 돈다 (다시 시작 버튼이 할 일 없이 남지 않음)
    [...old.conns][0].drop();
    await until(() => mgr.state.status === "disconnected", "거부 뒤 끊김");
    await until(() => mgr.state.status === "mismatch", "거부 뒤 다시 판 다름");
    old.runActive = false;
    const state = await mgr.restartDaemon();
    expect(old.alive).toBe(false);
    expect(state.status).toBe("connected");
    expect(state.startId).not.toBe(old.startId);
    expect(world.spawns).toEqual([ROOT]);
  });
});

describe("daemon 교체 뒤 복구", () => {
  const rev = (c: string) => c.repeat(64);

  function opened(path: string, revision: string): GraphOpenResult {
    return {
      doc_id: `doc-${path}`,
      revision,
      value: { format: "kookabug.graph/0" },
      canonical: true,
      diagnostics: [],
      shapes: {},
    } as unknown as ResultOf<"graph.open">;
  }

  test("test_start_id_change_reopens_docs_keeps_buffers", async () => {
    // 렌더러의 문서 표: 버퍼·dirty·base_revision은 여기 있다
    const buffers = new Map<string, { value: string; doc: string; base: string; dirty: boolean; undo: string[] }>([
      ["a.graph.json", { value: "A 편집 없음", doc: "old-a", base: rev("a"), dirty: false, undo: [] }],
      ["b.graph.json", { value: "B 편집 중", doc: "old-b", base: rev("b"), dirty: true, undo: ["이동"] }],
      ["c.graph.json", { value: "C 옛 값", doc: "old-c", base: rev("c"), dirty: false, undo: [] }],
      ["d.graph.json", { value: "D 편집 중", doc: "old-d", base: rev("d"), dirty: true, undo: ["추가"] }],
      ["gone.graph.json", { value: "지워진 파일", doc: "old-g", base: rev("e"), dirty: true, undo: [] }],
    ]);
    const disk: Record<string, string> = {
      "a.graph.json": rev("a"), // 그대로
      "b.graph.json": rev("1"), // 밖에서 바뀜 + 편집 중 → 충돌
      "c.graph.json": rev("2"), // 밖에서 바뀜 + 편집 없음 → 다시 열기
      "d.graph.json": rev("d"), // 그대로 + 편집 중 → 버퍼 유지
    };
    const log: string[] = [];
    const host: DocHost = {
      docs: () =>
        [...buffers].map(([path, b]): OpenDocRef => ({ path, baseRevision: b.base, dirty: b.dirty })),
      rebind: (path, r) => {
        buffers.get(path)!.doc = r.doc_id;
        log.push(`rebind ${path}`);
      },
      conflict: (path, revision) => log.push(`conflict ${path} ${revision.slice(0, 1)}`),
      reload: (path, r) => {
        Object.assign(buffers.get(path)!, { value: "C 디스크 값", doc: r.doc_id, base: r.revision });
        log.push(`reload ${path}`);
      },
      failed: (path, err) => log.push(`failed ${path} ${err.kind}`),
      validateAll: () => log.push("validate"),
    };
    const call = (async (method: string, params: { path: string }) => {
      expect(method).toBe("graph.open");
      if (!(params.path in disk)) throw { code: -32100, message: "없음", data: { code: "not_found", path: params.path } };
      return opened(params.path, disk[params.path]);
    }) as unknown as RpcCall;
    const recovery = new SessionRecovery(call);
    recovery.addDocs(host);

    expect(await recovery.connected({ root: ROOT, startId: "1".repeat(32), connection: 1 })).toBe("first");
    expect(log).toEqual([]);
    // 같은 연결의 연결됨이 다시 오면 아무것도 다시 열지 않는다
    expect(await recovery.connected({ root: ROOT, startId: "1".repeat(32), connection: 1 })).toBe(
      "same_connection",
    );
    expect(log).toEqual([]);

    expect(await recovery.connected({ root: ROOT, startId: "2".repeat(32), connection: 2 })).toBe("daemon_replaced");
    expect(log).toEqual([
      "rebind a.graph.json",
      "rebind b.graph.json",
      "conflict b.graph.json 1",
      "reload c.graph.json",
      "rebind d.graph.json",
      "failed gone.graph.json not_found",
      "validate",
    ]);
    // 새 doc_id에 붙고, 편집 중인 버퍼·실행 취소 기록·base_revision은 그대로
    expect(buffers.get("b.graph.json")).toEqual({
      value: "B 편집 중",
      doc: "doc-b.graph.json",
      base: rev("b"),
      dirty: true,
      undo: ["이동"],
    });
    expect(buffers.get("d.graph.json")).toMatchObject({ value: "D 편집 중", doc: "doc-d.graph.json", undo: ["추가"] });
    expect(buffers.get("c.graph.json")).toMatchObject({ value: "C 디스크 값", base: rev("2") });

    // 같은 daemon의 새 연결: daemon이 끊긴 연결의 문서 참조를 풀었으므로 모두 다시 연다 (검수 T7_2)
    log.length = 0;
    expect(await recovery.connected({ root: ROOT, startId: "2".repeat(32), connection: 3 })).toBe("same_daemon");
    expect(log).toEqual([
      "rebind a.graph.json",
      "rebind b.graph.json",
      "conflict b.graph.json 1",
      "rebind c.graph.json", // 다시 연 디스크 값이 이제 기준
      "rebind d.graph.json",
      "failed gone.graph.json not_found",
      "validate",
    ]);
    expect(buffers.get("b.graph.json")).toMatchObject({ value: "B 편집 중", dirty: true, undo: ["이동"], base: rev("b") });
  });

  test("test_start_id_change_expires_frames", async () => {
    let expired = 0;
    const recovery = new SessionRecovery((async () => ({})) as unknown as RpcCall);
    recovery.addFrames({ expireAll: () => expired++ });
    await recovery.connected({ root: ROOT, startId: "1".repeat(32) });
    await recovery.connected({ root: ROOT, startId: "1".repeat(32) });
    expect(expired).toBe(0);
    await recovery.connected({ root: ROOT, startId: "3".repeat(32) });
    expect(expired).toBe(1);
    // 다른 워크스페이스를 열면 처음 연결이다
    await recovery.connected({ root: "C:/other", startId: "4".repeat(32) });
    expect(expired).toBe(1);
  });
});

describe("parseSession", () => {
  test("필드 모양을 검사한다", () => {
    const good = {
      format: "kookabug.session/0",
      pid: 12,
      port: 5000,
      protocol: 1,
      token: "a".repeat(64),
      start_id: "b".repeat(32),
    };
    expect(parseSession(JSON.stringify(good))).toEqual({
      pid: 12,
      port: 5000,
      protocol: 1,
      token: "a".repeat(64),
      startId: "b".repeat(32),
      workspace: null,
    });
    for (const bad of [
      { ...good, format: "x" },
      { ...good, pid: 0 },
      { ...good, port: 70000 },
      { ...good, port: 1.5 },
      { ...good, token: "A".repeat(64) },
      { ...good, start_id: "b".repeat(31) },
    ]) {
      expect(parseSession(JSON.stringify(bad))).toBeNull();
    }
    expect(parseSession(null)).toBeNull();
  });
});

describe("중간에 끊긴 복구 (검수 T7_1 Mid, T7_2)", () => {
  const rev = (c: string) => c.repeat(64);

  test("test_reopen_interrupted_reopens_all_on_next_connection", async () => {
    const buffers = new Map([
      ["a.graph.json", { doc: "old-a", base: rev("a"), dirty: true, undo: ["이동"] }],
      ["b.graph.json", { doc: "old-b", base: rev("b"), dirty: false, undo: [] as string[] }],
      ["c.graph.json", { doc: "old-c", base: rev("c"), dirty: true, undo: ["추가"] }],
    ]);
    const opens: string[] = [];
    let down = false;
    let validated = 0;
    const host: DocHost = {
      docs: () => [...buffers].map(([path, b]): OpenDocRef => ({ path, baseRevision: b.base, dirty: b.dirty })),
      rebind: (path, r) => {
        buffers.get(path)!.doc = r.doc_id;
      },
      conflict: () => {
        throw new Error("디스크가 같아 충돌이 아니다");
      },
      reload: () => {
        throw new Error("디스크가 같아 다시 열지 않는다");
      },
      failed: (path) => {
        throw new Error(`실패로 보면 안 된다: ${path}`);
      },
      validateAll: () => validated++,
    };
    const call = (async (_method: string, params: { path: string }) => {
      opens.push(params.path);
      // b를 여는 도중 연결이 끊긴다
      if (params.path === "b.graph.json" && !down) {
        down = true;
        throw { code: -32000, message: "끊김", data: { code: "not_connected" } };
      }
      return {
        doc_id: `new-${params.path}`,
        revision: buffers.get(params.path)!.base,
        value: {},
        canonical: true,
        diagnostics: [],
        shapes: {},
      };
    }) as unknown as RpcCall;
    const recovery = new SessionRecovery(call);
    recovery.addDocs(host);
    await recovery.connected({ root: ROOT, startId: "1".repeat(32), connection: 1 });
    expect(await recovery.connected({ root: ROOT, startId: "2".repeat(32), connection: 2 })).toBe("daemon_replaced");
    expect(opens).toEqual(["a.graph.json", "b.graph.json"]);
    expect(validated).toBe(0); // 다 붙이기 전에는 검증하지 않는다
    // 같은 새 daemon에 새 연결로 다시 붙음 → 앞 연결에서 연 a도 다시 연다 (daemon이 끊긴 연결의 참조를 풀었다)
    expect(await recovery.connected({ root: ROOT, startId: "2".repeat(32), connection: 3 })).toBe("same_daemon");
    expect(opens).toEqual(["a.graph.json", "b.graph.json", "a.graph.json", "b.graph.json", "c.graph.json"]);
    expect(validated).toBe(1);
    expect([...buffers.values()].map((b) => b.doc)).toEqual(["new-a.graph.json", "new-b.graph.json", "new-c.graph.json"]);
    // 버퍼 쪽 dirty·실행 취소·base_revision은 그대로
    expect(buffers.get("a.graph.json")).toMatchObject({ dirty: true, undo: ["이동"], base: rev("a") });
    expect(buffers.get("c.graph.json")).toMatchObject({ dirty: true, undo: ["추가"], base: rev("c") });
    // 같은 연결의 연결됨이 다시 오면 아무것도 다시 열지 않는다 (중복 참조 없음)
    expect(await recovery.connected({ root: ROOT, startId: "2".repeat(32), connection: 3 })).toBe("same_connection");
    expect(opens).toHaveLength(5);
    expect(validated).toBe(1);
  });
});

describe("구독 커서와 적용 실패 (검수 T7_1 Mid)", () => {
  test("test_cursor_not_advanced_when_apply_fails", async () => {
    const calls: unknown[] = [];
    let failOnce = true;
    const applied: number[] = [];
    const cursors = new RunCursors(
      (async (_m: string, p: unknown) => {
        calls.push(p);
        return {};
      }) as RpcCall,
      (_run, seq) => {
        if (seq === 1 && failOnce) {
          failOnce = false;
          throw new Error("적용 실패");
        }
        applied.push(seq);
      },
    );
    await cursors.subscribe("run00003");
    expect(() => cursors.event("run00003", 1, {})).toThrow("적용 실패");
    expect(cursors.applied("run00003")).toBe(0);
    // 다음 이벤트는 빈틈 → 적용한 마지막 seq(0)부터 다시 구독
    expect(cursors.event("run00003", 2, {})).toBe("gap");
    await tick();
    // 재접속도 0부터
    await cursors.resubscribeAll();
    expect(calls).toEqual([
      { run_id: "run00003", after_seq: 0 },
      { run_id: "run00003", after_seq: 0 },
      { run_id: "run00003", after_seq: 0 },
    ]);
    // 다시 받은 seq 1은 중복이 아니라 적용된다
    expect(cursors.event("run00003", 1, {})).toBe("applied");
    expect(cursors.event("run00003", 2, {})).toBe("applied");
    expect(applied).toEqual([1, 2]);
  });
});
