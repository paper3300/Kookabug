// 영상 보기 (M3 계획 2.10 "영상", 사용자 결정 U8 — 시안에 없음): 스크린샷 줄 머리 "스크린샷 | 영상"에서 영상을 고르면
// 고른 스텝 시작 시각으로 옮겨 보인다. 조각은 kbimg://ws/<실행 폴더>/video/seg-NNNN.mp4 (Range 206, 2.7).
// - 시각 대응은 5 fps 격자 (videoTimeline.ts): 재생 위치 = 칸 × 200 ms
// - 조각이 끝나면 다음 조각을 이어 재생한다. 사이에 빈 구간이 있으면 그 이유를 잠깐 띄운 뒤 넘어간다
// - 스텝 시각이 빈 구간이면 영상 대신 이유(기록 끔·비밀값·멈춤·창 없음·중단·지원 안 됨)와 "다음 영상부터"를 보인다
// - 재생하지 못하면(이 PC의 디코더 없음 등) "이 PC에서 재생할 수 없음" — 다른 화면은 그대로 (검수 M9)
// 아래 띠는 실행 시각 위의 조각(파랑)·빈 구간(회색, 이유는 마우스를 올리면)이고 누르면 그 조각 처음부터 재생한다
import { useEffect, useMemo, useRef, useState } from "react";
import { formatClock } from "../run/highlight";
import { fileUrl } from "./evidenceCells";
import { isoMs } from "./labels";
import type { StepNode } from "./runIndexStore";
import css from "./runs.module.css";
import { gapText, locate, nextAfter, runTimeAt, seekSeconds, segmentChain, type VideoSpot, type VideoView } from "./videoTimeline";

/** 조각 사이 빈 구간 이유를 보이는 시간 */
export const GAP_NOTICE_MS = 1200;

type GapSpot = Extract<VideoSpot, { kind: "gap" }>;

export function VideoPlayer({ runDir, runStart, step, video }: { runDir: string; runStart: number | null; step: StepNode; video: VideoView }) {
  const chain = useMemo(() => segmentChain(video), [video]);
  const target = isoMs(step.t_start);
  const [cur, setCur] = useState<number | null>(null);
  const [gap, setGap] = useState<GapSpot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState<number | null>(null);
  const [seekTarget, setSeekTarget] = useState<number | null>(null);
  const ref = useRef<HTMLVideoElement>(null);
  const pending = useRef<{ seconds: number; play: boolean } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * 멈춘 채 옮겼다: Chromium은 마지막 칸(마지막 프레임 시각 이후)으로 옮기기만 해도 ended를 낸다. 재생하지 않았으면
   * 다음 조각으로 넘어가지 않는다 (재생을 시작하면 풀린다)
   */
  const held = useRef(false);

  const clearTimer = () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
  };

  /** 조각 index의 seconds 위치로 (src가 바뀌면 메타데이터를 받은 뒤) */
  const go = (index: number, seconds: number, play: boolean) => {
    setError(null);
    pending.current = { seconds, play };
    setSeekTarget(seconds);
    setCur(index);
    const el = ref.current;
    if (el !== null && index === cur && el.readyState >= 1) apply(el);
  };

  const apply = (el: HTMLVideoElement) => {
    const p = pending.current;
    if (p === null) return;
    pending.current = null;
    held.current = !p.play;
    el.currentTime = p.seconds;
    if (p.play) void el.play().catch(() => {});
    else el.pause();
  };

  // 고른 스텝이 바뀌면 그 시작 시각으로
  useEffect(() => {
    clearTimer();
    if (target === null || chain.length === 0) return;
    const spot = locate(video, target);
    if (spot.kind === "segment") {
      setGap(null);
      go(spot.index, seekSeconds(chain[spot.index].segment, spot.offsetMs), false);
    } else {
      setGap(spot);
      ref.current?.pause();
    }
    // go·apply는 매번 새 함수다: 스텝·영상이 바뀔 때만 옮긴다
  }, [step.step, target, video, chain]);

  useEffect(() => clearTimer, []);

  const segment = cur === null ? null : (chain[cur]?.segment ?? null);
  const onEnded = () => {
    if (cur === null || held.current) return;
    const after = nextAfter(video, cur);
    if (after.next === null) return;
    const next = after.next;
    if (after.gap !== null && after.gap.kind === "gap") {
      setGap(after.gap);
      clearTimer();
      timer.current = setTimeout(() => {
        timer.current = null;
        setGap(null);
        go(next, 0, true);
      }, GAP_NOTICE_MS);
    } else {
      go(next, 0, true);
    }
  };
  const playFrom = (index: number) => {
    clearTimer();
    setGap(null);
    go(index, 0, true);
  };

  const spanStart = Math.min(...chain.map((c) => c.start), ...video.gaps.map((g) => Date.parse(g.t_start)));
  const spanEnd = Math.max(...chain.map((c) => c.end), ...video.gaps.map((g) => Date.parse(g.t_end)));
  const span = Number.isFinite(spanStart) && Number.isFinite(spanEnd) && spanEnd > spanStart ? spanEnd - spanStart : null;
  const pct = (t: number) => (span === null ? 0 : ((t - spanStart) / span) * 100);
  const clock = (t: number | null) => (t === null || runStart === null ? "" : formatClock(t - runStart).slice(0, -2));

  return (
    <div
      className={css.video}
      data-part="video-player"
      data-state={error !== null ? "error" : gap !== null ? "gap" : "segment"}
      data-segment={segment?.file ?? ""}
      data-gap={gap?.reason ?? ""}
      data-seek-target={seekTarget ?? ""}
    >
      <div className={css.videoFrame}>
        {segment !== null && (
          <video
            ref={ref}
            className={css.videoEl}
            data-part="video"
            src={fileUrl(runDir, `video/${segment.file}`)}
            controls
            muted
            preload="auto"
            onLoadedMetadata={(e) => apply(e.currentTarget)}
            onTimeUpdate={(e) => cur !== null && setNow(runTimeAt(chain[cur], e.currentTarget.currentTime))}
            onSeeked={(e) => cur !== null && setNow(runTimeAt(chain[cur], e.currentTarget.currentTime))}
            onEnded={onEnded}
            onPlay={() => {
              held.current = false;
            }}
            onError={() => setError("이 PC에서 재생할 수 없음")}
          />
        )}
        {error !== null && (
          <div className={css.videoOverlay} data-part="video-error" role="status">
            {error}
          </div>
        )}
        {error === null && gap !== null && (
          <div className={css.videoOverlay} data-part="video-gap" role="status">
            <span>{gapText(gap.reason)}</span>
            {gap.next !== null && timer.current === null && (
              <button type="button" className={css.button} style={{ marginLeft: 0 }} onClick={() => playFrom(gap.next!)}>
                다음 영상부터 재생
              </button>
            )}
          </div>
        )}
      </div>
      <div className={css.videoMeta}>
        <span>{segment !== null ? `${segment.file} · ${cur! + 1}/${chain.length}` : ""}</span>
        <span data-part="video-clock">{clock(now)}</span>
      </div>
      {span !== null && (
        <div className={css.videoStrip} aria-label="영상 구간">
          {video.gaps.map((g, i) => (
            <div
              key={`g${i}`}
              className={css.videoGap}
              data-part="video-strip-gap"
              title={gapText(g.gap)}
              style={{ left: `${pct(Date.parse(g.t_start))}%`, width: `${pct(Date.parse(g.t_end)) - pct(Date.parse(g.t_start))}%` }}
            />
          ))}
          {chain.map((c, i) => (
            <button
              key={c.segment.file}
              type="button"
              className={css.videoSeg}
              aria-pressed={i === cur}
              aria-label={`조각 ${i + 1} 재생`}
              title={`${c.segment.file} · ${clock(c.start)} — ${clock(c.end)}`}
              style={{ left: `${pct(c.start)}%`, width: `${pct(c.end) - pct(c.start)}%` }}
              onClick={() => playFrom(i)}
            />
          ))}
          {target !== null && <div className={css.videoMarker} style={{ left: `${pct(target)}%` }} />}
        </div>
      )}
    </div>
  );
}
