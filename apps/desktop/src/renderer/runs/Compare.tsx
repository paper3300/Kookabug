// 지난 성공과 비교 (M3 계획 2.8·2.10, 시안 "<기준> (성공) 과 차이"). 결과는 daemon run.compare (코어 record/compare).
// - 비교 상자: 화면(차이 영역·비율)·그래프(같음·해시)·환경·시간 네 줄. 스텝 타임라인 아래(고른 스텝의 화면)와
//   비교 탭에 같은 것을 쓴다. 다른 줄과 다르면 경고 색
// - 비교 탭: 기준 실행 고르기(같은 테스트의 끝난 실행, 기본 = 자동: 같은 테스트·같은 프로필·pass·디버거 개입 아님
//   중 가장 최근), 두 화면 나란히(이 실행 증거에 차이 영역 상자), 바뀐 스냅샷 파일·환경 차이·노드별 평균 경과·늦어진
//   회차
import { useEffect, useRef, useState, type ReactNode } from "react";
import { client } from "../rpc/client";
import { fileUrl, fitted, type Size } from "./evidenceCells";
import { formatMs, stepTitle, type TypeTitle } from "./labels";
import { shortIdOf } from "./open";
import { compareKey, runIndexModel, type CompareResult, type RunViewState } from "./runIndexStore";
import { VERDICT_LABEL, toneOf, type RunSummary } from "./runListStore";
import css from "./runs.module.css";

type Screen = NonNullable<CompareResult["screen"]>;

const SCREEN_REASON: Record<NonNullable<Screen["reason"]>, string> = {
  policy_omitted: "정책으로 남기지 않음",
  no_thumbnail: "기준 실행에 썸네일 없음",
  no_evidence: "이 실행에 화면 증거 없음",
  no_matching_step: "기준 실행에 같은 노드 스텝 없음",
  image_unreadable: "이미지를 읽지 못함",
};

export interface CompareLine {
  key: "screen" | "graph" | "env" | "time";
  label: string;
  text: string;
  /** 기준과 다르다 (경고 색) */
  differs: boolean;
}

function short(v: unknown): string {
  if (v === null || v === undefined) return "없음";
  return typeof v === "string" ? v : JSON.stringify(v);
}

function observedText(run: Record<string, unknown> | null | undefined): string | null {
  const observed = run?.observed as { client_size?: unknown; dpi?: unknown } | undefined;
  if (!Array.isArray(observed?.client_size) || observed.client_size.length !== 2) return null;
  const dpi = typeof observed.dpi === "number" ? ` · DPI ${Math.round((observed.dpi / 96) * 100)}%` : "";
  return `${observed.client_size[0]}×${observed.client_size[1]}${dpi}`;
}

/** 비교 상자 네 줄 (시안 "화면 / 그래프 / 환경 / 시간") */
export function compareLines(
  result: CompareResult,
  baseId: string,
  title: (graph: string, node: string) => string,
  run: Record<string, unknown> | null | undefined,
): CompareLine[] {
  const lines: CompareLine[] = [];
  const screen = result.screen;
  if (screen === undefined) lines.push({ key: "screen", label: "화면", text: "비교할 스텝 없음", differs: false });
  else if (screen.reason !== undefined) lines.push({ key: "screen", label: "화면", text: SCREEN_REASON[screen.reason], differs: false });
  else if (screen.diff_ratio === undefined) lines.push({ key: "screen", label: "화면", text: "이 환경에서 계산할 수 없음", differs: false });
  else {
    const pct = `${Math.round(screen.diff_ratio * 100)}%`;
    const regions = screen.regions?.length ?? 0;
    lines.push({
      key: "screen",
      label: "화면",
      text: regions > 0 ? `#${baseId} 에 없던 영역 ${regions}곳 (화면 차이 ${pct})` : `같음 (화면 차이 ${pct})`,
      differs: regions > 0,
    });
  }
  const graph = result.graph;
  if (graph === undefined) lines.push({ key: "graph", label: "그래프", text: "스냅샷 없음 (예전 실행)", differs: false });
  else if (graph.same) lines.push({ key: "graph", label: "그래프", text: `같음 · ${graph.hash.slice(0, 6)}`, differs: false });
  else {
    lines.push({
      key: "graph",
      label: "그래프",
      text: `다름 · 파일 ${graph.changed.length}개 · ${graph.hash.slice(0, 6)} (기준 ${graph.baseline_hash.slice(0, 6)})`,
      differs: true,
    });
  }
  const env = result.env ?? [];
  if (env.length === 0) {
    const obs = observedText(run);
    lines.push({ key: "env", label: "환경", text: obs === null ? "같음" : `같음 · ${obs}`, differs: false });
  } else {
    const first = env[0];
    const more = env.length > 1 ? ` 외 ${env.length - 1}개` : "";
    lines.push({ key: "env", label: "환경", text: `${first.key} ${short(first.baseline)} → ${short(first.run)}${more}`, differs: true });
  }
  const time = result.time;
  const inflection = time?.inflections[0];
  if (inflection !== undefined) {
    const node = inflection.body_node ?? inflection.node;
    const before = inflection.body_before_ms ?? inflection.before_ms;
    const after = inflection.body_after_ms ?? inflection.after_ms;
    lines.push({
      key: "time",
      label: "시간",
      text: `${title(inflection.graph, node)} 평균 ${formatMs(before)} → ${formatMs(after)} (${(inflection.from_iteration + 1).toLocaleString("ko-KR")}회차~)`,
      differs: true,
    });
  } else {
    // 기준보다 1.5배 넘게(그리고 0.2초 넘게) 늦어진 노드 중 가장 많이 늦어진 것
    let worst: { text: string; ratio: number } | null = null;
    for (const n of time?.nodes ?? []) {
      if (n.mean_ms === null || n.baseline_mean_ms === null || n.baseline_mean_ms <= 0) continue;
      const ratio = n.mean_ms / n.baseline_mean_ms;
      if (ratio < 1.5 || n.mean_ms - n.baseline_mean_ms < 200) continue;
      if (worst === null || ratio > worst.ratio) {
        worst = { ratio, text: `${title(n.graph, n.node)} 평균 ${formatMs(n.baseline_mean_ms)} → ${formatMs(n.mean_ms)}` };
      }
    }
    lines.push({ key: "time", label: "시간", text: worst?.text ?? "비슷함", differs: worst !== null });
  }
  return lines;
}

/** 고른 스텝(없으면 실패 스텝)과의 비교를 읽는다. 실행이 끝나면 다시 */
function useCompare(view: RunViewState, step: string | null): RunViewState["compare"] {
  const state = view.index?.state;
  const baseline = view.baseline;
  const runId = view.runId;
  const seen = useRef(state);
  useEffect(() => {
    // 진행 중이던 실행이 끝나면 같은 열쇠도 다시 읽는다
    const ended = seen.current === "running" && state === "ended";
    seen.current = state;
    void runIndexModel.loadCompare(runId, step, ended);
  }, [runId, step, baseline, state]);
  const key = compareKey(view.baseline, step);
  return view.compare?.key === key ? view.compare : null;
}

function Lines({ lines }: { lines: CompareLine[] }) {
  return (
    <div className={css.kv}>
      {lines.map((l) => (
        <span key={l.key} style={{ display: "contents" }}>
          <span className={css.kvKey} data-differs={l.differs}>
            {l.label}
          </span>
          <span data-part={`compare-${l.key}`} data-differs={l.differs}>
            {l.text}
          </span>
        </span>
      ))}
    </div>
  );
}

function baseIdOf(result: CompareResult): string {
  return result.baseline === null ? "" : shortIdOf(result.baseline);
}

/** 비교 상자 (스텝 타임라인 아래, 시안 "<기준> (성공) 과 차이") */
export function CompareBox({ view, step, typeTitle }: { view: RunViewState; step: string | null; typeTitle: TypeTitle }) {
  const compare = useCompare(view, step);
  const title = (graph: string, node: string) => stepTitle(view, { graph, node }, typeTitle);
  const result = compare?.result;
  let body: ReactNode;
  let head = "지난 성공과 차이";
  if (result === undefined || result === "loading") body = <div className={css.boxNote}>비교하는 중…</div>;
  else if ("error" in result) body = <div className={css.boxNote}>비교하지 못했어요: {result.error}</div>;
  else if (result.baseline === null) body = <div className={css.boxNote}>{result.message ?? "비교할 성공 실행 없음"}</div>;
  else {
    head = `#${baseIdOf(result)} (${result.baseline_picked === "user" ? "고른 실행" : "성공"}) 과 차이`;
    body = <Lines lines={compareLines(result, baseIdOf(result), title, view.index?.run)} />;
  }
  return (
    <div className={css.box} data-part="compare-box" data-baseline={typeof result === "object" && !("error" in result) ? (result.baseline ?? "") : ""}>
      <div className={css.boxHead}>{head}</div>
      {body}
    </div>
  );
}

/** 하위 탭 이름: "#<기준> 과 비교" (기준을 모르면 "비교") */
export function compareTabLabel(view: RunViewState): string {
  const r = view.compare?.result;
  if (r === undefined || r === "loading" || "error" in r || r.baseline === null) return "비교";
  return `#${shortIdOf(r.baseline)} 과 비교`;
}

function BoxedImage({ src, boxes, label, part }: { src: string; boxes: readonly (readonly number[])[]; label: string; part: string }) {
  const [natural, setNatural] = useState<Size | null>(null);
  const [box, setBox] = useState<Size | null>(null);
  const inner = natural !== null && box !== null ? fitted(natural, box) : null;
  return (
    <div
      className={css.frame}
      ref={(el) => {
        if (el !== null && el.clientWidth > 0 && (box === null || box.w !== el.clientWidth || box.h !== el.clientHeight)) {
          setBox({ w: el.clientWidth, h: el.clientHeight });
        }
      }}
    >
      <img
        className={css.frameImg}
        src={src}
        alt={label}
        data-part={part}
        onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
      />
      {inner !== null && natural !== null && boxes.length > 0 && (
        <div className={css.frameInner} style={{ left: `${inner.left}%`, top: `${inner.top}%`, width: `${inner.width}%`, height: `${inner.height}%` }}>
          {boxes.map(([x, y, w, h], i) => (
            <div
              key={i}
              className={css.diffBox}
              data-part="diff-box"
              style={{
                left: `${(x / natural.w) * 100}%`,
                top: `${(y / natural.h) * 100}%`,
                width: `${(w / natural.w) * 100}%`,
                height: `${(h / natural.h) * 100}%`,
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function runFolderOf(runDir: string): string {
  const name = runDir.replaceAll("\\", "/").split("/").filter(Boolean).pop() ?? "";
  return `runs/${name}`;
}

/** 기준 고르기 목록 한 쪽 */
export const CANDIDATE_PAGE = 50;

interface Candidates {
  runs: RunSummary[] | null;
  /** 더 읽을 쪽이 있다 (run.list next) */
  more: boolean;
  loading: boolean;
  loadMore(): void;
}

/** 같은 테스트의 끝난 실행 (기준 고르기). 최근부터 한 쪽씩, "이전 실행 더 보기"로 다음 쪽 */
function useCandidates(view: RunViewState): Candidates {
  const graph = typeof view.index?.run?.graph === "string" ? view.index.run.graph : null;
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const epoch = useRef(0);
  const read = (before: string | null, reset: boolean) => {
    if (graph === null) return;
    const mine = ++epoch.current;
    setLoading(true);
    client()
      .call("run.list", { graph, limit: CANDIDATE_PAGE, ...(before === null ? {} : { before }) })
      .then((r) => {
        if (mine !== epoch.current) return;
        const page = r.runs.filter((x) => x.state === "ended" && x.run_id !== view.runId);
        setRuns((had) => (reset || had === null ? page : [...had, ...page.filter((p) => !had.some((h) => h.run_id === p.run_id))]));
        setNext(r.next ?? null);
      })
      .catch(() => {
        if (mine !== epoch.current) return;
        setRuns((had) => (reset ? [] : had));
        setNext(null);
      })
      .finally(() => {
        if (mine === epoch.current) setLoading(false);
      });
  };
  useEffect(() => {
    setRuns(null);
    setNext(null);
    read(null, true);
    return () => {
      epoch.current++;
    };
  }, [graph, view.runId]);
  return { runs, more: next !== null, loading, loadMore: () => next !== null && !loading && read(next, false) };
}

interface BaselineRun {
  runId: string;
  runDir: string;
  verdict: string | null;
  startedAt: string | null;
}

/**
 * 기준 실행의 폴더·결과 (run.status). 고르기 목록 쪽에 없어도(최근 50개 밖의 자동 기준) 그 화면을 그리고 목록에서
 * 다시 고를 수 있게 따로 읽는다
 */
function useBaselineRun(runId: string | null): BaselineRun | null {
  const [found, setFound] = useState<BaselineRun | null>(null);
  useEffect(() => {
    if (runId === null) return;
    let live = true;
    client()
      .call("run.status", { run_id: runId })
      .then((r) => {
        if (live) setFound({ runId, runDir: r.run_dir, verdict: r.outcome?.verdict ?? null, startedAt: r.started_at });
      })
      .catch(() => {
        if (live) setFound(null);
      });
    return () => {
      live = false;
    };
  }, [runId]);
  return found !== null && found.runId === runId ? found : null;
}

function stamp(at: string | null): string {
  if (at === null) return "";
  const d = new Date(at);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** 비교 탭 (전체 폭) */
export function CompareTab({ view, typeTitle }: { view: RunViewState; typeTitle: TypeTitle }) {
  const step = view.selected;
  const compare = useCompare(view, step);
  const candidates = useCandidates(view);
  const title = (graph: string, node: string) => stepTitle(view, { graph, node }, typeTitle);
  const result = compare?.result;
  const ready = result !== undefined && result !== "loading" && !("error" in result) ? result : null;
  const baseRun = useBaselineRun(ready?.baseline ?? view.baseline ?? null);
  const baseDir = ready?.baseline != null && baseRun?.runId === ready.baseline ? baseRun.runDir : null;
  const listed = candidates.runs ?? [];
  // 지금 기준(자동으로 고른 것·고른 것)이 읽은 쪽에 없으면 맨 위에 따로 둔다
  const extra = baseRun !== null && !listed.some((c) => c.run_id === baseRun.runId) ? baseRun : null;
  return (
    <div className={css.compareTab} data-part="compare-tab">
      <div className={css.pickRow}>
        <label className={css.pickRow}>
          기준 실행
          <select
            aria-label="기준 실행"
            className={css.select}
            data-part="baseline-select"
            value={view.baseline ?? ""}
            onChange={(e) => runIndexModel.setBaseline(view.runId, e.target.value === "" ? null : e.target.value)}
          >
            <option value="">자동 (지난 성공)</option>
            {extra !== null && (
              <option value={extra.runId} data-part="baseline-current">
                #{shortIdOf(extra.runId)} · {extra.verdict === null ? "" : `${VERDICT_LABEL[extra.verdict as keyof typeof VERDICT_LABEL] ?? extra.verdict} · `}
                {stamp(extra.startedAt)}
              </option>
            )}
            {listed.map((c) => (
              <option key={c.run_id} value={c.run_id}>
                #{shortIdOf(c.run_id)} · {VERDICT_LABEL[toneOf(c)]} · {stamp(c.started_at)}
                {c.debug_intervened === true ? " · 디버거 개입" : ""}
              </option>
            ))}
          </select>
        </label>
        {candidates.more && (
          <button
            type="button"
            className={css.button}
            style={{ marginLeft: 0 }}
            data-part="baseline-more"
            disabled={candidates.loading}
            onClick={candidates.loadMore}
          >
            이전 실행 더 보기
          </button>
        )}
      </div>
      <div className={css.tables} style={{ padding: 0 }}>
        <CompareBox view={view} step={step} typeTitle={typeTitle} />
      </div>
      {ready !== null && ready.baseline !== null && (
        <>
          {ready.screen !== undefined && (ready.screen.file !== null || ready.screen.baseline_file !== null) && (
            <div className={css.compareShots} data-part="compare-screen">
              <div className={css.shot}>
                <div className={css.shotHead}>
                  <span className={css.shotLabel}>이 실행</span>
                  <span className={css.shotTime}>{ready.screen.file ?? ""}</span>
                </div>
                {ready.screen.file !== null ? (
                  <BoxedImage
                    src={fileUrl(view.index!.run_dir, ready.screen.file)}
                    boxes={ready.screen.regions ?? []}
                    label="이 실행 화면"
                    part="compare-image"
                  />
                ) : (
                  <div className={css.omit}>화면 없음</div>
                )}
              </div>
              <div className={css.shot}>
                <div className={css.shotHead}>
                  <span className={css.shotLabel}>#{baseIdOf(ready)}</span>
                  <span className={css.shotTime}>{ready.screen.baseline_file ?? ""}</span>
                </div>
                {ready.screen.baseline_file !== null && baseDir !== null ? (
                  <BoxedImage src={fileUrl(runFolderOf(baseDir), ready.screen.baseline_file)} boxes={[]} label="기준 실행 화면" part="baseline-image" />
                ) : (
                  <div className={css.omit}>{ready.screen.reason !== undefined ? SCREEN_REASON[ready.screen.reason] : "화면 없음"}</div>
                )}
              </div>
            </div>
          )}
          <div className={css.tables}>
            {ready.graph !== undefined && !ready.graph.same && (
              <div className={css.box} data-part="compare-graph-files">
                <div className={css.boxHead}>바뀐 스냅샷 파일</div>
                <table className={css.table}>
                  <tbody>
                    {ready.graph.changed.map((c) => (
                      <tr key={c.path}>
                        <td>{c.change === "added" ? "추가" : c.change === "removed" ? "삭제" : "변경"}</td>
                        <td>{c.path}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(ready.env ?? []).length > 0 && (
              <div className={css.box} data-part="compare-env-table">
                <div className={css.boxHead}>환경 차이</div>
                <table className={css.table}>
                  <thead>
                    <tr>
                      <th>항목</th>
                      <th>기준</th>
                      <th>이 실행</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(ready.env ?? []).map((e) => (
                      <tr key={e.key}>
                        <td>{e.key}</td>
                        <td>{short(e.baseline)}</td>
                        <td>{short(e.run)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {ready.time !== undefined && ready.time.nodes.length > 0 && (
              <div className={css.box} data-part="compare-time-table">
                <div className={css.boxHead}>노드별 평균 경과</div>
                <div style={{ overflowX: "auto" }}>
                  <table className={css.table}>
                    <thead>
                      <tr>
                        <th>노드</th>
                        <th>횟수</th>
                        <th>기준</th>
                        <th>이 실행</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ready.time.nodes.map((n) => (
                        <tr key={`${n.graph}|${n.node}`}>
                          <td>{title(n.graph, n.node)}</td>
                          <td>
                            {n.baseline_count} → {n.count}
                          </td>
                          <td>{n.baseline_mean_ms === null ? "—" : formatMs(n.baseline_mean_ms)}</td>
                          <td>{n.mean_ms === null ? "—" : formatMs(n.mean_ms)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
