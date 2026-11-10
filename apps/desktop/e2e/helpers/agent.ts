// 에이전트 패널 E2E 도우미 (M5 B5): 가짜 ACP 에이전트(tools/kb_testing/fake_acp_agent.py)를 KOOKABUG_E2E_AGENT로
// 지정해 앱을 띄운다. 사용자 설정 폴더(KOOKABUG_USER_CONFIG_DIR)는 검사마다 따로 둔다 — daemon이 agents·권한 사용자
// 계층을 여기서 읽는다. 실제 에이전트 CLI는 쓰지 않는다
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";
import { REPO_ROOT } from "./app";
import { closeRunApp, openRunApp, prepareRunWorkspace, runEnv, type RunSession, type RunWorkspace } from "./run";

const PYTHON = path.join(REPO_ROOT, ".venv", "Scripts", "python.exe");
const FAKE_AGENT = path.join(REPO_ROOT, "tools", "kb_testing", "fake_acp_agent.py");

/** 설정에 넣는 에이전트 (명령은 KOOKABUG_E2E_AGENT가 가짜로 바꾼다) */
export const PANEL_AGENT = { id: "claude-code", name: "Claude Code", command: "claude-code-acp" };

export interface AgentSession extends RunSession {
  userDir: string;
  script: string;
  log: string;
}

export interface AgentOptions {
  /** 가짜 에이전트 각본 (fake_acp_agent.py 문서) */
  script?: Record<string, unknown>;
  /** 사용자 설정 settings.json (없으면 PANEL_AGENT 하나) */
  settings?: Record<string, unknown> | null;
  scaleFactor?: number;
  /** 앱을 띄우기 전에 워크스페이스·가짜 게임 사양을 고친다 (M7 탐색: 게임이 떠 있음·explorer 권한) */
  prepare?: (ws: RunWorkspace) => void;
}

export async function openAgentApp(options: AgentOptions = {}): Promise<AgentSession> {
  const ws = prepareRunWorkspace();
  options.prepare?.(ws);
  const base = fs.mkdtempSync(path.join(os.tmpdir(), "kb-agent-"));
  const userDir = path.join(base, "user");
  fs.mkdirSync(userDir);
  const settings =
    options.settings === undefined
      ? { format: "kookabug.user-settings/0", agents: [PANEL_AGENT] }
      : options.settings;
  if (settings !== null) fs.writeFileSync(path.join(userDir, "settings.json"), JSON.stringify(settings, null, 2));
  const script = path.join(base, "script.json");
  const log = path.join(base, "agent-log.jsonl");
  fs.writeFileSync(script, JSON.stringify(options.script ?? {}));
  const env = {
    ...runEnv(ws),
    KOOKABUG_USER_CONFIG_DIR: userDir,
    KOOKABUG_E2E_AGENT: JSON.stringify({
      command: PYTHON,
      args: [FAKE_AGENT],
      env: { KB_FAKE_ACP_SCRIPT: script, KB_FAKE_ACP_LOG: log },
    }),
  };
  const s = await openRunApp(ws, {
    env,
    ...(options.scaleFactor === undefined ? {} : { scaleFactor: options.scaleFactor }),
  });
  return { ...s, userDir, script, log };
}

export async function closeAgentApp(s: AgentSession | null): Promise<void> {
  if (s === null) return;
  await closeRunApp(s);
  fs.rmSync(path.dirname(s.userDir), { recursive: true, force: true });
}

/** 가짜 에이전트 각본을 바꾼다 (다음 세션부터) */
export function setScript(s: AgentSession, script: Record<string, unknown>): void {
  fs.writeFileSync(s.script, JSON.stringify(script));
}

/** 가짜 에이전트 기록 줄 */
export function agentLog(s: AgentSession): Record<string, unknown>[] {
  if (!fs.existsSync(s.log)) return [];
  return fs
    .readFileSync(s.log, "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

export function agentPanel(page: Page): Locator {
  return page.locator('[data-part="agent-panel"]');
}

/** 오른쪽 패널 에이전트 탭을 연다 */
export async function showAgentTab(page: Page): Promise<Locator> {
  const tab = page.locator('[data-part="agent-tab"]');
  if ((await tab.count()) === 0) {
    await page.getByRole("button", { name: "보기", exact: true }).click();
    await page.getByRole("menuitem", { name: "에이전트 패널" }).click();
  } else {
    await tab.click();
  }
  const panel = agentPanel(page);
  await expect(panel).toBeVisible();
  return panel;
}

/** 설정한 에이전트로 연결 (세션 ready까지) */
export async function connectAgent(page: Page, id = PANEL_AGENT.id): Promise<void> {
  const panel = await showAgentTab(page);
  await panel.locator(`[data-part="agent-row"][data-id="${id}"]`).getByRole("button", { name: "연결" }).click();
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
}

export async function sendMessage(page: Page, text: string): Promise<void> {
  const panel = agentPanel(page);
  await panel.getByRole("textbox", { name: "에이전트에게 메시지" }).fill(text);
  await panel.getByRole("button", { name: "보내기" }).click();
}
