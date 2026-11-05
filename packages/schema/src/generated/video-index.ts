/* 생성물 (packages/schema/*.schema.json → scripts/gen.mjs). 직접 고치지 않는다. */

/**
 * video/ 안에 녹화 스레드가 쓴 조각 파일 이름: 닫은 조각 seg-NNNN.mp4 또는 쓰는 중 파일 seg-NNNN.part.mp4 (지운 조각 기록에만 쓴다)
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "WrittenSegmentFile".
 */
export type WrittenSegmentFile = string;
/**
 * 조각의 영상 정책: on은 늘 남기고, failed_only는 판정 fail·error면 남긴다
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "SegmentMode".
 */
export type SegmentMode = "failed_only" | "on";
/**
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "GapReason".
 */
export type GapReason =
  | "capture_missed"
  | "failed"
  | "interrupted"
  | "no_window"
  | "paused"
  | "policy_off"
  | "secret_input"
  | "starting"
  | "unavailable";
/**
 * 영상이 없거나 멈춘 이유. mf_missing: Media Foundation이 없음, backend_missing: OpenCV MSMF 백엔드 없음, encoder_open_failed: 인코더 열기 실패, write_failed: 녹화 중 쓰기 실패, encoder_stuck: 녹화 스레드가 기다림 상한(3초, 마무리 유예가 짧으면 유예에서 기록 여유를 뺀 시간) 안에 끝나지 않아 영상을 포기, 또는 영상 마무리 단계에서 준비가 끝난 뒤 모은 프레임의 쓰기·닫기가 상한 안에 끝나지 않았거나 그 사이 runner가 끝남(대기 표식 phase writing), encoder_not_ready: 실행이 인코더 준비보다 먼저 끝나 모은 프레임을 들고 기다렸지만 영상 마무리 단계 상한(30초)까지 준비되지 않았거나 그 단계가 거절·취소·중단돼 버림
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "VideoReason".
 */
export type VideoReason =
  | "backend_missing"
  | "encoder_not_ready"
  | "encoder_open_failed"
  | "encoder_stuck"
  | "mf_missing"
  | "write_failed";
/**
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "StepId".
 */
export type StepId = string;
/**
 * UTC 시각, 밀리초까지 (2026-10-29T06:02:11.104Z). events.jsonl의 t와 같은 시계
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "Timestamp".
 */
export type Timestamp = string;
/**
 * video/ 안 닫은(재생할 수 있는) 조각 파일 이름 seg-NNNN.mp4. 쓰는 중 파일(.part.mp4)은 조각 목록에 올 수 없다
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "SegmentFile".
 */
export type SegmentFile = string;
/**
 * recorded: 조각을 남김(지웠을 수도 있음), none: 쓸 프레임이 없었음(정책·창 없음), unavailable: 인코더를 쓸 수 없음, failed: 녹화 중 쓰기 실패, omitted: 영상을 포기함 (reason encoder_stuck·encoder_not_ready)
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "VideoStatus".
 */
export type VideoStatus = "failed" | "none" | "omitted" | "recorded" | "unavailable";
/**
 * video/segments.jsonl 한 줄: 닫은 조각, 비운 구간, 또는 늦은 인코더 대기 완료 줄. 녹화 스레드만 덧붙인다
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "SegmentsLine".
 */
export type SegmentsLine = Segment | Gap | EncoderWaitSettled;

/**
 * 실행 폴더 video/index.json: 마무리(finalize_video)가 최종 run.end 기준으로 공개한 영상 색인. 같은 폴더 임시 파일 + replace로만 쓴다. 이 파일이 없으면 읽는 쪽은 segments.jsonl만 보고 보여 준다
 */
export interface VideoIndex {
  /**
   * 남은 조각 바이트 합
   */
  bytes: number;
  /**
   * 지워야 하는데 지우지 못한 파일 (다음 마무리가 다시 시도한다)
   */
  cleanup_failed?: string[];
  deleted: DeletedSegment[];
  format: "kookabug.video-index/0";
  gaps: Gap[];
  reason?: VideoReason;
  /**
   * 남은 조각 (실행 시각 순)
   */
  segments: Segment[];
  status: VideoStatus;
}
/**
 * 마무리에서 지운 조각과 이유. run_pass·run_skipped·run_cancelled: 판정 pass·skipped·사용자 취소라 failed_only 조각을 지움, interrupted: 쓰다 만 조각(.part.mp4, segments.jsonl 줄 없는 .mp4), encoder_stuck: 녹화 스레드가 멈춰(또는 영상 마무리 단계의 쓰기 중에 끝나) 그 실행의 영상을 포기함
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "DeletedSegment".
 */
export interface DeletedSegment {
  file: WrittenSegmentFile;
  mode?: SegmentMode;
  reason: "encoder_stuck" | "interrupted" | "run_cancelled" | "run_pass" | "run_skipped";
}
/**
 * 영상을 쓰지 않은 구간과 이유. policy_off: 기록 끈 구간, secret_input: 비밀값을 받은 스텝(이 열린 동안), paused: 디버거로 멈춤, no_window: 대상 창 없음, capture_missed: 캡처가 2초 넘게 계속 실패, unavailable: 이 PC에서 영상 인코더를 쓸 수 없음, failed: 녹화 중 쓰기가 실패해 영상을 멈춤, starting: 인코더 열기 시험을 기다린 실행 앞부분(프레임을 모으지 못한 구간. reason encoder_not_ready면 실행 중 모은 프레임이 있었지만 인코더가 영상 마무리 단계 상한까지 준비되지 않아 버린 구간이고 실행 끝까지다), interrupted: 실행이 중단돼 쓰던 조각을 지움. step은 구간을 연 스텝 (policy_off·secret_input·paused), reason은 unavailable·failed·starting의 이유 (마무리가 index.json의 status·reason을 이것으로 정한다)
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "Gap".
 */
export interface Gap {
  gap: GapReason;
  reason?: VideoReason;
  step?: StepId;
  t_end: Timestamp;
  t_start: Timestamp;
}
/**
 * 닫은 조각 하나 (segments.jsonl 한 줄, index.json의 segments 항목). 조각 하나는 한 모드·한 창·한 크기·최대 60초이고 안에 빈 구간이 없다. t0은 칸 0의 실행 시각, t_end는 닫은 실행 시각(t0 + frames * frame_ms). 실행 시각 t0 + slot * frame_ms = 재생 위치 slot * frame_ms
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "Segment".
 */
export interface Segment {
  bytes: number;
  file: SegmentFile;
  /**
   * 격자 칸 길이 (초당 5장이면 200)
   */
  frame_ms: number;
  /**
   * 쓴 칸 수 (반복 칸 포함)
   */
  frames: number;
  mode: SegmentMode;
  /**
   * [w, h] 쓴 프레임 크기 (긴 변 1920 이하로 줄인 뒤)
   *
   * @minItems 2
   * @maxItems 2
   */
  size: [number, number];
  t0: Timestamp;
  t_end: Timestamp;
  /**
   * 녹화한 창 (가장 안쪽 호출 프레임의 현재 창 바인딩, match.window와 같은 표기)
   */
  window: string;
}
/**
 * video/segments.jsonl 한 줄: 늦은 인코더 대기(encoder-wait.json 표식)에 들어간 녹화 스레드가 모은 프레임의 결과(조각·포기 빈 구간·failed·unavailable)를 모두 기록했다. 결과가 정해졌다는 근거는 이 줄 하나이고, 마무리는 이 줄이 있으면 표식을 무시한다(표식 지우기는 녹화 스레드의 최선 시도). t는 기록한 시각
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "EncoderWaitSettled".
 */
export interface EncoderWaitSettled {
  encoder_wait: "settled";
  t: Timestamp;
}
/**
 * video/seg-NNNN.frames.jsonl 한 줄: 격자 칸 하나에 무엇을 썼는지 (검사·사람 확인용. 뷰어 이동은 격자로 한다). pixels_at은 그 칸에 쓴 프레임의 픽셀 시각(반복이면 반복한 프레임의 시각)
 *
 * This interface was referenced by `VideoIndex`'s JSON-Schema
 * via the `definition` "FramesLine".
 */
export interface FramesLine {
  pixels_at: Timestamp;
  /**
   * 새 프레임이 없어(캡처 지연·건너뜀·보류 차단) 직전 프레임을 다시 썼다
   */
  repeat: boolean;
  /**
   * 격자 칸 번호 (조각 안에서 0부터). 재생 위치 = slot * frame_ms
   */
  slot: number;
}
