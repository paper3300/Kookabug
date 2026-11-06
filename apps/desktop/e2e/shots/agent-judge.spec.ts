// 판단 노드 스크린샷 (M5 계획 B4): 캔버스의 Agent 판단 노드 — 선택지 출구·unsure·비결정 배지, 팔레트 Agent 분류
//   agent-judge-dark  1440×900 (시안 Main의 "Agent 판단 · CLI" 노드 대비)
// 결과 build/ui-shots/agent-judge-dark.png → node tools/design-ref/compare.mjs agent-judge
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_BUILD, setContentSize, setTheme, settle, stubOpenDialog } from "../helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "../helpers/daemon";

const OUT = path.join(REPO_BUILD, "ui-shots");
const GRAPH = "tests/judge_popup.graph.json";

const VALUE = {
  format: "kookabug.graph/0",
  kind: "test",
  title: "팝업 판단",
  plugins: { core: "0.1.0" },
  layout: {
    nodes: {
      n_entry: { x: 40, y: 120 },
      n_shot: { x: 240, y: 120 },
      n_judge: { x: 480, y: 120 },
      n_api: { x: 480, y: 400 },
      n_pass: { x: 780, y: 100 },
      n_fail: { x: 780, y: 260 },
    },
  },
  nodes: {
    n_entry: { type: "core.graph.entry", version: 1, next: { start: "n_shot" } },
    n_shot: { type: "core.screen.capture", version: 1, next: { done: "n_judge" } },
    n_judge: {
      type: "core.agent.cli_judge",
      version: 1,
      in: { prompt: "이 팝업은 무엇인가요?", image: { $link: "n_shot.image" } },
      config: { choices: ["maintenance", "event"] },
      next: { maintenance: "n_pass", event: "n_pass", unsure: "n_fail" },
    },
    n_api: {
      type: "core.agent.api_judge",
      version: 1,
      in: { prompt: "보상 팝업인가요?", model: "model-name", api_key: { $secret: "model.key" } },
      config: { choices: ["yes", "no"], provider: "anthropic" },
    },
    n_pass: { type: "core.test.pass", version: 1 },
    n_fail: { type: "core.test.fail", version: 1 },
  },
};

let app: ElectronApplication;
let page: Page;
let userData: string;
let workspace: string | null = null;

test.beforeEach(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  ({ app, userData } = await launchApp({ scaleFactor: 1 }));
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
});

test.afterEach(async () => {
  await closeApp(app);
  if (workspace !== null) await cleanupWorkspace(workspace);
  workspace = null;
  fs.rmSync(userData, { recursive: true, force: true });
});

test("agent-judge-dark", async () => {
  await setTheme(page, "dark");
  await setContentSize(app, page, 1440, 900);
  workspace = copySampleWorkspace("sample-rpg");
  fs.writeFileSync(path.join(workspace, ...GRAPH.split("/")), JSON.stringify(VALUE, null, 2));
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  await page.getByRole("tree", { name: "워크스페이스 파일" }).locator(`[data-path="${GRAPH}"]`).click();
  const judge = page.locator('[data-node-id="n_judge"]');
  await expect(judge).toBeVisible();
  await expect(judge.locator('[data-part="node-status"]')).toHaveText("비결정");
  // 기본 표시명 (시안 Main "Agent 판단 · CLI") — 사용자 제목을 덮어쓰지 않는다
  await expect(judge.locator('[data-part="node-head"]')).toContainText("Agent 판단 · CLI");
  await expect(page.locator('[data-node-id="n_api"] [data-part="node-head"]')).toContainText("Agent 판단 · API");
  await expect(judge).toContainText("maintenance");
  await expect(judge).toContainText("unsure");
  // 팔레트의 Agent 분류를 펼쳐 배지를 보인다
  const agentGroup = page.locator('[data-part="palette"] [data-group="Agent"] [aria-level="1"]');
  if ((await agentGroup.getAttribute("aria-expanded")) !== "true") await agentGroup.click();
  const badges = page.locator('[data-part="palette-badge"]');
  await expect(badges.first()).toHaveText("비결정");
  await badges.last().scrollIntoViewIfNeeded();
  await page.mouse.move(1, 1);
  await page.addStyleTag({ content: "*{caret-color:transparent!important}" });
  await settle(page);
  const file = path.join(OUT, "agent-judge-dark.png");
  await page.screenshot({ path: file });
  expect(fs.statSync(file).size).toBeGreaterThan(0);
});
