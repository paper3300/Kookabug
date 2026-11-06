// 에이전트 패널 세션 수명·승인 경계 (M5 B5 검수 1라운드 반례를 옮김, 이름 유지). 패널 에이전트는 `kookabug agent-host`
// 도우미가 Job 하나로 묶는다: 연결 끊기·에이전트 죽음·자연 종료 모두 자손(kookabug mcp·손자)까지 끝나고, 그 MCP 연결의
// 확인 요청은 daemon이 cancelled로 닫는다. 끝난 세션의 남은 카드로 파일이 바뀌지 않는다
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
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
import { REPO_ROOT } from "./helpers/app";
import { openGraph, readBytes } from "./helpers/editor";
import { INVENTORY } from "./helpers/run";

let s: AgentSession | null = null;
const children: number[] = [];

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
  for (const pid of children.splice(0)) {
    try {
      process.kill(pid);
    } catch {
      // 이미 끝남
    }
  }
});

const patchSteps = [
  { do: "mcp_call", tool: "kb_toolset_enable", arguments: { toolsets: ["graph_edit"] } },
  { do: "mcp_call", tool: "kb_graph_get", arguments: { path: INVENTORY } },
  {
    do: "mcp_call",
    tool: "kb_graph_patch",
    arguments: { path: INVENTORY, base_revision: "$prev:revision", ops: [{ op: "set_meta", title: "승인되지 않은 변경" }] },
  },
];

function pendingApprovals(session: AgentSession): Promise<{ requests: unknown[] }> {
  return session.page.evaluate(() => window.kookabug.rpc("approval.list", {})) as Promise<{ requests: unknown[] }>;
}

test("연결 끊기에서 MCP 승인 요청 취소와 파일 보존", async () => {
  s = await openAgentApp({ script: { steps: patchSteps } });
  await connectAgent(s.page);
  const before = readBytes(s.ws.root, INVENTORY);
  await sendMessage(s.page, "검수");
  await expect(agentPanel(s.page).locator('[data-part="approval-card"][data-state="open"]')).toBeVisible({ timeout: 30_000 });
  await agentPanel(s.page).getByRole("button", { name: "에이전트 연결 끊기", exact: true }).click();
  await expect.poll(() => pendingApprovals(s!)).toEqual({ requests: [] });
  expect(readBytes(s.ws.root, INVENTORY)).toEqual(before);
});

test("프로세스 죽음에서 MCP 승인 요청 취소와 파일 보존", async () => {
  s = await openAgentApp({ script: { steps: patchSteps } });
  await connectAgent(s.page);
  const before = readBytes(s.ws.root, INVENTORY);
  await sendMessage(s.page, "검수");
  const card = agentPanel(s.page).locator('[data-part="approval-card"]');
  await expect(card).toHaveAttribute("data-state", "open", { timeout: 30_000 });
  const pid = agentLog(s).find((e) => e.event === "start")!.pid as number;
  process.kill(pid);
  await expect(agentPanel(s.page)).toHaveAttribute("data-status", "ended");
  await expect.poll(() => pendingApprovals(s!), { timeout: 5000 }).toEqual({ requests: [] });
  // 카드는 daemon approval.resolved(cancelled)로 닫힌다
  await expect(card).toHaveAttribute("data-state", "cancelled");
  expect(readBytes(s.ws.root, INVENTORY)).toEqual(before);
});

test("에이전트 자연 종료 뒤 자식 프로세스 정리", async () => {
  const pidfile = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "kb-child-")), "child.pid");
  s = await openAgentApp({ script: { steps: [{ do: "spawn_child", pidfile }, { do: "exit", code: 3 }] } });
  await connectAgent(s.page);
  await sendMessage(s.page, "검수");
  await expect(agentPanel(s.page)).toHaveAttribute("data-status", "ended");
  const pid = Number(fs.readFileSync(pidfile, "utf8"));
  children.push(pid);
  await expect.poll(() => alive(pid), { timeout: 5000 }).toBe(false);
  // 패널에 오류 줄과 다시 시작
  await expect(agentPanel(s.page).locator('[data-part="chat-error"]')).toHaveCount(1);
  await expect(agentPanel(s.page).locator('[data-part="chat-error"]')).toContainText("끝났어요");
});

test("잘못된 규칙 형식에서 권한 화면 진단 표시", async () => {
  s = await openAgentApp({ settings: { format: "kookabug.user-settings/0", permissions: { rules: "손상된 규칙" } } });
  const settingsFile = path.join(s.userDir, "settings.json");
  const original = fs.readFileSync(settingsFile);
  const errors: string[] = [];
  s.page.on("pageerror", (e) => errors.push(e.message));
  await s.page.getByRole("button", { name: "파일", exact: true }).click();
  await s.page.getByRole("menuitem", { name: "기본 설정: 에이전트 권한", exact: true }).click();
  const view = s.page.locator('[data-part="permissions-view"]');
  await expect(view).toBeVisible();
  await expect(s.page.getByRole("alert").first()).toBeVisible();
  // 그 계층을 열면 진단을 보이고 편집을 막는다 (파일 그대로)
  await view.locator('[role="tab"][data-scope="user"]').click();
  await expect(view.locator('[data-part="layer-malformed"]')).toBeVisible();
  await expect(view.getByRole("combobox", { name: "프리셋" })).toBeDisabled();
  await expect(view.getByRole("textbox", { name: "새 규칙" })).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(fs.readFileSync(settingsFile)).toEqual(original);
});

test("외부 control 승인 카드 라우팅과 항상 허용 없음", async () => {
  s = await openAgentApp({
    settings: {
      format: "kookabug.user-settings/0",
      agents: [{ id: "claude-code", name: "가짜", command: "fake" }],
      permissions: { preset: "runner" },
    },
  });
  await connectAgent(s.page);
  const out = path.join(path.dirname(s.userDir), "external.json");
  const worker = spawn(
    path.join(REPO_ROOT, ".venv", "Scripts", "python.exe"),
    ["-X", "utf8", path.join(import.meta.dirname, "helpers", "external_agent.py"), s.ws.root, out],
    { windowsHide: true, stdio: "ignore" },
  );
  if (worker.pid !== undefined) children.push(worker.pid);
  const card = s.page.locator('[data-part="external-approvals"] [data-part="approval-card"]');
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("data-external", "true");
  await expect(card).toContainText("외부 검수 에이전트");
  await expect(card.getByRole("button", { name: "항상 허용", exact: true })).toHaveCount(0);
  await expect(agentPanel(s.page).locator('[data-part="agent-chat"] [data-part="approval-card"]')).toHaveCount(0);
  await card.getByRole("button", { name: "거부", exact: true }).click();
  await expect
    .poll(() => (fs.existsSync(out) ? (JSON.parse(fs.readFileSync(out, "utf8")) as unknown) : null))
    .toEqual({ error: "approval_denied" });
});

test("종료된 세션의 남은 승인 카드로 파일이 바뀌면 안 됨", async () => {
  s = await openAgentApp({ script: { steps: patchSteps } });
  await connectAgent(s.page);
  const before = readBytes(s.ws.root, INVENTORY);
  await sendMessage(s.page, "검수");
  const card = agentPanel(s.page).locator('[data-part="approval-card"]').first();
  await expect(card).toHaveAttribute("data-state", "open", { timeout: 30_000 });
  const id = await card.getAttribute("data-id");
  const pid = agentLog(s).find((e) => e.event === "start")!.pid as number;
  process.kill(pid);
  await expect(agentPanel(s.page)).toHaveAttribute("data-status", "ended");
  // 끝난 세션의 카드 단추는 막히고(또는 daemon이 이미 닫아 단추가 없고), daemon에 남은 요청이 없다
  const allow = card.getByRole("button", { name: "한 번 허용", exact: true });
  if ((await allow.count()) > 0) await expect(allow).toBeDisabled();
  await expect.poll(() => pendingApprovals(s!), { timeout: 5000 }).toEqual({ requests: [] });
  await expect(card).toHaveAttribute("data-state", "cancelled");
  // 렌더러 단추를 거치지 않고 남은 요청 ID로 직접 답해도 daemon에 요청이 없다
  const direct = await s.page.evaluate(
    (rid) =>
      window.kookabug.rpc("approval.respond", { id: rid, verdict: "allow_once" }).then(
        () => "ok",
        (e: { data?: { code?: string } }) => e.data?.code ?? "error",
      ),
    id!,
  );
  expect(direct).toBe("not_found");
  await s.page.waitForTimeout(500);
  expect(readBytes(s.ws.root, INVENTORY)).toEqual(before);
});

test("설정 env의 $secret은 도우미가 실행 직전에 풀고, 못 풀면 연결 오류", async () => {
  // 비밀값 제공자: 앱 환경의 KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 (helpers/run.ts runEnv)
  s = await openAgentApp({
    settings: {
      format: "kookabug.user-settings/0",
      agents: [
        { id: "claude-code", name: "Claude Code", command: "claude-code-acp", env: { KBT_TOKEN: { $secret: "accounts.qa_tester_01" } } },
        { id: "broken", name: "키 없음", command: "claude-code-acp", env: { KBT_TOKEN: { $secret: "accounts.nope" } } },
      ],
    },
    script: { log_env: ["KBT_TOKEN"], steps: [{ do: "say_env", var: "KBT_TOKEN" }] },
  });
  const panel = await showAgentTab(s.page);
  await panel.locator('[data-part="agent-row"][data-id="broken"]').getByRole("button", { name: "연결" }).click();
  const error = panel.locator('[data-part="agent-start-error"]');
  await expect(error).toContainText("accounts.nope", { timeout: 30_000 });
  await expect(error).toContainText("KBT_TOKEN");
  // 풀리는 키: 에이전트 환경에 값이 들어간다 (가짜 쪽 기록으로 확인). 에이전트가 되돌려도 앱에는 가린 글만
  await connectAgent(s.page);
  const start = agentLog(s).filter((e) => e.event === "start").at(-1) as { logged_env: Record<string, string> };
  expect(start.logged_env).toEqual({ KBT_TOKEN: SECRET });
  await sendMessage(s.page, "환경");
  await expect(panel.locator('[data-part="chat-agent"]')).toContainText("***");
  expect(await s.page.locator("body").innerText()).not.toContain(SECRET);
});

/** helpers/run.ts runEnv의 시험 비밀값 (실제 자격 증명 아님) */
const SECRET = "sample-pass-01";

for (const mode of ["say_env", "error_env"] as const) {
  test(`비밀값이 ${mode} 응답을 통해 렌더러에 전달되지 않음`, async () => {
    s = await openAgentApp({
      settings: {
        format: "kookabug.user-settings/0",
        agents: [{ id: "claude-code", name: "검사 에이전트", command: "fake", env: { REVIEW_TOKEN: { $secret: "accounts.qa_tester_01" } } }],
      },
      script: { log_env: ["REVIEW_TOKEN"], steps: [{ do: mode, var: "REVIEW_TOKEN" }] },
    });
    let mainStderr = "";
    s.app.process().stderr?.on("data", (data: Buffer) => {
      mainStderr += String(data);
    });
    await s.page.evaluate(() => {
      (window as unknown as { __events: unknown[] }).__events = [];
      window.kookabug.on("agent.session", (e) => (window as unknown as { __events: unknown[] }).__events.push(e));
    });
    await connectAgent(s.page);
    // 에이전트는 값을 받았다 (가짜 쪽 기록)
    const start = agentLog(s).filter((e) => e.event === "start").at(-1) as { logged_env: Record<string, string> };
    expect(start.logged_env).toEqual({ REVIEW_TOKEN: SECRET });
    await sendMessage(s.page, "검사");
    await expect(agentPanel(s.page)).toHaveAttribute("data-status", "ready");
    await expect.poll(() => agentLog(s!).some((e) => e.method === "session/prompt")).toBe(true);
    const shown = agentPanel(s.page).locator('[data-part="chat-agent"], [data-part="chat-error"]');
    await expect.poll(() => shown.count()).toBeGreaterThan(0);
    await expect(shown.first()).toContainText("***");
    const events = await s.page.evaluate(() => (window as unknown as { __events: unknown[] }).__events);
    expect(JSON.stringify(events)).not.toContain(SECRET);
    expect(mainStderr).not.toContain(SECRET);
    expect(await s.page.locator("body").innerText()).not.toContain(SECRET);
  });
}

test("패널이 접혀 있어도 ACP 승인 대기가 표시됨", async () => {
  s = await openAgentApp({ script: { steps: [{ do: "sleep", ms: 1000 }, { do: "permission" }] } });
  await openGraph(s.page, INVENTORY);
  await connectAgent(s.page);
  await sendMessage(s.page, "검사");
  await s.page.getByRole("button", { name: "속성 패널 접기", exact: true }).click();
  const folded = s.page.locator('[data-part="inspector"][data-open="false"]');
  await expect(folded).toBeVisible();
  // 접혀도 세션·카드는 그대로, 대기 수가 접힌 버튼과 상태 바에 보인다
  await expect(folded.locator('[data-part="collapsed-pending"]')).toHaveText("1", { timeout: 10_000 });
  await expect(s.page.locator('[data-part="status-pending"]')).toContainText("승인 대기 1");
  await folded.getByRole("button").click();
  await expect(agentPanel(s.page).locator('[data-part="acp-permission"][data-state="open"]')).toBeVisible();
  await s.page.getByRole("button", { name: "속성 패널 접기", exact: true }).click();
  await expect(folded).toContainText(/승인|요청|대기|[1-9]/);
  // Kookabug 확인 요청도 센다: 카드에 답하면 대기 수가 사라진다
  await folded.getByRole("button").click();
  await agentPanel(s.page).locator('[data-part="acp-permission"]').getByRole("button", { name: "거부" }).click();
  await expect(s.page.locator('[data-part="status-pending"]')).toHaveCount(0);
});
