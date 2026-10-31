// 진단 → 그래프 노드 (M2 계획 2.7 문제 패널: 누르면 그 노드를 고르고 옮겨 간다).
// 진단의 `node`가 먼저다. 없으면 JSON pointer(`/nodes/<id>/…`, `/layout/nodes/<id>`)에서 노드를 찾는다.
// 다른 파일의 진단(서브그래프 안쪽 등)은 이 문서의 노드로 보지 않는다
import { parsePointer, type Diagnostic } from "../graph/model";

/** 이 문서의 진단인가 (file이 없으면 문서 자신의 진단) */
export function belongsTo(diag: Diagnostic, docPath: string): boolean {
  return diag.file === undefined || diag.file === null || diag.file === docPath;
}

export function problemNode(diag: Diagnostic, docPath: string, nodeIds: ReadonlySet<string>): string | null {
  if (!belongsTo(diag, docPath)) return null;
  if (typeof diag.node === "string" && nodeIds.has(diag.node)) return diag.node;
  const parts = typeof diag.pointer === "string" ? parsePointer(diag.pointer) : null;
  if (parts === null) return null;
  let id: string | undefined;
  if (parts[0] === "nodes") id = parts[1];
  else if (parts[0] === "layout" && parts[1] === "nodes") id = parts[2];
  return id !== undefined && nodeIds.has(id) ? id : null;
}

/** 문제 패널 정렬: 오류 먼저, 그다음 daemon 순서(코어 sort_diagnostics: 파일·pointer·코드) */
export function sortProblems<T extends { diag: Diagnostic }>(items: readonly T[]): T[] {
  const rank = (d: Diagnostic) => (d.severity === "error" ? 0 : 1);
  return items
    .map((item, i) => [item, i] as const)
    .sort(([a, ai], [b, bi]) => rank(a.diag) - rank(b.diag) || ai - bi)
    .map(([item]) => item);
}
