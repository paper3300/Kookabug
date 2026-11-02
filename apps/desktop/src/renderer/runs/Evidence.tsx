// 고른 스텝의 스크린샷 줄과 매칭 후보 표 (시안 RunViewer 아래쪽). 칸은 evidenceCells.ts가 정하고, 후보 상자는
// 마지막 칸 이미지 위에 그린다(후보 사각형은 _fail 이미지 좌표). "그래프에서 보기"는 실행 스냅샷 그래프를
// 읽기 전용 탭으로 연다 (viewInGraph.ts)
import { useState } from "react";
import { formatClock } from "../run/highlight";
import { candidateRows, evidenceCells, stepEnd, type EvidenceCell } from "./evidenceCells";
import { isoMs, stepTitle, type TypeTitle } from "./labels";
import type { RunViewState, StepDetail, StepNode } from "./runIndexStore";
import css from "./runs.module.css";
import { viewInGraph } from "./viewInGraph";

function fileUrl(runDir: string, file: string): string {
  return `kbimg://ws/${`${runDir}/${file}`.split("/").map(encodeURIComponent).join("/")}`;
}

interface Size {
  w: number;
  h: number;
}

/** object-fit: contain 으로 그린 그림의 상자 안 위치 (%) */
function fitted(img: Size, box: Size): { left: number; top: number; width: number; height: number } {
  const scale = Math.min(box.w / img.w, box.h / img.h);
  const w = img.w * scale;
  const h = img.h * scale;
  return { left: ((box.w - w) / 2 / box.w) * 100, top: ((box.h - h) / 2 / box.h) * 100, width: (w / box.w) * 100, height: (h / box.h) * 100 };
}

function Shot({ cell, runDir, detail, clock }: { cell: EvidenceCell; runDir: string; detail: StepDetail; clock: string }) {
  const [natural, setNatural] = useState<Size | null>(null);
  const [box, setBox] = useState<Size | null>(null);
  if (cell.file === null) {
    return (
      <div className={css.shot} data-part="shot" data-kind={cell.key}>
        <div className={css.shotHead}>
          <span className={css.shotLabel}>{cell.label}</span>
          <span className={css.shotTime}>{clock}</span>
        </div>
        <div className={css.omit} data-part={cell.key === "omitted" ? "omitted-cell" : "missing-cell"}>
          <span className={css.omitTitle}>{cell.key === "omitted" ? "정책으로 생략" : cell.reason}</span>
          {cell.key === "omitted" && <span className={css.omitReason}>{cell.reason}</span>}
        </div>
      </div>
    );
  }
  const ev = stepEnd(detail)?.evidence;
  const candidates = cell.candidates ? (ev?.candidates ?? []) : [];
  const inner = natural !== null && box !== null ? fitted(natural, box) : null;
  return (
    <div className={css.shot} data-part="shot" data-kind={cell.key} data-file={cell.file}>
      <div className={css.shotHead}>
        <span className={css.shotLabel}>{cell.label}</span>
        <span className={css.shotTime}>{clock}</span>
      </div>
      <div
        className={css.frame}
        ref={(el) => {
          if (el !== null && (box === null || box.w !== el.clientWidth || box.h !== el.clientHeight)) {
            if (el.clientWidth > 0) setBox({ w: el.clientWidth, h: el.clientHeight });
          }
        }}
      >
        <img
          className={css.frameImg}
          src={fileUrl(runDir, cell.file)}
          alt={cell.label}
          data-part="shot-image"
          onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
        />
        {inner !== null && natural !== null && candidates.length > 0 && (
          <div
            className={css.frameInner}
            style={{ left: `${inner.left}%`, top: `${inner.top}%`, width: `${inner.width}%`, height: `${inner.height}%` }}
          >
            {candidates.map((c, i) => {
              const [x, y, w, h] = c.rect;
              return (
                <div key={i}>
                  <div
                    className={css.candidate}
                    data-part="candidate-box"
                    style={{
                      left: `${(x / natural.w) * 100}%`,
                      top: `${(y / natural.h) * 100}%`,
                      width: `${(w / natural.w) * 100}%`,
                      height: `${(h / natural.h) * 100}%`,
                    }}
                  />
                  <div
                    className={css.candidateScore}
                    style={{ left: `${((x + w) / natural.w) * 100 + 0.5}%`, top: `${(y / natural.h) * 100}%` }}
                  >
                    {c.score.toFixed(2)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

function Candidates({ detail }: { detail: StepDetail }) {
  const rows = candidateRows(detail);
  const ev = stepEnd(detail)?.evidence;
  if (rows.length === 0) return null;
  const target = ev?.target?.split("/").pop()?.replace(/\.target\.json$/, "") ?? "";
  const threshold = ev?.threshold;
  return (
    <div className={css.box} data-part="candidates">
      <div className={css.boxHead}>
        매칭 후보{target !== "" ? ` · ${target}` : ""}
        {threshold !== undefined ? ` (임계값 ${threshold.toFixed(2)})` : ""}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className={css.table}>
          <thead>
            <tr>
              <th>#</th>
              <th>점수</th>
              <th>위치</th>
              <th>배율</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.rank} data-part="candidate-row">
                <td>{r.rank}</td>
                <td className={r.rank === 1 ? css.scoreTop : css.scoreRest}>{r.score.toFixed(2)}</td>
                <td>
                  ({r.x}, {r.y})
                </td>
                <td>{r.scale.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function Evidence({
  view,
  step,
  shortId,
  typeTitle,
}: {
  view: RunViewState;
  step: StepNode;
  shortId: string;
  typeTitle: TypeTitle;
}) {
  const detail = view.details.get(step.step);
  const index = view.index!;
  const runStart = isoMs(typeof index.run?.started_at === "string" ? index.run.started_at : null) ?? isoMs(index.steps[0]?.t_start);
  const stepStart = isoMs(step.t_start);
  const testGraph = typeof index.run?.graph === "string" ? index.run.graph : null;
  const clockOf = (cell: EvidenceCell) =>
    cell.atMs === null || stepStart === null || runStart === null ? "" : formatClock(stepStart - runStart + cell.atMs).slice(0, -2);
  const cells = typeof detail === "object" ? evidenceCells(step, detail, testGraph) : [];
  return (
    <section aria-label="스텝 증거" data-part="evidence" data-step={step.step}>
      <div className={css.stepHead}>
        <span className={css.stepTitle}>{stepTitle(view, step, typeTitle)}</span>
        <span className={css.stepPath} title={step.path.join(" › ")}>
          {step.graph}
          {step.message !== undefined ? ` · ${step.message}` : ""}
        </span>
        <button
          type="button"
          className={css.button}
          data-part="view-in-graph"
          onClick={() => void viewInGraph({ runId: view.runId, runDir: index.run_dir, shortId }, step.graph, step.node)}
        >
          그래프에서 보기
        </button>
      </div>
      {detail === "loading" || detail === undefined ? (
        <div className={css.message}>읽는 중…</div>
      ) : detail === "error" ? (
        <div className={css.message}>스텝 기록을 읽지 못했어요</div>
      ) : (
        <>
          {cells.length === 0 ? (
            <div className={css.message} data-part="no-shots">
              이 스텝은 화면을 남기지 않았어요
            </div>
          ) : (
            <div className={css.shots} data-part="shots">
              {cells.map((c) => (
                <Shot key={c.key} cell={c} runDir={index.run_dir} detail={detail} clock={clockOf(c)} />
              ))}
            </div>
          )}
          <div className={css.tables}>
            <Candidates detail={detail} />
          </div>
        </>
      )}
    </section>
  );
}
