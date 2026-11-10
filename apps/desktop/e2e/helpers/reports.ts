// 보고함 E2E 도우미 (M8 B7). 새 파일만 (기존 helpers는 main과 겹쳐 고치지 않는다)
// - 결과 워크스페이스는 B6 실제 흐름으로 만든다: 예제 상점 가짜 게임(reports_world.py) + 앱이 띄운 daemon +
//   실제 `kookabug agent-job run --agent-command <가짜 QA CLI 각본>` (보고 JSON을 손으로 쓰지 않는다)
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DEFAULT_TEST_AGENT, REPO_CLI } from "./app";
import { fakeAgentCommand, OCR_MODELS, TOOLS_DIR, VENV_PYTHON } from "./wizard";

export interface ShopWorld {
  dir: string;
  root: string;
  platform: string;
  env: Record<string, string>;
}

export function prepareShopWorld(variant: "moved" | "missing"): ShopWorld {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-rep-"));
  const done = spawnSync(VENV_PYTHON, ["-X", "utf8", path.join(import.meta.dirname, "reports_world.py"), dir, variant], {
    env: { ...process.env, PYTHONPATH: TOOLS_DIR },
    encoding: "utf8",
  });
  if (done.status !== 0) throw new Error(`reports_world.py 실패: ${done.stderr}`);
  const { root, platform } = JSON.parse(done.stdout.trim().split(/\r?\n/).pop() ?? "{}") as { root: string; platform: string };
  const state = path.join(dir, "state");
  const user = path.join(dir, "user");
  fs.mkdirSync(state);
  fs.mkdirSync(user);
  // 에이전트가 설정된 사용자 (미설정이면 마법사 5단계가 자동으로 떠 보고함 화면을 덮는다)
  fs.writeFileSync(path.join(user, "settings.json"), JSON.stringify({ format: "kookabug.user-settings/0", agents: [DEFAULT_TEST_AGENT] }));
  return {
    dir,
    root,
    platform,
    env: {
      KOOKABUG_DAEMON_ARGS: JSON.stringify(["--platform-fake", platform]),
      KOOKABUG_OCR_MODELS: OCR_MODELS,
      KOOKABUG_STATE_DIR: state,
      KOOKABUG_USER_CONFIG_DIR: user,
      KOOKABUG_E2E_HOOKS: "1",
      PYTHONPATH: TOOLS_DIR,
    },
  };
}

export interface CliOutcome {
  code: number | null;
  json: Record<string, unknown>;
  ms: number;
}

/** 사람 쪽 CLI 하나 (앱이 띄운 daemon에 붙는다) */
export function runCli(world: ShopWorld, args: string[], timeoutMs = 300_000): Promise<CliOutcome> {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const child = spawn(REPO_CLI, args, { cwd: world.root, env: { ...process.env, ...world.env }, windowsHide: true });
    let out = "";
    let err = "";
    child.stdout.setEncoding("utf8").on("data", (c: string) => (out += c));
    child.stderr.setEncoding("utf8").on("data", (c: string) => (err += c));
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`${args.join(" ")}: ${timeoutMs}ms 안에 끝나지 않았다\n${err.slice(-2000)}`));
    }, timeoutMs);
    child.on("close", (code) => {
      clearTimeout(timer);
      const line = out.trim().split(/\r?\n/).pop() ?? "{}";
      try {
        resolve({ code, json: JSON.parse(line) as Record<string, unknown>, ms: Date.now() - started });
      } catch {
        reject(new Error(`JSON이 아닌 출력 (종료 ${code}): ${out.slice(-1000)}\n${err.slice(-2000)}`));
      }
    });
  });
}

/** 실제 agent-job run (가짜 QA CLI 각본) — 끝까지 기다린다 */
export function runAgentJob(world: ShopWorld, script: string, playbook = "repair"): Promise<CliOutcome> {
  return runCli(world, [
    "agent-job",
    "run",
    "--workspace",
    world.root,
    "--playbook",
    playbook,
    "--agent-command",
    fakeAgentCommand(script),
    "--json",
  ]);
}

/** agent-job run을 띄우고 기다리지 않는다 (취소 검사) */
export function startAgentJob(world: ShopWorld, script: string, playbook = "repair"): Promise<CliOutcome> {
  return runAgentJob(world, script, playbook);
}

export function readBytes(world: ShopWorld, rel: string): Buffer {
  return fs.readFileSync(path.join(world.root, ...rel.split("/")));
}

export function cleanupShopWorld(world: ShopWorld | null): void {
  if (world === null) return;
  try {
    fs.rmSync(world.dir, { recursive: true, force: true });
  } catch {
    // daemon이 아직 잡고 있는 파일
  }
}
