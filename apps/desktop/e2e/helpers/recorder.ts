// 녹화 E2E 도우미 (M4 계획 T9·T10, 작업 크기 메모 "각본 도우미는 e2e/helpers/recorder.ts 하나"). 가짜 플랫폼 + 가짜 각본
// (예제 로그인, fixtures/sample-game/recorder/*.script.jsonl)으로 실제 daemon 녹화 세션을 연다. 각본은 기다리지 않고
// 흘린다(--recorder-script-speed inf). 비밀값은 환경 변수(KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01)로 daemon·runner에 간다
import fs from "node:fs";
import path from "node:path";
import { expect, type Locator, type Page } from "@playwright/test";
import { REPO_ROOT, showActivity } from "./app";
import { writeFile } from "./editor";
import { openRunApp, prepareRunWorkspace, runEnv, type RunSession, type RunWorkspace } from "./run";
import { selectRect } from "./target";

export const SCRIPTS = path.join(REPO_ROOT, "fixtures", "sample-game", "recorder");
export const SECRET_KEY = "accounts.qa_tester_01";
export const SECRET_TEXT = "sample-pass-01";
export const ACCOUNT_TEXT = "qa_tester_01";
/** 로비 화면 "서버 선택" 제목 자리 (화면 확인 영역, daemon 검사와 같음) */
export const LOBBY_TITLE = [412, 90, 200, 60] as const;
/** 로그인 화면 비밀번호 칸 (예제 layout.py password_field) */
export const PASSWORD_FIELD = [400, 285, 320, 50] as const;

export type ScriptName = "login" | "login_split";

/** 예제 각본 끝에 훅 끊김(가짜 각본 fault hook_exit)을 붙인 각본 파일 (오류 정지 hook_lost 화면) */
export function scriptWithHookLost(dir: string, base: ScriptName = "login_split"): string {
  const lines = fs.readFileSync(path.join(SCRIPTS, `${base}.script.jsonl`), "utf8").split("\n").filter((l) => l.trim() !== "");
  const last = Math.max(...lines.map((l) => Number((JSON.parse(l) as { t_ns?: number }).t_ns ?? 0)));
  const out = path.join(dir, "hook_lost.script.jsonl");
  fs.writeFileSync(out, [...lines, JSON.stringify({ kind: "fault", fault: "hook_exit", t_ns: last + 500_000_000 })].join("\n") + "\n");
  return out;
}

/** 녹화용 워크스페이스 (실행 E2E와 같은 사본 + 게임 설정) */
export function prepareRecorderWorkspace(): RunWorkspace {
  return prepareRunWorkspace();
}

/** 각본 이름(fixtures) 또는 각본 파일 절대 경로 */
export function recorderEnv(ws: RunWorkspace, script: ScriptName | string = "login_split"): Record<string, string> {
  return {
    ...runEnv(ws),
    KOOKABUG_DAEMON_ARGS: JSON.stringify([
      "--platform-fake",
      ws.platform,
      "--recorder-script",
      path.isAbsolute(script) ? script : path.join(SCRIPTS, `${script}.script.jsonl`),
      "--recorder-script-speed",
      "inf",
    ]),
  };
}

/** 앱을 띄워 워크스페이스를 열고 녹화 사이드바를 보인다 */
export async function openRecorderApp(ws: RunWorkspace, options: { script?: ScriptName | string; scaleFactor?: number } = {}): Promise<RunSession> {
  const s = await openRunApp(ws, { ...(options.scaleFactor === undefined ? {} : { scaleFactor: options.scaleFactor }), env: recorderEnv(ws, options.script) });
  await showRecorder(s.page);
  return s;
}

export async function showRecorder(page: Page): Promise<void> {
  await showActivity(page.getByRole("button", { name: "녹화", exact: true }));
  await expect(page.locator('[data-part="recorder-sidebar"]')).toBeVisible();
}

export function sidebar(page: Page): Locator {
  return page.locator('[data-part="recorder-sidebar"]');
}

export function steps(page: Page): Locator {
  return page.locator('[data-part="rec-step"]');
}

export function statusbar(page: Page): Locator {
  return page.locator('[data-part="statusbar"]');
}

/** "게임 띄워서 녹화" → 녹화 중 */
export async function startLaunch(page: Page): Promise<void> {
  await sidebar(page).getByRole("button", { name: "게임 띄워서 녹화" }).click();
  await expect(sidebar(page)).toHaveAttribute("data-state", /recording|paused|stopped/, { timeout: 60_000 });
}

/**
 * 각본이 다 흘러 로그인 스텝(클릭·클릭·글자·키·글자·클릭)이 쌓이고 비밀번호 판정이 끝날 때까지 (판정 중이 없음,
 * 비밀값 띠가 뜸)
 */
export async function waitLoginRecorded(page: Page): Promise<void> {
  await expect
    .poll(async () => (await steps(page).evaluateAll((els) => els.map((e) => e.getAttribute("data-kind")))).filter((k) => k !== "wait" && k !== "delay").length, {
      timeout: 90_000,
      message: "로그인 스텝 6개",
    })
    .toBeGreaterThanOrEqual(6);
  await expect(page.locator('[data-part="rec-step"][data-text-state="pending"]')).toHaveCount(0, { timeout: 60_000 });
  await expect(page.locator('[data-part="secret-row"]')).toHaveCount(1, { timeout: 30_000 });
}

/** 확인 넣기 모드로: 지금 화면을 다시 올리는 것이 끝나 판이 맞춰질 때까지 (그 전에 끌면 영역이 지워진다) */
export async function beginCheckMode(page: Page, button: "화면 확인 삽입" | "값 확인 삽입"): Promise<void> {
  await sidebar(page).getByRole("button", { name: button }).click();
  const tab = page.locator('[data-part="rec-tab"]');
  await expect(tab).toHaveAttribute("data-check", button === "화면 확인 삽입" ? "visible" : "text");
  await expect(tab).toHaveAttribute("data-loading", "false", { timeout: 30_000 });
  await expect(tab).not.toHaveAttribute("data-frame", "");
  const frame = (await tab.getAttribute("data-frame")) ?? "";
  await expect(page.locator('[data-part="target-frame"]')).toHaveAttribute("data-frame", frame);
  await expect(page.locator('[data-part="target-frame"]')).not.toHaveAttribute("data-view", "", { timeout: 30_000 });
}

/** 화면 확인 넣기: 지금 화면에서 로비 제목 영역 → 넣기 → check_visible 스텝 */
export async function insertLobbyCheck(page: Page): Promise<void> {
  const before = await page.locator('[data-part="rec-step"][data-kind="check_visible"]').count();
  await beginCheckMode(page, "화면 확인 삽입");
  await selectRect(page, LOBBY_TITLE);
  await page.locator('[data-part="rec-check-band"]').getByRole("button", { name: "넣기" }).click();
  await expect(page.locator('[data-part="rec-step"][data-kind="check_visible"]')).toHaveCount(before + 1, { timeout: 30_000 });
}

export async function stopRecording(page: Page): Promise<void> {
  await sidebar(page).getByRole("button", { name: "녹화 정지" }).click();
  await expect(sidebar(page)).toHaveAttribute("data-state", "stopped", { timeout: 30_000 });
}

/** 비밀값 띠에서 키를 적어 고른다 */
export async function chooseSecret(page: Page, key = SECRET_KEY): Promise<void> {
  const row = page.locator('[data-part="secret-row"]');
  await row.getByRole("combobox", { name: "비밀값 키" }).fill(key);
  await row.getByRole("button", { name: "고르기" }).click();
  await expect(row).toHaveCount(0, { timeout: 30_000 });
}

export function saveButton(page: Page): Locator {
  return page.locator('[data-part="rec-save"]').getByRole("button", { name: "새 테스트로 저장" });
}

export function insertButton(page: Page): Locator {
  return page.locator('[data-part="rec-save"]').getByRole("button", { name: "커서 위치에 노드로 삽입" });
}

/** 새 테스트로 저장 → 이름 → 그 그래프 탭이 열리고 녹화가 끝남 */
export async function saveNewTest(page: Page, name: string): Promise<string> {
  await saveButton(page).click();
  const dialog = page.getByRole("dialog", { name: "새 테스트로 저장" });
  await dialog.getByRole("textbox", { name: "이름" }).fill(name);
  await dialog.getByRole("button", { name: "저장" }).click();
  const rel = `tests/${name}.graph.json`;
  await expect(page.locator(`[role="tab"][data-path="${rel}"]`)).toHaveAttribute("aria-selected", "true", { timeout: 60_000 });
  await expect(page.locator('[data-part="rec-committed"]')).toBeVisible({ timeout: 30_000 });
  return rel;
}

/** 실행할 수 있는 테스트: 게임 띄우기 → (넣을 자리) → 로비 기다리기 → 통과 */
export const CHAIN_TEST = "tests/rec_chain.graph.json";
export function writeChainTest(ws: RunWorkspace): void {
  writeFile(
    ws.root,
    CHAIN_TEST,
    JSON.stringify(
      {
        format: "kookabug.graph/0",
        kind: "test",
        plugins: { core: "0.1.0" },
        nodes: {
          n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_launch" } },
          n_launch: {
            type: "core.app.launch",
            version: 1,
            in: {
              args: { $setting: "game.args" },
              cwd: { $setting: "game.cwd" },
              path: { $setting: "game.executable" },
              timeout_ms: 30000,
              window_title: { $setting: "game.title" },
            },
            next: { attached: "n_lobby" },
          },
          n_lobby: {
            type: "core.image.wait",
            version: 1,
            title: "로비 기다리기",
            in: { target: { $target: "targets/lobby/server_list.target.json" }, timeout_ms: 20000 },
            next: { found: "n_pass" },
          },
          n_pass: { type: "core.test.pass", version: 1 },
        },
        layout: { nodes: { n_entry: { x: 0, y: 0 }, n_launch: { x: 260, y: 0 }, n_lobby: { x: 520, y: 0 }, n_pass: { x: 780, y: 0 } } },
      },
      null,
      2,
    ),
  );
}

/** 넣을 서브그래프: 시작 → 출구 done */
export const CHAIN_SUB = "subgraphs/rec_sub.graph.json";
export function writeChainSubgraph(ws: RunWorkspace): void {
  writeFile(
    ws.root,
    CHAIN_SUB,
    JSON.stringify(
      {
        format: "kookabug.graph/0",
        kind: "subgraph",
        plugins: { core: "0.1.0" },
        interface: { exits: { done: { kind: "ok" } } },
        nodes: {
          n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_exit" } },
          n_exit: { type: "core.graph.exit", version: 1, config: { exit: "done" } },
        },
        layout: { nodes: { n_entry: { x: 0, y: 0 }, n_exit: { x: 280, y: 0 } } },
      },
      null,
      2,
    ),
  );
}
