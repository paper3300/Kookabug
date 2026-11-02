// 반복 회차 막대 (시안 "회차별 소요 시간"): 회차마다 막대 하나, 높이 = 경과. 앞 절반 중앙값보다 2배 넘게 늦은
// 회차는 주황, 실패한 회차·고른 회차는 진한 주황. 회차가 많으면 묶어서 그린다(묶음의 가장 긴 경과, 누르면 묶음의
// 마지막 회차). 막대를 누르면 그 회차 스텝을 연다 (run.children iteration)
import { formatCount } from "../run/highlight";
import { formatMs, isoMs } from "./labels";
import type { StepNode } from "./runIndexStore";
import css from "./runs.module.css";

type Iteration = NonNullable<StepNode["iterations"]>[number];

/** 한 줄에 그리는 막대 수 상한 */
export const MAX_BARS = 240;

export interface Bar {
  /** 누르면 열 회차 */
  iteration: number;
  first: number;
  durationMs: number | null;
  height: number;
  late: boolean;
  failed: boolean;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const s = [...values].sort((a, b) => a - b);
  const m = Math.floor(s.length / 2);
  return s.length % 2 === 1 ? s[m] : (s[m - 1] + s[m]) / 2;
}

export function barsOf(iterations: readonly Iteration[], max = MAX_BARS): Bar[] {
  const done = iterations.map((i) => i.duration_ms ?? null);
  const firstHalf = done.slice(0, Math.max(1, Math.floor(done.length / 2))).filter((d): d is number => d !== null);
  const base = median(firstHalf);
  const size = Math.max(1, Math.ceil(iterations.length / max));
  const groups: Iteration[][] = [];
  for (let i = 0; i < iterations.length; i += size) groups.push(iterations.slice(i, i + size));
  const longest = Math.max(1, ...done.filter((d): d is number => d !== null));
  return groups.map((g) => {
    const durations = g.map((i) => i.duration_ms).filter((d): d is number => d !== null && d !== undefined);
    const d = durations.length === 0 ? null : Math.max(...durations);
    return {
      iteration: g[g.length - 1].iteration,
      first: g[0].iteration,
      durationMs: d,
      height: d === null ? 100 : Math.max(8, Math.round((d / longest) * 100)),
      late: base !== null && base > 0 && d !== null && d > 2 * base,
      failed: g.some((i) => i.status === "fail" || i.status === "error"),
    };
  });
}

export function IterationBars({
  loop,
  selected,
  onPick,
}: {
  loop: StepNode;
  selected: number | null;
  onPick(iteration: number): void;
}) {
  const iterations = loop.iterations ?? [];
  const bars = barsOf(iterations);
  const current = iterations.find((i) => i.iteration === selected) ?? iterations[iterations.length - 1];
  const start = isoMs(current?.t_start);
  const end = start !== null && current?.duration_ms != null ? start + current.duration_ms : null;
  const clock = (ms: number) => new Date(ms).toLocaleTimeString("ko-KR", { hour12: false });
  return (
    <div className={css.iterations} data-part="iterations" data-loop={loop.step}>
      {current !== undefined && (
        <div className={css.iterHead}>
          <span>
            {formatCount(current.iteration + 1)}회차 · 스텝 {formatCount(current.steps)}개
          </span>
          <span>{start === null ? "" : `${clock(start)} — ${end === null ? "진행 중" : clock(end)}`}</span>
        </div>
      )}
      <div className={css.bars} role="group" aria-label="회차별 소요 시간">
        {bars.map((b) => (
          <button
            key={b.iteration}
            type="button"
            className={css.bar}
            style={{ height: `${b.height}%` }}
            data-part="iteration-bar"
            data-iteration={b.iteration}
            data-late={b.late}
            data-failed={b.failed}
            aria-pressed={selected !== null && selected >= b.first && selected <= b.iteration}
            aria-label={`${b.first === b.iteration ? `${b.iteration + 1}회차` : `${b.first + 1}~${b.iteration + 1}회차`} ${formatMs(b.durationMs)}`}
            title={`${b.first === b.iteration ? `${b.iteration + 1}회차` : `${b.first + 1}~${b.iteration + 1}회차`} · ${formatMs(b.durationMs) || "진행 중"}`}
            onClick={() => onPick(b.iteration)}
          />
        ))}
      </div>
      <div className={css.iterNote}>회차별 소요 시간 · {formatCount(iterations.length)}회</div>
    </div>
  );
}
