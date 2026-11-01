// 설치본 스모크 순서 (M2 계획 2.14 T13): 붙기(hello) → 열기 → 무수정 저장(wrote: false) → 닫기 → daemon 끄기 → 종료 코드 0
import path from "node:path";
import { describe, expect, test } from "vitest";
import type { DaemonState } from "./daemon-state";
import { parseSmokeArgs, runSmoke, SMOKE_GRAPH, type SmokeDaemon, withDeadline } from "./smoke";

const root = path.resolve("C:/ws/example");

const connected: DaemonState = {
  status: "connected",
  root,
  appProtocol: 1,
  startId: "a".repeat(32),
  daemonVersion: "0.1.0.dev0",
  protocol: 1,
  connection: 1,
};

interface FakeOptions {
  state?: DaemonState;
  wrote?: boolean;
  saveRevision?: string;
  fail?: Record<string, Error & { kind?: string }>;
}

function fake(options: FakeOptions = {}) {
  const calls: Array<[string, unknown]> = [];
  const events: string[] = [];
  const value = { format: "kookabug.graph/0", nodes: { a: { type: "core.start" } }, big: 1e20 };
  const daemon: SmokeDaemon = {
    async open(r) {
      events.push(`open ${r}`);
      return options.state ?? connected;
    },
    async call(method, params) {
      calls.push([method, params]);
      events.push(method);
      const failure = options.fail?.[method];
      if (failure) throw failure;
      if (method === "graph.open") return { doc_id: "d1", revision: "r1", value, canonical: true, diagnostics: [], shapes: {} };
      if (method === "graph.save") {
        return { wrote: options.wrote ?? false, revision: options.saveRevision ?? "r1", canonicalized: false, diagnostics: [] };
      }
      return {};
    },
    detach() {
      events.push("detach");
    },
  };
  return { daemon, calls, events, value };
}

function rpcError(message: string, kind: string): Error & { kind: string } {
  return Object.assign(new Error(message), { kind });
}

describe("스모크 순서", () => {
  test("test_smoke_sequence_hello_open_save_nowrite_exit0", async () => {
    const f = fake();
    const result = await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, f.daemon);
    expect(result.code).toBe(0);
    expect(result.ok).toBe(true);
    expect(result.steps.map((s) => s.id)).toEqual([
      "session.hello",
      "graph.open",
      "graph.save",
      "graph.close",
      "daemon.shutdown",
    ]);
    expect(f.events).toEqual([`open ${root}`, "graph.open", "graph.save", "graph.close", "daemon.shutdown", "detach"]);
    // 저장은 연 값 그대로·연 revision 기준 (무수정 저장)
    expect(f.calls[0]).toEqual(["graph.open", { path: SMOKE_GRAPH }]);
    expect(f.calls[1]).toEqual(["graph.save", { doc_id: "d1", base_revision: "r1", value: f.value }]);
    expect(f.calls[2]).toEqual(["graph.close", { doc_id: "d1" }]);
  });

  test("저장이 파일을 썼으면(wrote: true) 실패, daemon은 그래도 끈다", async () => {
    const f = fake({ wrote: true });
    const result = await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, f.daemon);
    expect(result.code).toBe(1);
    expect(result.steps.find((s) => s.id === "graph.save")?.ok).toBe(false);
    expect(f.events.slice(-2)).toEqual(["daemon.shutdown", "detach"]);
    // revision이 바뀌어도 실패
    expect((await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, fake({ saveRevision: "r2" }).daemon)).code).toBe(1);
  });

  test("붙지 못하면 실패하고 다른 메서드를 부르지 않는다", async () => {
    const f = fake({ state: { status: "error", root, appProtocol: 1, error: "cli_not_found", message: "kookabug CLI를 찾지 못했다" } });
    const result = await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, f.daemon);
    expect(result.code).toBe(1);
    expect(result.steps).toEqual([{ id: "session.hello", ok: false, detail: "error: kookabug CLI를 찾지 못했다" }]);
    expect(f.calls).toEqual([]);
    expect(f.events).toEqual([`open ${root}`, "detach"]);
  });

  test("열기 실패는 실패, 끄기는 한다", async () => {
    const f = fake({ fail: { "graph.open": rpcError("없는 파일", "not_found") } });
    const result = await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, f.daemon);
    expect(result.code).toBe(1);
    expect(f.events).toEqual([`open ${root}`, "graph.open", "daemon.shutdown", "detach"]);
  });

  test("끄기 응답 전에 연결이 닫히면(not_connected) 통과, 다른 거부는 실패", async () => {
    const gone = fake({ fail: { "daemon.shutdown": rpcError("연결이 없다", "not_connected") } });
    expect((await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, gone.daemon)).code).toBe(0);
    const busy = fake({ fail: { "daemon.shutdown": rpcError("진행 중인 실행", "run_active") } });
    expect((await runSmoke({ workspace: root, graph: SMOKE_GRAPH, report: null }, busy.daemon)).code).toBe(1);
  });

  test("워크스페이스가 없으면 바로 실패", async () => {
    const f = fake();
    const result = await runSmoke({ workspace: "", graph: SMOKE_GRAPH, report: null }, f.daemon);
    expect(result.code).toBe(1);
    expect(f.events).toEqual([]);
  });

  test("기한을 넘기면 실패 결과", async () => {
    const never = new Promise<never>(() => {});
    const result = await withDeadline(never, 20);
    expect(result.code).toBe(1);
    expect(result.steps[0].id).toBe("timeout");
  });
});

describe("명령줄", () => {
  test("--smoke가 없으면 null, 값은 공백·= 두 모양", () => {
    expect(parseSmokeArgs(["Kookabug.exe", "--user-data-dir=x"])).toBeNull();
    expect(parseSmokeArgs(["Kookabug.exe", "--smoke", "C:/ws/example"])).toEqual({
      workspace: root,
      graph: SMOKE_GRAPH,
      report: null,
    });
    expect(
      parseSmokeArgs(["Kookabug.exe", "--smoke=C:/ws/example", "--smoke-graph", "a/b.graph.json", "--smoke-report=C:/out/r.json"]),
    ).toEqual({ workspace: root, graph: "a/b.graph.json", report: path.resolve("C:/out/r.json") });
    expect(parseSmokeArgs(["Kookabug.exe", "--smoke"])?.workspace).toBe("");
  });
});
