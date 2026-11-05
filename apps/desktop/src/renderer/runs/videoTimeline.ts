// 영상 시각 대응 (M3 계획 2.5 "실행 시각 ↔ 재생 시각", 검수 M3). 조각 하나는 t0부터 frame_ms(200 ms) 격자로 쓰여
// 재생 위치 slot × frame_ms = 실행 시각 t0 + slot × frame_ms 다. 조각 안에는 빈 구간이 없고, 조각 사이는 빈 구간
// (gaps의 이유, 없으면 모름)이다 — 조각 사이 시각을 다음 조각 처음으로 옮기지 않는다
import type { runIndex, videoIndex } from "@kookabug/schema";

export type VideoView = runIndex.VideoView;
export type Segment = videoIndex.Segment;
export type Gap = videoIndex.Gap;
export type GapReason = videoIndex.GapReason;

export type VideoSpot =
  /** 조각 안: 그 칸의 재생 위치 */
  | { kind: "segment"; index: number; slot: number; offsetMs: number }
  /** 빈 구간 (reason null = 기록된 이유 없음). next = 그 뒤 첫 조각 (없으면 null) */
  | { kind: "gap"; reason: GapReason | null; gap: Gap | null; next: number | null };

export interface ChainSegment {
  segment: Segment;
  /** 실행 시각 ms */
  start: number;
  end: number;
}

function ms(t: string): number {
  const v = Date.parse(t);
  return Number.isFinite(v) ? v : Number.NaN;
}

/** 이어 재생할 순서: 실행 시각 순 (끝 = t0 + frames × frame_ms) */
export function segmentChain(view: VideoView): ChainSegment[] {
  return view.segments
    .map((segment) => {
      const start = ms(segment.t0);
      return { segment, start, end: start + segment.frames * segment.frame_ms };
    })
    .filter((c) => Number.isFinite(c.start))
    .sort((a, b) => a.start - b.start);
}

/** 실행 시각 tMs가 영상의 어디인가 */
export function locate(view: VideoView, tMs: number): VideoSpot {
  const chain = segmentChain(view);
  for (let i = 0; i < chain.length; i++) {
    const c = chain[i];
    if (tMs >= c.start && tMs < c.end) {
      const frame = c.segment.frame_ms;
      const slot = Math.min(c.segment.frames - 1, Math.max(0, Math.floor((tMs - c.start) / frame)));
      return { kind: "segment", index: i, slot, offsetMs: slot * frame };
    }
  }
  const next = chain.findIndex((c) => c.start > tMs);
  // 그 시각을 덮는 빈 구간, 없으면 그 시각이 든 조각 사이 틈과 가장 많이 겹치는 빈 구간
  // (녹화기는 끝나지 않은 칸을 버리고 조각을 닫아 조각 끝과 실제 차단 시작 사이에 칸보다 짧은 틈이 생긴다)
  const prevEnd = Math.max(Number.NEGATIVE_INFINITY, ...chain.filter((c) => c.end <= tMs).map((c) => c.end));
  const nextStart = next < 0 ? Number.POSITIVE_INFINITY : chain[next].start;
  const gap = view.gaps.find((g) => tMs >= ms(g.t_start) && tMs < ms(g.t_end)) ?? holeGap(view, prevEnd, nextStart);
  return { kind: "gap", reason: gap?.gap ?? null, gap, next: next < 0 ? null : next };
}

/** 스텝을 고르면 영상에서 보일 실행 시각에 쓰는 스텝 정보 (StepNode의 일부) */
export interface StepTimes {
  t_start: string | null | undefined;
  t_end?: string | null;
  status?: string | null;
}

const FAILED_STATUS = new Set(["fail", "error"]);

/**
 * 스텝을 고르면 옮겨 갈 실행 시각 ms (M3 사람 확인 R1 F2). 스텝 시작이 녹화 준비 중 같은 빈 구간이어도 그 스텝에 영상이
 * 있으면 영상부터 보인다:
 * - 실패 스텝: 실패 순간(스텝 끝 직전 칸). 그 순간이 빈 구간이면 스텝 구간 안 가장 늦은 영상 칸
 * - 그 밖: 시작 시각. 시작이 빈 구간이면 스텝 구간 안 첫 영상 시각
 * - 스텝 구간 안에 영상이 없으면 시작 시각 (빈 구간 이유를 보인다). 시작을 모르면 null
 */
export function stepVideoTime(view: VideoView, step: StepTimes): number | null {
  const start = step.t_start ? ms(step.t_start) : Number.NaN;
  if (!Number.isFinite(start)) return null;
  const endRaw = step.t_end ? ms(step.t_end) : Number.NaN;
  const end = Number.isFinite(endRaw) && endRaw >= start ? endRaw : null;
  const chain = segmentChain(view);
  const covered = (t: number) => chain.some((c) => t >= c.start && t < c.end);
  if (end !== null && FAILED_STATUS.has(step.status ?? "")) {
    // 끝 시각 자체는 칸 경계일 수 있어 1 ms 앞 (그 칸 = 실패를 판정한 순간의 화면)
    const moment = Math.max(start, end - 1);
    if (covered(moment)) return moment;
    const inside = chain.filter((c) => c.start <= moment && c.end > start);
    if (inside.length > 0) {
      const last = inside[inside.length - 1];
      return Math.max(last.start, Math.min(moment, last.end - 1));
    }
    return start;
  }
  if (covered(start)) return start;
  const first = chain.find((c) => c.start > start && (end === null || c.start < end));
  return first !== undefined ? first.start : start;
}

/** [from, to) 틈과 가장 많이 겹치는 기록된 빈 구간 (없으면 null) */
function holeGap(view: VideoView, from: number, to: number): Gap | null {
  let best: Gap | null = null;
  let most = 0;
  for (const g of view.gaps) {
    const overlap = Math.min(to, ms(g.t_end)) - Math.max(from, ms(g.t_start));
    if (overlap > most) {
      best = g;
      most = overlap;
    }
  }
  return best;
}

/** 그 칸을 보이려고 넣을 재생 위치 (초). 칸 가운데라 소수점 반올림으로 앞 칸이 보이지 않는다 */
export function seekSeconds(segment: Segment, offsetMs: number): number {
  return (offsetMs + segment.frame_ms / 2) / 1000;
}

/** 재생 위치(초) → 실행 시각 ms */
export function runTimeAt(chain: ChainSegment, seconds: number): number {
  return chain.start + seconds * 1000;
}

/**
 * 조각 끝에서 다음으로: 다음 조각과, 그 사이 빈 구간. [이 조각 끝, 다음 조각 시작)과 겹치는 기록된 빈 구간이 있으면
 * 짧아도 그 이유를 띄운다. 기록된 것이 없고 사이가 한 칸보다 짧으면 이어 붙은 것으로 본다
 */
export function nextAfter(view: VideoView, index: number): { next: number | null; gap: VideoSpot | null } {
  const chain = segmentChain(view);
  const cur = chain[index];
  const next = chain[index + 1];
  if (cur === undefined || next === undefined) return { next: null, gap: null };
  const gap = holeGap(view, cur.end, next.start);
  if (gap !== null) return { next: index + 1, gap: { kind: "gap", reason: gap.gap, gap, next: index + 1 } };
  if (next.start - cur.end < cur.segment.frame_ms) return { next: index + 1, gap: null };
  return { next: index + 1, gap: { kind: "gap", reason: null, gap: null, next: index + 1 } };
}

export const GAP_TEXT: Record<GapReason, string> = {
  policy_off: "기록 끔",
  secret_input: "비밀값 입력",
  paused: "디버거로 멈춤",
  no_window: "대상 창 없음",
  capture_missed: "화면을 받지 못함",
  unavailable: "이 PC에서 지원 안 됨",
  failed: "녹화 실패",
  starting: "녹화 준비 중",
  interrupted: "중단돼 지움",
};

export function gapText(reason: GapReason | null): string {
  return reason === null ? "영상 없음" : `영상 없음 · ${GAP_TEXT[reason] ?? reason}`;
}

/** 영상을 포기한 실행의 이유: 녹화 스레드가 멈춤(encoder_stuck), 인코더 준비가 늦어 모은 화면을 버림(encoder_not_ready). */
function omittedNote(reason: unknown): string {
  return reason === "encoder_not_ready" ? "영상 없음 · 인코더 준비가 늦어 버림" : "영상 없음 · 인코더가 멈춰 버림";
}

/**
 * 스크린샷 줄 머리의 영상 표시 (U8): 조각이 있으면 "스크린샷 | 영상" 전환, 없으면 전환 없이 이유만(영상 폴더가
 * 없는 실행은 아무것도). runVideo = run.json.video (지운 조각 수)
 */
export function videoHeader(
  view: VideoView | null | undefined,
  runVideo?: { status?: unknown; deleted?: unknown; reason?: unknown } | null,
): { toggle: boolean; note: string | null } {
  if (view === null || view === undefined) {
    if (runVideo?.status === "omitted") return { toggle: false, note: omittedNote(runVideo.reason) };
    return { toggle: false, note: null };
  }
  if (view.segments.length > 0) return { toggle: true, note: null };
  if (view.status === "omitted") return { toggle: false, note: omittedNote(view.reason) };
  if (view.status === "unavailable") return { toggle: false, note: "영상 없음 · 이 PC에서 영상 인코더를 쓸 수 없음" };
  if (view.status === "failed") return { toggle: false, note: "영상 없음 · 녹화 실패" };
  if (typeof runVideo?.deleted === "number" && runVideo.deleted > 0) return { toggle: false, note: "영상 없음 · 실패하지 않은 실행이라 지움" };
  return { toggle: false, note: null };
}
