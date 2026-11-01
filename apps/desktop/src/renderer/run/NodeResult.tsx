// 노드 결과 패널 (M2 계획 2.8 "패널"): 지금 탭에서 고른 노드의 마지막 step.end (상태·출구·출력·오류·생략·
// artifact 경로). 비밀값은 기록에 이미 가려져 있다
import { graphNodes } from "../graph/model";
import { useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { useTabs } from "../store/tabs";
import { formatDuration, runningText, type StepRecord } from "./highlight";
import css from "./run.module.css";
import { useRun } from "./runStore";
import { useNow, useTabRunView } from "./view";

const OUTPUT_MAX = 4000;

const STATUS_LABEL = { success: "성공", fail: "실패", error: "오류", cancelled: "중단" } as const;

function joinRunPath(runDir: string | null, rel: string): string {
  if (runDir === null) return rel;
  const sep = runDir.includes("\\") ? "\\" : "/";
  return `${runDir.replace(/[\\/]+$/, "")}${sep}${rel.split("/").join(sep)}`;
}

function json(value: unknown): string {
  const text = JSON.stringify(value, null, 2) ?? "";
  return text.length > OUTPUT_MAX ? `${text.slice(0, OUTPUT_MAX)}\n…` : text;
}

function RunningRow({ step }: { step: StepRecord }) {
  const now = useNow(true);
  return (
    <div className={css.resultRow} data-part="node-result-running">
      <span className={css.toneRun}>{runningText(step.startT, now)}</span>
      <span>
        실행 중 · 스텝 {step.step}
        {step.iteration !== null ? ` · 회차 ${step.iteration + 1}` : ""}
      </span>
    </div>
  );
}

/** 끝난 스텝 하나의 결과 (마지막 step.end) */
function StepDetail({ step, runDir }: { step: StepRecord; runDir: string | null }) {
  const end = step.end;
  if (end === null) return null;
  const tone = end.status === "success" ? css.toneOk : end.status === "fail" ? css.toneFail : end.status === "error" ? css.toneError : css.toneMuted;
  const outputs = Object.keys(end.outputs).length > 0 ? json(end.outputs) : null;
  return (
    <>
      <div className={css.resultRow} data-part="node-result-status" data-status={end.interrupted ? "interrupted" : end.status}>
        <span className={tone}>{end.interrupted ? "중단됨" : STATUS_LABEL[end.status]}</span>
        {end.exit !== null && <span>출구 {end.exit}</span>}
        <span>{formatDuration(end.durationMs)}</span>
        <span className={css.muted}>
          스텝 {step.step}
          {step.attempt > 1 ? ` · 시도 ${step.attempt}` : ""}
          {step.iteration !== null ? ` · 회차 ${step.iteration + 1}` : ""}
        </span>
      </div>
      {end.error !== null && (
        <div className={`${css.resultRow} ${css.toneError}`} data-part="node-result-error">
          {end.error.code}: {end.error.message}
        </div>
      )}
      {end.error === null && end.message !== null && <div className={css.resultRow}>{end.message}</div>}
      {end.artifacts.length > 0 && (
        <div className={css.resultBlock} data-part="node-result-artifacts">
          <span className={css.muted}>증거</span>
          {end.artifacts.map((a) => (
            <span key={a} className={css.artifact} data-artifact={a}>
              {joinRunPath(runDir, a)}
            </span>
          ))}
        </div>
      )}
      {end.omitted.length > 0 && (
        <div className={css.resultBlock}>
          <span className={css.muted}>남기지 않은 증거</span>
          <pre className={css.pre}>{json(end.omitted)}</pre>
        </div>
      )}
      {outputs !== null && (
        <div className={css.resultBlock}>
          <span className={css.muted}>출력</span>
          <pre className={css.pre} data-part="node-result-outputs">
            {outputs}
          </pre>
        </div>
      )}
    </>
  );
}

export function NodeResult() {
  const path = useTabs((s) => (s.tabs.find((t) => t.path === s.active)?.kind === "graph" ? s.active : null));
  const doc = useDocuments((s) => (path === null ? undefined : s.docs.get(path)));
  const types = useRegistry((s) => s.types);
  const current = useRun((s) => s.current);
  const run = useTabRunView(path ?? "", path === null ? null : (doc?.value ?? null));
  const selected = doc?.view.selected ?? null;
  if (selected === null || doc?.value == null) return <div className={css.empty}>고른 노드가 없어요</div>;
  const node = graphNodes(doc.value).find((n) => n.id === selected);
  const title = node?.title ?? (node !== undefined ? types.get(node.type)?.title : undefined) ?? selected;
  const view = run?.nodes.get(selected) ?? null;
  return (
    <div data-part="node-result" data-node={selected} data-run-id={current?.runId ?? ""}>
      <div className={css.resultTitle}>
        <span className={css.resultNode}>{title}</span>
        <span className={css.muted}>{selected}</span>
      </div>
      {view === null ? (
        <div className={css.resultRow}>
          {current === null ? "실행 결과가 아직 없어요" : "이 실행에서 아직 돌지 않았어요"}
        </div>
      ) : (
        <>
          {/* 지금 도는 스텝(다음 회차)이 있어도 마지막으로 끝난 결과는 남긴다 */}
          {view.step.end === null && <RunningRow step={view.step} />}
          {view.step.end !== null && view.step.end.interrupted && (
            <StepDetail step={view.step} runDir={current?.runDir ?? null} />
          )}
          {view.result !== null && (view.step.end === null || view.step.end.interrupted) && (
            <div className={css.muted} data-part="node-result-previous">
              마지막으로 끝난 결과
            </div>
          )}
          {view.result !== null && <StepDetail step={view.result} runDir={current?.runDir ?? null} />}
        </>
      )}
    </div>
  );
}
