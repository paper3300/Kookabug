// T1 스모크: 고른 Electron·Playwright 짝으로 창 띄우기·렌더러 평가·스크린샷과 보안 기본값
// (M2 계획 2.2 "같이 고정", 2.10)
import fs from "node:fs";
import path from "node:path";
import { expect, test, type ElectronApplication, type Page } from "@playwright/test";
import { launchApp, REPO_BUILD } from "./helpers/app";

let app: ElectronApplication;
let page: Page;
let userData: string;

test.beforeEach(async () => {
  ({ app, userData } = await launchApp());
  page = await app.firstWindow();
  await page.waitForLoadState("domcontentloaded");
});

test.afterEach(async () => {
  await app?.close();
  fs.rmSync(userData, { recursive: true, force: true });
});

test("test_app_window_opens_with_title", async () => {
  await expect(page).toHaveTitle("Kookabug");
  expect(page.url()).toBe("app://app/index.html");
  expect(app.windows()).toHaveLength(1);
  // 빈 화면은 시안 배경색 (다크 #1F1F1F 또는 라이트 #FFFFFF, Windows 설정을 따름)
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe(theme === "dark" ? "rgb(31, 31, 31)" : "rgb(255, 255, 255)");
  // CSP는 응답 헤더로 온다: 인라인 스크립트가 막힌다
  const inlineRan = await page.evaluate(async () => {
    const s = document.createElement("script");
    s.textContent = "window.__inline = 1";
    document.body.append(s);
    await new Promise((r) => setTimeout(r, 50));
    return (window as unknown as { __inline?: number }).__inline === 1;
  });
  expect(inlineRan).toBe(false);
  // 렌더러는 소켓을 열 수 없다 (connect-src 'none')
  const fetched = await page.evaluate(() =>
    fetch("http://127.0.0.1:9/").then(
      () => "ok",
      () => "blocked",
    ),
  );
  expect(fetched).toBe("blocked");
});

test("test_renderer_has_no_node_globals", async () => {
  const globals = await page.evaluate(() => ({
    require: typeof (globalThis as Record<string, unknown>).require,
    process: typeof (globalThis as Record<string, unknown>).process,
    module: typeof (globalThis as Record<string, unknown>).module,
    Buffer: typeof (globalThis as Record<string, unknown>).Buffer,
    bridge: Object.keys(window.kookabug).sort(),
  }));
  expect(globals).toEqual({
    require: "undefined",
    process: "undefined",
    module: "undefined",
    Buffer: "undefined",
    bridge: ["app", "on", "rpc"],
  });
  // 내부 메서드는 렌더러에서 부를 수 없다
  const hello = await page.evaluate(() =>
    window.kookabug.rpc("session.hello", {}).then(
      () => "ok",
      (e: Error) => e.message,
    ),
  );
  expect(hello).toContain("허용되지 않은 메서드");
});

test("test_navigation_and_window_open_blocked", async () => {
  // https 링크만 기본 브라우저로 넘긴다. 검사에서는 실제로 열지 않게 바꿔 둔다
  await app.evaluate(({ shell }) => {
    const opened: string[] = [];
    (globalThis as Record<string, unknown>).__opened = opened;
    shell.openExternal = async (url: string) => {
      opened.push(url);
    };
  });
  const results = await page.evaluate(() => [
    window.open("http://127.0.0.1:9/") === null,
    window.open("https://example.com/") === null,
    window.open("app://app/index.html") === null,
  ]);
  expect(results).toEqual([true, true, true]);
  expect(app.windows()).toHaveLength(1);
  const opened = await app.evaluate(() => (globalThis as Record<string, unknown>).__opened);
  expect(opened).toEqual(["https://example.com/"]);

  await page.evaluate(() => {
    location.href = "https://example.com/";
  });
  await page.waitForTimeout(500);
  expect(page.url()).toBe("app://app/index.html");
  await page.evaluate(() => {
    location.href = "file:///C:/Windows/win.ini";
  });
  await page.waitForTimeout(500);
  expect(page.url()).toBe("app://app/index.html");
  expect(app.windows()).toHaveLength(1);
});

test("test_permission_requests_denied", async () => {
  const result = await page.evaluate(async () => {
    const notification = await Notification.requestPermission();
    const geo = await new Promise<number | string>((resolve) =>
      navigator.geolocation.getCurrentPosition(
        () => resolve("granted"),
        (err) => resolve(err.code),
        { timeout: 5000 },
      ),
    );
    const media = await navigator.mediaDevices.getUserMedia({ audio: true }).then(
      () => "granted",
      (err: Error) => err.name,
    );
    const query = (await navigator.permissions.query({ name: "notifications" })).state;
    return { notification, geo, media, query };
  });
  expect(result.notification).toBe("denied");
  expect(result.geo).toBe(1); // PERMISSION_DENIED
  expect(result.media).not.toBe("granted");
  expect(result.query).toBe("denied");
});

test("test_screenshot_written", async () => {
  const out = path.join(REPO_BUILD, "e2e", "smoke.png");
  fs.rmSync(out, { force: true });
  await page.screenshot({ path: out });
  const png = fs.readFileSync(out);
  expect(png.subarray(0, 8)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]));
  const viewport = await page.evaluate(() => [window.innerWidth, window.innerHeight]);
  // IHDR 너비·높이 = 창 내용 크기 (deviceScaleFactor는 화면 배율을 따른다)
  const dpr = await page.evaluate(() => window.devicePixelRatio);
  expect(png.readUInt32BE(16)).toBe(Math.round(viewport[0] * dpr));
  expect(png.readUInt32BE(20)).toBe(Math.round(viewport[1] * dpr));
});

test("test_iframe_cannot_call_ipc", async () => {
  // 하위 프레임에는 preload가 들어가지 않는다 (nodeIntegrationInSubFrames: false)
  const inFrame = await page.evaluate(async () => {
    const frame = document.createElement("iframe");
    frame.src = "app://app/index.html";
    document.body.append(frame);
    await new Promise((r) => frame.addEventListener("load", r, { once: true }));
    try {
      const w = frame.contentWindow as (Window & { kookabug?: unknown }) | null;
      return { bridge: typeof w?.kookabug, require: typeof (w as unknown as { require?: unknown }).require };
    } catch {
      // M6: 하위 프레임 이동은 위젯 껍데기 처음 적재만 허용(will-frame-navigate) — app:// 문서를 싣지 못해 다른 출처(오류 문서)가 된다
      return { bridge: "blocked", require: "blocked" };
    }
  });
  expect([
    { bridge: "undefined", require: "undefined" },
    { bridge: "blocked", require: "blocked" },
  ]).toContainEqual(inFrame);

  // 주 프로세스 검사: 실제 하위 프레임(WebFrameMain)을 발신자로 넣으면 IPC 처리기가 거부한다
  const verdict = await app.evaluate(async ({ BrowserWindow, ipcMain }) => {
    const handlers = (ipcMain as unknown as { _invokeHandlers?: Map<string, Function> })._invokeHandlers;
    const handler = handlers?.get("kb:rpc");
    if (!handler) return "no-handler";
    const main = BrowserWindow.getAllWindows()[0].webContents.mainFrame;
    const sub = main.frames[0];
    if (!sub) return "no-subframe";
    const call = async (senderFrame: unknown) => {
      try {
        // 처리기는 daemon 오류를 봉투로 돌려준다 (ipc.ts)
        const reply = (await handler({ senderFrame }, "graph.open", { path: "x" })) as {
          ok: boolean;
          error?: { message: string };
        };
        return reply.ok ? "accepted" : `rejected: ${reply.error?.message}`;
      } catch (err) {
        return String((err as Error).message);
      }
    };
    return { sub: await call(sub), main: await call(main) };
  });
  expect(verdict).toEqual({
    sub: expect.stringContaining("주 프레임이 아닌"),
    // 주 프레임은 검사를 지나 daemon 단계에 닿는다 (워크스페이스를 열지 않아 연결 없음)
    main: "rejected: daemon에 연결되지 않았다",
  });
});
