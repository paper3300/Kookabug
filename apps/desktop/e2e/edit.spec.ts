// 구조 편집·팔레트·저장 (M2 계획 T9 완료 기준 e2e/edit.spec.ts). 실제 daemon(레포 .venv)과 예제 워크스페이스 사본.
// 저장한 파일은 Python 코어 규칙(graph_check.py: loads_strict·json_equal)으로 본다
import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { killDaemon, waitConnected } from "./helpers/daemon";
import {
  canvasOf,
  clickEdge,
  closeEditor,
  connectPins,
  CORPUS_DIR,
  dragNode,
  dropFromPalette,
  filePath,
  mtime,
  nodeEl,
  openEditor,
  openGraph,
  pin,
  pyEqual,
  pyTypes,
  readBytes,
  readJson,
  save,
  selectOnly,
  tabOf,
  writeFile,
  type EditorSession,
} from "./helpers/editor";

let s: EditorSession | null = null;

test.afterEach(async () => {
  await closeEditor(s);
  s = null;
});

const corpus = (name: string) => fs.readFileSync(path.join(CORPUS_DIR, `${name}.graph.json`));

type Graph = {
  nodes: Record<string, Record<string, unknown>>;
  layout?: { nodes?: Record<string, { x: number; y: number }> };
  [k: string]: unknown;
};

/** 바이트·mtime이 그대로인지 보려고 mtime 해상도보다 오래 기다린 뒤 저장한다 */
const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

test("test_open_save_without_change_bytes_identical", async () => {
  test.setTimeout(300_000);
  // 말뭉치 일부(원문 표기가 여러 가지인 것, 수·문자열·모르는 키·모르는 노드·접기·특수 값) + 예제 그래프 전부
  const names = [
    "canonical",
    "crlf",
    "indent4",
    "no-final-newline",
    "shuffled-keys",
    "integer-like-keys",
    "numbers",
    "strings",
    "proto-keys",
    "unknown-keys",
    "unknown-node",
    "groups-comments",
    "special-values",
    "empty-containers",
  ];
  const files: Record<string, Buffer> = {};
  for (const n of names) files[`tests/corpus/${n}.graph.json`] = corpus(n);
  s = await openEditor(files);
  const { page, workspace } = s;
  const samples = [
    "tests/inventory_open.graph.json",
    "tests/smoke_headless.graph.json",
    "tests/broken/swapped_target.graph.json",
    "subgraphs/enter_world.graph.json",
    "subgraphs/broken/enter_world_swapped_target.graph.json",
  ];
  const all = [...Object.keys(files), ...samples];
  const before = new Map(all.map((rel) => [rel, { bytes: readBytes(workspace, rel), mtime: mtime(workspace, rel) }]));
  await pause(50);
  for (const rel of all) {
    const canvas = await openGraph(page, rel);
    await expect(canvas).toHaveAttribute("data-dirty", "false");
    await save(page, rel);
    await expect(canvas).toHaveAttribute("data-dirty", "false");
    const b = before.get(rel)!;
    expect(readBytes(workspace, rel).equals(b.bytes), rel).toBe(true);
    expect(mtime(workspace, rel), rel).toBe(b.mtime);
    await page.keyboard.press("Control+W");
    await expect(tabOf(page, rel)).toHaveCount(0);
  }
});

test("test_edit_save_preserves_ids_unknown_config_semantics", async () => {
  const REL = "tests/unknown_node.graph.json";
  s = await openEditor({ [REL]: corpus("unknown-node") });
  const { page, workspace } = s;
  const original = readJson<Graph>(workspace, REL);
  const canvas = await openGraph(page, REL);
  // 1) 노드 지우기 (n_pass: n_log.next.done이 가리킴)
  await selectOnly(page, "n_pass");
  await page.keyboard.press("Delete");
  await expect(nodeEl(page, "n_pass")).toHaveCount(0);
  // 2) 팔레트에서 더하기
  const box = (await canvas.boundingBox())!;
  const added = await dropFromPalette(page, canvas, "고정 지연", "core.flow.delay", { x: box.width - 220, y: 120 });
  // 3) 흐름 잇기: n_log.done → 새 노드
  await connectPins(page, pin(page, "n_log", "x:done"), pin(page, added, "in"));
  await expect(page.locator(`.react-flow__edge[data-id='x:${JSON.stringify(["n_log", "done"])}']`)).toHaveCount(1);
  // 4) 옮기기 (좌표가 없던 노드)
  await dragNode(page, "n_entry", 37, 23);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await save(page, REL);
  await expect(canvas).toHaveAttribute("data-dirty", "false");

  const saved = readJson<Graph>(workspace, REL);
  const layout = saved.layout!.nodes!;
  for (const id of [added, "n_entry"]) {
    expect(Number.isInteger(layout[id].x) && Number.isInteger(layout[id].y), id).toBe(true);
  }
  // 기대 값: 처음 값에 한 편집만 (노드 ID 그대로, 모르는 노드·config 그대로)
  const expected = structuredClone(original);
  delete expected.nodes.n_pass;
  expected.nodes.n_log.next = { done: added };
  expected.nodes[added] = { type: "core.flow.delay", version: 1 };
  expected.layout = { nodes: { [added]: layout[added], n_entry: layout.n_entry } };
  expect(Object.keys(saved.nodes).sort()).toEqual(Object.keys(expected.nodes).sort());
  // JS 비교는 차이를 보여 주고, 판정은 Python json_equal로 한다
  expect(saved).toEqual(expected);
  expect(pyEqual(filePath(workspace, REL), expected)).toBe(true);
  // 모르는 노드는 바이트 단위 값까지 그대로 (Python으로 그 노드만)
  expect(pyEqual(filePath(workspace, REL), { ...saved, nodes: { ...saved.nodes, n_magic: original.nodes.n_magic } })).toBe(true);
  expect(saved.nodes.n_magic).toEqual(original.nodes.n_magic);
  expect(saved.plugins).toEqual(original.plugins);
});

test("test_edit_then_undo_all_save_keeps_original_bytes", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const bytes = readBytes(workspace, REL);
  const time = mtime(workspace, REL);
  const canvas = await openGraph(page, REL);
  await dragNode(page, "n_press_i", 60, 40);
  await selectOnly(page, "n_skip_maintenance");
  await page.keyboard.press("Delete");
  await expect(nodeEl(page, "n_skip_maintenance")).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await expect(tabOf(page, REL)).toHaveAttribute("data-dirty", "true");
  await page.keyboard.press("Control+Z");
  await expect(nodeEl(page, "n_skip_maintenance")).toHaveCount(1);
  await page.keyboard.press("Control+Z");
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  await expect(tabOf(page, REL)).toHaveAttribute("data-dirty", "false");
  // 다시 실행 → 다시 dirty, 되돌리면 깨끗
  await page.keyboard.press("Control+Y");
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await page.keyboard.press("Control+Z");
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  await pause(50);
  await save(page, REL);
  expect(readBytes(workspace, REL).equals(bytes)).toBe(true);
  expect(mtime(workspace, REL)).toBe(time);
});

test("test_palette_drag_adds_node_and_validates", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const canvas = await openGraph(page, REL);
  // 팔레트: 시안 분류 묶음, 검색
  const palette = page.getByRole("tree", { name: "노드 팔레트" });
  await expect(palette.getByRole("group", { name: "창" })).toBeVisible();
  await expect(palette.locator('[data-node-type="core.window.attach"]')).toBeVisible();
  await page.getByRole("searchbox", { name: "노드 검색" }).fill("이미지 대기");
  await expect(palette.locator("[data-node-type]")).toHaveCount(1);
  // 필수 입력(target)이 없는 이미지 대기를 더하면 daemon 검증이 그 노드에 오류를 단다
  const box = (await canvas.boundingBox())!;
  const added = await dropFromPalette(page, canvas, "이미지 대기", "core.image.wait", { x: box.width / 2, y: box.height - 160 });
  await expect(nodeEl(page, added)).toBeVisible();
  await expect(nodeEl(page, added).locator('[data-part="node"]')).not.toHaveAttribute("data-errors", "0", { timeout: 10_000 });
  await page.getByRole("tab", { name: /문제/ }).click();
  await expect(page.getByRole("list", { name: "문제 목록" }).locator(`[data-node="${added}"]`).first()).toBeVisible();
  await expect(nodeEl(page, added)).toHaveClass(/selected/);
  await save(page, REL);
  const saved = readJson<Graph>(workspace, REL);
  // 기본값으로 in을 채우지 않는다
  expect(saved.nodes[added]).toEqual({ type: "core.image.wait", version: 1 });
});

test("test_connect_exec_and_data_pins", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const canvas = await openGraph(page, REL);
  const box = (await canvas.boundingBox())!;
  const wait = await dropFromPalette(page, canvas, "이미지 대기", "core.image.wait", { x: 200, y: box.height - 170 });
  const click = await dropFromPalette(page, canvas, "클릭", "core.input.click", { x: 520, y: box.height - 170 });
  // 흐름: 출구 → 흐름 입력. 이미 이어진 출구에 새로 이으면 바꾼다
  await connectPins(page, pin(page, "n_press_i", "x:done"), pin(page, wait, "in"));
  await connectPins(page, pin(page, wait, "x:found"), pin(page, click, "in"));
  // 데이터: match 출력 → 클릭의 match 입력 (기본값 있는 선택 입력이라 평소엔 숨어 있고 끄는 동안 보인다)
  await expect(pin(page, click, "i:match")).toHaveCount(0);
  await connectPins(page, pin(page, wait, "o:match"), pin(page, click, "i:match"), async () => {
    await expect(pin(page, click, "i:match")).toHaveAttribute("data-compat", "ok");
    // 흐름 핀·타입이 다른 핀은 흐리게
    await expect(pin(page, click, "in")).toHaveAttribute("data-compat", "no");
    await expect(pin(page, click, "i:point")).toHaveAttribute("data-compat", "no");
  });
  await expect(page.locator(`.react-flow__edge[data-id='d:${JSON.stringify([click, "match"])}']`)).toHaveCount(1);
  await expect(page.locator(`.react-flow__edge[data-id='x:${JSON.stringify(["n_press_i", "done"])}']`)).toHaveCount(1);
  // 끌기가 끝나면 호환 표시가 사라진다
  await expect(page.locator("[data-compat]")).toHaveCount(0);
  await save(page, REL);
  const saved = readJson<Graph>(workspace, REL);
  expect(saved.nodes.n_press_i.next).toEqual({ done: wait });
  expect(saved.nodes[wait].next).toEqual({ found: click });
  expect(saved.nodes[click].in).toEqual({ match: { $link: `${wait}.match` } });

  // 연결선을 골라 지운다
  const edgeId = `x:${JSON.stringify([wait, "found"])}`;
  const edge = page.locator(`.react-flow__edge[data-id='${edgeId}']`);
  await clickEdge(page, edgeId);
  await expect(edge).toHaveClass(/selected/);
  await page.keyboard.press("Delete");
  await expect(edge).toHaveCount(0);
  await save(page, REL);
  expect(readJson<Graph>(workspace, REL).nodes[wait].next).toBeUndefined();
});

test("test_conflict_banner_reload_and_overwrite", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const canvas = await openGraph(page, REL);
  const banner = page.getByRole("alert", { name: "저장 충돌" });
  const withTitle = (title: string) => {
    const v = readJson<Graph>(workspace, REL);
    (v.meta as { title: string }).title = title;
    return JSON.stringify(v, null, 2) + "\n";
  };

  // 편집하지 않은 문서: 밖에서 바뀌면 조용히 다시 연다 (충돌 띠 없이 기준 revision이 바뀜)
  const revision = await canvas.getAttribute("data-revision");
  writeFile(workspace, REL, withTitle("밖에서 바꿈 1"));
  await expect(canvas).not.toHaveAttribute("data-revision", revision!, { timeout: 10_000 });
  await expect(banner).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  await dragNode(page, "n_press_i", 40, 40);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  // dirty면 충돌 띠 → 디스크 버전 다시 열기 (편집 버림 확인)
  writeFile(workspace, REL, withTitle("밖에서 바꿈 2"));
  await expect(banner).toBeVisible({ timeout: 10_000 });
  await banner.getByRole("button", { name: "디스크 버전 다시 열기" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "다시 열기" }).click();
  await expect(banner).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  // 다시 편집 → 밖에서 바뀜 → 내 편집으로 덮어쓰기
  await dragNode(page, "n_press_i", 50, 30);
  writeFile(workspace, REL, withTitle("밖에서 바꿈 3"));
  await expect(banner).toBeVisible({ timeout: 10_000 });
  const disk3 = readJson<Graph>(workspace, REL);
  const before = Number(await canvas.getAttribute("data-saves"));
  await banner.getByRole("button", { name: "내 편집으로 덮어쓰기" }).click();
  await expect(canvas).toHaveAttribute("data-saves", String(before + 1));
  await expect(banner).toHaveCount(0);
  const saved = readJson<Graph>(workspace, REL);
  // 버퍼는 "밖에서 바꿈 2"를 다시 연 값 + 이동이다 (디스크의 3은 덮였다)
  expect((saved.meta as { title: string }).title).toBe("밖에서 바꿈 2");
  expect(saved.layout!.nodes!.n_press_i).not.toEqual(disk3.layout!.nodes!.n_press_i);
  // 충돌 띠의 닫기: 띠만 닫고 저장하면 다시 충돌
  await dragNode(page, "n_press_i", 10, 10);
  writeFile(workspace, REL, withTitle("밖에서 바꿈 4"));
  await expect(banner).toBeVisible({ timeout: 10_000 });
  await banner.getByRole("button", { name: "닫기" }).click();
  await expect(banner).toHaveCount(0);
  await page.keyboard.press("Control+S");
  await expect(banner).toBeVisible();
  expect((readJson<Graph>(workspace, REL).meta as { title: string }).title).toBe("밖에서 바꿈 4");
});

test("test_overwrite_after_external_change_with_reverted_buffer", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const original = readBytes(workspace, REL);
  const canvas = await openGraph(page, REL);
  await dragNode(page, "n_press_i", 40, 40);
  const b = readJson<Graph>(workspace, REL);
  (b.meta as { title: string }).title = "B";
  writeFile(workspace, REL, JSON.stringify(b));
  const banner = page.getByRole("alert", { name: "저장 충돌" });
  await expect(banner).toBeVisible({ timeout: 10_000 });
  // 버퍼를 연 값(A)으로 되돌린 뒤 덮어쓰기 → 디스크는 A (무쓰기 판정은 지금 디스크 B와 비교)
  await page.keyboard.press("Control+Z");
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  await banner.getByRole("button", { name: "내 편집으로 덮어쓰기" }).click();
  await expect(banner).toHaveCount(0);
  await expect.poll(() => readBytes(workspace, REL).equals(original)).toBe(true);
});

test("test_new_test_graph_created_and_opened", async () => {
  s = await openEditor();
  const { page, workspace } = s;
  await page.getByRole("button", { name: "새 테스트" }).click();
  const dialog = page.getByRole("dialog", { name: "새 테스트" });
  await dialog.getByRole("textbox", { name: "이름" }).fill("새_검사");
  await dialog.getByRole("button", { name: "만들기" }).click();
  const REL = "tests/새_검사.graph.json";
  await expect(canvasOf(page, REL)).toHaveAttribute("data-status", "ready");
  await expect(tabOf(page, REL)).toHaveAttribute("aria-selected", "true");
  await expect(page.locator(".react-flow__node")).toHaveCount(1);
  const created = readJson<Graph>(workspace, REL);
  expect(created.kind).toBe("test");
  expect((created.meta as { title: string }).title).toBe("새_검사");
  await expect(page.getByRole("tree", { name: "워크스페이스 파일" }).locator(`[data-path="${REL}"]`)).toBeVisible();
  // 같은 이름은 거부하고 대화 상자에 이유를 보인다 (파일은 그대로)
  const bytes = readBytes(workspace, REL);
  await page.getByRole("button", { name: "새 테스트" }).click();
  await dialog.getByRole("textbox", { name: "이름" }).fill("새_검사");
  await dialog.getByRole("button", { name: "만들기" }).click();
  await expect(dialog.getByRole("alert")).toContainText("이미 있어요");
  await dialog.getByRole("button", { name: "취소" }).click();
  expect(readBytes(workspace, REL).equals(bytes)).toBe(true);
  // 새 서브그래프: 시작 → 출구
  await page.getByRole("button", { name: "새 서브그래프" }).click();
  const sub = page.getByRole("dialog", { name: "새 서브그래프" });
  await sub.getByRole("textbox", { name: "이름" }).fill("보조");
  await sub.getByRole("button", { name: "만들기" }).click();
  await expect(canvasOf(page, "subgraphs/보조.graph.json")).toHaveAttribute("data-status", "ready");
  expect(readJson<Graph>(workspace, "subgraphs/보조.graph.json").kind).toBe("subgraph");
});

test("test_close_dirty_prompts", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const bytes = readBytes(workspace, REL);
  await openGraph(page, REL);
  await dragNode(page, "n_press_i", 40, 40);
  const tab = tabOf(page, REL);
  await expect(tab).toHaveAttribute("data-dirty", "true");
  // 취소: 탭이 남는다
  await tab.getByRole("button", { name: /탭 닫기/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("저장할까요");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(tab).toHaveCount(1);
  // 저장 안 함: 닫히고 파일은 그대로
  await page.keyboard.press("Control+W");
  await dialog.getByRole("button", { name: "저장 안 함" }).click();
  await expect(tab).toHaveCount(0);
  expect(readBytes(workspace, REL).equals(bytes)).toBe(true);
  // 저장: 저장한 뒤 닫힌다
  await openGraph(page, REL);
  await dragNode(page, "n_press_i", 40, 40);
  await tab.getByRole("button", { name: /탭 닫기/ }).click();
  await dialog.getByRole("button", { name: "저장", exact: true }).click();
  await expect(tab).toHaveCount(0);
  await expect.poll(() => readBytes(workspace, REL).equals(bytes)).toBe(false);
  // 프로젝트 닫기도 저장 안 된 그래프를 묻는다
  await openGraph(page, REL);
  await dragNode(page, "n_press_i", 20, 20);
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "프로젝트 닫기" }).click();
  await expect(dialog).toContainText("저장하지 않은 그래프가 1개");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(tab).toHaveCount(1);
});

test("test_big_floats_unmodified_and_edited_save_real_path", async () => {
  const REL = "tests/numbers.graph.json";
  const OUT_OF_RANGE = "tests/out_of_range.graph.json";
  const bigInt = corpus("canonical").toString("utf8").replace(/\n}\n?$/, ',\n  "x_big": 9007199254740993\n}\n');
  s = await openEditor({ [REL]: corpus("numbers"), [OUT_OF_RANGE]: bigInt });
  const { page, workspace } = s;
  const bytes = readBytes(workspace, REL);
  const time = mtime(workspace, REL);
  const canvas = await openGraph(page, REL);
  await pause(50);
  // 무수정 저장: 바이트·mtime 그대로 (1e20 등이 렌더러 → 주 프로세스 → WebSocket → daemon을 지나도)
  await save(page, REL);
  expect(readBytes(workspace, REL).equals(bytes)).toBe(true);
  expect(mtime(workspace, REL)).toBe(time);
  // 다른 필드(좌표)를 고쳐 저장해도 큰 실수는 float로 남는다 (canonical 지수 표기)
  await dragNode(page, "n_entry", 30, 20);
  await save(page, REL);
  await expect(canvas).toHaveAttribute("data-dirty", "false");
  const pointers = [
    "/nodes/n_sink/in/big",
    "/nodes/n_sink/in/big_plus",
    "/nodes/n_sink/in/big_upper",
    "/nodes/n_sink/in/two_53_float",
    "/nodes/n_sink/in/big_digits",
    "/nodes/n_sink/config/big",
    "/nodes/n_sink/in/list/1",
    "/nodes/n_sink/in/max_safe",
    "/nodes/n_sink/in/min_safe",
  ];
  expect(pyTypes(filePath(workspace, REL), pointers)).toEqual({
    "/nodes/n_sink/in/big": "float",
    "/nodes/n_sink/in/big_plus": "float",
    "/nodes/n_sink/in/big_upper": "float",
    "/nodes/n_sink/in/two_53_float": "float",
    "/nodes/n_sink/in/big_digits": "float",
    "/nodes/n_sink/config/big": "float",
    "/nodes/n_sink/in/list/1": "float",
    "/nodes/n_sink/in/max_safe": "int",
    "/nodes/n_sink/in/min_safe": "int",
  });
  const text = readBytes(workspace, REL).toString("utf8");
  expect(text).toContain("1e+20");
  expect(text).toContain("9.007199254740992e+15");
  expect(text).toContain("1.2345678901234567e+19");
  // 실제 범위 밖 정수(파일의 9007199254740993 리터럴)는 열 때 거부된다. 파일은 그대로
  const outBytes = readBytes(workspace, OUT_OF_RANGE);
  const bad = await openGraph(page, OUT_OF_RANGE).catch(() => canvasOf(page, OUT_OF_RANGE));
  await expect(bad).toHaveAttribute("data-status", "error");
  await expect(bad.locator('[data-part="graph-error"]')).toBeVisible();
  expect(readBytes(workspace, OUT_OF_RANGE).equals(outBytes)).toBe(true);
});

test("test_daemon_killed_with_dirty_and_clean_tabs_recovers", async () => {
  test.setTimeout(150_000);
  const DIRTY = "tests/inventory_open.graph.json";
  const CLEAN = "tests/smoke_headless.graph.json";
  const CONFLICT = "subgraphs/enter_world.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  await openGraph(page, CLEAN);
  await openGraph(page, CONFLICT);
  await dragNode(page, "n_launch", 30, 30);
  await expect(canvasOf(page, CONFLICT)).toHaveAttribute("data-dirty", "true");
  const dirtyCanvas = await openGraph(page, DIRTY);
  await dragNode(page, "n_press_i", 40, 40);
  await expect(dirtyCanvas).toHaveAttribute("data-dirty", "true");

  await killDaemon(workspace);
  // daemon이 없는 동안 디스크를 바꾼다: clean 탭(다시 열림), dirty 탭(충돌 띠)
  const clean = readJson<Graph>(workspace, CLEAN);
  (clean.meta as { title: string }).title = "밖에서 바꾼 스모크";
  writeFile(workspace, CLEAN, JSON.stringify(clean, null, 2));
  const world = readJson<Graph>(workspace, CONFLICT);
  (world.meta as { title: string }).title = "밖에서 바꾼 월드";
  writeFile(workspace, CONFLICT, JSON.stringify(world, null, 2));

  await expect(page.locator('[data-part="statusbar"] [data-status]')).not.toHaveAttribute("data-status", "connected");
  await waitConnected(page, 60_000);

  // dirty 탭: 버퍼·실행 취소 기록이 남고, 새 daemon에서 검증·저장이 된다
  await expect(dirtyCanvas).toHaveAttribute("data-dirty", "true");
  await page.keyboard.press("Control+Z");
  await expect(dirtyCanvas).toHaveAttribute("data-dirty", "false");
  await page.keyboard.press("Control+Y");
  await expect(dirtyCanvas).toHaveAttribute("data-dirty", "true");
  const box = (await dirtyCanvas.boundingBox())!;
  const added = await dropFromPalette(page, dirtyCanvas, "이미지 대기", "core.image.wait", { x: box.width / 2, y: box.height - 160 });
  await expect(nodeEl(page, added).locator('[data-part="node"]')).not.toHaveAttribute("data-errors", "0", { timeout: 10_000 });
  await save(page, DIRTY);
  const saved = readJson<Graph>(workspace, DIRTY);
  expect(saved.nodes[added]).toEqual({ type: "core.image.wait", version: 1 });
  expect(saved.layout!.nodes!.n_press_i).not.toEqual({ x: 280, y: 0 });

  // clean 탭은 디스크 값으로 다시 열렸다 (충돌 띠 없음)
  await page.locator(`[role="tab"][data-path="${CLEAN}"] button`).first().click();
  await expect(canvasOf(page, CLEAN)).toHaveAttribute("data-dirty", "false");
  await expect(page.getByRole("alert", { name: "저장 충돌" })).toHaveCount(0);
  await save(page, CLEAN);
  expect((readJson<Graph>(workspace, CLEAN).meta as { title: string }).title).toBe("밖에서 바꾼 스모크");

  // 그 사이 디스크가 바뀐 dirty 탭은 충돌 띠 → 덮어쓰기로 해결
  await page.locator(`[role="tab"][data-path="${CONFLICT}"] button`).first().click();
  const banner = page.getByRole("alert", { name: "저장 충돌" });
  await expect(banner).toBeVisible();
  await banner.getByRole("button", { name: "내 편집으로 덮어쓰기" }).click();
  await expect(banner).toHaveCount(0);
  await expect(canvasOf(page, CONFLICT)).toHaveAttribute("data-dirty", "false");
  const resolved = readJson<Graph>(workspace, CONFLICT);
  expect((resolved.meta as { title: string }).title).toBe("월드 접속");
  expect(resolved.layout!.nodes!.n_launch).not.toEqual(world.layout!.nodes!.n_launch);
});

// ── 창 닫기·대화 상자 (T9 검수 1차 repro_T9_1_ui.spec.mts) ─────────────────────

test("test_window_close_asks_then_cancel_or_save_all", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const bytes = readBytes(workspace, REL);
  const canvas = await openGraph(page, REL);
  await dragNode(page, "n_press_i", 45, 35);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  // 창 X: 저장 확인이 뜬다. 취소하면 창과 편집이 그대로
  const closeButton = page.getByRole("button", { name: "닫기", exact: true });
  await closeButton.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("저장하지 않은 그래프가 1개");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).toHaveCount(0);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  expect(page.isClosed()).toBe(false);
  // 다시 X → 모두 저장: 저장한 뒤 창이 닫힌다
  const closed = page.waitForEvent("close");
  await closeButton.click();
  await dialog
    .getByRole("button", { name: "모두 저장" })
    .click()
    .catch(() => {});
  await closed;
  expect(readBytes(workspace, REL).equals(bytes)).toBe(false);
  expect(readJson<Graph>(workspace, REL).layout!.nodes!.n_press_i).not.toEqual({ x: 280, y: 0 });
});

test("test_quit_menu_discard_closes_without_saving", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page, workspace } = s;
  const bytes = readBytes(workspace, REL);
  const canvas = await openGraph(page, REL);
  await dragNode(page, "n_press_i", 45, 35);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  // 파일 > 끝내기도 같은 확인을 거친다. 저장 안 함 → 닫히고 파일은 그대로
  await page.getByRole("button", { name: "파일", exact: true }).click();
  await page.getByRole("menuitem", { name: "끝내기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("저장하지 않은 그래프가 1개");
  const closed = page.waitForEvent("close");
  // 누르자마자 창이 닫혀 click의 뒤처리가 "페이지 닫힘"으로 끝날 수 있다: 닫힘 이벤트로 판정한다
  await dialog
    .getByRole("button", { name: "저장 안 함" })
    .click()
    .catch(() => {});
  await closed;
  expect(readBytes(workspace, REL).equals(bytes)).toBe(true);
});

test("test_clean_window_closes_without_prompt", async () => {
  s = await openEditor();
  const { page } = s;
  await openGraph(page, "tests/inventory_open.graph.json");
  const closed = page.waitForEvent("close");
  await page
    .getByRole("button", { name: "닫기", exact: true })
    .click()
    .catch(() => {});
  await closed;
});

test("test_dialog_blocks_background_keyboard_edits", async () => {
  const REL = "tests/inventory_open.graph.json";
  s = await openEditor();
  const { page } = s;
  const canvas = await openGraph(page, REL);
  await dragNode(page, "n_press_i", 45, 35);
  await selectOnly(page, "n_press_i");
  await page.keyboard.press("Control+W");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  // 대화 상자가 떠 있는 동안 Delete·Backspace·실행 취소·다시 실행·저장·Tab은 뒤쪽 그래프에 닿지 않는다
  for (const key of ["Delete", "Backspace", "Control+Z", "Control+Y", "Control+S", "Tab", "Tab", "Tab", "Tab", "Delete"]) {
    await page.keyboard.press(key);
  }
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => document.querySelector('[role="dialog"]')?.contains(document.activeElement) ?? false)).toBe(true);
  await expect(nodeEl(page, "n_press_i")).toHaveCount(1);
  await expect(canvas).toHaveAttribute("data-saves", "0");
  await dialog.getByRole("button", { name: "취소" }).click();
  await expect(dialog).toHaveCount(0);
  // 취소 뒤: 노드와 편집(dirty·실행 취소 하나)이 그대로
  await expect(nodeEl(page, "n_press_i")).toHaveCount(1);
  await expect(canvas).toHaveAttribute("data-dirty", "true");
  await page.keyboard.press("Control+Z");
  await expect(canvas).toHaveAttribute("data-dirty", "false");
});
