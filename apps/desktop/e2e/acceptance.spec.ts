// M2 완료 기준 인수 검사, 앱 쪽 (M2 계획 3장 "완료 기준 → 테스트 매핑"). 실제 Electron 앱 + 실제 daemon(레포 .venv) +
// 예제 워크스페이스 사본. 다른 검사 모듈은 가져오지 않고 helpers만 쓴다. 저장한 파일은 Python 코어 규칙
// (graph_check.py: loads_strict·json_equal·check_graph·target 매칭)으로 본다.
//
// 1. 아무것도 안 바꾸고 저장하면 바이트가 같음 (말뭉치 전체 + 예제 그래프, 큰 실수 세 개가 든 파일 포함, 검수 H1)
// 2. 편집 후 의미·노드 ID·모르는 노드 설정 보존 (편집 열: 추가·이동·연결·속성·지우기 + NaN 입력 시도, 2차 검수 N3)
// 3. target 편집기로 만든 대상이 바로 매칭됨 (+ 그 target을 쓰는 그래프 실행 pass, 사용자 PNG 보존 2차 검수 N1)
// (범위) 팔레트·검증 표시·실행·실행 중 강조
import fs from "node:fs";
import path from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { REPO_ROOT } from "./helpers/app";
import { SAMPLE_WORKSPACE } from "./helpers/daemon";
import {
  canvasOf,
  closeEditor,
  connectPins,
  dragNode,
  dropFromPalette,
  filePath,
  mtime,
  nodeEl,
  openEditor,
  openGraph,
  pin,
  pyDiagnostics,
  pyEqual,
  pyFind,
  pyTypes,
  readBytes,
  readJson,
  save,
  selectOnly,
  tabOf,
  type EditorSession,
  type PyDiagnostic,
} from "./helpers/editor";
import {
  clickRun,
  closeRunApp,
  INVENTORY,
  openRunApp,
  prepareRunWorkspace,
  releaseGate,
  runFolders,
  runNode,
  toolbar,
  waitEnded,
  waitGate,
  type RunSession,
} from "./helpers/run";
import {
  addCapture,
  editorOf,
  frameOf,
  loadFrame,
  openTarget,
  readTarget,
  saveTargetTab,
  selectRect,
  START_BUTTON,
  TITLE_TEXT,
  waitPreview,
} from "./helpers/target";

let editor: EditorSession | null = null;
let runner: RunSession | null = null;

test.afterEach(async () => {
  await closeEditor(editor);
  editor = null;
  await closeRunApp(runner);
  runner = null;
});

type Graph = {
  nodes: Record<string, Record<string, unknown>>;
  layout?: { nodes?: Record<string, { x: number; y: number }>; [k: string]: unknown };
  [k: string]: unknown;
};

/** 바이트·mtime이 그대로인지 보려고 mtime 해상도보다 오래 기다린 뒤 저장한다 */
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ── 1. 무수정 저장 ────────────────────────────────────────────────

/** 말뭉치 목록(fixtures/graph-corpus/corpus.json) → 워크스페이스 경로. 예제 워크스페이스 파일은 제자리 */
function corpusFiles(): Record<string, Buffer> {
  const list = JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "fixtures", "graph-corpus", "corpus.json"), "utf8")) as { files: string[] };
  const out: Record<string, Buffer> = {};
  for (const rel of list.files) {
    const source = path.join(REPO_ROOT, ...rel.split("/"));
    const inSample = path.relative(SAMPLE_WORKSPACE, source);
    const key = inSample.startsWith("..") ? `tests/corpus/${path.basename(source)}` : inSample.split(path.sep).join("/");
    out[key] = fs.readFileSync(source);
  }
  return out;
}

test("test_open_save_unchanged_bytes_identical", async () => {
  test.setTimeout(420_000);
  const files = corpusFiles();
  const extra = Object.fromEntries(Object.entries(files).filter(([rel]) => rel.startsWith("tests/corpus/")));
  editor = await openEditor(extra);
  const { page, workspace } = editor;
  // 큰 실수 세 개가 원문 그대로 든 파일이 목록에 있다 (검수 H1)
  const numbers = readBytes(workspace, "tests/corpus/numbers.graph.json").toString("utf8");
  for (const token of ["1e20", "9007199254740992.0", "1.2345678901234567e19"]) expect(numbers).toContain(token);
  const before = new Map(Object.keys(files).map((rel) => [rel, { bytes: readBytes(workspace, rel), mtime: mtime(workspace, rel) }]));
  for (const [rel, b] of before) expect(b.bytes.equals(files[rel]), rel).toBe(true);
  await pause(50);
  for (const rel of before.keys()) {
    const canvas = await openGraph(page, rel);
    await expect(canvas, rel).toHaveAttribute("data-dirty", "false");
    await save(page, rel);
    await expect(canvas, rel).toHaveAttribute("data-dirty", "false");
    const b = before.get(rel)!;
    expect(readBytes(workspace, rel).equals(b.bytes), rel).toBe(true);
    expect(mtime(workspace, rel), rel).toBe(b.mtime);
    await page.keyboard.press("Control+W");
    await expect(tabOf(page, rel)).toHaveCount(0);
  }
});

// ── 2. 편집 후 보존 ───────────────────────────────────────────────

const EDIT = "tests/acceptance_edit.graph.json";
// 원문 그대로 쓴다: 1e20 등 큰 실수는 JSON.stringify를 거치면 정수 토큰이 된다
const EDIT_TEXT = `{
  "format": "kookabug.graph/0",
  "kind": "test",
  "layout": {
    "nodes": {
      "n_entry": {"x": 0, "y": 0},
      "n_delay": {"x": 260, "y": 0},
      "n_log": {"x": 560, "y": 0},
      "n_pass": {"x": 860, "y": 0},
      "n_spare": {"x": 260, "y": 220},
      "n_magic": {"x": 560, "y": 220}
    },
    "x_layout_unknown": {"keep": [1, 2]}
  },
  "meta": {"title": "인수 편집"},
  "nodes": {
    "n_entry": {"next": {"start": "n_delay"}, "type": "core.graph.entry", "version": 1},
    "n_delay": {"in": {"ms": 100, "x_in_unknown": "모르는 입력"}, "next": {"done": "n_log"}, "type": "core.flow.delay", "version": 1, "x_node_unknown": {"a": 1}},
    "n_log": {"in": {"text": "하나"}, "next": {"done": "n_pass"}, "type": "core.log.message", "version": 1, "x_node_unknown": "손대지 않음"},
    "n_pass": {"type": "core.test.pass", "version": 1},
    "n_spare": {"in": {"text": "지울 노드"}, "type": "core.log.message", "version": 1},
    "n_magic": {
      "config": {"big": 1e20, "deep": {"list": [1, 2.5, 1e+20]}, "mode": "fast"},
      "in": {"big": 1e20, "two_53_float": 9007199254740992.0, "big_digits": 1.2345678901234567e19, "text": "그대로"},
      "title": "설치 안 된 플러그인",
      "type": "notinstalled.widget.poke",
      "version": 7
    }
  },
  "plugins": {"core": "0.1.0", "notinstalled": "9.9.9"},
  "x_top_unknown": {"keep": true}
}
`;

function inspector(page: Page): Locator {
  return page.locator('[data-part="inspector"]');
}

function field(page: Page, name: string): Locator {
  return inspector(page).locator(`[data-part="field"][data-field="in"][data-pin="${name}"]`);
}

async function inspect(page: Page, id: string): Promise<void> {
  await selectOnly(page, id);
  await expect(inspector(page).locator('[data-part="inspector-body"]')).toHaveAttribute("data-node", id);
}

/** 진단을 노드 기준으로 나눠 비교할 수 있는 글자로 */
function diagKeys(list: PyDiagnostic[], skip: Set<string>): string[] {
  return list.filter((d) => d[2] === null || !skip.has(d[2])).map((d) => JSON.stringify(d)).sort();
}

test("test_edit_preserves_semantics_ids_unknown_nodes", async () => {
  test.setTimeout(180_000);
  editor = await openEditor({ [EDIT]: EDIT_TEXT });
  const { page, workspace } = editor;
  const file = filePath(workspace, EDIT);
  const original = readJson<Graph>(workspace, EDIT);
  const diagBefore = pyDiagnostics(workspace, EDIT);
  // 손대지 않는 노드(n_log의 모르는 키)와 그래프 전체(모르는 최상위 키)에 진단이 있다: 편집 뒤에도 그대로여야 한다
  expect(diagBefore.some((d) => d[2] === "n_log")).toBe(true);
  expect(diagBefore.some((d) => d[2] === null)).toBe(true);
  const canvas = await openGraph(page, EDIT);
  await expect(nodeEl(page, "n_magic").locator('[data-part="node"]')).toHaveAttribute("data-unknown", "true");

  // 0) NaN 입력 시도 (2차 검수 N3): 어느 길로도 반영·저장되지 않고 파일은 그대로다
  const bytes = readBytes(workspace, EDIT);
  const time = mtime(workspace, EDIT);
  await inspect(page, "n_delay");
  const ms = field(page, "ms").getByRole("textbox", { name: "ms", exact: true });
  await ms.fill("NaN");
  await expect(field(page, "ms").locator('[data-part="field-error"]')).toBeVisible();
  await ms.press("Enter");
  await expect(tabOf(page, EDIT)).toHaveAttribute("data-dirty", "false");
  await ms.press("Escape");
  await expect(ms).toHaveValue("100");
  await inspect(page, "n_magic");
  const box = inspector(page).getByRole("textbox", { name: "입력 JSON" });
  const shown = await box.inputValue();
  await box.fill(shown.replace('"text": "그대로"', '"text": "그대로", "inf": 1e400'));
  await expect(inspector(page).locator('[data-part="field-error"]')).toContainText("유한하지 않은 수");
  await box.press("Control+Enter");
  await expect(tabOf(page, EDIT)).toHaveAttribute("data-dirty", "false");
  await box.press("Escape");
  // 렌더러 검사를 건너뛰고 다리로 바로 NaN 값을 보내도 주 프로세스 전송 코덱이 거부한다
  const bridged = await page.evaluate(async (rel) => {
    const opened = (await window.kookabug.rpc("graph.open", { path: rel })) as {
      doc_id: string;
      revision: string;
      value: { nodes: Record<string, { in: Record<string, unknown> }> };
    };
    opened.value.nodes.n_delay.in.ms = Number.NaN;
    try {
      await window.kookabug.rpc("graph.save", { doc_id: opened.doc_id, value: opened.value, base_revision: opened.revision });
      return "saved";
    } catch (err) {
      return (err as { data?: { code?: string; pointer?: string } }).data ?? null;
    }
  }, EDIT);
  expect(bridged).toEqual({ code: "number_not_finite", pointer: expect.stringContaining("/nodes/n_delay/in/ms") });
  expect(readBytes(workspace, EDIT).equals(bytes)).toBe(true);
  expect(mtime(workspace, EDIT)).toBe(time);

  // 1) 지우기: 연결이 없는 n_spare
  await selectOnly(page, "n_spare");
  await page.keyboard.press("Delete");
  await expect(nodeEl(page, "n_spare")).toHaveCount(0);
  // 2) 팔레트에서 더하기
  const area = (await canvas.boundingBox())!;
  const added = await dropFromPalette(page, canvas, "고정 지연", "core.flow.delay", { x: area.width - 240, y: area.height - 160 });
  // 3) 잇기: 새 노드 done → n_pass
  await connectPins(page, pin(page, added, "x:done"), pin(page, "n_pass", "in"));
  await expect(page.locator(`.react-flow__edge[data-id='x:${JSON.stringify([added, "done"])}']`)).toHaveCount(1);
  // 4) 옮기기
  await dragNode(page, "n_entry", 37, 23);
  // 5) 속성: n_delay.ms 100 → 250
  await inspect(page, "n_delay");
  await ms.fill("250");
  await ms.press("Enter");
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await save(page, EDIT);
  await expect(canvas).toHaveAttribute("data-dirty", "false");

  // 기대 값: 처음 값에 이 편집만 (노드 ID 그대로, 모르는 키·모르는 노드 그대로)
  const saved = readJson<Graph>(workspace, EDIT);
  const layout = saved.layout!.nodes!;
  for (const id of [added, "n_entry"]) expect(Number.isInteger(layout[id].x) && Number.isInteger(layout[id].y), id).toBe(true);
  expect(layout.n_entry).not.toEqual(original.layout!.nodes!.n_entry);
  const expected = structuredClone(original);
  delete expected.nodes.n_spare;
  delete expected.layout!.nodes!.n_spare;
  expected.nodes[added] = { next: { done: "n_pass" }, type: "core.flow.delay", version: 1 };
  (expected.nodes.n_delay.in as Record<string, unknown>).ms = 250;
  expected.layout!.nodes![added] = layout[added];
  expected.layout!.nodes!.n_entry = layout.n_entry;
  expect(Object.keys(saved.nodes).sort()).toEqual(Object.keys(expected.nodes).sort());
  expect(saved).toEqual(expected);
  expect(pyEqual(file, expected)).toBe(true);
  // 손대지 않은 노드·모르는 노드는 값이 그대로 (Python json_equal, 노드 하나씩)
  for (const id of ["n_entry", "n_log", "n_pass", "n_magic"]) {
    const only = { ...saved, nodes: { ...saved.nodes, [id]: original.nodes[id] } };
    expect(pyEqual(file, only), id).toBe(true);
  }
  // 큰 실수는 실수로 남는다 (canonical 지수 표기)
  expect(
    pyTypes(file, [
      "/nodes/n_magic/in/big",
      "/nodes/n_magic/in/two_53_float",
      "/nodes/n_magic/in/big_digits",
      "/nodes/n_magic/config/big",
      "/nodes/n_magic/config/deep/list/2",
      "/nodes/n_delay/in/ms",
    ]),
  ).toEqual({
    "/nodes/n_magic/in/big": "float",
    "/nodes/n_magic/in/two_53_float": "float",
    "/nodes/n_magic/in/big_digits": "float",
    "/nodes/n_magic/config/big": "float",
    "/nodes/n_magic/config/deep/list/2": "float",
    "/nodes/n_delay/in/ms": "int",
  });
  const text = readBytes(workspace, EDIT).toString("utf8");
  for (const token of ["1e+20", "9.007199254740992e+15", "1.2345678901234567e+19"]) expect(text).toContain(token);
  // 진단 집합은 편집한 노드에서만 바뀐다 (지운·더한·속성 고친 노드. 이동은 의미가 아니다)
  const diagAfter = pyDiagnostics(workspace, EDIT);
  const touched = new Set(["n_spare", added, "n_delay"]);
  expect(diagKeys(diagAfter, touched)).toEqual(diagKeys(diagBefore, touched));
});

// ── 3. target 편집기 ──────────────────────────────────────────────

const MADE_GRAPH = "tests/editor_target.graph.json";
const MADE_TARGET = "targets/made/start.target.json";

function madeGraph(target: string): string {
  return JSON.stringify(
    {
      format: "kookabug.graph/0",
      kind: "test",
      layout: { nodes: { n_entry: { x: 0, y: 0 }, n_launch: { x: 260, y: 0 }, n_wait: { x: 560, y: 0 }, n_pass: { x: 860, y: 0 } } },
      meta: { title: "편집기 대상" },
      nodes: {
        n_entry: { next: { start: "n_launch" }, type: "core.graph.entry", version: 1 },
        n_launch: {
          in: { path: "SampleRPG", timeout_ms: 5000, window_title: "SampleRPG" },
          next: { attached: "n_wait" },
          type: "core.app.launch",
          version: 1,
        },
        n_wait: {
          in: { target: { $target: target }, timeout_ms: 5000 },
          next: { found: "n_pass" },
          title: "시작 버튼",
          type: "core.image.wait",
          version: 1,
        },
        n_pass: { type: "core.test.pass", version: 1 },
      },
      plugins: { core: "0.1.0" },
    },
    null,
    2,
  );
}

test("test_target_editor_made_target_matches_and_runs", async () => {
  test.setTimeout(180_000);
  const userPng = fs.readFileSync(filePath(SAMPLE_WORKSPACE, "targets/title/start_button.png"));
  const USER = "targets/user/button.target.json";
  const ws = prepareRunWorkspace();
  const files: Record<string, string | Buffer> = {
    [MADE_GRAPH]: madeGraph(MADE_TARGET),
    "targets/user/source.png": userPng,
    [USER]: JSON.stringify({ format: "kookabug.target/0", image: "source.png", recorded: { client_size: [1024, 640], dpi: 96 } }, null, 2),
  };
  for (const [rel, data] of Object.entries(files)) {
    fs.mkdirSync(path.dirname(filePath(ws.root, rel)), { recursive: true });
    fs.writeFileSync(filePath(ws.root, rel), data);
  }
  const capture = addCapture(ws.root, "title.png");
  runner = await openRunApp(ws);
  const { page } = runner;

  // 그래프의 대상 칸에서 새 대상을 만든다 (속성 편집기 → TARGET 탭)
  await page.getByRole("tree", { name: "워크스페이스 파일" }).locator(`[data-path="${MADE_GRAPH}"]`).click();
  await expect(canvasOf(page, MADE_GRAPH)).toHaveAttribute("data-status", "ready");
  await selectOnly(page, "n_wait");
  // 그래프는 이미 MADE_TARGET을 가리킨다 (파일은 아직 없음): 같은 경로로 새로 만든다
  const targetField = inspector(page).locator('[data-part="field"][data-field="in"][data-pin="target"]');
  await targetField.locator('[data-part="new-target"]').click();
  const dialog = page.getByRole("dialog", { name: "새 찾기 대상" });
  await dialog.getByRole("textbox", { name: "이름" }).fill("made/start");
  await dialog.getByRole("button", { name: "만들기" }).click();
  await expect(editorOf(page, MADE_TARGET)).toHaveAttribute("data-new", "true");

  // 정지 화면 → 영역 끌기 → 저장 전 미리보기 = 고른 영역
  await loadFrame(page, capture);
  const crop = await selectRect(page, START_BUTTON);
  expect(crop).toEqual([...START_BUTTON]);
  expect(await waitPreview(page, true)).toEqual(crop);
  await saveTargetTab(page, MADE_TARGET);
  // 바로 매칭: 저장 결과 = 같은 정지 화면에서 찾음, 점수 ≥ 임계값
  const saved = page.locator('[data-part="target-saved"]');
  await expect(saved).toHaveAttribute("data-found", "true");
  await expect(saved).toContainText("바로 매칭: 찾음");
  // 저장한 파일(디스크 이미지)로 다시 찾아도 같은 상자 (편집기 안, 그리고 Python이 파일을 다시 읽어서)
  await expect(frameOf(page).locator('[data-part="template-rect"]')).toHaveCount(0);
  expect(await waitPreview(page, true)).toEqual(crop);
  expect(pyFind(filePath(ws.root, MADE_TARGET), filePath(ws.root, capture))).toEqual(crop);
  expect(readTarget(ws.root, MADE_TARGET).recorded).toEqual({ client_size: [1024, 640], dpi: 96 });

  // 그 target을 쓰는 그래프 실행 → 통과 (가짜 플랫폼, 예제 장면)
  await tabOf(page, MADE_GRAPH).getByRole("button").first().click();
  await expect(nodeEl(page, "n_wait")).toBeVisible();
  await clickRun(page);
  await waitEnded(page, "pass");

  // 사용자가 넣은 PNG를 쓰던 target을 새 영역으로 다시 저장: 새 이미지, 사용자 PNG는 그대로 (2차 검수 N1)
  await openTarget(page, USER);
  await loadFrame(page, capture);
  await waitPreview(page, true);
  await selectRect(page, TITLE_TEXT);
  await waitPreview(page, true);
  await saveTargetTab(page, USER);
  const spec = readTarget(ws.root, USER);
  expect(spec.image).not.toBe("source.png");
  expect(fs.readFileSync(filePath(ws.root, "targets/user/source.png")).equals(userPng)).toBe(true);
  expect(pyFind(filePath(ws.root, USER), filePath(ws.root, capture))).toEqual([...TITLE_TEXT]);
});

// ── (범위) 팔레트·검증 표시·실행·실행 중 강조 ───────────────────────

test("test_palette_validate_run_highlight", async () => {
  test.setTimeout(180_000);
  const ws = prepareRunWorkspace({ i: "press_i" });
  runner = await openRunApp(ws);
  const { page } = runner;
  const canvas = await openGraph(page, INVENTORY);

  // 팔레트: 시안 분류 묶음과 검색
  const palette = page.getByRole("tree", { name: "노드 팔레트" });
  await expect(palette.getByRole("group", { name: "창" })).toBeVisible();
  await page.getByRole("searchbox", { name: "노드 검색" }).fill("이미지 대기");
  await expect(palette.locator("[data-node-type]")).toHaveCount(1);
  // 필수 입력이 빠진 노드를 놓으면 daemon 검증이 그 노드와 문제 패널에 오류를 단다
  const area = (await canvas.boundingBox())!;
  const added = await dropFromPalette(page, canvas, "이미지 대기", "core.image.wait", { x: area.width / 2, y: area.height - 160 });
  const addedBody = nodeEl(page, added).locator('[data-part="node"]');
  await expect(addedBody).not.toHaveAttribute("data-errors", "0", { timeout: 10_000 });
  await expect(addedBody).toHaveAttribute("data-head", "error");
  await page.getByRole("tab", { name: /문제/ }).click();
  const problem = page.getByRole("list", { name: "문제 목록" }).locator(`[data-node="${added}"]`).first();
  await expect(problem).toBeVisible();
  // 오류가 있으면 실행을 막는다 (자동 저장 뒤 사전 검증, 실행 폴더 없음)
  await clickRun(page);
  await expect(toolbar(page).locator('[data-part="run-blocked"]')).toHaveText(/^검증 오류 [1-9]\d*개$/);
  expect(runFolders(ws)).toEqual([]);
  // 지우고 저장하면 다시 실행할 수 있다
  await selectOnly(page, added);
  await page.keyboard.press("Delete");
  await expect(nodeEl(page, added)).toHaveCount(0);
  await save(page, INVENTORY);

  // 메뉴 "실행"의 실행·정지는 툴바와 같은 명령·활성 조건이다: 대기 중 실행만 켜짐 → 메뉴로 실행한다
  const runMenu = async () => {
    await page.getByRole("navigation", { name: "메뉴" }).getByRole("button", { name: "실행", exact: true }).click();
    const menu = page.getByRole("menu", { name: "실행" });
    return { menu, run: menu.getByRole("menuitem", { name: /^실행/ }), stop: menu.getByRole("menuitem", { name: /^정지/ }) };
  };
  let m = await runMenu();
  await expect(m.run).toBeEnabled();
  await expect(m.stop).toBeDisabled();
  await m.run.click();
  // 실행 → I 키 앞에서 멈춘 동안: 지금 노드만 강조, 지나간 노드는 결과·시간, 상태 바 실행 중
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running");
  await waitGate(ws, "press_i");
  m = await runMenu();
  await expect(m.run).toBeDisabled();
  await expect(m.stop).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(m.menu).toHaveCount(0);
  await expect(runNode(page, "n_press_i")).toHaveAttribute("data-run", "active");
  await expect(page.locator('[data-part="node"][data-run="active"]')).toHaveCount(1);
  for (const id of ["n_entry", "n_enter_world"]) {
    await expect(runNode(page, id)).toHaveAttribute("data-run-tone", "ok");
    await expect(runNode(page, id).locator('[data-part="node-status"]')).toHaveText(/^✓ \d/);
  }
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "true");
  releaseGate(ws, "press_i");
  await waitEnded(page, "pass");
  await expect(page.locator('[data-part="node"][data-run="active"]')).toHaveCount(0);
  await expect(runNode(page, "n_check_inventory")).toHaveAttribute("data-run-tone", "ok");
  await expect(page.locator('[data-part="statusbar"]')).toHaveAttribute("data-running", "false");
  await expect(page.locator('[data-part="run-result"]')).toHaveAttribute("data-verdict", "pass");
  expect(runFolders(ws)).toHaveLength(1);
});
