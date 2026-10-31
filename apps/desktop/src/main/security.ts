// 창 보안 기본값과 kbimg:// 경로 검사 (M2 계획 2.10, 2.4 "이미지는 RPC에 싣지 않는다").
// electron을 import하지 않는다: vitest가 Electron 없이 검사한다
import fs from "node:fs";
import path from "node:path";

export const APP_SCHEME = "app";
export const APP_HOST = "app";
export const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`;
export const KBIMG_SCHEME = "kbimg";

export const CSP =
  "default-src 'self'; img-src 'self' kbimg: data:; style-src 'self' 'unsafe-inline'; " +
  "font-src 'self'; connect-src 'none'";

export function cspHeaderValue(): string {
  return CSP;
}

// BrowserWindow webPreferences. 값을 바꾸면 security.test.ts가 실패한다
export function lockedWebPreferences(preload: string) {
  return {
    preload,
    contextIsolation: true,
    sandbox: true,
    nodeIntegration: false,
    nodeIntegrationInWorker: false,
    nodeIntegrationInSubFrames: false,
    webSecurity: true,
    allowRunningInsecureContent: false,
    webviewTag: false,
    experimentalFeatures: false,
    spellcheck: false,
  } as const;
}

// 앱 페이지 주소인지. 원격 내용은 싣지 않는다
export function isAppUrl(url: string): boolean {
  return url === APP_ORIGIN || url.startsWith(`${APP_ORIGIN}/`);
}

// 외부 링크는 https만 기본 브라우저로 연다
export function isExternalOpenAllowed(url: string): boolean {
  try {
    return new URL(url).protocol === "https:";
  } catch {
    return false;
  }
}

// app://app/<경로> → 렌더러 빌드 폴더 안 파일. 폴더 밖이면 null
export function resolveAppFile(url: string, rendererRoot: string): string | null {
  const prefix = `${APP_ORIGIN}/`;
  if (!url.startsWith(prefix)) return null;
  const rel = url.slice(prefix.length).split(/[?#]/, 1)[0] || "index.html";
  const segments = decodeSegments(rel);
  if (segments === null) return null;
  const file = path.join(rendererRoot, ...segments);
  return isInside(rendererRoot, file) ? file : null;
}

export const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"]);
export const PRIVATE_DIR = ".kookabug";
export const EDITOR_CACHE_DIR = [PRIVATE_DIR, "cache", "editor"] as const;

export type KbimgResult =
  | { ok: true; file: string }
  | {
      ok: false;
      reason: "bad_url" | "path_outside_workspace" | "private_path" | "not_image" | "not_found";
    };

/**
 * kbimg://cache/<id>.png 와 kbimg://ws/<상대 경로>만 받는다.
 * 원문 URL을 직접 나눈다: URL 파서의 점 구간 정리나 %2F 해석에 기대지 않는다.
 * 경계는 워크스페이스의 실제 루트에서 정한다. ws는 실제 경로가 루트 안이고 비공개 폴더 밖이어야
 * 한다. 비공개 폴더는 이름 위치(`<루트>/.kookabug`)와, `.kookabug`가 정션이면 그 실제 대상 둘 다다.
 * cache는 `<실제 루트>/.kookabug/cache/editor` 바로 안의 파일만이고, 그 사이 폴더가 정션이라
 * 실제 위치가 바뀌면 거부한다.
 */
export function resolveKbimgPath(url: string, workspaceRoot: string | null): KbimgResult {
  const prefix = `${KBIMG_SCHEME}://`;
  if (!url.toLowerCase().startsWith(prefix)) return { ok: false, reason: "bad_url" };
  const rest = url.slice(prefix.length);
  if (/[?#]/.test(rest)) return { ok: false, reason: "bad_url" };
  const slash = rest.indexOf("/");
  if (slash <= 0) return { ok: false, reason: "bad_url" };
  const host = rest.slice(0, slash).toLowerCase();
  const segments = decodeSegments(rest.slice(slash + 1));
  if (segments === null) return { ok: false, reason: "path_outside_workspace" };
  if (workspaceRoot === null) return { ok: false, reason: "not_found" };
  if (host !== "cache" && host !== "ws") return { ok: false, reason: "bad_url" };
  const realRoot = realOrNull(workspaceRoot);
  if (realRoot === null) return { ok: false, reason: "not_found" };

  if (host === "cache") {
    if (segments.length !== 1 || !/^[A-Za-z0-9_-]+\.png$/.test(segments[0])) {
      return { ok: false, reason: "bad_url" };
    }
    const expected = path.join(realRoot, ...EDITOR_CACHE_DIR);
    const realDir = realOrNull(path.join(workspaceRoot, ...EDITOR_CACHE_DIR));
    if (realDir === null) return { ok: false, reason: "not_found" };
    if (!samePath(realDir, expected)) return { ok: false, reason: "path_outside_workspace" };
    const realFile = realOrNull(path.join(realDir, segments[0]));
    if (realFile === null) return { ok: false, reason: "not_found" };
    // 파일 자체가 링크라 다른 곳을 가리키면 거부한다
    if (!samePath(path.dirname(realFile), expected)) {
      return { ok: false, reason: "path_outside_workspace" };
    }
    return finish(realFile);
  }

  // 대소문자·끝 점·공백은 decodeSegments가 막거나 여기서 접는다 (Windows는 대소문자 무시)
  if (segments[0].toLowerCase() === PRIVATE_DIR) return { ok: false, reason: "private_path" };
  if (!IMAGE_EXTENSIONS.has(path.extname(segments.at(-1)!).toLowerCase())) {
    return { ok: false, reason: "not_image" };
  }
  const realFile = realOrNull(path.join(workspaceRoot, ...segments));
  if (realFile === null) return { ok: false, reason: "not_found" };
  if (!isInside(realRoot, realFile)) return { ok: false, reason: "path_outside_workspace" };
  const privateDirs = [path.join(realRoot, PRIVATE_DIR), realOrNull(path.join(workspaceRoot, PRIVATE_DIR))];
  for (const dir of privateDirs) {
    if (dir !== null && (samePath(dir, realFile) || isInside(dir, realFile))) {
      return { ok: false, reason: "private_path" };
    }
  }
  return finish(realFile);
}

// 구간마다 퍼센트 해석 뒤 검사. 빈 구간·`.`·`..`·구분자·드라이브·NUL, Windows가 지우는
// 끝 점·공백(`.kookabug.` = `.kookabug`)은 거부한다
function decodeSegments(rel: string): string[] | null {
  if (rel === "") return null;
  const out: string[] = [];
  for (const raw of rel.split("/")) {
    let seg: string;
    try {
      seg = decodeURIComponent(raw);
    } catch {
      return null;
    }
    if (seg === "" || seg === "." || seg === "..") return null;
    if (/[\\/:\0*?"<>|]/.test(seg) || /[. ]$/.test(seg)) return null;
    out.push(seg);
  }
  return out;
}

// Windows 경로는 대소문자를 가리지 않는다
function fold(p: string): string {
  return process.platform === "win32" ? path.resolve(p).toLowerCase() : path.resolve(p);
}

function samePath(a: string, b: string): boolean {
  return fold(a) === fold(b);
}

// 부모 판정은 경로 구간 기준이다. `..secret.png`·`..shots`는 이름이지 부모 구간이 아니다
function isInside(root: string, file: string): boolean {
  const rel = path.relative(fold(root), fold(file));
  return rel !== "" && rel !== ".." && !rel.startsWith(`..${path.sep}`) && !path.isAbsolute(rel);
}

function realOrNull(p: string): string | null {
  try {
    return fs.realpathSync.native(p);
  } catch {
    return null;
  }
}

// 실제 파일의 확장자(링크가 이미지 아닌 파일을 가리킬 수 있다)와 파일인지 확인
function finish(realFile: string): KbimgResult {
  if (!IMAGE_EXTENSIONS.has(path.extname(realFile).toLowerCase())) {
    return { ok: false, reason: "not_image" };
  }
  if (!fs.statSync(realFile).isFile()) return { ok: false, reason: "not_found" };
  return { ok: true, file: realFile };
}
