// 편집기 부품 ↔ 문서 어댑터 (M4 계획 2.10, T11). 정지 화면 판·미리보기·클릭 지점·확장 패널(민감 대상·색 허용치·
// 같은 모양·다른 배율·검색 범위 숫자·글자 읽기)은 문서가 무엇이든 같다. 문서마다 다른 것(편집을 어디에 쓰는가,
// 미리보기 요청의 템플릿이 무엇인가)만 어댑터가 정한다
// - 파일 target: targetStore (TARGET 탭, target.save로 저장) — fileTargetAdapter
// - 녹화 초안: REC 탭이 recorder.step.update로 쓴다 — draftAdapter.ts (자리만, 구현은 T10)
import type { daemonRpc } from "@kookabug/schema";
import type { Rect } from "./geometry";
import type { TargetSpec } from "./spec";
import { editSpec, previewRequest, setTemplate, type TargetDoc } from "./targetStore";

/** 편집기 부품이 읽는 문서 모양 (파일 target 문서 TargetDoc의 부분) */
export type TargetEditorView = Pick<
  TargetDoc,
  | "status"
  | "isNew"
  | "spec"
  | "savedSpec"
  | "image"
  | "frame"
  | "frameExpired"
  | "template"
  | "preview"
  | "previewNote"
  | "previewPending"
> & { path: string };

export type PreviewParams = Omit<daemonRpc.TargetPreviewParams, "seq">;

export interface TargetDocAdapter {
  readonly kind: "file" | "draft";
  /** 문서 열쇠 (파일 target이면 경로, 녹화 초안이면 스텝 ID) */
  readonly key: string;
  /** 사양을 고친다 (같은 값이면 아무것도 하지 않는다) */
  editSpec(fn: (spec: TargetSpec) => TargetSpec): void;
  /** 템플릿 영역 (정지 화면 픽셀) */
  setTemplate(rect: Rect | null): void;
  /** 지금 문서로 보낼 미리보기 요청 (다른 배율 점수도 같은 요청에 scales를 붙여 보낸다). 보낼 수 없으면 이유 */
  previewRequest(doc: TargetEditorView): { params: PreviewParams } | { note: string };
}

const fileAdapters = new Map<string, TargetDocAdapter>();

/** 파일 target 어댑터 (경로마다 하나 — React 메모 없이 같은 객체) */
export function fileTargetAdapter(path: string): TargetDocAdapter {
  let adapter = fileAdapters.get(path);
  if (adapter === undefined) {
    adapter = {
      kind: "file",
      key: path,
      editSpec: (fn) => editSpec(path, fn),
      setTemplate: (rect) => setTemplate(path, rect),
      previewRequest: (doc) => previewRequest(doc),
    };
    fileAdapters.set(path, adapter);
  }
  return adapter;
}
