// 시안 템플릿 렌더러 (M2 계획 2.12). `.dc.html`의 `<sc-for>`·`<sc-if>`·`{{식}}`을 파일 끝
// `renderVals()` 데이터로 펼치고, 시안이 요청한 글꼴을 로컬 판으로 바꿔 Edge로 찍는다.
//
//   node tools/design-ref/render.mjs [이름...]   → build/design-ref/<이름>.png
//
// 시안 원본은 고치지 않는다. 지원하지 않는 태그·식·빠진 값·남은 `{{`는 실패다.
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { chromium } from "playwright";

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = path.resolve(HERE, "..", "..");
export const DESIGN_DIR = path.join(REPO_ROOT, "Docs", "Design", "UX 시안 v0.1");
export const OUT_DIR = path.join(REPO_ROOT, "build", "design-ref");
export const DEFAULT_SCREENS = ["Main", "MainLight", "Recorder", "RunViewer", "Setup0Welcome", "Setup0WelcomeLight"];

// 페이지와 로컬 자원을 서비스하는 가짜 주소. 그 밖의 요청은 막고 센다
export const LOCAL_ORIGIN = "http://design-ref.local";

// 시안이 Google Fonts에 요청하는 글꼴 → 로컬 @fontsource 패키지. 없는 글꼴은 실패다
export const LOCAL_FONTS = {
  "Noto Sans KR": "@fontsource/noto-sans-kr",
  "JetBrains Mono": "@fontsource/jetbrains-mono",
  Fraunces: "@fontsource/fraunces",
};

const require = createRequire(import.meta.url);

export class TemplateError extends Error {
  name = "TemplateError";
}

export function canvasBoards() {
  const canvas = JSON.parse(fs.readFileSync(path.join(DESIGN_DIR, "canvas.json"), "utf8"));
  return canvas.boards;
}

// canvas.json의 화면별 판 크기 (Main·Recorder 1440×900, Setup 1120×720)
export function viewportOf(name) {
  const board = canvasBoards()[`${name}.dc.html`];
  if (!board) throw new TemplateError(`canvas.json에 판이 없다: ${name}`);
  return { width: board.w, height: board.h };
}

/**
 * Google Fonts css2 링크에서 글꼴과 굵기를 읽는다.
 * `family=Noto+Sans+KR:wght@400;500;700`, `family=Fraunces:opsz,wght@9..144,700`
 */
export function parseFontRequests(html) {
  const out = [];
  const linkRe = /<link\b[^>]*href="(https:\/\/fonts\.googleapis\.com\/css2\?[^"]+)"[^>]*>/g;
  for (const m of html.matchAll(linkRe)) {
    const url = new URL(m[1].replaceAll("&amp;", "&"));
    for (const family of url.searchParams.getAll("family")) {
      const [name, spec] = family.split(":");
      let weights = [400];
      if (spec) {
        const [axes, values] = spec.split("@");
        const w = axes.split(",").indexOf("wght");
        if (w < 0) throw new TemplateError(`굵기 축이 없는 글꼴 요청: ${family}`);
        weights = values.split(";").map((tuple) => Number(tuple.split(",")[w]));
      }
      out.push({ family: name.replaceAll("+", " "), weights, link: m[0] });
    }
  }
  return out;
}

function fontPackageDir(pkg) {
  return path.dirname(require.resolve(`${pkg}/package.json`));
}

/**
 * 원본 HTML을 펼치기 전 형태로 바꾼다: 글꼴 링크 → 로컬, `support.js`·`x-dc`·`helmet` 걷기,
 * `<script type="text/x-dc">` 떼어 내기. 결과 `{html, logic, fonts}`
 */
export function prepare(source) {
  const fonts = parseFontRequests(source);
  let html = source;
  const links = [];
  for (const req of fonts) {
    const pkg = LOCAL_FONTS[req.family];
    if (!pkg) throw new TemplateError(`로컬 판이 없는 글꼴: ${req.family}`);
    const dir = fontPackageDir(pkg);
    for (const w of req.weights) {
      if (!fs.existsSync(path.join(dir, `${w}.css`))) {
        throw new TemplateError(`로컬 글꼴에 굵기가 없다: ${req.family} ${w}`);
      }
      links.push(`<link rel="stylesheet" href="${LOCAL_ORIGIN}/fonts/${pkg}/${w}.css">`);
    }
  }
  for (const req of fonts) html = html.replace(req.link, "");
  html = html.replace(/<script src="\.\/support\.js"><\/script>/, "");

  const scripts = [...html.matchAll(/<script\b[^>]*type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/g)];
  if (scripts.length !== 1) throw new TemplateError(`text/x-dc 스크립트가 ${scripts.length}개다`);
  const logic = scripts[0][1];
  html = html.replace(scripts[0][0], "");
  if (/<script\b/i.test(html)) throw new TemplateError("알 수 없는 스크립트가 남았다");

  const helmet = html.match(/<helmet>([\s\S]*?)<\/helmet>/);
  if (helmet) html = html.replace(helmet[0], "");
  html = html.replace(/<\/?x-dc>/g, "");
  const head = [...links, helmet ? helmet[1] : ""].join("\n");
  if (!html.includes("</head>")) throw new TemplateError("</head>가 없다");
  html = html.replace("</head>", `${head}\n</head>`);
  return { html, logic, fonts: fonts.map(({ family, weights }) => ({ family, weights })) };
}

// 페이지 안에서 돈다: renderVals()를 얻고 템플릿을 펼친다
function expandInPage(logic) {
  class DCLogic {
    constructor() {
      this.props = {};
      this.state = {};
    }
  }
  const Component = new Function("DCLogic", `${logic}\nreturn Component;`)(DCLogic);
  const vals = new Component().renderVals();
  const loops = [];
  const PATH = /^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$/;

  function evalExpr(expr, scope) {
    const e = expr.trim();
    if (e === "true") return { value: true, path: e };
    if (e === "false") return { value: false, path: e };
    if (e === "null") return { value: null, path: e };
    if (/^-?\d+(\.\d+)?$/.test(e)) return { value: Number(e), path: e };
    if (!PATH.test(e)) throw new Error(`지원하지 않는 식: {{${expr}}}`);
    const [head, ...rest] = e.split(".");
    let cur;
    let curPath;
    if (Object.hasOwn(scope, head)) ({ value: cur, path: curPath } = scope[head]);
    else if (Object.hasOwn(vals, head)) [cur, curPath] = [vals[head], head];
    else throw new Error(`값이 없다: {{${expr}}}`);
    for (const key of rest) {
      if (cur === null || typeof cur !== "object" || !Object.hasOwn(cur, key)) {
        throw new Error(`값이 없다: {{${expr}}}`);
      }
      cur = cur[key];
      curPath = `${curPath}.${key}`;
    }
    if (cur === undefined) throw new Error(`값이 없다: {{${expr}}}`);
    return { value: cur, path: curPath };
  }

  function single(attr, scope) {
    const m = attr.match(/^\s*\{\{([^{}]*)\}\}\s*$/);
    if (!m) throw new Error(`식 하나여야 한다: ${attr}`);
    return evalExpr(m[1], scope);
  }

  function interpolate(text, scope) {
    return text.replace(/\{\{([^{}]*)\}\}/g, (_, expr) => {
      const { value } = evalExpr(expr, scope);
      if (value !== null && typeof value === "object") throw new Error(`객체를 글자로 쓸 수 없다: {{${expr}}}`);
      return String(value);
    });
  }

  function expandChildren(parent, scope) {
    for (const node of [...parent.childNodes]) expandNode(node, scope);
  }

  function expandNode(node, scope) {
    if (node.nodeType === Node.TEXT_NODE) {
      if (node.data.includes("{{")) node.data = interpolate(node.data, scope);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const tag = node.localName;
    if (tag === "sc-for") {
      const list = single(node.getAttribute("list") ?? "", scope);
      const as = node.getAttribute("as");
      if (!Array.isArray(list.value)) throw new Error(`sc-for 목록이 배열이 아니다: ${list.path}`);
      if (!as || !/^[A-Za-z_$][\w$]*$/.test(as)) throw new Error(`sc-for as가 틀리다: ${as}`);
      const templates = [...node.childNodes];
      if (templates.filter((n) => n.nodeType === Node.ELEMENT_NODE).length === 0) {
        throw new Error(`sc-for에 요소가 없다: ${list.path}`);
      }
      list.value.forEach((item, i) => {
        const inner = { ...scope, [as]: { value: item, path: `${list.path}[${i}]` } };
        let marked = false;
        for (const t of templates) {
          const clone = t.cloneNode(true);
          if (!marked && clone.nodeType === Node.ELEMENT_NODE) {
            clone.setAttribute("data-dc-row", list.path);
            marked = true;
          }
          node.before(clone);
          expandNode(clone, inner);
        }
      });
      loops.push({ path: list.path, count: list.value.length });
      node.remove();
      return;
    }
    if (tag === "sc-if") {
      const cond = single(node.getAttribute("value") ?? "", scope);
      if (cond.value) {
        const kids = [...node.childNodes];
        node.replaceWith(...kids);
        for (const k of kids) expandNode(k, scope);
      } else {
        node.remove();
      }
      return;
    }
    if (tag.startsWith("sc-") || tag.includes("-")) throw new Error(`지원하지 않는 템플릿 태그: <${tag}>`);
    for (const attr of [...node.attributes]) {
      if (attr.value.includes("{{")) node.setAttribute(attr.name, interpolate(attr.value, scope));
    }
    expandChildren(node, scope);
  }

  try {
    expandChildren(document.documentElement, {});
  } catch (err) {
    return { error: String(err.message ?? err) };
  }
  return { vals: JSON.parse(JSON.stringify(vals)), loops };
}

// 펼친 결과를 renderVals와 대조한다 (검수 M10). 페이지 안에서 돈다
function verifyInPage({ vals, loops }) {
  const problems = [];
  if (document.documentElement.outerHTML.includes("{{")) problems.push("남은 {{ 가 있다");
  if (document.querySelector("sc-for, sc-if")) problems.push("펼치지 않은 템플릿 태그가 있다");
  const text = document.body.textContent ?? "";
  for (const loop of loops) {
    const rows = document.querySelectorAll(`[data-dc-row="${CSS.escape(loop.path)}"]`).length;
    if (rows !== loop.count) problems.push(`${loop.path}: 줄 ${rows}개, renderVals ${loop.count}개`);
    const list = loop.path
      .split(/\.|\[(\d+)\]/)
      .filter((k) => k !== undefined && k !== "")
      .reduce((cur, k) => cur?.[k], vals);
    for (const [i, item] of (list ?? []).entries()) {
      for (const key of ["title", "name", "msg", "node"]) {
        const v = item?.[key];
        if (typeof v === "string" && v.trim() && !text.includes(v)) {
          problems.push(`${loop.path}[${i}].${key} 글자가 화면에 없다: ${v}`);
        }
      }
    }
  }
  return problems;
}

/**
 * 시안 하나를 연 페이지를 돌려준다. `source`를 주면 그 HTML을 쓴다(검사용).
 * 결과 `{page, context, vals, loops, fonts, external}` — external은 막은 바깥 요청 목록
 */
export async function openReference(browser, name, { source, viewport } = {}) {
  const raw = source ?? fs.readFileSync(path.join(DESIGN_DIR, `${name}.dc.html`), "utf8");
  const prepared = prepare(raw);
  const context = await browser.newContext({
    viewport: viewport ?? viewportOf(name),
    deviceScaleFactor: 1,
  });
  const external = [];
  await context.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== LOCAL_ORIGIN) {
      external.push(url.href);
      return route.abort("blockedbyclient");
    }
    if (url.pathname === "/page.html") {
      return route.fulfill({ contentType: "text/html; charset=utf-8", body: prepared.html });
    }
    const file = localFile(decodeURIComponent(url.pathname));
    if (file === null) return route.fulfill({ status: 404, body: "" });
    return route.fulfill({ path: file });
  });
  const page = await context.newPage();
  await page.goto(`${LOCAL_ORIGIN}/page.html`);
  const expanded = await page.evaluate(expandInPage, prepared.logic);
  if (expanded.error) {
    await context.close();
    throw new TemplateError(`${name}: ${expanded.error}`);
  }
  const fonts = await page.evaluate(loadFontsInPage, prepared.fonts);
  const missing = fonts.filter((f) => !f.loaded);
  if (missing.length) {
    await context.close();
    throw new TemplateError(`${name}: 로컬 글꼴을 싣지 못했다: ${JSON.stringify(missing)}`);
  }
  return { page, context, vals: expanded.vals, loops: expanded.loops, fonts, external };
}

// /fonts/<패키지>/<파일> → 그 @fontsource 폴더 안, /design/<파일> → 시안 폴더 안
function localFile(pathname) {
  const inside = (root, rel) => {
    const file = path.resolve(root, rel);
    const r = path.relative(root, file);
    return r && !r.startsWith("..") && !path.isAbsolute(r) && fs.existsSync(file) ? file : null;
  };
  for (const pkg of Object.values(LOCAL_FONTS)) {
    const prefix = `/fonts/${pkg}/`;
    if (pathname.startsWith(prefix)) return inside(fontPackageDir(pkg), pathname.slice(prefix.length));
  }
  if (pathname.startsWith("/design/")) return inside(DESIGN_DIR, pathname.slice("/design/".length));
  return null;
}

// 요청한 글꼴·굵기마다 실제로 실린 FontFace가 있는지 (unicode-range 조각은 쓸 때 실린다)
async function loadFontsInPage(requests) {
  const out = [];
  for (const { family, weights } of requests) {
    for (const weight of weights) {
      const sample = family === "Noto Sans KR" ? "가나다Aa" : "Aa";
      const faces = await document.fonts.load(`${weight} 16px "${family}"`, sample);
      out.push({ family, weight, loaded: faces.length > 0 && faces.every((f) => f.status === "loaded") });
    }
  }
  await document.fonts.ready;
  return out;
}

export async function verify(page, { vals, loops }) {
  return page.evaluate(verifyInPage, { vals, loops });
}

export async function launchBrowser() {
  return chromium.launch({ channel: "msedge" });
}

// 시안 하나를 찍어 PNG로 쓴다. 대조에 실패하면 던진다
export async function renderToPng(browser, name, outDir = OUT_DIR) {
  const ref = await openReference(browser, name);
  try {
    const problems = await verify(ref.page, ref);
    if (ref.external.length) problems.push(`바깥 요청: ${ref.external.join(", ")}`);
    if (problems.length) throw new TemplateError(`${name}: ${problems.join("; ")}`);
    fs.mkdirSync(outDir, { recursive: true });
    const file = path.join(outDir, `${name}.png`);
    await ref.page.screenshot({ path: file });
    return { file, loops: ref.loops, fonts: ref.fonts };
  } finally {
    await ref.context.close();
  }
}

async function main(argv) {
  const names = argv.length ? argv : DEFAULT_SCREENS;
  const browser = await launchBrowser();
  try {
    for (const name of names) {
      const { file, loops } = await renderToPng(browser, name);
      const rows = loops.map((l) => `${l.path}=${l.count}`).join(" ");
      console.log(`${path.relative(REPO_ROOT, file)}  ${rows}`);
    }
  } finally {
    await browser.close();
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main(process.argv.slice(2)).catch((err) => {
    console.error(err.message ?? err);
    process.exit(1);
  });
}
