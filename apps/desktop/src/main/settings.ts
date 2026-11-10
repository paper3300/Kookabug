// 앱 설정과 최근 프로젝트 (M2 계획 2.10 테마·폴더 열기). userData/settings.json, userData/recent.json.
// electron을 import하지 않는다 (vitest)
import fs from "node:fs";
import path from "node:path";
import type { RecentProject, ThemeMode } from "../preload/bridge";

export const RECENT_MAX = 10;
export const WORKSPACE_FILE = "kookabug.json";

const THEME_MODES: readonly ThemeMode[] = ["system", "light", "dark"];

export function isThemeMode(v: unknown): v is ThemeMode {
  return typeof v === "string" && (THEME_MODES as readonly string[]).includes(v);
}

function readJson(file: string): unknown {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

// 임시 파일 + 이름 바꾸기 (쓰다 꺼져도 앞 파일이 남는다)
function writeJson(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n");
  fs.renameSync(tmp, file);
}

function samePath(a: string, b: string): boolean {
  const fold = (p: string) => (process.platform === "win32" ? path.resolve(p).toLowerCase() : path.resolve(p));
  return fold(a) === fold(b);
}

export class Settings {
  constructor(private readonly dir: string) {}

  private get settingsFile(): string {
    return path.join(this.dir, "settings.json");
  }

  private get recentFile(): string {
    return path.join(this.dir, "recent.json");
  }

  /** 첫 실행은 system (Windows 설정을 따른다) */
  get theme(): ThemeMode {
    const data = readJson(this.settingsFile) as { theme?: unknown } | null;
    return isThemeMode(data?.theme) ? data.theme : "system";
  }

  set theme(mode: ThemeMode) {
    const data = readJson(this.settingsFile);
    const base = typeof data === "object" && data !== null && !Array.isArray(data) ? data : {};
    writeJson(this.settingsFile, { ...base, theme: mode });
  }

  /** 디버그 툴바 가로 자리 (캔버스 가운데 기준 px, M3 계획 2.9 "자리를 기억한다"). 처음은 가운데(0) */
  get debugToolbarX(): number {
    const data = readJson(this.settingsFile) as { debugToolbarX?: unknown } | null;
    const x = data?.debugToolbarX;
    return typeof x === "number" && Number.isFinite(x) ? x : 0;
  }

  set debugToolbarX(x: number) {
    const data = readJson(this.settingsFile);
    const base = typeof data === "object" && data !== null && !Array.isArray(data) ? data : {};
    writeJson(this.settingsFile, { ...base, debugToolbarX: Math.round(x) });
  }

  /** 에이전트 첫 설정 대화 상자를 "나중에"로 닫음 (다시 띄우지 않는다) */
  get agentSetupDismissed(): boolean {
    const data = readJson(this.settingsFile) as { agentSetupDismissed?: unknown } | null;
    return data?.agentSetupDismissed === true;
  }

  set agentSetupDismissed(value: boolean) {
    const data = readJson(this.settingsFile);
    const base = typeof data === "object" && data !== null && !Array.isArray(data) ? data : {};
    writeJson(this.settingsFile, { ...base, agentSetupDismissed: value });
  }

  /** 패널 배치 (사이드바·오른쪽 패널 폭·펼침). 모양 검사는 렌더러(parseLayout)가 한다 */
  get layout(): unknown {
    const data = readJson(this.settingsFile) as { layout?: unknown } | null;
    return data?.layout ?? null;
  }

  set layout(value: unknown) {
    const data = readJson(this.settingsFile);
    const base = typeof data === "object" && data !== null && !Array.isArray(data) ? data : {};
    writeJson(this.settingsFile, { ...base, layout: value });
  }

  recent(): RecentProject[] {
    const data = readJson(this.recentFile);
    if (!Array.isArray(data)) return [];
    return data
      .filter(
        (r): r is RecentProject =>
          typeof r === "object" &&
          r !== null &&
          typeof r.path === "string" &&
          typeof r.name === "string" &&
          typeof r.openedAt === "string",
      )
      .slice(0, RECENT_MAX);
  }

  /** 맨 앞에 넣는다. 같은 폴더는 하나만, 최대 10개 */
  addRecent(root: string, now = new Date()): RecentProject[] {
    const entry: RecentProject = { path: root, name: path.basename(root), openedAt: now.toISOString() };
    const list = [entry, ...this.recent().filter((r) => !samePath(r.path, root))].slice(0, RECENT_MAX);
    writeJson(this.recentFile, list);
    return list;
  }
}

/** 폴더가 Kookabug 워크스페이스인지 (`kookabug.json`이 있는지) */
export function checkWorkspaceFolder(dir: string): "ok" | "not_found" | "not_workspace" {
  try {
    if (!fs.statSync(dir).isDirectory()) return "not_found";
  } catch {
    return "not_found";
  }
  return fs.existsSync(path.join(dir, WORKSPACE_FILE)) ? "ok" : "not_workspace";
}
