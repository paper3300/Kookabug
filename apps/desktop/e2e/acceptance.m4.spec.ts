// M4 완료 기준 인수 검사, 앱 쪽 (M4 계획 3장 "M4 완료 기준 → 테스트 매핑"). 실제 Electron 앱 + 실제 daemon(레포 .venv) +
// 예제 워크스페이스 사본 + 가짜 플랫폼 + 가짜 각본(예제 로그인, 쉬었다 이어 친 비밀번호·Backspace). 다른 검사 모듈은
// 가져오지 않고 helpers만 쓴다.
//
// 1. 예제 게임 로그인을 녹화한 그래프가 바로 재생 통과 — 녹화 → 화면 확인 넣기 → 정지 → 비밀값 키 → 새 테스트로 저장 →
//    F5 pass (게임 띄우기 노드부터, 화면 확인으로 끝)
// 4. 비밀번호 칸 입력은 글자 그대로 저장하지 않고 `$secret` 참조를 요구 — 비밀값 띠가 키를 고를 때까지 저장을 막고,
//    사이드바·그래프 파일에 원문이 없다
// (범위) target 편집기 확장 — 민감 대상 저장, 같은 모양 N곳, 다른 배율 점수
//
// Python 쪽 인수는 python/kookabug_core/tests/acceptance/test_m4.py. 사람 입력(실제 훅)은 Docs/verification/m4-manual.md
import fs from "node:fs";
import { expect, test } from "@playwright/test";
import { filePath, readJson, writeFile } from "./helpers/editor";
import { encodePng } from "./helpers/png";
import {
  ACCOUNT_TEXT,
  chooseSecret,
  insertLobbyCheck,
  openRecorderApp,
  prepareRecorderWorkspace,
  saveButton,
  saveNewTest,
  SECRET_KEY,
  SECRET_TEXT,
  sidebar,
  startLaunch,
  stopRecording,
  waitLoginRecorded,
} from "./helpers/recorder";
import { closeRunApp, openRunApp, prepareRunWorkspace, waitEnded, type RunSession } from "./helpers/run";
import { addCapture, editorOf, frameOf, loadFrame, openExtPanels, openTarget, readTarget, saveTargetTab, selectRect, START_BUTTON, waitPreview } from "./helpers/target";

test.setTimeout(240_000);

let s: RunSession | null = null;

test.afterEach(async () => {
  await closeRunApp(s);
  s = null;
});

type Graph = { nodes: Record<string, { type: string; in?: Record<string, unknown>; next?: Record<string, string> }> };

/** entry에서 next를 따라간 노드 종류 차례 */
function chainTypes(graph: Graph): string[] {
  const out: string[] = [];
  let cur: string | undefined = "n_entry";
  const seen = new Set<string>();
  while (cur !== undefined && !seen.has(cur) && graph.nodes[cur] !== undefined) {
    seen.add(cur);
    out.push(graph.nodes[cur].type);
    cur = Object.values(graph.nodes[cur].next ?? {})[0];
  }
  return out;
}

test("test_record_save_f5_pass", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await startLaunch(page);
  await waitLoginRecorded(page);
  await insertLobbyCheck(page);
  await stopRecording(page);
  await chooseSecret(page);
  const rel = await saveNewTest(page, "m4_login");
  const graph = readJson<Graph>(ws.root, rel);
  const chain = chainTypes(graph);
  expect(chain.slice(0, 2)).toEqual(["core.graph.entry", "core.app.launch"]);
  expect(chain).toContain("core.image.click");
  expect(chain.filter((t) => t === "core.input.type_text")).toHaveLength(2);
  expect(chain.at(-1)).toBe("core.assert.visible");
  // 녹화가 끝나 저장한 그래프가 앞 탭 — F5로 바로 재생 (가짜 플랫폼 runner, 고른 비밀값으로 로그인 → 로비 확인)
  await page.locator(`[data-part="canvas"][data-path="${rel}"]`).click({ position: { x: 5, y: 5 } });
  await page.keyboard.press("F5");
  await waitEnded(page, "pass", 120_000);
});

test("test_secret_banner_blocks_save_until_key", async () => {
  const ws = prepareRecorderWorkspace();
  s = await openRecorderApp(ws);
  const { page } = s;
  await startLaunch(page);
  await waitLoginRecorded(page);
  // 쉬었다 이어 친 비밀번호·Backspace가 비밀값 스텝 하나 (● × 길이), 원문은 화면 어디에도 없다
  const secretSteps = page.locator('[data-part="rec-step"][data-text-state="secret"]');
  await expect(secretSteps).toHaveCount(1);
  await expect(secretSteps.locator('[data-part="rec-raw"]')).toContainText("●".repeat(SECRET_TEXT.length));
  await expect(page.locator('[data-part="rec-step"][data-text-state="ordinary"] [data-part="rec-raw"]')).toContainText(ACCOUNT_TEXT);
  await insertLobbyCheck(page);
  await stopRecording(page);
  await expect(page.locator("body")).not.toContainText(SECRET_TEXT);
  // 키를 고르기 전: 비밀값 띠 + 저장·삽입 단추가 꺼짐(이유 툴팁)
  const row = page.locator('[data-part="secret-row"]');
  await expect(row).toHaveCount(1);
  await expect(row).toContainText("비밀번호 칸에 입력했어요");
  await expect(saveButton(page)).toBeDisabled();
  await expect(saveButton(page)).toHaveAttribute("title", "비밀값을 고르면 저장할 수 있어요");
  await chooseSecret(page);
  await expect(saveButton(page)).toBeEnabled();
  const rel = await saveNewTest(page, "m4_secret");
  // 그래프: 비밀값은 $secret 키 한 번(clear), 원문 바이트 없음, 일반 글자는 그대로
  const text = fs.readFileSync(filePath(ws.root, rel), "utf8");
  expect(text).not.toContain(SECRET_TEXT);
  expect(text).not.toContain("pass-01");
  expect(text).toContain(ACCOUNT_TEXT);
  const graph = readJson<Graph>(ws.root, rel);
  const secretNodes = Object.values(graph.nodes).filter((n) => JSON.stringify(n.in ?? {}).includes('"$secret"'));
  expect(secretNodes).toHaveLength(1);
  expect(secretNodes[0].in?.text).toEqual({ $secret: SECRET_KEY });
  expect(secretNodes[0].in?.clear).toBe(true);
  await expect(sidebar(page)).not.toContainText(SECRET_TEXT);
});

/** 같은 무늬 셋이 있는 장면 (400x300, 무늬 40x30, 정해진 의사 난수) */
const PATTERN = [40, 30] as const;
const PATTERN_AT = [
  [60, 50],
  [280, 190],
  [170, 230],
] as const;

function patternScene(): Buffer {
  const [w, h] = [400, 300];
  let seed = 7;
  const next = () => {
    seed = (seed * 1103515245 + 12345) >>> 0;
    return (seed >>> 16) & 0xff;
  };
  const rgb = new Uint8Array(w * h * 3);
  for (let i = 0; i < rgb.length; i++) rgb[i] = next();
  const pattern = new Uint8Array(PATTERN[0] * PATTERN[1] * 3);
  seed = 11;
  for (let i = 0; i < pattern.length; i++) pattern[i] = next();
  for (const [px, py] of PATTERN_AT) {
    for (let y = 0; y < PATTERN[1]; y++) {
      const src = y * PATTERN[0] * 3;
      rgb.set(pattern.subarray(src, src + PATTERN[0] * 3), ((py + y) * w + px) * 3);
    }
  }
  return encodePng(w, h, rgb);
}

test("test_target_editor_ext_sensitive_peaks_scale", async () => {
  const ws = prepareRunWorkspace();
  addCapture(ws.root, "title.png");
  writeFile(ws.root, "captures/pattern_three.png", patternScene());
  s = await openRunApp(ws);
  const { page } = s;
  const START = "targets/title/start_button.target.json";
  const before = readTarget(ws.root, START);
  await openTarget(page, START);
  // 민감 대상: 저장하면 키가 생기고 다른 키는 그대로
  const sensitive = page.getByRole("checkbox", { name: "민감 대상" });
  await sensitive.check();
  await expect(editorOf(page, START)).toHaveAttribute("data-dirty", "true");
  await saveTargetTab(page, START);
  const saved = readTarget(ws.root, START);
  expect(saved.sensitive).toBe(true);
  for (const key of ["click", "format", "image", "recorded"]) expect(saved[key]).toEqual(before[key]);
  // 같은 모양 N곳: 무늬가 셋인 화면에서 3곳 + 점선 상자 둘
  await loadFrame(page, "captures/pattern_three.png");
  const [x, y] = PATTERN_AT[0];
  await selectRect(page, [x, y, PATTERN[0], PATTERN[1]]);
  await waitPreview(page, true);
  const same = page.locator('[data-part="same-shape"]');
  await expect(same).toHaveAttribute("data-count", "3");
  await expect(frameOf(page).locator('[data-part="peak-rect"]')).toHaveCount(2);
  // 다른 배율 점수: 1.00·1.25·1.50·2.00배
  await openExtPanels(page);
  const rows = page.locator('[data-part="scale-table"] tbody tr');
  await expect(rows).toHaveCount(4, { timeout: 30_000 });
  expect(await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-factor")))).toEqual(["1", "1.25", "1.5", "2"]);
  // 하나뿐인 시작 버튼은 같은 모양 표시 없음
  await loadFrame(page, "captures/title.png");
  await frameOf(page).scrollIntoViewIfNeeded();
  await selectRect(page, START_BUTTON);
  await waitPreview(page, true);
  await expect(same).toHaveCount(0);
});
