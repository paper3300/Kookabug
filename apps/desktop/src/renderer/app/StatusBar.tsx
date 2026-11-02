// 상태 바 (M2 계획 2.8 "상태 바"): 대기 중이면 무채색, 실행 중이면 파랑(시안 Main "▶ 실행 중")이고 회차·경과
// 시간을 쓴다. 디버거로 멈췄으면 파랑 그대로 "⏸ 멈춤 · <노드>"(M3 U2). 입력 임대권 소유자("입력: 실행 #…"), 연결 상태와 실행 환경(캡처·OCR·Python·플러그인 수).
// 녹화(빨강)·Agent(보라) 상태는 해당 단계에서 붙인다
import { pausedTitle } from "../debug/PauseBanner";
import { formatCount, formatElapsed, loopProgress } from "../run/highlight";
import { useRun, type LeaseOwner } from "../run/runStore";
import { openRun } from "../runs/open";
import { docLookup, loopLimitOf, useNow } from "../run/view";
import { useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { useWorkspace } from "../store/workspace";
import { DotIcon, LockIcon, PlayIcon } from "../theme/icons";
import css from "./shell.module.css";

const CONNECTION = {
  idle: ["연결 없음", css.statusWarn],
  connecting: ["연결 중…", css.statusWarn],
  connected: ["daemon 연결됨", css.statusOk],
  disconnected: ["연결 끊김", css.statusWarn],
  mismatch: ["판 다름", css.statusError],
  error: ["daemon 오류", css.statusError],
} as const;

const VERDICT = { pass: "통과", fail: "실패", error: "오류", skipped: "건너뜀" } as const;

function pythonVersion(v: string): string {
  return v.split(".").slice(0, 2).join(".");
}

function leaseText(owner: LeaseOwner): string {
  if (typeof owner.run_id === "string") return `입력: 실행 #${owner.run_id}`;
  return `입력: ${typeof owner.kind === "string" ? owner.kind : "사용 중"}`;
}

function RunItems() {
  const current = useRun((s) => s.current);
  const docs = useDocuments((s) => s.docs);
  const types = useRegistry((s) => s.types);
  const running = current?.phase === "running";
  const now = useNow(running, 500);
  if (current === null) return null;
  const trace = current.trace;
  if (!running) {
    const verdict = current.outcome?.verdict ?? trace.end?.verdict ?? null;
    const label = verdict === null ? "끝남" : (VERDICT[verdict as keyof typeof VERDICT] ?? verdict);
    const ms = trace.end?.durationMs ?? null;
    const failed = verdict === "fail" || verdict === "error";
    return (
      <span className={css.statusItem} data-part="run-result" data-verdict={verdict ?? ""}>
        마지막 실행 {label}
        {ms !== null ? ` · ${formatElapsed(ms)}` : ""}
        {/* 기록 뷰어로 실패 노드까지 한 번에 (M3 완료 기준 1) */}
        {failed && (
          <button
            type="button"
            className={css.statusLink}
            data-part="status-show-failure"
            onClick={() => openRun(current.runId, current.graph)}
          >
            실패 보기
          </button>
        )}
      </span>
    );
  }
  const loop = loopProgress(trace, current.calls, docLookup(docs), loopLimitOf(types));
  const elapsed = formatElapsed(trace.startT === null ? 0 : now - trace.startT);
  return (
    <span className={css.statusItem} data-part="run-progress">
      {loop !== null ? `반복 ${formatCount(loop.count)} / ${loop.limit === null ? "?" : formatCount(loop.limit)} · ${elapsed}` : `경과 ${elapsed}`}
    </span>
  );
}

/** 실행 중 표시. 멈췄으면 파랑 그대로 "⏸ 멈춤 · <노드 제목>" (M3 U2) */
function RunState() {
  const paused = useRun((s) => (s.current?.phase === "running" ? s.current.pause.paused : null));
  const docs = useDocuments((s) => s.docs);
  const types = useRegistry((s) => s.types);
  if (paused !== null) {
    return (
      <span className={`${css.statusItem} ${css.statusRunning}`} data-part="run-state" data-paused="true">
        ⏸ 멈춤 · {pausedTitle(paused, docs, types)}
      </span>
    );
  }
  return (
    <span className={`${css.statusItem} ${css.statusRunning}`} data-part="run-state" data-paused="false">
      <PlayIcon width={10} height={10} />
      실행 중
    </span>
  );
}

export function StatusBar() {
  const daemon = useWorkspace((s) => s.daemon);
  const info = useWorkspace((s) => s.info);
  const running = useRun((s) => s.current?.phase === "running");
  const lease = useRun((s) => s.lease);
  const [label, tone] = CONNECTION[daemon.status];
  const runtime = info?.runtime;
  const capture = runtime ? `캡처 ${runtime.capture ? runtime.capture.toUpperCase() : "없음"}` : null;
  const ocr = runtime ? `OCR ${runtime.ocr ? "사용 가능" : "없음"}` : null;
  return (
    <footer
      aria-label="상태 바"
      className={`${css.statusbar} ${running ? css.statusbarRunning : ""}`}
      data-part="statusbar"
      data-running={running}
    >
      {running && <RunState />}
      <span className={css.statusItem} data-status={daemon.status} title={daemon.message}>
        <DotIcon className={running ? undefined : tone} />
        {label}
      </span>
      <RunItems />
      {lease !== null && (
        <span className={css.statusItem} data-part="lease" title="입력 임대권: 이 PC의 입력은 한 번에 하나만 보낸다">
          <LockIcon />
          {leaseText(lease)}
        </span>
      )}
      <div className={css.spacer} />
      {runtime && (
        <>
          <span className={css.statusItem} title={runtime.ocr ?? undefined}>
            {capture} · {ocr}
          </span>
          <span className={css.statusItem}>Python {pythonVersion(runtime.python)}</span>
          <span className={css.statusItem}>플러그인 {info?.plugins.length ?? 0}</span>
        </>
      )}
    </footer>
  );
}
