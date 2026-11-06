// 플러그인 위젯 E2E 도우미 (M6 B6): 예제 플러그인(색 위젯)과 위젯 탐침 픽스처를 미리 설치한 워크스페이스와,
// 색 고르기·탐침 노드가 있는 그래프. 탐침 config에는 시도할 주소를 넣어 둔다 (탐침 위젯이 결과를 값으로 써 넣는다)
import fs from "node:fs";
import path from "node:path";
import { expect, type FrameLocator, type Page } from "@playwright/test";
import { openGraph, selectOnly } from "./editor";
import { pluginWorkspace, preinstall, type PluginWorld } from "./plugins";

export const WIDGET_GRAPH = "tests/widget.graph.json";
export const PROBE_GRAPH = "tests/widget_probe.graph.json";
export const NONCE_ZERO = "0".repeat(32);

export interface WidgetWorkspace {
  ws: string;
  /** 위젯 호스트 `<id>-<지문12>` */
  hosts: { sample: string; widget_probe: string };
}

/** 두 플러그인을 설치하고 그래프를 쓴다. probe: 탐침 노드 config 값 (주소) */
export function widgetWorkspace(world: PluginWorld, probe: { fetch?: string } = {}): WidgetWorkspace {
  const ws = pluginWorkspace(world);
  preinstall(world, ws, "sample");
  preinstall(world, ws, "widget_probe");
  const lock = JSON.parse(fs.readFileSync(path.join(ws, "kookabug.lock"), "utf8")) as {
    plugins: { id: string; env: string }[];
    environments: Record<string, { fingerprint: string }>;
  };
  const host = (id: string) => {
    const entry = lock.plugins.find((p) => p.id === id)!;
    return `${id.replaceAll("_", "-")}-${lock.environments[entry.env].fingerprint.slice(0, 12)}`;
  };
  const hosts = { sample: host("sample"), widget_probe: host("widget_probe") };
  writeWidgetGraph(ws, {
    fetch: probe.fetch ?? "http://127.0.0.1:9/never",
    // 자기 껍데기를 다른 세션으로 다시 싣기 (막혀야 한다)
    nav: `kbplugin://${hosts.widget_probe}/__widget.html?w=widget_probe.nav&s=${NONCE_ZERO}`,
    // 다른 플러그인(예제)의 ES 모듈 (막혀야 한다)
    other: `kbplugin://${hosts.sample}/index.js`,
  });
  return { ws, hosts };
}

function writeGraph(ws: string, rel: string, graph: Record<string, unknown>): void {
  const file = path.join(ws, ...rel.split("/"));
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify({ format: "kookabug.graph/0", kind: "test", ...graph }, null, 2) + "\n");
}

const node = (type: string, extra: Record<string, unknown> = {}) => ({ type, version: 1, ...extra });

function writeWidgetGraph(ws: string, probe: { fetch: string; nav: string; other: string }): void {
  // 실행할 수 있는 그래프: 색 고르기 → 20초 기다림 → 통과 (실행 중 읽기 전용 검사)
  writeGraph(ws, WIDGET_GRAPH, {
    meta: { title: "위젯" },
    plugins: { core: "0.1.0", sample: "0.1.0" },
    nodes: {
      n_entry: node("core.graph.entry", { next: { start: "n_color" } }),
      n_color: node("sample.color.pick", { title: "색", config: { color: "#3366ff" }, next: { done: "n_wait" } }),
      n_wait: node("core.flow.delay", { in: { ms: 20000 }, next: { done: "n_pass" } }),
      n_pass: node("core.test.pass"),
    },
    layout: { nodes: { n_entry: { x: 0, y: 0 }, n_color: { x: 280, y: 0 }, n_wait: { x: 560, y: 0 }, n_pass: { x: 840, y: 0 } } },
  });
  // 탐침 노드만 (실행하지 않는다)
  writeGraph(ws, PROBE_GRAPH, {
    meta: { title: "위젯 탐침" },
    plugins: { widget_probe: "0.1.0" },
    nodes: {
      n_fetch: node("widget_probe.probe.fetch", { config: { result: probe.fetch } }),
      n_nav: node("widget_probe.probe.nav", { config: { result: probe.nav } }),
      n_other: node("widget_probe.probe.other", { config: { result: probe.other } }),
    },
    layout: { nodes: { n_fetch: { x: 0, y: 0 }, n_nav: { x: 280, y: 0 }, n_other: { x: 560, y: 0 } } },
  });
}

/** 그래프를 열고 그 노드를 고른다 (오른쪽 패널 속성) */
export async function openWidgetNode(page: Page, node: string, graph = WIDGET_GRAPH): Promise<void> {
  await openGraph(page, graph);
  await selectOnly(page, node);
  await expect(page.locator('[data-part="inspector-body"]')).toHaveAttribute("data-node", node);
}

export function widgetBox(page: Page, widget: string) {
  return page.locator(`[data-part="plugin-widget"][data-widget="${widget}"]`);
}

export function widgetFrame(page: Page, widget: string): FrameLocator {
  return widgetBox(page, widget).frameLocator("iframe");
}

/** 위젯 iframe에 간 키보드 초점을 앱 문서로 되돌린다 (Ctrl+S 등 앱 단축키) */
export async function focusApp(page: Page): Promise<void> {
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
}

/** 그 config 칸 (기본 편집기로 돌아갔을 때의 입력 상자 포함) */
export function configField(page: Page, name: string) {
  return page.locator(`[data-part="field"][data-field="config"][data-pin="${name}"]`);
}
