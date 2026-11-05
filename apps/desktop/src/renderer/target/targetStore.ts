// 열린 target 편집기 표 (M2 계획 2.9, T12). TARGET 탭 하나 = 문서 하나 (경로가 열쇠)
// - 사양(JSON 트리)은 렌더러가 갖고, 매칭·저장은 daemon이 한다 (렌더러는 매칭하지 않는다)
// - 정지 화면(frame)은 daemon 프레임 캐시에 있다. 다른 정지 화면을 고르거나 daemon이 바뀌면 frame_expired.
//   기존 target을 다시 열면 이 세션에서 마지막으로 쓴 정지 화면을 보인다
// - 미리보기: 사양·영역·정지 화면이 바뀔 때마다 200 ms 디바운스로 target.preview. 요청마다 seq를 올리고
//   마지막으로 보낸 seq의 응답만 쓴다 (검수 M5). 새로 고른 영역은 template.crop, 고르지 않았으면 기존 이미지
//   template.image (target 기준 경로 + base_path)
// - 저장: target.save {path, spec, crop?, base_revision}. 새 파일은 base_revision null, 기존 파일은 열 때의
//   합친 revision. 영역을 새로 고르지 않았으면 crop 없이 JSON만 저장한다 (T6 계약). 저장 뒤 다시 열어 디스크
//   사양·revision·이미지로 맞춘다. 충돌이면 띠를 띄우고 기존 target은 그대로다 (2.9 "실패한 저장은 기존 target을
//   바꾸지 않는다")
// - 속성 편집기 "새 대상 만들기"로 연 새 target은 저장되면 그 핀에 {"$target": 경로}를 넣는다 (2.9 "그래프와 연결")
// - 늦게 오는 응답 (T12 검수 1차): 응답은 요청 때 적어 둔 세대(store/generations.ts)가 그대로일 때만 쓴다.
//   edits = 사용자 편집 수, reloadSeq = 다시 열기 요청 번호, frameGen = 정지 화면 세대(고르기·만료마다 오름),
//   previewSeq = 미리보기 요청 번호. 그래프 문서 표(store/documents.ts)와 같은 방식이다
import type { daemonRpc } from "@kookabug/schema";
import { create } from "zustand";
import { setNodeValue } from "../graph/commands/setPin";
import { isObject } from "../graph/model";
import { getIn, jsonEqual } from "../graph/valueOps";
import { client, toRpcError, type RpcError } from "../rpc/client";
import type { FrameHost } from "../rpc/recovery";
import { editsLocked } from "../store/dialog";
import { applySystemEdit, getDoc } from "../store/documents";
import { sameStamp, stampOf } from "../store/generations";
import { useTabs } from "../store/tabs";
import { containsRect, type Rect } from "./geometry";
import { newSpec, rebaseSpec, type TargetSpec } from "./spec";

export type Frame = daemonRpc.Frame;
export type PreviewResult = daemonRpc.PreviewResult;
export type ImageRef = daemonRpc.ImageRef;
export type Diagnostic = daemonRpc.Diagnostic;

export const PREVIEW_DEBOUNCE_MS = 200;

/** 새 target을 만든 그래프 핀 (저장되면 그 핀에 $target을 넣는다) */
export interface TargetOrigin {
  graph: string;
  node: string;
  pin: string;
  /**
   * "새 대상 만들기"를 누를 때의 그 핀 값 (없으면 undefined). 채우기를 미뤘다가 다시 할 때, 그사이 사용자가 핀을
   * 다른 값으로 바꿨으면 덮어쓰지 않는다 (T12 검수 2차 Mid 1)
   */
  previous?: unknown;
}

/** 정지 화면 요청 결과: 썼음 · 실패(이유) · 더 새 요청이 있어 버림 */
export type FrameOutcome = { kind: "ok" } | { kind: "error"; message: string } | { kind: "superseded" };

/** 저장 직후 결과 ("바로 매칭") */
export interface SavedNote {
  preview: PreviewResult | null;
  warnings: string[];
  wroteImage: string;
}

export interface TargetDoc {
  path: string;
  instance: number;
  status: "loading" | "ready" | "error";
  /** 열지 못함 (JSON 오류·없음) */
  error: string | null;
  /** 아직 디스크에 없는 새 target */
  isNew: boolean;
  /** 열거나 저장한 때의 합친 revision (새 파일이면 null) */
  baseRevision: string | null;
  /** 디스크 사양 (dirty 기준, 배율 다시 켜기 기준) */
  savedSpec: TargetSpec | null;
  spec: TargetSpec;
  /** 지금 target 이미지 (워크스페이스 파일) */
  image: ImageRef | null;
  diagnostics: Diagnostic[];
  frame: Frame | null;
  /** 정지 화면 출처 (창 제목·이미지 경로) */
  frameSource: string | null;
  /** 정지 화면이 사라짐 (daemon 교체·캐시에서 밀려남): "정지 화면을 다시 고르세요" */
  frameExpired: boolean;
  /** 정지 화면 세대: 고르거나 만료될 때마다 오른다. 옛 정지 화면에 대한 응답은 버린다 */
  frameGen: number;
  /** 정지 화면 요청 번호 (캡처·이미지 열기를 보낼 때마다 오름). 마지막 요청의 응답만 쓴다 */
  frameRequest: number;
  /** 마지막 정지 화면 요청을 기다리는 중 */
  frameLoading: boolean;
  /** 새로 고른 템플릿 영역 (정지 화면 픽셀). null이면 기존 이미지 */
  template: Rect | null;
  preview: PreviewResult | null;
  /** 미리보기를 보낼 수 없거나 실패한 이유 */
  previewNote: string | null;
  previewSeq: number;
  previewPending: boolean;
  /** 사용자 편집 수 (사양·영역). 다시 열기 응답이 그사이 편집을 덮지 않게 본다 */
  edits: number;
  /** 디스크에서 다시 열기 요청 번호. 더 새 요청이 있으면 옛 응답은 버린다 */
  reloadSeq: number;
  /** 저장 중 (저장 뒤 다시 열기까지) */
  saving: boolean;
  /** 저장 충돌 (그때 디스크 revision. 파일이 없어졌으면 "") */
  conflict: string | null;
  saveError: string | null;
  saved: SavedNote | null;
  /** 성공한 저장 수 (E2E가 저장 끝을 기다린다) */
  saves: number;
  /** 저장되면 채울 그래프 핀. 채운 뒤에야 지운다 */
  origin: TargetOrigin | null;
}

interface TargetsState {
  docs: ReadonlyMap<string, TargetDoc>;
}

export const useTargets = create<TargetsState>(() => ({ docs: new Map() }));

let nextInstance = 0;
const timers = new Map<string, ReturnType<typeof setTimeout>>();
/** target 경로 → 이 세션에서 마지막으로 쓴 정지 화면 (다시 열 때 보인다) */
const lastFrames = new Map<string, { frame: Frame; source: string }>();

export function getTarget(path: string): TargetDoc | undefined {
  return useTargets.getState().docs.get(path);
}

function update(path: string, patch: (doc: TargetDoc) => Partial<TargetDoc> | null, instance?: number): void {
  useTargets.setState((s) => {
    const doc = s.docs.get(path);
    if (doc === undefined || (instance !== undefined && doc.instance !== instance)) return s;
    const p = patch(doc);
    if (p === null) return s;
    return { docs: new Map(s.docs).set(path, { ...doc, ...p }) };
  });
}

function emptyDoc(path: string, isNew: boolean, origin: TargetOrigin | null): TargetDoc {
  const last = lastFrames.get(path) ?? null;
  return {
    path,
    instance: ++nextInstance,
    status: isNew ? "ready" : "loading",
    error: null,
    isNew,
    baseRevision: null,
    savedSpec: null,
    spec: newSpec(),
    image: null,
    diagnostics: [],
    frame: last?.frame ?? null,
    frameSource: last?.source ?? null,
    frameExpired: false,
    frameGen: 0,
    frameRequest: 0,
    frameLoading: false,
    template: null,
    preview: null,
    previewNote: null,
    previewSeq: 0,
    previewPending: false,
    edits: 0,
    reloadSeq: 0,
    saving: false,
    conflict: null,
    saveError: null,
    saved: null,
    saves: 0,
    origin,
  };
}

/** 저장 안 된 편집이 있는가: 새 파일, 새로 고른 영역, 디스크와 다른 사양 */
export function targetDirty(doc: TargetDoc | undefined): boolean {
  if (doc === undefined || doc.status !== "ready") return false;
  return doc.isNew || doc.template !== null || !jsonEqual(doc.spec, doc.savedSpec);
}

export function dirtyTargets(): TargetDoc[] {
  return [...useTargets.getState().docs.values()].filter((d) => targetDirty(d));
}

function errorText(err: RpcError): string {
  const d = (err.data ?? {}) as { message?: unknown; diagnostics?: unknown };
  if (Array.isArray(d.diagnostics) && d.diagnostics.length > 0) {
    const first = d.diagnostics[0] as { message?: unknown };
    if (typeof first.message === "string") return first.message;
  }
  if (err.kind === "not_connected") return "daemon에 연결되어 있지 않아요";
  return typeof d.message === "string" ? d.message : err.message;
}

// ── 열기 ────────────────────────────────────────────────────────

type OpenResult = daemonRpc.TargetOpenResult;

function opened(result: OpenResult): Partial<TargetDoc> {
  return {
    status: "ready",
    error: null,
    isNew: false,
    baseRevision: result.revision,
    savedSpec: result.spec,
    spec: result.spec,
    image: result.image,
    diagnostics: result.diagnostics,
    conflict: null,
  };
}

async function openTarget(path: string): Promise<void> {
  if (getTarget(path) !== undefined) return;
  const doc = emptyDoc(path, false, null);
  useTargets.setState((s) => ({ docs: new Map(s.docs).set(path, doc) }));
  try {
    const result = await client().call("target.open", { path });
    update(path, () => opened(result), doc.instance);
    requestPreview(path, 0);
  } catch (err) {
    const error = toRpcError(err);
    update(path, () => ({ status: "error", error: `열지 못했어요: ${errorText(error)}` }), doc.instance);
  }
}

/**
 * 디스크 버전을 다시 연다 (편집을 버린다). 요청한 때의 버퍼만 버린다: 응답을 기다리는 동안 사양·영역을
 * 고쳤거나 저장이 시작됐으면 그 편집을 두고, 디스크가 기준과 다르면 충돌 띠로 바꾼다. 더 새 다시 열기 요청이
 * 있으면 이 응답은 버린다 (그래프 문서 reloadDoc과 같은 규칙, T12 검수 1차 High 2)
 */
export async function reloadTarget(path: string): Promise<void> {
  const doc = getTarget(path);
  if (doc === undefined || doc.isNew) return;
  const seq = doc.reloadSeq + 1;
  update(path, () => ({ reloadSeq: seq }), doc.instance);
  const request = stampOf({ instance: doc.instance, reloadSeq: seq }, ["instance", "reloadSeq"]);
  const edits = doc.edits;
  let result: OpenResult;
  try {
    result = await client().call("target.open", { path });
  } catch (err) {
    const d = getTarget(path);
    if (sameStamp(d, request)) update(path, () => ({ saveError: `다시 열지 못했어요: ${errorText(toRpcError(err))}` }), doc.instance);
    return;
  }
  const d = getTarget(path);
  if (!sameStamp(d, request)) return;
  if (d.edits !== edits || d.saving) {
    // 기다리는 동안 생긴 편집은 지우지 않는다: 기준 revision은 그대로라 저장하면 충돌로 묻는다
    if (result.revision !== d.baseRevision) update(path, () => ({ conflict: result.revision }), doc.instance);
    return;
  }
  update(path, () => ({ ...opened(result), template: null, saveError: null }), doc.instance);
  requestPreview(path, 0);
}

/**
 * 새 target 문서를 만든다 (탭은 부르는 쪽이 연다). origin이 있으면 지금 그 핀 값을 previous로 적어 둔다
 * (채우기를 미뤘을 때 사용자의 새 값을 덮어쓰지 않으려고)
 */
export function createTargetDoc(path: string, origin: TargetOrigin | null): void {
  const withPrevious =
    origin === null || Object.hasOwn(origin, "previous")
      ? origin
      : { ...origin, previous: getIn(getDoc(origin.graph)?.value, ["nodes", origin.node, "in", origin.pin]) };
  useTargets.setState((s) => {
    if (s.docs.has(path)) return s;
    return { docs: new Map(s.docs).set(path, emptyDoc(path, true, withPrevious)) };
  });
}

function clearTimer(path: string): void {
  const timer = timers.get(path);
  if (timer !== undefined) clearTimeout(timer);
  timers.delete(path);
}

function closeTarget(path: string): void {
  clearTimer(path);
  useTargets.setState((s) => {
    const docs = new Map(s.docs);
    docs.delete(path);
    return { docs };
  });
}

/** 프로젝트가 바뀜 */
export function resetTargets(): void {
  for (const t of timers.values()) clearTimeout(t);
  timers.clear();
  lastFrames.clear();
  useTargets.setState({ docs: new Map() });
}

/**
 * 바깥(탐색기·다른 도구)에서 target 파일이 바뀜: 편집하지 않은 문서는 조용히 다시 연다. 응답을 기다리는 동안
 * 편집이 생기면 reloadTarget이 편집을 두고 충돌 띠로 바꾼다
 */
export function onWorkspaceChanged(paths: readonly string[]): void {
  for (const doc of useTargets.getState().docs.values()) {
    if (doc.status !== "ready" || doc.isNew || doc.saving || targetDirty(doc)) continue;
    if (paths.length === 0 || paths.some((p) => p === doc.path)) void reloadTarget(doc.path);
  }
}

// ── 정지 화면 ───────────────────────────────────────────────────

/** 정지 화면을 바꾼다. 세대를 올려 옛 정지 화면에 대한 미리보기 응답을 버린다 */
function adoptFrame(path: string, frame: Frame, source: string, instance: number): void {
  lastFrames.set(path, { frame, source });
  update(
    path,
    (d) => ({
      frame,
      frameSource: source,
      frameExpired: false,
      frameGen: d.frameGen + 1,
      frameLoading: false,
      previewSeq: d.previewSeq + 1,
      previewPending: false,
      preview: null,
      previewNote: null,
      // 고른 영역이 새 정지 화면 안에 있으면 둔다 (같은 크기 창을 다시 찍은 경우)
      template: d.template !== null && containsRect([frame.width, frame.height], d.template) ? d.template : null,
    }),
    instance,
  );
  requestPreview(path, 0);
}

/**
 * 정지 화면 요청 (캡처·이미지). 마지막으로 보낸 요청의 응답만 쓴다: 연속으로 고르면 응답 순서와 무관하게 나중에
 * 고른 것이 남는다 (요청 번호 frameRequest, T12 검수 2차 Mid 2). 기다리는 동안 문서가 바뀌었거나 daemon이 바뀌어
 * 정지 화면이 만료됐으면(frameGen) 쓰지 않는다
 */
async function fetchFrame(path: string, load: () => Promise<Frame>, source: string, failure: string): Promise<FrameOutcome> {
  const doc = getTarget(path);
  if (doc === undefined) return { kind: "superseded" };
  const number = doc.frameRequest + 1;
  update(path, () => ({ frameRequest: number, frameLoading: true }), doc.instance);
  const request = stampOf({ instance: doc.instance, frameRequest: number, frameGen: doc.frameGen }, ["instance", "frameRequest", "frameGen"]);
  let frame: Frame;
  try {
    frame = await load();
  } catch (err) {
    const d = getTarget(path);
    if (d === undefined || d.instance !== doc.instance || d.frameRequest !== number) return { kind: "superseded" };
    update(path, () => ({ frameLoading: false }), doc.instance);
    return { kind: "error", message: `${failure}: ${errorText(toRpcError(err))}` };
  }
  const d = getTarget(path);
  if (d === undefined || d.instance !== doc.instance || d.frameRequest !== number) return { kind: "superseded" };
  if (!sameStamp(d, request)) {
    update(path, () => ({ frameLoading: false }), doc.instance);
    return { kind: "error", message: "그사이 daemon이 바뀌어 정지 화면이 만료됐어요. 다시 고르세요" };
  }
  adoptFrame(path, frame, source, doc.instance);
  return { kind: "ok" };
}

export function captureWindow(path: string, handle: number, title: string): Promise<FrameOutcome> {
  return fetchFrame(path, () => client().call("target.capture", { window: handle }), title, "캡처하지 못했어요");
}

export function loadImageFrame(path: string, image: string): Promise<FrameOutcome> {
  return fetchFrame(path, () => client().call("target.load_image", { path: image }), image, "이미지를 열지 못했어요");
}

/** 정지 화면 만료: 세대·미리보기 번호를 올려 보낸 요청의 응답이 다시 결과를 보이지 않게 한다 (검수 1차 Mid 2) */
function expired(d: TargetDoc): Partial<TargetDoc> {
  return {
    frame: null,
    frameExpired: true,
    frameGen: d.frameGen + 1,
    frameLoading: false,
    previewSeq: d.previewSeq + 1,
    previewPending: false,
    preview: null,
    previewNote: null,
  };
}

function expire(path: string): void {
  lastFrames.delete(path);
  clearTimer(path);
  update(path, expired);
}

/** daemon이 바뀜: 옛 frame_id는 전부 만료 (편집 중인 사양·영역은 둔다, 2.3 6) */
export const framesHost: FrameHost = {
  expireAll() {
    lastFrames.clear();
    for (const path of useTargets.getState().docs.keys()) {
      clearTimer(path);
      // 정지 화면이 아직 없어도 세대는 올린다: 교체 전에 보낸 첫 정지 화면 요청의 응답도 옛 daemon 것이다
      update(path, (d) => (d.frame === null && !d.previewPending ? { frameGen: d.frameGen + 1, frameLoading: false } : expired(d)));
    }
  },
};

// ── 편집 ────────────────────────────────────────────────────────

/**
 * 사양을 고친다 (같은 값이면 아무것도 하지 않는다). 대화 상자·"저장하고 닫기" 중에는 고치지 않는다
 * (store/dialog 편집 잠금, 그래프와 같다)
 */
export function editSpec(path: string, fn: (spec: TargetSpec) => TargetSpec): void {
  const doc = getTarget(path);
  if (doc === undefined || doc.status !== "ready" || editsLocked()) return;
  const next = fn(doc.spec);
  if (next === doc.spec) return;
  update(path, (d) => ({ spec: next, edits: d.edits + 1 }), doc.instance);
  requestPreview(path);
}

export function setTemplate(path: string, rect: Rect | null): void {
  const doc = getTarget(path);
  if (doc === undefined || doc.status !== "ready" || doc.frame === null || editsLocked()) return;
  if (rect !== null && !containsRect([doc.frame.width, doc.frame.height], rect)) return;
  update(path, (d) => ({ template: rect, edits: d.edits + 1 }), doc.instance);
  requestPreview(path);
}

// ── 미리보기 ────────────────────────────────────────────────────

/** 보낼 미리보기 요청. 보낼 수 없으면 이유 */
export function previewRequest(
  doc: Pick<TargetDoc, "frame" | "template" | "spec" | "isNew" | "path" | "image">,
): { params: Omit<daemonRpc.TargetPreviewParams, "seq"> } | { note: string } {
  if (doc.frame === null) return { note: "정지 화면을 고르세요" };
  if (doc.template !== null) {
    return {
      params: { frame_id: doc.frame.frame_id, spec: doc.spec, template: { crop: { frame_id: doc.frame.frame_id, rect: doc.template } } },
    };
  }
  const image = doc.spec.image;
  if (doc.isNew || typeof image !== "string" || doc.image === null) {
    return { note: "정지 화면에서 찾을 영역을 드래그하세요" };
  }
  return { params: { frame_id: doc.frame.frame_id, spec: doc.spec, template: { image }, base_path: doc.path } };
}

async function previewNow(path: string): Promise<void> {
  const doc = getTarget(path);
  // 저장 중에는 보내지 않는다: 저장·다시 열기가 끝나면 디스크 사양으로 한 번 보낸다
  if (doc === undefined || doc.status !== "ready" || doc.saving) return;
  const request = previewRequest(doc);
  if ("note" in request) {
    update(path, () => ({ preview: null, previewNote: request.note, previewPending: false }), doc.instance);
    return;
  }
  const seq = doc.previewSeq + 1;
  update(path, () => ({ previewSeq: seq, previewPending: true }), doc.instance);
  // 늦게 온 옛 응답은 새 선택을 덮지 않는다. 그사이 정지 화면이 바뀌었거나 만료됐으면(daemon 교체) 버린다
  const stamp = stampOf({ instance: doc.instance, previewSeq: seq, frameGen: doc.frameGen }, ["instance", "previewSeq", "frameGen"]);
  try {
    const result = await client().call("target.preview", { ...request.params, seq });
    update(path, (d) => (sameStamp(d, stamp) && result.seq === seq ? { preview: result, previewNote: null, previewPending: false } : null));
  } catch (err) {
    const error = toRpcError(err);
    if (!sameStamp(getTarget(path), stamp)) return;
    if (error.kind === "frame_expired") {
      expire(path);
      return;
    }
    update(path, (d) => (sameStamp(d, stamp) ? { preview: null, previewNote: `찾지 못했어요: ${errorText(error)}`, previewPending: false } : null));
  }
}

export function requestPreview(path: string, delay = PREVIEW_DEBOUNCE_MS): void {
  clearTimer(path);
  timers.set(
    path,
    setTimeout(() => {
      timers.delete(path);
      void previewNow(path);
    }, delay),
  );
}

/** 결과 문구 (검수 M6): "찾음 · 점수 0.93 · 배율 1.00" 또는 "못 찾음 · 최고 점수 0.61" */
export function previewSummary(result: PreviewResult): string {
  if (result.found && result.match !== null) {
    return `찾음 · 점수 ${result.match.score.toFixed(2)} · 배율 ${result.match.scale.toFixed(2)}`;
  }
  const best = result.best as { score?: unknown } | null;
  const score = typeof best?.score === "number" ? best.score.toFixed(2) : "—";
  return `못 찾음 · 최고 점수 ${score}`;
}

/** 같은 모양의 다른 자리 (찾은 상자 말고 임계값 이상인 봉우리, daemon peaks) — 정지 화면에 점선 상자 */
export function otherPeaks(preview: PreviewResult | null): Rect[] {
  const match = preview?.found === true ? preview.match : null;
  if (preview === null || match === null || match === undefined) return [];
  const key = (match.rect as number[]).join(",");
  return (preview.peaks ?? []).map((p) => p.rect as Rect).filter((r) => r.join(",") !== key);
}

/** "같은 모양 N곳" (찾은 자리 포함, daemon peaks). 찾지 못했거나 세지 않았으면 null (M4 T11) */
export function sameShapeCount(result: PreviewResult): number | null {
  if (!result.found || result.peaks === undefined) return null;
  return Math.max(1, result.peaks.length);
}

// ── 저장 ────────────────────────────────────────────────────────

export type TargetSaveOutcome = "saved" | "conflict" | "failed" | "busy";

/** 저장할 수 없는 이유 (버튼 옆 문구). 저장할 수 있으면 null */
export function saveBlocker(doc: TargetDoc): string | null {
  if (doc.status !== "ready") return "열리지 않았어요";
  if (doc.isNew && doc.template === null) return "정지 화면에서 영역을 드래그하세요";
  if (doc.template !== null && doc.frame === null) return "정지 화면을 다시 고르세요";
  return null;
}

/**
 * 저장한다. force는 충돌 띠의 "내 편집으로 덮어쓰기" (기준 revision을 지금 디스크 것으로 바꿔 보낸다).
 * 저장 뒤 디스크 사양을 다시 읽어, 저장을 기다리는 동안 사용자가 바꾼 것만 그 위에 얹는다 (rebaseSpec,
 * 검수 1차 Mid 1). 새 target을 만든 그래프 핀은 저장이 성공하면 채우고, 채운 뒤에야 origin을 지운다 (High 1)
 */
export async function saveTarget(path: string, options: { force?: boolean } = {}): Promise<TargetSaveOutcome> {
  const doc = getTarget(path);
  if (doc === undefined) return "failed";
  if (doc.saving) return "busy";
  const blocked = saveBlocker(doc);
  if (blocked !== null) {
    update(path, () => ({ saveError: `저장하지 못했어요: ${blocked}` }), doc.instance);
    return "failed";
  }
  const base = doc.isNew ? null : options.force === true && doc.conflict !== null && doc.conflict !== "" ? doc.conflict : doc.baseRevision;
  const crop = doc.template !== null && doc.frame !== null ? { frame_id: doc.frame.frame_id, rect: doc.template } : undefined;
  const spec = doc.spec;
  const template = doc.template;
  update(path, () => ({ saving: true, saveError: null, saved: null }), doc.instance);
  let result: daemonRpc.TargetSaveResult;
  try {
    result = await client().call("target.save", {
      path,
      spec,
      base_revision: base,
      ...(crop === undefined ? {} : { crop }),
    });
  } catch (err) {
    const error = toRpcError(err);
    if (error.kind === "revision_conflict") {
      const disk = (error.data as { revision?: unknown } | undefined)?.revision;
      update(path, () => ({ saving: false, conflict: typeof disk === "string" ? disk : "" }), doc.instance);
      requestPreview(path, 0);
      return "conflict";
    }
    if (error.kind === "frame_expired") expire(path);
    const kept = doc.isNew ? "" : " 기존 대상 파일은 그대로예요.";
    const text = error.kind === "exists" ? `'${path}'이(가) 이미 있어요` : errorText(error);
    update(path, () => ({ saving: false, saveError: `저장하지 못했어요: ${text}.${kept}` }), doc.instance);
    requestPreview(path, 0);
    return "failed";
  }
  const warnings = [...result.warnings];
  // 새 target을 만든 핀 채우기 (사용자 편집 잠금과 무관하다: "모두 저장" 중에도 채운다)
  const origin = getTarget(path)?.origin ?? null;
  const link = origin === null ? null : fillOrigin(origin, path);
  if (link !== null && link.warning !== null) warnings.push(link.warning);
  const filled = link === null || link.state !== "pending";
  // 디스크 사양(이미지 이름·recorded·맞춘 검색 범위)을 다시 읽는다
  let reopened: OpenResult | null = null;
  try {
    reopened = await client().call("target.open", { path });
  } catch (err) {
    warnings.push(`저장한 대상을 다시 읽지 못했어요: ${errorText(toRpcError(err))}`);
  }
  update(
    path,
    (d) => ({
      saving: false,
      saves: d.saves + 1,
      isNew: false,
      conflict: null,
      saveError: null,
      saved: { preview: result.preview, warnings, wroteImage: result.image },
      origin: filled ? null : d.origin,
      // 저장한 영역은 이제 target 이미지다 (그사이 다른 영역을 골랐으면 그것은 둔다)
      template: d.template === template ? null : d.template,
      ...(reopened === null
        ? { baseRevision: result.revision, savedSpec: spec }
        : {
            baseRevision: reopened.revision,
            savedSpec: reopened.spec,
            spec: d.spec === spec ? reopened.spec : rebaseSpec(spec, d.spec, reopened.spec),
            image: reopened.image,
            diagnostics: reopened.diagnostics,
          }),
    }),
    doc.instance,
  );
  requestPreview(path, 0);
  return "saved";
}

/**
 * 새 대상을 만든 그래프 핀에 {"$target": 경로}를 넣는다. "값을 바꿨는가"와 "연결이 끝났는가"를 나눈다
 * (T12 검수 2차 Mid 1): 핀이 이미 그 참조면 바꿀 것 없이 끝난 것이다.
 * - done: 핀이 그 참조다 (넣었거나 이미 그랬음) → origin을 지운다
 * - pending: 그래프가 열려 있지 않다 → origin을 두고 다음 저장에서 다시 한다
 * - dropped: 노드가 없어졌거나, 그사이 사용자가 핀을 다른 값으로 바꿨다 → 덮어쓰지 않고 origin을 지운다
 */
export function fillOrigin(origin: TargetOrigin, path: string): { state: "done" | "pending" | "dropped"; warning: string | null } {
  const ref = { $target: path };
  const pinPath = ["nodes", origin.node, "in", origin.pin];
  const doc = getDoc(origin.graph);
  if (doc === undefined || doc.status !== "ready" || doc.value === null) {
    return { state: "pending", warning: `'${origin.graph}'가 열려 있지 않아 대상 칸을 채우지 못했어요. 그 그래프를 열고 다시 저장하면 채워요` };
  }
  if (!isObject(getIn(doc.value, ["nodes", origin.node]))) {
    return { state: "dropped", warning: `'${origin.graph}'에 노드 '${origin.node}'가 없어 대상 칸을 채우지 않았어요` };
  }
  const current = getIn(doc.value, pinPath);
  if (jsonEqual(current, ref)) return { state: "done", warning: null };
  if (!jsonEqual(current, origin.previous)) {
    return { state: "dropped", warning: `'${origin.node}.${origin.pin}'이(가) 그사이 다른 값으로 바뀌어 덮어쓰지 않았어요` };
  }
  applySystemEdit(origin.graph, (v) => setNodeValue(v, origin.node, "in", origin.pin, ref));
  const after = getDoc(origin.graph)?.value;
  return jsonEqual(getIn(after, pinPath), ref)
    ? { state: "done", warning: null }
    : { state: "pending", warning: `'${origin.graph}'의 대상 칸을 채우지 못했어요` };
}

export function dismissTargetConflict(path: string): void {
  update(path, () => ({ conflict: null }));
}

export function dismissTargetError(path: string): void {
  update(path, () => ({ saveError: null }));
}

export function dismissSaved(path: string): void {
  update(path, () => ({ saved: null }));
}

// 탭이 열리고 닫히는 것을 따라 문서를 열고 닫는다
useTabs.subscribe((state) => {
  const targetTabs = new Set(state.tabs.filter((t) => t.kind === "target").map((t) => t.path));
  for (const path of targetTabs) if (getTarget(path) === undefined) void openTarget(path);
  for (const path of useTargets.getState().docs.keys()) if (!targetTabs.has(path)) closeTarget(path);
});
