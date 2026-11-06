// 상태 바 (M2 계획 2.8 "상태 바"): 대기 중이면 무채색, 실행 중이면 파랑(시안 Main "▶ 실행 중")이고 회차·경과
// 시간을 쓴다. 디버거로 멈췄으면 파랑 그대로 "⏸ 멈춤 · <노드>"(M3 U2). 입력 임대권 소유자("입력: 실행 #…"), 연결 상태와 실행 환경(캡처·OCR·Python·플러그인 수).
// 녹화(빨강)·Agent(보라) 상태는 해당 단계에서 붙인다
import { pendingCount, useAgent } from "../agent/agentStore";
import { pausedTitle } from "../debug/PauseBanner";
import { statusBarItems, statusBarRecording } from "../recorder/labels";
import { elapsedNow, useRecorder } from "../recorder/recorderStore";
import { formatCount, formatElapsed, loopProgress } from "../run/highlight";
import { useRun, type LeaseOwner } from "../run/runStore";
import { openRun } from "../runs/open";
import { useRunIndex } from "../runs/runIndexStore";
import { retentionText, useRunList, videoPolicyText } from "../runs/runListStore";
import { useTabs } from "../store/tabs";
import { openAgentPanel } from "../store/ui";
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

export function leaseText(owner: LeaseOwner): string {
  if (owner.kind === "recorder") return "입력: 녹화";
  if (typeof owner.run_id === "string") return `입력: 실행 #${owner.run_id}`;
  return `입력: ${typeof owner.kind === "string" ? owner.kind : "사용 중"}`;
}

/** 녹화 항목 (시안 Recorder 상태 바, M4 T9). 녹화 중이면 맨 앞에 흰 점 */
function useRecorderStatus(): { recording: boolean; items: { left: string[]; right: string[] } | null } {
  const state = useRecorder((s) => s.state);
  const stateAt = useRecorder((s) => s.stateAt);
  const now = useNow(state?.state === "recording", 500);
  if (state === null) return { recording: false, items: null };
  return { recording: statusBarRecording(state), items: statusBarItems(state, elapsedNow({ state, stateAt }, now)) };
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

/** 기록 뷰어(RUN 탭)를 보고 있으면 보관 정책·runs/ 용량 (M3 계획 2.10 "상태 바(뷰어)") */
function Retention() {
  const viewer = useTabs((s) => s.tabs.some((t) => t.path === s.active && t.kind === "run"));
  const retention = useWorkspace((s) => s.info?.retention);
  const bytes = useRunList((s) => s.runsBytes);
  const text = viewer ? retentionText(retention, bytes) : null;
  if (text === null) return null;
  return (
    <span className={css.statusItem} data-part="retention" title="실행 기록 보관 정책 (kookabug.json retention)">
      {text}
    </span>
  );
}

/** 기록 뷰어(RUN 탭)를 보고 있으면 그 실행의 실효 영상 정책과 출처 (M4 T12) */
function VideoPolicy() {
  const runId = useTabs((s) => s.tabs.find((t) => t.path === s.active && t.kind === "run")?.runId ?? null);
  const policy = useRunIndex((s) => (runId === null ? undefined : s.runs.get(runId)?.index?.video_policy));
  const text = videoPolicyText(policy);
  if (text === null) return null;
  return (
    <span
      className={css.statusItem}
      data-part="video-policy"
      data-mode={policy?.mode ?? ""}
      title="이 실행의 영상 정책 (위 층이 아래 층을 이긴다: kookabug.json → 테스트 → 서브그래프 → 노드)"
    >
      {text}
    </span>
  );
}

/** "에이전트 N" (U6: MCP는 stdio라 포트가 없다 — 붙은 agent 연결 수). 누르면 에이전트 패널 */
function Agents() {
  const connections = useAgent((s) => s.connections);
  const waiting = useAgent(pendingCount);
  const title =
    connections.length === 0
      ? "붙은 에이전트가 없어요"
      : connections.map((c) => `${c.name || "mcp"} · ${c.id}${c.attended ? "" : " (사람 없음)"}`).join(" / ");
  return (
    <button type="button" className={`${css.statusItem} ${css.statusLink}`} data-part="status-agents" title={title} onClick={openAgentPanel}>
      에이전트 {connections.length}
      {waiting > 0 && <span data-part="status-pending"> · 승인 대기 {waiting}</span>}
    </button>
  );
}

export function StatusBar() {
  const daemon = useWorkspace((s) => s.daemon);
  const info = useWorkspace((s) => s.info);
  const running = useRun((s) => s.current?.phase === "running");
  const lease = useRun((s) => s.lease);
  const rec = useRecorderStatus();
  const [label, tone] = CONNECTION[daemon.status];
  const runtime = info?.runtime;
  const capture = runtime ? `캡처 ${runtime.capture ? runtime.capture.toUpperCase() : "없음"}` : null;
  const ocr = runtime ? `OCR ${runtime.ocr ? "사용 가능" : "없음"}` : null;
  return (
    <footer
      aria-label="상태 바"
      className={`${css.statusbar} ${rec.recording ? css.statusbarRecording : running ? css.statusbarRunning : ""}`}
      data-part="statusbar"
      data-running={running}
      data-recording={rec.recording}
    >
      {rec.items?.left.map((text, i) => (
        <span key={i} className={css.statusItem} data-part={i === 0 ? "rec-status" : "rec-status-item"}>
          {i === 0 && rec.recording && <DotIcon />}
          {text}
        </span>
      ))}
      {running && !rec.recording && <RunState />}
      {/* 녹화 중에는 시안처럼 녹화 항목만 (연결 표시는 숨기되 data-status는 남긴다 — 검사가 연결 상태를 본다) */}
      <span
        className={css.statusItem}
        data-status={daemon.status}
        title={daemon.message}
        style={rec.recording ? { display: "none" } : undefined}
      >
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
      {rec.items?.right.map((text) => (
        <span key={text} className={css.statusItem} data-part="rec-status-right">
          {text}
        </span>
      ))}
      <VideoPolicy />
      <Retention />
      {runtime && !rec.recording && (
        <>
          <span className={css.statusItem} title={runtime.ocr ?? undefined}>
            {capture} · {ocr}
          </span>
          <span className={css.statusItem}>Python {pythonVersion(runtime.python)}</span>
          <span className={css.statusItem}>플러그인 {info?.plugins.length ?? 0}</span>
        </>
      )}
      {daemon.status === "connected" && !rec.recording && <Agents />}
    </footer>
  );
}
