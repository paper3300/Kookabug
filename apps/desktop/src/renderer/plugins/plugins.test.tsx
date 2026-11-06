// 플러그인 화면 (M6 B5): 경로 가리기·원천 입력·준비 띠·진행 단계·오류 글, 흐름(신뢰 카드를 거쳐야만 설치·준비),
// 신뢰 카드 문구 (react-dom/server로 그린다)
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, test } from "vitest";
import {
  bannerView,
  busyText,
  errorView,
  hidePaths,
  isSshGit,
  nodesByPermission,
  previewParams,
  progressSteps,
  sourceView,
  SSH_REFUSED,
  TRUST_WARNING,
  EMPTY_DRAFT,
  type PluginEntry,
  type PluginsList,
  type PreviewResult,
} from "./model";

// ── 가짜 다리 (window.kookabug): 호출 기록과 알림 처리기 ─────────────
type Handler = (method: string, params: unknown) => unknown;
const calls: { method: string; params: unknown }[] = [];
const listeners = new Map<string, (data: unknown) => void>();
let handler: Handler = () => ({});
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc: async (method: string, params: unknown) => {
    calls.push({ method, params });
    return handler(method, params);
  },
  on: (name: string, cb: (data: unknown) => void) => {
    listeners.set(name, cb);
    return () => listeners.delete(name);
  },
};

const store = await import("./pluginStore");
const { RelockCard, TrustCard } = await import("./PluginDialog");
const { PluginDetailBody } = await import("./PluginDetail");

const SAMPLE: PluginEntry = {
  id: "sample",
  dist: "kookabug-plugin-sample",
  version: "0.1.0",
  env: "shared",
  env_status: "ready",
  manifest: { title: "Sample", modules: ["kookabug_plugin_sample.nodes.text"], permissions: ["capture"] },
  nodes: [
    { type: "sample.text.reverse", title: "글자 뒤집기", effects: [] },
    { type: "sample.window.title", title: "창 제목", effects: ["capture"] },
  ],
  requires: ["kookabug-sdk>=0.1.0.dev0,<0.2", "kbfix-dep==1.*"],
  source: { kind: "git", url: "file:///C:/Users/someone/AppData/Local/Temp/repos/sample", ref: "v0.1.0", commit: "a1b2c3d4e5f6a7b8c9d0a1b2c3d4e5f6a7b8c9d0" },
  isolated_because: null,
};

function list(over: Partial<PluginsList> = {}): PluginsList {
  return {
    busy: null,
    environments: { shared: { folder: "shared-abc", plugins: ["sample"], status: "ready" } },
    gc_candidates: { envs: [], staging: [], wheels: [] },
    lock_sha256: "f".repeat(64),
    plugins: [SAMPLE],
    revision: "r".repeat(64),
    stale_reason: null,
    trusted: true,
    ...over,
  };
}

const PREVIEW: PreviewResult = {
  op_id: "op1",
  id: "sample",
  dist: "kookabug-plugin-sample",
  title: "Sample",
  version: "0.1.0",
  isolation: "auto",
  permissions: ["capture", "secrets"],
  dependencies: ["kookabug-sdk>=0.1.0.dev0,<0.2", "kbfix-dep==1.*"],
  replaces: null,
  source: { kind: "git", url: "file:///D:/work/repos/kookabug-plugin-sample", ref: "v0.1.0", commit: "0123456789abcdef0123456789abcdef01234567" },
  untrusted: ["conflict_a", "compatible_c"],
  expires_in_s: 300,
};

beforeEach(() => {
  calls.length = 0;
  handler = () => ({});
  store.resetPlugins();
});

describe("경로 가리기 (화면에 로컬 절대 경로 원문 없음)", () => {
  test("Windows·UNC·file:// 경로는 마지막 이름만, https·상대 경로는 그대로", () => {
    expect(hidePaths("받지 못했다: C:\\Users\\me\\repos\\sample.whl.")).toBe("받지 못했다: …\\sample.whl.");
    expect(hidePaths("D:/work/x/plugin-a 폴더")).toBe("…\\plugin-a 폴더");
    expect(hidePaths("\\\\nas\\share\\p\\a.whl")).toBe("…\\a.whl");
    expect(hidePaths("git+file:///C:/Users/me/repo@v1")).toBe("git+…/repo@v1");
    expect(hidePaths("https://github.com/acme/kookabug-plugin-sample")).toBe("https://github.com/acme/kookabug-plugin-sample");
    expect(hidePaths("plugins/sample")).toBe("plugins/sample");
    // 터미널 색 코드는 뺀다
    expect(hidePaths("\u001b[1;35mRuntimeError\u001b[0m: x")).toBe("RuntimeError: x");
  });

  test("공백·한글·따옴표·file:// 경로도 앞 폴더(사용자 이름)를 남기지 않는다 (검수 Mid)", () => {
    expect(hidePaths("C:\\Users\\My Name\\private\\plugin.whl")).toBe("…\\plugin.whl");
    expect(hidePaths("file:///C:/Users/My Name/private/plugin.whl")).toBe("…/plugin.whl");
    expect(hidePaths("file:///C:/Users/My%20Name/private/plugin.whl")).toBe("…/plugin.whl");
    expect(hidePaths('열 수 없다: "C:\\Users\\My Name\\private\\plugin.whl" (권한)')).toBe('열 수 없다: "…\\plugin.whl" (권한)');
    expect(hidePaths("받지 못했다: D:\\작업 폴더\\홍 길동\\플러그인.whl 에서 오류")).toBe("받지 못했다: …\\플러그인.whl 에서 오류");
    expect(hidePaths("'\\\\nas\\공유 폴더\\a b\\x.whl'")).toBe("'…\\x.whl'");
    for (const s of ["My Name", "홍 길동", "공유 폴더", "private"]) {
      expect(hidePaths(`경로 C:\\Users\\${s}\\x\\y.whl`)).not.toContain(s);
    }
  });

  test("구조화된 원천 경로는 값 전체를 경로로 보고 마지막 이름만", () => {
    expect(sourceView({ kind: "path", path: "C:\\Users\\My Name\\plugins\\my plugin" }).where).toBe("…\\my plugin");
    expect(sourceView({ kind: "wheel", path: "D:\\홍 길동\\a b-0.1.0-py3-none-any.whl" }).where).toBe("…\\a b-0.1.0-py3-none-any.whl");
    expect(sourceView({ kind: "git", url: "file:///C:/Users/My%20Name/repos/my%20repo" }).where).toBe("…/my repo");
    expect(sourceView({ kind: "git", url: "https://***@github.com/acme/x" }).where).toBe("https://***@github.com/acme/x");
    expect(sourceView({ kind: "wheel", url: "https://h/a.whl", sha256: "a".repeat(64) }).where).toBe("https://h/a.whl");
  });

  test("원천 줄: git은 주소(가림)·ref·짧은 커밋, wheel은 sha256 앞부분", () => {
    const git = sourceView(SAMPLE.source);
    expect(git).toMatchObject({ kind: "git", label: "Git", where: "…/sample", detail: "@ v0.1.0 (a1b2c3d)" });
    expect(sourceView({ kind: "wheel", path: "C:\\x\\a-0.1.0-py3-none-any.whl", sha256: "ab".repeat(32) })).toMatchObject({
      where: "…\\a-0.1.0-py3-none-any.whl",
      detail: `sha256 ${"ab".repeat(6)}…`,
    });
    expect(sourceView({ kind: "path", path: "plugins/sample" }).where).toBe("plugins/sample");
  });
});

describe("추가 대화 상자 입력", () => {
  test("git: git+ 붙이기, ref는 따로, ssh는 받지 않음 (U14)", () => {
    expect(previewParams({ ...EMPTY_DRAFT, text: "https://h/a.git", ref: " v1 " })).toEqual({
      params: { source: "git+https://h/a.git", isolation: "auto", ref: "v1" },
    });
    expect(previewParams({ ...EMPTY_DRAFT, text: "git+file:///D:/r" })).toEqual({ params: { source: "git+file:///D:/r", isolation: "auto" } });
    expect(isSshGit("git@github.com:acme/x.git")).toBe(true);
    expect(isSshGit("ssh://git@host/x")).toBe(true);
    expect(isSshGit("https://user:tok@host/x")).toBe(false);
    expect(previewParams({ ...EMPTY_DRAFT, text: "git@github.com:acme/x.git" })).toEqual({ error: SSH_REFUSED });
    expect(previewParams({ ...EMPTY_DRAFT, text: " " })).toHaveProperty("error");
  });

  test("wheel: https면 sha256 64자리 필수, http는 거부, 경로는 그대로", () => {
    const wheel = { ...EMPTY_DRAFT, kind: "wheel" as const };
    expect(previewParams({ ...wheel, text: "https://h/a.whl" })).toHaveProperty("error");
    expect(previewParams({ ...wheel, text: "http://h/a.whl" })).toEqual({ error: "wheel 주소는 https만 받아요" });
    expect(previewParams({ ...wheel, text: "https://h/a.whl", sha256: "AB".repeat(32), isolation: "isolated" })).toEqual({
      params: { source: "https://h/a.whl", isolation: "isolated", sha256: "ab".repeat(32) },
    });
    expect(previewParams({ ...wheel, text: "D:\\w\\a.whl" })).toEqual({ params: { source: "D:\\w\\a.whl", isolation: "auto" } });
  });
});

describe("목록 모델", () => {
  test("준비 띠: 조건 다름 → 다시 잠그기, 환경 없음 → 준비 필요 N, 깨짐 → 새로 만들기 문구, 다 준비됨 → 없음", () => {
    expect(bannerView(list())).toBeNull();
    expect(bannerView(list({ plugins: [] }))).toBeNull();
    const missing = bannerView(list({ plugins: [{ ...SAMPLE, env_status: "missing" }, { ...SAMPLE, id: "b", env_status: "missing" }] }));
    expect(missing).toMatchObject({ kind: "prepare", text: "준비 필요 2", count: 2 });
    expect(bannerView(list({ plugins: [{ ...SAMPLE, env_status: "broken" }] }))).toMatchObject({
      kind: "prepare",
      text: "환경이 깨졌어요 — 준비…로 새로 만들어요",
    });
    const stale = bannerView(list({ stale_reason: "SDK wheel이 다르다 (C:\\Users\\me\\sdk.whl)", plugins: [{ ...SAMPLE, env_status: "stale" }] }));
    expect(stale).toMatchObject({ kind: "relock", detail: "SDK wheel이 다르다 (…\\sdk.whl)" });
  });

  test("다른 창 작업: 승인 대기면 확인 중, 이 창 작업이면 없음", () => {
    expect(busyText({ kind: "install", op_id: null, stage: "manifest", waiting: true }, null)).toBe("다른 창에서 신뢰 확인을 기다리는 중이에요");
    expect(busyText({ kind: "sync", op_id: "x", stage: null, waiting: false }, null)).toBe("플러그인 준비 진행 중이에요");
    expect(busyText({ kind: "sync", op_id: "x", stage: null, waiting: false }, "x")).toBeNull();
  });

  test("권한별 쓰는 노드", () => {
    expect(nodesByPermission(SAMPLE)).toEqual([{ id: "capture", nodes: ["창 제목"] }]);
  });

  test("진행 단계: 설치는 받기가 끝난 채 시작, 단계 알림만큼 앞으로", () => {
    expect(progressSteps("install", []).map((s) => s.state)).toEqual(["done", "active", "pending", "pending", "pending", "pending"]);
    const built = progressSteps("install", ["confirmed", "resolved", "built"]);
    expect(built.find((s) => s.state === "active")?.label).toBe("환경 만들기");
    expect(progressSteps("sync", ["env_installed"]).map((s) => s.state)).toEqual(["done", "active"]);
    expect(progressSteps("gc", [])).toEqual([]);
  });

  test("오류 글: 코드별 요약, 자세히에 단계·문구(경로 가림)·작업 로그", () => {
    const v = errorView({ code: "verify_failed", stage: "env_verified", message: "import 실패: D:\\ws\\.kookabug\\plugins\\envs\\shared-1\\x.py", op_id: "op9" });
    expect(v.summary).toBe("설치한 플러그인을 확인하지 못했어요");
    expect(v.detail).toEqual(["verify_failed · 단계 env_verified", "import 실패: …\\x.py", "작업 로그: .kookabug/plugins/logs/op9.log"]);
    expect(errorView({ code: "source_refused", message: "ssh 전송은 받지 않는다" }).summary).toBe(SSH_REFUSED);
    expect(errorView({ code: "plugin_conflict", conflicts: ["kbfix-dep"] }).summary).toContain("kbfix-dep");
  });
});

describe("흐름: 신뢰 카드를 거쳐야만 설치·준비한다", () => {
  test("추가: 미리보기 → 신뢰 카드(아직 install 없음) → 신뢰하고 설치 = 그 미리보기 op_id로 install → 끝 알림 → 결과", async () => {
    store.initPlugins(() => {});
    handler = (method) => {
      if (method === "plugins.preview") return PREVIEW;
      if (method === "plugins.install") return { op_id: "op1" };
      if (method === "plugins.list") return list();
      return {};
    };
    store.openAddDialog();
    await store.submitSource({ ...EMPTY_DRAFT, text: "file:///D:/work/repos/kookabug-plugin-sample", ref: "v0.1.0" });
    expect(calls.map((c) => c.method)).toEqual(["plugins.preview"]);
    expect(calls[0].params).toEqual({ source: "git+file:///D:/work/repos/kookabug-plugin-sample", isolation: "auto", ref: "v0.1.0" });
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "install", step: "trust" });
    await store.confirmFlow();
    expect(calls.at(-1)).toEqual({ method: "plugins.install", params: { op_id: "op1" } });
    expect(store.usePlugins.getState().flow).toMatchObject({ step: "progress", opId: "op1", title: "Sample" });
    listeners.get("plugins.progress")!({ op_id: "op1", stage: "resolved", message: "의존성을 풀었어요" });
    expect(store.usePlugins.getState().ops.op1.stages).toEqual(["resolved"]);
    listeners.get("plugins.done")!({ op_id: "op1", kind: "install", ok: false, error: { code: "verify_failed", stage: "env_verified", message: "x" } });
    expect(store.usePlugins.getState().flow).toMatchObject({ step: "result", ok: false, kind: "install" });
    expect(store.usePlugins.getState().running).toBeNull();
  });

  test("신뢰 카드를 닫으면 미리보기를 취소한다 (install 없음)", async () => {
    handler = (method) => (method === "plugins.preview" ? PREVIEW : {});
    store.openAddDialog();
    await store.submitSource({ ...EMPTY_DRAFT, text: "https://h/a.git" });
    store.closeFlow();
    await new Promise((r) => setTimeout(r, 0));
    // 취소 뒤 목록(busy)을 다시 읽는다 — install은 없다
    expect(calls.map((c) => c.method)).toEqual(["plugins.preview", "plugins.cancel", "plugins.list"]);
    expect(calls[1].params).toEqual({ op_id: "op1" });
  });

  test("다른 창 작업·승인 전 취소한 미리보기의 끝 알림: 결과 대화 상자 없이 목록(busy)을 다시 읽는다 (검수 Mid)", async () => {
    store.initPlugins(() => {});
    let busy: PluginsList["busy"] = { kind: "install", op_id: null, stage: "manifest", waiting: true };
    handler = () => list({ busy });
    await store.reloadPlugins();
    expect(store.usePlugins.getState().list?.busy).not.toBeNull();
    busy = null;
    calls.length = 0;
    listeners.get("plugins.done")!({ op_id: "other", kind: "install", ok: false, error: { code: "cancelled", stage: "confirm", message: "x" } });
    await new Promise((r) => setTimeout(r, 0));
    expect(calls.map((c) => c.method)).toEqual(["plugins.list"]);
    expect(store.usePlugins.getState().list?.busy).toBeNull();
    expect(store.usePlugins.getState().flow).toBeNull();
  });

  test("미리보기 실패: 원천 입력으로 돌아가 오류 글 (plugin_failed의 plugin_error)", async () => {
    handler = () => {
      throw { code: -32000, message: "x", data: { code: "plugin_failed", plugin_error: { code: "source_unavailable", stage: "fetch", message: "없다: C:\\r\\x" } } };
    };
    store.openAddDialog();
    await store.submitSource({ ...EMPTY_DRAFT, text: "https://h/a.git" });
    const flow = store.usePlugins.getState().flow;
    expect(flow).toMatchObject({ step: "source" });
    expect(flow?.step === "source" && flow.error).toBe("원천을 받지 못했어요\n없다: …\\x");
  });

  test("끝 알림이 응답보다 먼저 와도 결과로 간다", async () => {
    store.initPlugins(() => {});
    handler = (method) => {
      if (method === "plugins.gc") {
        listeners.get("plugins.done")!({ op_id: "g1", kind: "gc", ok: true, result: {} });
        return { op_id: "g1" };
      }
      return list({ gc_candidates: { envs: ["old"], staging: [], wheels: [] } });
    };
    await store.startGc();
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "gc", step: "confirm" });
    await store.confirmFlow();
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "gc", step: "result", ok: true });
  });

  test("준비: 신뢰하지 않은 잠금이면 카드만 띄우고 sync는 확인 뒤 그 lock_sha256으로", async () => {
    handler = (method) => (method === "plugins.list" ? list({ trusted: false, plugins: [{ ...SAMPLE, env_status: "missing" }] }) : { op_id: "s1" });
    await store.startPrepare();
    expect(calls.map((c) => c.method)).toEqual(["plugins.list"]);
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "sync", step: "trust" });
    await store.confirmFlow();
    expect(calls.at(-1)).toEqual({ method: "plugins.sync", params: { lock_sha256: "f".repeat(64) } });
  });

  test("준비: 이 PC가 신뢰한 잠금이면 다시 묻지 않고 sync (U2)", async () => {
    handler = (method) => (method === "plugins.list" ? list({ plugins: [{ ...SAMPLE, env_status: "missing" }] }) : { op_id: "s2" });
    await store.startPrepare();
    expect(calls.map((c) => c.method)).toEqual(["plugins.list", "plugins.sync"]);
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "sync", step: "progress", opId: "s2" });
  });

  test("제거: 확인할 때 본 잠금 revision을 base_revision으로", async () => {
    handler = (method) => (method === "plugins.list" ? list() : { op_id: "r1" });
    await store.reloadPlugins();
    store.startRemove(SAMPLE);
    expect(calls.map((c) => c.method)).toEqual(["plugins.list"]);
    await store.confirmFlow();
    expect(calls.at(-1)).toEqual({ method: "plugins.remove", params: { id: "sample", base_revision: "r".repeat(64) } });
  });

  test("다시 잠그기: 카드의 lock_sha256을 보내고, 잠금이 바뀌면 카드를 새 목록으로 바꿔 다시 확인하게 한다 (검수 H)", async () => {
    store.initPlugins(() => {});
    const card = list({ stale_reason: "SDK가 다르다", plugins: [{ ...SAMPLE, env_status: "stale" }] });
    const added: PluginEntry = { ...SAMPLE, id: "compatible_c", manifest: { title: "C", permissions: ["network"] } };
    const incoming = list({ stale_reason: "SDK가 다르다", lock_sha256: "e".repeat(64), trusted: false, plugins: [card.plugins[0], added] });
    let current = card;
    handler = (method) => (method === "plugins.list" ? current : { op_id: "rl1" });
    await store.startRelock();
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "relock", step: "confirm" });
    // 밖에서 잠금이 바뀜 → plugins.changed → 카드가 새 목록·"바뀜" 표시
    current = incoming;
    listeners.get("plugins.changed")!({ revision: "x" });
    await new Promise((r) => setTimeout(r, 0));
    const flow = store.usePlugins.getState().flow;
    expect(flow).toMatchObject({ kind: "relock", step: "confirm", changed: true });
    expect(flow?.step === "confirm" && flow.kind === "relock" && flow.list.plugins.map((p) => p.id)).toEqual(["sample", "compatible_c"]);
    const html = renderToStaticMarkup(<RelockCard list={incoming} busy={false} changed />);
    expect(html).toContain("잠금이 바뀌었어요");
    expect(html).toContain("compatible_c");
    calls.length = 0;
    await store.confirmFlow();
    expect(calls).toEqual([{ method: "plugins.relock", params: { lock_sha256: "e".repeat(64) } }]);
  });

  test("다시 잠그기: 바뀌지 않았으면 카드가 본 해시 그대로", async () => {
    handler = (method) => (method === "plugins.list" ? list({ stale_reason: "x" }) : { op_id: "rl2" });
    await store.startRelock();
    await store.confirmFlow();
    expect(calls.at(-1)).toEqual({ method: "plugins.relock", params: { lock_sha256: "f".repeat(64) } });
  });

  test("정리: 카드에서 본 후보만 보내고, 후보가 바뀌면 카드를 바꿔 다시 확인", async () => {
    const seen = { envs: ["old-a"], staging: [], wheels: [] };
    let current = list({ gc_candidates: seen });
    handler = (method) => (method === "plugins.list" ? current : { op_id: "g2" });
    await store.startGc();
    current = list({ gc_candidates: { envs: ["old-a", "old-b"], staging: [], wheels: ["w1"] } });
    await store.reloadPlugins();
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "gc", changed: true, candidates: { envs: ["old-a", "old-b"] } });
    calls.length = 0;
    await store.confirmFlow();
    expect(calls).toEqual([{ method: "plugins.gc", params: { candidates: { envs: ["old-a", "old-b"], staging: [], wheels: ["w1"] } } }]);
  });

  test("제거: 카드를 연 뒤 잠금에서 그 플러그인이 없어지면 카드를 닫는다, revision만 바뀌면 다시 확인", async () => {
    let current = list();
    handler = (method) => (method === "plugins.list" ? current : { op_id: "r2" });
    await store.reloadPlugins();
    store.startRemove(SAMPLE);
    current = list({ revision: "q".repeat(64) });
    await store.reloadPlugins();
    expect(store.usePlugins.getState().flow).toMatchObject({ kind: "remove", revision: "q".repeat(64), changed: true });
    current = list({ revision: "z".repeat(64), plugins: [] });
    await store.reloadPlugins();
    expect(store.usePlugins.getState().flow).toBeNull();
  });

  test("확인 카드가 없으면 confirmFlow는 아무것도 하지 않는다", async () => {
    await store.confirmFlow();
    store.openAddDialog();
    await store.confirmFlow();
    expect(calls).toEqual([]);
  });
});

describe("화면", () => {
  test("신뢰 카드: 경고 문구·이름·판·출처(커밋)·권한 뜻·의존성 수·함께 신뢰할 플러그인, 로컬 경로 원문 없음", () => {
    const html = renderToStaticMarkup(<TrustCard preview={PREVIEW} busy={false} />);
    expect(html).toContain(TRUST_WARNING);
    expect(html).toContain("Sample");
    expect(html).toContain("sample · 0.1.0");
    expect(html).toContain("…/kookabug-plugin-sample");
    expect(html).toContain("(0123456)");
    expect(html).toContain("게임 창 화면을 읽어요");
    expect(html).toContain("저장된 비밀값(계정·토큰)을 읽어요");
    expect(html).toContain("<summary>1개</summary>");
    expect(html).toContain("이 잠금의 다른 플러그인 2개도 신뢰해요");
    expect(html).toContain("신뢰하고 설치");
    expect(html).not.toMatch(/[A-Za-z]:[\\/]|work\/repos/);
  });

  test("상세 탭: 권한 표(쓰는 노드)·노드·의존성, 출처 경로 가림", () => {
    const html = renderToStaticMarkup(<PluginDetailBody entry={SAMPLE} busy={false} />);
    expect(html).toContain("Sample 플러그인");
    expect(html).toContain("창 제목");
    expect(html).toContain("공유 · 준비됨");
    expect(html).toContain("의존성 1개");
    expect(html).toContain("…/sample");
    expect(html).not.toContain("someone");
  });
});
