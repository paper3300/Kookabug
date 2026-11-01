// 설치본 스모크 (M2 계획 2.14): `Kookabug.exe --smoke <워크스페이스> [--smoke-graph <경로>] [--smoke-report <파일>]`
// → daemon 띄우기·붙기(session.hello) → graph.open → graph.save(아무것도 안 바꿈, wrote: false) → graph.close →
// daemon.shutdown → 종료 코드 0. 창을 띄우지 않는다. 설치 검사(tools/installer/smoke.py)와 CI installer 잡이 쓴다.
// electron을 import하지 않는다 (vitest). 연결은 DaemonManager(daemon.ts)를 그대로 쓴다
import path from "node:path";
import type { DaemonState } from "./daemon-state";

/** 예제 워크스페이스의 헤드리스 스모크 그래프 (CLI 스모크와 같은 파일) */
export const SMOKE_GRAPH = "tests/smoke_headless.graph.json";
/** 스모크 전체 기한. 넘으면 실패로 끝낸다 (설치 검사가 멈춘 앱을 기다리지 않게) */
export const SMOKE_TIMEOUT_MS = 90_000;

export interface SmokeArgs {
  workspace: string;
  /** 워크스페이스 기준 그래프 경로 (/ 구분) */
  graph: string;
  /** 결과 JSON을 쓸 파일 (없으면 표준 출력만) */
  report: string | null;
}

function option(argv: readonly string[], name: string): string | null | undefined {
  const flag = `--${name}`;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === flag) return i + 1 < argv.length ? argv[i + 1] : null;
    if (a.startsWith(`${flag}=`)) return a.slice(flag.length + 1);
  }
  return undefined;
}

/** 명령줄에서 스모크 인자를 읽는다. `--smoke`가 없으면 null. 값이 빠졌으면 workspace가 빈 문자열 */
export function parseSmokeArgs(argv: readonly string[]): SmokeArgs | null {
  const workspace = option(argv, "smoke");
  if (workspace === undefined) return null;
  const graph = option(argv, "smoke-graph");
  const report = option(argv, "smoke-report");
  return {
    workspace: workspace === null ? "" : path.resolve(workspace),
    graph: graph || SMOKE_GRAPH,
    report: report ? path.resolve(report) : null,
  };
}

/** 스모크가 쓰는 daemon 관리자 기능 (DaemonManager) */
export interface SmokeDaemon {
  open(root: string): Promise<DaemonState>;
  call(method: string, params: unknown): Promise<unknown>;
  detach(): void;
}

export interface SmokeStep {
  id: string;
  ok: boolean;
  detail: string;
}

export interface SmokeResult {
  ok: boolean;
  /** 프로세스 종료 코드: 0 = 전부 통과, 1 = 실패 */
  code: number;
  steps: SmokeStep[];
}

interface OpenResult {
  doc_id: string;
  revision: string;
  value: unknown;
}

interface SaveResult {
  wrote: boolean;
  revision: string;
}

function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * 붙기 → 열기 → 무수정 저장 → 닫기 → daemon 끄기. 단계마다 결과를 남기고, 실패하면 남은 단계를 건너뛰되 daemon은
 * 끄려고 한다(설치 폴더의 Python이 남으면 제거가 막힌다)
 */
export async function runSmoke(args: SmokeArgs, daemon: SmokeDaemon): Promise<SmokeResult> {
  const steps: SmokeStep[] = [];
  const step = (id: string, ok: boolean, detail: string): boolean => {
    steps.push({ id, ok, detail });
    return ok;
  };
  const finish = (): SmokeResult => {
    const ok = steps.length > 0 && steps.every((s) => s.ok);
    return { ok, code: ok ? 0 : 1, steps };
  };

  if (args.workspace === "") {
    step("args", false, "--smoke에 워크스페이스 폴더가 없다");
    return finish();
  }
  let connected = false;
  const body = async (): Promise<void> => {
    const state = await daemon.open(args.workspace);
    connected = state.status === "connected";
    const detail = connected
      ? `start_id ${state.startId}, daemon ${state.daemonVersion}, protocol ${state.protocol}`
      : `${state.status}: ${state.message ?? ""}${state.logPath ? ` (로그 ${state.logPath})` : ""}`;
    if (!step("session.hello", connected, detail)) return;

    let opened: OpenResult;
    try {
      opened = (await daemon.call("graph.open", { path: args.graph })) as OpenResult;
    } catch (err) {
      step("graph.open", false, message(err));
      return;
    }
    step("graph.open", true, `${args.graph} (doc ${opened.doc_id}, revision ${opened.revision})`);
    try {
      const saved = (await daemon.call("graph.save", {
        doc_id: opened.doc_id,
        base_revision: opened.revision,
        value: opened.value,
      })) as SaveResult;
      const same = saved.wrote === false && saved.revision === opened.revision;
      step("graph.save", same, `wrote ${saved.wrote}, revision ${saved.revision === opened.revision ? "같음" : "다름"}`);
    } catch (err) {
      step("graph.save", false, message(err));
    }
    try {
      await daemon.call("graph.close", { doc_id: opened.doc_id });
      step("graph.close", true, "닫음");
    } catch (err) {
      step("graph.close", false, message(err));
    }
  };
  try {
    await body();
  } catch (err) {
    step("session.hello", false, message(err));
  }
  if (connected) {
    try {
      await daemon.call("daemon.shutdown", {});
      step("daemon.shutdown", true, "요청함");
    } catch (err) {
      // 응답보다 연결 닫힘이 먼저 오면 not_connected다: daemon은 끝나는 중이다
      const gone = (err as { kind?: unknown }).kind === "not_connected";
      step("daemon.shutdown", gone, gone ? "응답 전에 연결이 닫힘 (끝나는 중)" : message(err));
    }
  }
  daemon.detach();
  return finish();
}

/** 기한 안에 끝나지 않으면 실패 결과 */
export function withDeadline(work: Promise<SmokeResult>, ms: number = SMOKE_TIMEOUT_MS): Promise<SmokeResult> {
  return new Promise((resolve) => {
    const timer = setTimeout(
      () => resolve({ ok: false, code: 1, steps: [{ id: "timeout", ok: false, detail: `${ms / 1000}초 안에 끝나지 않았다` }] }),
      ms,
    );
    work.then(
      (result) => {
        clearTimeout(timer);
        resolve(result);
      },
      (err: unknown) => {
        clearTimeout(timer);
        resolve({ ok: false, code: 1, steps: [{ id: "error", ok: false, detail: message(err) }] });
      },
    );
  });
}
