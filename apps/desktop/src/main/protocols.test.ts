// kbplugin:// 위젯 처리기 (M6 계획 3.10): 그 플러그인 ui 폴더 파일만, CSP·CORS 머리, 하위 프레임 이동 규칙
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import { pluginResponse } from "./protocols";
import {
  frameNavigationAllowed,
  isWidgetShellUrl,
  resolvePluginUrl,
  widgetCsp,
  widgetHostDir,
  widgetUrl,
  type WidgetHost,
} from "./security";
import { WidgetHosts, widgetHostsFrom } from "./widgets";

const A = "sample-0123456789ab";
const B = "other-ba9876543210";
const NONCE = "0123456789abcdef0123456789abcdef";
const SHELL = widgetUrl(A, "sample.color", NONCE);

describe("kbplugin", () => {
  let tmp: string;
  let ws: string;
  let hostA: WidgetHost;
  let hostB: WidgetHost;

  beforeAll(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kb-kbplugin-"));
    ws = path.join(tmp, "작업 공간");
    const envs = path.join(ws, ".kookabug", "plugins", "envs");
    const site = (env: string) => path.join(envs, env, "Lib", "site-packages");
    const uiA = path.join(site("shared-0123456789ab-aaaaaaaa"), "kookabug_plugin_sample", "ui");
    const uiB = path.join(site("iso-other-ba9876543210-bbbbbbbb"), "other_pkg", "ui");
    for (const d of [path.join(uiA, "lib"), uiB, path.join(tmp, "outside")]) fs.mkdirSync(d, { recursive: true });
    fs.writeFileSync(path.join(uiA, "index.js"), "export {};");
    fs.writeFileSync(path.join(uiA, "lib", "a.mjs"), "export const a = 1;");
    fs.writeFileSync(path.join(uiA, "style.css"), "body{}");
    fs.writeFileSync(path.join(uiA, "icon.svg"), "<svg/>");
    fs.writeFileSync(path.join(uiA, "secret.txt"), "no");
    fs.writeFileSync(path.join(uiA, "page.html"), "<p>no</p>");
    fs.writeFileSync(path.join(path.dirname(uiA), "__init__.py"), "x = 1");
    fs.writeFileSync(path.join(uiB, "index.js"), "export const b = 2;");
    fs.writeFileSync(path.join(tmp, "outside", "evil.js"), "evil()");
    // 관리자 권한 없이 만들 수 있는 정션: ui 폴더 안에서 밖(다른 플러그인 ui·레포 밖)을 가리킨다
    fs.symlinkSync(path.join(tmp, "outside"), path.join(uiA, "escape"), "junction");
    fs.symlinkSync(uiB, path.join(uiA, "neighbor"), "junction");
    const resolved = (rel: string) => widgetHostDir(ws, rel)!;
    hostA = { host: A, ...resolved(path.relative(ws, uiA).split(path.sep).join("/")) };
    hostB = { host: B, ...resolved(path.relative(ws, uiB).split(path.sep).join("/")) };
  });

  afterAll(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  const lookup = (h: string) => (h === A ? hostA : h === B ? hostB : null);

  test("kbplugin serves only own ui folder", async () => {
    // 껍데기와 자기 자원
    expect(resolvePluginUrl(SHELL, lookup)).toEqual({ ok: true, kind: "shell", host: A });
    const index = resolvePluginUrl(`kbplugin://${A}/index.js`, lookup);
    expect(index.ok && index.kind === "file" && fs.readFileSync(index.file, "utf8")).toBe("export {};");
    expect(index.ok && index.kind === "file" && index.contentType).toBe("text/javascript; charset=utf-8");
    expect(resolvePluginUrl(`kbplugin://${A}/lib/a.mjs`, lookup).ok).toBe(true);
    expect(resolvePluginUrl(`kbplugin://${A}/style.css`, lookup).ok).toBe(true);
    expect(resolvePluginUrl(`kbplugin://${A}/icon.svg`, lookup).ok).toBe(true);
    // 다른 호스트는 그 플러그인 ui 폴더 (A 폴더 파일이 아니다)
    const b = resolvePluginUrl(`kbplugin://${B}/index.js`, lookup);
    expect(b.ok && b.kind === "file" && fs.readFileSync(b.file, "utf8")).toBe("export const b = 2;");

    const rejected: [string, string][] = [
      // .. (그대로·퍼센트·역슬래시)
      [`kbplugin://${A}/../__init__.py`, "outside"],
      [`kbplugin://${A}/lib/../../__init__.py`, "outside"],
      [`kbplugin://${A}/..%2F__init__.py`, "outside"],
      [`kbplugin://${A}/%2e%2e/__init__.py`, "outside"],
      [`kbplugin://${A}/lib%5C..%5C..%5C__init__.py`, "outside"],
      // 절대 경로·드라이브
      [`kbplugin://${A}/${encodeURIComponent(path.join(tmp, "outside", "evil.js"))}`, "outside"],
      [`kbplugin://${A}/C:%5CWindows%5Cx.js`, "outside"],
      [`kbplugin://${A}//C:/Windows/x.js`, "outside"],
      // 심볼릭 링크·정션 (밖·다른 플러그인 ui 폴더)
      [`kbplugin://${A}/escape/evil.js`, "link"],
      [`kbplugin://${A}/neighbor/index.js`, "link"],
      // 모르는 호스트(잠금에 없거나 환경 준비 안 됨)·호스트 모양
      [`kbplugin://nobody-0123456789ab/index.js`, "unknown_host"],
      [`kbplugin://Sample/index.js`, "bad_url"],
      // '_'가 든 호스트는 CSP 소스가 될 수 없다 (ID의 '_'는 '-'로 바꾼 호스트를 쓴다)
      [`kbplugin://widget_probe-0123456789ab/index.js`, "bad_url"],
      [`kbplugin://${A}`, "bad_url"],
      // 확장자 (html·txt·py 없음)
      [`kbplugin://${A}/page.html`, "not_allowed"],
      [`kbplugin://${A}/secret.txt`, "not_allowed"],
      [`kbplugin://${A}/missing.js`, "not_found"],
      // 자원에는 쿼리 없음
      [`kbplugin://${A}/index.js?x=1`, "bad_url"],
      // 껍데기는 위젯·세션 모양이 맞을 때만
      [`kbplugin://${A}/__widget.html`, "bad_url"],
      [`kbplugin://${A}/__widget.html?w=sample.color&s=short`, "bad_url"],
      [`kbplugin://${A}/__widget.html?w=../x&s=${NONCE}`, "bad_url"],
      ["kbimg://ws/x.png", "bad_url"],
    ];
    for (const [url, reason] of rejected) {
      expect(resolvePluginUrl(url, lookup), url).toEqual({ ok: false, reason });
    }

    // 처리기 응답: 그 호스트 CSP·CORS null·nosniff. 표에 없는 호스트는 404
    const hosts = new WidgetHosts({ list: async () => ({ plugins: [] }), root: () => ws });
    (hosts as unknown as { lookup: (h: string) => Promise<WidgetHost | null> }).lookup = async (h) => lookup(h);
    const req = (url: string) => ({ url }) as Request;
    const shell = await pluginResponse(req(SHELL), hosts);
    expect(shell.status).toBe(200);
    expect(shell.headers.get("content-security-policy")).toBe(widgetCsp(A));
    expect(shell.headers.get("access-control-allow-origin")).toBe("null");
    expect(shell.headers.get("x-content-type-options")).toBe("nosniff");
    expect(await shell.text()).toContain('<script type="module" src="index.js"></script>');
    const js = await pluginResponse(req(`kbplugin://${A}/index.js`), hosts);
    expect(js.status).toBe(200);
    expect(js.headers.get("content-type")).toBe("text/javascript; charset=utf-8");
    expect(js.headers.get("content-security-policy")).toBe(widgetCsp(A));
    expect(await js.text()).toBe("export {};");
    expect((await pluginResponse(req(`kbplugin://${A}/escape/evil.js`), hosts)).status).toBe(404);
    expect((await pluginResponse(req("kbplugin://nobody-0123456789ab/index.js"), hosts)).status).toBe(404);
  });

  test("widget csp has no network, no other plugin, framed by app only", () => {
    const csp = widgetCsp(A);
    const d = new Map(csp.split(";").map((x) => x.trim().split(/\s+/)).map(([k, ...v]) => [k, v]));
    expect(d.get("default-src")).toEqual(["'none'"]);
    expect(d.has("connect-src")).toBe(false);
    expect(d.get("script-src")).toEqual([`kbplugin://${A}`]);
    expect(d.get("style-src")).toEqual([`kbplugin://${A}`, "'unsafe-inline'"]);
    expect(d.get("img-src")).toEqual([`kbplugin://${A}`, "data:"]);
    expect(d.get("font-src")).toEqual([`kbplugin://${A}`]);
    expect(d.get("base-uri")).toEqual(["'none'"]);
    expect(d.get("form-action")).toEqual(["'none'"]);
    expect(d.get("frame-ancestors")).toEqual(["app:"]);
    expect(csp).not.toContain("unsafe-eval");
    expect(csp).not.toContain(B);
  });

  test("host table comes from ready plugins under envs only", () => {
    const list = {
      plugins: [
        { env_status: "ready", ui: { host: A, path: ".kookabug/plugins/envs/shared-x/Lib/site-packages/p/ui" } },
        { env_status: "missing", ui: { host: B, path: ".kookabug/plugins/envs/iso-y/Lib/site-packages/q/ui" } },
        { env_status: "ready", ui: { host: "evil-000000000000", path: "../outside" } },
        { env_status: "ready", ui: { host: "evil-111111111111", path: ".kookabug/plugins/../../x/y/z" } },
        { env_status: "ready", ui: { host: "evil-222222222222", path: "C:/Windows/System32/a/b" } },
        { env_status: "ready" },
      ],
    };
    const table = widgetHostsFrom(list, ws);
    expect([...table.keys()]).toEqual([A]);
    expect(table.get(A)!.dir).toBe(path.join(ws, ".kookabug", "plugins", "envs", "shared-x", "Lib", "site-packages", "p", "ui"));
    expect(widgetHostsFrom(null, ws).size).toBe(0);
  });
});

// B6 검수 High: 준비가 철회된 환경의 위젯 자원을 캐시로 계속 주지 않는다
describe("widget host check", () => {
  const ready = { plugins: [{ env_status: "ready", ui: { host: A, path: ".kookabug/plugins/envs/shared-x/Lib/site-packages/p/ui" } }] };
  const broken = { plugins: [{ env_status: "broken", ui: null }] };

  test("every request asks the daemon again (no cache across requests)", async () => {
    let current: unknown = ready;
    let calls = 0;
    const hosts = new WidgetHosts({ root: () => "C:/ws", list: async () => (calls++, current) });
    expect((await hosts.lookup(A))?.host).toBe(A);
    // 알림 없이 환경이 깨짐으로 바뀌어도 다음 자원 요청은 거부한다
    current = broken;
    expect(await hosts.lookup(A)).toBeNull();
    expect(calls).toBe(2);
    // 확인 실패(연결 없음)·워크스페이스 없음은 거부
    const down = new WidgetHosts({ root: () => "C:/ws", list: async () => Promise.reject(new Error("끊김")) });
    expect(await down.lookup(A)).toBeNull();
    expect(await new WidgetHosts({ root: () => null, list: async () => ready }).lookup(A)).toBeNull();
  });

  test("an answer that started before invalidate() is not used", async () => {
    // 첫 응답(준비됨)은 무효화 뒤에 도착한다 → 버리고 다시 묻는다 → 깨짐 → 거부
    const answers: { resolve(v: unknown): void }[] = [];
    const hosts = new WidgetHosts({
      root: () => "C:/ws",
      list: () => new Promise((resolve) => answers.push({ resolve })),
    });
    const pending = hosts.lookup(A);
    await Promise.resolve();
    hosts.invalidate();
    answers[0].resolve(ready);
    await new Promise((r) => setTimeout(r, 0));
    expect(answers).toHaveLength(2);
    answers[1].resolve(broken);
    expect(await pending).toBeNull();

    // 워크스페이스가 확인 도중 바뀌어도 그 응답은 쓰지 않는다
    let root = "C:/ws";
    const moved: { resolve(v: unknown): void }[] = [];
    const other = new WidgetHosts({ root: () => root, list: () => new Promise((resolve) => moved.push({ resolve })) });
    const p2 = other.lookup(A);
    await Promise.resolve();
    root = "C:/other";
    moved[0].resolve(ready);
    await new Promise((r) => setTimeout(r, 0));
    moved[1].resolve({ plugins: [] });
    expect(await p2).toBeNull();

    // 무효화가 끝없이 겹치면 거부한다 (열린 쪽으로 실패하지 않음)
    const busy = new WidgetHosts({
      root: () => "C:/ws",
      list: async () => {
        busy.invalidate();
        return ready;
      },
    });
    expect(await busy.lookup(A)).toBeNull();
  });
});

describe("widget frame navigation", () => {
  const base = { isMainFrame: false, url: SHELL, frameUrl: "about:blank", parentUrl: "app://app/index.html", initiatorUrl: "app://app/index.html" };

  test("only the app's first load of a widget shell is allowed", () => {
    expect(isWidgetShellUrl(SHELL)).toBe(true);
    expect(frameNavigationAllowed(base)).toBe(true);
    expect(frameNavigationAllowed({ ...base, frameUrl: "" })).toBe(true);
    for (const nav of [
      // 위젯의 자기 재탐색 (이미 실린 프레임)
      { ...base, frameUrl: SHELL, initiatorUrl: SHELL },
      { ...base, frameUrl: SHELL },
      // 다른 주소
      { ...base, url: "https://example.com/" },
      { ...base, url: `kbplugin://${A}/index.js` },
      { ...base, url: "app://app/index.html" },
      { ...base, url: "about:blank" },
      // 앱 문서가 아닌 부모·시작자 (위젯 안 하위 프레임), 알 수 없는 프레임
      { ...base, parentUrl: SHELL },
      { ...base, initiatorUrl: SHELL },
      { ...base, initiatorUrl: null },
      { ...base, frameUrl: null },
      // 렌더러가 시작한 주 프레임 이동
      { ...base, isMainFrame: true },
    ]) {
      expect(frameNavigationAllowed(nav), JSON.stringify(nav)).toBe(false);
    }
  });
});
