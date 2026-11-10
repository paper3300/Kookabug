// 마법사·보고함이 쓰는 사람 쪽 CLI 띄우기 (M8 계획 3.17 "메인 IPC", B7). electron을 import하지 않는다 (vitest)
//
//   workspaceCreate  → kookabug workspace new <폴더> --name=<이름> [--git] --json
//   agentProbe       → kookabug agent-job probe --workspace <열린 루트> --agent <프로필> --json
//   agentJobRun      → kookabug agent-job run --workspace <열린 루트> --playbook init --agent <프로필> --json
//   doctor           → kookabug doctor --json
//
// 엄격 (B7): 렌더러는 실행 파일·인자·명령줄을 주지 못한다. 플레이북은 허용 목록, 워크스페이스 루트는 주 프로세스가
// 연 것, Agent는 사용자 설정(daemon agents.get)에 있는 ID를 프로필 이름으로 바꾼 것만. 셸 없이 인자 배열로 띄운다.
// 작업 토큰은 agent-job CLI 안에만 있다(이 모듈·렌더러는 보지 않는다). CLI 출력은 `--json` 결과의 정해진 필드만 넘기고
// 원문 로그(stderr)는 버린다
import childProcess from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { JOB_PLAYBOOKS } from "./ipc-guard";

export { JOB_PLAYBOOKS };

/** 사용자 설정 Agent ID → agent-job 프로필 (감지 표 kookabug_core.agents.detect의 ID) */
export const AGENT_PROFILES: Readonly<Record<string, "claude" | "codex">> = {
  "claude-code": "claude",
  claude: "claude",
  codex: "codex",
};

/** 렌더러에 넘기는 CLI 결과 필드 (그 밖은 버린다 — 경로·로그·토큰이 섞일 자리를 막는다) */
const RESULT_FIELDS = ["job", "state", "exit_code", "error_code", "code", "probe_ok", "report", "root", "name"] as const;
const OUTPUT_LIMIT = 256 * 1024;
const RESERVED = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$/i;
// eslint-disable-next-line no-control-regex
const NAME_CHARS = /^[^\\/:*?"<>|\u0000-\u001f]{1,64}$/;

export class JobsError extends Error {
  override name = "JobsError";
  constructor(
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export interface CliResult {
  [key: string]: unknown;
}

/** 실행 결과: 종료 코드와 표준 출력 (표준 오류는 받지 않는다) */
export interface ExecOutcome {
  code: number | null;
  stdout: string;
}

export interface JobDeps {
  /** kookabug CLI (cli-locate.ts) */
  cli(): string | null;
  /** 주 프로세스가 연 워크스페이스 루트 */
  root(): string | null;
  /** 사용자 설정의 Agent ID 목록 (daemon agents.get) */
  agentIds(): Promise<string[]>;
  /** 셸 없이 띄우고 끝까지 기다린다 */
  exec(file: string, args: string[], timeoutMs: number): Promise<ExecOutcome>;
  /** 셸 없이 띄우고 기다리지 않는다. 끝나면 onExit */
  spawn(file: string, args: string[], onExit: (outcome: ExecOutcome) => void): RunningChild;
  /** 작업이 끝났다 (app 알림 jobs.cli) */
  emit(result: CliResult): void;
  /** E2E 검사 전용 custom 명령줄 (주 프로세스가 E2E 훅을 켰을 때만 준다) */
  override: string | null;
  exists?(file: string): boolean;
}

/** 띄운 agent-job run (앱 종료 때 정리용) */
export interface RunningChild {
  /** 프로세스가 끝나면 풀린다 */
  readonly done: Promise<void>;
  /** 자식 프로세스 트리를 끝낸다 (Windows taskkill /T /F) */
  killTree(): void;
}

/** 앱 종료 때 agent-job 취소를 기다리는 상한 */
export const SHUTDOWN_LIMIT_MS = 5_000;

export interface CreateRequest {
  parent: string;
  name: string;
  git: boolean;
}

/** 프로젝트 이름: 폴더 이름으로 쓸 수 있고 옵션처럼 보이지 않는다 */
export function checkProjectName(value: unknown): string {
  if (typeof value !== "string") throw new JobsError("invalid_name", "이름이 문자열이 아니다");
  const name = value;
  if (
    !NAME_CHARS.test(name) ||
    name !== name.trim() ||
    name.startsWith("-") ||
    name.startsWith(".") ||
    name.endsWith(".") ||
    RESERVED.test(name)
  ) {
    throw new JobsError("invalid_name", "폴더 이름으로 쓸 수 없는 이름이에요");
  }
  return name;
}

export interface FsLike {
  realpath(p: string): string;
  isDir(p: string): boolean;
  /** 링크를 따라가지 않는다 (깨진 링크도 있음) */
  exists(p: string): boolean;
  /** 링크·정션 (lstat) */
  isLink(p: string): boolean;
  isEmptyDir(p: string): boolean;
}

function samePath(a: string, b: string): boolean {
  const norm = (p: string) => (process.platform === "win32" ? path.resolve(p).toLowerCase() : path.resolve(p));
  return norm(a) === norm(b);
}

/** 렌더러가 준 만들기 요청을 검사하고 만들 폴더(정규화한 절대 경로)를 정한다 */
export function checkCreateRequest(value: unknown, fsLike: FsLike = nodeFs): { folder: string; name: string; git: boolean } {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new JobsError("invalid_request", "만들기 요청이 객체가 아니다");
  }
  const keys = Object.keys(value);
  if (keys.some((k) => !["parent", "name", "git"].includes(k))) throw new JobsError("invalid_request", "모르는 키");
  const { parent, name, git } = value as Record<string, unknown>;
  if (typeof git !== "boolean") throw new JobsError("invalid_request", "git이 boolean이 아니다");
  const checked = checkProjectName(name);
  if (typeof parent !== "string" || parent.length === 0 || parent.length > 1000 || !path.isAbsolute(parent)) {
    throw new JobsError("invalid_parent", "위치는 절대 경로여야 해요");
  }
  // eslint-disable-next-line no-control-regex
  if (/[\u0000-\u001f]/.test(parent) || parent.split(/[\\/]/).includes("..")) {
    throw new JobsError("invalid_parent", "위치에 쓸 수 없는 글자가 있어요");
  }
  if (!fsLike.isDir(parent)) throw new JobsError("parent_missing", "위치 폴더가 없어요");
  // 링크·정션을 푼 실제 폴더 아래에 만든다 (요청 글자와 다른 곳에 쓰지 않게 정규화)
  const realParent = fsLike.realpath(parent);
  const folder = path.join(realParent, checked);
  if (fsLike.exists(folder)) {
    // 이미 있는 마지막 폴더 자체도 본다: 정션이면 빈 외부 폴더라도 그쪽에 쓰게 된다 (B7 검수 H1)
    if (fsLike.isLink(folder)) throw new JobsError("path_link", "같은 이름의 링크·정션이 있어 만들지 않아요");
    if (!samePath(path.dirname(fsLike.realpath(folder)), realParent)) {
      throw new JobsError("path_link", "만들 폴더의 실제 위치가 고른 위치 밖이에요");
    }
    if (!fsLike.isEmptyDir(folder)) throw new JobsError("folder_not_empty", "같은 이름의 폴더가 이미 있고 비어 있지 않아요");
  }
  return { folder, name: checked, git };
}

const nodeFs: FsLike = {
  realpath: (p: string) => fs.realpathSync.native(p),
  exists: (p: string) => fs.lstatSync(p, { throwIfNoEntry: false }) !== undefined,
  isLink: (p: string) => fs.lstatSync(p, { throwIfNoEntry: false })?.isSymbolicLink() === true,
  isDir: (p: string) => {
    try {
      return fs.statSync(p).isDirectory();
    } catch {
      return false;
    }
  },
  isEmptyDir: (p: string) => {
    try {
      return fs.statSync(p).isDirectory() && fs.readdirSync(p).length === 0;
    } catch {
      return false;
    }
  },
};

/** CLI `--json` 출력의 마지막 JSON 줄에서 정해진 필드만 */
export function pickResult(stdout: string, exitCode: number | null): CliResult {
  const lines = stdout.split(/\r?\n/).filter((l) => l.trim() !== "");
  let parsed: Record<string, unknown> = {};
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      const value: unknown = JSON.parse(lines[i]);
      if (value !== null && typeof value === "object" && !Array.isArray(value)) {
        parsed = value as Record<string, unknown>;
        break;
      }
    } catch {
      // JSON이 아닌 줄은 건너뛴다
    }
  }
  const out: CliResult = {};
  for (const key of RESULT_FIELDS) {
    const v = parsed[key];
    if (v === undefined) continue;
    if (typeof v === "string" || typeof v === "number" || typeof v === "boolean" || v === null) out[key] = v;
  }
  if (out.exit_code === undefined) out.exit_code = exitCode;
  return out;
}

/** doctor 결과: 항목 ID·통과만 (detail에는 이 PC의 절대 경로가 들어 있어 화면·샷에 넘기지 않는다) */
export function pickDoctor(stdout: string, exitCode: number | null): { ok: boolean; checks: { id: string; ok: boolean }[] } {
  for (const line of stdout.split(/\r?\n/).reverse()) {
    try {
      const value = JSON.parse(line) as { ok?: unknown; checks?: unknown };
      if (Array.isArray(value.checks)) {
        const checks = value.checks
          .filter((c): c is { id: string; ok: boolean } => typeof c?.id === "string" && typeof c?.ok === "boolean")
          .map((c) => ({ id: c.id, ok: c.ok }));
        return { ok: value.ok === true, checks };
      }
    } catch {
      // 다음 줄
    }
  }
  return { ok: exitCode === 0, checks: [] };
}

/** 실행 표지: 앱이 띄운 `agent-job run`을 목록에서 알아보는 무작위 값 (비밀 아님·권한 없음, hex 32자) */
export const LAUNCH_TAG = /^[0-9a-f]{32}$/;

export function newLaunchTag(): string {
  return crypto.randomBytes(16).toString("hex");
}

/**
 * `agent-job list --json`에서 실행 표지가 같은 진행 중 작업 ID. 이 앱이 띄운 CLI가 `job.json`에 남긴 `launch_tag`로만
 * 고른다 (시각·워크스페이스 잠금으로 짐작하지 않는다 — 남이 띄운 작업은 표지가 없거나 다르다, B7-2 검수 H2)
 */
export function pickRunningJob(stdout: string, tag: string): string | null {
  if (!LAUNCH_TAG.test(tag)) return null;
  for (const line of stdout.split(/\r?\n/).reverse()) {
    let value: unknown;
    try {
      value = JSON.parse(line);
    } catch {
      continue;
    }
    const jobs = (value as { jobs?: unknown } | null)?.jobs;
    if (!Array.isArray(jobs)) continue;
    const mine = jobs.filter((j): j is { id: string } => {
      const x = j as { id?: unknown; state?: unknown; launch_tag?: unknown } | null;
      if (typeof x?.id !== "string" || !/^j-[0-9]{8}-[0-9]{6}-[0-9a-f]{4}$/.test(x.id)) return false;
      if (x.state !== "running" && x.state !== "ending") return false;
      return x.launch_tag === tag;
    });
    return mine.length === 1 ? mine[0].id : null;
  }
  return null;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

type Busy = "probe" | "run" | "create";
type DoctorResult = { ok: boolean; checks: { id: string; ok: boolean }[] };
const BUSY_CODE: Record<Busy, [string, string]> = {
  probe: ["probe_active", "연결 시험이 이미 진행 중이에요"],
  run: ["job_active", "다른 작업이 도는 중이에요"],
  create: ["create_active", "프로젝트를 만드는 중이에요"],
};

/** 띄운 agent-job run: 띄울 때의 CLI·루트와 실행 표지. 종료 때 이 값으로만 취소를 요청한다 */
interface Launched {
  proc: RunningChild;
  cli: string;
  root: string;
  tag: string;
  alive: boolean;
}

export class JobRunner {
  /** 진행 중인 동작. 첫 await 전에 잡고 finally에서 놓는다 (B7 검수 M6) */
  private readonly busy = new Set<Busy>();
  private child: Launched | null = null;
  private doctoring: Promise<DoctorResult> | null = null;
  /** shutdown()이 첫 단계에서 세운다. 그 뒤로는 아무것도 띄우지 않는다 (B7-2 검수 M4) */
  private closing = false;

  constructor(private readonly deps: JobDeps) {}

  /** 이 앱이 띄운 agent-job run이 아직 도는가 */
  get running(): boolean {
    return this.child !== null || this.busy.has("run");
  }

  /** 띄우기 직전(await 뒤)에 부른다: 그사이 앱 종료가 시작됐으면 띄우지 않는다 */
  private open(): void {
    if (this.closing) throw new JobsError("shutting_down", "앱을 끝내는 중이에요");
  }

  private claim(kind: Busy): () => void {
    this.open();
    if (this.busy.has(kind)) {
      const [code, message] = BUSY_CODE[kind];
      throw new JobsError(code, message);
    }
    this.busy.add(kind);
    return () => this.busy.delete(kind);
  }

  private cli(): string {
    const file = this.deps.cli();
    if (file === null) throw new JobsError("cli_missing", "kookabug CLI를 찾지 못했어요");
    return file;
  }

  private root(): string {
    const root = this.deps.root();
    if (root === null) throw new JobsError("no_workspace", "열린 프로젝트가 없어요");
    return root;
  }

  /** Agent ID → agent-job 인자 (`--agent <프로필>`, E2E는 custom + 주 프로세스가 정한 명령줄) */
  async agentArgs(agentId: unknown): Promise<string[]> {
    if (typeof agentId !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/.test(agentId)) {
      throw new JobsError("invalid_agent", "Agent ID 형식이 틀렸다");
    }
    const known = await this.deps.agentIds();
    if (!known.includes(agentId)) throw new JobsError("unknown_agent", "사용자 설정에 없는 Agent예요");
    if (this.deps.override !== null) return ["--agent", "custom", "--agent-command", this.deps.override];
    const profile = AGENT_PROFILES[agentId];
    if (profile === undefined) {
      throw new JobsError("agent_job_unsupported", "무인 작업(agent-job)은 Claude Code·Codex CLI만 지원해요");
    }
    return ["--agent", profile];
  }

  async createWorkspace(request: unknown): Promise<CliResult & { folder: string }> {
    const release = this.claim("create");
    try {
      const { folder, name, git } = checkCreateRequest(request);
      const args = ["workspace", "new", folder, `--name=${name}`, "--json", ...(git ? ["--git"] : [])];
      const cli = this.cli();
      this.open();
      const outcome = await this.deps.exec(cli, args, 120_000);
      const result = pickResult(outcome.stdout, outcome.code);
      if (outcome.code !== 0) {
        throw new JobsError(String(result.error_code ?? "create_failed"), "프로젝트를 만들지 못했어요");
      }
      return { ...result, folder };
    } finally {
      release();
    }
  }

  async probe(agentId: unknown): Promise<CliResult> {
    const release = this.claim("probe");
    try {
      const agent = await this.agentArgs(agentId);
      const args = ["agent-job", "probe", "--workspace", this.root(), ...agent, "--json"];
      const cli = this.cli();
      this.open();
      const outcome = await this.deps.exec(cli, args, 180_000);
      return { ...pickResult(outcome.stdout, outcome.code), ok: outcome.code === 0 };
    } finally {
      release();
    }
  }

  async runJob(playbook: unknown, agentId: unknown): Promise<{ started: boolean; error_code?: string }> {
    if (typeof playbook !== "string" || !JOB_PLAYBOOKS.has(playbook)) {
      throw new JobsError("invalid_playbook", `허용되지 않은 플레이북: ${String(playbook)}`);
    }
    if (this.running) return { started: false, error_code: "job_active" };
    // 인자 준비(await) 중에도 잡아 둔다 — 띄운 뒤에는 child가 끝날 때까지 running
    const release = this.claim("run");
    try {
      const agent = await this.agentArgs(agentId);
      const root = this.root();
      const cli = this.cli();
      const tag = newLaunchTag();
      const args = ["agent-job", "run", "--workspace", root, "--playbook", playbook, ...agent, "--launch-tag", tag, "--json"];
      this.open();
      let launched: Launched | null = null;
      let exited = false;
      const proc = this.deps.spawn(cli, args, (outcome) => {
        exited = true;
        if (launched !== null) launched.alive = false;
        if (launched !== null && this.child === launched) this.child = null;
        this.deps.emit({ action: "run", playbook, ...pickResult(outcome.stdout, outcome.code) });
      });
      launched = { proc, cli, root, tag, alive: !exited };
      if (!exited) this.child = launched;
      return { started: true };
    } finally {
      release();
    }
  }

  /** 점검이 이미 돌면 그 결과를 같이 받는다 (인자가 없어 거부할 까닭이 없다 — 단계 다시 그리기·StrictMode 두 번 실행) */
  doctor(): Promise<DoctorResult> {
    if (this.doctoring !== null) return this.doctoring;
    if (this.closing) return Promise.reject(new JobsError("shutting_down", "앱을 끝내는 중이에요"));
    const run = (async () => {
      const outcome = await this.deps.exec(this.cli(), ["doctor", "--json"], 180_000);
      return pickDoctor(outcome.stdout, outcome.code);
    })();
    this.doctoring = run;
    void run.finally(() => {
      if (this.doctoring === run) this.doctoring = null;
    }).catch(() => {});
    return run;
  }

  /**
   * 앱 종료: 먼저 종료 플래그를 세워 새로 띄우지 않는다. 띄운 agent-job run이 돌고 있으면 **띄울 때 루트**에서 실행 표지가
   * 같은 작업에만 취소를 요청하고(`agent-job cancel` → daemon `job.end`, 토큰 폐기·실행 취소·입력 복구·보고는 daemon·CLI
   * 몫) 상한까지 CLI가 끝나기를 기다린다. 넘기면 자기 자식 프로세스 트리만 끝낸다. 표지가 맞는 작업이 없으면 취소하지 않는다
   */
  async shutdown(limitMs = SHUTDOWN_LIMIT_MS): Promise<"idle" | "exited" | "killed"> {
    this.closing = true;
    const child = this.child;
    if (child === null || !child.alive) return "idle";
    const deadline = Date.now() + limitMs;
    const left = () => Math.max(1, deadline - Date.now());
    let settled = false;
    // 늦게 온 목록 응답으로 취소를 보내지 않는다: 자식이 끝났거나 종료 절차가 끝났으면 멈춘다
    const stillMine = () => !settled && child.alive;
    // 취소 요청은 기다리지 않는다 (상한은 run CLI가 끝나는 것으로 잰다). 요청 CLI도 상한에서 끊긴다
    void (async () => {
      const listed = await this.deps.exec(child.cli, ["agent-job", "list", "--workspace", child.root, "--json"], left());
      if (!stillMine()) return;
      const job = pickRunningJob(listed.stdout, child.tag);
      if (job === null) return;
      await this.deps.exec(child.cli, ["agent-job", "cancel", job, "--workspace", child.root, "--json"], left());
    })().catch(() => {});
    const exited = await Promise.race([child.proc.done.then(() => true), sleep(limitMs).then(() => false)]);
    child.alive = child.alive && !exited;
    settled = true;
    if (!exited) child.proc.killTree();
    return exited ? "exited" : "killed";
  }
}

/** 실제 프로세스 띄우기 (셸 없음·창 없음·표준 오류 버림·출력 상한) */
function launch(env: NodeJS.ProcessEnv, file: string, args: string[], timeoutMs: number) {
  const child = childProcess.spawn(file, args, { shell: false, windowsHide: true, env, stdio: ["ignore", "pipe", "ignore"] });
  const result = new Promise<ExecOutcome>((resolve) => {
    let stdout = "";
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      if (stdout.length < OUTPUT_LIMIT) stdout += chunk;
    });
    const timer = setTimeout(() => child.kill(), timeoutMs);
    child.on("error", () => {
      clearTimeout(timer);
      resolve({ code: null, stdout });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout });
    });
  });
  return { child, result };
}

/** 프로세스 트리 끝내기 (agent-job CLI → 감독하는 Agent CLI·손자까지) */
export function killProcessTree(child: childProcess.ChildProcess): void {
  if (child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32" && child.pid !== undefined) {
    childProcess.spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", timeout: 10_000 });
    return;
  }
  child.kill("SIGKILL");
}

export function nodeExec(env: NodeJS.ProcessEnv) {
  return (file: string, args: string[], timeoutMs: number): Promise<ExecOutcome> => launch(env, file, args, timeoutMs).result;
}

export function nodeSpawn(env: NodeJS.ProcessEnv) {
  return (file: string, args: string[], onExit: (outcome: ExecOutcome) => void): RunningChild => {
    // 작업 시간 상한은 agent-job이 지킨다 (예산 + 유예). 여기서는 하루를 넘기면 끊는 안전망만
    const { child, result } = launch(env, file, args, 24 * 3600_000);
    const done = result.then(onExit);
    return { done, killTree: () => killProcessTree(child) };
  };
}
