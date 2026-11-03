// 에디터 탐색 (다듬기 P1-B, 사용자 요청 ⑧⑨): 서브그래프 호출 노드 더블클릭·"서브그래프 열기"로 SUB 탭,
// 탐색기의 전용 편집기 없는 파일(화면 지도·설정·문서·이미지)을 읽기 전용 보기 탭으로. 실제 daemon(가짜 플랫폼)
import fs from "node:fs";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { closeEditor, filePath, nodeEl, openEditor, openGraph, selectOnly, settleCanvas, tabOf, writeFile, type EditorSession } from "./helpers/editor";
import { clickRun, closeRunApp, debugToolbar, INVENTORY, openRunApp, prepareRunWorkspace, runNode, waitEnded, type RunSession } from "./helpers/run";

const SUB = "subgraphs/enter_world.graph.json";

let s: EditorSession | null = null;
let r: RunSession | null = null;

test.afterEach(async () => {
  await closeEditor(s);
  await closeRunApp(r);
  s = null;
  r = null;
});

const tree = (page: Page): Locator => page.getByRole("tree", { name: "워크스페이스 파일" });
const activeTab = (page: Page): Locator => page.locator('[data-part="tabs"] [role="tab"][aria-selected="true"]');
const fileView = (page: Page, rel: string): Locator => page.locator(`[data-part="file-view"][data-path="${rel}"]`);
const dialog = (page: Page): Locator => page.getByRole("dialog", { name: "서브그래프를 열 수 없어요" });

/** 탐색기에서 누른다. 폴더가 접혀 있으면 펼친다 */
async function clickTree(page: Page, rel: string): Promise<void> {
  const parts = rel.split("/");
  for (let i = 1; i < parts.length; i++) {
    const dir = tree(page).locator(`[data-path="${parts.slice(0, i).join("/")}"]`);
    await expect(dir).toBeVisible();
    if ((await dir.getAttribute("aria-expanded")) === "false") await dir.click();
  }
  await tree(page).locator(`[data-path="${rel}"]`).click();
}

async function dblclickNode(page: Page, id: string): Promise<void> {
  await nodeEl(page, id).locator('[data-part="node-head"]').dblclick();
}

/** 없는 서브그래프·틀린 경로를 부르는 테스트 (검증 오류가 있어도 캔버스는 열린다) */
const CALLS = {
  format: "kookabug.graph/0",
  kind: "test",
  layout: { nodes: { n_entry: { x: 0, y: 0 }, n_missing: { x: 280, y: 0 }, n_bad: { x: 560, y: 0 } } },
  nodes: {
    n_entry: { next: { start: "n_missing" }, title: "시작", type: "core.graph.entry", version: 1 },
    n_missing: {
      config: { graph: "subgraphs/none.graph.json" },
      title: "없는 서브그래프",
      type: "core.graph.call",
      version: 1,
    },
    n_bad: { config: { graph: "../outside.graph.json" }, title: "틀린 경로", type: "core.graph.call", version: 1 },
  },
  plugins: { core: "0.1.0" },
};

test("test_double_click_call_node_opens_subgraph_tab", async () => {
  s = await openEditor({ "tests/calls.graph.json": JSON.stringify(CALLS, null, 2) });
  const { page } = s;
  await openGraph(page, INVENTORY);
  await dblclickNode(page, "n_enter_world");
  await expect(activeTab(page)).toHaveAttribute("data-path", SUB);
  await expect(activeTab(page)).toHaveAttribute("data-kind", "SUB");
  await expect(page.locator(`[data-part="canvas"][data-path="${SUB}"]`)).toHaveAttribute("data-status", "ready");

  // 이미 열려 있으면 그 탭으로 (탭이 늘지 않는다)
  await tabOf(page, INVENTORY).locator("button").first().click();
  await settleCanvas(page);
  await dblclickNode(page, "n_enter_world");
  await expect(activeTab(page)).toHaveAttribute("data-path", SUB);
  await expect(tabOf(page, SUB)).toHaveCount(1);

  // 속성 편집기 "서브그래프 열기": 호출 노드에만 있다
  await tabOf(page, INVENTORY).locator("button").first().click();
  await settleCanvas(page);
  await selectOnly(page, "n_press_i");
  await expect(page.locator('[data-part="open-subgraph"]')).toHaveCount(0);
  await selectOnly(page, "n_enter_world");
  await tabOf(page, SUB).locator('button[aria-label^="탭 닫기"]').click();
  await expect(tabOf(page, SUB)).toHaveCount(0);
  await page.locator('[data-part="open-subgraph"]').click();
  await expect(activeTab(page)).toHaveAttribute("data-path", SUB);

  // 다른 노드를 더블클릭하면 아무 일도 없다
  await tabOf(page, INVENTORY).locator("button").first().click();
  await settleCanvas(page);
  await dblclickNode(page, "n_press_i");
  await expect(activeTab(page)).toHaveAttribute("data-path", INVENTORY);

  // 없는 파일·틀린 경로는 알린다 (탭을 열지 않는다)
  await openGraph(page, "tests/calls.graph.json");
  await dblclickNode(page, "n_missing");
  await expect(dialog(page)).toContainText("서브그래프 파일이 없어요");
  await expect(dialog(page)).toContainText("subgraphs/none.graph.json");
  await dialog(page).getByRole("button", { name: "확인" }).click();
  await expect(dialog(page)).toHaveCount(0);
  await expect(activeTab(page)).toHaveAttribute("data-path", "tests/calls.graph.json");
  await expect(tabOf(page, "subgraphs/none.graph.json")).toHaveCount(0);
  await selectOnly(page, "n_bad");
  await page.locator('[data-part="open-subgraph"]').click();
  await expect(dialog(page)).toContainText("경로가 틀렸어요");
  await dialog(page).getByRole("button", { name: "확인" }).click();
  await expect(activeTab(page)).toHaveAttribute("data-path", "tests/calls.graph.json");
});

test("test_double_click_on_node_controls_does_not_open_subgraph", async () => {
  // P1-B 검수: 호출 노드 안의 브레이크포인트 점·포트 더블클릭은 그 요소의 조작이다 (탭을 바꾸지 않는다)
  s = await openEditor();
  const { page } = s;
  await openGraph(page, INVENTORY);
  const node = nodeEl(page, "n_enter_world");
  const spot = node.locator('[data-part="bp-spot"]');
  await expect(spot).toBeVisible();
  await expect(spot).toHaveAttribute("data-on", "false");
  await spot.dblclick();
  await expect(activeTab(page)).toHaveAttribute("data-path", INVENTORY);
  await expect(tabOf(page, SUB)).toHaveCount(0);
  // 두 번 눌렀으니 토글 두 번 → 처음 상태
  await expect(spot).toHaveAttribute("data-on", "false");

  const port = node.locator("[data-pin]").first();
  await expect(port).toBeVisible();
  await port.dblclick();
  await expect(activeTab(page)).toHaveAttribute("data-path", INVENTORY);
  await expect(tabOf(page, SUB)).toHaveCount(0);

  // 노드 본문 더블클릭은 그대로 연다
  await dblclickNode(page, "n_enter_world");
  await expect(activeTab(page)).toHaveAttribute("data-path", SUB);
});

test("test_double_click_while_paused_keeps_pause_highlight", async () => {
  const ws = prepareRunWorkspace();
  r = await openRunApp(ws);
  const { page } = r;
  await openGraph(page, INVENTORY);
  await runNode(page, "n_enter_world").locator('[data-part="node-head"]').click({ button: "right" });
  await page.locator('[data-part="node-menu"]').getByRole("menuitem", { name: /브레이크포인트 설정/ }).click();
  await clickRun(page);
  await expect(debugToolbar(page)).toHaveAttribute("data-state", "paused", { timeout: 60_000 });
  await expect(runNode(page, "n_enter_world")).toHaveAttribute("data-paused", "breakpoint");
  // 서브그래프로 들어가 멈춘다 → 루트 탭에서 호출 노드를 더블클릭하면 SUB 탭의 멈춘 노드가 노란 테두리
  await page.keyboard.press("F11");
  await expect(page.locator('[data-part="pause-banner"]')).toHaveAttribute("data-node", "n_launch");
  await dblclickNode(page, "n_enter_world");
  await expect(activeTab(page)).toHaveAttribute("data-path", SUB);
  await expect(runNode(page, "n_launch")).toHaveAttribute("data-paused", "step");
  await expect(page.locator('[data-part="node"][data-paused]')).toHaveCount(1);
  // 멈춤 중 탭 이동은 실행에 영향이 없다
  await page.keyboard.press("F5");
  await waitEnded(page, "pass");
});

test("test_explorer_opens_read_only_file_view_tabs", async () => {
  s = await openEditor({ "tests/notes.txt": "첫 줄\n둘째 줄\n", "AGENTS.md": "# 에이전트 안내\n" });
  const { page, workspace } = s;

  // 화면 지도: SCREEN 탭, 들여쓰기·구문 색
  await clickTree(page, "screens/lobby.screen.json");
  await expect(activeTab(page)).toHaveAttribute("data-kind", "SCREEN");
  await expect(activeTab(page)).toContainText("lobby.screen.json");
  const screen = fileView(page, "screens/lobby.screen.json");
  await expect(screen).toHaveAttribute("data-status", "ready");
  await expect(screen.locator('[data-part="file-json"]')).toBeVisible();
  await expect(screen.locator('[data-seg="key"]').first()).toBeVisible();
  await expect(screen).toContainText("읽기 전용");
  await expect(page.locator('[data-part="breadcrumb"]')).toContainText("lobby.screen.json");
  // 원문이 한 줄이어도 두 칸 들여쓰기로 보인다
  const raw = JSON.parse(fs.readFileSync(filePath(workspace, "screens/lobby.screen.json"), "utf8")) as Record<string, unknown>;
  const firstKey = Object.keys(raw)[0];
  await expect(screen.locator('[data-part="file-json"] > div').nth(1)).toHaveText(new RegExp(`^  "${firstKey}": `));

  // 밖에서 바뀌면 다시 읽는다
  writeFile(workspace, "screens/lobby.screen.json", JSON.stringify({ ...raw, note_from_outside: 42 }));
  await expect(screen).toContainText('"note_from_outside": 42', { timeout: 10_000 });

  // 설정 파일: JSON 탭, 같은 파일을 다시 누르면 그 탭으로 (탭이 늘지 않는다)
  await clickTree(page, "kookabug.json");
  await expect(activeTab(page)).toHaveAttribute("data-kind", "JSON");
  await expect(fileView(page, "kookabug.json").locator('[data-part="file-json"]')).toContainText('"profiles"');
  await clickTree(page, "screens/lobby.screen.json");
  await clickTree(page, "kookabug.json");
  await expect(page.locator('[role="tab"][data-path="kookabug.json"]')).toHaveCount(1);

  // 문서·글자 파일: 원문
  await clickTree(page, "AGENTS.md");
  await expect(activeTab(page)).toHaveAttribute("data-kind", "MD");
  await expect(fileView(page, "AGENTS.md").locator('[data-part="file-text"]')).toHaveText("# 에이전트 안내\n");
  await clickTree(page, "tests/notes.txt");
  await expect(activeTab(page)).toHaveAttribute("data-kind", "TEXT");
  await expect(fileView(page, "tests/notes.txt").locator('[data-part="file-text"]')).toHaveText("첫 줄\n둘째 줄\n");

  // 이미지: IMAGE 탭에 그림. 밖에서 다른 그림으로 바뀌면 다시 그린다
  const png = "targets/login/login_button.png";
  await clickTree(page, png);
  await expect(activeTab(page)).toHaveAttribute("data-kind", "IMAGE");
  const image = fileView(page, png).locator('[data-part="file-image"]');
  await expect.poll(() => image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  const size = fileView(page, png).locator('[data-part="file-image-size"]');
  const before = await size.textContent();
  const other = fs.readFileSync(filePath(workspace, "targets/login/error_popup.png"));
  writeFile(workspace, png, other);
  await expect(size).not.toHaveText(before!, { timeout: 10_000 });

  // 없어진 파일은 알린다
  fs.rmSync(filePath(workspace, "tests/notes.txt"));
  await page.locator('[role="tab"][data-path="tests/notes.txt"] button').first().click();
  await expect(fileView(page, "tests/notes.txt").locator('[data-part="file-error"]')).toContainText("파일이 없어요", { timeout: 10_000 });

  // 그래프·target은 지금처럼 전용 편집기
  await clickTree(page, SUB);
  await expect(activeTab(page)).toHaveAttribute("data-kind", "SUB");
  await clickTree(page, "targets/login/login_button.target.json");
  await expect(activeTab(page)).toHaveAttribute("data-kind", "TARGET");
});
