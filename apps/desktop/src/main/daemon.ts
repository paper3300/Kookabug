// daemon 관리자 (M2 계획 2.3 "클라이언트의 붙기 순서"): session.json 읽기 → 살아 있으면 연결·hello
// → 아니면 `kookabug daemon` 띄우기 → 유효한 세션이 생길 때까지 기다리기(15초) → 끊기면 0.5·1·2·4·5초
// 간격으로 처음부터 다시. 판이 다르면 연결을 열어 둔 채 "daemon 다시 시작"(진행 중인 실행이 없을 때만).
//
// 파일·프로세스·소켓·시간은 DaemonDeps로 받는다. vitest가 가짜로 경쟁·끊김·교체를 만든다.
// 문서 다시 열기·frame 만료·구독 재개는 렌더러(rpc/recovery.ts)가 start_id를 보고 한다
import { spawn as spawnChild } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { type CliLocation } from "./cli-locate";
import type { DaemonState } from "./daemon-state";
import { RpcConnection, RpcFailure, notConnected, type SocketLike } from "./rpc-connection";

/** 앱이 쓰는 daemon 프로토콜 판 (session.json·hello의 protocol) */
export const APP_PROTOCOL = 1;
export const WAIT_TIMEOUT_MS = 15_000;
export const POLL_MS = 100;
export const HELLO_TIMEOUT_MS = 5_000;
export const BACKOFF_MS = [500, 1000, 2000, 4000, 5000] as const;
export const SESSION_FILE = [".kookabug", "session.json"] as const;
export const LOGS_DIR = [".kookabug", "logs"] as const;

export type { DaemonErrorKind, DaemonState, DaemonStatus } from "./daemon-state";

export interface SessionInfo {
  pid: number;
  port: number;
  token: string;
  startId: string;
  protocol: number;
  /** daemon이 맡은 워크스페이스 절대 경로 (복사된 session.json을 가려낸다) */
  workspace: string | null;
}

/** session.json 텍스트 → 붙기에 필요한 필드. 형식이 틀리면(손상) null = 오래된 파일과 같다 */
export function parseSession(text: string | null): SessionInfo | null {
  if (text === null) return null;
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const d = data as Record<string, unknown>;
  const int = (v: unknown, max: number) => Number.isSafeInteger(v) && (v as number) >= 1 && (v as number) <= max;
  if (d.format !== "kookabug.session/0") return null;
  if (!int(d.pid, Number.MAX_SAFE_INTEGER) || !int(d.port, 65535) || !int(d.protocol, Number.MAX_SAFE_INTEGER)) {
    return null;
  }
  if (typeof d.token !== "string" || !/^[0-9a-f]{64}$/.test(d.token)) return null;
  if (typeof d.start_id !== "string" || !/^[0-9a-f]{32}$/.test(d.start_id)) return null;
  if (d.workspace !== undefined && (typeof d.workspace !== "string" || d.workspace === "")) return null;
  return {
    pid: d.pid as number,
    port: d.port as number,
    token: d.token,
    startId: d.start_id,
    protocol: d.protocol as number,
    workspace: (d.workspace as string | undefined) ?? null,
  };
}

/** 경로 비교 기본값: 구분자·끝 구분자·대소문자(Windows)를 맞춘다. 실제 환경은 링크까지 푼다 (nodeDeps) */
export function sameWorkspacePath(a: string, b: string): boolean {
  const norm = (p: string) => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  return norm(a) === norm(b);
}

export interface HelloResult {
  start_id: string;
  protocol: number;
  daemon_version: string;
  workspace: string;
}

/** hello까지 마친 연결 */
export interface Connection {
  readonly hello: HelloResult;
  readonly closed: Promise<void>;
  call(method: string, params: unknown, paramsText?: string): Promise<unknown>;
  onNotification(cb: (method: string, params: unknown) => void): () => void;
  onClose(cb: () => void): void;
  close(): void;
}

/** hello가 거부됐다. 판이 다르면 연결은 열린 채 daemon.shutdown만 받는다 */
export class HelloRejected extends Error {
  override name = "HelloRejected";
  constructor(
    readonly kind: string,
    message: string,
    readonly protocol: number | null,
    readonly conn: Connection | null,
  ) {
    super(message);
  }
}

export interface DaemonDeps {
  /** `<루트>/.kookabug/session.json` 텍스트. 없거나 못 읽으면 null */
  readSession(root: string): string | null;
  isAlive(pid: number): boolean;
  /** 연결 + session.hello. 실패하면 던진다 (판 다름은 HelloRejected) */
  connect(port: number, token: string): Promise<Connection>;
  locateCli(): CliLocation;
  /** `kookabug daemon --workspace <루트>`를 띄운다. 로그 파일 경로를 돌려준다 */
  spawn(cli: string, root: string): { logPath: string };
  sleep(ms: number): Promise<void>;
  now(): number;
  /** 두 워크스페이스 경로가 같은 폴더인지. 없으면 sameWorkspacePath */
  sameWorkspace?(a: string, b: string): boolean;
}

export interface DaemonEvents {
  state(state: DaemonState): void;
  notification(method: string, params: unknown): void;
  log(level: "info" | "warn" | "error", message: string): void;
}

type AttachResult = "connected" | "mismatch" | "failed" | "stale";

function failureKind(err: unknown): string | null {
  return err instanceof RpcFailure ? err.kind : null;
}

/**
 * 세대(gen): 워크스페이스 열기·닫기·다시 시도·다시 시작마다 올린다. 비동기 작업은 await 뒤마다 자기
 * 세대가 아직 지금 세대인지 보고, 아니면 아무것도 쓰지 않고(상태·연결·띄우기) "stale"로 끝난다.
 * 그래서 늦게 끝난 앞 프로젝트의 연결 실패가 새 프로젝트 상태를 덮거나 앞 프로젝트 daemon을 띄우지 않는다
 */
export class DaemonManager {
  private gen = 0;
  private conn: Connection | null = null;
  private mismatchConn: Connection | null = null;
  /** 붙은 연결 수 (DaemonState.connection) */
  private connections = 0;
  private current: DaemonState = { status: "idle", root: null, appProtocol: APP_PROTOCOL };

  constructor(
    private readonly deps: DaemonDeps,
    private readonly events: DaemonEvents,
  ) {}

  get state(): DaemonState {
    return this.current;
  }

  get root(): string | null {
    return this.current.root;
  }

  get connected(): boolean {
    return this.conn !== null;
  }

  /** 워크스페이스에 붙는다. 첫 시도가 끝나면 풀린다(성공·판 다름·오류·다른 열기로 취소) */
  async open(root: string): Promise<DaemonState> {
    // 바로 "연결 중"으로 간다: 중간에 idle(워크스페이스 없음)을 알리면 렌더러가 시작 화면으로 깜빡인다
    this.release();
    const gen = ++this.gen;
    this.setState({ status: "connecting", root, appProtocol: APP_PROTOCOL, attempt: 1 });
    await this.attach(gen);
    return this.current;
  }

  /**
   * 지금 연결만 끊는다 (daemon·실행은 그대로). 끊김과 같은 길로 다시 붙는다: 다시 붙기 간격 → 같은 start_id의
   * 새 연결 → 렌더러 복구(문서 다시 열기·실행 구독은 적용한 마지막 seq부터). E2E 검사 전용 훅이 부른다
   * (e2e-hooks.ts: 패키징되지 않은 개발 빌드에서만)
   */
  dropConnection(): boolean {
    const conn = this.conn;
    if (conn === null) return false;
    conn.close();
    return true;
  }

  /** 연결을 놓는다 (daemon은 남는다: UI를 꺼도 daemon과 실행은 계속된다) */
  detach(): void {
    this.release();
    this.gen++;
    if (this.current.status !== "idle") this.setState({ status: "idle", root: null, appProtocol: APP_PROTOCOL });
  }

  private release(): void {
    this.gen++;
    const conns = [this.conn, this.mismatchConn];
    this.conn = null;
    this.mismatchConn = null;
    for (const c of conns) c?.close();
  }

  /** 오류·끊김 상태에서 바로 다시 붙어 본다 */
  async retry(): Promise<DaemonState> {
    const root = this.current.root;
    if (root === null || this.current.status === "connected") return this.current;
    this.release();
    const gen = ++this.gen;
    const result = await this.attach(gen);
    if (result === "failed" && gen === this.gen && this.current.error !== "cli_not_found") {
      void this.reconnectLoop(gen, 1);
    }
    return this.current;
  }

  /**
   * 판 다름일 때 daemon을 끝내고 새로 띄운다. 진행 중인 실행이 있으면 daemon이 거부한다.
   * 판이 다른 연결이 이미 닫혔으면 먼저 지금 세션을 다시 찾아 붙는다(같은 판이면 그대로 연결됨)
   */
  async restartDaemon(): Promise<DaemonState> {
    const root = this.current.root;
    if (root === null || this.current.status !== "mismatch") return this.current;
    let gen = ++this.gen;
    let conn = this.mismatchConn;
    if (conn === null) {
      const found = await this.attach(gen);
      if (found !== "mismatch" || gen !== this.gen) return this.current;
      conn = this.mismatchConn;
      if (conn === null) return this.current;
    }
    try {
      await conn.call("daemon.shutdown", {});
    } catch (err) {
      if (gen !== this.gen) return this.current;
      if (failureKind(err) === "run_active") {
        this.setState({ ...this.current, runActive: true });
        this.events.log("warn", "진행 중인 실행이 있어 daemon을 다시 시작하지 않았다");
        return this.current;
      }
      if (failureKind(err) !== "not_connected") {
        this.events.log("error", `daemon 종료 요청 실패: ${(err as Error).message}`);
        return this.current;
      }
    }
    // 이 연결의 닫힘은 다시 붙기를 일으키지 않는다 (아래에서 직접 붙는다)
    if (this.mismatchConn === conn) this.mismatchConn = null;
    await Promise.race([conn.closed, this.deps.sleep(HELLO_TIMEOUT_MS)]);
    conn.close();
    if (gen !== this.gen) return this.current;
    gen = ++this.gen;
    this.events.log("info", "daemon을 다시 시작한다");
    await this.attach(gen);
    return this.current;
  }

  call(method: string, params: unknown, paramsText?: string): Promise<unknown> {
    if (this.conn === null) return Promise.reject(notConnected());
    return this.conn.call(method, params, paramsText);
  }

  private setState(next: DaemonState): void {
    this.current = next;
    this.events.state(next);
  }

  private same(a: string, b: string): boolean {
    return (this.deps.sameWorkspace ?? sameWorkspacePath)(a, b);
  }

  private async attach(gen: number, attempt = 1): Promise<AttachResult> {
    const root = this.current.root;
    if (root === null || gen !== this.gen) return "stale";
    this.setState({ status: "connecting", root, appProtocol: APP_PROTOCOL, attempt });
    const first = await this.tryExisting(gen, root);
    if (gen !== this.gen) return "stale";
    if (first !== "none") return first;

    const cli = this.deps.locateCli();
    if (cli.path === null) {
      this.events.log("error", `kookabug CLI를 찾지 못했다: ${cli.tried.join(", ")}`);
      this.setState({
        status: "error",
        root,
        appProtocol: APP_PROTOCOL,
        error: "cli_not_found",
        tried: cli.tried,
        message: "kookabug CLI를 찾지 못했다",
      });
      return "failed";
    }
    let logPath: string;
    try {
      ({ logPath } = this.deps.spawn(cli.path, root));
    } catch (err) {
      const message = `daemon을 띄우지 못했다: ${(err as Error).message}`;
      this.events.log("error", message);
      this.setState({ status: "error", root, appProtocol: APP_PROTOCOL, error: "spawn_failed", message });
      return "failed";
    }
    this.events.log("info", `daemon을 띄웠다: ${cli.path} (로그 ${logPath})`);
    this.setState({ ...this.current, logPath });

    const deadline = this.deps.now() + WAIT_TIMEOUT_MS;
    while (this.deps.now() < deadline) {
      await this.deps.sleep(POLL_MS);
      if (gen !== this.gen) return "stale";
      const r = await this.tryExisting(gen, root);
      if (gen !== this.gen) return "stale";
      if (r !== "none") return r;
    }
    const message = `daemon이 ${WAIT_TIMEOUT_MS / 1000}초 안에 준비되지 않았다`;
    this.events.log("error", `${message}. 로그: ${logPath}`);
    this.setState({ status: "error", root, appProtocol: APP_PROTOCOL, error: "timeout", message, logPath });
    return "failed";
  }

  /**
   * 지금 session.json이 가리키는 daemon에 붙어 본다. 유효한 세션 = 형식·살아 있는 PID·이 워크스페이스의
   * 세션·hello 인증 성공·hello의 워크스페이스와 start_id가 세션과 같음. 다른 폴더에서 복사된
   * session.json(살아 있는 다른 워크스페이스의 daemon)은 쓰지 않는다
   */
  private async tryExisting(gen: number, root: string): Promise<AttachResult | "none"> {
    const session = parseSession(this.deps.readSession(root));
    if (session === null || !this.deps.isAlive(session.pid)) return "none";
    if (session.workspace !== null && !this.same(session.workspace, root)) {
      this.events.log("warn", `다른 워크스페이스의 session.json이다 (${session.workspace}). 새 daemon을 띄운다`);
      return "none";
    }
    let conn: Connection;
    try {
      conn = await this.deps.connect(session.port, session.token);
    } catch (err) {
      const mismatch = err instanceof HelloRejected && err.kind === "protocol_mismatch" ? err.conn : null;
      if (gen !== this.gen) {
        mismatch?.close();
        return "stale";
      }
      if (mismatch !== null) {
        this.adoptMismatch(mismatch, (err as HelloRejected).protocol, root);
        return "mismatch";
      }
      return "none";
    }
    if (gen !== this.gen) {
      conn.close();
      return "stale";
    }
    if (!this.same(conn.hello.workspace, root) || conn.hello.start_id !== session.startId) {
      conn.close();
      this.events.log(
        "warn",
        `세션과 다른 daemon이다 (워크스페이스 ${conn.hello.workspace}, start_id ${conn.hello.start_id}). 쓰지 않는다`,
      );
      return "none";
    }
    this.adopt(conn, gen, root);
    return "connected";
  }

  private adopt(conn: Connection, gen: number, root: string): void {
    this.conn = conn;
    conn.onNotification((method, params) => {
      if (this.conn === conn) this.events.notification(method, params);
    });
    conn.onClose(() => {
      if (this.conn !== conn) return;
      this.conn = null;
      this.events.log("warn", "daemon 연결이 끊겼다");
      if (gen === this.gen) void this.reconnectLoop(gen, 0);
    });
    this.events.log("info", `daemon에 붙었다 (start_id ${conn.hello.start_id}, 판 ${conn.hello.daemon_version})`);
    this.setState({
      status: "connected",
      root,
      appProtocol: APP_PROTOCOL,
      startId: conn.hello.start_id,
      connection: ++this.connections,
      daemonVersion: conn.hello.daemon_version,
      protocol: conn.hello.protocol,
    });
  }

  private adoptMismatch(conn: Connection, protocol: number | null, root: string): void {
    this.mismatchConn = conn;
    // 판이 다른 daemon이 끝나거나 연결이 끊기면 붙기 순서를 다시 한다 (새 daemon이 같은 판일 수 있다).
    // 다시 시작 버튼이 할 일이 없는 채로 남지 않는다
    // 지금 붙들고 있는 연결인지로만 판단한다(놓을 때는 포인터를 먼저 비운다): 거부된 다시 시작이
    // 세대를 올린 뒤에 끊겨도 다시 붙기를 한다
    conn.onClose(() => {
      if (this.mismatchConn !== conn) return;
      this.mismatchConn = null;
      this.events.log("warn", "판이 다른 daemon과의 연결이 끊겼다");
      void this.reconnectLoop(this.gen, 0);
    });
    const message = `daemon 프로토콜 판(${protocol ?? "?"})이 앱(${APP_PROTOCOL})과 다르다`;
    this.events.log("error", message);
    this.setState({
      status: "mismatch",
      root,
      appProtocol: APP_PROTOCOL,
      ...(protocol === null ? {} : { protocol }),
      message,
    });
  }

  /** 끊긴 뒤: 0.5·1·2·4·5초(최대 5초) 간격으로 붙기 순서를 처음부터 다시 한다 */
  private async reconnectLoop(gen: number, startIndex: number): Promise<void> {
    const root = this.current.root;
    if (root === null) return;
    for (let i = startIndex; ; i++) {
      if (gen !== this.gen) return;
      const delay = BACKOFF_MS[Math.min(i, BACKOFF_MS.length - 1)];
      const message = this.current.status === "error" ? this.current.message : undefined;
      this.setState({
        status: "disconnected",
        root,
        appProtocol: APP_PROTOCOL,
        attempt: i + 1,
        retryInMs: delay,
        ...(message === undefined ? {} : { message }),
      });
      await this.deps.sleep(delay);
      if (gen !== this.gen) return;
      const result = await this.attach(gen, i + 1);
      if (result !== "failed") return;
      if (this.current.error === "cli_not_found") return;
    }
  }
}

// ── 실제 환경 ──────────────────────────────────────────────────────────────

/** 전역 WebSocket(Electron 주 프로세스 = Node 24, undici)을 SocketLike로. Origin을 붙이지 않는다 */
function openSocket(url: string, timeoutMs: number): Promise<SocketLike> {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(url);
    let messageCb: (data: string | null) => void = () => {};
    let closeCb: () => void = () => {};
    const timer = setTimeout(() => {
      ws.close();
      reject(new Error("연결 시간 초과"));
    }, timeoutMs);
    ws.addEventListener("open", () => {
      clearTimeout(timer);
      resolve({
        send: (text) => ws.send(text),
        close: () => ws.close(),
        onMessage: (cb) => (messageCb = cb),
        onClose: (cb) => (closeCb = cb),
      });
    });
    ws.addEventListener("message", (e: MessageEvent) => messageCb(typeof e.data === "string" ? e.data : null));
    ws.addEventListener("error", () => {
      clearTimeout(timer);
      reject(new Error("연결하지 못했다"));
    });
    ws.addEventListener("close", () => {
      clearTimeout(timer);
      closeCb();
    });
  });
}

function withTimeout<T>(p: Promise<T>, ms: number, what: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${what} 시간 초과`)), ms);
    p.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e: unknown) => {
        clearTimeout(timer);
        reject(e);
      },
    );
  });
}

export interface ClientInfo {
  kind: "ui";
  name: string;
  version: string;
}

/** 127.0.0.1:<포트>에 붙고 session.hello를 보낸다 */
export async function connectDaemon(port: number, token: string, client: ClientInfo): Promise<Connection> {
  const socket = await openSocket(`ws://127.0.0.1:${port}/`, HELLO_TIMEOUT_MS);
  const rpc = new RpcConnection(socket);
  let hello: HelloResult;
  try {
    hello = (await withTimeout(
      rpc.call("session.hello", { token, protocol: APP_PROTOCOL, client }),
      HELLO_TIMEOUT_MS,
      "session.hello",
    )) as HelloResult;
  } catch (err) {
    if (err instanceof RpcFailure && err.kind === "protocol_mismatch") {
      const protocol = (err.data as { protocol?: number }).protocol ?? null;
      throw new HelloRejected("protocol_mismatch", err.message, protocol, wrap(rpc, null));
    }
    rpc.close();
    throw err;
  }
  return wrap(rpc, hello);
}

function wrap(rpc: RpcConnection, hello: HelloResult | null): Connection {
  return {
    hello: hello ?? { start_id: "", protocol: 0, daemon_version: "", workspace: "" },
    closed: rpc.closed,
    call: (method, params, text) => rpc.call(method, params, text),
    onNotification: (cb) => rpc.onNotification(cb),
    onClose: (cb) => rpc.onClose(cb),
    close: () => rpc.close(),
  };
}

function timestamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getUTCFullYear()}${p(d.getUTCMonth() + 1)}${p(d.getUTCDate())}` +
    `T${p(d.getUTCHours())}${p(d.getUTCMinutes())}${p(d.getUTCSeconds())}`
  );
}

export interface NodeDepsOptions {
  client: ClientInfo;
  locateCli(): CliLocation;
  /** 검사용 추가 인자 (KOOKABUG_DAEMON_ARGS, JSON 문자열 배열) */
  extraArgs?: readonly string[];
}

export function nodeDeps(options: NodeDepsOptions): DaemonDeps {
  return {
    readSession(root) {
      try {
        return fs.readFileSync(path.join(root, ...SESSION_FILE), "utf8");
      } catch {
        return null;
      }
    },
    isAlive(pid) {
      // 생성 시각 비교는 하지 않는다: Node에서 바로 읽을 수 없고, 다음 단계 hello가 32바이트 토큰으로
      // 그 daemon인지 확인한다 (PID가 재사용돼도 토큰이 맞지 않으면 붙지 않는다)
      try {
        process.kill(pid, 0);
        return true;
      } catch (err) {
        return (err as NodeJS.ErrnoException).code === "EPERM";
      }
    },
    connect: (port, token) => connectDaemon(port, token, options.client),
    sameWorkspace(a, b) {
      // 링크·정션·8.3 짧은 이름을 푼 실제 경로로 비교한다 (Windows는 대소문자 무시)
      const real = (p: string) => {
        try {
          return fs.realpathSync.native(p);
        } catch {
          return path.resolve(p);
        }
      };
      return sameWorkspacePath(real(a), real(b));
    },
    locateCli: () => options.locateCli(),
    spawn(cli, root) {
      const dir = path.join(root, ...LOGS_DIR);
      fs.mkdirSync(dir, { recursive: true });
      const logPath = path.join(dir, `daemon-${timestamp(new Date())}-ui.log`);
      const fd = fs.openSync(logPath, "a");
      try {
        // detached: UI를 꺼도 daemon이 남는다. windowsHide: 콘솔 창을 띄우지 않는다
        const child = spawnChild(cli, ["daemon", "--workspace", root, ...(options.extraArgs ?? [])], {
          detached: true,
          windowsHide: true,
          stdio: ["ignore", fd, fd],
        });
        child.on("error", (err) => fs.appendFileSync(logPath, `\n[ui] daemon 실행 실패: ${err.message}\n`));
        child.unref();
      } finally {
        fs.closeSync(fd);
      }
      return { logPath };
    },
    sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    now: () => Date.now(),
  };
}

/** KOOKABUG_DAEMON_ARGS(JSON 문자열 배열)를 읽는다. 틀리면 무시한다 */
export function parseExtraArgs(text: string | undefined): string[] {
  if (!text) return [];
  try {
    const v: unknown = JSON.parse(text);
    return Array.isArray(v) && v.every((s) => typeof s === "string") ? v : [];
  } catch {
    return [];
  }
}
