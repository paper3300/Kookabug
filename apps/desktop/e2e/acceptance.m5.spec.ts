// M5 완료 기준 인수 검사, 앱 쪽 (M5 계획 5장). 실제 Electron 앱 + 실제 daemon(레포 .venv) + 예제 워크스페이스 사본 +
// 가짜 플랫폼 + 가짜 ACP 에이전트(tools/kb_testing/fake_acp_agent.py — session/new로 받은 `kookabug mcp`를 띄워 MCP로
// 부른다). 다른 검사 모듈은 가져오지 않고 helpers만 쓴다.
//
// 1. 패널 에이전트가 MCP로 그래프를 만들고(사람 확인 카드 "한 번 허용") 실행하고 실패를 분석한다
// 4. UI가 고치는 중(dirty)에 에이전트가 고치면 UI 저장이 늦은 쪽으로 거부된다 (파일은 에이전트 바이트 그대로)
//
// Python 쪽 인수는 python/kookabug_core/tests/acceptance/test_m5.py. 실제 에이전트 CLI·조작감은 Docs/verification/m5-manual.md
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { agentLog, agentPanel, closeAgentApp, connectAgent, openAgentApp, sendMessage, type AgentSession } from "./helpers/agent";
import { canvasOf, filePath, nodeIds, openGraph, readBytes, selectOnly, tabOf } from "./helpers/editor";
import { INVENTORY } from "./helpers/run";
import { runItem, showRunList } from "./helpers/runs";

test.setTimeout(240_000);

let s: AgentSession | null = null;

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
});

const BUILT = "tests/agent_built.graph.json";

type McpLine = {
  event: string;
  tool?: string;
  reply?: { result: { isError: boolean; structuredContent: Record<string, unknown> } };
};

function mcpReply(log: Record<string, unknown>[], tool: string): McpLine["reply"] {
  const line = (log as McpLine[]).filter((e) => e.event === "mcp" && e.tool === tool).at(-1);
  return line?.reply;
}

/** 예제 워크스페이스의 권한을 runner 프리셋으로 (그래프 편집 = 확인, 실행 = 허용). 다른 키는 그대로 */
function setPreset(root: string, preset: string): void {
  const local = path.join(root, ".kookabug", "local.json");
  const body = JSON.parse(fs.readFileSync(local, "utf8")) as Record<string, unknown>;
  body.permissions = { preset };
  fs.writeFileSync(local, JSON.stringify(body));
}

const BUILD_RUN_ANALYZE = [
  { do: "say", text: "그래프를 만들어 돌려 볼게요." },
  { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["graph_edit", "run"] } },
  {
    do: "mcp_call",
    tool: "kb_graph_create",
    arguments: {
      path: BUILT,
      kind: "test",
      title: "에이전트가 만든 테스트",
      ops: [
        { op: "add_node", ref: "log", type: "core.log.message", in: { text: "에이전트 실행" } },
        { op: "add_node", ref: "fail", type: "core.test.fail", title: "일부러 실패", in: { reason: "에이전트 확인용 실패" } },
        { op: "connect", from: "n_entry", exit: "start", to: "log" },
        { op: "connect", from: "log", exit: "done", to: "fail" },
      ],
    },
  },
  { do: "mcp_call", tool: "kb_run_start", arguments: { path: BUILT, idempotency_key: "acceptance-m5" } },
  { do: "mcp_call", tool: "kb_run_status", arguments: { run: "$prev:run", wait_ms: 30000 } },
  { do: "mcp_call", tool: "kb_run_events", arguments: { run: "$prev:run_id", kinds: ["step.end"] } },
  { do: "say", text: "실패 원인: '일부러 실패' 노드가 fail로 끝났어요." },
];

test("panel agent builds, runs and explains failure", async () => {
  s = await openAgentApp({ script: { prompts: [BUILD_RUN_ANALYZE] } });
  const { page, ws } = s;
  setPreset(ws.root, "runner");
  await connectAgent(page);
  await sendMessage(page, "로그를 남기고 실패하는 테스트를 만들어 돌린 뒤 실패를 설명해 줘");
  const panel = agentPanel(page);
  // 그래프 만들기는 사람 확인 (runner 프리셋: graph_edit ask)
  const card = panel.locator('[data-part="approval-card"][data-state="open"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText("kb_graph_create");
  expect(fs.existsSync(filePath(ws.root, BUILT))).toBe(false);
  await card.getByRole("button", { name: "한 번 허용" }).click();
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("실패 원인", { timeout: 90_000 });

  // 만든 그래프: 노드 ID는 daemon이 정함, 실행 판정 fail, 실패 위치 = 만든 fail 노드
  const created = mcpReply(agentLog(s), "kb_graph_create");
  expect(created?.result.isError).toBe(false);
  const ids = (created?.result.structuredContent.created ?? {}) as Record<string, string>;
  const graph = JSON.parse(fs.readFileSync(filePath(ws.root, BUILT), "utf8")) as { nodes: Record<string, { type: string }> };
  expect(graph.nodes[ids.fail].type).toBe("core.test.fail");
  const status = mcpReply(agentLog(s), "kb_run_status");
  expect(status?.result.isError).toBe(false);
  const content = status!.result.structuredContent as {
    run_id: string;
    outcome: { verdict: string };
    failure: { failure: { node: string } };
  };
  expect(content.outcome.verdict).toBe("fail");
  expect(content.failure.failure.node).toBe(ids.fail);
  const events = mcpReply(agentLog(s), "kb_run_events");
  expect(events?.result.isError).toBe(false);
  // 도구 호출 줄이 대화에 접혀 남는다
  await expect(panel.locator('[data-part="tool-line"]').first()).toContainText(/도구 \d+개/);
  // 사람도 기록 뷰어에서 같은 실행을 본다 (에이전트가 시작한 실행)
  await showRunList(page);
  await expect(runItem(page, content.run_id)).toBeVisible({ timeout: 15_000 });
});

const PATCH_STEPS = [
  { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["graph_edit"] } },
  { do: "mcp_call", tool: "kb_graph_get", arguments: { path: INVENTORY } },
  {
    do: "mcp_call",
    tool: "kb_graph_patch",
    arguments: {
      path: INVENTORY,
      base_revision: "$prev:revision",
      ops: [{ op: "add_node", ref: "p", type: "core.test.pass", title: "에이전트 먼저", position: { x: 900, y: 400 } }],
    },
  },
  { do: "say", text: "끝났어요." },
];

test("ui dirty + agent patch → conflict", async () => {
  s = await openAgentApp({ script: { prompts: [PATCH_STEPS] } });
  const { page, ws } = s;
  await openGraph(page, INVENTORY);
  const [first] = await nodeIds(page);
  await selectOnly(page, first);
  const title = page.locator('[data-part="inspector"]').getByRole("textbox", { name: "제목", exact: true });
  await title.fill("UI가 고친 제목");
  await title.press("Enter");
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "true");
  await connectAgent(page);
  await sendMessage(page, "노드 하나 더해 줘");
  const card = agentPanel(page).locator('[data-part="approval-card"][data-state="open"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await card.getByRole("button", { name: "한 번 허용" }).click();
  await expect(agentPanel(page).locator('[data-part="chat-agent"]').last()).toContainText("끝났어요", { timeout: 30_000 });
  const agentBytes = readBytes(ws.root, INVENTORY);
  expect(agentBytes.toString("utf8")).toContain("에이전트 먼저");
  // 편집 중인 문서: 디스크 변경 띠, 저장은 늦은 쪽이라 거부 — 파일은 에이전트 바이트 그대로
  await expect(page.locator('[data-part="conflict-banner"]')).toBeVisible({ timeout: 15_000 });
  await canvasOf(page, INVENTORY).click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+s");
  await expect(page.locator('[data-part="conflict-banner"]')).toBeVisible();
  await page.waitForTimeout(500);
  expect(readBytes(ws.root, INVENTORY)).toEqual(agentBytes);
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "true");
});
