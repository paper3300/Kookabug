// 멈춤 띠 (M3 계획 2.9, U2): 경로 표시줄 아래에 "⏸ 멈춤 · 이유 · 노드"와 재개 경고를 띄운다. 재개 경고는 경계에서
// 멈춘 노드의 입력이 관측 노드 출력에서 오면 낸다 (staleWarning.ts, 판정은 runner). 멈춘 노드가 든 그래프 파일이
// 탭에 열려 있을 때만 그래프 모양을 본다
import type { TypeIndex } from "../graph/mapping";
import { graphNodes, type GraphValue } from "../graph/model";
import { useRun } from "../run/runStore";
import { useDocuments, type GraphDoc } from "../store/documents";
import { useRegistry } from "../store/registry";
import css from "./debug.module.css";
import { REASON_TEXT, type PausePoint } from "./pauseState";
import { staleInputs, staleWarningText } from "./staleWarning";

function nodeTitle(value: GraphValue | null, id: string, types: TypeIndex): string {
  const node = value === null ? undefined : graphNodes(value).find((n) => n.id === id);
  if (node === undefined) return id;
  if (node.title !== null && node.title !== "") return node.title;
  return types.get(node.type)?.title ?? id;
}

/** 멈춘 노드 이름: 그 그래프 파일이 열려 있으면 버퍼의 제목, 아니면 노드 ID */
export function pausedTitle(point: PausePoint, docs: ReadonlyMap<string, GraphDoc>, types: TypeIndex): string {
  const id = point.node ?? point.step ?? "";
  const value = point.graph === null ? null : (docs.get(point.graph)?.value ?? null);
  return nodeTitle(value, id, types);
}

/** 재개하면 오래된 관측값을 쓰게 되는 경계 멈춤이면 그 문구 */
export function resumeWarning(point: PausePoint, docs: ReadonlyMap<string, GraphDoc>, types: TypeIndex): string | null {
  if (point.where !== "boundary" || point.node === null || point.graph === null) return null;
  const value = docs.get(point.graph)?.value ?? null;
  if (value === null) return null;
  const sources = staleInputs(value, point.node, types);
  if (sources.length === 0) return null;
  return staleWarningText(nodeTitle(value, point.node, types), sources, (id) => nodeTitle(value, id, types));
}

export function PauseBanner() {
  const current = useRun((s) => s.current);
  const docs = useDocuments((s) => s.docs);
  const types = useRegistry((s) => s.types);
  const point = current?.phase === "running" ? current.pause.paused : null;
  if (point === null || point === undefined) return null;
  const warning = resumeWarning(point, docs, types);
  return (
    <div
      role="status"
      aria-label="멈춤"
      className={css.banner}
      data-part="pause-banner"
      data-reason={point.reason}
      data-where={point.where}
      data-node={point.node ?? ""}
    >
      <span className={css.bannerTitle}>
        ⏸ 멈춤 · {REASON_TEXT[point.reason]} · {pausedTitle(point, docs, types)}
        {point.where === "poll" ? " (기다리는 중)" : ""}
      </span>
      {warning !== null && (
        <span className={css.warning} data-part="resume-warning">
          {warning}
        </span>
      )}
    </div>
  );
}
