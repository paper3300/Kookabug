// REC 탭 문서와 녹화 초안 어댑터 (M4 계획 2.10 첫 줄, T10). 편집기 부품(TargetEditorBody)을 그대로 쓰고, 편집은
// target 파일이 아니라 recorder.step.update로 보낸다.
// - 정지 화면: recorder.frame {step, which}(클릭 직전·커서 들어오기 전·다음 동작 직전) 또는 live(지금 화면). 결과의
//   protected(보호 영역)를 판에 빗금으로 그린다
// - 초안 사양: daemon은 고칠 때마다 준 값으로 초안을 다시 만든다(준 것 말고는 기본값) — 그래서 편집마다 사양 전체
//   (영역·클릭 지점·임계값·색·배율·색 허용치·민감 대상·검색 범위)와 지금 정지 화면 frame_id를 같이 보낸다
// - 보호 영역과 겹치면 daemon이 secret_region_overlap으로 거부 → 영역을 앞 값으로 되돌리고 거부 문구
// 검색 범위는 편집기 쪽이 정규화 [x, y, w, h](파일 target 형식), daemon 쪽이 정지 화면 픽셀이라 여기서 바꾼다
import type { daemonRpc } from "@kookabug/schema";
import { create } from "zustand";
import { client, toRpcError } from "../rpc/client";
import type { PreviewParams, TargetDocAdapter, TargetEditorView } from "../target/adapter";
import { normalizedToPixels, pixelsToRegion, type Rect, type Size } from "../target/geometry";
import { DEFAULT_METHODS, specFields, type TargetSpec } from "../target/spec";
import { PREVIEW_DEBOUNCE_MS, type PreviewResult } from "../target/targetStore";
import { recorderErrorText, type RecorderStep } from "./labels";
import { replaceStepFromServer } from "./recorderStore";

export type FrameWhich = daemonRpc.RecorderFrameWhich;

export interface RecDoc extends TargetEditorView {
  /** 정지 화면의 스텝 (live·확인 넣기면 null) */
  step: string | null;
  which: FrameWhich;
  frameLoading: boolean;
  frameError: string | null;
  /** 마지막으로 daemon이 받아들인 영역 (거부되면 여기로 되돌린다) */
  acceptedTemplate: Rect | null;
  /** 보호 영역 겹침 등 거부 문구 */
  refusal: string | null;
  /** 보내는 중 (step.update) */
  sending: boolean;
  /** 미리보기 요청 번호 */
  previewSeq: number;
}

const EMPTY: RecDoc = {
  path: "rec:capture",
  status: "ready",
  isNew: true,
  spec: {},
  savedSpec: null,
  image: null,
  frame: null,
  frameExpired: false,
  template: null,
  preview: null,
  previewNote: null,
  previewPending: false,
  protectedRects: [],
  step: null,
  which: "live",
  frameLoading: false,
  frameError: null,
  acceptedTemplate: null,
  refusal: null,
  sending: false,
  previewSeq: 0,
};

export const useRecDoc = create<{ doc: RecDoc; gen: number }>(() => ({ doc: EMPTY, gen: 0 }));

let sendTimer: ReturnType<typeof setTimeout> | null = null;

/** 재사용 target을 이 화면에서 찾지 못해 초안으로 바꿀 수 없을 때 */
export const FILE_TARGET_NOTE = "기존 대상을 이 화면에서 찾지 못했어요 — 영역을 다시 고르면 새 대상이 돼요";

function patchDoc(patch: Partial<RecDoc>, gen?: number): void {
  useRecDoc.setState((s) => (gen !== undefined && gen !== s.gen ? s : { doc: { ...s.doc, ...patch } }));
}

export function resetRecDoc(): void {
  useRecDoc.setState((s) => ({ doc: EMPTY, gen: s.gen + 1 }));
}

function frameSize(doc: Pick<RecDoc, "frame">): Size | null {
  return doc.frame === null ? null : (doc.frame.client_size as Size);
}

/** daemon 초안 사양 → 편집기 사양 (파일 target 형식). 화면에 없는 값은 지금 편집기 값을 이어 쓴다 */
export function draftToSpec(draft: daemonRpc.RecorderTargetSpec | undefined, size: Size | null, keep: TargetSpec): TargetSpec {
  const f = specFields(keep);
  const spec: TargetSpec = {
    click: { anchor: draft?.anchor ?? f.anchor, offset: draft?.offset ?? f.offset },
    match: {
      threshold: draft?.threshold ?? f.threshold,
      rgb: draft?.rgb ?? f.rgb,
      methods: draft?.methods ?? (f.multiscale ? [...DEFAULT_METHODS] : ["template"]),
      color_tolerance: draft?.color_tolerance ?? f.colorTolerance,
    },
  };
  if (draft?.sensitive ?? f.sensitive) spec.sensitive = true;
  const search = draft === undefined ? (f.region === null || size === null ? null : normalizedToPixels(f.region, size)) : (draft.search ?? null);
  if (search !== null && size !== null) spec.search = { region: pixelsToRegion(search as Rect, size) };
  return spec;
}

/** 편집기 사양 + 영역 → daemon 초안 사양 (전체) */
export function specToDraft(spec: TargetSpec, rect: Rect, size: Size | null): daemonRpc.RecorderTargetSpec {
  const f = specFields(spec);
  const out: daemonRpc.RecorderTargetSpec = {
    rect,
    anchor: f.anchor,
    offset: f.offset,
    threshold: f.threshold,
    rgb: f.rgb,
    methods: f.multiscale ? ["template_multiscale", "template"] : ["template"],
    color_tolerance: f.colorTolerance,
    sensitive: f.sensitive,
    search: f.region === null || size === null ? null : normalizedToPixels(f.region, size),
  };
  return out;
}

// ── 정지 화면 ───────────────────────────────────────────────────

/**
 * 스텝(또는 live)의 정지 화면을 올린다. 초안이면 그 영역·사양을 편집기에.
 * bind false: 그 스텝의 화면만 빌리고 편집 대상 스텝은 연결하지 않는다 — 확인 넣기 영역 고르기가 기존 스텝을
 * 바꾸지 않게 (B5 검수 M2)
 */
export async function loadRecFrame(step: RecorderStep | null, which: FrameWhich, options: { bind?: boolean } = {}): Promise<void> {
  const bind = options.bind ?? true;
  const owner = bind ? (step?.step ?? null) : null;
  const gen = useRecDoc.getState().gen + 1;
  if (sendTimer !== null) {
    // 앞 문서의 보내기 대기는 그 문서와 함께 버린다 (다른 스텝·확인 모드로 보내지 않게)
    clearTimeout(sendTimer);
    sendTimer = null;
  }
  const keepSpec = owner !== null && useRecDoc.getState().doc.step === owner ? useRecDoc.getState().doc.spec : {};
  useRecDoc.setState({
    gen,
    doc: { ...EMPTY, step: owner, which, frameLoading: true, spec: keepSpec },
  });
  try {
    const r = await client().call("recorder.frame", step === null ? { which: "live" } : { step: step.step, which });
    const size = r.frame.client_size as Size;
    const target = bind ? step?.target : undefined;
    const draft = target?.source === "draft" ? target.spec : undefined;
    const rect = draft?.rect === undefined ? null : (draft.rect as Rect);
    // 기존(재사용) target 파일: 그 사양·이미지로 찾아 보인다. 고치면 이 화면에서 새 초안이 된다(파일은 그대로)
    const filePath = target?.source === "file" ? (target.path ?? null) : null;
    let fileSpec: TargetSpec | null = null;
    let fileImage: RecDoc["image"] = null;
    if (filePath !== null) {
      try {
        const opened = await client().call("target.open", { path: filePath });
        fileSpec = opened.spec;
        fileImage = opened.image;
      } catch {
        // 파일을 못 읽음: 영역을 고르면 초안으로 만든다
      }
    }
    patchDoc(
      {
        path: filePath ?? EMPTY.path,
        frame: r.frame,
        protectedRects: r.protected as Rect[],
        frameLoading: false,
        template: rect,
        acceptedTemplate: rect,
        spec: fileSpec ?? draftToSpec(draft, size, keepSpec),
        image: fileImage,
        isNew: fileSpec === null,
        status: "ready",
      },
      gen,
    );
    requestRecPreview();
  } catch (err) {
    const e = toRpcError(err);
    patchDoc({ frameLoading: false, frameError: e.kind === "no_frame" ? "보일 화면이 없어요" : e.message }, gen);
  }
}

// ── 미리보기 ────────────────────────────────────────────────────

function previewRequest(doc: TargetEditorView): { params: PreviewParams } | { note: string } {
  if (doc.frame === null) return { note: "정지 화면이 없어요" };
  if (doc.template === null) {
    // 재사용한 target 파일: 그 이미지로 찾는다 (경로는 target 파일 기준)
    const image = doc.spec.image;
    if (!doc.isNew && typeof image === "string" && doc.image !== null) {
      return { params: { frame_id: doc.frame.frame_id, spec: doc.spec, template: { image }, base_path: doc.path } };
    }
    return { note: "정지 화면에서 찾을 영역을 드래그하세요" };
  }
  return { params: { frame_id: doc.frame.frame_id, spec: doc.spec, template: { crop: { frame_id: doc.frame.frame_id, rect: doc.template } } } };
}

let previewTimer: ReturnType<typeof setTimeout> | null = null;

export function requestRecPreview(delay = PREVIEW_DEBOUNCE_MS): void {
  if (previewTimer !== null) clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    previewTimer = null;
    void previewNow();
  }, delay);
}

async function previewNow(): Promise<void> {
  const { doc, gen } = useRecDoc.getState();
  const request = previewRequest(doc);
  if ("note" in request) {
    patchDoc({ preview: null, previewNote: request.note, previewPending: false }, gen);
    return;
  }
  const seq = doc.previewSeq + 1;
  patchDoc({ previewSeq: seq, previewPending: true }, gen);
  try {
    const result: PreviewResult = await client().call("target.preview", { ...request.params, seq });
    const now = useRecDoc.getState();
    if (now.gen === gen && now.doc.previewSeq === seq) patchDoc({ preview: result, previewNote: null, previewPending: false }, gen);
  } catch (err) {
    const now = useRecDoc.getState();
    if (now.gen === gen && now.doc.previewSeq === seq) {
      patchDoc({ preview: null, previewNote: `찾지 못했어요: ${toRpcError(err).message}`, previewPending: false }, gen);
    }
  }
}

// ── 초안 보내기 ─────────────────────────────────────────────────

export const SEND_DEBOUNCE_MS = 250;

function scheduleSend(): void {
  if (sendTimer !== null) clearTimeout(sendTimer);
  sendTimer = setTimeout(() => {
    sendTimer = null;
    void sendDraft();
  }, SEND_DEBOUNCE_MS);
}

/** 지금 편집기 값을 그 스텝의 초안으로 보낸다. 거부되면 영역을 되돌린다 */
export async function sendDraft(): Promise<boolean> {
  const { doc, gen } = useRecDoc.getState();
  if (doc.step === null || doc.frame === null || doc.template === null) return false;
  patchDoc({ sending: true }, gen);
  try {
    const r = await client().call("recorder.step.update", {
      step: doc.step,
      patch: { frame_id: doc.frame.frame_id, target: specToDraft(doc.spec, doc.template, frameSize(doc)) },
    });
    replaceStepFromServer(doc.step, r.step, r.rev);
    patchDoc({ sending: false, refusal: null, acceptedTemplate: doc.template }, gen);
    return true;
  } catch (err) {
    const e = toRpcError(err);
    const text = e.kind === "secret_region_overlap" ? "비밀번호 칸과 겹치는 영역은 쓸 수 없어요 — 영역을 다시 고르세요" : recorderErrorText(e.kind, e.message);
    const back = useRecDoc.getState().doc.acceptedTemplate;
    patchDoc({ sending: false, refusal: text, template: back }, gen);
    requestRecPreview(0);
    return false;
  }
}

// ── 어댑터 ──────────────────────────────────────────────────────

/** 녹화 초안 어댑터 (판·패널이 쓰는 편집 경로). 확인 넣기·live에서는 영역만 고른다(보내지 않음) */
export const recAdapter: TargetDocAdapter & { readonly kind: "draft" } = {
  kind: "draft",
  key: "rec:capture",
  editSpec(fn) {
    const { doc } = useRecDoc.getState();
    if (doc.frame === null) return;
    // 재사용 target 파일(영역 없음)을 고치면: 파일은 그대로 두고 이 화면에서 찾은 자리로 새 초안을 만든다
    // (B5 검수 M4). 못 찾았으면 고치지 않고 영역을 다시 고르라고 알린다
    let template = doc.template;
    if (doc.step !== null && template === null && !doc.isNew) {
      const match = doc.preview?.found === true ? doc.preview.match : null;
      if (match === null || match === undefined) {
        patchDoc({ refusal: FILE_TARGET_NOTE });
        return;
      }
      template = match.rect as Rect;
    }
    const next = fn(doc.spec);
    if (next === doc.spec && template === doc.template) return;
    patchDoc(template === doc.template ? { spec: next } : { spec: next, template, isNew: true, image: null, refusal: null });
    requestRecPreview();
    if (doc.step !== null && template !== null) scheduleSend();
  },
  setTemplate(rect) {
    const { doc } = useRecDoc.getState();
    if (doc.frame === null) return;
    patchDoc({ template: rect, refusal: null });
    requestRecPreview();
    if (doc.step !== null && rect !== null) scheduleSend();
  },
  previewRequest,
};

/** 기다리는 보내기가 있으면 지금 보낸다 (파일로 쓰기 전에 최신 영역·사양을 daemon에) */
export async function flushDraft(): Promise<boolean> {
  if (sendTimer === null) return true;
  clearTimeout(sendTimer);
  sendTimer = null;
  return sendDraft();
}

/** 지금 정지 화면에서 글자를 읽을 영역: 고른 영역, 없으면 찾은 상자 */
export function readRegion(): { frameId: string; rect: Rect } | null {
  const { doc } = useRecDoc.getState();
  if (doc.frame === null) return null;
  const match = doc.preview?.found === true ? doc.preview.match : null;
  const rect = doc.template ?? (match === null || match === undefined ? null : (match.rect as Rect));
  return rect === null ? null : { frameId: doc.frame.frame_id, rect };
}

/** 확인 넣기 모드에서 쓸 지금 영역 */
export function checkRegion(): { frameId: string; rect: Rect } | null {
  const { doc } = useRecDoc.getState();
  return doc.frame === null || doc.template === null ? null : { frameId: doc.frame.frame_id, rect: doc.template };
}
