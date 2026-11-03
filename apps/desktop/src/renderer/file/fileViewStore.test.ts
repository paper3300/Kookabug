// 보기 탭 내용·탭 종류 (다듬기 P1-B)
import { beforeEach, describe, expect, test } from "vitest";
import { create } from "zustand";
import { RpcError, type RpcCall } from "../rpc/client";
import { closeTab, fileBadgeText, fileViewKind, openFileTab, openTab, tabBadge, useTabs } from "../store/tabs";
import { FileViewModel, type FileView } from "./fileViewStore";

interface Pending {
  params: { path: string };
  resolve(value: unknown): void;
  reject(err: unknown): void;
}

function fakeDaemon() {
  const pending: Pending[] = [];
  const calls: string[] = [];
  const call = ((method: string, params: { path: string }) => {
    calls.push(`${method} ${params.path}`);
    return new Promise((resolve, reject) => pending.push({ params, resolve, reject }));
  }) as unknown as RpcCall;
  const take = (path: string): Pending => {
    const i = pending.findIndex((p) => p.params.path === path);
    if (i < 0) throw new Error(`${path} 요청이 없다`);
    return pending.splice(i, 1)[0];
  };
  return { call, calls, pending, take };
}

const flush = () => new Promise((r) => setTimeout(r, 0));
const result = (text: string, extra: object = {}) => ({ text, bytes: text.length, truncated: false, binary: false, ...extra });

function setup() {
  const daemon = fakeDaemon();
  const store = create<{ views: ReadonlyMap<string, FileView> }>(() => ({ views: new Map() }));
  const model = new FileViewModel(() => daemon.call, store);
  return { daemon, store, model };
}

describe("보기 종류·탭 글자", () => {
  test.each([
    ["screens/lobby.screen.json", "json", "SCREEN"],
    ["kookabug.json", "json", "JSON"],
    ["kookabug.lock", "json", "JSON"],
    ["tests/data/values.json", "json", "JSON"],
    ["AGENTS.md", "text", "MD"],
    ["tests/notes.txt", "text", "TEXT"],
    ["targets/login/login_button.png", "image", "IMAGE"],
    ["targets/a/B.JPG", "image", "IMAGE"],
  ])("%s → %s · %s", (path, kind, badge) => {
    expect(fileViewKind(path)).toBe(kind);
    expect(fileBadgeText(path)).toBe(badge);
    expect(tabBadge({ kind: "file", graphKind: null, path })).toEqual({ text: badge, tone: "file" });
  });
});

describe("openFileTab", () => {
  beforeEach(() => useTabs.setState({ tabs: [], active: null }));

  test("파일 이름 제목의 file 탭, 이미 열려 있으면 그 탭으로", () => {
    openFileTab("screens/lobby.screen.json");
    openTab({ path: "tests/a.graph.json", kind: "graph", graphKind: "test" });
    openFileTab("screens/lobby.screen.json");
    const { tabs, active } = useTabs.getState();
    expect(tabs.map((t) => [t.path, t.kind, t.title])).toEqual([
      ["screens/lobby.screen.json", "file", "lobby.screen.json"],
      ["tests/a.graph.json", "graph", "a"],
    ]);
    expect(active).toBe("screens/lobby.screen.json");
    closeTab("screens/lobby.screen.json");
    expect(useTabs.getState().tabs.map((t) => t.path)).toEqual(["tests/a.graph.json"]);
  });
});

describe("FileViewModel", () => {
  test("열린 보기 탭을 읽고, 닫으면 버린다", async () => {
    const { daemon, model } = setup();
    model.sync(["kookabug.json", "targets/a.png"]);
    expect(model.get("kookabug.json")?.status).toBe("loading");
    // 이미지는 RPC로 읽지 않는다 (kbimg://ws/)
    expect(daemon.calls).toEqual(["workspace.read kookabug.json"]);
    expect(model.get("targets/a.png")).toMatchObject({ kind: "image", status: "ready" });
    expect(model.get("targets/a.png")!.version).toBeGreaterThan(0);
    daemon.take("kookabug.json").resolve(result('{"a":1}', { bytes: 7 }));
    await flush();
    expect(model.get("kookabug.json")).toMatchObject({ kind: "json", status: "ready", text: '{"a":1}', bytes: 7, version: 1 });
    model.sync(["targets/a.png"]);
    expect(model.get("kookabug.json")).toBeUndefined();
  });

  test("바뀐 경로만 다시 읽고, 다시 읽는 동안 앞 내용을 둔다", async () => {
    const { daemon, model } = setup();
    model.sync(["a.json", "b.md", "c.png"]);
    daemon.take("a.json").resolve(result("1"));
    daemon.take("b.md").resolve(result("# b"));
    await flush();
    daemon.calls.length = 0;
    const image = model.get("c.png")!.version;
    model.changed(["b.md", "tests/other.graph.json", "c.png"]);
    expect(daemon.calls).toEqual(["workspace.read b.md"]);
    expect(model.get("b.md")).toMatchObject({ status: "ready", text: "# b" });
    expect(model.get("c.png")!.version).toBeGreaterThan(image);
    daemon.take("b.md").resolve(result("# b2"));
    await flush();
    expect(model.get("b.md")).toMatchObject({ text: "# b2", version: 2 });
    expect(model.get("a.json")?.version).toBe(1);
    // 빈 경로 목록 = 모두
    daemon.calls.length = 0;
    model.reloadAll();
    expect(daemon.calls.sort()).toEqual(["workspace.read a.json", "workspace.read b.md"]);
  });

  test("늦게 온 앞 응답은 버린다 (닫았다 다시 연 탭 포함)", async () => {
    const { daemon, model } = setup();
    model.sync(["a.json"]);
    const first = daemon.take("a.json");
    model.changed(["a.json"]);
    const second = daemon.take("a.json");
    second.resolve(result("new"));
    first.resolve(result("old"));
    await flush();
    expect(model.get("a.json")?.text).toBe("new");

    model.sync([]);
    model.sync(["a.json"]);
    const reopened = daemon.take("a.json");
    model.sync([]);
    model.sync(["a.json"]);
    const latest = daemon.take("a.json");
    reopened.resolve(result("stale"));
    await flush();
    expect(model.get("a.json")?.status).toBe("loading");
    latest.resolve(result("fresh"));
    await flush();
    expect(model.get("a.json")?.text).toBe("fresh");
  });

  test("없어진 파일·읽기 실패는 error, 다시 생기면 ready", async () => {
    const { daemon, model } = setup();
    model.sync(["screens/x.screen.json", "tests/y.txt"]);
    daemon.take("screens/x.screen.json").reject(new RpcError(-32100, "없다", { code: "not_found" }));
    daemon.take("tests/y.txt").reject(new RpcError(-32100, "접근 거부", { code: "io_error" }));
    await flush();
    expect(model.get("screens/x.screen.json")).toMatchObject({ status: "error", error: "파일이 없어요" });
    expect(model.get("tests/y.txt")).toMatchObject({ status: "error", error: "접근 거부" });
    model.changed(["screens/x.screen.json"]);
    daemon.take("screens/x.screen.json").resolve(result("{}"));
    await flush();
    expect(model.get("screens/x.screen.json")).toMatchObject({ status: "ready", error: null, text: "{}" });
  });

  test("reset은 모두 버린다", () => {
    const { model, store } = setup();
    model.sync(["a.json"]);
    model.reset();
    expect(store.getState().views.size).toBe(0);
  });
});
