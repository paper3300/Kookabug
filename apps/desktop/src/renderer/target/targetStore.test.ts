// target 문서 표의 늦은 응답 경계 (T12 검수 1차 High 1·2, Mid 1·2와 편집 잠금). 실제 store 코드에 가짜 daemon 응답
// 순서를 넣어 본다 (검수 재현 repro_T12_1_store.mjs의 다섯 반례가 올바른 결과가 되는지)
import { afterEach, describe, expect, test } from "vitest";

type Rpc = (method: string, params: Record<string, unknown>) => Promise<unknown>;
let rpc: Rpc = () => Promise.reject(new Error("rpc 없음"));
(globalThis as unknown as { kookabug: unknown }).kookabug = {
  rpc: (m: string, p: Record<string, unknown>) => rpc(m, p),
  on: () => () => {},
};

const store = await import("./targetStore");
const { setThreshold } = await import("./spec");
const { setNodeValue } = await import("../graph/commands/setPin");
const tabs = await import("../store/tabs");
const dialog = await import("../store/dialog");
const documents = await import("../store/documents");
const editing = await import("../store/editing");

const P = "targets/review.target.json";
const FRAME = { frame_id: "f1", width: 1024, height: 640, dpi: 96, client_size: [1024, 640], image: { cache: "f1.png", width: 1024, height: 640 } };
const IMAGE = { workspace: "targets/review.png", width: 200, height: 64 };
const DISK = { format: "kookabug.target/0", image: "review.png", recorded: { client_size: [1024, 640], dpi: 96 } };
const OPENED = { revision: "r1", spec: DISK, image: IMAGE, diagnostics: [] };
const preview = (seq: unknown) => ({
  seq,
  found: true,
  match: { rect: [412, 380, 200, 64], score: 1, scale: 1, method: "template", click: [512, 412] },
  best: null,
  threshold: 0.85,
  expected_scale: 1,
  search: [0, 0, 1024, 640],
  search_rect_px: [0, 0, 1024, 640],
  candidates: [],
  elapsed_ms: 1,
});
const pause = (ms = 0) => new Promise((r) => setTimeout(r, ms));
function deferred(): { promise: Promise<void>; resolve(): void } {
  let resolve!: () => void;
  const promise = new Promise<void>((r) => (resolve = r));
  return { promise, resolve };
}
const doc = () => {
  const d = store.getTarget(P);
  if (d === undefined) throw new Error("문서 없음");
  return d;
};

async function newDoc(origin: Parameters<typeof store.createTargetDoc>[1] = null): Promise<void> {
  store.createTargetDoc(P, origin);
  tabs.openTab({ path: P, kind: "target" });
  expect(await store.loadImageFrame(P, "captures/title.png")).toEqual({ kind: "ok" });
  store.setTemplate(P, [412, 380, 200, 64]);
}

afterEach(async () => {
  tabs.closeAllTabs();
  store.resetTargets();
  documents.resetDocuments();
  while (dialog.useDialog.getState().current !== null) dialog.finish({ value: "cancel", text: "" });
  await pause(5);
});

describe("저장을 기다리는 동안 편집 (Mid 1)", () => {
  test("저장 뒤 디스크 사양(image·recorded) 위에 그사이 바꾼 임계값을 얹고 기존 이미지로 미리보기한다", async () => {
    const gate = deferred();
    const previews: unknown[] = [];
    rpc = async (m, a) => {
      if (m === "target.load_image") return FRAME;
      if (m === "target.save") {
        await gate.promise;
        return { revision: "r1", image: "targets/review.png", preview: preview(1), warnings: [] };
      }
      if (m === "target.open") return OPENED;
      if (m === "target.preview") {
        previews.push(a.template);
        return preview(a.seq);
      }
      throw new Error(m);
    };
    await newDoc();
    const saving = store.saveTarget(P);
    store.editSpec(P, (s) => setThreshold(s, 0.91));
    gate.resolve();
    expect(await saving).toBe("saved");
    const d = doc();
    expect(d.spec).toEqual({ ...DISK, match: { threshold: 0.91 } });
    expect(d.savedSpec).toEqual(DISK);
    expect(d.template).toBeNull();
    expect(store.targetDirty(d)).toBe(true);
    // 저장 뒤 미리보기는 저장한 이미지로 (영역을 다시 드래그하라고 하지 않는다)
    expect(store.previewRequest(d)).toEqual({
      params: { frame_id: "f1", spec: d.spec, template: { image: "review.png" }, base_path: P },
    });
    await pause(10);
    expect(doc().previewNote).toBeNull();
    expect(previews.at(-1)).toEqual({ image: "review.png" });
  });

  test("기존 target을 새 영역으로 다시 자르는 동안 바꾼 것도 새 image 위에 얹는다", async () => {
    const gate = deferred();
    let opens = 0;
    const after = { ...DISK, image: "review-1a2b3c4d.png" };
    rpc = async (m, a) => {
      if (m === "target.open") return ++opens === 1 ? OPENED : { ...OPENED, revision: "r2", spec: after, image: { ...IMAGE, workspace: "targets/review-1a2b3c4d.png" } };
      if (m === "target.load_image") return FRAME;
      if (m === "target.save") {
        await gate.promise;
        return { revision: "r2", image: "targets/review-1a2b3c4d.png", preview: preview(1), warnings: [] };
      }
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    tabs.openTab({ path: P, kind: "target" });
    await pause(5);
    await store.loadImageFrame(P, "captures/title.png");
    store.setTemplate(P, [10, 10, 50, 20]);
    const saving = store.saveTarget(P);
    store.editSpec(P, (s) => setThreshold(s, 0.8));
    gate.resolve();
    await saving;
    expect(doc().spec).toEqual({ ...after, match: { threshold: 0.8 } });
    expect(doc().baseRevision).toBe("r2");
  });
});

describe("모두 저장 (High 1)", () => {
  test("편집 잠금 중 저장해도 새 target을 만든 그래프 핀을 채우고, 그래프까지 저장한 뒤 떠난다", async () => {
    const graph = "tests/review.graph.json";
    const saves: unknown[] = [];
    rpc = async (m, a) => {
      if (m === "graph.open") {
        return {
          doc_id: "g1",
          revision: "g1",
          canonical: true,
          diagnostics: [],
          shapes: {},
          value: { format: "kookabug.graph/0", kind: "test", nodes: { n_wait: { type: "core.image.wait", version: 1, in: { timeout_ms: 5000 } } } },
        };
      }
      if (m === "graph.save") {
        saves.push(a.value);
        return { revision: "g2", wrote: true, canonicalized: false, diagnostics: [] };
      }
      if (m === "target.load_image") return FRAME;
      if (m === "target.save") return { revision: "r1", image: "targets/review.png", preview: preview(1), warnings: [] };
      if (m === "target.open") return OPENED;
      if (m === "target.preview") return preview(a.seq);
      if (m === "graph.validate") return { seq: a.seq, diagnostics: [], shapes: {} };
      if (m === "graph.close") return {};
      throw new Error(m);
    };
    tabs.openTab({ path: graph, kind: "graph" });
    await pause(5);
    await newDoc({ graph, node: "n_wait", pin: "target" });
    const leave = editing.confirmLeaveDirty();
    dialog.finish({ value: "save", text: "" });
    expect(await leave).toBe(true);
    const g = documents.getDoc(graph);
    expect((g?.value?.nodes as Record<string, { in: unknown }>).n_wait.in).toEqual({ target: { $target: P }, timeout_ms: 5000 });
    expect(g?.dirty).toBe(false);
    // 디스크(graph.save)에 참조가 갔다
    expect(saves).toHaveLength(1);
    expect((saves[0] as { nodes: Record<string, { in: unknown }> }).nodes.n_wait.in).toEqual({ target: { $target: P }, timeout_ms: 5000 });
    expect(doc().origin).toBeNull();
  });

  test("그래프가 닫혀 있으면 origin을 지우지 않고 경고를 남긴다", async () => {
    rpc = async (m, a) => {
      if (m === "target.load_image") return FRAME;
      if (m === "target.save") return { revision: "r1", image: "targets/review.png", preview: preview(1), warnings: [] };
      if (m === "target.open") return OPENED;
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    await newDoc({ graph: "tests/closed.graph.json", node: "n", pin: "target" });
    expect(await store.saveTarget(P)).toBe("saved");
    expect(doc().origin).toEqual({ graph: "tests/closed.graph.json", node: "n", pin: "target", previous: undefined });
    expect(doc().saved?.warnings.join()).toContain("대상 칸을 채우지 못했어요");
  });
});

describe("바깥 변경 자동 다시 열기 (High 2)", () => {
  test("응답을 기다리는 동안 한 편집은 지우지 않고 충돌 띠로 바꾼다", async () => {
    const gate = deferred();
    let opens = 0;
    rpc = async (m, a) => {
      if (m === "target.open") {
        if (++opens > 1) {
          await gate.promise;
          return { ...OPENED, revision: "r9", spec: { ...DISK, match: { threshold: 0.9 } } };
        }
        return OPENED;
      }
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    tabs.openTab({ path: P, kind: "target" });
    await pause(5);
    store.onWorkspaceChanged([P]);
    store.editSpec(P, (s) => setThreshold(s, 0.93));
    gate.resolve();
    await pause(10);
    const d = doc();
    expect(d.spec).toEqual({ ...DISK, match: { threshold: 0.93 } });
    expect(store.targetDirty(d)).toBe(true);
    expect(d.baseRevision).toBe("r1");
    expect(d.conflict).toBe("r9");
  });

  test("편집이 없으면 조용히 디스크 버전으로, 더 새 다시 열기가 있으면 옛 응답은 버린다", async () => {
    const first = deferred();
    let opens = 0;
    rpc = async (m, a) => {
      if (m === "target.open") {
        opens++;
        if (opens === 2) {
          await first.promise;
          return { ...OPENED, revision: "old", spec: { ...DISK, match: { threshold: 0.7 } } };
        }
        if (opens === 3) return { ...OPENED, revision: "new", spec: { ...DISK, match: { threshold: 0.6 } } };
        return OPENED;
      }
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    tabs.openTab({ path: P, kind: "target" });
    await pause(5);
    const a = store.reloadTarget(P);
    await store.reloadTarget(P);
    first.resolve();
    await a;
    expect(doc().baseRevision).toBe("new");
    expect(doc().spec).toEqual({ ...DISK, match: { threshold: 0.6 } });
    expect(doc().conflict).toBeNull();
  });
});

describe("정지 화면 만료 (Mid 2)", () => {
  test("만료 전에 보낸 미리보기 응답은 결과를 다시 보이지 않는다", async () => {
    const gate = deferred();
    rpc = async (m, a) => {
      if (m === "target.load_image") return FRAME;
      if (m === "target.preview") {
        await gate.promise;
        return preview(a.seq);
      }
      throw new Error(m);
    };
    await newDoc();
    store.requestPreview(P, 0);
    await pause(10);
    expect(doc().previewPending).toBe(true);
    store.framesHost.expireAll();
    expect(doc().previewPending).toBe(false);
    gate.resolve();
    await pause(10);
    expect(doc().frame).toBeNull();
    expect(doc().frameExpired).toBe(true);
    expect(doc().preview).toBeNull();
    // 고른 영역은 둔다 (정지 화면을 다시 고르면 이어서 쓴다)
    expect(doc().template).toEqual([412, 380, 200, 64]);
  });

  test("만료 전에 요청한 정지 화면이 만료 뒤 도착하면 쓰지 않는다", async () => {
    const gate = deferred();
    let loads = 0;
    rpc = async (m, a) => {
      if (m === "target.load_image") {
        if (++loads === 2) await gate.promise;
        return FRAME;
      }
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    await newDoc();
    const late = store.loadImageFrame(P, "captures/title.png");
    store.framesHost.expireAll();
    gate.resolve();
    const outcome = await late;
    expect(outcome.kind === "error" && outcome.message).toContain("다시 고르세요");
    expect(doc().frame).toBeNull();
  });
});

// ── 검수 2차 ────────────────────────────────────────────────────

const G = "tests/review.graph.json";

function graphRpc(pinValue: unknown, saved: unknown[] = []): Rpc {
  return async (m, a) => {
    if (m === "graph.open") {
      return {
        doc_id: "g1",
        revision: "g1",
        canonical: true,
        diagnostics: [],
        shapes: {},
        value: { format: "kookabug.graph/0", kind: "test", nodes: { n: { type: "core.image.wait", version: 1, in: pinValue === undefined ? {} : { target: pinValue } } } },
      };
    }
    if (m === "graph.save") {
      saved.push(a.value);
      return { revision: "g2", wrote: true, canonicalized: false, diagnostics: [] };
    }
    if (m === "graph.validate") return { seq: a.seq, diagnostics: [], shapes: {} };
    if (m === "graph.close") return {};
    if (m === "target.load_image") return FRAME;
    if (m === "target.save") return { revision: "r1", image: "targets/review.png", preview: preview(1), warnings: [] };
    if (m === "target.open") return OPENED;
    if (m === "target.preview") return preview(a.seq);
    throw new Error(m);
  };
}

const pinOf = () => (documents.getDoc(G)?.value?.nodes as Record<string, { in: Record<string, unknown> }>).n.in.target;

describe("핀 연결 완료 (검수 2차 Mid 1)", () => {
  test("핀이 처음부터 같은 참조면 바꿀 것 없이 끝난 것: origin을 지우고, 뒤에 사용자가 바꾼 참조를 다시 저장해도 덮지 않는다", async () => {
    rpc = graphRpc({ $target: P });
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    await newDoc({ graph: G, node: "n", pin: "target" });
    expect(await store.saveTarget(P)).toBe("saved");
    expect(doc().origin).toBeNull();
    expect(doc().saved?.warnings).toEqual([]);
    expect(documents.getDoc(G)?.dirty).toBe(false);
    // 사용자가 핀을 다른 대상으로 바꾼 뒤 target만 다시 저장
    documents.applyEdit(G, (v) => setNodeValue(v, "n", "in", "target", { $target: "targets/other.target.json" }));
    store.editSpec(P, (s) => setThreshold(s, 0.8));
    expect(await store.saveTarget(P)).toBe("saved");
    expect(pinOf()).toEqual({ $target: "targets/other.target.json" });
  });

  test("그래프가 닫혀 있어 미룬 채우기: 그사이 사용자가 핀을 바꿨으면 덮지 않고 origin을 지운다", async () => {
    rpc = graphRpc({ $target: "targets/old.target.json" });
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    await newDoc({ graph: G, node: "n", pin: "target" });
    expect(doc().origin?.previous).toEqual({ $target: "targets/old.target.json" });
    // 그래프를 닫고 저장 → 미룸
    tabs.closeTab(G);
    expect(await store.saveTarget(P)).toBe("saved");
    expect(doc().origin).not.toBeNull();
    expect(doc().saved?.warnings.join()).toContain("열려 있지 않아");
    // 다시 열고 사용자가 다른 대상으로 바꾼 뒤 target 저장 → 덮지 않는다
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    documents.applyEdit(G, (v) => setNodeValue(v, "n", "in", "target", { $target: "targets/mine.target.json" }));
    store.editSpec(P, (s) => setThreshold(s, 0.8));
    expect(await store.saveTarget(P)).toBe("saved");
    expect(pinOf()).toEqual({ $target: "targets/mine.target.json" });
    expect(doc().origin).toBeNull();
    expect(doc().saved?.warnings.join()).toContain("덮어쓰지 않았어요");
  });

  test("미룬 채우기: 핀이 그대로면 그래프를 다시 연 뒤 저장할 때 채운다", async () => {
    rpc = graphRpc({ $target: "targets/old.target.json" });
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    await newDoc({ graph: G, node: "n", pin: "target" });
    tabs.closeTab(G);
    await store.saveTarget(P);
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    store.editSpec(P, (s) => setThreshold(s, 0.8));
    await store.saveTarget(P);
    expect(pinOf()).toEqual({ $target: P });
    expect(doc().origin).toBeNull();
  });

  test("노드가 없어졌으면 노드를 만들지 않고 origin을 지운다", async () => {
    rpc = graphRpc(undefined);
    tabs.openTab({ path: G, kind: "graph" });
    await pause(5);
    await newDoc({ graph: G, node: "n_gone", pin: "target" });
    await store.saveTarget(P);
    expect(documents.getDoc(G)?.value?.nodes).not.toHaveProperty("n_gone");
    expect(doc().origin).toBeNull();
    expect(doc().saved?.warnings.join()).toContain("없어");
  });
});

describe("연속 정지 화면 고르기 (검수 2차 Mid 2)", () => {
  for (const order of ["먼저 고른 것이 먼저 도착", "나중 고른 것이 먼저 도착"] as const) {
    test(`마지막으로 고른 것이 남는다 (${order})`, async () => {
      const gates = { "a.png": deferred(), "b.png": deferred() };
      rpc = async (m, a) => {
        if (m === "target.load_image") {
          const p = a.path as "a.png" | "b.png";
          await gates[p].promise;
          return { ...FRAME, frame_id: p, image: { ...FRAME.image, cache: `${p}` } };
        }
        if (m === "target.preview") return preview(a.seq);
        throw new Error(m);
      };
      store.createTargetDoc(P, null);
      tabs.openTab({ path: P, kind: "target" });
      const first = store.loadImageFrame(P, "a.png");
      const second = store.loadImageFrame(P, "b.png");
      expect(doc().frameLoading).toBe(true);
      const [x, y] = order === "먼저 고른 것이 먼저 도착" ? (["a.png", "b.png"] as const) : (["b.png", "a.png"] as const);
      gates[x].resolve();
      await pause(5);
      gates[y].resolve();
      expect(await first).toEqual({ kind: "superseded" });
      expect(await second).toEqual({ kind: "ok" });
      expect(doc().frameSource).toBe("b.png");
      expect(doc().frame?.frame_id).toBe("b.png");
      expect(doc().frameLoading).toBe(false);
    });
  }

  test("정지 화면이 아직 없을 때 보낸 요청도 daemon 교체 뒤에 오면 쓰지 않는다", async () => {
    const gate = deferred();
    rpc = async (m, a) => {
      if (m === "target.load_image") {
        await gate.promise;
        return FRAME;
      }
      if (m === "target.preview") return preview(a.seq);
      throw new Error(m);
    };
    store.createTargetDoc(P, null);
    tabs.openTab({ path: P, kind: "target" });
    const pending = store.loadImageFrame(P, "a.png");
    store.framesHost.expireAll();
    gate.resolve();
    const outcome = await pending;
    expect(outcome.kind).toBe("error");
    expect(doc().frame).toBeNull();
    expect(doc().frameLoading).toBe(false);
  });
});

describe("편집 잠금", () => {
  test("대화 상자·저장하고 닫기 중에는 사양·영역을 고치지 않는다", async () => {
    rpc = async (m, a) => (m === "target.load_image" ? FRAME : preview(a.seq));
    await newDoc();
    const unlock = dialog.lockEdits();
    store.editSpec(P, (s) => setThreshold(s, 0.97));
    store.setTemplate(P, [0, 0, 10, 10]);
    expect(doc().spec).not.toHaveProperty("match");
    expect(doc().template).toEqual([412, 380, 200, 64]);
    unlock();
    store.editSpec(P, (s) => setThreshold(s, 0.97));
    expect(doc().spec).toHaveProperty("match", { threshold: 0.97 });
  });
});
