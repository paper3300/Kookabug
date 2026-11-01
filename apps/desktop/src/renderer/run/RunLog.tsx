// 실행 로그 패널 (시안 Main 하단 "실행 로그"): 시각(실행 시작부터)·수준·노드·메시지, 새 줄이 위.
// 열린 스텝은 맨 위 RUN 줄로 흐르는 시간을 보인다. 수준 색은 RUN·OK·WARN·INFO (2.8 "패널")
import { useMemo } from "react";
import { useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { formatClock, runningText, stepLabel, type LogEntry, type LogLevel } from "./highlight";
import css from "./run.module.css";
import { useRun } from "./runStore";
import { docLookup, typeTitleOf, useNow } from "./view";

const LEVEL_CLASS: Record<LogLevel, string> = {
  RUN: css.levelRun,
  OK: css.levelOk,
  WARN: css.levelWarn,
  INFO: css.levelInfo,
  FAIL: css.levelFail,
  ERROR: css.levelError,
  STOP: css.levelInfo,
};

interface Line {
  key: string;
  seq: number;
  t: number;
  level: LogLevel;
  path: readonly string[] | null;
  message: string;
  since: number | null;
}

export function RunLog() {
  const current = useRun((s) => s.current);
  const docs = useDocuments((s) => s.docs);
  const types = useRegistry((s) => s.types);
  const running = current?.phase === "running";
  const now = useNow(running && (current?.trace.open.size ?? 0) > 0);
  const lines = useMemo(() => {
    if (current === null) return [];
    const trace = current.trace;
    const out: Line[] = trace.log.map((e: LogEntry) => ({ key: `e${e.seq}`, ...e, since: null }));
    for (const rec of trace.open.values()) {
      out.push({ key: `o${rec.step}`, seq: rec.startSeq, t: rec.startT, level: "RUN", path: rec.path, message: "", since: rec.startT });
    }
    return out.sort((a, b) => b.seq - a.seq);
  }, [current]);
  if (current === null) return <div className={css.empty}>실행 기록이 없어요</div>;
  const trace = current.trace;
  const lookup = docLookup(docs);
  const typeTitle = typeTitleOf(types);
  const start = trace.startT;
  return (
    <div
      data-part="run-log"
      data-run-id={current.runId}
      data-applied={trace.lastSeq}
      data-steps-ended={trace.stepsEnded}
      data-phase={current.phase}
    >
      {lines.map((l) => (
        <div key={l.key} className={css.logLine} data-level={l.level}>
          <span className={css.logTime}>{formatClock(start === null ? 0 : l.t - start)}</span>
          <span className={`${css.logLevel} ${LEVEL_CLASS[l.level]}`}>{l.level}</span>
          <span className={css.logNode} title={l.path?.join(" › ")}>
            {l.path === null ? "" : stepLabel(trace.graph, l.path, current.calls, lookup, typeTitle)}
          </span>
          <span className={css.logMessage}>{l.since !== null ? `실행 중 ${runningText(l.since, now).slice(2)}` : l.message}</span>
        </div>
      ))}
    </div>
  );
}
