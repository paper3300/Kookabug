// 실행 E2E 도우미 (M2 계획 T11): 가짜 플랫폼으로 예제 워크스페이스를 실행한다.
// - 예제 워크스페이스 + 장면 PNG(frames)를 임시 폴더에 나란히 복사하고 `.kookabug/local.json`(게임 설정)을 쓴다
//   (CLI 인수 검사 copy_example_workspace와 같은 모양)
// - 가짜 플랫폼 사양은 워크스페이스 밖(옆)에 쓴다. 입력 훅 `wait:<경로>`로 실행을 그 입력 앞에서 세운다:
//   그 입력에 닿으면 `<경로>.ready`가 생기고, `<경로>.go`를 만들면 이어 간다
// - daemon은 앱이 띄운다. 환경(KOOKABUG_DAEMON_ARGS·비밀값·OCR 모델·임대권 상태 폴더)은 앱 → daemon → runner로
//   이어진다. 입력 임대권 상태 폴더는 검사마다 따로 둔다 (사람의 실제 임대권과 섞이지 않게)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type ElectronApplication, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, REPO_ROOT, setContentSize, stubOpenDialog } from "./app";
import { cleanupWorkspace, SAMPLE_WORKSPACE, waitConnected } from "./daemon";

export const INVENTORY = "tests/inventory_open.graph.json";
export const SWAPPED = "tests/broken/swapped_target.graph.json";
const FRAMES = path.join(REPO_ROOT, "fixtures", "sample-game", "frames");
const GAME_DIR = path.join(REPO_ROOT, "fixtures", "sample-game");
const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const OCR_MODELS = process.env.KOOKABUG_OCR_MODELS ?? path.join(REPO_BUILD, "ocr-models");
const OCR_MANIFEST = path.join(REPO_ROOT, "python", "kookabug_platform", "src", "kookabug_platform", "ocr", "models.toml");

/**
 * 예제 그래프(enter_world)는 OCR 노드를 지난다. 모델이 없으면 실행이 error로 끝나 지점·멈춤 대기가 시간 초과로만
 * 보이므로, 실행 준비 때 모델 표의 파일이 다 있는지 먼저 확인한다 (크기·SHA256은 daemon이 본다)
 */
function requireOcrModels(): void {
  const files = [...fs.readFileSync(OCR_MANIFEST, "utf8").matchAll(/^file\s*=\s*"([^"]+)"/gm)].map((m) => m[1]);
  const missing = files.filter((f) => !fs.existsSync(path.join(OCR_MODELS, f)));
  if (files.length === 0 || missing.length > 0) {
    throw new Error(
      `OCR 모델이 없다: ${OCR_MODELS} (${missing.join(", ") || "모델 표를 못 읽음"}). ` +
        "`uv run python tools/fetch_ocr_models.py`로 받는다 (다른 폴더면 KOOKABUG_OCR_MODELS)",
    );
  }
}

export interface RunWorkspace {
  root: string;
  platform: string;
  stateDir: string;
  /** 입력 훅으로 세운 지점: 닿으면 ready, go를 만들면 이어 간다 */
  gates: Record<string, string>;
}

/**
 * 실행할 워크스페이스 사본. gates = 입력 이름(`i`, `mouse:left`) → 지점 이름. 그 입력을 처음 누르기 직전에 선다
 */
export function prepareRunWorkspace(gates: Record<string, string> = {}, name = "sample-rpg"): RunWorkspace {
  requireOcrModels();
  const parent = fs.mkdtempSync(path.join(os.tmpdir(), "kb-ws-"));
  const root = path.join(parent, name);
  fs.cpSync(SAMPLE_WORKSPACE, root, { recursive: true, filter: (src) => path.basename(src) !== "runs" });
  fs.cpSync(FRAMES, path.join(parent, "frames"), { recursive: true });
  fs.mkdirSync(path.join(root, ".kookabug"), { recursive: true });
  fs.writeFileSync(
    path.join(root, ".kookabug", "local.json"),
    JSON.stringify({ format: "kookabug.local/0", settings: { "game.cwd": GAME_DIR, "game.executable": PYTHON } }),
  );
  const gateDir = path.join(parent, "gates");
  fs.mkdirSync(gateDir);
  const bases: Record<string, string> = {};
  const before: Record<string, string> = {};
  for (const [input, gate] of Object.entries(gates)) {
    bases[gate] = path.join(gateDir, gate).split(path.sep).join("/");
    before[input] = `wait:${bases[gate]}`;
  }
  const platform = path.join(parent, "platform.json");
  fs.writeFileSync(
    platform,
    JSON.stringify({ scenario: "frames/scenario.json", input_log: "fake-input.jsonl", hooks: { before_down: before } }),
  );
  const stateDir = path.join(parent, "state");
  fs.mkdirSync(stateDir);
  return { root, platform, stateDir, gates: bases };
}

export function runEnv(ws: RunWorkspace): Record<string, string> {
  return {
    KOOKABUG_DAEMON_ARGS: JSON.stringify(["--platform-fake", ws.platform]),
    KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01: "sample-pass-01",
    KOOKABUG_OCR_MODELS: OCR_MODELS,
    KOOKABUG_STATE_DIR: ws.stateDir,
    KOOKABUG_E2E_HOOKS: "1",
  };
}

export interface RunSession {
  app: ElectronApplication;
  page: Page;
  userData: string;
  ws: RunWorkspace;
}

/** 앱을 띄워 이 워크스페이스를 연다. scaleFactor 1 = 시안 비교 스크린샷 */
export async function openRunApp(
  ws: RunWorkspace,
  options: { scaleFactor?: number; userData?: string } = {},
): Promise<RunSession> {
  const launched = await launchApp({ env: runEnv(ws), ...options });
  const page = await launched.app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(launched.app, page, 1440, 900);
  await stubOpenDialog(launched.app, ws.root);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  return { app: launched.app, page, userData: launched.userData, ws };
}

export async function closeRunApp(s: RunSession | null, keepWorkspace = false): Promise<void> {
  if (s === null) return;
  await closeApp(s.app);
  if (!keepWorkspace) await cleanupWorkspace(s.ws.root);
  fs.rmSync(s.userData, { recursive: true, force: true });
}

/** 실행이 그 지점에 닿을 때까지 */
export async function waitGate(ws: RunWorkspace, gate: string, timeout = 60_000): Promise<void> {
  await expect.poll(() => fs.existsSync(`${ws.gates[gate]}.ready`), { timeout, message: `지점 ${gate}` }).toBe(true);
}

export function releaseGate(ws: RunWorkspace, gate: string): void {
  fs.writeFileSync(`${ws.gates[gate]}.go`, "");
}

export function toolbar(page: Page): Locator {
  return page.locator('[data-part="run-toolbar"]');
}

const SIAN_MAIN = path.join(import.meta.dirname, "..", "fixtures", "sian-main.graph.json");
/** 시안 Main 그래프를 실행할 자리 (시안 비교 스크린샷) */
export const SIAN_RUN_GRAPH = "tests/enchant_loop.graph.json";

/**
 * e2e/fixtures/sian-main.graph.json(시안 Main 노드 배치)에서 "창 찾기"만 가짜 플랫폼에서 돌도록 게임 실행 노드로
 * 바꾼 것 (가짜 플랫폼에는 실행 전에 창이 없다)
 */
export function runnableSianMain(): string {
  const graph = JSON.parse(fs.readFileSync(SIAN_MAIN, "utf8")) as { nodes: Record<string, Record<string, unknown>> };
  graph.nodes.n_attach = {
    ...graph.nodes.n_attach,
    type: "core.app.launch",
    in: {
      args: { $setting: "game.args" },
      cwd: { $setting: "game.cwd" },
      path: { $setting: "game.executable" },
      timeout_ms: 30000,
      window_title: { $setting: "game.title" },
    },
    next: { attached: "n_repeat" },
  };
  return JSON.stringify(graph, null, 2);
}

/** 디버그 툴바 (시안 "실행 제어", M3 T9). 실행이 있을 때만 있다. 정지 단추는 여기에만 있다 */
export function debugToolbar(page: Page): Locator {
  return page.locator('[data-part="debug-toolbar"]');
}

export async function clickRun(page: Page): Promise<void> {
  const play = toolbar(page).getByRole("button", { name: "실행 F5" });
  await expect(play).toBeEnabled();
  await play.click();
}

export async function waitEnded(page: Page, verdict?: string, timeout = 90_000): Promise<void> {
  await expect(toolbar(page)).toHaveAttribute("data-phase", "ended", { timeout });
  if (verdict !== undefined) await expect(toolbar(page)).toHaveAttribute("data-verdict", verdict);
}

/** 실행 폴더의 events.jsonl 줄 */
export function readEvents(ws: RunWorkspace, runId: string): Record<string, unknown>[] {
  const runs = path.join(ws.root, "runs");
  const dir = fs.readdirSync(runs).find((d) => d.endsWith(`_${runId}`));
  if (dir === undefined) throw new Error(`실행 폴더가 없다: ${runId}`);
  return fs
    .readFileSync(path.join(runs, dir, "events.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

export function runFolders(ws: RunWorkspace): string[] {
  const runs = path.join(ws.root, "runs");
  return fs.existsSync(runs) ? fs.readdirSync(runs).filter((d) => fs.statSync(path.join(runs, d)).isDirectory()) : [];
}

export function runFolder(ws: RunWorkspace, runId: string): string {
  const dir = runFolders(ws).find((d) => d.endsWith(`_${runId}`));
  if (dir === undefined) throw new Error(`실행 폴더가 없다: ${runId}`);
  return path.join(ws.root, "runs", dir);
}

/** 노드 하나 (캔버스) */
export function runNode(page: Page, id: string): Locator {
  return page.locator(`[data-part="node"][data-node-id="${id}"]`);
}
