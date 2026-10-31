// 캔버스 보기·검증 표시 (M2 계획 T8 완료 기준 e2e/canvas.spec.ts). 실제 daemon(레포 .venv)과 예제 워크스페이스 사본
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Locator, type Page } from "@playwright/test";
import { closeApp, launchApp, REPO_ROOT, setContentSize, settle, stubOpenDialog } from "./helpers/app";
import { cleanupWorkspace, copySampleWorkspace, waitConnected } from "./helpers/daemon";

const SIAN_MAIN = path.join(import.meta.dirname, "fixtures", "sian-main.graph.json");

let app: ElectronApplication;
let page: Page;
let userData: string;
let workspace: string | null = null;

test.afterEach(async () => {
  await closeApp(app);
  if (workspace !== null) await cleanupWorkspace(workspace);
  workspace = null;
  if (userData) fs.rmSync(userData, { recursive: true, force: true });
});

/** 워크스페이스 사본에 파일을 더한 뒤 연다 (더한 파일이 첫 트리에 보이게) */
async function openWorkspace(files: Record<string, string> = {}): Promise<string> {
  workspace = copySampleWorkspace();
  for (const [rel, text] of Object.entries(files)) {
    const file = path.join(workspace, ...rel.split("/"));
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, text);
  }
  ({ app, userData } = await launchApp());
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, workspace);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);
  return workspace;
}

/** 탐색기에서 연다. 폴더가 접혀 있으면 펼친다 */
async function openGraph(rel: string): Promise<Locator> {
  const tree = page.getByRole("tree", { name: "워크스페이스 파일" });
  const parts = rel.split("/");
  for (let i = 1; i < parts.length; i++) {
    const dir = tree.locator(`[data-path="${parts.slice(0, i).join("/")}"]`);
    if ((await dir.getAttribute("aria-expanded")) === "false") await dir.click();
  }
  await tree.locator(`[data-path="${rel}"]`).click();
  const canvas = page.locator(`[data-part="canvas"][data-path="${rel}"]`);
  await expect(canvas).toBeVisible();
  return canvas;
}

const nodeEl = (id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
/** 그려진 연결선 ID (React Flow가 data-id에 둔다) */
const renderedEdges = () =>
  page.$$eval(".react-flow__edge", (els) => els.map((e) => e.getAttribute("data-id") ?? "").sort());

/**
 * 코어 규칙 그대로의 연결 목록 (흐름 next, 데이터 $link. $literal 안은 보지 않는다). ID는 계약 형식:
 * 흐름 `x:` + JSON [노드, 출구], 데이터 `d:` + JSON [노드, 핀, …값 안 경로]
 */
function expectedEdges(value: { nodes: Record<string, { next?: Record<string, unknown>; in?: Record<string, unknown> }> }) {
  const ids = new Set(Object.keys(value.nodes));
  const out: string[] = [];
  const links = (v: unknown, where: (string | number)[], emit: (w: (string | number)[]) => void): void => {
    if (Array.isArray(v)) v.forEach((x, i) => links(x, [...where, i], emit));
    else if (typeof v === "object" && v !== null) {
      const o = v as Record<string, unknown>;
      const keys = Object.keys(o);
      if (keys.length === 1 && keys[0] === "$link") {
        const ref = o.$link;
        if (typeof ref === "string" && ids.has(ref.split(".")[0])) emit(where);
      } else if (!("$literal" in o)) keys.forEach((k) => links(o[k], [...where, k], emit));
    }
  };
  for (const [id, node] of Object.entries(value.nodes)) {
    for (const [exit, to] of Object.entries(node.next ?? {})) {
      if (typeof to === "string" && ids.has(to)) out.push(`x:${JSON.stringify([id, exit])}`);
    }
    for (const [pin, v] of Object.entries(node.in ?? {})) links(v, [], (w) => out.push(`d:${JSON.stringify([id, pin, ...w])}`));
  }
  return out.sort();
}

function readJson(rel: string): never {
  return JSON.parse(fs.readFileSync(path.join(workspace!, ...rel.split("/")), "utf8")) as never;
}

test("test_open_sample_graph_renders_all_nodes_and_edges", async () => {
  await openWorkspace();
  // 접힌 그룹이 없는 테스트 그래프: 노드·연결선이 다 있다
  await openGraph("tests/inventory_open.graph.json");
  const inventory = readJson("tests/inventory_open.graph.json") as { nodes: Record<string, never> };
  for (const id of Object.keys(inventory.nodes)) await expect(nodeEl(id), id).toBeVisible();
  const edges = expectedEdges(inventory);
  expect(edges.length).toBeGreaterThan(3);
  await expect.poll(renderedEdges).toEqual(edges);

  // 접힌 그룹이 있는 서브그래프: 접힌 동안 구성원은 그룹 하나, 펼치면 전부
  await openGraph("subgraphs/enter_world.graph.json");
  const world = readJson("subgraphs/enter_world.graph.json") as {
    nodes: Record<string, never>;
    layout: { collapsed: Record<string, { nodes: string[] }> };
  };
  const members = new Set(Object.values(world.layout.collapsed).flatMap((g) => g.nodes));
  expect(members.size).toBeGreaterThan(0);
  for (const id of Object.keys(world.nodes)) {
    if (members.has(id)) await expect(nodeEl(id), id).toHaveCount(0);
    else await expect(nodeEl(id), id).toBeVisible();
  }
  const group = page.locator('[data-part="group"]').first();
  await expect(group).toHaveAttribute("data-expanded", "false");
  await group.getByRole("button", { name: "펼치기" }).click();
  for (const id of Object.keys(world.nodes)) await expect(nodeEl(id), id).toBeVisible();
  await expect.poll(renderedEdges).toEqual(expectedEdges(world));
  // 노드 머리 = 노드 제목, 핀 손잡이가 있다
  await expect(nodeEl("n_wait_title").locator('[data-part="node-head"]')).toContainText("타이틀 대기");
  await expect(nodeEl("n_wait_title").locator('[data-pin="x:found"]')).toHaveCount(1);
  await expect(nodeEl("n_wait_title").locator('[data-pin="in"]')).toHaveCount(1);
  // 배열·객체 안쪽 $link는 연결선에 원소 위치를 쓴다 (예제에는 없어 시안 그래프로 본다)
});

test("test_validation_errors_shown_on_node_and_problems", async () => {
  // 없는 target을 가리키는 노드 하나 = 실행 전 검증 오류
  const broken = JSON.parse(fs.readFileSync(SIAN_MAIN, "utf8")) as {
    nodes: Record<string, { in: Record<string, unknown> }>;
  };
  broken.nodes.n_click.in.target = { $target: "targets/nope/missing.target.json" };
  await openWorkspace({ "tests/broken_target.graph.json": `${JSON.stringify(broken, null, 2)}\n` });
  await openGraph("tests/broken_target.graph.json");
  const node = nodeEl("n_click").locator('[data-part="node"]');
  await expect(node).toHaveAttribute("data-head", "error");
  await expect(node.locator('[data-part="node-status"]')).toContainText("오류");
  await expect(node.locator('[data-part="node-note"]')).toHaveAttribute("data-tone", "error");
  // 경고(연결 안 된 ok 출구)는 경고 표시
  await expect(nodeEl("n_report").locator('[data-part="node"]')).toHaveAttribute("data-head", "warn");
  // 문제 패널: 개수 배지와 줄 (오류가 먼저)
  const count = page.locator('[data-part="problem-count"]');
  await expect(count).toBeVisible();
  await page.getByRole("tab", { name: /문제/ }).click();
  const items = page.getByRole("list", { name: "문제 목록" }).getByRole("button");
  await expect(items.first()).toHaveAttribute("data-severity", "error");
  await expect(items.first()).toHaveAttribute("data-node", "n_click");
  expect(Number(await count.textContent())).toBe(await items.count());
  await expect(page.getByRole("list", { name: "문제 목록" }).locator('[data-node="n_report"][data-severity="warning"]')).toHaveCount(1);
});

test("test_click_problem_selects_node", async () => {
  await openWorkspace({ "tests/sian-main.graph.json": fs.readFileSync(SIAN_MAIN, "utf8") });
  const canvas = await openGraph("tests/sian-main.graph.json");
  await expect(nodeEl("n_report")).toBeVisible();
  // 화면을 멀리 옮겨 둔다 (빈 곳 끌기)
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + 40, box.y + box.height - 40);
  await page.mouse.down();
  await page.mouse.move(box.x + 40 - 900, box.y + box.height - 40 - 600, { steps: 8 });
  await page.mouse.up();
  await expect(nodeEl("n_report")).not.toBeInViewport();
  await page.getByRole("tab", { name: /문제/ }).click();
  await page.getByRole("list", { name: "문제 목록" }).locator('[data-node="n_report"]').click();
  await expect(nodeEl("n_report")).toHaveClass(/selected/);
  await expect(nodeEl("n_report")).toBeInViewport();
  // 화면 가운데 근처로 옮겨 온다
  await expect
    .poll(async () => {
      const n = (await nodeEl("n_report").boundingBox())!;
      const c = (await canvas.boundingBox())!;
      return Math.abs(n.x + n.width / 2 - (c.x + c.width / 2)) + Math.abs(n.y + n.height / 2 - (c.y + c.height / 2));
    })
    .toBeLessThan(40);
});

test("test_node_click_under_overlay_edge_selects_node", async () => {
  // 노드 위 층에 그린 뒤로 가는 연결선이 겹친 노드 머리 누르기를 가로채지 않는다 (T8 검수 2차)
  await openWorkspace({ "tests/sian-main.graph.json": fs.readFileSync(SIAN_MAIN, "utf8") });
  await openGraph("tests/sian-main.graph.json");
  await expect(page.locator(".react-flow__node")).toHaveCount(10);
  await expect(page.locator(".react-flow__edge.kb-edge-overlay").first()).toBeAttached();
  await settle(page);
  // 위 층 연결선 경로가 노드 머리 안쪽을 지나는 화면 점
  const hit = await page.evaluate(() => {
    const heads = [...document.querySelectorAll('[data-part="node-head"]')];
    for (const path of document.querySelectorAll<SVGPathElement>(".react-flow__edge.kb-edge-overlay .react-flow__edge-path")) {
      const matrix = path.getScreenCTM();
      if (matrix === null) continue;
      const len = path.getTotalLength();
      for (let d = 4; d < len - 4; d += 2) {
        const p = path.getPointAtLength(d).matrixTransform(matrix);
        for (const head of heads) {
          const r = head.getBoundingClientRect();
          if (p.x < r.left + 8 || p.x > r.right - 8 || p.y < r.top + 4 || p.y > r.bottom - 4) continue;
          return { x: p.x, y: p.y, node: head.closest(".react-flow__node")!.getAttribute("data-id")! };
        }
      }
    }
    return null;
  });
  expect(hit, "시안 그래프에서 위 층 연결선이 노드 머리를 지난다").not.toBeNull();
  // 그 점의 맨 위 요소가 연결선이 아니라 노드다
  const top = await page.evaluate(({ x, y }) => {
    const el = document.elementFromPoint(x, y);
    return { edge: el?.closest(".react-flow__edge") !== null, node: el?.closest(".react-flow__node")?.getAttribute("data-id") ?? null };
  }, hit!);
  expect(top).toEqual({ edge: false, node: hit!.node });
  await page.mouse.click(hit!.x, hit!.y);
  await expect(nodeEl(hit!.node)).toHaveClass(/selected/);
});

test("test_click_cross_file_problem_selects_node_in_collapsed_group", async () => {
  // 서브그래프의 접힌 그룹 안 노드에 오류를 만든다. 부모 테스트를 열면 그 진단이 부모 문서에서도 나온다
  const sub = "subgraphs/enter_world.graph.json";
  const root = copySampleWorkspace();
  workspace = root;
  const subFile = path.join(root, ...sub.split("/"));
  const graph = JSON.parse(fs.readFileSync(subFile, "utf8")) as { nodes: Record<string, { in: Record<string, unknown> }> };
  graph.nodes.n_click_login.in.target = { $target: "targets/review_missing.target.json" };
  fs.writeFileSync(subFile, `${JSON.stringify(graph, null, 2)}\n`);
  ({ app, userData } = await launchApp());
  page = await app.firstWindow();
  // 다시 그리기가 멈추지 않는 오류(React #185) 같은 렌더러 오류가 없어야 한다
  const pageErrors: string[] = [];
  page.on("pageerror", (e) => pageErrors.push(e.message));
  await page.waitForLoadState("domcontentloaded");
  await setContentSize(app, page, 1440, 900);
  await stubOpenDialog(app, root);
  await page.getByRole("button", { name: "프로젝트 열기" }).click();
  await waitConnected(page);

  const parent = "tests/inventory_open.graph.json";
  const issue = () =>
    page
      .getByRole("list", { name: "문제 목록" })
      .getByRole("button")
      .filter({ hasText: "review_missing" })
      .filter({ hasText: sub })
      .first();
  const target = nodeEl("n_click_login");
  const centered = async () => {
    const n = (await target.boundingBox())!;
    const c = (await page.locator(`[data-part="canvas"][data-path="${sub}"]`).boundingBox())!;
    return Math.abs(n.x + n.width / 2 - (c.x + c.width / 2)) + Math.abs(n.y + n.height / 2 - (c.y + c.height / 2));
  };

  // ① 서브그래프 탭이 아직 없다: 누르면 탭이 열리고 그룹을 펼쳐 그 노드를 고른다
  await openGraph(parent);
  await page.getByRole("tab", { name: /문제/ }).click();
  await issue().click();
  await expect(page.locator('[data-part="canvas"]')).toHaveAttribute("data-path", sub);
  await expect(page.locator('[data-part="tabs"] [role="tab"][aria-selected="true"]')).toContainText("SUB");
  await expect(page.locator('[data-group-id="grp_login"]')).toHaveAttribute("data-expanded", "true");
  await expect(target).toHaveClass(/selected/);
  await expect.poll(centered).toBeLessThan(40);

  // ② 이미 열린 탭: 그룹을 다시 접고 화면을 옮겨 둔 뒤 부모 탭에서 누른다
  await page.locator('[data-group-id="grp_login"]').getByRole("button", { name: "접기" }).click();
  await expect(target).toHaveCount(0);
  const box = (await page.locator('[data-part="canvas"]').boundingBox())!;
  await page.mouse.move(box.x + 40, box.y + box.height - 40);
  await page.mouse.down();
  await page.mouse.move(box.x + 40 - 900, box.y + box.height - 40 - 600, { steps: 8 });
  await page.mouse.up();
  await page.locator(`[data-part="tabs"] [data-path="${parent}"] button`).first().click();
  await expect(page.locator('[data-part="canvas"]')).toHaveAttribute("data-path", parent);
  await issue().click();
  await expect(page.locator('[data-part="canvas"]')).toHaveAttribute("data-path", sub);
  await expect(page.locator('[data-group-id="grp_login"]')).toHaveAttribute("data-expanded", "true");
  await expect(target).toHaveClass(/selected/);
  await expect.poll(centered).toBeLessThan(40);
  expect(pageErrors).toEqual([]);
});

test("test_unknown_plugin_node_rendered_marked", async () => {
  const source = fs.readFileSync(path.join(REPO_ROOT, "fixtures", "graph-corpus", "unknown-node.graph.json"), "utf8");
  await openWorkspace({ "tests/unknown_node.graph.json": source });
  await openGraph("tests/unknown_node.graph.json");
  const magic = nodeEl("n_magic").locator('[data-part="node"]');
  await expect(magic).toHaveAttribute("data-unknown", "true");
  await expect(magic.locator('[data-part="node-status"]')).toHaveText("모르는 노드");
  await expect(magic.locator('[data-part="node-head"]')).toContainText("acme.vision.magic");
  // 핀 = in 키, 출구 = next 키, 출력 = 다른 노드가 읽는 이름
  for (const pin of ["in", "i:region", "i:target", "x:found", "x:missing", "o:label", "o:reason"]) {
    await expect(magic.locator(`[data-pin="${pin}"]`), pin).toHaveCount(1);
  }
  await expect.poll(renderedEdges).toEqual(expectedEdges(JSON.parse(source)));
  // 설치되지 않은 플러그인 노드도 문제 패널에 나온다
  await page.getByRole("tab", { name: /문제/ }).click();
  await expect(page.getByRole("list", { name: "문제 목록" }).locator('[data-node="n_magic"]').first()).toBeVisible();
});

test("test_open_invalid_json_shows_error_view", async () => {
  await openWorkspace({ "tests/bad.graph.json": '{\n  "format": "kookabug.graph/0",\n  "nodes": {,}\n}\n' });
  const canvas = await openGraph("tests/bad.graph.json");
  const error = canvas.locator('[data-part="graph-error"]');
  await expect(error).toBeVisible();
  await expect(error).toHaveAttribute("data-kind", "invalid_json");
  await expect(error).toContainText("그래프를 열 수 없어요");
  await expect(error).toContainText("줄 3");
  await expect(canvas.locator(".react-flow")).toHaveCount(0);
});

test("test_open_does_not_mark_dirty", async () => {
  const root = await openWorkspace({ "tests/sian-main.graph.json": fs.readFileSync(SIAN_MAIN, "utf8") });
  // 마지막이 지금 탭 (접힌 그룹이 있는 서브그래프)
  const files = ["tests/sian-main.graph.json", "tests/inventory_open.graph.json", "subgraphs/enter_world.graph.json"];
  const before = files.map((rel) => {
    const file = path.join(root, ...rel.split("/"));
    return { rel, bytes: fs.readFileSync(file), mtime: fs.statSync(file).mtimeMs };
  });
  for (const rel of files) {
    const canvas = await openGraph(rel);
    await expect(canvas).toHaveAttribute("data-status", "ready");
    await expect(canvas).toHaveAttribute("data-dirty", "false");
  }
  // 보기 상태만 바꾼다: 그룹 펼치기·노드 고르기·줌
  await page.locator('[data-part="group"]').getByRole("button", { name: "펼치기" }).click();
  await nodeEl("n_launch").click();
  await expect(nodeEl("n_launch")).toHaveClass(/selected/);
  await page.getByRole("button", { name: "확대" }).click();
  // 좌표 없는 노드가 있어도 값에 쓰지 않는다 (예제 그래프 중 하나라도 좌표가 빠졌으면 자동 배치)
  // 검증 디바운스·폴링이 돌 시간을 준다
  await page.waitForTimeout(1500);
  await expect(page.locator('[data-part="canvas"]')).toHaveAttribute("data-dirty", "false");
  for (const { rel, bytes, mtime } of before) {
    const file = path.join(root, ...rel.split("/"));
    expect(fs.readFileSync(file).equals(bytes), rel).toBe(true);
    expect(fs.statSync(file).mtimeMs, rel).toBe(mtime);
  }
});
