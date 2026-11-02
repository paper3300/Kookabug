// 기록 뷰어 글자: 스텝 제목(실행 스냅샷의 노드 제목 → 노드 종류 제목 → 노드 ID), 상태, 경과
import type { RunViewState, StepNode } from "./runIndexStore";

export type TypeTitle = (type: string) => string | null;

export function stepTitle(view: RunViewState, step: Pick<StepNode, "graph" | "node">, typeTitle: TypeTitle): string {
  const info = view.nodes.get(step.graph)?.get(step.node);
  if (info?.title != null && info.title !== "") return info.title;
  const byType = info?.type != null ? typeTitle(info.type) : null;
  return byType ?? step.node;
}

export const STATUS_LABEL: Record<string, string> = {
  success: "성공",
  fail: "실패",
  error: "오류",
  cancelled: "취소",
  running: "실행 중",
  aborted: "중단",
};

/** 스텝 경과 (0.4s, 12.0s, 3m 08s) */
export function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const s = Math.round(ms / 1000);
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export function isoMs(t: string | null | undefined): number | null {
  if (t === null || t === undefined || t === "") return null;
  const ms = Date.parse(t);
  return Number.isFinite(ms) ? ms : null;
}
