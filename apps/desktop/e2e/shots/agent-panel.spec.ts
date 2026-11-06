// 에이전트 패널·권한 설정 스크린샷 (M5 계획 B5, 시안 Main 오른쪽·Permissions·Setup5 대비). 가짜 ACP 에이전트
//   panel-empty           연결 화면 (설정한·감지한 에이전트·직접 입력·프리셋)
//   panel-chat            대화 (내 말풍선·도구 호출 줄·답 본문·바닥 줄)
//   panel-approval        그래프 편집 승인 카드 (한 번 허용·항상 허용·캔버스에서 보기·거부)
//   panel-acp-permission  에이전트 자기 도구의 권한 요청 카드 (에이전트 선택지 그대로)
//   permissions           권한 설정 화면 (다크·라이트)
//   runviewer-analyze     RUN 탭 "에이전트에게 분석 요청" → 패널 @run 칩
// 권한 설정은 시안 Permissions를 렌더러(render.mjs)가 아직 못 그려(sc-for 빈 목록) 비교 PNG 없이 사람이 시안 원본과 본다
// 결과 build/ui-shots/<이름>-<테마>.png → node tools/design-ref/compare.mjs panel-empty panel-chat panel-approval panel-acp-permission runviewer-analyze
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { agentPanel, closeAgentApp, connectAgent, openAgentApp, sendMessage, showAgentTab, type AgentSession } from "../helpers/agent";
import { REPO_BUILD, setTheme, settle } from "../helpers/app";
import { openGraph } from "../helpers/editor";
import { INVENTORY } from "../helpers/run";
import { runItem, showRunList, startRun, waitRunEnded } from "../helpers/runs";

const OUT = path.join(REPO_BUILD, "ui-shots");

let s: AgentSession | null = null;

test.beforeEach(() => {
  fs.mkdirSync(OUT, { recursive: true });
});

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
});

/** `<이름>-<테마>.png` (compare.mjs 규칙). 테마를 주지 않으면 다크 */
async function shot(page: Page, name: string, theme: "dark" | "light" = "dark"): Promise<void> {
  await settle(page);
  await page.mouse.move(2, 600);
  await page.screenshot({ path: path.join(OUT, `${name}-${theme}.png`) });
}

const ANALYSIS = [
  "실패한 노드는 \"인벤토리 열림 대기\"예요. 10초 안에 인벤토리 화면이 나오지 않아 시간 초과로 실패했어요.",
  "",
  "1. 실패 직전 화면에 점검 공지 팝업이 떠 있었어요. 지난 성공 실행에는 없던 화면이에요.",
  "2. 매칭 후보 최고 점수가 0.41이라 대상 이미지 문제는 아니에요.",
  "",
  "버그보다는 예상 못한 팝업으로 보여요. 팝업을 닫는 분기를 넣을까요?",
].join("\n");

test("agent panel shots", async () => {
  s = await openAgentApp({
    scaleFactor: 1,
    settings: {
      format: "kookabug.user-settings/0",
      agents: [{ id: "claude-code", name: "Claude Code", command: "claude-code-acp" }],
    },
    script: {
      prompts: [
        [
          { do: "tool", title: "kb_run_status" },
          { do: "tool", title: "kb_run_compare" },
          { do: "say", text: ANALYSIS },
        ],
        [
          { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["graph_edit", "run", "observe"] } },
          { do: "mcp_call", tool: "kb_graph_get", arguments: { path: INVENTORY } },
          {
            do: "mcp_call",
            tool: "kb_graph_patch",
            arguments: {
              path: INVENTORY,
              base_revision: "$prev:revision",
              ops: [
                { op: "add_node", ref: "popup", type: "core.image.exists", title: "점검 공지?", position: { x: 900, y: 360 } },
                { op: "add_node", ref: "close", type: "core.input.click", title: "닫기 클릭", position: { x: 1160, y: 360 } },
              ],
            },
          },
          { do: "say", text: "분기를 넣지 않았어요. 다른 방법을 찾아볼게요." },
        ],
        [{ do: "permission", title: "README.md에 실패 분석 메모 쓰기" }],
      ],
    },
  });
  const { page } = s;
  await setTheme(page, "dark");
  await openGraph(page, INVENTORY);
  const panel = await showAgentTab(page);
  await expect(panel.locator('[data-part="candidate-row"]').first()).toBeVisible();
  await shot(page, "panel-empty");

  await connectAgent(page);
  await sendMessage(page, "실행 실패한 노드 원인 분석해 줘. 지난 성공 실행이랑 비교해서.");
  await expect(panel.locator('[data-part="chat-agent"]')).toContainText("팝업을 닫는 분기");
  await shot(page, "panel-chat");

  await sendMessage(page, "응, 팝업 닫는 분기를 넣어 줘");
  const card = panel.locator('[data-part="approval-card"][data-state="open"]');
  await expect(card).toBeVisible({ timeout: 60_000 });
  await shot(page, "panel-approval");
  await card.getByRole("button", { name: "거부" }).click();
  await expect(panel.locator('[data-part="chat-agent"]').last()).toContainText("다른 방법", { timeout: 30_000 });

  await sendMessage(page, "분석 내용을 README에 적어 줘");
  await expect(panel.locator('[data-part="acp-permission"][data-state="open"]')).toBeVisible();
  await shot(page, "panel-acp-permission");
  await agentPanel(page).getByRole("button", { name: "닫기" }).last().click();
});

test("permissions shots", async () => {
  s = await openAgentApp({ scaleFactor: 1 });
  const { page, ws } = s;
  const local = path.join(ws.root, ".kookabug", "local.json");
  const value = JSON.parse(fs.readFileSync(local, "utf8")) as Record<string, unknown>;
  value.permissions = {
    preset: "graph_author",
    toolsets: { run: "ask", control: "deny" },
    rules: [
      { rule: "kb_input_*(SampleRPG*)", verdict: "ask" },
      { rule: "kb_run_compare", verdict: "allow" },
    ],
  };
  fs.writeFileSync(local, JSON.stringify(value, null, 2));
  for (const theme of ["dark", "light"] as const) {
    await setTheme(page, theme);
    await page.getByRole("button", { name: "파일", exact: true }).click();
    await page.getByRole("menuitem", { name: "기본 설정: 에이전트 권한" }).click();
    const view = page.locator('[data-part="permissions-view"]');
    await expect(view.locator('[data-part="rule-row"]')).toHaveCount(2);
    await shot(page, "permissions", theme);
  }
});

test("runviewer analyze shot", async () => {
  s = await openAgentApp({ scaleFactor: 1 });
  const { page, ws } = s;
  await setTheme(page, "dark");
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
  const runId = await startRun(page, "tests/agent_quick.graph.json");
  await waitRunEnded(page, runId);
  await showRunList(page);
  await runItem(page, runId).click();
  await page.locator('[data-part="ask-agent"]').click();
  await connectAgent(page);
  await expect(agentPanel(page).locator('[data-part="chip"]')).toHaveCount(1);
  await shot(page, "runviewer-analyze");
});
