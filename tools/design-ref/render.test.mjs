// 시안 렌더러 검사 (M2 계획 T1, 검수 M10). node --test tools/design-ref/
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import {
  DESIGN_DIR,
  launchBrowser,
  openReference,
  renderToPng,
  TemplateError,
  verify,
  viewportOf,
} from "./render.mjs";

let browser;
before(async () => {
  browser = await launchBrowser();
});
after(async () => {
  await browser?.close();
});

const FONT_LINK =
  '<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&amp;display=swap" rel="stylesheet">';

// 시안 파일과 같은 틀의 작은 템플릿
function template(body, vals, { head = FONT_LINK } = {}) {
  return `<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>t</title>
<script src="./support.js"></script></head><body><x-dc><helmet>${head}<style>body{margin:0}</style></helmet>
${body}
</x-dc>
<script type="text/x-dc" data-dc-script>
class Component extends DCLogic { renderVals() { return ${JSON.stringify(vals)}; } }
</script></body></html>`;
}

async function withRef(name, opts, fn) {
  const ref = await openReference(browser, name, { viewport: { width: 400, height: 300 }, ...opts });
  try {
    return await fn(ref);
  } finally {
    await ref.context.close();
  }
}

// renderVals 배열 길이를 시안 소스에서 따로 센다 (렌더러의 기록에 기대지 않음)
function countTopLevelRows(name) {
  const src = fs.readFileSync(path.join(DESIGN_DIR, `${name}.dc.html`), "utf8");
  const logic = src.match(/<script\b[^>]*type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/)[1];
  const Component = new Function("DCLogic", `${logic}\nreturn Component;`)(class {});
  const vals = new Component().renderVals();
  return Object.fromEntries(Object.entries(vals).filter(([, v]) => Array.isArray(v)).map(([k, v]) => [k, v.length]));
}

test("test_expands_sc_for_and_if", async () => {
  const body = `<ul id="list"><sc-for list="{{items}}" as="it"><li style="color: {{it.color}}">{{it.name}}<sc-for list="{{it.tags}}" as="t"><b>{{t}}</b></sc-for><sc-if value="{{it.note}}"><i>{{it.note}}</i></sc-if></li></sc-for></ul><p>{{title}} · {{count}}</p>`;
  const vals = {
    title: "제목",
    count: 2,
    items: [
      { name: "가", color: "#112233", tags: ["x", "y"], note: "메모" },
      { name: "나", color: "#445566", tags: [], note: "" },
    ],
  };
  await withRef("T", { source: template(body, vals) }, async (ref) => {
    const dom = await ref.page.evaluate(() => ({
      items: [...document.querySelectorAll("#list > li")].map((li) => ({
        text: li.textContent,
        color: li.style.color,
        b: li.querySelectorAll("b").length,
        i: li.querySelectorAll("i").length,
      })),
      p: document.querySelector("p").textContent,
      tags: document.querySelectorAll("sc-for, sc-if, x-dc, helmet").length,
    }));
    assert.deepEqual(dom.items, [
      { text: "가xy메모", color: "rgb(17, 34, 51)", b: 2, i: 1 },
      { text: "나", color: "rgb(68, 85, 102)", b: 0, i: 0 },
    ]);
    assert.equal(dom.p, "제목 · 2");
    assert.equal(dom.tags, 0);
    assert.deepEqual(ref.loops.map((l) => [l.path, l.count]), [
      ["items[0].tags", 2],
      ["items[1].tags", 0],
      ["items", 2],
    ]);
    assert.deepEqual(await verify(ref.page, ref), []);
  });
});

test("test_unknown_template_tag_fails", async () => {
  const cases = [
    ["<sc-switch value=\"{{a}}\"><p>x</p></sc-switch>", { a: 1 }, /지원하지 않는 템플릿 태그: <sc-switch>/],
    ["<p>{{a + 1}}</p>", { a: 1 }, /지원하지 않는 식/],
    ["<p>{{a.missing}}</p>", { a: {} }, /값이 없다/],
    ["<sc-for list=\"{{a}}\" as=\"x\"><p>{{x}}</p></sc-for>", { a: "문자열" }, /배열이 아니다/],
  ];
  for (const [body, vals, message] of cases) {
    await assert.rejects(openReference(browser, "T", { source: template(body, vals), viewport: { width: 200, height: 100 } }), (err) => {
      assert.ok(err instanceof TemplateError, String(err));
      assert.match(err.message, message);
      return true;
    });
  }
});

test("test_no_leftover_mustache", async () => {
  // 실제 시안: 펼친 뒤 {{ 가 하나도 없다
  for (const name of ["Main", "Recorder"]) {
    const ref = await openReference(browser, name);
    try {
      const html = await ref.page.content();
      assert.equal(html.includes("{{"), false, name);
      assert.deepEqual(await verify(ref.page, ref), [], name);
    } finally {
      await ref.context.close();
    }
  }
  // 펼치지 못한 자리(주석 안)가 남으면 대조가 실패한다
  await withRef("T", { source: template("<p>{{a}}</p><!-- {{a}} -->", { a: "x" }) }, async (ref) => {
    const problems = await verify(ref.page, ref);
    assert.ok(problems.some((p) => p.includes("남은 {{")), JSON.stringify(problems));
  });
});

for (const name of ["Main", "Recorder", "Setup0Welcome"]) {
  test(`test_row_counts_and_key_texts_match_render_vals[${name}]`, async () => {
    const expected = countTopLevelRows(name);
    const ref = await openReference(browser, name);
    try {
      assert.deepEqual(await verify(ref.page, ref), []);
      const counts = await ref.page.evaluate((keys) => {
        const out = {};
        for (const k of keys) out[k] = document.querySelectorAll(`[data-dc-row="${k}"]`).length;
        return out;
      }, Object.keys(expected));
      assert.deepEqual(counts, expected);
      if (name === "Main") assert.deepEqual(expected, { graph: 10, tree: 12, nodes: 11, logs: 8 });
      if (name === "Recorder") assert.deepEqual(expected, { steps: 7 });
      if (name === "Setup0Welcome") assert.deepEqual(expected, {});
      // 주요 글자가 실제로 화면에 있다
      const text = await ref.page.evaluate(() => document.body.innerText);
      for (const [key, list] of Object.entries(ref.vals)) {
        if (!Array.isArray(list)) continue;
        for (const item of list) {
          for (const field of ["title", "name", "msg"]) {
            if (typeof item[field] === "string" && item[field]) {
              assert.ok(text.includes(item[field]), `${key}.${field}: ${item[field]}`);
            }
          }
        }
      }
    } finally {
      await ref.context.close();
    }
  });
}

test("test_viewport_per_canvas_board", async () => {
  assert.deepEqual(viewportOf("Main"), { width: 1440, height: 900 });
  assert.deepEqual(viewportOf("Recorder"), { width: 1440, height: 900 });
  assert.deepEqual(viewportOf("Setup0Welcome"), { width: 1120, height: 720 });
  assert.deepEqual(viewportOf("Setup0WelcomeLight"), { width: 1120, height: 720 });
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "kb-design-ref-"));
  try {
    for (const [name, w, h] of [
      ["Main", 1440, 900],
      ["Setup0Welcome", 1120, 720],
    ]) {
      const { file } = await renderToPng(browser, name, out);
      const png = fs.readFileSync(file);
      assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [w, h], name);
    }
  } finally {
    fs.rmSync(out, { recursive: true, force: true });
  }
});

test("test_requested_fonts_all_local_including_fraunces", async () => {
  const ref = await openReference(browser, "Setup0Welcome");
  try {
    const got = ref.fonts.map((f) => `${f.family} ${f.weight} ${f.loaded}`).sort();
    assert.deepEqual(got, [
      "Fraunces 700 true",
      "JetBrains Mono 400 true",
      "JetBrains Mono 500 true",
      "Noto Sans KR 400 true",
      "Noto Sans KR 500 true",
      "Noto Sans KR 700 true",
    ]);
    // 워드마크가 실제로 Fraunces로 그려진다 (대체 글꼴 Georgia가 아님)
    const wordmark = await ref.page.evaluate(() => {
      const el = [...document.querySelectorAll("span")].find((s) => s.textContent === "Kookabug");
      return { family: getComputedStyle(el).fontFamily, ok: document.fonts.check('700 40px "Fraunces"', "Kookabug") };
    });
    assert.match(wordmark.family, /^Fraunces/);
    assert.equal(wordmark.ok, true);
  } finally {
    await ref.context.close();
  }
  // 시안이 요청한 글꼴에 로컬 판이 없으면 실패한다
  const head = '<link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400&amp;display=swap" rel="stylesheet">';
  await assert.rejects(openReference(browser, "T", { source: template("<p>a</p>", {}, { head }) }), /로컬 판이 없는 글꼴: Roboto/);
  // 로컬 판에 없는 굵기도 실패다
  const head2 = '<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,650&amp;display=swap" rel="stylesheet">';
  await assert.rejects(openReference(browser, "T", { source: template("<p>a</p>", {}, { head: head2 }) }), /굵기가 없다: Fraunces 650/);
});

test("test_fonts_local_no_network", async () => {
  for (const name of ["Main", "Setup0Welcome"]) {
    const ref = await openReference(browser, name);
    try {
      assert.deepEqual(ref.external, [], name);
      const sheets = await ref.page.evaluate(() => [...document.styleSheets].map((s) => s.href).filter(Boolean));
      assert.ok(sheets.length > 0);
      for (const href of sheets) assert.match(href, /^http:\/\/design-ref\.local\/fonts\/@fontsource\//);
    } finally {
      await ref.context.close();
    }
  }
  // 가로채기가 실제로 바깥 요청을 잡는다
  const body = '<img src="https://example.com/x.png" alt="">';
  await withRef("T", { source: template(body, {}) }, async (ref) => {
    await ref.page.waitForLoadState("load");
    assert.deepEqual(ref.external, ["https://example.com/x.png"]);
  });
});

test("test_broken_reference_detected", async () => {
  const ref = await openReference(browser, "Main");
  try {
    assert.deepEqual(await verify(ref.page, ref), []);
    // 노드 하나를 지운 기준 렌더
    await ref.page.evaluate(() => document.querySelectorAll('[data-dc-row="graph"]')[3].remove());
    const problems = await verify(ref.page, ref);
    assert.ok(problems.some((p) => p.startsWith("graph: 줄 9개, renderVals 10개")), JSON.stringify(problems));
    assert.ok(problems.some((p) => p.includes("graph[3].title 글자가 화면에 없다")), JSON.stringify(problems));
  } finally {
    await ref.context.close();
  }
  // 행 표시가 남아도 글자가 바뀌면 잡는다
  const ref2 = await openReference(browser, "Main");
  try {
    await ref2.page.evaluate(() => {
      const row = document.querySelectorAll('[data-dc-row="logs"]')[1];
      row.lastElementChild.textContent = "다른 글자";
    });
    const problems = await verify(ref2.page, ref2);
    assert.ok(problems.some((p) => p.startsWith("logs[1].msg")), JSON.stringify(problems));
  } finally {
    await ref2.context.close();
  }
});
