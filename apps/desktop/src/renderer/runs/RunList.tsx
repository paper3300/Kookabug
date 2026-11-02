// 사이드바 "실행 기록" (시안 RunViewer 왼쪽): 날짜 묶음 · 결과 색 점 · `#<id> <테스트>` · 배지 · 메타. 누르면 RUN
// 탭을 열고 실패 노드로 바로 간다. 끝까지 내리면 다음 쪽. 검색 칸·필터 단추는 시안에 있지만 run.list 거르기를 붙일
// 때까지 숨긴다
import { useEffect, useMemo } from "react";
import { ChevronDownIcon } from "../theme/icons";
import { useTabs } from "../store/tabs";
import { openRun } from "./open";
import { badgesOf, groupRuns, metaOf, runListModel, shortIds, testName, toneOf, useRunList } from "./runListStore";
import css from "./runs.module.css";

export function RunList() {
  const runs = useRunList((s) => s.runs);
  const next = useRunList((s) => s.next);
  const loading = useRunList((s) => s.loading);
  const error = useRunList((s) => s.error);
  const activeRun = useTabs((s) => s.tabs.find((t) => t.path === s.active && t.kind === "run")?.runId ?? null);
  useEffect(() => {
    void runListModel.reload();
  }, []);
  const ids = useMemo(() => shortIds(runs.map((r) => r.run_id)), [runs]);
  const groups = groupRuns(runs, new Date());
  return (
    <div
      className={css.list}
      data-part="run-list"
      data-count={runs.length}
      onScroll={(e) => {
        const el = e.currentTarget;
        if (el.scrollTop + el.clientHeight >= el.scrollHeight - 24) void runListModel.more();
      }}
    >
      {groups.map((g) => (
        <section key={g.name} aria-label={g.name}>
          <div className={css.group}>
            <ChevronDownIcon />
            {g.name}
          </div>
          {g.runs.map((r) => {
            const tone = toneOf(r);
            return (
              <button
                key={r.run_id}
                type="button"
                className={css.run}
                aria-current={r.run_id === activeRun}
                data-part="run-item"
                data-run-id={r.run_id}
                data-tone={tone}
                onClick={() => openRun(r.run_id, r.graph)}
              >
                <span className={css.dot} data-tone={tone} />
                <span className={css.runText}>
                  <span className={css.runTitle}>
                    <span className={css.runName}>
                      #{ids.get(r.run_id)} {testName(r)}
                    </span>
                    {badgesOf(r).map((b) => (
                      <span key={b.kind} className={css.badge} data-kind={b.kind} data-part="run-badge">
                        {b.text}
                      </span>
                    ))}
                  </span>
                  <span className={css.runMeta}>{metaOf(r)}</span>
                </span>
              </button>
            );
          })}
        </section>
      ))}
      {runs.length === 0 && !loading && <div className={css.listNote}>아직 실행 기록이 없어요</div>}
      {error !== null && <div className={css.listNote}>목록을 읽지 못했어요: {error}</div>}
      {next !== null && (
        <button type="button" className={css.more} disabled={loading} onClick={() => void runListModel.more()}>
          더 보기
        </button>
      )}
    </div>
  );
}
