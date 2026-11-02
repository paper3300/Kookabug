// 스텝 타임라인 (M3 계획 2.10): 호출 트리. 서브그래프 호출 줄은 접고 펼치고, 반복 줄을 펼치면 회차 막대와 고른
// 회차의 스텝(run.children iteration)이 보인다. 반복 노드로 되돌아온 스텝(회차 끝)은 성공이면 숨긴다(회차 막대가
// 보여 준다). 줄마다 상태·제목·경과·출구, 재시도 스텝은 시도 수, 끝나지 않은 스텝은 "중단"·"실행 중"
import { useEffect, useRef } from "react";
import { ChevronDownIcon, ChevronRightIcon } from "../theme/icons";
import { IterationBars } from "./IterationBars";
import { formatMs, STATUS_LABEL, stepTitle, type TypeTitle } from "./labels";
import { childrenOf, pageKey, runIndexModel, topSteps, type RunViewState, type StepNode } from "./runIndexStore";
import css from "./runs.module.css";

const INDENT = 18;

function expandable(step: StepNode): boolean {
  return step.children > 0 || step.calls !== undefined || step.iterations !== undefined;
}

/** 반복 스텝 아래에서 숨기는 줄: 반복 노드로 되돌아와 다음 회차로 간 스텝 */
function hiddenReentry(parent: StepNode, child: StepNode): boolean {
  return parent.iterations !== undefined && child.node === parent.node && child.graph === parent.graph && child.status === "success";
}

function omittedShots(step: StepNode): boolean {
  return (step.omitted ?? []).some((o) => o.kind === "screenshot" || o.kind === "thumbnail");
}

function Row({ view, step, depth, typeTitle }: { view: RunViewState; step: StepNode; depth: number; typeTitle: TypeTitle }) {
  const open = view.expanded.has(step.step);
  const canOpen = expandable(step);
  const selected = view.selected === step.step;
  const iteration = step.iterations !== undefined ? (view.iteration.get(step.step) ?? null) : null;
  const page = view.pages.get(pageKey(step.step, iteration));
  const kids = open ? childrenOf(view, step).filter((c) => !hiddenReentry(step, c)) : [];
  const attempts = step.attempt > 1 ? `시도 ${step.attempt}` : null;
  return (
    <>
      <div
        role="treeitem"
        aria-selected={selected}
        aria-expanded={canOpen ? open : undefined}
        aria-level={depth + 1}
        className={css.row}
        style={{ paddingLeft: depth * INDENT + 4 }}
        data-part="timeline-row"
        data-step={step.step}
        data-node={step.node}
        data-graph={step.graph}
        data-status={step.status}
        data-iteration={step.iteration ?? ""}
        onClick={() => runIndexModel.select(view.runId, step.step)}
      >
        {canOpen ? (
          <button
            type="button"
            className={css.caret}
            aria-label={open ? "접기" : "펼치기"}
            data-part="timeline-toggle"
            onClick={(e) => {
              e.stopPropagation();
              runIndexModel.toggle(view.runId, step.step);
            }}
          >
            {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
          </button>
        ) : (
          <span className={css.caret} />
        )}
        <span className={css.status} data-status={step.status} data-part="row-status">
          {STATUS_LABEL[step.status] ?? step.status}
        </span>
        <span className={css.rowTitle}>{stepTitle(view, step, typeTitle)}</span>
        {step.iterations !== undefined && <span className={css.tag}>{step.iterations.length}회</span>}
        {omittedShots(step) && (
          <span className={css.tag} data-part="omitted-tag">
            생략
          </span>
        )}
        <span className={css.rowMeta}>
          {attempts !== null && <span>{attempts}</span>}
          {step.exit !== null && <span>{step.exit}</span>}
          <span>{step.status === "running" ? "…" : formatMs(step.duration_ms)}</span>
        </span>
      </div>
      {open && step.iterations !== undefined && (
        <div style={{ paddingLeft: (depth + 1) * INDENT }}>
          <IterationBars loop={step} selected={iteration} onPick={(i) => runIndexModel.setIteration(view.runId, step.step, i)} />
        </div>
      )}
      {open && kids.map((c) => <Row key={c.step} view={view} step={c} depth={depth + 1} typeTitle={typeTitle} />)}
      {open && page !== undefined && page.total > page.steps.length && (
        <button
          type="button"
          className={css.more}
          style={{ marginLeft: (depth + 1) * INDENT + 4 }}
          disabled={page.loading}
          onClick={() => void runIndexModel.loadMore(view.runId, step.step, iteration)}
        >
          스텝 {page.total - page.steps.length}개 더 보기
        </button>
      )}
      {open && page?.loading === true && page.steps.length === 0 && (
        <div className={css.listNote} style={{ paddingLeft: (depth + 1) * INDENT + 4 }}>
          읽는 중…
        </div>
      )}
    </>
  );
}

export function Timeline({ view, typeTitle }: { view: RunViewState; typeTitle: TypeTitle }) {
  const box = useRef<HTMLDivElement>(null);
  // 실패로 이동: 고른 줄이 그려지면 보이게 옮긴다 (펼친 쪽을 읽는 동안 다시 본다)
  const reveal = view.reveal;
  useEffect(() => {
    if (reveal === null) return;
    let frame = 0;
    let tries = 0;
    const go = () => {
      const row = box.current?.querySelector<HTMLElement>(`[data-step="${reveal.step}"]`);
      if (row === null || row === undefined) {
        if (tries++ < 120) frame = requestAnimationFrame(go);
        return;
      }
      row.scrollIntoView({ block: "center" });
    };
    go();
    return () => cancelAnimationFrame(frame);
  }, [reveal]);
  const top = topSteps(view);
  return (
    <div ref={box} role="tree" aria-label="스텝 타임라인" className={css.timeline} data-part="timeline">
      {top.length === 0 && <div className={css.listNote}>아직 스텝이 없어요</div>}
      {top.map((s) => (
        <Row key={s.step} view={view} step={s} depth={0} typeTitle={typeTitle} />
      ))}
    </div>
  );
}
