// 플러그인 UI 확장 (M6 계획 3.10·B6): 인스펙터 config 칸의 위젯이 샌드박스 iframe(불투명 출처, 플러그인마다 다른
// kbplugin:// 호스트)에서 ES 모듈로 실리고 값을 고친다. 자기 프레임 이동은 막히고 재적재면 세션이 끝나 기본 편집기로,
// 다른 플러그인 자원·네트워크는 막히고, 실행 중에는 읽기 전용이다. 실제 daemon·uv·venv, 로컬 인덱스(네트워크 없음)
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { closeApp } from "./helpers/app";
import { cleanupWorkspace } from "./helpers/daemon";
import { canvasOf, readJson, save } from "./helpers/editor";
import {
  openPluginApp,
  startWorld,
  stopWorld,
  verifyPlugins,
  type PluginSession,
  type PluginWorld,
} from "./helpers/plugins";
import { toolbar } from "./helpers/run";
import {
  configField,
  focusApp,
  liveWidgetFrame,
  NONCE_ZERO,
  openWidgetNode,
  PROBE_GRAPH,
  WIDGET_GRAPH,
  widgetBox,
  widgetFrame,
  widgetWorkspace,
  type WidgetWorkspace,
} from "./helpers/widgets";

let world: PluginWorld | null = null;
let wws: WidgetWorkspace | null = null;
let s: PluginSession | null = null;
let server: http.Server | null = null;
let hits = 0;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(600_000);
  world = await startWorld();
  // fetch 탐침이 두드릴 로컬 서버: 위젯 CSP가 막으면 요청이 하나도 오지 않는다
  server = http.createServer((_req, res) => {
    hits += 1;
    res.writeHead(200, { "Access-Control-Allow-Origin": "*" });
    res.end("leak");
  });
  await new Promise<void>((r) => server!.listen(0, "127.0.0.1", r));
  const port = (server.address() as AddressInfo).port;
  wws = widgetWorkspace(world, { fetch: `http://127.0.0.1:${port}/leak` });
});

test.afterAll(async () => {
  if (wws !== null) await cleanupWorkspace(wws.ws);
  await new Promise((r) => (server === null ? r(null) : server.close(r)));
  await stopWorld(world);
  world = null;
});

test.afterEach(async () => {
  if (s !== null) {
    await closeApp(s.app);
    fs.rmSync(s.userData, { recursive: true, force: true });
  }
  s = null;
});

function ww(): WidgetWorkspace {
  if (wws === null) throw new Error("워크스페이스가 없다");
  return wws;
}

async function open(): Promise<Page> {
  if (world === null) throw new Error("세계가 없다");
  s = await openPluginApp(world, ww().ws);
  return s.page;
}

/** 초점을 앱 문서로 돌린 뒤 Ctrl+S (초점이 위젯 iframe에 있으면 키가 위젯으로 간다) */
async function saveGraph(page: Page, graph = WIDGET_GRAPH): Promise<void> {
  await focusApp(page);
  await save(page, graph);
}

/** 탐침 위젯이 config에 써 넣은 값: 앱이 받아들였으면 문서가 바뀐다 → 저장해서 파일로 본다 */
async function probeResult(page: Page, node: string, expected: string): Promise<void> {
  await expect(canvasOf(page, PROBE_GRAPH)).toHaveAttribute("data-dirty", "true", { timeout: 30_000 });
  await saveGraph(page, PROBE_GRAPH);
  const graph = readJson<{ nodes: Record<string, { config?: { result?: string } }> }>(ww().ws, PROBE_GRAPH);
  expect(graph.nodes[node].config?.result).toBe(expected);
}

test("es module widget loads and edits config", async () => {
  test.setTimeout(180_000);
  const page = await open();
  await openWidgetNode(page, "n_color");
  const box = widgetBox(page, "sample.color");
  await expect(box).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  // 플러그인마다 다른 호스트·세션 nonce, 샌드박스 = 스크립트만 (같은 출처 없음)
  const iframe = box.locator("iframe");
  await expect(iframe).toHaveAttribute("sandbox", "allow-scripts");
  const src = (await iframe.getAttribute("src")) ?? "";
  expect(src).toMatch(new RegExp(`^kbplugin://${ww().hosts.sample}/__widget\\.html\\?w=sample\\.color&s=[0-9a-f]{32}$`));
  // 살아 있는 위젯 프레임에는 앱 다리·Node·프로세스가 없다
  const live = await liveWidgetFrame(page, "sample.color");
  expect(
    await live.evaluate(() => {
      const g = window as unknown as Record<string, unknown>;
      return [typeof g.kookabug, typeof g.require, typeof g.process];
    }),
  ).toEqual(["undefined", "undefined", "undefined"]);
  // ES 모듈(index.js → ./kookabug-ui.js)이 실려 init 값을 그렸다
  const frame = widgetFrame(page, "sample.color");
  const text = frame.getByRole("textbox", { name: "색 코드" });
  await expect(text).toHaveValue("#3366ff");

  // 위젯에서 고침 → 기존 편집 경로(되돌리기·저장)
  await text.fill("#22AA66");
  await text.press("Enter");
  await expect(canvasOf(page, WIDGET_GRAPH)).toHaveAttribute("data-dirty", "true");
  await saveGraph(page);
  expect(readJson<{ nodes: { n_color: { config: { color: string } } } }>(ww().ws, WIDGET_GRAPH).nodes.n_color.config.color).toBe(
    "#22aa66",
  );
  // 되돌리기 → 같은 세션의 위젯이 값 알림을 받아 다시 그린다
  await focusApp(page);
  await page.keyboard.press("Control+Z");
  await expect(text).toHaveValue("#3366ff");
  await expect(box).toHaveAttribute("data-ready", "true");
  // 스와치 누르기
  await frame.locator('button[data-color="#e01b24"]').click();
  await expect(text).toHaveValue("#e01b24");
  await saveGraph(page);
  expect(readJson<{ nodes: { n_color: { config: { color: string } } } }>(ww().ws, WIDGET_GRAPH).nodes.n_color.config.color).toBe(
    "#e01b24",
  );
  // 상세 탭에 위젯 목록
  await page.locator('[data-part="node-plugin"]').click();
  await expect(page.locator('[data-part="plugin-widgets"]')).toContainText("sample.color");
});

test("self navigation blocked and session ends", async () => {
  test.setTimeout(180_000);
  const page = await open();
  const seen: string[] = [];
  page.on("framenavigated", (f) => seen.push(f.url()));
  await openWidgetNode(page, "n_nav", PROBE_GRAPH);
  // 탐침: 자기 프레임을 다른 세션 주소로 옮기려 함 → 막혀 문서가 살아 있어 "nav:alive"를 보냄
  //       → 문서를 다시 써 load가 한 번 더 남 → 세션 끝 → 기본 편집기. 옛 세션의 "nav:after-reload"는 버려진다
  const fallback = configField(page, "result").locator('[data-part="widget-fallback"]');
  await expect(fallback).toHaveAttribute("data-reason", "reloaded", { timeout: 20_000 });
  await expect(widgetBox(page, "widget_probe.nav")).toHaveCount(0);
  const input = configField(page, "result").getByRole("textbox", { name: "result" });
  await expect(input).toHaveValue("nav:alive");
  await page.waitForTimeout(1500);
  await expect(input).toHaveValue("nav:alive");
  // 위조 세션 주소로는 한 번도 이동하지 않았다
  expect(seen.filter((u) => u.includes(NONCE_ZERO))).toEqual([]);
  expect(page.frames().map((f) => f.url()).filter((u) => u.includes(NONCE_ZERO))).toEqual([]);
});

test("other plugin resource blocked", async () => {
  test.setTimeout(120_000);
  const page = await open();
  await openWidgetNode(page, "n_other", PROBE_GRAPH);
  await expect(widgetBox(page, "widget_probe.other")).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await probeResult(page, "n_other", "other:blocked");
});

test("fetch fails", async () => {
  test.setTimeout(120_000);
  const page = await open();
  await openWidgetNode(page, "n_fetch", PROBE_GRAPH);
  await expect(widgetBox(page, "widget_probe.fetch")).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await probeResult(page, "n_fetch", "fetch:blocked");
  expect(hits).toBe(0);
});

test("readOnly while running", async () => {
  test.setTimeout(180_000);
  const page = await open();
  await openWidgetNode(page, "n_color");
  const box = widgetBox(page, "sample.color");
  await expect(box).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  const frame = widgetFrame(page, "sample.color");
  const text = frame.getByRole("textbox", { name: "색 코드" });
  await expect(text).toBeEnabled();
  const before = await text.inputValue();

  await toolbar(page).getByRole("button", { name: "실행 F5" }).click();
  await expect(toolbar(page)).toHaveAttribute("data-phase", "running", { timeout: 60_000 });
  // 실행 중: 위젯이 읽기 전용을 받고, 위젯이 억지로 보낸 change도 버린다
  await expect(text).toBeDisabled();
  const iframe = await liveWidgetFrame(page, "sample.color");
  expect(iframe.url().startsWith(`kbplugin://${ww().hosts.sample}/`)).toBe(true);
  await iframe.evaluate(() => {
    const session = new URLSearchParams(location.search).get("s");
    window.parent.postMessage({ kb: "change", session, value: "#000000" }, "*");
  });
  await page.waitForTimeout(1000);
  await expect(text).toHaveValue(before);
  await expect(canvasOf(page, WIDGET_GRAPH)).toHaveAttribute("data-dirty", "false");
});

// B6 검수 High (검수자 재현 review_B6_1_browser를 차단 단언으로): 실제 verify로 환경이 깨짐이 되면 이미 뜬 위젯의
// 새 모듈 요청도 거부하고, daemon 알림으로 인스펙터가 기본 편집기로 돌아간다. 환경을 깨므로 이 파일의 마지막 검사다
test("env turned broken by verify refuses new widget requests", async () => {
  test.setTimeout(240_000);
  const page = await open();
  await openWidgetNode(page, "n_color");
  const live = await liveWidgetFrame(page, "sample.color");
  expect(live.url().startsWith(`kbplugin://${ww().hosts.sample}/`)).toBe(true);
  // 깨짐 뒤 요청은 처리기가 곧바로 거부하지만(요청마다 daemon plugins.list), 인스펙터가 위젯을 내리는 것은
  // daemon 감시 tick(약 1초)의 plugins.changed 뒤라, 진짜 위젯 프레임은 느린 러너에서 import 전에 떼어질 수
  // 있다(CI ci_1 "Frame was detached"). 그래서 같은 껍데기 주소를 앱 문서가 미리 띄워 둔 프레임 하나를
  // 고정해 두고(React가 지우지 않음) "깨짐 전에 뜬 위젯 문서의 새 모듈 요청"을 그 프레임에서 본다
  const shell = live.url();
  await page.evaluate((src) => {
    const pinned = document.createElement("iframe");
    pinned.name = "kb-e2e-pinned-widget";
    pinned.setAttribute("sandbox", "allow-scripts");
    pinned.style.display = "none";
    pinned.src = src;
    document.body.appendChild(pinned);
  }, shell);
  await expect.poll(() => page.frames().some((f) => f.name() === "kb-e2e-pinned-widget" && f.url() === shell)).toBe(true);
  const frame = page.frames().find((f) => f.name() === "kb-e2e-pinned-widget")!;
  const importLate = (file: string) =>
    frame.evaluate(async (name) => {
      try {
        // 위젯 문서 기준 상대 주소 (검사 파일의 모듈이 아니다). 자원 주소에는 질의를 붙일 수 없어(처리기 bad_url)
        // 요청마다 다른 파일이다
        const late: string = `./${name}`;
        const m = (await import(late)) as { observed: string };
        return m.observed;
      } catch (e) {
        return `blocked:${String(e)}`;
      }
    }, file);
  const listed = (await page.evaluate(() => window.kookabug.rpc("plugins.list", {}))) as {
    plugins: { id: string; ui?: { path: string } }[];
  };
  const ui = path.join(ww().ws, listed.plugins.find((p) => p.id === "sample")!.ui!.path);
  // 환경 안 ui 폴더에 새 모듈을 더하고(환경 파일이 바뀜) 실제 verify → 깨짐 기록
  fs.writeFileSync(path.join(ui, "late.mjs"), 'export const observed = "served-after-broken";');
  fs.writeFileSync(path.join(ui, "before.mjs"), 'export const observed = "served-before-broken";');
  // 양성 대조: 깨짐 전에는 고정 프레임의 같은 종류 요청이 실제로 실린다 (거부가 고정 프레임 탓이 아님)
  expect(await importLate("before.mjs")).toBe("served-before-broken");
  const verified = verifyPlugins(world!, ww().ws);
  expect(verified.ok).toBe(false);
  expect(verified.environments.shared.status).toBe("broken");
  const after = (await page.evaluate(() => window.kookabug.rpc("plugins.list", {}))) as {
    plugins: { id: string; env_status: string; ui?: unknown }[];
  };
  const sample = after.plugins.find((p) => p.id === "sample")!;
  expect(sample.env_status).toBe("broken");
  expect(sample.ui).toBeUndefined();
  // daemon이 환경 상태 변화를 plugins.changed로 알려 인스펙터가 위젯을 내리고 기본 편집기로.
  // 느린 러너에서 실제로 생긴 순서(위젯이 먼저 내려감)를 일부러 만든 뒤 요청한다 — 순서에 기대지 않는다
  await expect(widgetBox(page, "sample.color")).toHaveCount(0, { timeout: 15_000 });
  await expect(configField(page, "color").getByRole("textbox", { name: "color" })).toHaveValue(/^#/);
  // 깨짐 전에 뜬 위젯 문서(고정 프레임)의, 깨짐 뒤 처음 하는 모듈 요청은 처리기가 거부한다
  expect(await importLate("late.mjs")).toMatch(/^blocked:/);
});
