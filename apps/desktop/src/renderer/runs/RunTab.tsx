// 기록 뷰어 RUN 탭 (시안 RunViewer 에디터 영역, M3 계획 2.10).
// - 머리: `#<id> <테스트>` · 결과·사유 · 시작 시각 · 경과(멈춘 시간이 있으면 "실제 a · 멈춤 제외 b") · 반복 · 스냅샷
//   경로 · 해상도·DPI. "에디터에서 재현"·"분석 번들 내보내기"는 T11, "에이전트에게 분석 요청"은 M5(숨김)
// - 하위 탭: 스텝 타임라인 · run.json. 노드별 통계·비교는 T11, "수집 데이터"는 숨김(U11)
// - 처음 열면 실패 노드로 바로 이동한다(실패 사슬을 펼치고 실패 스텝을 고른 뒤 보이게 하고 그 증거를 보인다)
// - 진행 중 실행은 실행 화면이 받은 이벤트를 따라 늘어난다 (runIndexStore, live.ts)
import { useEffect } from "react";
import { formatCount } from "../run/highlight";
import { useRegistry } from "../store/registry";
import { renameTab, runTabPath } from "../store/tabs";
import { Evidence } from "./Evidence";
import { isoMs, stepTitle, type TypeTitle } from "./labels";
import { runTabTitle, shortIdOf } from "./open";
import { findStep, runIndexModel, useRunIndex, type RunIndex, type RunViewState } from "./runIndexStore";
import { formatDuration } from "./runListStore";
import css from "./runs.module.css";
import { Timeline } from "./Timeline";

const VERDICT = { pass: "성공", fail: "실패", error: "오류", skipped: "건너뜀" } as const;

const EXIT_TEXT: Record<string, string> = { timeout: "시간 초과" };

/**
 * 결과 칸 (시안 "실패 · 시간 초과"): 판정 · 실패 스텝 제목과 출구. 실패 스텝이 없으면 사유. 긴 사유 전체는
 * 마우스를 올리면 보인다
 */
function verdictOf(view: RunViewState, typeTitle: TypeTitle): { tone: string; text: string; reason: string | null } {
  const index = view.index!;
  if (index.state === "running") return { tone: "running", text: "실행 중", reason: null };
  const run = index.run ?? {};
  const verdict = typeof run.verdict === "string" ? run.verdict : null;
  const label = verdict === null ? "끝남" : (VERDICT[verdict as keyof typeof VERDICT] ?? verdict);
  const reason = typeof run.reason === "string" && run.reason !== "" && verdict !== "pass" ? run.reason : null;
  const failureId = index.failure_chain[index.failure_chain.length - 1];
  const failure = failureId === undefined ? null : findStep(view, failureId);
  if (failure !== null) {
    const exit = failure.exit === null ? (failure.status === "error" ? "오류" : "") : (EXIT_TEXT[failure.exit] ?? failure.exit);
    return { tone: verdict ?? "error", text: `${label} · ${stepTitle(view, failure, typeTitle)}${exit === "" ? "" : ` ${exit}`}`, reason };
  }
  const short = reason !== null && reason.length > 40 ? `${reason.slice(0, 40)}…` : reason;
  return { tone: verdict ?? "error", text: short === null ? label : `${label} · ${short}`, reason };
}

function stamp(ms: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 머리 메타 줄 (시안 "10-28 23:04 · 2시간 41분 · 2,981 / 10,000회 · 스냅샷 runs/128/snapshot · 1280×720") */
export function headMeta(index: RunIndex): string[] {
  const run = index.run ?? {};
  const parts: string[] = [];
  const started = isoMs(typeof run.started_at === "string" ? run.started_at : null) ?? isoMs(index.steps[0]?.t_start);
  if (started !== null) parts.push(stamp(started));
  const ended = isoMs(typeof run.ended_at === "string" ? run.ended_at : null);
  const wall = started !== null && ended !== null ? ended - started : null;
  const active = typeof run.active_duration_ms === "number" ? run.active_duration_ms : null;
  const paused = typeof run.paused_ms === "number" ? run.paused_ms : 0;
  if (wall !== null) {
    parts.push(paused > 0 && active !== null ? `실제 ${formatDuration(wall)} · 멈춤 제외 ${formatDuration(active)}` : formatDuration(wall));
  }
  const loop = index.steps.find((s) => s.parent === null && s.iterations !== undefined);
  if (loop?.iterations !== undefined) parts.push(`반복 ${formatCount(loop.iterations.length)}회`);
  parts.push(`스냅샷 ${index.run_dir}/snapshot`);
  const observed = run.observed as { client_size?: unknown; dpi?: unknown } | undefined;
  if (Array.isArray(observed?.client_size) && observed.client_size.length === 2) {
    const dpi = typeof observed.dpi === "number" ? ` · DPI ${Math.round((observed.dpi / 96) * 100)}%` : "";
    parts.push(`${observed.client_size[0]}×${observed.client_size[1]}${dpi}`);
  }
  if (typeof run.game_build === "string" && run.game_build !== "") parts.push(`build=${run.game_build}`);
  return parts;
}

function Head({ view, shortId, typeTitle }: { view: RunViewState; shortId: string; typeTitle: TypeTitle }) {
  const index = view.index!;
  const verdict = verdictOf(view, typeTitle);
  const title = view.testTitle ?? (typeof index.run?.graph === "string" ? index.run.graph : index.run_id);
  return (
    <div className={css.head} data-part="run-head">
      <div className={css.headText}>
        <div className={css.headTitle}>
          <h1 className={css.h1}>
            #{shortId} {title}
          </h1>
          <span className={css.verdict} data-tone={verdict.tone} data-part="run-verdict" title={verdict.reason ?? undefined}>
            {verdict.text}
          </span>
        </div>
        <div className={css.headMeta} data-part="run-meta">
          {headMeta(index).join(" · ")}
        </div>
      </div>
    </div>
  );
}

function RunJson({ view }: { view: RunViewState }) {
  const r = view.runJson;
  if (r === null || r === "loading") return <div className={css.message}>읽는 중…</div>;
  if (r === "error") return <div className={css.message}>run.json을 읽지 못했어요 (아직 없을 수 있어요)</div>;
  return (
    <pre className={css.pre} data-part="run-json">
      {r.text}
      {r.truncated ? "\n…" : ""}
    </pre>
  );
}

export function RunTab({ runId }: { runId: string }) {
  const view = useRunIndex((s) => s.runs.get(runId));
  const types = useRegistry((s) => s.types);
  useEffect(() => {
    void runIndexModel.open(runId);
  }, [runId]);
  const testTitle = view?.testTitle ?? null;
  useEffect(() => {
    if (testTitle !== null) renameTab(runTabPath(runId), runTabTitle(runId, testTitle));
  }, [runId, testTitle]);
  const shortId = shortIdOf(runId);
  const typeTitle = (type: string) => types.get(type)?.title ?? null;
  if (view === undefined || (view.status === "loading" && view.index === null)) {
    return (
      <div className={css.tab} data-part="run-tab" data-run-id={runId} data-status="loading">
        <div className={css.message}>실행 기록을 읽는 중…</div>
      </div>
    );
  }
  if (view.index === null) {
    return (
      <div className={css.tab} data-part="run-tab" data-run-id={runId} data-status="error">
        <div className={css.message} role="alert">
          실행 기록을 읽지 못했어요{view.error !== null ? `: ${view.error}` : ""}
        </div>
      </div>
    );
  }
  const selected = view.selected === null ? null : findStep(view, view.selected);
  return (
    <div
      className={css.tab}
      data-part="run-tab"
      data-run-id={runId}
      data-status="ready"
      data-state={view.index.state}
      data-jumped={view.jumped}
      data-selected={view.selected ?? ""}
      data-last-seq={view.index.last_seq}
    >
      <Head view={view} shortId={shortId} typeTitle={typeTitle} />
      <div role="tablist" aria-label="기록 보기" className={css.subtabs}>
        <button
          type="button"
          role="tab"
          aria-selected={view.view === "timeline"}
          className={css.subtab}
          onClick={() => runIndexModel.setView(runId, "timeline")}
        >
          스텝 타임라인
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view.view === "runjson"}
          className={css.subtab}
          onClick={() => runIndexModel.setView(runId, "runjson")}
        >
          run.json
        </button>
      </div>
      <div className={css.body}>
        {view.view === "runjson" ? (
          <RunJson view={view} />
        ) : (
          <>
            <Timeline view={view} typeTitle={typeTitle} />
            {selected !== null ? (
              <Evidence view={view} step={selected} shortId={shortId} typeTitle={typeTitle} />
            ) : (
              <div className={css.message}>스텝을 고르면 화면과 매칭 후보가 보여요</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
