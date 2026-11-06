// 창 보안 기본값과 kbimg:// 경로 검사 (M2 계획 2.10, 2.4 "이미지는 RPC에 싣지 않는다").
// M3 계획 2.7: 실행 영상(.mp4)은 runs/<폴더>/video/ 바로 안만, Range 요청은 206 부분 응답.
// electron을 import하지 않는다: vitest가 Electron 없이 검사한다
import fs from "node:fs";
import path from "node:path";
import { Readable } from "node:stream";

export const APP_SCHEME = "app";
export const APP_HOST = "app";
export const APP_ORIGIN = `${APP_SCHEME}://${APP_HOST}`;
export const KBIMG_SCHEME = "kbimg";

export const KBPLUGIN_SCHEME = "kbplugin";

// frame-src: 플러그인 위젯 iframe (M6 3.10)만. 그 밖은 M2 2.10 그대로
export const CSP =
  "default-src 'self'; img-src 'self' kbimg: data:; media-src kbimg:; " +
  "style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src 'none'; frame-src kbplugin:";

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
export const VIDEO_EXTENSION = ".mp4";
export const RUNS_DIR = "runs";
export const RUN_VIDEO_DIR = "video";
export const PRIVATE_DIR = ".kookabug";
export const EDITOR_CACHE_DIR = [PRIVATE_DIR, "cache", "editor"] as const;

export type KbimgResult =
  | { ok: true; file: string }
  | {
      ok: false;
      reason: "bad_url" | "path_outside_workspace" | "private_path" | "not_image" | "not_found";
    };

// 실행 영상 자리: <루트>/runs/<실행 폴더>/video/<파일>.mp4 (구간은 루트 기준, 대소문자 무시). 쓰는 중 조각
// (seg-NNNN.part.mp4)은 MP4 색인이 없어 재생할 수 없고 녹화 스레드가 쥔 파일이라 주지 않는다 (M3 T11)
function isRunVideo(parts: readonly string[]): boolean {
  return (
    parts.length === 4 &&
    parts[0].toLowerCase() === RUNS_DIR &&
    parts[2].toLowerCase() === RUN_VIDEO_DIR &&
    path.extname(parts[3]).toLowerCase() === VIDEO_EXTENSION &&
    !parts[3].toLowerCase().endsWith(`.part${VIDEO_EXTENSION}`)
  );
}

/**
 * kbimg://cache/<id>.png 와 kbimg://ws/<상대 경로>만 받는다. ws의 .mp4는 runs/<실행 폴더>/video/
 * 바로 안의 파일만이다(실제 경로도 그 자리여야 한다).
 * 원문 URL을 직접 나눈다: URL 파서의 점 구간 정리나 %2F 해석에 기대지 않는다.
 * 경계는 워크스페이스의 실제 루트에서 정한다. ws는 실제 경로가 루트 안이고 비공개 폴더 밖이어야
 * 한다. 비공개 폴더는 이름 위치(`<루트>/.kookabug`)와, `.kookabug`가 정션이면 그 실제 대상 둘 다다.
 * cache는 `<실제 루트>/.kookabug/cache/editor` 바로 안의 파일만이고, 그 사이 폴더가 정션이라
 * 실제 위치가 바뀌면 거부한다.
 */
export function resolveKbimgPath(url: string, workspaceRoot: string | null): KbimgResult {
  const prefix = `${KBIMG_SCHEME}://`;
  if (!url.toLowerCase().startsWith(prefix)) return { ok: false, reason: "bad_url" };
  let rest = url.slice(prefix.length);
  // 다시 읽기 표식 `?v=<숫자>`만 받고 버린다 (ws 이미지만, 다듬기 P1-B 보기 탭). 같은 주소의 그림은 렌더러가
  // 메모리에 둔 것을 다시 쓰므로, 파일이 바뀌면 표식을 바꿔 새로 읽게 한다. 그 밖의 ?·#는 거부한다
  const version = /^ws\/[^?#]*\?v=\d{1,15}$/i.test(rest) ? rest.lastIndexOf("?") : -1;
  if (version >= 0) rest = rest.slice(0, version);
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
  const ext = path.extname(segments.at(-1)!).toLowerCase();
  const video = ext === VIDEO_EXTENSION;
  if (video && version >= 0) return { ok: false, reason: "bad_url" };
  // 영상은 실행 폴더의 video/ 바로 안만 (요청 경로와 실제 경로 모두)
  if (video ? !isRunVideo(segments) : !IMAGE_EXTENSIONS.has(ext)) {
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
  if (video && !isRunVideo(path.relative(fold(realRoot), fold(realFile)).split(path.sep))) {
    return { ok: false, reason: "not_image" };
  }
  return finish(realFile, video);
}

export type ByteRange = { start: number; end: number };

/**
 * `Range` 머리 → 파일 안 바이트 범위 (끝 포함). 머리가 없거나 바이트 범위가 아니거나 여러 범위면
 * null(전체 응답), 맞출 수 없는 범위면 "unsatisfiable"(416)
 */
export function parseRange(header: string | null, size: number): ByteRange | null | "unsatisfiable" {
  if (header === null) return null;
  const m = /^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$/i.exec(header);
  if (m === null) return null;
  const [, a, b] = m;
  if (a === "" && b === "") return null;
  let start: number;
  let end: number;
  if (a === "") {
    const suffix = Number(b);
    if (suffix === 0 || size === 0) return "unsatisfiable";
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(a);
    end = b === "" ? size - 1 : Math.min(Number(b), size - 1);
    if (start >= size || end < start) return "unsatisfiable";
  }
  return { start, end };
}

const CONTENT_TYPES: Record<string, string> = {
  ".mp4": "video/mp4",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
};

/**
 * 파일 응답 (kbimg 영상). Range 요청이면 206 부분 응답, 아니면 200 전체 응답이고 둘 다
 * `Accept-Ranges: bytes`다. 영상 탐색(<video>)은 Range로 원하는 자리를 읽는다
 */
export function fileResponse(file: string, rangeHeader: string | null): Response {
  const size = fs.statSync(file).size;
  const headers = new Headers({
    "Accept-Ranges": "bytes",
    "Content-Type": CONTENT_TYPES[path.extname(file).toLowerCase()] ?? "application/octet-stream",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  const range = parseRange(rangeHeader, size);
  if (range === "unsatisfiable") {
    headers.set("Content-Range", `bytes */${size}`);
    return new Response(null, { status: 416, headers });
  }
  const { start, end } = range ?? { start: 0, end: size - 1 };
  headers.set("Content-Length", String(Math.max(0, end - start + 1)));
  if (range !== null) headers.set("Content-Range", `bytes ${start}-${end}/${size}`);
  const body =
    size === 0
      ? null
      : (Readable.toWeb(fs.createReadStream(file, { start, end })) as ReadableStream<Uint8Array>);
  return new Response(body, { status: range === null ? 200 : 206, headers });
}

// ---------------------------------------------------------------- 플러그인 위젯 (M6 계획 3.10)

/** 처리기가 만드는 위젯 껍데기 문서 이름 */
export const WIDGET_SHELL = "__widget.html";
export const PLUGIN_CONTENT_TYPES: Record<string, string> = {
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
};
// <플러그인 ID('_'는 '-')>-<환경 지문 12자>: CSP 호스트 문법에는 '_'가 없다 (있으면 그 소스를 무시해 모두 막힌다)
const PLUGIN_HOST = /^[a-z][a-z0-9-]*-[0-9a-f]{12}$/;
const WIDGET_QUERY = /^\?w=[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*&s=[0-9a-f]{32}$/;

/** 위젯 호스트 하나: `kbplugin://<host>/`가 `dir`(환경 안 ui 폴더) 아래 파일만 준다 */
export interface WidgetHost {
  host: string;
  /** ui 폴더 (절대 경로) */
  dir: string;
  /** 이 폴더가 들어 있어야 하는 곳: `<워크스페이스>/.kookabug/plugins/envs` */
  envs: string;
}

/**
 * 위젯 문서·자원의 CSP. 네트워크(connect-src 없음)·다른 플러그인 자원·하위 프레임·폼·base 없음,
 * 앱 문서 안에서만 뜬다
 */
export function widgetCsp(host: string): string {
  const self = `${KBPLUGIN_SCHEME}://${host}`;
  return (
    `default-src 'none'; script-src ${self}; style-src ${self} 'unsafe-inline'; ` +
    `img-src ${self} data:; font-src ${self}; base-uri 'none'; form-action 'none'; frame-ancestors app:`
  );
}

/** 처리기가 만드는 껍데기: 그 플러그인의 ui/index.js를 ES 모듈로 싣는다 */
export function widgetShell(): string {
  return (
    '<!doctype html><html><head><meta charset="utf-8"><meta name="color-scheme" content="dark light">' +
    '</head><body><script type="module" src="index.js"></script></body></html>'
  );
}

/** 위젯 껍데기 주소: `kbplugin://<host>/__widget.html?w=<위젯>&s=<세션 nonce>` */
export function widgetUrl(host: string, widget: string, session: string): string {
  return `${KBPLUGIN_SCHEME}://${host}/${WIDGET_SHELL}?w=${widget}&s=${session}`;
}

export function isWidgetShellUrl(url: string): boolean {
  const m = /^kbplugin:\/\/([^/?#]+)\/__widget\.html(\?[^#]*)$/.exec(url);
  return m !== null && PLUGIN_HOST.test(m[1]) && WIDGET_QUERY.test(m[2]);
}

/**
 * plugins.list의 위젯 호스트 경로(워크스페이스 기준 '/' 경로) → 절대 경로. `.kookabug/plugins/envs/` 아래가
 * 아니거나 `..`·절대 경로·드라이브면 null
 */
export function widgetHostDir(workspaceRoot: string, rel: string): { dir: string; envs: string } | null {
  const segments = decodeSegments(rel.split("/").map(encodeURIComponent).join("/"));
  if (segments === null || segments.length < 5) return null;
  if (segments.slice(0, 3).join("/").toLowerCase() !== ".kookabug/plugins/envs") return null;
  return { dir: path.join(workspaceRoot, ...segments), envs: path.join(workspaceRoot, ".kookabug", "plugins", "envs") };
}

export type KbpluginResult =
  | { ok: true; kind: "shell"; host: string }
  | { ok: true; kind: "file"; host: string; file: string; contentType: string }
  | { ok: false; reason: "bad_url" | "unknown_host" | "outside" | "link" | "not_allowed" | "not_found" };

/**
 * `kbplugin://<host>/<경로>` 판정. 호스트는 `lookup`(지금 잠금에 있고 환경이 준비된 플러그인)에 있어야
 * 하고, 파일은 그 플러그인 ui 폴더 바로 그 아래만이다: `..`·절대 경로·구분자·드라이브·끝 점 거부, 경로의
 * 어느 구간이든 심볼릭 링크·정션이면 거부(실제 경로 = 요청 경로), 확장자는 js·mjs·css·png·svg·woff2만.
 * 다른 플러그인 위젯이 이 호스트 자원을 읽는 것은 그 위젯 문서의 CSP(자기 호스트만)가 막는다 — Electron 처리기
 * 요청에는 referrer·Origin이 오지 않아 처리기에서 요청한 문서를 가릴 수 없다
 */
export function resolvePluginUrl(url: string, lookup: (host: string) => WidgetHost | null): KbpluginResult {
  const m = /^kbplugin:\/\/([^/?#]+)\/([^?#]*)(\?[^#]*)?$/i.exec(url);
  if (m === null) return { ok: false, reason: "bad_url" };
  const host = m[1].toLowerCase();
  if (!PLUGIN_HOST.test(host)) return { ok: false, reason: "bad_url" };
  const entry = lookup(host);
  if (entry === null) return { ok: false, reason: "unknown_host" };
  if (m[2] === WIDGET_SHELL) {
    if (m[3] === undefined || !WIDGET_QUERY.test(m[3])) return { ok: false, reason: "bad_url" };
    return { ok: true, kind: "shell", host };
  }
  if (m[3] !== undefined) return { ok: false, reason: "bad_url" };
  const segments = decodeSegments(m[2]);
  if (segments === null) return { ok: false, reason: "outside" };
  const contentType = PLUGIN_CONTENT_TYPES[path.extname(segments.at(-1)!).toLowerCase()];
  if (contentType === undefined) return { ok: false, reason: "not_allowed" };
  const realEnvs = realOrNull(entry.envs);
  const realDir = realOrNull(entry.dir);
  if (realEnvs === null || realDir === null) return { ok: false, reason: "not_found" };
  // ui 폴더 자체도 환경 폴더 안 실제 자리여야 한다 (그 사이 정션이면 경계가 바뀐다)
  if (!isInside(realEnvs, realDir) || !samePath(realDir, path.join(realEnvs, path.relative(entry.envs, entry.dir)))) {
    return { ok: false, reason: "link" };
  }
  const expected = path.join(realDir, ...segments);
  const realFile = realOrNull(path.join(entry.dir, ...segments));
  if (realFile === null) return { ok: false, reason: "not_found" };
  if (!samePath(realFile, expected) || !isInside(realDir, realFile)) return { ok: false, reason: "link" };
  if (!fs.statSync(realFile).isFile()) return { ok: false, reason: "not_found" };
  return { ok: true, kind: "file", host, file: realFile, contentType };
}

/** kbplugin 응답 머리: 그 호스트 CSP, 불투명 출처 iframe의 ES 모듈 로딩용 CORS(null)는 이 응답에만 */
export function pluginHeaders(host: string, contentType: string): Headers {
  return new Headers({
    "Content-Type": contentType,
    "Content-Security-Policy": widgetCsp(host),
    "Access-Control-Allow-Origin": "null",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
  });
}

export interface FrameNavigation {
  isMainFrame: boolean;
  url: string;
  /** 이동하려는 프레임의 지금 주소 (새 iframe이면 "" 또는 about:blank, 알 수 없으면 null = 막음) */
  frameUrl: string | null;
  /** 그 프레임 부모의 주소 */
  parentUrl: string | null;
  /** 이동을 시작한 프레임의 주소 */
  initiatorUrl: string | null;
}

/**
 * 하위 프레임 이동 (`will-frame-navigate`): 앱 문서가 새 위젯 iframe에 껍데기를 처음 싣는 것만 허용한다.
 * 위젯의 자기 재탐색·다른 주소·다른 하위 프레임, 렌더러가 시작한 주 프레임 이동은 막는다
 */
export function frameNavigationAllowed(nav: FrameNavigation): boolean {
  if (nav.isMainFrame) return false;
  const fresh = nav.frameUrl === "" || nav.frameUrl === "about:blank";
  return (
    fresh &&
    isWidgetShellUrl(nav.url) &&
    nav.parentUrl !== null &&
    isAppUrl(nav.parentUrl) &&
    nav.initiatorUrl !== null &&
    isAppUrl(nav.initiatorUrl)
  );
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
function finish(realFile: string, video = false): KbimgResult {
  const ext = path.extname(realFile).toLowerCase();
  if (video ? ext !== VIDEO_EXTENSION : !IMAGE_EXTENSIONS.has(ext)) {
    return { ok: false, reason: "not_image" };
  }
  if (!fs.statSync(realFile).isFile()) return { ok: false, reason: "not_found" };
  return { ok: true, file: realFile };
}
