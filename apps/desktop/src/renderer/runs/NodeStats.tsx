// 노드별 통계 탭 (M3 계획 2.10, 시안 하위 탭 "노드별 통계"): 노드·횟수·성공/실패/오류·평균·p95·최대 (색인 stats,
// 끝난 스텝만). 행을 누르면 그 노드의 마지막 실패 스텝으로 간다 — 쪽을 다 읽지 않은 스텝이면 조상을 따라 올라가
// 펼친다 (runIndexStore.revealStep)
import { formatCount } from "../run/highlight";
import { formatMs, stepTitle, type TypeTitle } from "./labels";
import { runIndexModel, type RunIndex, type RunViewState } from "./runIndexStore";
import css from "./runs.module.css";

type NodeStat = RunIndex["stats"][number];

/** 실패·오류가 있는 노드 먼저, 그다음 경과 합이 큰 순 */
export function sortStats(stats: readonly NodeStat[]): NodeStat[] {
  return [...stats].sort((a, b) => {
    const bad = (s: NodeStat) => s.fail + s.error;
    return bad(b) - bad(a) || b.mean_ms * b.count - a.mean_ms * a.count || a.node.localeCompare(b.node);
  });
}

export function NodeStats({ view, typeTitle }: { view: RunViewState; typeTitle: TypeTitle }) {
  const stats = sortStats(view.index?.stats ?? []);
  if (stats.length === 0) return <div className={css.message}>끝난 스텝이 아직 없어요</div>;
  return (
    <div className={css.statsTab} data-part="node-stats">
      <table className={css.table}>
        <thead>
          <tr>
            <th>노드</th>
            <th>그래프</th>
            <th>횟수</th>
            <th>성공</th>
            <th>실패</th>
            <th>오류</th>
            <th>평균</th>
            <th>p95</th>
            <th>최대</th>
          </tr>
        </thead>
        <tbody>
          {stats.map((s) => {
            const target = s.last_failure_step;
            return (
              <tr
                key={`${s.graph}|${s.node}`}
                className={target !== null ? css.statsRowLink : undefined}
                data-part="stats-row"
                data-node={s.node}
                data-graph={s.graph}
                data-last-failure={target ?? ""}
                title={target !== null ? "마지막 실패 스텝으로 가기" : undefined}
                onClick={() => {
                  if (target !== null) void runIndexModel.revealStep(view.runId, target);
                }}
              >
                <td>{stepTitle(view, s, typeTitle)}</td>
                <td className={css.statsGraph}>{s.graph}</td>
                <td>{formatCount(s.count)}</td>
                <td>{formatCount(s.success)}</td>
                <td className={s.fail > 0 ? css.scoreTop : undefined}>{formatCount(s.fail)}</td>
                <td className={s.error > 0 ? css.scoreTop : undefined}>{formatCount(s.error)}</td>
                <td>{formatMs(s.mean_ms)}</td>
                <td>{formatMs(s.p95_ms)}</td>
                <td>{formatMs(s.max_ms)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
