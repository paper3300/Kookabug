import { describe, expect, test } from "vitest";
import { gapText, locate, nextAfter, seekSeconds, segmentChain, videoHeader, type Segment, type VideoView } from "./videoTimeline";

const T0 = Date.parse("2026-11-02T01:00:00.000Z");
const iso = (ms: number) => new Date(T0 + ms).toISOString();

function seg(file: string, startMs: number, frames: number): Segment {
  return {
    bytes: 100,
    file: file as Segment["file"],
    frame_ms: 200,
    frames,
    mode: "failed_only",
    size: [160, 96],
    t0: iso(startMs),
    t_end: iso(startMs + frames * 200),
    window: "w",
  };
}

// 조각 A 0~3초, 비밀값 빈 구간 3~4초, 조각 B 4~6초, (이유 없는 빈틈 6~8초), 조각 C 8~9초. 받은 순서는 섞임
const VIEW: VideoView = {
  finalized: true,
  status: "recorded",
  segments: [seg("seg-0003.mp4", 8000, 5), seg("seg-0001.mp4", 0, 15), seg("seg-0002.mp4", 4000, 10)],
  gaps: [{ gap: "secret_input", step: "s4", t_start: iso(3000), t_end: iso(4000) }],
};

describe("영상 시각 대응 (M3 T11, 검수 M3)", () => {
  test("test_step_time_maps_to_segment_offset_by_grid", () => {
    // 실행 시각 → 조각 t0·frame_ms 격자의 칸 (칸 안 어디든 그 칸의 시작)
    expect(locate(VIEW, T0 + 0)).toEqual({ kind: "segment", index: 0, slot: 0, offsetMs: 0 });
    expect(locate(VIEW, T0 + 1234)).toEqual({ kind: "segment", index: 0, slot: 6, offsetMs: 1200 });
    expect(locate(VIEW, T0 + 2999)).toEqual({ kind: "segment", index: 0, slot: 14, offsetMs: 2800 });
    expect(locate(VIEW, T0 + 4399)).toEqual({ kind: "segment", index: 1, slot: 1, offsetMs: 200 });
    expect(locate(VIEW, T0 + 8000)).toEqual({ kind: "segment", index: 2, slot: 0, offsetMs: 0 });
    // 재생 위치는 칸 가운데 (앞 칸이 보이지 않게)
    const spot = locate(VIEW, T0 + 1234);
    expect(spot.kind === "segment" && seekSeconds(segmentChain(VIEW)[0].segment, spot.offsetMs)).toBeCloseTo(1.3);
  });

  test("test_gap_reason_for_time_in_gap", () => {
    const spot = locate(VIEW, T0 + 3500);
    expect(spot).toMatchObject({ kind: "gap", reason: "secret_input", next: 1 });
    expect(gapText(spot.kind === "gap" ? spot.reason : null)).toBe("영상 없음 · 비밀값 입력");
    // 첫 조각 앞·마지막 조각 뒤
    expect(locate(VIEW, T0 - 500)).toMatchObject({ kind: "gap", reason: null, next: 0 });
    expect(locate(VIEW, T0 + 9000)).toMatchObject({ kind: "gap", reason: null, next: null });
  });

  test("test_segment_chain_playback_order", () => {
    expect(segmentChain(VIEW).map((c) => c.segment.file)).toEqual(["seg-0001.mp4", "seg-0002.mp4", "seg-0003.mp4"]);
    // A 끝 → 비밀값 빈 구간을 보이고 B, B 끝 → 이유 없는 빈틈을 보이고 C, C 끝 → 없음
    expect(nextAfter(VIEW, 0)).toMatchObject({ next: 1, gap: { kind: "gap", reason: "secret_input" } });
    expect(nextAfter(VIEW, 1)).toMatchObject({ next: 2, gap: { kind: "gap", reason: null } });
    expect(nextAfter(VIEW, 2)).toEqual({ next: null, gap: null });
    // 이어 붙은 조각(60초 조각 경계)은 빈 구간 없이 다음으로
    const joined: VideoView = { ...VIEW, segments: [seg("seg-0001.mp4", 0, 15), seg("seg-0002.mp4", 3000, 5)], gaps: [] };
    expect(nextAfter(joined, 0)).toEqual({ next: 1, gap: null });
  });

  test("test_time_between_segments_shows_gap_not_next_segment", () => {
    // 이유가 기록되지 않은 조각 사이 시각도 다음 조각으로 옮기지 않는다
    const spot = locate(VIEW, T0 + 7000);
    expect(spot).toEqual({ kind: "gap", reason: null, gap: null, next: 2 });
    expect(gapText(null)).toBe("영상 없음");
    // 조각 끝 시각(t0 + frames × frame_ms)은 그 조각이 아니다
    expect(locate(VIEW, T0 + 3000)).toMatchObject({ kind: "gap", reason: "secret_input" });
  });

  test("test_gap_reason_when_gate_closes_off_grid_after_segment_end", () => {
    // T11 검수 2: 녹화기는 끝나지 않은 칸을 버리고 조각을 닫아, 조각 A 끝(1000)과 비밀값 차단 시작(1050) 사이에 칸보다
    // 짧은 틈이 생긴다. 이어 재생·틈 시각 모두 기록된 이유를 보인다
    const off: VideoView = {
      finalized: true,
      status: "recorded",
      segments: [seg("seg-0001.mp4", 0, 5), seg("seg-0002.mp4", 2250, 5)],
      gaps: [{ gap: "secret_input", step: "s4", t_start: iso(1050), t_end: iso(2250) }],
    };
    expect(locate(off, T0 + 1100)).toMatchObject({ kind: "gap", reason: "secret_input", next: 1 });
    expect(nextAfter(off, 0)).toMatchObject({ next: 1, gap: { kind: "gap", reason: "secret_input", next: 1 } });
    // 틈(1000~1050) 안 시각도 이유 없음이 아니라 그 틈과 겹치는 빈 구간
    expect(locate(off, T0 + 1020)).toMatchObject({ kind: "gap", reason: "secret_input", next: 1 });
    // 한 칸보다 짧은 빈 구간이라도 기록돼 있으면 없애지 않는다
    const short: VideoView = {
      ...off,
      segments: [seg("seg-0001.mp4", 0, 5), seg("seg-0002.mp4", 1100, 5)],
      gaps: [{ gap: "paused", t_start: iso(1020), t_end: iso(1100) }],
    };
    expect(nextAfter(short, 0)).toMatchObject({ next: 1, gap: { kind: "gap", reason: "paused" } });
  });

  test("test_video_header_toggle_and_notes", () => {
    expect(videoHeader(VIEW)).toEqual({ toggle: true, note: null });
    expect(videoHeader(null)).toEqual({ toggle: false, note: null });
    const empty = { ...VIEW, segments: [] };
    expect(videoHeader({ ...empty, status: "omitted", reason: "encoder_stuck" }).note).toBe("영상 없음 · 인코더가 멈춰 버림");
    expect(videoHeader(null, { status: "omitted" }).note).toBe("영상 없음 · 인코더가 멈춰 버림");
    expect(videoHeader({ ...empty, status: "unavailable", reason: "mf_missing" }).toggle).toBe(false);
    expect(videoHeader(empty, { status: "recorded", deleted: 2 }).note).toContain("지움");
  });
});
