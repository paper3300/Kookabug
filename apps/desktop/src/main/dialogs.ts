// "분석 번들 내보내기" (M3 계획 2.7·2.10): 주 프로세스 저장 대화 상자가 zip 경로를 고르고 daemon run.export를 부른다.
// run.export는 렌더러 표면에 없다(ipc-guard INTERNAL_METHODS) — 렌더러는 실행 ID만 넘기고 쓸 경로는 사람이 대화
// 상자에서 고른 곳뿐이다. electron·node 모듈을 import하지 않는다 (vitest, preload 타입이 이 파일을 본다)
import { LOCAL_ERROR, RpcFailure, type RpcErrorShape } from "./rpc-connection";

export type ExportResult =
  | { ok: true; path: string; bytes: number }
  | { ok: false; reason: "canceled" }
  | { ok: false; reason: "failed"; error: RpcErrorShape };

export interface ExportDeps {
  /** 저장 대화 상자. 고른 절대 경로 (취소면 null) */
  pickSave(defaultName: string): Promise<string | null>;
  /** daemon 호출 (실패하면 RpcFailure를 던진다) */
  call(method: string, params: Record<string, unknown>): Promise<unknown>;
}

const RUN_ID = /^[a-z0-9]{8}$/;

/** 저장 대화 상자의 기본 파일 이름: 실행 폴더 이름.zip (모르면 kookabug-run-<id>.zip) */
export function bundleName(runId: string, runDir: unknown): string {
  const base = typeof runDir === "string" ? (runDir.split(/[\\/]/).filter(Boolean).pop() ?? "") : "";
  // Windows 파일 이름에 못 쓰는 글자는 바꾼다 (실행 폴더 이름은 시각·그래프 이름이라 보통 없다)
  const safe = base.replace(/[<>:"/\\|?*]/g, "_");
  return `${safe !== "" ? safe : `kookabug-run-${runId}`}.zip`;
}

export async function exportRun(runId: unknown, deps: ExportDeps): Promise<ExportResult> {
  if (typeof runId !== "string" || !RUN_ID.test(runId)) throw new TypeError("실행 ID가 아니다");
  try {
    let runDir: unknown = null;
    try {
      runDir = ((await deps.call("run.status", { run_id: runId })) as { run_dir?: unknown }).run_dir;
    } catch {
      // 이름만 못 정한다: 내보내기 자체의 오류는 run.export가 돌려준다
    }
    const dest = await deps.pickSave(bundleName(runId, runDir));
    if (dest === null) return { ok: false, reason: "canceled" };
    const result = (await deps.call("run.export", { run_id: runId, dest })) as { path: string; bytes: number };
    return { ok: true, path: result.path, bytes: result.bytes };
  } catch (err) {
    if (err instanceof RpcFailure) return { ok: false, reason: "failed", error: err.toShape() };
    return { ok: false, reason: "failed", error: { code: LOCAL_ERROR, message: (err as Error).message ?? String(err) } };
  }
}
