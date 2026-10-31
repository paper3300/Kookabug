// 속성 편집기 (M2 계획 T10 완료 기준 e2e/inspector.spec.ts). 실제 daemon(레포 .venv)과 예제 워크스페이스 사본.
// 저장한 파일은 Python 코어 규칙(graph_check.py: loads_strict·json_equal)으로 본다. 속성 편집으로도 노드 ID·모르는
// 노드·모르는 키가 그대로인지(M2 완료 기준 2) 본다
import { expect, test, type Locator, type Page } from "@playwright/test";
import {
  canvasOf,
  closeEditor,
  filePath,
  nodeEl,
  nodeIds,
  openEditor,
  openGraph,
  pyEqual,
  readBytes,
  readJson,
  save,
  selectOnly,
  tabOf,
  type EditorSession,
} from "./helpers/editor";

let s: EditorSession | null = null;

test.afterEach(async () => {
  await closeEditor(s);
  s = null;
});

type Graph = { nodes: Record<string, Record<string, unknown>>; [k: string]: unknown };

const INVENTORY = "tests/inventory_open.graph.json";

function inspector(page: Page): Locator {
  return page.locator('[data-part="inspector"]');
}

function field(page: Page, pin: string, kind: "in" | "config" = "in"): Locator {
  return inspector(page).locator(`[data-part="field"][data-field="${kind}"][data-pin="${pin}"]`);
}

/** 그 노드를 고르고 속성 편집기가 그 노드를 보일 때까지 */
async function inspect(page: Page, id: string): Promise<void> {
  await selectOnly(page, id);
  await expect(inspector(page).locator('[data-part="inspector-body"]')).toHaveAttribute("data-node", id);
}

/** 탭이 dirty가 되고 검증 응답까지 받은 뒤 */
async function waitDirty(page: Page, rel: string): Promise<void> {
  await expect(tabOf(page, rel)).toHaveAttribute("data-dirty", "true");
}

async function exitPins(page: Page, id: string): Promise<string[]> {
  return nodeEl(page, id)
    .locator('[data-pin^="x:"]')
    .evaluateAll((els) => els.map((e) => e.getAttribute("data-pin") ?? ""));
}

const WAIT_ANY = "tests/wait_any.graph.json";
const waitAnyGraph = {
  format: "kookabug.graph/0",
  kind: "test",
  layout: {
    nodes: {
      n_entry: { x: 0, y: 0 },
      n_wait: { x: 260, y: 0 },
      n_popup: { x: 560, y: -80 },
      n_lobby: { x: 560, y: 80 },
    },
  },
  meta: { title: "여럿 중 대기" },
  nodes: {
    n_entry: { next: { start: "n_wait" }, type: "core.graph.entry", version: 1 },
    n_lobby: { type: "core.test.pass", version: 1 },
    n_popup: { in: { reason: "점검" }, type: "core.test.skip", version: 1 },
    n_wait: {
      config: { exits: ["popup", "lobby"] },
      in: {
        targets: {
          lobby: { $target: "targets/lobby/server_list.target.json" },
          popup: { $target: "targets/title/maintenance_popup.target.json" },
        },
      },
      next: { lobby: "n_lobby", popup: "n_popup" },
      title: "팝업 또는 로비",
      type: "core.image.wait_any",
      version: 1,
    },
  },
  plugins: { core: "0.1.0" },
};

const LINKED = "tests/linked.graph.json";
const linkedGraph = {
  format: "kookabug.graph/0",
  kind: "test",
  layout: { nodes: { n_entry: { x: 0, y: 0 }, n_wait: { x: 260, y: 0 }, n_click: { x: 560, y: 0 } } },
  nodes: {
    n_click: { in: { match: { $link: "n_wait.match" } }, type: "core.input.click", version: 1 },
    n_entry: { next: { start: "n_wait" }, type: "core.graph.entry", version: 1 },
    n_wait: {
      in: { target: { $target: "targets/title/start_button.target.json" } },
      next: { found: "n_click" },
      title: "시작 버튼 대기",
      type: "core.image.wait",
      version: 1,
    },
  },
  plugins: { core: "0.1.0" },
};

const PRESERVE = "tests/preserve.graph.json";
const preserveGraph = {
  format: "kookabug.graph/0",
  kind: "test",
  layout: {
    nodes: { n_entry: { x: 0, y: 0 }, n_delay: { x: 260, y: 0 }, n_plug: { x: 560, y: 0 } },
    x_layout_unknown: { keep: [1, 2] },
  },
  nodes: {
    n_delay: {
      in: { ms: 100, x_in_unknown: "모르는 입력" },
      next: { done: "n_plug" },
      type: "core.flow.delay",
      version: 1,
      x_node_unknown: { a: 1 },
    },
    n_entry: { next: { start: "n_delay" }, type: "core.graph.entry", version: 1 },
    n_plug: {
      config: { mode: "fast", deep: { list: [1, 2.5, 1e20] } },
      in: { amount: 3, big: 1e20, link: { $link: "n_delay.missing" }, text: "그대로" },
      next: { poked: "n_entry" },
      title: "설치 안 된 플러그인",
      type: "notinstalled.widget.poke",
      version: 7,
    },
  },
  plugins: { core: "0.1.0", notinstalled: "9.9.9" },
  x_top_unknown: { keep: true },
};

const json = (v: unknown) => `${JSON.stringify(v, null, 2)}\n`;

test("test_edit_timeout_ms_saves_minimal_diff", async () => {
  s = await openEditor();
  const { page, workspace } = s;
  const original = readBytes(workspace, INVENTORY).toString("utf8");
  await openGraph(page, INVENTORY);
  await inspect(page, "n_check_inventory");
  const box = field(page, "timeout_ms").getByRole("textbox", { name: "timeout_ms", exact: true });
  await expect(box).toHaveValue("5000");
  // 정수 범위 밖은 바로 알리고 반영하지 않는다
  await box.fill("9007199254740992");
  await expect(field(page, "timeout_ms").locator('[data-part="field-error"]')).toContainText("정수 범위");
  await box.press("Enter");
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "false");
  await box.press("Escape");
  await expect(box).toHaveValue("5000");
  // min 0
  await box.fill("-1");
  await expect(field(page, "timeout_ms").locator('[data-part="field-error"]')).toContainText("0 이상");
  await box.press("Escape");
  await box.fill("7000");
  await box.press("Enter");
  await waitDirty(page, INVENTORY);
  await save(page, INVENTORY);
  // 그 줄만 바뀐다 (예제 파일은 canonical이라 저장 결과도 canonical 전체)
  const saved = readBytes(workspace, INVENTORY).toString("utf8");
  expect(saved).toBe(original.replace('"timeout_ms": 5000', '"timeout_ms": 7000'));
  const expected = JSON.parse(original) as Graph;
  (expected.nodes.n_check_inventory.in as Record<string, unknown>).timeout_ms = 7000;
  expect(pyEqual(filePath(workspace, INVENTORY), expected)).toBe(true);
});

test("test_wait_any_exits_reorder_updates_pins", async () => {
  s = await openEditor({ [WAIT_ANY]: json(waitAnyGraph) });
  const { page, workspace } = s;
  await openGraph(page, WAIT_ANY);
  await expect.poll(() => exitPins(page, "n_wait")).toEqual(["x:popup", "x:lobby", "x:timeout"]);
  await inspect(page, "n_wait");
  const exits = field(page, "exits", "config");
  await expect(exits.locator('[data-part="list-row"]')).toHaveCount(2);
  // 순서 바꾸기 → graph.validate 모양 갱신 → 캔버스 출구 핀 순서
  await exits.getByRole("button", { name: "exits 2 위로" }).click();
  await expect.poll(() => exitPins(page, "n_wait")).toEqual(["x:lobby", "x:popup", "x:timeout"]);
  // 출구 이름을 바꾸면 끊긴 next(lobby)는 그대로 두고 문제 패널에 나온다
  const first = exits.getByRole("textbox", { name: "exits 1", exact: true });
  await expect(first).toHaveValue("lobby");
  await first.fill("server");
  await first.press("Enter");
  // 끊긴 lobby는 캔버스에 "선언에 없는 출구"(T8 대체 핀)로 남아 연결선도 보인다
  await expect.poll(() => exitPins(page, "n_wait")).toEqual(["x:server", "x:popup", "x:lobby", "x:timeout"]);
  await expect(nodeEl(page, "n_wait").locator('[data-pin="x:server"]')).toHaveCount(1);
  await page.getByRole("tab", { name: /^문제/ }).click();
  await expect(page.getByRole("list", { name: "문제 목록" }).locator('[data-node="n_wait"]').first()).toContainText("lobby");
  // targets 사전도 줄 편집이다: 대상 고르기 칸이 줄마다 있다
  const targets = field(page, "targets");
  await expect(targets.locator('[data-part="list-row"]')).toHaveCount(2);
  await expect(targets.getByRole("combobox", { name: "targets popup", exact: true })).toHaveValue(
    "targets/title/maintenance_popup.target.json",
  );
  await save(page, WAIT_ANY);
  const saved = readJson<Graph>(workspace, WAIT_ANY);
  expect(saved.nodes.n_wait.config).toEqual({ exits: ["server", "popup"] });
  expect(saved.nodes.n_wait.next).toEqual({ lobby: "n_lobby", popup: "n_popup" });
  expect(saved.nodes.n_wait.in).toEqual(waitAnyGraph.nodes.n_wait.in);
});

test("test_target_picker_sets_target_ref", async () => {
  s = await openEditor();
  const { page, workspace } = s;
  await openGraph(page, INVENTORY);
  await inspect(page, "n_check_inventory");
  const target = field(page, "target");
  await expect(target).toHaveAttribute("data-mode", "target");
  const select = target.getByRole("combobox", { name: "target", exact: true });
  await expect(select).toHaveValue("targets/inventory/window_title.target.json");
  // "새 대상 만들기" 자리 (target 편집기 연결은 T12)
  await expect(target.locator('[data-part="new-target"]')).toBeVisible();
  await select.selectOption("targets/world/minimap.target.json");
  await waitDirty(page, INVENTORY);
  // 설명 줄이 새 대상 이름을 보인다
  await expect(nodeEl(page, "n_check_inventory")).toContainText("minimap");
  await save(page, INVENTORY);
  const saved = readJson<Graph>(workspace, INVENTORY);
  expect(saved.nodes.n_check_inventory.in).toEqual({
    target: { $target: "targets/world/minimap.target.json" },
    timeout_ms: 5000,
  });
});

test("test_setting_and_secret_keys", async () => {
  s = await openEditor();
  const { page, workspace } = s;
  await openGraph(page, INVENTORY);
  // 서브그래프 호출의 입력 핀은 그 서브그래프 interface에서 온다 (daemon 모양)
  await inspect(page, "n_enter_world");
  const password = field(page, "password");
  await expect(password).toHaveAttribute("data-mode", "secret");
  const secretKey = password.getByRole("textbox", { name: "password 비밀 키" });
  await expect(secretKey).toHaveValue("accounts.qa_tester_01");
  await secretKey.fill("accounts.qa_tester_02");
  await secretKey.press("Enter");
  // 빈 키는 받지 않는다
  await secretKey.fill("  ");
  await expect(password.locator('[data-part="field-error"]')).toContainText("키를 넣으세요");
  await secretKey.press("Escape");
  await expect(secretKey).toHaveValue("accounts.qa_tester_02");
  // 글자 핀을 설정 값으로 바꾼다
  const server = field(page, "server");
  await server.getByRole("combobox", { name: "server 값 종류" }).selectOption("setting");
  const settingKey = server.getByRole("textbox", { name: "server 설정 키" });
  await settingKey.fill("game.server");
  await settingKey.press("Enter");
  await expect(server).toHaveAttribute("data-mode", "setting");
  await expect(server.locator('[data-tag="$setting"]')).toContainText("설정");
  await save(page, INVENTORY);
  const saved = readJson<Graph>(workspace, INVENTORY);
  expect(saved.nodes.n_enter_world.in).toEqual({
    account: "qa_tester_01",
    password: { $secret: "accounts.qa_tester_02" },
    server: { $setting: "game.server" },
  });
});

test("test_disconnect_link_from_inspector", async () => {
  s = await openEditor({ [LINKED]: json(linkedGraph) });
  const { page, workspace } = s;
  await openGraph(page, LINKED);
  const edge = page.locator(`.react-flow__edge[data-id='d:["n_click","match"]']`);
  await expect(edge).toHaveCount(1);
  await inspect(page, "n_click");
  const match = field(page, "match");
  await expect(match).toHaveAttribute("data-mode", "link");
  await expect(match.locator('[data-part="link"]')).toContainText("시작 버튼 대기.match");
  await match.getByRole("button", { name: "연결 끊기" }).click();
  await expect(edge).toHaveCount(0);
  await expect(match).toHaveAttribute("data-mode", "value");
  await save(page, LINKED);
  const saved = readJson<Graph>(workspace, LINKED);
  // 그 핀 키를 지우고 비게 된 in도 지운다 (T9 연결 끊기와 같은 규칙)
  expect(saved.nodes.n_click).toEqual({ type: "core.input.click", version: 1 });
  expect(saved.nodes.n_wait).toEqual(linkedGraph.nodes.n_wait);
});

test("test_title_edit_keeps_id", async () => {
  s = await openEditor();
  const { page, workspace } = s;
  const before = readJson<Graph>(workspace, INVENTORY);
  await openGraph(page, INVENTORY);
  const ids = await nodeIds(page);
  await inspect(page, "n_press_i");
  const title = inspector(page).getByRole("textbox", { name: "제목", exact: true });
  await expect(title).toHaveValue("I 키");
  await expect(inspector(page).locator('[data-part="node-id"]')).toHaveText("n_press_i");
  await title.fill("인벤토리 열기 키");
  await title.press("Enter");
  await expect(nodeEl(page, "n_press_i")).toContainText("인벤토리 열기 키");
  expect(await nodeIds(page)).toEqual(ids);
  // 실행 취소 하나가 제목 고치기 하나다 (입력 칸 밖에서 Ctrl+Z: 노드를 다시 눌러 포커스를 옮긴다)
  await selectOnly(page, "n_press_i");
  await page.keyboard.press("Control+Z");
  await expect(title).toHaveValue("I 키");
  await expect(tabOf(page, INVENTORY)).toHaveAttribute("data-dirty", "false");
  await page.keyboard.press("Control+Y");
  await expect(title).toHaveValue("인벤토리 열기 키");
  await save(page, INVENTORY);
  const saved = readJson<Graph>(workspace, INVENTORY);
  expect(Object.keys(saved.nodes).sort()).toEqual(Object.keys(before.nodes).sort());
  expect(saved.nodes.n_press_i).toEqual({ ...before.nodes.n_press_i, title: "인벤토리 열기 키" });
  expect(saved.layout).toEqual(before.layout);
  const expected = structuredClone(before);
  expected.nodes.n_press_i.title = "인벤토리 열기 키";
  expect(pyEqual(filePath(workspace, INVENTORY), expected)).toBe(true);
});

test("test_property_edits_preserve_unknown_nodes_and_keys", async () => {
  // 1e20(실수)이 든 파일이라 JSON.stringify 대신 원문을 그대로 쓴다
  const text = json(preserveGraph).replace(/100000000000000000000/g, "1e20");
  s = await openEditor({ [PRESERVE]: text });
  const { page, workspace } = s;
  await openGraph(page, PRESERVE);
  await expect(nodeEl(page, "n_plug").locator('[data-part="node"]')).toHaveAttribute("data-unknown", "true");
  // 아는 노드: 핀 하나만 고친다. 선언에 없는 입력은 JSON 칸으로 보이고 그대로다
  await inspect(page, "n_delay");
  const ms = field(page, "ms").getByRole("textbox", { name: "ms", exact: true });
  await ms.fill("250");
  await ms.press("Enter");
  await expect(field(page, "x_in_unknown")).toContainText("선언에 없음");
  // 모르는 노드: in JSON 상자에서 amount만 고친다
  await inspect(page, "n_plug");
  await expect(inspector(page).locator('[data-part="unknown-note"]')).toBeVisible();
  const box = inspector(page).getByRole("textbox", { name: "입력 JSON" });
  const shown = await box.inputValue();
  expect(shown).toContain('"big": 1e+20');
  await box.fill(shown.replace('"amount": 3', '"amount": 4'));
  await box.press("Control+Enter");
  await waitDirty(page, PRESERVE);
  // 틀린 JSON은 반영하지 않는다
  await box.fill("{ 틀림");
  await expect(inspector(page).locator('[data-part="field-error"]')).toContainText("JSON이 아니에요");
  await box.press("Escape");
  await save(page, PRESERVE);
  const expected = structuredClone(preserveGraph) as unknown as Graph;
  (expected.nodes.n_delay.in as Record<string, unknown>).ms = 250;
  (expected.nodes.n_plug.in as Record<string, unknown>).amount = 4;
  expect(pyEqual(filePath(workspace, PRESERVE), expected)).toBe(true);
  // 1e20은 실수로 남는다 (2.6 전송 코덱)
  const saved = readBytes(workspace, PRESERVE).toString("utf8");
  expect(saved).toContain('"big": 1e+20');
  expect(saved).not.toContain("100000000000000000000");
  await expect(canvasOf(page, PRESERVE)).toHaveAttribute("data-saves", "1");
});

// ── T10 검수 1·2 회귀 ────────────────────────────────────────────

const CANCEL = "tests/cancel.graph.json";
const cancelGraph = {
  format: "kookabug.graph/0",
  kind: "test",
  layout: {
    nodes: { n_entry: { x: 0, y: 0 }, n_delay: { x: 260, y: 0 }, n_unknown: { x: 0, y: 200 }, n_click: { x: 520, y: 0 } },
  },
  nodes: {
    n_click: { in: { point: [10, 20] }, type: "core.input.click", version: 1 },
    n_delay: { in: { ms: 100 }, title: "Original", type: "core.flow.delay", version: 1 },
    n_entry: { next: { start: "n_delay" }, type: "core.graph.entry", version: 1 },
    n_unknown: { config: { retained: true }, in: { a: 1, secret: { $secret: "accounts.test" } }, type: "missing.node", version: 7 },
  },
  plugins: { core: "0.1.0" },
};

/** 편집 메뉴의 "실행 취소"가 꺼져 있는가 (실행 취소 기록이 없음) */
async function undoDisabled(page: Page): Promise<boolean> {
  await page.getByRole("navigation", { name: "메뉴" }).getByRole("button", { name: "편집", exact: true }).click();
  const item = page.getByRole("menu", { name: "편집" }).getByRole("menuitem", { name: /실행 취소/ });
  const disabled = await item.isDisabled();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("menu", { name: "편집" })).toHaveCount(0);
  return disabled;
}

test("test_escape_cancels_valid_drafts", async () => {
  test.setTimeout(150_000);
  // 유효한 값을 넣은 뒤 Esc: 칸·dirty·실행 취소 기록·저장 바이트가 그대로다 (숫자·제목·JSON·좌표 칸)
  const text = json(cancelGraph);
  s = await openEditor({ [CANCEL]: text });
  const { page, workspace } = s;
  await openGraph(page, CANCEL);
  const cases = [
    { node: "n_delay", name: "ms", draft: "250" },
    { node: "n_delay", name: "제목", draft: "Cancelled" },
    { node: "n_unknown", name: "입력 JSON", draft: '{"a": 2, "secret": {"$secret": "accounts.test"}}' },
    { node: "n_click", name: "point x", draft: "50" },
  ];
  for (const c of cases) {
    await inspect(page, c.node);
    const box = inspector(page).getByRole("textbox", { name: c.name, exact: true });
    const before = await box.inputValue();
    await box.fill(c.draft);
    await box.press("Escape");
    await expect(box).toHaveValue(before);
    await expect(box).not.toBeFocused();
    await expect(tabOf(page, CANCEL)).toHaveAttribute("data-dirty", "false");
    expect(await undoDisabled(page), `${c.name}: 실행 취소 기록`).toBe(true);
  }
  // 무수정 저장: 바이트 그대로
  await save(page, CANCEL);
  expect(readBytes(workspace, CANCEL).toString("utf8")).toBe(text);
  // 대조: 칸을 떠나면(Esc 아님) 반영된다
  await inspect(page, "n_delay");
  const ms = inspector(page).getByRole("textbox", { name: "ms", exact: true });
  await ms.fill("250");
  await inspector(page).getByRole("textbox", { name: "제목", exact: true }).focus();
  await waitDirty(page, CANCEL);
  await expect(ms).toHaveValue("250");
});

test("test_config_link_like_value_not_interpreted", async () => {
  // config 안의 `$link`처럼 생긴 값은 보통 데이터다: 연결 끊기가 없고, 고쳐도 같은 이름의 입력 핀(in.ms)은 그대로
  const fixture = structuredClone(cancelGraph) as unknown as Graph;
  fixture.nodes.n_delay.config = { ms: { retained: { $link: "n_entry.any" } } };
  s = await openEditor({ [CANCEL]: json(fixture) });
  const { page, workspace } = s;
  await openGraph(page, CANCEL);
  await inspect(page, "n_delay");
  const config = field(page, "ms", "config");
  await expect(config).toHaveAttribute("data-mode", "value");
  await expect(config.getByRole("button", { name: "연결 끊기" })).toHaveCount(0);
  await expect(config.locator('[data-part="linked-inside"], [data-part="link"]')).toHaveCount(0);
  const box = config.getByRole("textbox", { name: "ms", exact: true });
  const shown = await box.inputValue();
  expect(shown).toContain('"$link": "n_entry.any"');
  await box.fill(shown.replace("n_entry.any", "n_entry.other"));
  await box.press("Control+Enter");
  await waitDirty(page, CANCEL);
  // 지우기(×)도 config 키만 지운다
  await save(page, CANCEL);
  let saved = readJson<Graph>(workspace, CANCEL);
  expect(saved.nodes.n_delay.in).toEqual({ ms: 100 });
  expect(saved.nodes.n_delay.config).toEqual({ ms: { retained: { $link: "n_entry.other" } } });
  await config.getByRole("button", { name: "ms 지우기" }).click();
  await save(page, CANCEL);
  saved = readJson<Graph>(workspace, CANCEL);
  expect(saved.nodes.n_delay.in).toEqual({ ms: 100 });
  expect(Object.hasOwn(saved.nodes.n_delay, "config")).toBe(false);
});
