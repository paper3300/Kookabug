import { describe, expect, test } from "vitest";
import { bundleName, exportRun, type ExportDeps } from "./dialogs";
import { RpcFailure } from "./rpc-connection";

function deps(picked: string | null, fail?: RpcFailure): ExportDeps & { calls: { method: string; params: unknown }[]; names: string[] } {
  const calls: { method: string; params: unknown }[] = [];
  const names: string[] = [];
  return {
    calls,
    names,
    async pickSave(name) {
      names.push(name);
      return picked;
    },
    async call(method, params) {
      calls.push({ method, params });
      if (method === "run.status") return { run_dir: "D:/ws/runs/2026-11-02T01-00-00_viewer_fail_abcd1234" };
      if (fail !== undefined) throw fail;
      return { path: (params as { dest: string }).dest, bytes: 42 };
    },
  };
}

describe("분석 번들 내보내기 (M3 T11)", () => {
  test("test_export_picks_path_then_calls_run_export", async () => {
    const d = deps("C:/out/bundle.zip");
    const r = await exportRun("abcd1234", d);
    expect(r).toEqual({ ok: true, path: "C:/out/bundle.zip", bytes: 42 });
    expect(d.names).toEqual(["2026-11-02T01-00-00_viewer_fail_abcd1234.zip"]);
    expect(d.calls.at(-1)).toEqual({ method: "run.export", params: { run_id: "abcd1234", dest: "C:/out/bundle.zip" } });
  });

  test("test_export_canceled_calls_nothing", async () => {
    const d = deps(null);
    expect(await exportRun("abcd1234", d)).toEqual({ ok: false, reason: "canceled" });
    expect(d.calls.map((c) => c.method)).toEqual(["run.status"]);
  });

  test("test_export_failure_returned_as_value", async () => {
    const d = deps("C:/out/a.zip", new RpcFailure(-32000, "진행 중", { code: "run_active" }));
    expect(await exportRun("abcd1234", d)).toEqual({
      ok: false,
      reason: "failed",
      error: { code: -32000, message: "진행 중", data: { code: "run_active" } },
    });
  });

  test("test_export_rejects_bad_run_id", async () => {
    await expect(exportRun("../x", deps("C:/a.zip"))).rejects.toThrow(TypeError);
    await expect(exportRun(12, deps("C:/a.zip"))).rejects.toThrow(TypeError);
  });

  test("test_bundle_name_fallback", () => {
    expect(bundleName("abcd1234", null)).toBe("kookabug-run-abcd1234.zip");
    expect(bundleName("abcd1234", "runs\\x_abcd1234")).toBe("x_abcd1234.zip");
  });
});
