// M6 완료 기준 인수 검사, 앱 쪽 (M6 계획 5장). 실제 Electron 앱 + 실제 daemon(레포 .venv)·uv·venv + 예제 워크스페이스
// 사본 + 로컬 인덱스·레포 밖 임시 git 레포(plugin_world.py — 네트워크 없음, 임시 uv 캐시). 다른 검사 모듈은 가져오지
// 않고 helpers만 쓴다.
//
// 1. 외부 레포의 샘플 플러그인을 앱 대화 상자로 설치(신뢰 카드) → 인스펙터 위젯으로 고친 노드가 든 그래프를 실행해 통과
// 3. 설치가 실패해도 목록·잠금·기존 그래프 실행이 그대로
// (엄격) 위젯 격리: ES 모듈 로딩, 네트워크 없음, 프레임 이동 없음(재적재면 세션 끝), 다른 플러그인 자원 없음, 비밀값
//        항목 위젯은 설치부터 거부, 실행 중 읽기 전용
//
// Python 쪽 인수는 python/kookabug_core/tests/acceptance/test_m6.py. 실제 공개 레포·PyPI·다른 PC·설치본 화면은
// Docs/verification/m6-manual.md
import { showActivity } from "./helpers/app";
import fs from "node:fs";
import http from "node:http";
import type { AddressInfo } from "node:net";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { canvasOf, openGraph, readJson, save, selectOnly } from "./helpers/editor";
import {
  closePluginApp,
  lockBytes,
  openPluginApp,
  pluginRow,
  pluginWorkspace,
  preinstall,
  previewSource,
  showPlugins,
  startWorld,
  stopWorld,
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
  widgetBox,
  widgetFrame,
  widgetWorkspace,
} from "./helpers/widgets";

const WAIT = 240_000;
const GRAPH = "tests/m6_widget.graph.json";

let world: PluginWorld | null = null;
let s: PluginSession | null = null;

test.describe.configure({ mode: "serial" });

test.beforeAll(async () => {
  test.setTimeout(300_000);
  world = await startWorld();
});

test.afterAll(async () => {
  await stopWorld(world);
  world = null;
});

test.afterEach(async () => {
  await closePluginApp(s);
  s = null;
});

function w(): PluginWorld {
  if (world === null) throw new Error("세계가 없다");
  return world;
}

/** 색 고르기(위젯으로 고칠 config) → 그 색이 기대값인지 비교 → 통과. 글자 뒤집기도 한 번 */
function writeGraph(ws: string, expectColor: string): void {
  const node = (type: string, extra: Record<string, unknown> = {}) => ({ type, version: 1, ...extra });
  const graph = {
    format: "kookabug.graph/0",
    kind: "test",
    meta: { title: "M6 인수 위젯" },
    plugins: { core: "0.1.0", sample: "0.1.0" },
    nodes: {
      n_entry: node("core.graph.entry", { next: { start: "n_color" } }),
      n_color: node("sample.color.pick", { title: "색", config: { color: "#3366ff" }, next: { done: "n_cmp" } }),
      n_cmp: node("core.assert.compare", {
        in: { a: { $link: "n_color.color" }, op: "==", b: expectColor },
        next: { ok: "n_cmp_rev" },
      }),
      n_rev: node("sample.text.reverse", { in: { text: "abc" } }),
      n_cmp_rev: node("core.assert.compare", { in: { a: { $link: "n_rev.text" }, op: "==", b: "cba" }, next: { ok: "n_pass" } }),
      n_pass: node("core.test.pass"),
    },
    layout: {
      nodes: {
        n_entry: { x: 0, y: 0 },
        n_color: { x: 280, y: 0 },
        n_cmp: { x: 560, y: 0 },
        n_rev: { x: 560, y: 200 },
        n_cmp_rev: { x: 840, y: 0 },
        n_pass: { x: 1120, y: 0 },
      },
    },
  };
  const file = path.join(ws, ...GRAPH.split("/"));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(graph, null, 2) + "\n");
}

async function runPasses(page: Page): Promise<void> {
  await focusApp(page);
  await toolbar(page).getByRole("button", { name: "실행 F5" }).click();
  await expect(page.locator('[data-part="run-result"]')).toHaveAttribute("data-verdict", "pass", { timeout: 120_000 });
}

test("install sample from git via dialog, run graph with widget-edited node", async () => {
  test.setTimeout(2 * WAIT);
  const ws = pluginWorkspace(w());
  writeGraph(ws, "#22aa66");
  s = await openPluginApp(w(), ws);
  const { page } = s;
  await showPlugins(page);
  // 레포 밖 로컬 git 레포(태그 v0.1.0, 스키마 파일 없음) → 미리보기 → 신뢰 카드 → 설치
  await previewSource(page, "Git 주소", w().git_repo, "v0.1.0");
  const trust = page.locator('[data-part="plugin-trust"]');
  await expect(trust).toContainText("이 플러그인은 내 PC에서 내 권한으로 실행돼요");
  expect(lockBytes(ws)).toBeNull(); // 신뢰 전에는 잠금도 환경도 없다
  await trust.getByRole("button", { name: "신뢰하고 설치" }).click();
  const ok = page.locator('[data-part="plugin-result-ok"]');
  await expect(ok).toBeVisible({ timeout: WAIT });
  await ok.getByRole("button", { name: "닫기" }).click();
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  const lock = JSON.parse(lockBytes(ws)!.toString("utf8")) as { plugins: { source: { kind: string; commit: string } }[] };
  expect(lock.plugins[0].source.kind).toBe("git");
  expect(lock.plugins[0].source.commit).toMatch(/^[0-9a-f]{40}$/);

  // 인스펙터 위젯(샌드박스 iframe, ES 모듈)으로 색을 고치고 저장
  await showActivity(page.getByRole("button", { name: "탐색기" }));
  await openGraph(page, GRAPH);
  await selectOnly(page, "n_color");
  const box = widgetBox(page, "sample.color");
  await expect(box).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
  await expect(box.locator("iframe")).toHaveAttribute("sandbox", "allow-scripts");
  await widgetFrame(page, "sample.color").locator('button[data-color="#22aa66"]').click();
  await expect(canvasOf(page, GRAPH)).toHaveAttribute("data-dirty", "true");
  await focusApp(page);
  await save(page, GRAPH);
  const saved = readJson<{ nodes: { n_color: { config: { color: string } } } }>(ws, GRAPH);
  expect(saved.nodes.n_color.config.color).toBe("#22aa66");

  // 실행: 설치된 환경의 워커가 위젯으로 고친 값을 출력한다 (비교 통과)
  await runPasses(page);
});

test("failed install leaves plugins and graph working", async () => {
  test.setTimeout(2 * WAIT);
  const ws = pluginWorkspace(w());
  preinstall(w(), ws, "sample");
  writeGraph(ws, "#3366ff");
  const before = lockBytes(ws);
  s = await openPluginApp(w(), ws);
  const { page } = s;
  await showPlugins(page);
  await previewSource(page, "wheel 파일·주소", w().wheels.broken_import);
  await page.locator('[data-part="plugin-trust"]').getByRole("button", { name: "신뢰하고 설치" }).click();
  const failed = page.locator('[data-part="plugin-result-failed"]');
  await expect(failed).toBeVisible({ timeout: WAIT });
  await expect(failed).toContainText("설치하지 못했어요. 기존 플러그인은 그대로예요.");
  await failed.getByRole("button", { name: "닫기" }).click();
  await expect(page.locator('[data-part="plugin-row"]')).toHaveCount(1);
  await expect(pluginRow(page, "sample")).toHaveAttribute("data-status", "ready");
  expect(lockBytes(ws)).toEqual(before);
  // 기존 그래프는 그대로 실행된다
  await showActivity(page.getByRole("button", { name: "탐색기" }));
  await openGraph(page, GRAPH);
  await runPasses(page);
});

test("widget sandboxed (module load, no network, no navigation, no other plugin, no secret fields, readOnly)", async () => {
  test.setTimeout(3 * WAIT);
  let hits = 0;
  const server = http.createServer((_req, res) => {
    hits += 1;
    res.writeHead(200, { "Access-Control-Allow-Origin": "*" });
    res.end("leak");
  });
  await new Promise<void>((r) => server.listen(0, "127.0.0.1", r));
  const port = (server.address() as AddressInfo).port;
  const wws = widgetWorkspace(w(), { fetch: `http://127.0.0.1:${port}/leak` });
  // 비밀값 항목에 위젯을 단 플러그인은 설치부터 거부된다 (앱도 마운트하지 않는다 — PluginWidget.test.tsx)
  expect(() => preinstall(w(), wws.ws, "widget_secret")).toThrow();
  try {
    s = await openPluginApp(w(), wws.ws);
    const { page } = s;
    const seen: string[] = [];
    page.on("framenavigated", (f) => seen.push(f.url()));

    // 탐침: 네트워크 · 다른 플러그인 모듈은 막히고, 자기 프레임 이동은 막히며 문서를 다시 쓰면 세션이 끝난다
    await openWidgetNode(page, "n_fetch", PROBE_GRAPH);
    await expect(widgetBox(page, "widget_probe.fetch")).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
    await expect(canvasOf(page, PROBE_GRAPH)).toHaveAttribute("data-dirty", "true", { timeout: 30_000 });
    await selectOnly(page, "n_other");
    await expect(widgetBox(page, "widget_probe.other")).toHaveAttribute("data-ready", "true", { timeout: 15_000 });
    await page.waitForTimeout(1500);
    await selectOnly(page, "n_nav");
    const fallback = configField(page, "result").locator('[data-part="widget-fallback"]');
    await expect(fallback).toHaveAttribute("data-reason", "reloaded", { timeout: 20_000 });
    await expect(configField(page, "result").getByRole("textbox", { name: "result" })).toHaveValue("nav:alive");
    await focusApp(page);
    await save(page, PROBE_GRAPH);
    const probes = readJson<{ nodes: Record<string, { config: { result: string } }> }>(wws.ws, PROBE_GRAPH).nodes;
    expect(probes.n_fetch.config.result).toBe("fetch:blocked");
    expect(probes.n_other.config.result).toBe("other:blocked");
    expect(probes.n_nav.config.result).toBe("nav:alive");
    expect(hits).toBe(0);
    expect(seen.filter((u) => u.includes(NONCE_ZERO))).toEqual([]);

    // ES 모듈 위젯이 플러그인마다 다른 호스트에서 실린다
    await openWidgetNode(page, "n_color");
    const live = await liveWidgetFrame(page, "sample.color");
    expect(live.url().startsWith(`kbplugin://${wws.hosts.sample}/__widget.html?`)).toBe(true);
    // 살아 있는 위젯에서 앱 다리·Node·프로세스에 닿을 길이 없다 (B7 검수 H2: 프레임이 없으면 실패)
    const reach = await live.evaluate(() => {
      const g = window as unknown as Record<string, unknown>;
      return [typeof g.kookabug, typeof g.require, typeof g.process];
    });
    expect(reach).toEqual(["undefined", "undefined", "undefined"]);

    // 실행 중 읽기 전용: 위젯 입력이 꺼지고 억지 change도 버린다
    const text = widgetFrame(page, "sample.color").getByRole("textbox", { name: "색 코드" });
    await expect(text).toBeEnabled();
    await focusApp(page);
    await toolbar(page).getByRole("button", { name: "실행 F5" }).click();
    await expect(toolbar(page)).toHaveAttribute("data-phase", "running", { timeout: 60_000 });
    await expect(text).toBeDisabled();
    await live.evaluate(() => {
      const session = new URLSearchParams(location.search).get("s");
      window.parent.postMessage({ kb: "change", session, value: "#000000" }, "*");
    });
    await page.waitForTimeout(1000);
    await expect(text).toHaveValue("#3366ff");
    await expect(canvasOf(page, "tests/widget.graph.json")).toHaveAttribute("data-dirty", "false");
  } finally {
    await new Promise((r) => server.close(r));
  }
});
