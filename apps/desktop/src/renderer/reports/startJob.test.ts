// UX5 후속 (CI): 보고가 "done"이 된 직후 누르면 앞 작업의 CLI가 아직 마무리 중이라 주 프로세스가 job_active로 거절한다.
// 저절로 다시 띄우지 않고(UX6 검수 1 High 1·Mid 3) 목록에 도는 작업이 없으면 "정리하는 중 — 다시 눌러 주세요"로 안내한다
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("../rpc/client", async (original) => {
  const mod = await original<typeof import("../rpc/client")>();
  const answers: Record<string, unknown> = {
    "agents.get": { agents: [{ id: "codex" }], default_agent: "codex" },
    "jobs.list": { jobs: [] },
    "reports.list": { reports: [] },
    "adoptions.list": { adoptions: [] },
  };
  return { ...mod, client: () => ({ call: async (method: string) => answers[method] ?? {} }) };
});

const { busyText, startEntry, useReports } = await import("./reportsStore");

const JOB = "j-20261113-000000-aaaa";
const RUNNING = [{ job: "j-20261113-000001-bbbb", playbook: "init", state: "running", started_at: "2026-11-13T00:00:01Z" }];
let agentJobRun: ReturnType<typeof vi.fn>;

beforeEach(() => {
  agentJobRun = vi.fn();
  (globalThis as unknown as { kookabug: unknown }).kookabug = { app: { agentJobRun } };
  useReports.setState({ rows: [], pending: new Set(), messages: {}, follow: false });
});

describe("접속 경로 시작: 앞 작업 CLI 마무리 중", () => {
  test("목록에 도는 작업이 없으면 한 번만 부르고 다시 눌러 달라고 안내한다", async () => {
    agentJobRun.mockResolvedValue({ started: false, error_code: "job_active" });
    await startEntry(JOB);
    expect(agentJobRun).toHaveBeenCalledTimes(1);
    expect(useReports.getState().messages[`entry:${JOB}`]).toBe("앞 작업을 정리하는 중이에요. 잠시 뒤 다시 눌러 주세요");
    expect(useReports.getState().pending.size).toBe(0);
  });

  test("목록에 도는 작업이 있으면 그 작업이 도는 중이라고 안내한다", () => {
    expect(busyText(RUNNING as never)).not.toMatch(/정리하는 중/);
    expect(busyText([])).toMatch(/정리하는 중/);
  });

  test("시작되면 시작 안내", async () => {
    agentJobRun.mockResolvedValue({ started: true });
    await startEntry(JOB);
    expect(agentJobRun).toHaveBeenCalledWith("entry", "codex");
    expect(useReports.getState().messages[`entry:${JOB}`]).toMatch(/시작했어요/);
  });
});
