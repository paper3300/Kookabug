// 녹화 초안 어댑터 자리 (M4 계획 2.10 첫 줄, T11은 자리만 — 구현은 T10 REC 탭)
// REC 탭은 TargetEditorBody(TargetEditor.tsx)를 이 어댑터로 쓴다. T10이 채울 것:
// - 문서: recorder.frame {step, which}로 올린 정지 화면(frame_id)·보호 영역(protected, 빗금), 스텝의 target 사양(초안)
// - editSpec·setTemplate: 렌더러 초안 상태를 고치고 recorder.step.update {patch:{target:{rect, offset, anchor, threshold,
//   rgb, methods, color_tolerance, sensitive, search}, frame_id}}로 보낸다 (겹치면 secret_region_overlap)
// - previewRequest: 그 frame_id의 crop 템플릿 (파일 target과 같은 target.preview)
// - "찾기 대상 탭으로 열기": 그 초안만 파일로 저장하고 파일 target 어댑터(TARGET 탭)로 바꾼다
import type { TargetDocAdapter } from "./adapter";
import type { Rect } from "./geometry";

export interface DraftTargetAdapter extends TargetDocAdapter {
  readonly kind: "draft";
  /** 녹화 스텝 ID */
  readonly step: string;
  /** 지금 정지 화면의 보호 영역 (정지 화면 픽셀) — 판에 빗금으로 그린다 */
  readonly protectedRects: readonly Rect[];
}
