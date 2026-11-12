// UX3 (Agent 읽기 허용 폴더) E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) → 실제 `kookabug agent-job run`(가짜 QA CLI 각본).
// 실제 게임 입력·네트워크·실제 Agent CLI 없음. 샘플 게임 워크스페이스만 쓴다
// - 6단계 "Agent가 읽어도 되는 폴더": 자동 포함 줄(게임 실행 파일 폴더)이 보이고, 워크스페이스를 품는 폴더는 저장 거부(이유 그대로),
//   워크스페이스 밖 임시 폴더는 이 PC local.json에 저장
// - Init(가짜 Agent)이 그 폴더 아래 실행 bat를 kb_source_read로 읽고, 게임 실행 파일 폴더(read:game)도 읽는다
// 샷: build/e2e/ux3-shots
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { REPO_BUILD } from "./helpers/app";
import { copySampleWorkspace } from "./helpers/daemon";
import { runAgentJob } from "./helpers/reports";
import {
  cleanupWorld,
  closeWizardApp,
  expectStep,
  launchWizardApp,
  nextButton,
  openProject,
  prepareWizardWorld,
  writeWizardProgress,
  type WizardSession,
  type WizardWorld,
} from "./helpers/wizard";

const SCRIPT = path.join(import.meta.dirname, "fixtures", "qa-ux3.json");
const SHOTS = path.join(REPO_BUILD, "e2e", "ux3-shots");

let s: WizardSession | null = null;
let world: WizardWorld | null = null;
let roots: string[] = [];

test.afterEach(async () => {
  await closeWizardApp(s);
  s = null;
  await cleanupWorld(world, roots);
  world = null;
  roots = [];
});

type Json = Record<string, unknown>;

function readJson(file: string): Json {
  return JSON.parse(fs.readFileSync(file, "utf8").replace(/^﻿/, "")) as Json;
}

async function shot(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

test("6단계에서 밖 폴더를 읽기 허용 폴더로 저장 → Init이 그 아래 파일과 게임 실행 파일 폴더를 읽는다", async () => {
  test.setTimeout(420_000);
  world = prepareWizardWorld(SCRIPT);
  const w = world;
  const root = copySampleWorkspace("ux3");
  roots.push(root);
  writeWizardProgress(root, { step: 6, done: [1, 2, 3], skipped: [4, 5] });
  // 게임 실행 파일 폴더 (자동 포함) · 실행 bat 폴더 (사람이 더함) — 둘 다 워크스페이스 밖
  const game = path.join(w.dir, "game");
  fs.mkdirSync(game);
  fs.writeFileSync(path.join(game, "Game.exe"), "MZ");
  fs.writeFileSync(path.join(game, "servers.json"), JSON.stringify({ servers: ["dev-server"] }));
  const tools = path.join(w.dir, "launch_tools");
  fs.mkdirSync(tools);
  fs.writeFileSync(path.join(tools, "launch.bat"), "@echo off\r\nGame.exe -server=dev\r\n");
  fs.writeFileSync(path.join(tools, ".env"), "TOKEN=x\n");
  fs.writeFileSync(path.join(w.dir, "secret.txt"), "밖 파일");
  const localFile = path.join(root, ".kookabug", "local.json");
  fs.mkdirSync(path.dirname(localFile), { recursive: true });
  fs.writeFileSync(
    localFile,
    JSON.stringify({ format: "kookabug.local/0", permissions: { preset: "curator" }, settings: { "game.executable": path.join(game, "Game.exe") } }, null, 2),
  );

  s = await launchWizardApp(w, { height: 820 });
  await openProject(s, root);
  const page = s.page;
  await expectStep(page, 6, 30_000);
  await expect(nextButton(page)).toBeEnabled({ timeout: 15_000 });
  const group = page.locator('[data-part="read-roots"]');
  // 자동 포함 줄: 고칠 수 없다
  const auto = group.locator('[data-part="read-root-auto"][data-root="read:game"]');
  await expect(auto).toHaveAttribute("data-state", "ok");
  await expect(auto.locator("input")).toHaveValue(game);
  await expect(auto.locator("input")).toHaveAttribute("readonly", "");
  await expect(group.locator('[data-part="read-roots-note"]')).toContainText("외부 AI 서비스");

  // 워크스페이스를 품는 폴더는 저장하지 않는다 (이유를 그대로)
  const before = fs.readFileSync(localFile);
  await group.getByLabel("읽어도 되는 폴더 1", { exact: true }).fill(path.dirname(root));
  await nextButton(page).click();
  const error = group.locator('[data-part="read-roots-error"]');
  await expect(error).toContainText("1번째 폴더를 저장하지 않았어요", { timeout: 30_000 });
  await expect(error).toContainText("워크스페이스를 품는 폴더");
  expect(fs.readFileSync(localFile).equals(before)).toBe(true);
  await shot(page, "wizard-step6-read-roots-error");

  // 밖 임시 폴더는 저장된다 (여러 줄 — 둘째 줄은 비워 둔다)
  await group.getByLabel("읽어도 되는 폴더 1", { exact: true }).fill(tools);
  await group.locator('[data-part="read-root-add"]').click();
  await expect(group.locator('[data-part="read-root"]')).toHaveCount(2);
  await expect(error).toHaveCount(0);
  await nextButton(page).click();
  await expect(nextButton(page)).toHaveText(/다음/, { timeout: 30_000 });
  const settings = readJson(localFile).settings as Json;
  expect(settings["agent.read_roots"]).toEqual([tools]);
  expect(settings["game.executable"]).toBe(path.join(game, "Game.exe"));
  // 팀 설정에는 두지 않는다
  expect(JSON.stringify(readJson(path.join(root, "kookabug.json")))).not.toContain("read_roots");
  await shot(page, "wizard-step6-read-roots");

  // Init (9단계와 같은 agent-job run, 가짜 QA CLI) — 각본이 목록·읽기·이름 거부·근거 아님을 단언한다
  const init = await runAgentJob({ dir: w.dir, root, platform: w.platform, env: w.env }, SCRIPT, "init");
  expect(init.code, JSON.stringify(init.json)).toBe(0);
  expect(init.json.state).toBe("done");
  const job = String(init.json.job);
  const fake = readJson(path.join(root, ".kookabug", "jobs", job, "fake.json"));
  expect(fake.failed, JSON.stringify(fake)).toBeUndefined();
  expect(tools.startsWith(path.dirname(root))).toBe(false); // 읽기 허용 폴더는 워크스페이스 밖
  const activity = fs
    .readFileSync(path.join(root, ".kookabug", "jobs", job, "activity.jsonl"), "utf8")
    .trim()
    .split(/\r?\n/)
    .map((l) => JSON.parse(l) as Json);
  expect(activity.some((e) => e.tool === "kb_source_read" && e.target === "read:1:launch.bat")).toBe(true);
  expect(activity.some((e) => e.tool === "kb_source_read" && e.target === "read:game:servers.json")).toBe(true);
  // 읽기 허용 폴더 파일은 근거가 아니라 주장이 생기지 않았다
  expect(fs.existsSync(path.join(root, "knowledge", "features", "launch.json"))).toBe(false);
});
