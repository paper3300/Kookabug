// 녹화 UI E2E (M4 계획 T9·T10): 가짜 플랫폼 + 가짜 각본(예제 로그인, 쉬었다 이어 친 비밀번호)으로 실제 daemon 녹화 세션.
// 핵심 경로: 녹화 → 비밀값 키 → 화면 확인 넣기 → 새 테스트로 저장 → F5 → pass. 커서 위치 삽입(테스트 사슬 중간·서브그래프·
// 되돌리기), 같은 이름 → 다른 이름(재녹화 없음), REC 탭 영역 고치기·비밀번호 칸 겹침 거부, 전역 단축키(등록 실패면
// 시작 안 함·주 프로세스 정지), 두 번째 창(다른 곳 녹화 중)·녹화 중 앱 종료 정리
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication } from "@playwright/test";
import { filePath, openGraph, pyDiagnostics, pyEqual, readBytes, readJson, selectOnly, writeFile } from "./helpers/editor";
import { closeRunApp, openRunApp, runEnv, toolbar, waitEnded, type RunSession } from "./helpers/run";
import {
  ACCOUNT_TEXT,
  beginCheckMode,
  CHAIN_SUB,
  CHAIN_TEST,
  chooseSecret,
  insertButton,
  insertLobbyCheck,
  LOBBY_TITLE,
  openRecorderApp,
  PASSWORD_FIELD,
  prepareRecorderWorkspace,
  saveButton,
  saveNewTest,
  SECRET_KEY,
  SECRET_TEXT,
  showRecorder,
  sidebar,
  startLaunch,
  statusbar,
  steps,
  stopRecording,
  waitLoginRecorded,
  writeChainSubgraph,
  writeChainTest,
} from "./helpers/recorder";
import { selectRect, TITLE_TEXT } from "./helpers/target";

test.setTimeout(240_000);

let s: RunSession | null = null;
let other: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(other, true);
  other = null;
  if (s !== null && process.env.KB_KEEP_WS === "1") console.log(`워크스페이스 남김: ${s.ws.root}`);
  await closeRunApp(s, process.env.KB_KEEP_WS === "1");
  s = null;
});

type Graph = { nodes: Record<string, { type: string; in?: Record<string, unknown>; next?: Record<string, string> }> };

function e2e(app: ElectronApplication) {
  return {
    accelerators: () => app.evaluate(() => (globalThis as unknown as { __kookabugE2E: { recorderAccelerators(): string[] } }).__kookabugE2E.recorderAccelerators()),
    press: (role: "stop" | "mark_secret") =>
      app.evaluate((_e, r) => (globalThis as unknown as { __kookabugE2E: { pressRecorderHotkey(r: string): boolean } }).__kookabugE2E.pressRecorderHotkey(r), role),
    block: (accelerator: string | null) =>
      app.evaluate((_e, a) => (globalThis as unknown as { __kookabugE2E: { blockRecorderHotkey(a: string | null): void } }).__kookabugE2E.blockRecorderHotkey(a), accelerator),
  };
}

/** 그래프 사슬 차례 (entry에서 next를 따라감 — ok 출구 하나씩) */
function chainOf(graph: Graph, from = "n_entry"): string[] {
  const out: string[] = [];
  let cur: string | undefined = from;
  const seen = new Set<string>();
  while (cur !== undefined && !seen.has(cur)) {
    seen.add(cur);
    out.push(cur);
    const next: Record<string, string> = graph.nodes[cur]?.next ?? {};
    cur = Object.values(next)[0];
  }
  return out;
}

async function recordLoginAndStop(page: RunSession["page"], check = false): Promise<void> {
  await startLaunch(page);
  await waitLoginRecorded(page);
  if (check) await insertLobbyCheck(page);
  await stopRecording(page);
}

test("test_record_login_script_save_new_test_then_f5_pass", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  // 녹화 전 (시안 없음, U1): 창 고르기·게임 띄워서 녹화
  await expect(page.locator('[data-part="rec-start"]')).toBeVisible();
  // 녹화 중에 열어 둔 그래프 탭: 실행 단추가 꺼지고 툴팁 (2.11)
  await page.getByRole("button", { name: "탐색기" }).click();
  await openGraph(page, "tests/inventory_open.graph.json");
  await showRecorder(page);
  await startLaunch(page);
  await expect(statusbar(page)).toHaveAttribute("data-recording", "true");
  await expect(statusbar(page).locator('[data-part="rec-status"]')).toContainText(/녹화 중|녹화 준비/);
  await expect(statusbar(page).locator('[data-part="lease"]')).toHaveText("입력: 녹화", { timeout: 10_000 });
  await page.locator('[role="tab"][data-path="tests/inventory_open.graph.json"]').getByRole("button").first().click();
  const play = toolbar(page).getByRole("button", { name: "실행 F5" });
  await expect(play).toBeDisabled();
  await expect(play).toHaveAttribute("title", "녹화 중에는 실행할 수 없어요");
  await waitLoginRecorded(page);
  // 비밀번호는 ● × 길이, 계정은 원문 (판정 뒤 일반 글자)
  await expect(page.locator('[data-part="rec-step"][data-text-state="secret"] [data-part="rec-raw"]')).toContainText("●".repeat(SECRET_TEXT.length));
  await expect(page.locator('[data-part="rec-step"][data-text-state="ordinary"] [data-part="rec-raw"]')).toContainText(ACCOUNT_TEXT);
  await expect(sidebar(page)).not.toContainText(SECRET_TEXT);
  await insertLobbyCheck(page);
  await stopRecording(page);
  await expect(statusbar(page)).toHaveAttribute("data-recording", "false");
  await expect(statusbar(page).locator('[data-part="rec-status"]')).toContainText("녹화 끝");
  // 정지 뒤(다듬는 중)에는 실행할 수 있다
  await page.locator('[role="tab"][data-path="tests/inventory_open.graph.json"]').getByRole("button").first().click();
  await expect(play).toBeEnabled();
  // 비밀값 띠: 키를 고르기 전에는 저장 단추가 꺼지고 이유 툴팁
  await expect(page.locator('[data-part="secret-row"]')).toContainText("비밀번호 칸에 입력했어요");
  await expect(saveButton(page)).toBeDisabled();
  await expect(saveButton(page)).toHaveAttribute("title", "비밀값을 고르면 저장할 수 있어요");
  await chooseSecret(page);
  await expect(saveButton(page)).toBeEnabled();
  const rel = await saveNewTest(page, "rec_login");
  // 그래프: 게임 띄우기부터, 비밀값은 $secret 한 번, 원문 없음, 화면 확인으로 끝 (test.pass 없음)
  const text = fs.readFileSync(filePath(ws.root, rel), "utf8");
  expect(text).not.toContain(SECRET_TEXT);
  expect(text).toContain(ACCOUNT_TEXT);
  const graph = readJson<Graph>(ws.root, rel);
  const chain = chainOf(graph).map((id) => graph.nodes[id].type);
  expect(chain[0]).toBe("core.graph.entry");
  expect(chain[1]).toBe("core.app.launch");
  expect(chain.at(-1)).toBe("core.assert.visible");
  const secretNodes = Object.values(graph.nodes).filter((n) => JSON.stringify(n.in ?? {}).includes('"$secret"'));
  expect(secretNodes).toHaveLength(1);
  expect(secretNodes[0].in?.text).toEqual({ $secret: SECRET_KEY });
  // 녹화가 끝나 REC 탭이 닫히고 그 그래프가 앞에 — F5로 바로 재생
  await expect(page.locator('[role="tab"][data-path="rec:capture"]')).toHaveCount(0);
  await expect(sidebar(page)).toHaveAttribute("data-state", /committed|idle/);
  await page.locator(`[data-part="canvas"][data-path="${rel}"]`).click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("F5");
  await waitEnded(page, "pass", 120_000);
});

test("test_insert_without_assertion_mid_chain_in_test_runs_to_original_successor", async () => {
  const ws = prepareRecorderWorkspace();
  writeChainTest(ws);
  const original = readBytes(ws.root, CHAIN_TEST);
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page);
  await chooseSecret(page);
  // 그래프 탭이 없으면 삽입 단추가 꺼져 있다
  await expect(insertButton(page)).toBeDisabled();
  await page.getByRole("button", { name: "탐색기" }).click();
  await openGraph(page, CHAIN_TEST);
  await selectOnly(page, "n_launch");
  await showRecorder(page);
  await expect(insertButton(page)).toBeEnabled();
  const canvas = page.locator(`[data-part="canvas"][data-path="${CHAIN_TEST}"]`);
  const saves = Number((await canvas.getAttribute("data-saves")) ?? "0");
  await insertButton(page).click();
  await expect(canvas).toHaveAttribute("data-saves", String(saves + 1), { timeout: 60_000 });
  const graph = readJson<Graph>(ws.root, CHAIN_TEST);
  const chain = chainOf(graph);
  // 게임 띄우기 → 녹화한 노드들 → 원래 다음 노드(로비 기다리기) → 통과. 삽입은 종료 노드·창 노드를 붙이지 않는다
  expect(chain.slice(0, 2)).toEqual(["n_entry", "n_launch"]);
  expect(chain.slice(-2)).toEqual(["n_lobby", "n_pass"]);
  const inserted = chain.slice(2, -2).map((id) => graph.nodes[id].type);
  expect(inserted.length).toBeGreaterThanOrEqual(6);
  expect(inserted).not.toContain("core.test.pass");
  expect(inserted).not.toContain("core.app.launch");
  expect(fs.readFileSync(filePath(ws.root, CHAIN_TEST), "utf8")).not.toContain(SECRET_TEXT);
  // F5 → 녹화한 로그인 뒤 원래 다음 노드까지 가서 pass
  await canvas.click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("F5");
  await waitEnded(page, "pass", 120_000);
  // test_insert_undo_restores_graph: 한 번의 되돌리기로 넣기 전 값 (저장하면 원래 파일과 같다)
  await canvas.click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("Control+Z");
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await page.keyboard.press("Control+S");
  await expect(canvas).toHaveAttribute("data-saves", String(saves + 2), { timeout: 30_000 });
  expect(pyEqual(filePath(ws.root, CHAIN_TEST), JSON.parse(original.toString("utf8")))).toBe(true);
});

test("test_insert_mid_chain_in_subgraph_validates", async () => {
  const ws = prepareRecorderWorkspace();
  writeChainSubgraph(ws);
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page);
  await chooseSecret(page);
  await page.getByRole("button", { name: "탐색기" }).click();
  await openGraph(page, CHAIN_SUB);
  await selectOnly(page, "n_entry");
  await showRecorder(page);
  const canvas = page.locator(`[data-part="canvas"][data-path="${CHAIN_SUB}"]`);
  const saves = Number((await canvas.getAttribute("data-saves")) ?? "0");
  await insertButton(page).click();
  await expect(canvas).toHaveAttribute("data-saves", String(saves + 1), { timeout: 60_000 });
  const graph = readJson<Graph>(ws.root, CHAIN_SUB);
  const chain = chainOf(graph);
  expect(chain[0]).toBe("n_entry");
  expect(chain.at(-1)).toBe("n_exit");
  expect(chain.length).toBeGreaterThan(6);
  // 실행 전 검증: 오류 없음 (종료 노드를 붙이지 않아 terminal_in_subgraph 없음). 비밀값은 실행처럼 환경 변수로 준다
  process.env.KOOKABUG_SECRET_ACCOUNTS_QA_TESTER_01 = SECRET_TEXT;
  const errors = pyDiagnostics(ws.root, CHAIN_SUB).filter((d) => d[0] === "error");
  expect(errors).toEqual([]);
});

test("test_new_test_name_exists_then_save_other_name", async () => {
  const ws = prepareRecorderWorkspace();
  writeChainTest(ws);
  writeFile(ws.root, "tests/taken.graph.json", readBytes(ws.root, CHAIN_TEST));
  const taken = readBytes(ws.root, "tests/taken.graph.json");
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page, true);
  await chooseSecret(page);
  await saveButton(page).click();
  const dialog = page.getByRole("dialog", { name: "새 테스트로 저장" });
  await dialog.getByRole("textbox", { name: "이름" }).fill("taken");
  await dialog.getByRole("button", { name: "저장" }).click();
  // 같은 이름: commit_abort 뒤 같은 대화 상자에 이유 (재녹화 없음, 기존 파일 그대로)
  await expect(dialog.getByRole("alert")).toContainText("이미 있어요", { timeout: 60_000 });
  expect(readBytes(ws.root, "tests/taken.graph.json").equals(taken)).toBe(true);
  await expect(sidebar(page)).toHaveAttribute("data-state", "stopped");
  await dialog.getByRole("textbox", { name: "이름" }).fill("rec_other");
  await dialog.getByRole("button", { name: "저장" }).click();
  await expect(page.locator('[role="tab"][data-path="tests/rec_other.graph.json"]')).toHaveAttribute("aria-selected", "true", { timeout: 60_000 });
  // 써진 target 재사용: 그래프가 가리키는 target이 다 있고, 녹화 폴더에 같은 초안이 두 번 쓰이지 않았다
  const graph = readJson<Graph>(ws.root, "tests/rec_other.graph.json");
  const refs = [...new Set(Object.values(graph.nodes).flatMap((n) => [...JSON.stringify(n.in ?? {}).matchAll(/"\$target":"(targets\/rec\/[^"]+)"/g)].map((m) => m[1])))];
  expect(refs.length).toBeGreaterThan(0);
  for (const r of refs) expect(fs.existsSync(filePath(ws.root, r))).toBe(true);
  const written = fs
    .readdirSync(filePath(ws.root, "targets/rec"), { recursive: true })
    .map(String)
    .filter((f) => f.endsWith(".target.json"));
  expect(written.length).toBe(refs.length);
});

test("test_rec_tab_edit_crop_and_manual_crop_over_secret_field_rejected", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page, true);
  const clicks = page.locator('[data-part="rec-step"][data-kind="click"]');
  // 로그인 단추 클릭(마지막 클릭)의 정지 화면: 비밀번호 칸이 보호 영역(빗금)이고 그 영역을 고르면 거부
  await clicks.last().click();
  const tab = page.locator('[data-part="rec-tab"]');
  await expect(tab).not.toHaveAttribute("data-frame", "", { timeout: 30_000 });
  await expect(page.locator('[data-part="protected-rect"]').first()).toBeVisible({ timeout: 30_000 });
  await selectRect(page, PASSWORD_FIELD);
  await expect(page.locator('[data-part="rec-refusal"]')).toContainText("비밀번호 칸과 겹치는 영역은 쓸 수 없어요", { timeout: 30_000 });
  // 시작 단추 클릭(첫 클릭)의 영역을 제목 글자로 바꾸면 저장된 target이 그 영역
  await clicks.first().click();
  await expect(tab).toHaveAttribute("data-step", /.+/);
  await expect(page.locator('[data-part="target-frame"]')).not.toHaveAttribute("data-view", "", { timeout: 30_000 });
  const firstStep = (await clicks.first().getAttribute("data-step")) ?? "";
  await expect(tab).toHaveAttribute("data-step", firstStep);
  // 판이 축소돼 끈 영역은 몇 픽셀 다를 수 있다: 판이 고른 영역 그대로를 기대값으로 쓴다
  const picked = await selectRect(page, TITLE_TEXT);
  // 보내기가 끝나 daemon이 그 영역을 받아들일 때까지 (step.update 응답)
  await expect(tab).toHaveAttribute("data-accepted", picked.join(","), { timeout: 15_000 });
  await expect(page.locator('[data-part="rec-refusal"]')).toHaveCount(0);
  await chooseSecret(page);
  const rel = await saveNewTest(page, "rec_crop");
  const graph = readJson<Graph>(ws.root, rel);
  const firstClick = chainOf(graph)
    .map((id) => graph.nodes[id])
    .find((n) => n.type === "core.image.click");
  const targetRel = ((firstClick?.in?.target as { $target?: string } | undefined)?.$target ?? "") as string;
  expect(targetRel).toMatch(/^targets\/rec\//);
  const spec = readJson<{ image: string }>(ws.root, targetRel);
  const png = fs.readFileSync(path.join(path.dirname(filePath(ws.root, targetRel)), spec.image));
  expect([png.readUInt32BE(16), png.readUInt32BE(20)]).toEqual([picked[2], picked[3]]);
});

test("test_stop_hotkey_via_main_process_and_registration_failure_blocks_start", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { app, page } = s;
  const hooks = e2e(app);
  // 등록 실패(다른 앱이 쥔 단축키 흉내): recorder.start를 보내지 않는다 — 녹화가 시작되지 않고 단축키도 남지 않는다
  await hooks.block("CommandOrControl+Shift+P");
  await sidebar(page).getByRole("button", { name: "게임 띄워서 녹화" }).click();
  await expect(page.locator('[data-part="rec-notice"]')).toContainText("Ctrl+Shift+P");
  await expect(page.locator('[data-part="rec-start"]')).toBeVisible();
  expect(await hooks.accelerators()).toEqual([]);
  await expect(statusbar(page)).toHaveAttribute("data-recording", "false");
  await expect(statusbar(page).locator('[data-part="lease"]')).toHaveCount(0);
  // 등록되면 녹화 중에만 쥐고, 주 프로세스 정지 단축키로 멈추면 푼다
  await hooks.block(null);
  await startLaunch(page);
  expect((await hooks.accelerators()).sort()).toEqual(["CommandOrControl+Shift+P", "CommandOrControl+Shift+R"]);
  expect(await hooks.press("stop")).toBe(true);
  await expect(sidebar(page)).toHaveAttribute("data-state", "stopped", { timeout: 30_000 });
  await expect.poll(() => hooks.accelerators()).toEqual([]);
  await expect(statusbar(page)).toHaveAttribute("data-recording", "false");
});

test("test_open_as_target_tab_materializes_one_target", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page, true);
  // 화면 확인 스텝은 녹화 초안: "찾기 대상 탭으로 열기" → 그 초안만 지금 파일로 → TARGET 탭
  await page.locator('[data-part="rec-step"][data-kind="check_visible"]').click();
  const tab = page.locator('[data-part="rec-tab"]');
  await expect(tab).not.toHaveAttribute("data-frame", "", { timeout: 30_000 });
  await page.locator('[data-part="rec-toolbar"]').getByRole("button", { name: "찾기 대상 탭으로 열기" }).click();
  const targetTab = page.locator('[role="tab"][data-kind="TARGET"]');
  await expect(targetTab).toHaveCount(1, { timeout: 30_000 });
  const rel = (await targetTab.getAttribute("data-path")) ?? "";
  expect(rel).toMatch(/^targets\/rec\/.+\.target\.json$/);
  expect(fs.existsSync(filePath(ws.root, rel))).toBe(true);
  const firstBytes = fs.readFileSync(filePath(ws.root, rel));
  const files = () =>
    fs
      .readdirSync(filePath(ws.root, "targets/rec"), { recursive: true })
      .map(String)
      .filter((f) => f.endsWith(".target.json"));
  expect(files()).toHaveLength(1);
  // 커밋은 그 파일을 다시 쓰지 않고 그 경로를 쓴다
  await showRecorder(page);
  await chooseSecret(page);
  const graphRel = await saveNewTest(page, "rec_materialized");
  expect(fs.readFileSync(filePath(ws.root, graphRel), "utf8")).toContain(rel);
  // 같은 초안을 커밋 폴더에 다시 쓰지 않았다 (다른 초안 — 대기 대상 등 — 은 커밋이 쓴다)
  const name = path.basename(rel).replace(/^\d+_/, "");
  expect(files().filter((f) => f.endsWith(`_${name}`))).toHaveLength(1);
  expect(fs.readFileSync(filePath(ws.root, rel)).equals(firstBytes)).toBe(true);
});

test("test_check_cancel_after_stop_keeps_last_step", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await recordLoginAndStop(page);
  const rpc = (method: string, params: object = {}) =>
    page.evaluate(
      async ([m, p]) => (window as unknown as { kookabug: { rpc(m: string, p: unknown): Promise<unknown> } }).kookabug.rpc(m, p),
      [method, params] as const,
    );
  const before = (await rpc("recorder.steps")) as { steps: { step: string; target?: unknown }[] };
  const last = before.steps.at(-1)!;
  // 정지 뒤 확인 넣기는 마지막 스텝 화면을 빌리기만 한다: 영역을 골랐다 취소해도 그 스텝은 그대로
  await beginCheckMode(page, "화면 확인 삽입");
  const tab = page.locator('[data-part="rec-tab"]');
  await expect(tab).toHaveAttribute("data-doc-step", "");
  await selectRect(page, LOBBY_TITLE);
  await page.waitForTimeout(1000);
  await page.locator('[data-part="rec-check-band"]').getByRole("button", { name: "취소" }).click();
  const after = (await rpc("recorder.steps")) as { steps: { step: string; target?: unknown }[] };
  expect(after.steps.length).toBe(before.steps.length);
  expect(after.steps.find((x) => x.step === last.step)?.target).toEqual(last.target);
});

test("test_text_step_toggle_and_check_text_expected_value", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await startLaunch(page);
  await waitLoginRecorded(page);
  // 값 확인 넣기 → 그 스텝의 기댓값을 고쳐 적용
  await beginCheckMode(page, "값 확인 삽입");
  await selectRect(page, LOBBY_TITLE);
  await page.locator('[data-part="rec-check-band"]').getByRole("button", { name: "넣기" }).click();
  const check = page.locator('[data-part="rec-step"][data-kind="check_text"]');
  await expect(check).toHaveCount(1, { timeout: 30_000 });
  await stopRecording(page);
  await check.click();
  const expected = page.locator('[data-part="rec-expected"]');
  await expect(expected).toBeVisible({ timeout: 30_000 });
  await expected.getByRole("textbox", { name: "기댓값" }).fill("서버 고르기");
  await expected.getByRole("button", { name: "기댓값 적용" }).click();
  await expect(expected.getByRole("button", { name: "기댓값 적용" })).toBeDisabled({ timeout: 15_000 });
  // 비밀번호 원문은 기댓값으로 받지 않는다 (원문은 띠·화면에 나오지 않는다)
  await expected.getByRole("textbox", { name: "기댓값" }).fill(`x ${SECRET_TEXT}`);
  await expected.getByRole("button", { name: "기댓값 적용" }).click();
  await expect(page.locator('[data-part="rec-notice"]')).toContainText("비밀번호 칸과 겹치는");
  await expected.getByRole("textbox", { name: "기댓값" }).fill("서버 고르기");
  // 일반 글자(계정) 스텝 → 비밀값으로 → 다시 일반 글자로(확인 대화 상자)
  const account = page.locator('[data-part="rec-step"][data-text-state="ordinary"]');
  const id = (await account.getAttribute("data-step")) ?? "";
  await account.click();
  await account.locator('[data-part="rec-mark-secret"]').click();
  const row = page.locator(`[data-part="rec-step"][data-step="${id}"]`);
  await expect(row).toHaveAttribute("data-text-state", "secret", { timeout: 15_000 });
  await expect(row.locator('[data-part="rec-raw"]')).not.toContainText(ACCOUNT_TEXT);
  await row.locator('[data-part="rec-mark-ordinary"]').click();
  const dialog = page.getByRole("dialog", { name: "글자를 보이고 일반 글자로 저장할까요?" });
  await dialog.getByRole("button", { name: "일반 글자로" }).click();
  await expect(row).toHaveAttribute("data-text-state", "ordinary", { timeout: 15_000 });
  await chooseSecret(page);
  const rel = await saveNewTest(page, "rec_expected");
  const graph = readJson<Graph>(ws.root, rel);
  const assertText = Object.values(graph.nodes).filter((n) => n.type === "core.assert.text");
  expect(assertText.map((n) => n.in?.equals)).toEqual(["서버 고르기"]);
  expect(fs.readFileSync(filePath(ws.root, rel), "utf8")).not.toContain(SECRET_TEXT);
});

test("test_second_window_sees_recording_elsewhere_and_quit_cleans_up", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  await startLaunch(s.page);
  await expect(steps(s.page).first()).toBeVisible({ timeout: 60_000 });
  // 두 번째 UI 연결 (다른 사용자 데이터로 띄운 앱이 같은 daemon에 붙음): 스텝·창 제목 없이 "다른 창에서 녹화 중"
  other = await openRunApp(ws, { env: runEnv(ws) });
  await showRecorder(other.page);
  await expect(other.page.locator('[data-part="rec-elsewhere"]')).toBeVisible({ timeout: 30_000 });
  await expect(other.page.locator('[data-part="rec-step"]')).toHaveCount(0);
  await expect(other.page.locator('[data-part="rec-start"]')).toHaveCount(0);
  await expect(statusbar(other.page).locator('[data-part="rec-status"]')).toHaveText("다른 창에서 녹화 중");
  await expect(statusbar(other.page)).toHaveAttribute("data-recording", "false");
  // 녹화 중 앱 종료 → 연결이 끊겨 세션을 버리고 임대권을 놓는다 (U9). 남은 창은 다시 녹화할 수 있다
  await closeRunApp(s, true);
  s = null;
  await expect(other.page.locator('[data-part="rec-start"]')).toBeVisible({ timeout: 30_000 });
  await expect(statusbar(other.page).locator('[data-part="lease"]')).toHaveCount(0, { timeout: 10_000 });
  // 남은 창이 이어 받은 정리: 다음 검사 정리에서 daemon을 끈다
  s = other;
  other = null;
});
