// Electron 주 프로세스: 창, 보안 기본값, app://·kbimg:// 프로토콜, IPC 다리, daemon 관리자 (M2 계획 2.3·2.10)
import fs from "node:fs";
import path from "node:path";
import { wireStringify } from "@kookabug/schema";
import { app, BrowserWindow, dialog, ipcMain, nativeTheme, session, shell } from "electron";
import type { OpenResult, OutputLine, ThemeMode, ThemeState } from "../preload/bridge";
import { locateCli } from "./cli-locate";
import { CloseGuard } from "./close-guard";
import { DaemonManager, nodeDeps, parseExtraArgs, sameWorkspacePath } from "./daemon";
import { exportRun } from "./dialogs";
import { installE2EHooks, ResponseDelays } from "./e2e-hooks";
import { createNotificationForwarder, createRpcHandler, type DaemonCall } from "./ipc";
import { APP_CHANNEL, checkAppAction, checkSender, EVENT_CHANNEL, IpcGuardError, RPC_CHANNEL } from "./ipc-guard";
import { handleProtocols, registerSchemes } from "./protocols";
import { APP_ORIGIN, isExternalOpenAllowed, lockedWebPreferences } from "./security";
import { checkWorkspaceFolder, isThemeMode, Settings } from "./settings";
import { parseSmokeArgs, runSmoke, type SmokeArgs, withDeadline } from "./smoke";

/** 빌드가 정한다 (scripts/build-options.mjs): 배포 빌드는 false라 E2E 훅 분기가 번들에서 빠진다 */
declare const __KOOKABUG_E2E_HOOKS__: boolean;

const RENDERER_ROOT = path.join(__dirname, "..", "renderer");
const PRELOAD = path.join(__dirname, "..", "preload", "preload.cjs");
// 개발 모드: dist/main → 레포 루트 (CLI는 레포 .venv)
const REPO_ROOT = path.resolve(__dirname, "..", "..", "..", "..");
const OUTPUT_MAX = 500;
// 창 배경 (첫 칠하기 전 깜빡임 방지): 시안 --kb-bg
const WINDOW_BG = { dark: "#1F1F1F", light: "#FFFFFF" } as const;

// 검사·여러 사본 실행용: 사용자 데이터 폴더(단일 인스턴스 잠금 범위)를 바꾼다
const userDataDir = app.commandLine.getSwitchValue("user-data-dir");
if (userDataDir) app.setPath("userData", path.resolve(userDataDir));

registerSchemes();

let mainWindow: BrowserWindow | null = null;
const output: OutputLine[] = [];
// 설치본 스모크 (smoke.ts): 창 없이 daemon 붙기·열기·무수정 저장을 하고 끝난다. 단일 인스턴스 잠금을 잡지 않는다
const smokeArgs = parseSmokeArgs(process.argv);

if (smokeArgs !== null) {
  void app.whenReady().then(() => startSmoke(smokeArgs));
} else if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    if (mainWindow === null) return;
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
  });
  app.on("web-contents-created", (_event, contents) => lockContents(contents));
  app.on("window-all-closed", () => app.quit());
  void app.whenReady().then(start);
}

function lockContents(contents: Electron.WebContents): void {
  contents.on("will-navigate", (event) => event.preventDefault());
  contents.on("will-redirect", (event) => event.preventDefault());
  contents.on("will-attach-webview", (event) => event.preventDefault());
  contents.setWindowOpenHandler(({ url }) => {
    if (isExternalOpenAllowed(url)) void shell.openExternal(url);
    return { action: "deny" };
  });
}

function cliLocation() {
  return locateCli({
    env: process.env,
    packaged: app.isPackaged,
    installDir: path.dirname(process.execPath),
    repoRoot: REPO_ROOT,
    exists: (f) => fs.existsSync(f),
  });
}

async function startSmoke(args: SmokeArgs): Promise<void> {
  const manager = new DaemonManager(
    nodeDeps({
      client: { kind: "ui", name: "Kookabug", version: app.getVersion() },
      locateCli: cliLocation,
      extraArgs: parseExtraArgs(process.env.KOOKABUG_DAEMON_ARGS),
    }),
    {
      state: () => {},
      notification: () => {},
      log: (level, message) => console.log(`[${level}] ${message}`),
    },
  );
  const result = await withDeadline(runSmoke(args, manager));
  const text = JSON.stringify({ ...result, workspace: args.workspace, graph: args.graph });
  console.log(text);
  if (args.report !== null) {
    try {
      fs.writeFileSync(args.report, text + "\n", "utf8");
    } catch (err) {
      console.error(`스모크 결과를 쓰지 못했다: ${(err as Error).message}`);
    }
  }
  app.exit(result.code);
}

function send(name: string, data: unknown): void {
  if (mainWindow !== null && !mainWindow.isDestroyed()) mainWindow.webContents.send(EVENT_CHANNEL, name, data);
}

function start(): void {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
  ses.setDevicePermissionHandler(() => false);

  const settings = new Settings(app.getPath("userData"));
  nativeTheme.themeSource = settings.theme;
  const themeState = (): ThemeState => ({ mode: settings.theme, dark: nativeTheme.shouldUseDarkColors });

  const forward = createNotificationForwarder(send);
  const manager = new DaemonManager(
    nodeDeps({
      client: { kind: "ui", name: "Kookabug", version: app.getVersion() },
      locateCli: cliLocation,
      extraArgs: parseExtraArgs(process.env.KOOKABUG_DAEMON_ARGS),
    }),
    {
      state: (state) => send("daemon.state", state),
      notification: (method, params) => forward(method, params),
      log: (level, message) => {
        const line: OutputLine = { time: new Date().toISOString(), level, message };
        output.push(line);
        if (output.length > OUTPUT_MAX) output.splice(0, output.length - OUTPUT_MAX);
        send("daemon.log", line);
      },
    },
  );

  let daemonCall: DaemonCall = (method, params, text) => manager.call(method, params, text);
  // E2E 검사 전용 훅 (e2e-hooks.ts): 배포 빌드에서는 이 분기가 통째로 빠지고, 패키징된 앱에서는 켜지지 않는다
  if (__KOOKABUG_E2E_HOOKS__) {
    const delays = new ResponseDelays();
    const installed = installE2EHooks(globalThis, {
      packaged: app.isPackaged,
      env: process.env,
      hooks: {
        dropDaemonConnection: () => manager.dropConnection(),
        delayResponses: (method, delaysMs) => delays.set(method, delaysMs),
      },
    });
    if (installed) {
      const direct = daemonCall;
      daemonCall = async (method, params, text) => {
        const result = await direct(method, params, text);
        const wait = delays.next(method);
        if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
        return result;
      };
    }
  }

  handleProtocols(RENDERER_ROOT, () => manager.root);

  const rpc = createRpcHandler(daemonCall);
  ipcMain.handle(RPC_CHANNEL, (event, method: unknown, params: unknown) => {
    guardSender(event);
    return rpc(method, params);
  });

  const openWorkspace = (dir: string): OpenResult => {
    const root = path.resolve(dir);
    const check = checkWorkspaceFolder(root);
    if (check !== "ok") return { ok: false, reason: check, path: root };
    settings.addRecent(root);
    // 이미 연결된 같은 프로젝트를 다시 고르면 연결을 끊지 않는다
    const same = manager.root !== null && sameWorkspacePath(manager.root, root);
    if (!(same && manager.state.status === "connected")) void manager.open(root);
    return { ok: true, root, name: path.basename(root) };
  };

  const actions: Record<string, (...args: unknown[]) => unknown> = {
    async openFolder() {
      const win = mainWindow;
      const options: Electron.OpenDialogOptions = { title: "프로젝트 열기", properties: ["openDirectory"] };
      const picked = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options);
      if (picked.canceled || picked.filePaths.length === 0) return { ok: false, reason: "canceled" };
      return openWorkspace(picked.filePaths[0]);
    },
    openRecent(dir) {
      if (typeof dir !== "string" || dir === "") throw new IpcGuardError("경로가 문자열이 아니다");
      return openWorkspace(dir);
    },
    recent: () => settings.recent(),
    closeWorkspace: () => manager.detach(),
    themeGet: () => themeState(),
    themeSet(mode) {
      if (!isThemeMode(mode)) throw new IpcGuardError(`모르는 테마: ${String(mode)}`);
      settings.theme = mode;
      nativeTheme.themeSource = mode as ThemeMode;
      return themeState();
    },
    debugToolbarGet: () => settings.debugToolbarX,
    debugToolbarSet(x) {
      if (typeof x !== "number" || !Number.isFinite(x) || Math.abs(x) > 100_000) {
        throw new IpcGuardError("debugToolbarSet 인자가 유한한 수가 아니다");
      }
      settings.debugToolbarX = x;
    },
    daemonState: () => manager.state,
    daemonLog: () => output.slice(),
    daemonRetry: () => manager.retry(),
    daemonRestart: () => manager.restartDaemon(),
    windowControl(action) {
      const win = mainWindow;
      if (win === null) return;
      if (action === "minimize") win.minimize();
      else if (action === "maximize") {
        if (win.isMaximized()) win.unmaximize();
        else win.maximize();
      } else if (action === "close") win.close();
      else throw new IpcGuardError(`모르는 창 동작: ${String(action)}`);
    },
    windowState: () => ({ maximized: mainWindow?.isMaximized() ?? false }),
    closeGuard(on) {
      if (typeof on !== "boolean") throw new IpcGuardError("closeGuard 인자가 boolean이 아니다");
      closeGuard.arm(on);
    },
    closeAnswer(ok) {
      if (typeof ok !== "boolean") throw new IpcGuardError("closeAnswer 인자가 boolean이 아니다");
      closeGuard.answer(ok);
    },
    exportRun(runId) {
      if (typeof runId !== "string") throw new IpcGuardError("exportRun 인자가 문자열이 아니다");
      return exportRun(runId, {
        async pickSave(name) {
          const win = mainWindow;
          const options: Electron.SaveDialogOptions = {
            title: "분석 번들 내보내기",
            defaultPath: path.join(app.getPath("downloads"), name),
            filters: [{ name: "zip", extensions: ["zip"] }],
          };
          const picked = win ? await dialog.showSaveDialog(win, options) : await dialog.showSaveDialog(options);
          return picked.canceled || !picked.filePath ? null : picked.filePath;
        },
        call: (method, params) => daemonCall(method, params, wireStringify(params)),
      });
    },
  };
  // 창 닫기 확인 (close-guard.ts): 저장 안 된 그래프가 있으면 렌더러가 저장·버림·취소를 묻는다
  const closeGuard = new CloseGuard({
    ask: () => send("app.closeRequested", {}),
    close: () => mainWindow?.close(),
  });
  ipcMain.handle(APP_CHANNEL, (event, action: unknown, ...args: unknown[]) => {
    guardSender(event);
    return actions[checkAppAction(action)](...args);
  });

  const theme = () => (nativeTheme.shouldUseDarkColors ? "dark" : "light");
  mainWindow = new BrowserWindow({
    title: "Kookabug",
    width: 1440,
    height: 900,
    minWidth: 960,
    minHeight: 600,
    // 시안 타이틀 바(메뉴·명령 검색·창 버튼)를 그대로 그린다 (2.10 "창")
    frame: false,
    backgroundColor: WINDOW_BG[theme()],
    webPreferences: lockedWebPreferences(PRELOAD),
  });
  const win = mainWindow;
  const windowState = () => send("window.state", { maximized: win.isMaximized() });
  win.on("maximize", windowState);
  win.on("unmaximize", windowState);
  nativeTheme.on("updated", () => {
    if (win.isDestroyed()) return;
    win.setBackgroundColor(WINDOW_BG[theme()]);
    send("theme.state", themeState());
  });
  win.on("close", (event) => {
    if (closeGuard.onClose()) event.preventDefault();
  });
  // 렌더러가 다시 읽히거나 죽으면 확인 경로가 없다: 붙일 때까지 막지 않는다
  win.webContents.on("did-start-navigation", (details) => {
    if (details.isMainFrame && !details.isSameDocument) closeGuard.rendererGone();
  });
  win.webContents.on("render-process-gone", () => closeGuard.rendererGone());
  win.on("closed", () => {
    mainWindow = null;
    // daemon은 남는다 (UI를 꺼도 daemon과 실행은 계속된다). 연결만 놓는다
    manager.detach();
  });
  void win.loadURL(`${APP_ORIGIN}/index.html`);
}

function guardSender(event: Electron.IpcMainInvokeEvent): void {
  const main = mainWindow?.webContents.mainFrame ?? null;
  try {
    checkSender(event.senderFrame, main, APP_ORIGIN);
  } catch (err) {
    if (err instanceof IpcGuardError) console.warn(`IPC 거부: ${err.message}`);
    throw err;
  }
}
