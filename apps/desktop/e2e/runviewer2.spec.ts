// 기록 뷰어 2 (M3 계획 T11 완료 기준, 2.8·2.10): 지난 성공과 비교·노드별 통계·영상·분석 번들 내보내기·에디터에서 재현.
// 실제 daemon + 가짜 플랫폼(예제 장면). 실행을 만드는 데 시간이 들어 앱 하나·워크스페이스 하나를 검사들이 차례로
// 같이 쓴다 (serial). 실행 만들기:
// - 비교: 같은 테스트(viewer_compare)를 게임 인수 `--maintenance`(통과, 기준) → 프로필 maintenance(통과, 다른 기준
//   후보) → 기본(시작 단추 뒤 로그인 화면이라 실패) 순서로 돌린다. 기준과 화면(점검 팝업 ↔ 로그인)·환경(게임 인수)이
//   다르다
// - 영상: 워크스페이스 영상 정책을 failed_only로 바꿔 실패 실행의 실제 MSMF 조각을 남긴다(이 PC에 Media Foundation이
//   있을 때). 재생·탐색·빈 구간은 레포의 표본 H.264(fixtures/video-sample.mp4, 칸마다 색)로 조각을 바꿔 넣은 사본
//   실행으로 늘 검사한다 — CI 호스트에 MF가 없어도 된다
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { canvasOf } from "./helpers/editor";
import { decodePng, dominant, pixel } from "./helpers/png";
import { closeRunApp, openRunApp, prepareRunWorkspace, toolbar, type RunSession } from "./helpers/run";
import {
  cloneRun,
  rowOfNode,
  runEnd,
  runFolderOf,
  runItem,
  runTab,
  runToEnd,
  setLocalGameArgs,
  setWorkspaceVideo,
  showRunList,
  startRun,
  timelineRow,
  VIEWER_CHECK,
  VIEWER_CMP,
  VIEWER_FAIL,
  waitRunEnded,
  writeViewerGraphs,
} from "./helpers/runs";

test.describe.configure({ mode: "serial" });

const SAMPLE = path.join(import.meta.dirname, "fixtures", "video-sample.mp4");
/** 표본 영상을 넣은 사본 실행 */
const VIDEO_RUN = "v1de0a01";

let s: RunSession | null = null;
const runs: Record<"base" | "other" | "fail" | "prof", string> = { base: "", other: "", fail: "", prof: "" };
let out = "";

test.beforeAll(async () => {
  test.setTimeout(600_000);
  const ws = prepareRunWorkspace();
  writeViewerGraphs(ws);
  setWorkspaceVideo(ws, "failed_only");
  out = fs.mkdtempSync(path.join(os.tmpdir(), "kb-export-"));
  s = await openRunApp(ws);
  const { page } = s;
  setLocalGameArgs(ws, ["-m", "sample_game", "--maintenance"]);
  runs.base = await runToEnd(page, VIEWER_CMP, "pass");
  setLocalGameArgs(ws, null);
  runs.other = await startRun(page, VIEWER_CMP, "maintenance");
  expect(await waitRunEnded(page, runs.other)).toBe("pass");
  runs.fail = await runToEnd(page, VIEWER_CMP, "fail");
  runs.prof = await startRun(page, VIEWER_FAIL, "login_fail");
  expect(await waitRunEnded(page, runs.prof)).toBe("fail");
  plantSampleVideo(runs.fail, VIDEO_RUN);
});

test.afterAll(async () => {
  await closeRunApp(s);
  s = null;
  if (out !== "") fs.rmSync(out, { recursive: true, force: true });
});

function session(): RunSession {
  if (s === null) throw new Error("앱이 없다");
  return s;
}

/** 목록에서 한 번 눌러 RUN 탭을 연다 */
async function openFromList(page: Page, runId: string): Promise<void> {
  await showRunList(page);
  await expect(runItem(page, runId)).toBeVisible({ timeout: 15_000 });
  await runItem(page, runId).click();
  await expect(runTab(page, runId)).toHaveAttribute("data-jumped", "true", { timeout: 15_000 });
}

function events(runId: string): Record<string, unknown>[] {
  return fs
    .readFileSync(path.join(runFolderOf(session().ws, runId), "events.jsonl"), "utf8")
    .split("\n")
    .filter((l) => l.trim() !== "")
    .map((l) => JSON.parse(l) as Record<string, unknown>);
}

function stepStart(runId: string, node: string): { step: string; t: number } {
  const e = events(runId).find((x) => x.event === "step.start" && x.node === node);
  if (e === undefined) throw new Error(`${node} 스텝이 없다`);
  return { step: e.step as string, t: Date.parse(e.t as string) };
}

const iso = (ms: number) => new Date(ms).toISOString();

/**
 * 실패 실행을 복사해 영상 폴더를 표본으로 바꾼다: 조각 1 = 실패 스텝 시작 3초 전부터 3초(15칸, 빨강·초록·파랑),
 * 빈 구간 = 실패 스텝 시작 50 ms 뒤부터 (비밀값, 실제 녹화기처럼 격자에 맞지 않는 차단 시각 — 조각 끝과 사이에 칸보다
 * 짧은 틈), 조각 2 = 실패 스텝 시작 1초 뒤부터 3초
 */
function plantSampleVideo(from: string, id: string): void {
  const ws = session().ws;
  const folder = cloneRun(ws, from, id, {});
  const failure = stepStart(id, "n_wait_popup").t;
  const video = path.join(folder, "video");
  fs.rmSync(video, { recursive: true, force: true });
  fs.mkdirSync(video);
  const bytes = fs.statSync(SAMPLE).size;
  const seg = (file: string, t0: number) => ({
    bytes,
    file,
    frame_ms: 200,
    frames: 15,
    mode: "failed_only",
    size: [160, 96],
    t0: iso(t0),
    t_end: iso(t0 + 3000),
    window: "SampleRPG",
  });
  for (const f of ["seg-0001.mp4", "seg-0002.mp4"]) fs.copyFileSync(SAMPLE, path.join(video, f));
  // 쓰는 중 조각(재생할 수 없음)은 kbimg가 주지 않는다
  fs.copyFileSync(SAMPLE, path.join(video, "seg-0003.part.mp4"));
  const index = {
    bytes: bytes * 2,
    deleted: [],
    format: "kookabug.video-index/0",
    gaps: [{ gap: "secret_input", t_start: iso(failure + 50), t_end: iso(failure + 1000) }],
    segments: [seg("seg-0001.mp4", failure - 3000), seg("seg-0002.mp4", failure + 1000)],
    status: "recorded",
  };
  fs.writeFileSync(path.join(video, "index.json"), JSON.stringify(index));
}

const COLORS = ["red", "green", "blue"] as const;

/**
 * 영상이 그 위치에 멈춰 그 칸을 그렸을 때까지. 마지막 칸(마지막 프레임 시각 이후)으로 옮기면 Chromium은 끝난
 * 것으로 보고 위치를 길이로 올린다 — 그래도 보이는 것은 마지막 프레임이다
 */
async function waitFrame(page: Page, seconds: number, last = false): Promise<void> {
  const video = page.locator('[data-part="video"]');
  await expect
    .poll(
      () =>
        video.evaluate(
          (v: HTMLVideoElement, [want, end]) => ({
            ready: v.readyState >= 2 && !v.seeking && v.videoWidth > 0,
            at: Math.abs(v.currentTime - want) < 0.005 || (end && v.currentTime >= want - 0.005 && v.currentTime <= v.duration + 0.001),
            paused: v.paused,
            t: v.currentTime,
          }),
          [seconds, last] as const,
        ),
      { timeout: 15_000 },
    )
    .toMatchObject({ ready: true, at: true, paused: true });
}

/** 영상 가운데 픽셀의 색 (표본: 칸 0~4 빨강, 5~9 초록, 10~14 파랑) */
async function frameColor(page: Page): Promise<string> {
  const shot = await page.locator('[data-part="video"]').screenshot();
  const png = decodePng(shot);
  return dominant(pixel(png, png.width / 2, png.height / 3));
}

test("test_compare_box_graph_env_time_screen", async () => {
  const { page } = session();
  await openFromList(page, runs.fail);
  const tab = runTab(page, runs.fail);
  const failure = runEnd(session().ws, runs.fail).failure_step as string;
  await expect(tab).toHaveAttribute("data-selected", failure);
  // 스텝 타임라인 아래 비교 상자: 자동 기준 = 같은 테스트·같은 프로필·통과 중 가장 최근(프로필이 다른 실행은 빠짐)
  const box = page.locator('[data-part="compare-box"]');
  await expect(box).toHaveAttribute("data-baseline", runs.base, { timeout: 30_000 });
  await expect(box).toContainText(`#${runs.base.slice(0, 4)} (성공) 과 차이`);
  // 화면: 점검 팝업(기준 썸네일) ↔ 로그인 화면(실패 증거) → 차이 영역
  await expect(box.locator('[data-part="compare-screen"]')).toHaveAttribute("data-differs", "true");
  await expect(box.locator('[data-part="compare-screen"]')).toContainText(/영역 \d+곳 \(화면 차이 \d+%\)/);
  // 그래프: 같은 파일 → 같음 · 해시 6자
  await expect(box.locator('[data-part="compare-graph"]')).toHaveText(/^같음 · [0-9a-f]{6}$/);
  // 환경: 게임 인수가 다르다 (local.json)
  await expect(box.locator('[data-part="compare-env"]')).toHaveAttribute("data-differs", "true");
  await expect(box.locator('[data-part="compare-env"]')).toContainText("game.args");
  await expect(box.locator('[data-part="compare-time"]')).not.toBeEmpty();

  // 비교 탭: 이름에 기준 ID, 두 화면 나란히 + 차이 영역 상자
  const subtab = page.locator('[data-part="subtab-compare"]');
  await expect(subtab).toHaveText(`#${runs.base.slice(0, 4)} 과 비교`);
  await subtab.click();
  await expect(page.locator('[data-part="compare-tab"]')).toBeVisible();
  const mine = page.locator('[data-part="compare-image"]');
  await expect(mine).toHaveJSProperty("complete", true);
  expect(await mine.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('[data-part="diff-box"]').first()).toBeVisible();
  const base = page.locator('[data-part="baseline-image"]');
  await expect(base).toHaveJSProperty("complete", true);
  expect(await base.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  expect(await base.getAttribute("src")).toContain(runs.base);
  await expect(page.locator('[data-part="compare-env-table"]')).toContainText("game.args");
  await expect(page.locator('[data-part="compare-time-table"]')).toContainText("점검 팝업 대기");
});

test("test_pick_other_baseline", async () => {
  const { page } = session();
  await openFromList(page, runs.fail);
  await page.locator('[data-part="subtab-compare"]').click();
  const select = page.locator('[data-part="baseline-select"]');
  // 같은 테스트의 끝난 실행 (이 실행 제외)
  await expect(select.locator(`option[value="${runs.other}"]`)).toHaveCount(1);
  await expect(select.locator(`option[value="${runs.fail}"]`)).toHaveCount(0);
  await select.selectOption(runs.other);
  const box = page.locator('[data-part="compare-box"]');
  await expect(box).toHaveAttribute("data-baseline", runs.other, { timeout: 30_000 });
  await expect(box).toContainText(`#${runs.other.slice(0, 4)} (고른 실행) 과 차이`);
  await expect(page.locator('[data-part="subtab-compare"]')).toHaveText(`#${runs.other.slice(0, 4)} 과 비교`);
  // 고른 기준은 프로필이 다르다
  await expect(page.locator('[data-part="compare-env-table"]')).toContainText("conditions.profile");
  // 자동으로 되돌린다
  await select.selectOption("");
  await expect(box).toHaveAttribute("data-baseline", runs.base, { timeout: 30_000 });
});

test("test_node_stats_row_jumps_to_last_failure", async () => {
  const { page } = session();
  const failure = runEnd(session().ws, runs.prof).failure_step as string;
  await openFromList(page, runs.prof);
  // 다른 스텝을 고르고 실패 사슬을 접는다
  await page.locator('[data-part="timeline-row"]').first().click();
  await rowOfNode(page, "n_call").locator('[data-part="timeline-toggle"]').click();
  await expect(timelineRow(page, failure)).toHaveCount(0);
  await page.locator('[data-part="subtab-stats"]').click();
  const row = page.locator('[data-part="stats-row"][data-node="n_wait_missing"]');
  await expect(row).toHaveAttribute("data-graph", VIEWER_CHECK);
  await expect(row).toHaveAttribute("data-last-failure", failure);
  // 횟수·실패 수
  await expect(row.locator("td").nth(2)).toHaveText("1");
  await expect(row.locator("td").nth(4)).toHaveText("1");
  await row.click();
  const tab = runTab(page, runs.prof);
  await expect(page.locator('[data-part="subtab-timeline"]')).toHaveAttribute("aria-selected", "true");
  await expect(tab).toHaveAttribute("data-selected", failure);
  await expect(timelineRow(page, failure)).toHaveAttribute("aria-selected", "true");
  await expect(timelineRow(page, failure)).toBeInViewport();
  await expect(rowOfNode(page, "n_call")).toHaveAttribute("aria-expanded", "true");
});

test("test_video_tab_seeks_to_step_and_shows_gap_reason", async () => {
  const { page, app, ws } = session();
  // ① 표본 영상 (늘): 실패 스텝 시각은 비밀값 빈 구간, 그 앞 스텝은 조각 1의 그 칸
  await openFromList(page, VIDEO_RUN);
  const toggle = page.locator('[data-part="media-toggle"]');
  await expect(toggle).toBeVisible();
  await page.locator('[data-part="media-video"]').click();
  const player = page.locator('[data-part="video-player"]');
  await expect(player).toHaveAttribute("data-state", "gap");
  await expect(player).toHaveAttribute("data-gap", "secret_input");
  await expect(page.locator('[data-part="video-gap"]')).toContainText("영상 없음 · 비밀값 입력");

  const failure = stepStart(VIDEO_RUN, "n_wait_popup").t;
  let checked = 0;
  for (const node of ["n_click", "n_wait_title"]) {
    const at = stepStart(VIDEO_RUN, node);
    const offset = at.t - (failure - 3000);
    if (offset < 0) continue; // 조각 1보다 앞 (긴 타이틀 대기)
    checked++;
    const slot = Math.min(14, Math.floor(offset / 200));
    await timelineRow(page, at.step).click();
    await expect(player).toHaveAttribute("data-state", "segment");
    await expect(player).toHaveAttribute("data-segment", "seg-0001.mp4");
    const seconds = (slot * 200 + 100) / 1000;
    await expect(player).toHaveAttribute("data-seek-target", String(seconds));
    await waitFrame(page, seconds, slot === 14);
    // 멈춘 채 옮긴 마지막 칸은 다음 조각으로 넘어가지 않는다
    await page.waitForTimeout(1500);
    await expect(player).toHaveAttribute("data-segment", "seg-0001.mp4");
    expect(await frameColor(page)).toBe(COLORS[Math.floor(slot / 5)]);
  }
  // 클릭 스텝은 실패 스텝 바로 앞이라 늘 조각 1 안이다
  expect(checked).toBeGreaterThan(0);
  // 빈 구간에서 다음 영상부터 → 조각 2를 처음부터 재생 (Range 요청으로 이어 읽는다)
  await timelineRow(page, stepStart(VIDEO_RUN, "n_wait_popup").step).click();
  await expect(player).toHaveAttribute("data-state", "gap");
  await page.getByRole("button", { name: "다음 영상부터 재생" }).click();
  await expect(player).toHaveAttribute("data-segment", "seg-0002.mp4");
  await expect
    .poll(() => page.locator('[data-part="video"]').evaluate((v: HTMLVideoElement) => v.currentTime), { timeout: 15_000 })
    .toBeGreaterThan(0.3);

  // 조각 1을 끝까지 재생하면 사이 빈 구간 이유를 잠깐 보이고 조각 2로 저절로 넘어간다 (VideoPlayer onEnded, T11 검수 2)
  await player.evaluate((el) => {
    const seen: string[] = [];
    (window as unknown as { __videoStates: string[] }).__videoStates = seen;
    const note = () => {
      const s = `${el.getAttribute("data-state")}:${el.getAttribute("data-state") === "gap" ? el.getAttribute("data-gap") : el.getAttribute("data-segment")}`;
      if (seen.at(-1) !== s) seen.push(s);
    };
    note();
    new MutationObserver(note).observe(el, { attributes: true });
  });
  await page.getByRole("button", { name: "조각 1 재생" }).click();
  await expect(player).toHaveAttribute("data-segment", "seg-0001.mp4");
  await expect(player).toHaveAttribute("data-state", "gap", { timeout: 15_000 });
  await expect(page.locator('[data-part="video-gap"]')).toContainText("영상 없음 · 비밀값 입력");
  await expect(player).toHaveAttribute("data-segment", "seg-0002.mp4", { timeout: 15_000 });
  await expect(player).toHaveAttribute("data-state", "segment");
  await expect
    .poll(() => page.locator('[data-part="video"]').evaluate((v: HTMLVideoElement) => !v.paused && v.currentTime > 0.2), { timeout: 15_000 })
    .toBe(true);
  const states = await page.evaluate(() => (window as unknown as { __videoStates: string[] }).__videoStates);
  const from = states.lastIndexOf("segment:seg-0001.mp4");
  expect(states.slice(from)).toEqual(["segment:seg-0001.mp4", "gap:secret_input", "segment:seg-0002.mp4"]);

  // kbimg 영상: Range 요청은 206 부분 응답 (실제 처리기), 쓰는 중 조각은 주지 않는다 (T7 검수 Low)
  const runDir = path.basename(runFolderOf(ws, VIDEO_RUN));
  const url = (file: string) => `kbimg://ws/runs/${runDir}/video/${file}`;
  const part = await app.evaluate(async ({ net }, u) => {
    const r = await net.fetch(u, { headers: { Range: "bytes=10-109" } });
    return { status: r.status, range: r.headers.get("content-range"), length: (await r.arrayBuffer()).byteLength };
  }, url("seg-0001.mp4"));
  expect(part).toEqual({ status: 206, range: `bytes 10-109/${fs.statSync(SAMPLE).size}`, length: 100 });
  const writing = await app.evaluate(async ({ net }, u) => (await net.fetch(u)).status, url("seg-0003.part.mp4"));
  expect(writing).toBe(404);

  // ② 실제 녹화 (이 PC에 Media Foundation이 있으면): 실패 실행의 조각이 남고 앱에서 재생·탐색된다
  const video = JSON.parse(fs.readFileSync(path.join(runFolderOf(ws, runs.fail), "run.json"), "utf8")).video as
    | { status: string; kept?: number; reason?: string }
    | undefined;
  if (video?.status !== "recorded" || (video.kept ?? 0) === 0) {
    expect(process.env.KOOKABUG_MEDIA_TESTS, `실제 영상 없음: ${JSON.stringify(video)}`).not.toBe("require");
    test.info().annotations.push({ type: "media", description: `실제 MSMF 영상 없음 (${JSON.stringify(video)}) — 표본 영상만 검사` });
    return;
  }
  // 성공한 실행의 영상은 지워졌다
  const passVideo = JSON.parse(fs.readFileSync(path.join(runFolderOf(ws, runs.base), "run.json"), "utf8")).video as { kept?: number };
  expect(passVideo?.kept ?? 0).toBe(0);
  await openFromList(page, runs.fail);
  await page.locator('[data-part="media-video"]').click();
  const index = JSON.parse(fs.readFileSync(path.join(runFolderOf(ws, runs.fail), "video", "index.json"), "utf8")) as {
    segments: { t0: string; frames: number; frame_ms: number; file: string }[];
  };
  expect(index.segments.length).toBeGreaterThan(0);
  // 조각 안에서 시작한 (지금 타임라인에 보이는) 스텝으로 탐색한다
  const visible = new Set(await page.locator('[data-part="timeline-row"]').evaluateAll((rows) => rows.map((r) => r.getAttribute("data-step"))));
  let hit: { step: string; seg: (typeof index.segments)[number]; t: number } | null = null;
  for (const e of events(runs.fail)) {
    if (e.event !== "step.start" || !visible.has(e.step as string)) continue;
    const t = Date.parse(e.t as string);
    const seg = index.segments.find((x) => t >= Date.parse(x.t0) && t < Date.parse(x.t0) + x.frames * x.frame_ms);
    if (seg !== undefined) hit = { step: e.step as string, seg, t };
  }
  // 그래프가 타이틀 뒤 녹화 준비 대기(n_settle)를 두어 그 뒤 스텝은 조각 안에서 시작한다 — 실제 조각 안 탐색을 꼭 거친다
  expect(hit, `조각 안에서 시작한 스텝 없음: ${JSON.stringify(index.segments)}`).not.toBeNull();
  await timelineRow(page, hit!.step).click();
  await expect(player).toHaveAttribute("data-state", "segment");
  await expect(player).toHaveAttribute("data-segment", hit!.seg.file);
  const slot = Math.min(hit!.seg.frames - 1, Math.floor((hit!.t - Date.parse(hit!.seg.t0)) / hit!.seg.frame_ms));
  const seconds = (slot * hit!.seg.frame_ms + hit!.seg.frame_ms / 2) / 1000;
  await expect(player).toHaveAttribute("data-seek-target", String(seconds));
  await waitFrame(page, seconds, slot === hit!.seg.frames - 1);
  expect(await page.locator('[data-part="video"]').evaluate((v: HTMLVideoElement) => v.videoWidth)).toBeGreaterThan(0);
  test.info().annotations.push({ type: "media", description: `실제 조각 안 탐색: ${hit!.seg.file} 칸 ${slot}/${hit!.seg.frames}` });
  await expect(page.locator('[data-part="video-error"]')).toHaveCount(0);
});

test("test_export_bundle_zip_contains_run_folder", async () => {
  const { page, app, ws } = session();
  await openFromList(page, runs.fail);
  const stub = async (picked: string | null) =>
    app.evaluate(({ dialog }, p) => {
      dialog.showSaveDialog = (async () => (p === null ? { canceled: true, filePath: "" } : { canceled: false, filePath: p })) as never;
    }, picked);
  const button = page.locator('[data-part="export-bundle"]');
  const notice = page.locator('[data-part="run-notice"]');
  // 취소하면 아무것도 쓰지 않는다
  await stub(null);
  await button.click();
  await expect(notice).toHaveCount(0);
  expect(fs.readdirSync(out)).toEqual([]);
  // 고른 곳에 zip
  const dest = path.join(out, "bundle.zip");
  await stub(dest);
  await button.click();
  await expect(notice).toHaveAttribute("data-tone", "info");
  await expect(notice).toContainText("분석 번들을 내보냈어요");
  await expect(notice).toContainText("bundle.zip");
  const folder = path.basename(runFolderOf(ws, runs.fail));
  const zip = fs.readFileSync(dest);
  // zip 항목 이름은 압축하지 않고 적힌다
  for (const name of ["events.jsonl", "run.json", `snapshot/${VIEWER_CMP}`]) expect(zip.includes(Buffer.from(`${folder}/${name}`))).toBe(true);
  expect(fs.readdirSync(out)).toEqual(["bundle.zip"]);
  // 실행 기록 폴더 안에는 내보내지 않는다 (T7 검수 Low)
  const inside = path.join(runFolderOf(ws, runs.fail), "bundle.zip");
  await stub(inside);
  await button.click();
  await expect(notice).toHaveAttribute("data-tone", "error");
  await expect(notice).toContainText("runs/");
  expect(fs.existsSync(inside)).toBe(false);
});

test("test_reproduce_opens_graph_sets_breakpoint_selects_profile_no_autorun", async () => {
  const { page } = session();
  await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
  const before = ((await page.evaluate(() => window.kookabug.rpc("run.list", { limit: 100 }))) as { runs: unknown[] }).runs.length;
  await openFromList(page, runs.prof);
  await page.locator('[data-part="reproduce"]').click();
  // 테스트 그래프 탭이 열리고 (서브그래프 안 실패면 루트의 호출 노드를 고른다)
  const graphTab = page.locator(`[role="tab"][data-path="${VIEWER_FAIL}"]`);
  await expect(graphTab).toHaveAttribute("aria-selected", "true");
  await expect(canvasOf(page, VIEWER_FAIL)).toHaveAttribute("data-status", "ready");
  await expect(canvasOf(page, VIEWER_FAIL).locator('.react-flow__node[data-id="n_call"]')).toHaveClass(/selected/);
  // 실패 노드(서브그래프 파일)에 브레이크포인트
  await expect
    .poll(async () => ((await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.get", {}))) as { breakpoints: unknown[] }).breakpoints)
    .toEqual([{ graph: VIEWER_CHECK, node: "n_wait_missing" }]);
  // 그 실행의 프로필
  await expect(page.getByRole("combobox", { name: "실행 프로필" })).toHaveValue("login_fail");
  // 실행은 하지 않는다 (사용자가 F5)
  await page.waitForTimeout(1500);
  await expect(toolbar(page)).not.toHaveAttribute("data-phase", /running|starting/);
  const after = ((await page.evaluate(() => window.kookabug.rpc("run.list", { limit: 100 }))) as { runs: unknown[] }).runs.length;
  expect(after).toBe(before);
  // 알림 (RUN 탭)
  await page.locator(`[role="tab"][data-path="run:${runs.prof}"] button`).first().click();
  await expect(page.locator('[data-part="run-notice"]')).toContainText("F5로 실행");
  await expect(page.locator('[data-part="run-notice"]')).toContainText("프로필 login_fail");
  await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
  await page.getByRole("combobox", { name: "실행 프로필" }).selectOption("").catch(() => {});
});

test("test_reproduce_warns_when_graph_changed", async () => {
  const { page, ws } = session();
  const file = path.join(ws.root, ...VIEWER_CMP.split("/"));
  const original = fs.readFileSync(file, "utf8");
  try {
    const changed = JSON.parse(original) as { nodes: Record<string, { title: string }> };
    changed.nodes.n_click.title = "바뀐 클릭";
    fs.writeFileSync(file, JSON.stringify(changed, null, 2) + "\n");
    await openFromList(page, runs.fail);
    const graphTab = page.locator(`[role="tab"][data-path="${VIEWER_CMP}"]`);
    // 취소하면 아무것도 열지 않는다
    await page.locator('[data-part="reproduce"]').click();
    const dialog = page.getByRole("dialog", { name: "그래프가 실행 때와 다릅니다" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "취소" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(graphTab).toHaveCount(0);
    // 그래도 열기 → 열리고 경고 알림
    await page.locator('[data-part="reproduce"]').click();
    await page.getByRole("dialog", { name: "그래프가 실행 때와 다릅니다" }).getByRole("button", { name: "그래도 열기" }).click();
    await expect(graphTab).toHaveAttribute("aria-selected", "true");
    await page.locator(`[role="tab"][data-path="run:${runs.fail}"] button`).first().click();
    await expect(page.locator('[data-part="run-notice"]')).toHaveAttribute("data-tone", "warn");
  } finally {
    fs.writeFileSync(file, original);
    await page.evaluate(() => window.kookabug.rpc("debug.breakpoints.set", { breakpoints: [] }));
  }
});

test("test_baseline_outside_first_page_shown_and_selectable", async () => {
  // T11 검수 1: 같은 테스트의 더 최근 끝난 실행이 한 쪽(50개)을 넘게 쌓여 자동 기준(지난 성공)이 첫 쪽 밖에 있어도
  // 기준 화면을 그리고 목록에서 고를 수 있다. "이전 실행 더 보기"로 다음 쪽을 읽는다. (끝에 둔다: 실행 51개를 더한다)
  const { page, ws } = session();
  const body = JSON.parse(fs.readFileSync(path.join(runFolderOf(ws, runs.fail), "run.json"), "utf8")) as { started_at: string };
  for (let i = 0; i < 51; i++) {
    cloneRun(ws, runs.fail, `zz${String(i).padStart(6, "0")}`, { started_at: iso(Date.parse(body.started_at) + (i + 1) * 1000) });
  }
  const page1 = (await page.evaluate((g) => window.kookabug.rpc("run.list", { graph: g, limit: 50 }), VIEWER_CMP)) as {
    runs: { run_id: string }[];
    next: string | null;
  };
  expect(page1.runs.map((r) => r.run_id)).not.toContain(runs.base);
  expect(page1.next).not.toBeNull();
  await openFromList(page, runs.fail);
  await page.locator('[data-part="subtab-compare"]').click();
  const box = page.locator('[data-part="compare-box"]');
  await expect(box).toHaveAttribute("data-baseline", runs.base, { timeout: 30_000 });
  // 기준 화면 (run.status로 읽은 기준 폴더)
  const image = page.locator('[data-part="baseline-image"]');
  await expect(image).toHaveJSProperty("complete", true);
  expect(await image.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0);
  // 목록: 첫 쪽(복사본 50개) + 지금 기준을 맨 위에 따로
  const select = page.locator('[data-part="baseline-select"]');
  await expect(select.locator(`option[value="${runs.base}"]`)).toHaveCount(1);
  await expect(select.locator(`option[value="${runs.other}"]`)).toHaveCount(0);
  // 다음 쪽
  await page.locator('[data-part="baseline-more"]').click();
  await expect(select.locator(`option[value="${runs.other}"]`)).toHaveCount(1);
  await expect(select.locator(`option[value="${runs.base}"]`)).toHaveCount(1);
  await expect(page.locator('[data-part="baseline-more"]')).toHaveCount(0);
  // 다음 쪽의 실행을 골랐다가 첫 쪽 밖의 기준을 직접 다시 고른다
  await select.selectOption(runs.other);
  await expect(box).toHaveAttribute("data-baseline", runs.other, { timeout: 30_000 });
  await select.selectOption(runs.base);
  await expect(box).toHaveAttribute("data-baseline", runs.base, { timeout: 30_000 });
  await expect(box).toContainText(`#${runs.base.slice(0, 4)} (고른 실행) 과 차이`);
  await expect(image).toHaveJSProperty("complete", true);
});
