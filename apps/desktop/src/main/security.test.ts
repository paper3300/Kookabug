import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { afterAll, beforeAll, describe, expect, test } from "vitest";
import {
  cspHeaderValue,
  isExternalOpenAllowed,
  lockedWebPreferences,
  resolveAppFile,
  resolveKbimgPath,
} from "./security";

test("test_web_preferences_locked", () => {
  const prefs = lockedWebPreferences("C:/app/preload.cjs");
  expect(prefs.contextIsolation).toBe(true);
  expect(prefs.sandbox).toBe(true);
  expect(prefs.nodeIntegration).toBe(false);
  expect(prefs.nodeIntegrationInWorker).toBe(false);
  expect(prefs.nodeIntegrationInSubFrames).toBe(false);
  expect(prefs.webSecurity).toBe(true);
  expect(prefs.allowRunningInsecureContent).toBe(false);
  expect(prefs.webviewTag).toBe(false);
  expect(prefs.preload).toBe("C:/app/preload.cjs");
});

test("test_csp_header_value", () => {
  // 계획 2.10 문자열 그대로. 렌더러는 소켓을 열지 않는다 (connect-src 'none')
  expect(cspHeaderValue()).toBe(
    "default-src 'self'; img-src 'self' kbimg: data:; style-src 'self' 'unsafe-inline'; " +
      "font-src 'self'; connect-src 'none'",
  );
  const directives = new Map(
    cspHeaderValue()
      .split(";")
      .map((d) => d.trim().split(/\s+/))
      .map(([k, ...v]) => [k, v]),
  );
  expect(directives.get("connect-src")).toEqual(["'none'"]);
  expect(directives.get("default-src")).toEqual(["'self'"]);
  expect(directives.has("script-src")).toBe(false); // default-src 'self' → 인라인 스크립트 없음
});

test("external links open only for https", () => {
  expect(isExternalOpenAllowed("https://example.com/")).toBe(true);
  for (const url of ["http://example.com/", "file:///C:/x", "javascript:alert(1)", "app://app/x", "nope"]) {
    expect(isExternalOpenAllowed(url)).toBe(false);
  }
});

test("app files stay inside renderer root", () => {
  const root = path.resolve("/renderer");
  expect(resolveAppFile("app://app/index.html", root)).toBe(path.join(root, "index.html"));
  expect(resolveAppFile("app://app/assets/a.js?x=1", root)).toBe(path.join(root, "assets", "a.js"));
  for (const url of [
    "app://app/..%2F..%2Fsecret.txt",
    "app://app/assets/%2e%2e/%2e%2e/x",
    "app://app/C:%5CWindows%5Cwin.ini",
    "app://other/index.html",
    "file:///C:/index.html",
  ]) {
    expect(resolveAppFile(url, root), url).toBeNull();
  }
});

describe("kbimg", () => {
  let tmp: string;
  let ws: string;
  let outside: string;

  beforeAll(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kb-kbimg-"));
    ws = path.join(tmp, "작업 공간");
    outside = path.join(tmp, "outside");
    for (const dir of [
      path.join(ws, "targets"),
      path.join(ws, ".kookabug", "cache", "editor"),
      outside,
    ]) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(path.join(ws, "targets", "버튼.png"), "png");
    fs.writeFileSync(path.join(ws, "targets", "a.target.json"), "{}");
    fs.writeFileSync(path.join(ws, ".kookabug", "secret.png"), "png");
    fs.writeFileSync(path.join(ws, ".kookabug", "cache", "editor", "f1.png"), "png");
    fs.writeFileSync(path.join(outside, "x.png"), "png");
    fs.writeFileSync(path.join(tmp, "up.png"), "png");
    // 관리자 권한 없이 만들 수 있는 정션: 루트 밖과 .kookabug 안을 가리킨다
    fs.symlinkSync(outside, path.join(ws, "escape"), "junction");
    fs.symlinkSync(path.join(ws, ".kookabug"), path.join(ws, "private-link"), "junction");
  });

  afterAll(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test("test_kbimg_path_rejects_traversal_and_private", () => {
    const ok = resolveKbimgPath(`kbimg://ws/targets/${encodeURIComponent("버튼")}.png`, ws);
    expect(ok.ok).toBe(true);
    expect(ok.ok && fs.realpathSync.native(ok.file)).toBe(
      fs.realpathSync.native(path.join(ws, "targets", "버튼.png")),
    );
    const cache = resolveKbimgPath("kbimg://cache/f1.png", ws);
    expect(cache.ok).toBe(true);

    const rejected: [string, string][] = [
      // ..
      ["kbimg://ws/../up.png", "path_outside_workspace"],
      ["kbimg://ws/targets/../../up.png", "path_outside_workspace"],
      ["kbimg://ws/..%2Fup.png", "path_outside_workspace"],
      ["kbimg://ws/%2e%2e/up.png", "path_outside_workspace"],
      ["kbimg://ws/targets%5C..%5C..%5Cup.png", "path_outside_workspace"],
      // 절대 경로
      [`kbimg://ws/${encodeURIComponent(path.join(tmp, "up.png"))}`, "path_outside_workspace"],
      ["kbimg://ws//C:/Windows/x.png", "path_outside_workspace"],
      ["kbimg://ws/C:%5CWindows%5Cx.png", "path_outside_workspace"],
      // .kookabug/ (대소문자, Windows가 지우는 끝 점·공백, 정션)
      ["kbimg://ws/.kookabug/secret.png", "private_path"],
      ["kbimg://ws/.KOOKABUG/secret.png", "private_path"],
      ["kbimg://ws/.kookabug./secret.png", "path_outside_workspace"],
      ["kbimg://ws/.kookabug%20/secret.png", "path_outside_workspace"],
      ["kbimg://ws/private-link/secret.png", "private_path"],
      ["kbimg://ws/.kookabug/cache/editor/f1.png", "private_path"],
      // 루트 밖 정션
      ["kbimg://ws/escape/x.png", "path_outside_workspace"],
      // 이미지 아닌 확장자
      ["kbimg://ws/targets/a.target.json", "not_image"],
      ["kbimg://ws/targets/a.exe", "not_image"],
      // 캐시는 그 폴더의 PNG 이름만
      ["kbimg://cache/../secret.png", "path_outside_workspace"],
      ["kbimg://cache/sub/f1.png", "bad_url"],
      ["kbimg://cache/f1.jpg", "bad_url"],
      // 형식
      ["kbimg://other/targets/버튼.png", "bad_url"],
      ["kbimg://ws/targets/버튼.png?x=1", "bad_url"],
      ["kbimg://ws/targets/missing.png", "not_found"],
    ];
    for (const [url, reason] of rejected) {
      expect(resolveKbimgPath(url, ws), url).toEqual({ ok: false, reason });
    }
    // 워크스페이스가 없으면 아무것도 서비스하지 않는다
    expect(resolveKbimgPath("kbimg://cache/f1.png", null).ok).toBe(false);
  });

  // 캐시 경로의 중간 폴더(.kookabug·cache·editor)가 정션이면 경계가 바뀌므로 거부한다 (검수 T1_1 High)
  test("kbimg cache rejects junctions on the cache path", () => {
    // [정션 위치(.kookabug/cache/editor 중 하나), 대상(base 기준)]. 대상 아래 남은 경로에 secret.png를 둔다
    const cases: [string, string][] = [
      [".kookabug/cache/editor", "away/editor"],
      [".kookabug/cache", "away/cache"],
      [".kookabug", "away/kb"],
      [".kookabug/cache/editor", "ws/.kookabug/private"],
      [".kookabug/cache/editor", "ws/shots"],
    ];
    for (const [junction, target] of cases) {
      const base = fs.mkdtempSync(path.join(tmp, "cache-"));
      const ws = path.join(base, "ws");
      const rest = path.relative(junction, ".kookabug/cache/editor");
      const filesDir = path.join(base, target, rest);
      fs.mkdirSync(filesDir, { recursive: true });
      fs.writeFileSync(path.join(filesDir, "secret.png"), "png");
      fs.mkdirSync(path.dirname(path.join(ws, junction)), { recursive: true });
      link(path.join(base, target), path.join(ws, junction));
      expect(resolveKbimgPath("kbimg://cache/secret.png", ws), `${junction} → ${target}`).toEqual({
        ok: false,
        reason: "path_outside_workspace",
      });
    }
  });

  // `.kookabug` 자체가 정션이면 그 실제 대상과, 그쪽을 가리키는 다른 별칭도 비공개다 (검수 T1_1 Mid)
  test("kbimg ws rejects the real target of a junctioned .kookabug and its aliases", () => {
    const base = fs.mkdtempSync(path.join(tmp, "private-"));
    const ws = path.join(base, "ws");
    const data = path.join(ws, "private-data");
    fs.mkdirSync(path.join(data, "cache", "editor"), { recursive: true });
    fs.writeFileSync(path.join(data, "secret.png"), "png");
    fs.writeFileSync(path.join(data, "cache", "editor", "f.png"), "png");
    fs.mkdirSync(path.join(ws, "targets"), { recursive: true });
    fs.writeFileSync(path.join(ws, "targets", "ok.png"), "png");
    link(data, path.join(ws, ".kookabug"));
    link(data, path.join(ws, "alias"));

    for (const url of [
      "kbimg://ws/private-data/secret.png",
      "kbimg://ws/alias/secret.png",
      "kbimg://ws/.kookabug/secret.png",
      "kbimg://ws/private-data/cache/editor/f.png",
    ]) {
      expect(resolveKbimgPath(url, ws), url).toEqual({ ok: false, reason: "private_path" });
    }
    // 정션된 .kookabug 아래 캐시도 경계가 바뀐 것이라 거부
    expect(resolveKbimgPath("kbimg://cache/f.png", ws)).toEqual({ ok: false, reason: "path_outside_workspace" });
    // 일반 워크스페이스 이미지는 그대로
    expect(resolveKbimgPath("kbimg://ws/targets/ok.png", ws).ok).toBe(true);
  });
});

// 점 두 개로 시작하는 이름(`..secret.png`, `..shots`)도 비공개 폴더 안이다 (검수 T1_2 Mid)
describe("kbimg dot-dot names", () => {
  let tmp: string;
  beforeAll(() => {
    tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kb-kbimg-dots-"));
  });
  afterAll(() => {
    fs.rmSync(tmp, { recursive: true, force: true });
  });

  test("kbimg ws rejects private files whose names start with two dots", () => {
    for (const junctioned of [false, true]) {
      const ws = path.join(tmp, junctioned ? "junctioned" : "ordinary");
      // 비공개 내용이 있는 실제 폴더: 일반 .kookabug, 또는 .kookabug가 가리키는 private-data
      const privateReal = path.join(ws, junctioned ? "private-data" : ".kookabug");
      fs.mkdirSync(path.join(privateReal, "..shots"), { recursive: true });
      for (const rel of ["secret.png", "..secret.png", path.join("..shots", "secret.png")]) {
        fs.writeFileSync(path.join(privateReal, rel), "png");
      }
      if (junctioned) link(privateReal, path.join(ws, ".kookabug"));
      link(privateReal, path.join(ws, "alias"));
      fs.mkdirSync(path.join(ws, "..public"), { recursive: true });
      fs.writeFileSync(path.join(ws, "..public", "ok.png"), "png");
      fs.writeFileSync(path.join(ws, "..ok.png"), "png");

      for (const url of [
        "kbimg://ws/alias/secret.png",
        "kbimg://ws/alias/..secret.png",
        "kbimg://ws/alias/..shots/secret.png",
        ...(junctioned
          ? ["kbimg://ws/private-data/..secret.png", "kbimg://ws/private-data/..shots/secret.png"]
          : []),
      ]) {
        expect(resolveKbimgPath(url, ws), `${junctioned} ${url}`).toEqual({
          ok: false,
          reason: "private_path",
        });
      }
      // 루트 안의 점 두 개 이름은 일반 이미지다
      expect(resolveKbimgPath("kbimg://ws/..public/ok.png", ws).ok).toBe(true);
      expect(resolveKbimgPath("kbimg://ws/..ok.png", ws).ok).toBe(true);
    }
  });

  test("app files with two-dot names stay inside renderer root", () => {
    const root = path.resolve("/renderer");
    expect(resolveAppFile("app://app/..x.js", root)).toBe(path.join(root, "..x.js"));
  });
});

function link(target: string, at: string): void {
  fs.symlinkSync(target, at, "junction");
}
