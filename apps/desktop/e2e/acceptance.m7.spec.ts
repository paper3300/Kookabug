// M7 인수 E2E (계획 5장): 화면 지도 카드·간선·출처, 승격 대화 상자(저장 안 한 그래프 탭 유지), 탐색 승인과 상태 바.
// 지도 준비는 실제 탐색 결과(explore_world.py: 가짜 예제 게임 + 실제 MCP·daemon·runner + 가짜 탐색 에이전트 각본 →
// 사람 CLI 승격 → 다시 탐색)다. 탐색 승인은 가짜 ACP 에이전트가 패널 세션의 kookabug mcp로 탐색을 열고 클릭한다.
// 실제 입력·실제 에이전트 CLI는 쓰지 않는다
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { agentLog, agentPanel, closeAgentApp, connectAgent, openAgentApp, sendMessage, type AgentSession } from "./helpers/agent";
import { dragNode, filePath, nodeIds, openGraph, readBytes, tabOf } from "./helpers/editor";
import {
  candidate,
  card,
  closeMapApp,
  openMapApp,
  prepareWorld,
  removeWorld,
  showMap,
  type MapSession,
  type World,
} from "./helpers/screenmap";

test.describe.configure({ mode: "serial" });

let world: World | null = null;
let s: MapSession | null = null;
let a: AgentSession | null = null;

test.afterAll(() => {
  removeWorld(world);
  world = null;
});

test.afterEach(async () => {
  await closeMapApp(s);
  s = null;
  await closeAgentApp(a);
  a = null;
});

function w(): World {
  if (world === null) world = prepareWorld();
  return world;
}

const GRAPH = "tests/inventory_open.graph.json";

test("test_map_shows_cards_edges_sources", async () => {
  test.setTimeout(600_000);
  s = await openMapApp(w());
  const { page } = s;
  const [first, second] = w().sessions;
  const map = await showMap(page);
  // 확정 title(탐색에서 옮김) + 1차 탐색 후보 6. 2차 탐색의 같은 화면은 카드가 아니라 합치기 후보
  await expect(map.locator('[data-part="map-card"]')).toHaveCount(7);
  await expect(card(page, "title")).toHaveAttribute("data-state", "confirmed");
  for (const key of ["login", "login_error", "lobby", "loading", "world"]) {
    await expect(card(page, candidate(first, key))).toHaveAttribute("data-state", "explored");
  }
  await expect(page.locator(`[data-part="map-merge"][data-node="${candidate(second, "title_again")}"]`)).toBeVisible();
  // 간선: 탐색 이동이 실선, 출처는 Agent 탐색. 범례는 있는 출처만
  const edges = map.locator('[data-part="map-edge"]');
  expect(await edges.count()).toBeGreaterThanOrEqual(5);
  expect(await map.locator('[data-part="map-edge"][data-source="explored"]').count()).toBeGreaterThanOrEqual(5);
  const sources = await map.locator('[data-part="map-legend"]').evaluateAll((els) => els.map((e) => e.getAttribute("data-source")));
  expect(sources).toEqual(["explored"]);
  // 카드 출처 표시 + 보호로 스크린샷 없는 후보
  await expect(card(page, "title")).toHaveAttribute("data-source", "explored");
  await expect(card(page, candidate(first, "loading"))).toContainText("보호로 스크린샷 없음");
  await expect(page.locator('[data-part="map-counts"]')).toContainText("화면 7");
});

test("test_promote_dialog_moves_card", async () => {
  test.setTimeout(600_000);
  s = await openMapApp(w());
  const { page, workspace } = s;
  const [first] = w().sessions;
  // 저장 안 한 그래프 탭
  await openGraph(page, GRAPH);
  const graphBefore = readBytes(workspace, GRAPH);
  const [someNode] = await nodeIds(page);
  await dragNode(page, someNode!, 40, 20);
  await expect(tabOf(page, GRAPH)).toHaveAttribute("data-dirty", "true");
  // 승격 대화 상자: 확인(screens.check) → 옮기기 → 카드가 확정으로
  await showMap(page);
  await page.locator(`[data-part="map-candidate"][data-node="${candidate(first, "lobby")}"] [data-part="map-promote"]`).click();
  const dialog = page.locator('[data-part="promote-dialog"]');
  await expect(dialog).toHaveAttribute("data-mode", "new");
  await expect(dialog.locator('[data-part="promote-check"]')).toHaveAttribute("data-ok", "true", { timeout: 30_000 });
  await dialog.locator('[data-part="promote-submit"]').click();
  await expect(dialog).toHaveCount(0);
  await expect(card(page, "lobby")).toHaveAttribute("data-state", "confirmed");
  await expect(card(page, candidate(first, "lobby"))).toHaveCount(0);
  expect(fs.existsSync(filePath(workspace, "screens/lobby.screen.json"))).toBe(true);
  expect(fs.existsSync(filePath(workspace, `screens/_explored/${first}/lobby.screen.json`))).toBe(false);
  // 열린 그래프 탭(저장 안 함)과 그 파일은 그대로
  await expect(tabOf(page, GRAPH)).toHaveAttribute("data-dirty", "true");
  expect(readBytes(workspace, GRAPH).equals(graphBefore)).toBe(true);
});

const WINDOW = "SampleRPG";
const START_BUTTON = [512, 412];

test("test_explore_approval_and_status_bar", async () => {
  test.setTimeout(300_000);
  const click = { do: "mcp_call", tool: "kb_input_click", arguments: { window: WINDOW, point: START_BUTTON } };
  a = await openAgentApp({
    // 게임이 떠 있는 가짜 예제 게임 + explorer 권한(탐색 세션 허용, 게임 조작은 묻기)
    prepare: (ws) => {
      const scenarioFile = path.join(path.dirname(ws.platform), "frames", "scenario.json");
      fs.writeFileSync(scenarioFile, JSON.stringify({ ...JSON.parse(fs.readFileSync(scenarioFile, "utf8")), running: true }));
      const local = path.join(ws.root, ".kookabug", "local.json");
      fs.writeFileSync(local, JSON.stringify({ ...JSON.parse(fs.readFileSync(local, "utf8")), permissions: { preset: "explorer" } }));
    },
    script: {
      prompts: [
        [
          { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["observe", "control", "screens"] } },
          { do: "mcp_call", tool: "kb_explore_start", arguments: { title: "예제 게임 둘러보기", window: WINDOW, max_steps: 5 } },
          click,
          click,
          { do: "sleep", ms: 8000 },
          { do: "mcp_call", tool: "kb_explore_end", arguments: {} },
          { do: "say", text: "탐색을 마쳤어요." },
        ],
      ],
    },
  });
  const { page, ws } = a;
  await connectAgent(page);
  await sendMessage(page, "예제 게임을 탐색해 줘");
  const panel = agentPanel(page);
  // 첫 클릭: 확인 카드 (항상 허용 없음, 이 탐색 동안 허용 있음 + 세션 이름 안내)
  const cardEl = panel.locator('[data-part="approval-card"]');
  await expect(cardEl).toHaveCount(1, { timeout: 60_000 });
  await expect(cardEl.locator("button[data-verdict]")).toHaveText(["허용", "이 탐색 동안 허용"]);
  await expect(cardEl.locator('[data-part="session-scope"]')).toContainText("예제 게임 둘러보기");
  // 탐색 중 상태 바: 보라 "Agent 탐색 중", 승인 대기
  const bar = page.locator('[data-part="statusbar"]');
  await expect(bar).toHaveAttribute("data-exploring", "true");
  await expect(bar.locator('[data-part="explore-status"]')).toContainText("Agent 탐색 중");
  await expect(bar.locator('[data-part="status-pending"]')).toContainText("승인 대기 1");
  const purple = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--kb-statusbar-agent-bg").trim());
  expect(purple).not.toBe("");
  expect(await bar.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
  await cardEl.locator('button[data-verdict="allow_session"]').click();
  await expect(cardEl.locator('[data-part="approval-result"]')).toContainText("이 탐색 동안 허용했어요");
  // 같은 창·같은 조작은 다시 묻지 않는다 (카드가 늘지 않음), 상태 바 입력 도구
  await expect(bar.locator('[data-part="input-tool"]')).toContainText("이 탐색 동안 허용됨", { timeout: 30_000 });
  await expect(panel.locator('[data-part="approval-card"]')).toHaveCount(1);
  // 탐색이 끝나면 보라가 풀린다
  await expect(bar).toHaveAttribute("data-exploring", "false", { timeout: 60_000 });
  await expect(panel).toContainText("탐색을 마쳤어요.", { timeout: 30_000 });
  const calls = agentLog(a).filter((e) => e.event === "mcp") as { tool: string; reply: { result?: { isError?: boolean } } }[];
  expect(calls.filter((c) => c.tool === "kb_input_click").map((c) => c.reply.result?.isError ?? false)).toEqual([false, false]);
  // 가짜 게임에 클릭 두 번이 갔다 (실제 입력 없음)
  const inputs = fs
    .readFileSync(path.join(path.dirname(ws.platform), "fake-input.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "");
  expect(inputs.length).toBeGreaterThanOrEqual(2);
});
