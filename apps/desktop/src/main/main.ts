// Electron 주 프로세스: 창, 보안 기본값, app://·kbimg:// 프로토콜, IPC 다리 (M2 계획 2.10)
import path from "node:path";
import { pathToFileURL } from "node:url";
import { app, BrowserWindow, ipcMain, net, protocol, session, shell } from "electron";
import { checkRendererMethod, checkSender, IpcGuardError, RPC_CHANNEL } from "./ipc-guard";
import {
  APP_ORIGIN,
  APP_SCHEME,
  cspHeaderValue,
  isAppUrl,
  isExternalOpenAllowed,
  KBIMG_SCHEME,
  lockedWebPreferences,
  resolveAppFile,
  resolveKbimgPath,
} from "./security";

const RENDERER_ROOT = path.join(__dirname, "..", "renderer");
const PRELOAD = path.join(__dirname, "..", "preload", "preload.cjs");

// 검사·여러 사본 실행용: 사용자 데이터 폴더(단일 인스턴스 잠금 범위)를 바꾼다
const userDataDir = app.commandLine.getSwitchValue("user-data-dir");
if (userDataDir) app.setPath("userData", path.resolve(userDataDir));

protocol.registerSchemesAsPrivileged([
  { scheme: APP_SCHEME, privileges: { standard: true, secure: true, supportFetchAPI: true } },
  { scheme: KBIMG_SCHEME, privileges: { standard: true, secure: true } },
]);

// 열린 워크스페이스 루트. daemon 연결(T7)이 정한다
let workspaceRoot: string | null = null;
let mainWindow: BrowserWindow | null = null;

if (!app.requestSingleInstanceLock()) {
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

function start(): void {
  const ses = session.defaultSession;
  ses.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
  ses.setDevicePermissionHandler(() => false);

  protocol.handle(APP_SCHEME, serveApp);
  protocol.handle(KBIMG_SCHEME, serveKbimg);
  ipcMain.handle(RPC_CHANNEL, (event, method: unknown) => {
    guardSender(event);
    checkRendererMethod(method);
    // daemon 연결과 params 스키마 검사는 T7
    throw new Error("daemon에 연결되지 않았다");
  });

  mainWindow = new BrowserWindow({
    title: "Kookabug",
    width: 1440,
    height: 900,
    backgroundColor: "#1F1F1F",
    webPreferences: lockedWebPreferences(PRELOAD),
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
  });
  void mainWindow.loadURL(`${APP_ORIGIN}/index.html`);
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

async function serveApp(request: Request): Promise<Response> {
  const file = isAppUrl(request.url) ? resolveAppFile(request.url, RENDERER_ROOT) : null;
  if (file === null) return new Response("not found", { status: 404 });
  const res = await net.fetch(pathToFileURL(file).toString());
  const headers = new Headers(res.headers);
  headers.set("Content-Security-Policy", cspHeaderValue());
  headers.set("X-Content-Type-Options", "nosniff");
  return new Response(res.body, { status: res.status, headers });
}

async function serveKbimg(request: Request): Promise<Response> {
  const result = resolveKbimgPath(request.url, workspaceRoot);
  if (!result.ok) return new Response(result.reason, { status: 404 });
  return net.fetch(pathToFileURL(result.file).toString());
}
