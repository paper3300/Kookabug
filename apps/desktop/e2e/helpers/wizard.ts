// 마법사 E2E 도우미 (M8 B7). 새 파일만 — 기존 helpers는 main과 겹쳐 고치지 않는다
// - 가짜 플랫폼: 예제 게임 장면 표를 임시 폴더에 복사하고 이미 떠 있는 창(running)으로 둔다 → 2단계 창 목록에 보인다
// - 사용자 설정·입력 임대권 상태 폴더는 검사마다 따로 (사람의 실제 설정과 섞이지 않게)
// - Init·연결 시험의 Agent는 주 프로세스 E2E 훅(KOOKABUG_E2E_AGENT_JOB)이 주는 가짜 QA CLI다 (렌더러가 명령을 주지 않는다)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type ElectronApplication, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, REPO_ROOT, setContentSize, stubOpenDialog } from "./app";
import { readSession, waitConnected } from "./daemon";

export const VENV_PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
export const TOOLS_DIR = path.join(REPO_ROOT, "tools");
export const OCR_MODELS = process.env.KOOKABUG_OCR_MODELS ?? path.join(REPO_BUILD, "ocr-models");
const FRAMES = path.join(REPO_ROOT, "fixtures", "sample-game", "frames");
/** 연결 시험·Init 둘 다 지나는 짧은 각본 (kb_project_info 한 번) */
export const MIN_SCRIPT = path.join(import.meta.dirname, "..", "fixtures", "qa-init-min.json");

export interface WizardWorld {
  dir: string;
  /** 1단계 "위치"로 고를 폴더 */
  parent: string;
  platform: string;
  env: Record<string, string>;
}

/**
 * 세계마다 따로 쓰는 입력 임대권 뮤텍스 이름 (kb_testing/proc.py `isolated_env`와 같은 뜻).
 * 기본 이름(`Local\Kookabug.InputLease`)은 Windows 세션 전체에 하나라, 같은 PC에서 사람이 띄운 Kookabug가
 * 실행·녹화 중이면 검사 실행이 `input_lease_busy`로 끝난다. 상태 폴더(`KOOKABUG_STATE_DIR`)만 나눠서는 막지 못한다
 */
export function isolatedLeaseName(dir: string): string {
  return `Local\\Kookabug.InputLease.e2e-${path.basename(dir)}`;
}

/** 가짜 QA CLI 명령줄 (agent-job custom 프로필이 CommandLineToArgvW로 나눈다) */
export function fakeAgentCommand(script: string): string {
  return `"${VENV_PYTHON}" -m kb_testing.fake_qa_agent --script "${script}"`;
}

export function prepareWizardWorld(script = MIN_SCRIPT): WizardWorld {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "kb-wiz-"));
  const parent = path.join(dir, "projects");
  fs.mkdirSync(parent);
  const frames = path.join(dir, "frames");
  fs.cpSync(FRAMES, frames, { recursive: true });
  const table = JSON.parse(fs.readFileSync(path.join(frames, "scenario.json"), "utf8")) as Record<string, unknown>;
  table.running = true;
  fs.writeFileSync(path.join(frames, "scenario.json"), JSON.stringify(table));
  const platform = path.join(dir, "platform.json");
  fs.writeFileSync(platform, JSON.stringify({ scenario: path.join(frames, "scenario.json"), input_log: path.join(dir, "input.jsonl") }));
  const state = path.join(dir, "state");
  const user = path.join(dir, "user");
  fs.mkdirSync(state);
  fs.mkdirSync(user);
  return {
    dir,
    parent,
    platform,
    env: {
      KOOKABUG_DAEMON_ARGS: JSON.stringify(["--platform-fake", platform]),
      KOOKABUG_OCR_MODELS: OCR_MODELS,
      KOOKABUG_STATE_DIR: state,
      KOOKABUG_INPUT_LEASE_NAME: isolatedLeaseName(dir),
      KOOKABUG_USER_CONFIG_DIR: user,
      KOOKABUG_E2E_HOOKS: "1",
      KOOKABUG_E2E_AGENT_JOB: fakeAgentCommand(script),
      PYTHONPATH: TOOLS_DIR,
    },
  };
}

export interface WizardSession {
  app: ElectronApplication;
  page: Page;
  userData: string;
}

export async function launchWizardApp(world: WizardWorld, options: { userData?: string; width?: number; height?: number } = {}): Promise<WizardSession> {
  const { app, userData } = await launchApp({ env: world.env, scaleFactor: 1, userData: options.userData });
  const page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, options.width ?? 1120, options.height ?? 720);
  return { app, page, userData };
}

/** 시작 화면 "이미 있는 프로젝트 열기"로 연다 (대화 상자는 이 폴더를 고른 것처럼) */
export async function openProject(s: WizardSession, root: string): Promise<void> {
  await stubOpenDialog(s.app, root);
  await s.page.getByRole("button", { name: "이미 있는 프로젝트 열기", exact: true }).click();
  await waitConnected(s.page);
}

export function overlay(page: Page): Locator {
  return page.locator('[data-screen="wizard"]');
}

export function nextButton(page: Page): Locator {
  return page.locator('[data-part="wizard-next"]');
}

export async function expectStep(page: Page, step: number, timeout = 30_000): Promise<void> {
  await expect(overlay(page)).toHaveAttribute("data-step", String(step), { timeout });
}

/** "다음"(또는 그 단계의 주 단추)을 눌러 다음 단계로 — 눌리기 전에 켜져 있는지부터 본다 (꺼진 단추 클릭을 성공으로 보지 않게) */
export async function pressNext(page: Page, expectNext: number, timeout = 60_000): Promise<void> {
  await expect(nextButton(page)).toBeEnabled({ timeout });
  await nextButton(page).click();
  await expectStep(page, expectNext, timeout);
}

export async function skipStep(page: Page, expectNext: number): Promise<void> {
  await page.getByRole("button", { name: "건너뛰기" }).click();
  await expectStep(page, expectNext);
}

export function readWizardFile(root: string): { step: number; done: number[]; skipped: number[]; warnings: { step: number; code: string }[] } & Record<string, unknown> {
  return JSON.parse(fs.readFileSync(path.join(root, ".kookabug", "wizard.json"), "utf8")) as never;
}

/** 저장된 마법사 진행을 이 PC에 둔다 (다시 열면 그 단계부터 이어서 — M8 인수 B8) */
export function writeWizardProgress(root: string, progress: { step: number; done: number[]; skipped: number[] }): void {
  const file = path.join(root, ".kookabug", "wizard.json");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, `${JSON.stringify({ format: "kookabug.wizard/0", ...progress, warnings: [] }, null, 2)}\n`);
}

export async function closeWizardApp(s: WizardSession | null): Promise<void> {
  if (s === null) return;
  await closeApp(s.app);
}

/** 검사 끝: 연 워크스페이스들의 daemon을 끄고(UI를 꺼도 daemon은 남는다) 검사 폴더를 지운다 */
export async function cleanupWorld(world: WizardWorld | null, roots: readonly string[] = []): Promise<void> {
  if (world === null) return;
  for (const root of roots) {
    const session = readSession(root);
    if (session === null) continue;
    try {
      process.kill(session.pid);
    } catch {
      // 이미 끝남
    }
    await expect.poll(() => alive(session.pid), { timeout: 15_000 }).toBe(false);
  }
  for (let i = 0; i < 25; i++) {
    try {
      fs.rmSync(world.dir, { recursive: true, force: true });
      return;
    } catch {
      await new Promise((r) => setTimeout(r, 200));
    }
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}
