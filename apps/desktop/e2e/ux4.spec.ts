// UX4 화면 사용성 E2E. 실제 앱 → 실제 daemon(가짜 플랫폼) → 가짜 ACP 에이전트(tools/kb_testing/fake_acp_agent.py).
// 실제 게임 입력·네트워크·실제 Agent CLI 없음. 샘플 게임 워크스페이스만 쓴다
// - 탭 오른쪽 클릭 메뉴 "다른 탭 닫기"
// - 활동 막대 보고함 단추 → 보고함 탭
// - 화면 지도 카드 선택 → 오른쪽 속성 탭 (사이드바에는 목록만)
// - 이전 대화: 저장 → 새 대화 → 목록에서 다시 열기 (loadSession 있음 = 이어 가기, 없음 = 읽기 전용 + 이어 하기)
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { agentLog, agentPanel, closeAgentApp, connectAgent, openAgentApp, sendMessage, setScript, type AgentSession } from "./helpers/agent";
import { showActivity } from "./helpers/app";
import { openGraph, tabOf } from "./helpers/editor";
import { INVENTORY } from "./helpers/run";

let s: AgentSession | null = null;

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
});

const OTHER = "subgraphs/enter_world.graph.json";

test("탭 메뉴 다른 탭 닫기 · 활동 막대 보고함 · 화면 지도 선택 → 속성 탭", async () => {
  test.setTimeout(180_000);
  s = await openAgentApp();
  const { page } = s;
  // 탭 메뉴: 그래프 둘을 열고 하나에서 "다른 탭 닫기"
  await openGraph(page, INVENTORY);
  await openGraph(page, OTHER);
  await expect(tabOf(page, INVENTORY)).toBeVisible();
  await tabOf(page, INVENTORY).click({ button: "right" });
  const menu = page.locator('[data-part="tab-menu"]');
  await expect(menu).toBeVisible();
  await expect(menu.getByRole("menuitem")).toHaveText(["닫기", "다른 탭 닫기", "모든 탭 닫기"]);
  await menu.getByRole("menuitem", { name: "다른 탭 닫기" }).click();
  await expect(page.locator('[role="tab"][data-path]')).toHaveCount(1);
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("aria-selected", "true");

  // 그래프: 노드 위에서 오른쪽 단추로 끌면 화면 이동, 메뉴는 뜨지 않는다. 짧은 오른쪽 클릭은 노드 메뉴
  const viewport = page.locator(".react-flow__viewport");
  const before = await viewport.getAttribute("style");
  const node = page.locator(".react-flow__node").first();
  const box = (await node.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + 12);
  await page.mouse.down({ button: "right" });
  await page.mouse.move(box.x + box.width / 2 + 60, box.y + 52, { steps: 6 });
  await page.mouse.up({ button: "right" });
  await expect.poll(() => viewport.getAttribute("style")).not.toBe(before);
  await expect(page.locator('[data-part="node-menu"]')).toHaveCount(0);
  await node.click({ button: "right", position: { x: box.width / 2, y: 12 } });
  await expect(page.locator('[data-part="node-menu"]')).toBeVisible();
  await page.keyboard.press("Escape");

  // 활동 막대 보고함 → 보고함 탭 (사이드바 보기를 바꾸지 않는다)
  const reports = page.locator('[data-part="activity-reports"]');
  await expect(reports).toBeVisible();
  await reports.click();
  await expect(tabOf(page, "reports:inbox")).toHaveAttribute("aria-selected", "true");
  await expect(reports).toHaveAttribute("aria-pressed", "true");

  // 화면 지도: 사이드바에는 목록만, 카드를 고르면 속성 탭에
  await page.getByRole("button", { name: "속성 패널 접기" }).click();
  await showActivity(page.locator('[data-part="activity-screens"]'));
  const side = page.locator('[data-part="sidebar"][data-view="screens"]');
  await expect(side).toBeVisible();
  await side.locator('[data-part="map-row"]').first().click();
  const map = page.locator('[data-part="screen-map"]');
  await expect(map.locator('[data-part="map-card"]').first()).toBeVisible();
  await expect(side.locator('[data-part="map-selected"]')).toHaveCount(0);
  const lobby = map.locator('[data-part="map-card"][data-node="lobby"]');
  await lobby.click();
  const inspector = page.locator('[data-part="inspector"]');
  await expect(inspector).toHaveAttribute("data-open", "true");
  await expect(inspector).toHaveAttribute("data-tab", "props");
  await expect(inspector.locator('[data-part="map-selected"]')).toHaveAttribute("data-node", "lobby");
  await expect(inspector.locator('[data-part="map-detect"]')).toBeVisible();
});

test("이전 대화: 저장 → 새 대화 → 다시 열기 (이어 가기·읽기 전용 + 이어 하기)", async () => {
  test.setTimeout(240_000);
  s = await openAgentApp({ script: { load_session: true, prompts: [[{ do: "say", text: "첫 답이에요" }]] } });
  const { page, ws } = s;
  await connectAgent(page);
  const panel = agentPanel(page);
  await sendMessage(page, "로비 테스트를 만들어 줘");
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("첫 답이에요");
  const folder = path.join(ws.root, ".kookabug", "conversations");
  await expect.poll(() => (fs.existsSync(folder) ? fs.readdirSync(folder).filter((f) => f.endsWith(".json")).length : 0)).toBe(1);
  const file = path.join(folder, fs.readdirSync(folder).find((f) => f.endsWith(".json"))!);
  await expect.poll(() => fs.readFileSync(file, "utf8")).toContain("첫 답이에요");
  const id = path.basename(file, ".json");

  // 새 대화 → 목록에서 다시 열기 (loadSession 지원 → session/load로 이어 간다)
  await panel.getByRole("button", { name: "새 대화" }).click();
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(panel.locator('[data-part="chat-user"]')).toHaveCount(0);
  await panel.locator('[data-part="agent-history-button"]').click();
  const row = panel.locator(`[data-part="agent-history-row"][data-id="${id}"]`);
  await expect(row).toContainText("로비 테스트를 만들어 줘");
  await expect(row).toContainText("Claude Code");
  await row.getByRole("button").first().click();
  await expect(panel).toHaveAttribute("data-status", "ready", { timeout: 30_000 });
  await expect(panel.locator('[data-part="chat-user"]')).toHaveText(["로비 테스트를 만들어 줘"]);
  await expect(panel.locator('[data-part="chat-agent"]')).toHaveText(["첫 답이에요"]);
  await expect(panel.locator('[data-part="agent-read-only"]')).toHaveCount(0);
  await expect(panel.getByRole("textbox", { name: "에이전트에게 메시지" })).toBeEnabled();
  expect(agentLog(s).some((e) => e.event === "request" && e.method === "session/load")).toBe(true);

  // loadSession 없는 Agent: 읽기 전용, "이 대화 이어 하기" → 첫 메시지에 지난 대화 요약
  setScript(s, { load_session: false, prompts: [[{ do: "say", text: "이어서 답해요" }]] });
  await panel.locator('[data-part="agent-history-button"]').click();
  await panel.locator(`[data-part="agent-history-row"][data-id="${id}"]`).getByRole("button").first().click();
  await expect(panel.locator('[data-part="agent-read-only"]')).toBeVisible({ timeout: 30_000 });
  await expect(panel.getByRole("textbox", { name: "에이전트에게 메시지" })).toBeDisabled();
  await panel.locator('[data-part="agent-continue"]').click();
  await expect(panel.locator('[data-part="agent-continue-note"]')).toBeVisible();
  await sendMessage(page, "계속해 줘");
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("이어서 답해요");
  const prompts = agentLog(s).filter((e) => e.event === "request" && e.method === "session/prompt");
  const last = JSON.stringify(prompts.at(-1));
  expect(last).toContain("지난 대화 요약");
  expect(last).toContain("로비 테스트를 만들어 줘");

  // 지우기: 확인 한 번
  await panel.locator('[data-part="agent-history-button"]').click();
  await panel.locator(`[data-part="agent-history-row"][data-id="${id}"] [data-part="agent-history-delete"]`).click();
  await page.getByRole("button", { name: "지우기", exact: true }).click();
  await expect(panel.locator(`[data-part="agent-history-row"][data-id="${id}"]`)).toHaveCount(0);
  expect(fs.existsSync(file)).toBe(false);
});
