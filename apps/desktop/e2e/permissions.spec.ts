// 권한 설정 화면 (M5 계획 3.10, 시안 Permissions): 프리셋·툴셋·규칙을 바꾸면 그 계층 파일의 permissions만 바뀌고
// 다른 키·순서는 그대로다. 팀(kookabug.json)은 잠겨 있다(읽기만)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { closeAgentApp, openAgentApp, type AgentSession } from "./helpers/agent";

let s: AgentSession | null = null;

test.afterEach(async () => {
  await closeAgentApp(s);
  s = null;
});

function readJson(file: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Record<string, unknown>;
}

async function openSettings(page: Page) {
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "기본 설정: 에이전트 권한" }).click();
  const view = page.locator('[data-part="permissions-view"]');
  await expect(view).toBeVisible();
  return view;
}

test("preset and toolset change writes settings, team locked", async () => {
  s = await openAgentApp();
  const { page, ws, userDir } = s;
  const local = path.join(ws.root, ".kookabug", "local.json");
  const localBefore = readJson(local);
  const team = fs.readFileSync(path.join(ws.root, "kookabug.json"));
  const view = await openSettings(page);
  await expect(page.locator('[role="tab"][data-kind="SETTINGS"]')).toBeVisible();

  // 프로젝트 계층 (기본 범위): 프리셋 → 실행
  await expect(view).toHaveAttribute("data-scope", "project");
  await view.getByRole("combobox", { name: "프리셋" }).selectOption("runner");
  await expect.poll(() => (readJson(local).permissions as { preset?: string } | undefined)?.preset).toBe("runner");
  // 다른 키(settings)와 순서는 그대로
  const afterPreset = readJson(local);
  expect(Object.keys(afterPreset)).toEqual([...Object.keys(localBefore), "permissions"]);
  expect(afterPreset.settings).toEqual(localBefore.settings);
  // 툴셋: 게임 조작 거부, 기본으로 되돌리면 키가 빠진다
  await view.getByRole("combobox", { name: "control 권한" }).selectOption("deny");
  await expect.poll(() => (readJson(local).permissions as { toolsets?: object }).toolsets).toEqual({ control: "deny" });
  await expect(view.locator('[data-part="toolset-row"][data-toolset="control"]')).toHaveAttribute("data-modified", "true");
  await view.getByRole("combobox", { name: "graph_edit 권한" }).selectOption("allow");
  await expect.poll(() => (readJson(local).permissions as { toolsets?: object }).toolsets).toEqual({ control: "deny", graph_edit: "allow" });
  await view.getByRole("combobox", { name: "control 권한" }).selectOption("");
  await expect.poll(() => (readJson(local).permissions as { toolsets?: object }).toolsets).toEqual({ graph_edit: "allow" });
  // 세부 규칙 추가·지우기
  await view.getByRole("textbox", { name: "새 규칙" }).fill("kb_input_*(SampleRPG*)");
  await view.getByRole("combobox", { name: "새 규칙 판정" }).selectOption("ask");
  await view.getByRole("button", { name: "규칙 추가" }).click();
  await expect.poll(() => (readJson(local).permissions as { rules?: unknown[] }).rules).toEqual([
    { rule: "kb_input_*(SampleRPG*)", verdict: "ask" },
  ]);
  await expect(view.locator('[data-part="rule-row"][data-layer="project"]')).toHaveCount(1);
  await view.getByRole("button", { name: "kb_input_*(SampleRPG*) 지우기" }).click();
  await expect.poll(() => "rules" in (readJson(local).permissions as object)).toBe(false);

  // 에이전트 패널 바닥 줄·빈 화면은 실효 프리셋을 따른다
  // 사용자 계층: 사용자 설정 파일의 permissions만 (agents는 그대로)
  await view.locator('[role="tab"][data-scope="user"]').click();
  await expect(view).toHaveAttribute("data-scope", "user");
  await view.getByRole("combobox", { name: "프리셋" }).selectOption("read_only");
  const settingsFile = path.join(userDir, "settings.json");
  await expect.poll(() => (readJson(settingsFile).permissions as { preset?: string } | undefined)?.preset).toBe("read_only");
  expect(readJson(settingsFile).agents).toEqual([{ id: "claude-code", name: "Claude Code", command: "claude-code-acp" }]);

  // 밖에서 먼저 바꾸면 늦은 쪽(화면)은 쓰지 않는다
  const external = { ...readJson(settingsFile), permissions: { preset: "full" } };
  fs.writeFileSync(settingsFile, JSON.stringify(external));
  const externalBytes = fs.readFileSync(settingsFile);
  await view.getByRole("combobox", { name: "프리셋" }).selectOption("runner");
  await expect(view.locator('[data-part="settings-message"]')).toContainText("그 사이 파일이 바뀌어");
  expect(fs.readFileSync(settingsFile)).toEqual(externalBytes);

  // 팀: 잠김 (읽기만)
  await view.locator('[role="tab"][data-scope="team"]').click();
  await expect(view).toHaveAttribute("data-scope", "team");
  await expect(view.getByRole("combobox", { name: "프리셋" })).toBeDisabled();
  await expect(view.getByRole("combobox", { name: "control 권한" })).toBeDisabled();
  await expect(view.getByRole("textbox", { name: "새 규칙" })).toHaveCount(0);
  expect(fs.readFileSync(path.join(ws.root, "kookabug.json"))).toEqual(team);
});
