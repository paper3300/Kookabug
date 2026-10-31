import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { after, before, test } from "node:test";
import { compare } from "./compare.mjs";
import { launchBrowser, renderToPng } from "./render.mjs";

let browser;
let tmp;
before(async () => {
  browser = await launchBrowser();
  tmp = fs.mkdtempSync(path.join(os.tmpdir(), "kb-compare-"));
});
after(async () => {
  await browser?.close();
  fs.rmSync(tmp, { recursive: true, force: true });
});

test("compare writes side by side png", async () => {
  const { file: ref } = await renderToPng(browser, "Setup0Welcome", tmp);
  const outFile = path.join(tmp, "out", "welcome-dark.png");
  await compare(browser, "welcome", "dark", { refFile: ref, appFile: ref, outFile });
  const png = fs.readFileSync(outFile);
  // 두 장(1120×720) + 간격 16×3, 글자 줄 28 + 간격 16×2
  assert.deepEqual([png.readUInt32BE(16), png.readUInt32BE(20)], [1120 * 2 + 48, 720 + 28 + 32]);
  assert.equal(fs.existsSync(outFile.replace(/\.png$/, ".html")), false);
});
