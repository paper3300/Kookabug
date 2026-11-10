// Electron 주 프로세스: 창, 보안 기본값, app://·kbimg:// 프로토콜, IPC 다리, daemon 관리자 (M2 계획 2.3·2.10)
import fs from "node:fs";
import path from "node:path";
import { wireStringify } from "@kookabug/schema";
import { app, BrowserWindow, dialog, globalShortcut, ipcMain, nativeTheme, session, shell } from "electron";
import type { OpenResult, OutputLine, ThemeMode, ThemeState } from "../preload/bridge";
import { AgentHost, AgentHostError, parseAgentOverride, type AgentSpecLite } from "./acp/host";
import { spawnAgent } from "./acp/spawn";
import { locateCli } from "./cli-locate";
import { CloseGuard } from "./close-guard";
import { DaemonManager, nodeDeps, parseExtraArgs, sameWorkspacePath } from "./daemon";
import { exportRun } from "./dialogs";
import { e2eHooksEnabled, installE2EHooks, ResponseDelays } from "./e2e-hooks";
import { createNotificationForwarder, createRpcHandler, type DaemonCall } from "./ipc";
import { JobRunner, JobsError, nodeExec, nodeSpawn } from "./jobs";
import { APP_CHANNEL, checkAppAction, checkJobArgs, checkSender, EVENT_CHANNEL, IpcGuardError, RPC_CHANNEL } from "./ipc-guard";
import { handleProtocols, registerSchemes } from "./protocols";
import { APP_ORIGIN, frameNavigationAllowed, isExternalOpenAllowed, lockedWebPreferences } from "./security";
import { WidgetHosts } from "./widgets";
import { checkWorkspaceFolder, isThemeMode, Settings } from "./settings";
import { guardRecorderCall, RECORDER_HOTKEYS, RecorderShortcuts, type ShortcutHost } from "./shortcuts";
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
  // 하위 프레임 (M6 3.10): 앱 문서가 새 위젯 iframe에 껍데기를 처음 싣는 것만. 위젯 자기 재탐색·다른 주소는 막는다
  contents.on("will-frame-navigate", (event) => {
    let frameUrl: string | null = null;
    let parentUrl: string | null = null;
    try {
      frameUrl = event.frame?.url ?? null;
      parentUrl = event.frame?.parent?.url ?? null;
    } catch {
      // 이미 사라진 프레임: 막는다
    }
    const allowed = frameNavigationAllowed({
      isMainFrame: event.isMainFrame,
      url: event.url,
      frameUrl,
      parentUrl,
      initiatorUrl: event.initiator?.url ?? null,
    });
    if (!allowed) event.preventDefault();
  });
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
  // 녹화 단축키 (M4 T9, shortcuts.ts): 녹화 중에만 전역 등록. E2E는 등록 실패를 흉내 내고 누름을 부른다
  const hotkeyCallbacks = new Map<string, () => void>();
  const blockedHotkeys = new Set<string>();
  const shortcutHost: ShortcutHost = {
    register(accelerator, callback) {
      if (blockedHotkeys.has(accelerator)) return false;
      const ok = globalShortcut.register(accelerator, callback);
      if (ok) hotkeyCallbacks.set(accelerator, callback);
      return ok;
    },
    unregister(accelerator) {
      hotkeyCallbacks.delete(accelerator);
      globalShortcut.unregister(accelerator);
    },
  };
  // 정지 단축키는 주 프로세스가 바로 daemon에 보낸다 (렌더러가 바빠도 멈춘다). 같은 연결이라 소유 연결이다
  const shortcuts = new RecorderShortcuts(shortcutHost, () => {
    void daemonCall("recorder.stop", {}, "{}").catch((err: unknown) => {
      console.warn(`녹화 정지 단축키: ${(err as Error).message}`);
    });
  });
  app.on("will-quit", () => {
    shortcuts.disarm();
    globalShortcut.unregisterAll();
  });
  // 위젯 호스트 확인: 주 프로세스가 daemon에서 직접 읽는다 (렌더러가 경로를 정하지 못한다). manager는 부를 때 쓴다
  const widgetHosts = new WidgetHosts({
    list: () => manager.call("plugins.list", {}, "{}"),
    root: () => manager.root,
  });
  const manager = new DaemonManager(
    nodeDeps({
      client: { kind: "ui", name: "Kookabug", version: app.getVersion() },
      locateCli: cliLocation,
      extraArgs: parseExtraArgs(process.env.KOOKABUG_DAEMON_ARGS),
    }),
    {
      state: (state) => {
        shortcuts.onConnection(state.status);
        // 연결이 바뀌면 진행 중인 위젯 호스트 확인의 응답을 버린다 (다른 daemon·끊긴 연결)
        widgetHosts.invalidate();
        send("daemon.state", state);
      },
      notification: (method, params) => {
        if (method === "recorder.changed") {
          const p = params as { state?: unknown; session?: unknown } | null;
          shortcuts.onRecorderState(p?.state, p?.session);
        }
        if (method === "plugins.changed") widgetHosts.invalidate();
        forward(method, params);
      },
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
        pressRecorderHotkey(role) {
          const accelerator = RECORDER_HOTKEYS.find((h) => h.role === role)?.accelerator;
          const callback = accelerator === undefined ? undefined : hotkeyCallbacks.get(accelerator);
          callback?.();
          return callback !== undefined;
        },
        recorderAccelerators: () => shortcuts.accelerators(),
        blockRecorderHotkey(accelerator) {
          blockedHotkeys.clear();
          if (accelerator !== null) blockedHotkeys.add(accelerator);
        },
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

  // 녹화 문지기는 맨 바깥: 렌더러 요청·정지 단축키가 모두 거친다
  daemonCall = guardRecorderCall(daemonCall, shortcuts, wireStringify);

  // 에이전트 패널 세션 (M5 B5): 띄울 명령은 daemon agents.get(사용자 설정)에서 ID로 찾는다
  const agentOverride =
    __KOOKABUG_E2E_HOOKS__ && e2eHooksEnabled(app.isPackaged, process.env)
      ? parseAgentOverride(process.env.KOOKABUG_E2E_AGENT)
      : null;
  const agentHost = new AgentHost({
    async agents() {
      const result = (await daemonCall("agents.get", {}, "{}")) as { agents: AgentSpecLite[] };
      return result.agents;
    },
    cli: () => cliLocation().path,
    root: () => manager.root,
    baseEnv: process.env,
    override: agentOverride,
    spawn: spawnAgent,
    emit: (event) => send("agent.session", event),
  });
  app.on("will-quit", () => agentHost.stopAll());
  // 앱 동작의 오류는 code를 메시지 앞에 붙여 렌더러가 알아보게 한다 (IPC는 Error 추가 필드를 버린다)
  const agentAction =
    <A extends unknown[], R>(fn: (...args: A) => R) =>
    async (...args: A): Promise<Awaited<R>> => {
      try {
        return await fn(...args);
      } catch (err) {
        if (err instanceof AgentHostError || err instanceof JobsError) throw new Error(`${err.code}: ${err.message}`);
        throw err;
      }
    };
  // 마법사·보고함의 사람 쪽 CLI (M8 B7, jobs.ts): 루트·Agent 명령은 주 프로세스가 정한다
  const jobs = new JobRunner({
    cli: () => cliLocation().path,
    root: () => manager.root,
    async agentIds() {
      const result = (await daemonCall("agents.get", {}, "{}")) as { agents: AgentSpecLite[] };
      return result.agents.map((a) => a.id);
    },
    exec: nodeExec(process.env),
    spawn: nodeSpawn(process.env),
    emit: (result) => send("jobs.cli", result),
    override:
      __KOOKABUG_E2E_HOOKS__ && e2eHooksEnabled(app.isPackaged, process.env)
        ? (process.env.KOOKABUG_E2E_AGENT_JOB ?? null)
        : null,
  });
  // 앱이 띄운 agent-job이 돌고 있으면 끝내기 전에 취소를 요청하고 상한(5초)까지 기다린다. 작업 종료 경로(R8)는 daemon·CLI 몫
  let jobsShutDown = false;
  app.on("before-quit", (event) => {
    if (jobsShutDown || !jobs.running) return;
    event.preventDefault();
    jobsShutDown = true;
    void jobs.shutdown().finally(() => app.quit());
  });
  // 띄운 작업이 없던 종료도 종료 플래그는 세운다 (끝내는 사이 시작 중이던 probe·run·만들기가 띄우지 않게)
  app.on("will-quit", () => void jobs.shutdown());

  handleProtocols(RENDERER_ROOT, () => manager.root, widgetHosts);

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
    closeWorkspace: () => {
      agentHost.stopAll();
      return manager.detach();
    },
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
    agentSetupDismissedGet: () => settings.agentSetupDismissed,
    layoutGet: () => settings.layout,
    layoutSet(layout) {
      // 작은 평평한 객체만 (값은 수·참거짓·null)
      const ok =
        typeof layout === "object" &&
        layout !== null &&
        !Array.isArray(layout) &&
        Object.keys(layout).length <= 16 &&
        Object.values(layout).every((v) => v === null || typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v)));
      if (!ok) throw new IpcGuardError("layoutSet 인자가 배치 객체가 아니다");
      settings.layout = layout;
    },
    agentSetupDismissedSet() {
      settings.agentSetupDismissed = true;
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
    recorderArm: () => shortcuts.arm(),
    recorderDisarm: () => shortcuts.disarm(),
    agentStart: agentAction((agentId: unknown) => {
      if (typeof agentId !== "string" || agentId === "") throw new IpcGuardError("agentStart 인자가 문자열이 아니다");
      return agentHost.start(agentId);
    }),
    agentPrompt: agentAction((session: unknown, text: unknown) => agentHost.prompt(session, text)),
    agentCancel: agentAction((session: unknown) => agentHost.cancel(session)),
    agentPermission: agentAction((session: unknown, id: unknown, optionId: unknown) =>
      agentHost.permission(session, id, optionId),
    ),
    agentStop: agentAction((session: unknown) => agentHost.stop(session)),
    // M8 B7 마법사·보고함 (jobs.ts)
    async pickFolder() {
      const options: Electron.OpenDialogOptions = { title: "프로젝트 위치", properties: ["openDirectory", "createDirectory"] };
      const picked = mainWindow ? await dialog.showOpenDialog(mainWindow, options) : await dialog.showOpenDialog(options);
      return picked.canceled || picked.filePaths.length === 0 ? null : picked.filePaths[0];
    },
    workspaceCreate: agentAction(async (request: unknown) => {
      const created = await jobs.createWorkspace(request);
      return openWorkspace(created.folder);
    }),
    agentProbe: agentAction((agentId: unknown) => jobs.probe(agentId)),
    agentJobRun: agentAction((playbook: unknown, agentId: unknown) => jobs.runJob(playbook, agentId)),
    doctor: agentAction(() => jobs.doctor()),
    agentSetConfig: agentAction((session: unknown, id: unknown, value: unknown) => agentHost.setConfig(session, id, value)),
  };
  // 창 닫기 확인 (close-guard.ts): 저장 안 된 그래프가 있으면 렌더러가 저장·버림·취소를 묻는다
  const closeGuard = new CloseGuard({
    ask: () => send("app.closeRequested", {}),
    close: () => mainWindow?.close(),
  });
  ipcMain.handle(APP_CHANNEL, (event, action: unknown, ...args: unknown[]) => {
    guardSender(event);
    const name = checkAppAction(action);
    checkJobArgs(name, args);
    return actions[name](...args);
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
    agentHost.stopAll();
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
