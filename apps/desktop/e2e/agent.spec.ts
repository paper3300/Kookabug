// 에이전트 패널 (M5 계획 3.10, B5 완료 기준): 가짜 ACP 에이전트가 session/new로 받은 `kookabug mcp`를 띄워 MCP로
// 그래프를 고친다. 그래프 편집은 사람 확인 카드(approval.requested)를 거치고, 에이전트 자기 도구의 권한 요청은 그
// 선택지 그대로 카드로만 묻는다 (자동 허용 없음). 실제 에이전트 CLI는 쓰지 않는다
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import {
  agentLog,
  agentPanel,
  closeAgentApp,
  connectAgent,
  openAgentApp,
  sendMessage,
  showAgentTab,
  type AgentSession,
} from "./helpers/agent";
import { canvasOf, filePath, nodeIds, openGraph, readBytes, selectOnly, tabOf } from "./helpers/editor";
import { INVENTORY } from "./helpers/run";
import { runTab, showRunList, runItem, waitRunEnded, startRun } from "./helpers/runs";

let s: AgentSession | null = null;

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
});

const PATCH_STEPS = (title: string) => [
  { do: "say", text: "그래프를 고칠게요." },
  { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["graph_edit"] } },
  { do: "mcp_call", tool: "kb_graph_get", arguments: { path: INVENTORY } },
  {
    do: "mcp_call",
    tool: "kb_graph_patch",
    arguments: {
      path: INVENTORY,
      base_revision: "$prev:revision",
      ops: [{ op: "add_node", ref: "p", type: "core.test.pass", title, position: { x: 900, y: 400 } }],
    },
  },
  { do: "say", text: "끝났어요." },
];

test("panel chat → fake agent patches graph after approval card", async () => {
  s = await openAgentApp({ script: { prompts: [PATCH_STEPS("에이전트가 더함"), PATCH_STEPS("거부될 노드")] } });
  const { page, ws } = s;
  await openGraph(page, INVENTORY);
  const before = await nodeIds(page);
  await connectAgent(page);
  // 에이전트는 kookabug mcp 하나만 받는다 (panel:<세션>, 사람이 몰고 있는 연결)
  const created = agentLog(s).find((e) => e.event === "request" && e.method === "session/new") as {
    params: { mcpServers: { name: string; args: string[] }[] };
  };
  expect(created.params.mcpServers).toHaveLength(1);
  expect(created.params.mcpServers[0].name).toBe("kookabug");
  expect(created.params.mcpServers[0].args).toEqual(expect.arrayContaining(["mcp", "--agent-id", "--client", "panel"]));
  const start = agentLog(s).find((e) => e.event === "start") as { env: Record<string, string> };
  expect(start.env).toEqual({});

  await sendMessage(page, "인벤토리 테스트 끝에 통과 노드를 더해 줘");
  const panel = agentPanel(page);
  await expect(panel.locator('[data-part="chat-user"]')).toContainText("통과 노드");
  const card = panel.locator('[data-part="approval-card"][data-state="open"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await expect(card).toContainText("그래프 편집 승인 필요");
  await expect(card).toContainText("kb_graph_patch");
  await expect(card.locator('[data-part="always-rule"]')).toContainText(`kb_graph_patch(${INVENTORY})`);
  // 승인 전에는 파일이 그대로
  const original = readBytes(ws.root, INVENTORY);
  expect(fs.readFileSync(filePath(ws.root, INVENTORY))).toEqual(original);
  // 캔버스에서 보기: 읽기 전용 미리보기 탭 (실제 파일은 그대로)
  await card.getByRole("button", { name: "캔버스에서 보기" }).click();
  const preview = page.locator('[role="tab"][data-kind="PREVIEW"]');
  await expect(preview).toBeVisible();
  await expect(page.locator('[data-part="canvas"][data-readonly="true"]').locator(".react-flow__node")).toHaveCount(before.length + 1);
  await preview.getByRole("button", { name: "탭 닫기" }).click();
  await tabOf(page, INVENTORY).locator("button").first().click();

  await card.getByRole("button", { name: "한 번 허용" }).click();
  await expect(panel.locator('[data-part="approval-result"]').first()).toContainText("한 번 허용했어요");
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("끝났어요", { timeout: 30_000 });
  // 깨끗한 문서라 디스크 변경을 다시 읽어 캔버스에 노드가 생긴다
  await expect.poll(async () => (await nodeIds(page)).length, { timeout: 15_000 }).toBe(before.length + 1);
  const afterAllow = readBytes(ws.root, INVENTORY);
  expect(afterAllow.toString("utf8")).toContain("에이전트가 더함");
  // 도구 호출 줄: 작업 N초 · 도구 M개
  await expect(panel.locator('[data-part="tool-line"]').first()).toContainText(/작업 \d+초 · 도구 \d+개/);
  // 바닥 줄: 에이전트 · ACP · 권한 · MCP 툴셋 (core + graph_edit)
  await expect(panel.locator('[data-part="agent-footer"]')).toContainText("Claude Code · ACP");
  await expect(panel.locator('[data-part="footer-toolsets"]')).toHaveText("MCP 툴셋 2");
  await expect(page.locator('[data-part="status-agents"]')).toHaveText("에이전트 1");

  // 거부 → 파일 바이트 그대로
  await sendMessage(page, "하나 더");
  const second = panel.locator('[data-part="approval-card"][data-state="open"]');
  await expect(second).toBeVisible({ timeout: 60_000 });
  await second.getByRole("button", { name: "거부" }).click();
  await expect(panel.locator('[data-part="approval-result"]').last()).toContainText("거부했어요");
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("끝났어요", { timeout: 30_000 });
  expect(readBytes(ws.root, INVENTORY)).toEqual(afterAllow);
  const denied = agentLog(s).filter((e) => e.event === "mcp" && e.tool === "kb_graph_patch").at(-1) as {
    reply: { result: { isError: boolean; structuredContent: { error: { code: string } } } };
  };
  expect(denied.reply.result.isError).toBe(true);
  expect(denied.reply.result.structuredContent.error.code).toBe("approval_denied");
});

test("acp permission request shows agent options and never auto-allows", async () => {
  const options = [
    { optionId: "once", name: "이번만 허용", kind: "allow_once" },
    { optionId: "always", name: "늘 허용", kind: "allow_always" },
    { optionId: "nope", name: "안 돼요", kind: "reject_once" },
  ];
  s = await openAgentApp({
    script: {
      prompts: [
        [{ do: "permission", title: "README.md 고치기", options }, { do: "say", text: "답을 받았어요" }],
        [{ do: "permission", title: "셸 명령 실행", options }, { do: "say", text: "두 번째" }],
      ],
    },
  });
  const { page } = s;
  await connectAgent(page);
  const panel = agentPanel(page);
  await sendMessage(page, "파일을 고쳐 줘");
  const card = panel.locator('[data-part="acp-permission"][data-state="open"]');
  await expect(card).toBeVisible();
  await expect(card).toContainText("README.md 고치기");
  // 에이전트가 준 선택지 그대로 (+ 닫기)
  await expect(card.getByRole("button")).toHaveText(["이번만 허용", "늘 허용", "안 돼요", "닫기"]);
  // 자동 허용 없음: 기다려도 답이 가지 않는다
  await page.waitForTimeout(1500);
  expect(agentLog(s).some((e) => e.event === "response" && e.method === "session/request_permission")).toBe(false);
  await card.getByRole("button", { name: "안 돼요" }).click();
  await expect(panel.locator('[data-part="acp-permission-result"]')).toContainText("골랐어요: 안 돼요");
  await expect.poll(() => agentLog(s!).filter((e) => e.event === "response").length).toBe(1);
  const answered = agentLog(s).find((e) => e.event === "response") as { result: unknown };
  expect(answered.result).toEqual({ outcome: { outcome: "selected", optionId: "nope" } });
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("답을 받았어요");

  // 중지: 열린 카드는 cancelled로 닫힌다 (허용으로 바뀌지 않는다)
  await sendMessage(page, "셸도");
  await expect(panel.locator('[data-part="acp-permission"][data-state="open"]')).toBeVisible();
  await panel.getByRole("button", { name: "중지" }).click();
  await expect(panel.locator('[data-part="acp-permission"]').last()).toHaveAttribute("data-state", "cancelled");
  await expect.poll(() => agentLog(s!).filter((e) => e.event === "response").length).toBe(2);
  const cancelled = agentLog(s).filter((e) => e.event === "response").at(-1) as { result: unknown };
  expect(cancelled.result).toEqual({ outcome: { outcome: "cancelled" } });
  expect(agentLog(s).some((e) => e.event === "cancel")).toBe(true);
});

test("run tab analyze button opens panel with run chip", async () => {
  s = await openAgentApp();
  const { page, ws } = s;
  fs.writeFileSync(
    path.join(ws.root, "tests", "agent_quick.graph.json"),
    JSON.stringify({
      format: "kookabug.graph/0",
      kind: "test",
      meta: { title: "빠른 실패" },
      plugins: { core: "0.1.0" },
      nodes: {
        n_entry: { next: { start: "n_fail" }, type: "core.graph.entry", version: 1 },
        n_fail: { in: { reason: "일부러 실패" }, type: "core.test.fail", version: 1 },
      },
    }),
  );
  const runId = await startRun(page, "tests/agent_quick.graph.json").catch((err: unknown) => {
    throw new Error(`run.start: ${JSON.stringify(err)} ${String(err)}`);
  });
  await waitRunEnded(page, runId);
  await showRunList(page);
  await runItem(page, runId).click();
  await expect(runTab(page, runId)).toBeVisible();
  // 오른쪽 패널은 RUN 탭에도 보인다 (속성 탭 기본)
  await expect(page.locator('[data-part="inspector"]')).toBeVisible();
  await page.locator('[data-part="ask-agent"]').click();
  const panel = agentPanel(page);
  await expect(panel).toBeVisible();
  await expect(page.locator('[data-part="inspector"]')).toHaveAttribute("data-tab", "agent");
  // 연결 전이면 연결 화면 — 칩과 문장은 남아 연결 뒤 보낸다
  await connectAgent(page);
  const chip = panel.locator('[data-part="chip"]');
  await expect(chip).toHaveCount(1);
  await expect(chip).toContainText("@run #");
  await expect(panel.getByRole("textbox", { name: "에이전트에게 메시지" })).toHaveValue(/실패한 원인을 분석해 줘/);
  await panel.getByRole("button", { name: "보내기" }).click();
  await expect(panel.locator('[data-part="chat-user"]')).toContainText("@run #");
  await expect
    .poll(() =>
      agentLog(s!).some(
        (e) => e.event === "request" && e.method === "session/prompt" && JSON.stringify(e.params).includes(`runs/${runId}`),
      ),
    )
    .toBe(true);
});

test("agent edit while UI dirty → UI save conflict", async () => {
  s = await openAgentApp({ script: { prompts: [PATCH_STEPS("에이전트 먼저")] } });
  const { page, ws } = s;
  await openGraph(page, INVENTORY);
  // UI에서 고쳐 dirty로 둔다 (저장하지 않음)
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

test("footer pickers: model and effort come from agent config options; choice is sent and remembered", async () => {
  const config = [
    { id: "model", name: "Model", category: "model", type: "select", currentValue: "sonnet", options: [{ value: "sonnet", name: "Sonnet" }, { value: "opus", name: "Opus" }] },
    { id: "effort", name: "Effort", category: "thought_level", type: "select", currentValue: "medium", options: [{ value: "low", name: "Low" }, { value: "medium", name: "Medium" }, { value: "high", name: "High" }] },
    { id: "mode", name: "Mode", category: "mode", type: "select", currentValue: "default", options: [{ value: "default", name: "Default" }, { value: "acceptEdits", name: "Accept Edits" }] },
  ];
  s = await openAgentApp({ script: { config_options: config } });
  const { page } = s;
  await connectAgent(page);
  const panel = agentPanel(page);
  const model = panel.locator('[data-part="pick-model"] button[aria-haspopup="menu"]');
  const effort = panel.locator('[data-part="pick-effort"] button[aria-haspopup="menu"]');
  await expect(panel.locator('[data-part="pick-agent"]')).toContainText("Claude Code · ACP");
  await expect(model).toContainText("Sonnet");
  await expect(effort).toContainText("Medium");
  await model.click();
  const menu = panel.getByRole("menu", { name: "Model" });
  await expect(menu.getByRole("menuitemradio", { name: "Sonnet" })).toHaveAttribute("aria-checked", "true");
  await menu.getByRole("menuitemradio", { name: "Opus" }).click();
  await expect(model).toContainText("Opus");
  await effort.click();
  await panel.getByRole("menu", { name: "Effort" }).getByRole("menuitemradio", { name: "High" }).click();
  await expect(effort).toContainText("High");
  const mode = panel.locator('[data-part="pick-mode"] button[aria-haspopup="menu"]');
  await expect(mode).toContainText("Default");
  await mode.click();
  await panel.getByRole("menu", { name: "Mode" }).getByRole("menuitemradio", { name: "Accept Edits" }).click();
  await expect(mode).toContainText("Accept Edits");
  const sets = agentLog(s).filter((e) => e.method === "session/set_config_option");
  expect(sets.map((e) => e.params)).toEqual([
    { sessionId: "s1", configId: "model", value: "opus" },
    { sessionId: "s1", configId: "effort", value: "high" },
    { sessionId: "s1", configId: "mode", value: "acceptEdits" },
  ]);
  // 새 대화(새 세션)는 기억한 값을 다시 건다 — 가짜 에이전트는 세션마다 각본 기본값으로 시작
  await panel.getByRole("button", { name: "새 대화" }).click();
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(model).toContainText("Opus");
  await expect(effort).toContainText("High");
});

test("first project open shows agent setup dialog; later remembers and the panel reopens it", async () => {
  s = await openAgentApp({ settings: null, agentSetup: true });
  const { page } = s;
  const setup = page.locator('[data-part="agent-setup"]');
  await expect(setup).toBeVisible({ timeout: 30_000 });
  await expect(setup.locator('[data-part="setup-row"]')).toHaveCount(3);
  // 뒤쪽 단축키는 막힌다 (빠른 열기 Ctrl+P가 열리지 않음)
  await page.keyboard.press("Control+p");
  await expect(page.getByRole("dialog", { name: "파일 빠른 열기" })).toHaveCount(0);
  await setup.getByRole("button", { name: "나중에" }).click();
  await expect(setup).toHaveCount(0);
  await expect
    .poll(() => (JSON.parse(fs.readFileSync(path.join(s!.userData, "settings.json"), "utf8")) as { agentSetupDismissed?: boolean }).agentSetupDismissed)
    .toBe(true);
  const panel = await showAgentTab(page);
  await panel.locator('[data-part="open-agent-setup"]').click();
  await expect(setup).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(setup).toHaveCount(0);
});

test("agent panel tab shows connect screen with detected list and manual entry", async () => {
  s = await openAgentApp({ settings: null });
  const { page } = s;
  const panel = await showAgentTab(page);
  const connect = panel.locator('[data-part="agent-connect"]');
  await expect(connect).toBeVisible();
  await expect(connect.locator('[data-part="candidate-row"]')).not.toHaveCount(0);
  await expect(connect.getByRole("textbox", { name: "에이전트 명령줄" })).toBeVisible();
  // 직접 입력 → 사용자 설정 agents에 더하고 연결 (명령은 E2E가 가짜로 바꾼다)
  await connect.getByRole("textbox", { name: "에이전트 이름" }).fill("내 에이전트");
  await connect.getByRole("textbox", { name: "에이전트 명령줄" }).fill('my-agent --acp "a b"');
  await connect.getByRole("button", { name: "추가하고 연결" }).click();
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  const settings = JSON.parse(fs.readFileSync(path.join(s.userDir, "settings.json"), "utf8")) as {
    agents: { id: string; name: string; command: string; args: string[] }[];
  };
  expect(settings.agents).toEqual([{ id: "custom-1", name: "내 에이전트", command: "my-agent", args: ["--acp", "a b"] }]);
});
