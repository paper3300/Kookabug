// target 편집기의 좌표 계산 (M2 계획 2.9 "조작"). 순수 함수만 둔다 (geometry.test.ts).
// - 좌표는 정지 화면의 **물리 픽셀**이다. 화면 배율·확대와 무관하게 이미지 좌표로 바꾼다
// - 보기(View)는 이미지 (0, 0)이 화면(보기 영역 왼쪽 위 기준)의 어디에 몇 배로 그려지는지다
// - 클릭 지점·정규화 범위 계산은 Python(kookabug_platform)과 같은 식이다: 클릭 = 상자 안 9분할 지점
//   (오른쪽·아래 끝은 x + w - 1) + offset, 정수는 0.5 올림. 정규화 → 픽셀은 네 변을 따로 반올림

export type Rect = [number, number, number, number];
export type Size = [number, number];

export interface Pt {
  x: number;
  y: number;
}

export interface View {
  zoom: number;
  x: number;
  y: number;
}

export const ZOOM_MIN = 0.05;
export const ZOOM_MAX = 32;
/** 이만큼(화면 px) 움직이기 전에는 클릭으로 본다 */
export const DRAG_THRESHOLD = 3;

export const ANCHORS = {
  top_left: [0, 0],
  top: [0.5, 0],
  top_right: [1, 0],
  left: [0, 0.5],
  center: [0.5, 0.5],
  right: [1, 0.5],
  bottom_left: [0, 1],
  bottom: [0.5, 1],
  bottom_right: [1, 1],
} as const satisfies Record<string, readonly [number, number]>;

export type Anchor = keyof typeof ANCHORS;
export const ANCHOR_ORDER: readonly Anchor[] = [
  "top_left",
  "top",
  "top_right",
  "left",
  "center",
  "right",
  "bottom_left",
  "bottom",
  "bottom_right",
];

export function isAnchor(v: unknown): v is Anchor {
  return typeof v === "string" && Object.hasOwn(ANCHORS, v);
}

/** Python round_half_up (0.5는 늘 위로) */
export function roundHalfUp(v: number): number {
  return Math.floor(v + 0.5);
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.min(Math.max(v, lo), hi);
}

// ── 보기 ────────────────────────────────────────────────────────

/** 화면 점 → 이미지 좌표 (실수) */
export function screenToImage(p: Pt, view: View): Pt {
  return { x: (p.x - view.x) / view.zoom, y: (p.y - view.y) / view.zoom };
}

export function imageToScreen(p: Pt, view: View): Pt {
  return { x: view.x + p.x * view.zoom, y: view.y + p.y * view.zoom };
}

/** 이미지 좌표 → 그 점을 담은 픽셀 (이미지 밖이면 끝 픽셀로) */
export function pixelAt(p: Pt, size: Size): Pt {
  return { x: clamp(Math.floor(p.x), 0, size[0] - 1), y: clamp(Math.floor(p.y), 0, size[1] - 1) };
}

/** 이미지 전체가 보이게 가운데 놓는다. 작은 이미지는 1배보다 키우지 않는다 */
export function fitView(image: Size, viewport: Size, pad = 16): View {
  const [w, h] = image;
  const vw = Math.max(1, viewport[0] - pad * 2);
  const vh = Math.max(1, viewport[1] - pad * 2);
  const zoom = clamp(Math.min(vw / Math.max(1, w), vh / Math.max(1, h), 1), ZOOM_MIN, ZOOM_MAX);
  return { zoom, x: (viewport[0] - w * zoom) / 2, y: (viewport[1] - h * zoom) / 2 };
}

/** 화면 점 p 아래의 이미지 점이 그대로 있게 확대·축소 */
export function zoomAt(view: View, factor: number, p: Pt): View {
  const zoom = clamp(view.zoom * factor, ZOOM_MIN, ZOOM_MAX);
  const img = screenToImage(p, view);
  return { zoom, x: p.x - img.x * zoom, y: p.y - img.y * zoom };
}

export function pan(view: View, dx: number, dy: number): View {
  return { ...view, x: view.x + dx, y: view.y + dy };
}

// ── 조작 ────────────────────────────────────────────────────────

export type GestureKind = "click" | "template" | "search";

/** 끌기 = 템플릿 영역, Shift+끌기 = 검색 범위, (거의) 움직이지 않음 = 클릭 지점. 거리는 화면 px */
export function gestureKind(start: Pt, end: Pt, shift: boolean): GestureKind {
  const moved = Math.hypot(end.x - start.x, end.y - start.y) >= DRAG_THRESHOLD;
  if (!moved) return "click";
  return shift ? "search" : "template";
}

/**
 * 끈 두 점(이미지 좌표)이 덮는 픽셀 사각형. 끝점이 있는 픽셀까지 담는다. 이미지 안으로 자르고, 너비·높이가
 * 1보다 작으면 null
 */
export function rectFromDrag(a: Pt, b: Pt, size: Size): Rect | null {
  const [w, h] = size;
  const x0 = clamp(Math.floor(Math.min(a.x, b.x)), 0, w);
  const y0 = clamp(Math.floor(Math.min(a.y, b.y)), 0, h);
  const x1 = clamp(Math.floor(Math.max(a.x, b.x)) + 1, 0, w);
  const y1 = clamp(Math.floor(Math.max(a.y, b.y)) + 1, 0, h);
  if (x1 - x0 < 1 || y1 - y0 < 1) return null;
  return [x0, y0, x1 - x0, y1 - y0];
}

/** 사각형을 옮긴다 (이미지 밖으로 나가지 않게) */
export function moveRect(rect: Rect, dx: number, dy: number, size: Size): Rect {
  const [x, y, w, h] = rect;
  return [clamp(x + dx, 0, Math.max(0, size[0] - w)), clamp(y + dy, 0, Math.max(0, size[1] - h)), w, h];
}

/** 방향키: 1px, Shift면 10px. 방향키가 아니면 null */
export function nudge(rect: Rect, key: string, shift: boolean, size: Size): Rect | null {
  const step = shift ? 10 : 1;
  const d: Record<string, [number, number]> = {
    ArrowLeft: [-step, 0],
    ArrowRight: [step, 0],
    ArrowUp: [0, -step],
    ArrowDown: [0, step],
  };
  const m = d[key];
  if (m === undefined) return null;
  return moveRect(rect, m[0], m[1], size);
}

export type Handle = "n" | "s" | "e" | "w" | "ne" | "nw" | "se" | "sw";
export const HANDLES: readonly Handle[] = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

/** 핸들의 이미지 좌표 (사각형 테두리 위) */
export function handlePoint(rect: Rect, handle: Handle): Pt {
  const [x, y, w, h] = rect;
  const hx = handle.includes("w") ? x : handle.includes("e") ? x + w : x + w / 2;
  const hy = handle.includes("n") ? y : handle.includes("s") ? y + h : y + h / 2;
  return { x: hx, y: hy };
}

/** 핸들을 이미지 점 p로 끌었을 때의 사각형. 반대쪽 변은 그대로이고 너비·높이는 1 이상 */
export function resizeRect(rect: Rect, handle: Handle, p: Pt, size: Size): Rect {
  let x0 = rect[0];
  let y0 = rect[1];
  let x1 = rect[0] + rect[2];
  let y1 = rect[1] + rect[3];
  const px = clamp(Math.round(p.x), 0, size[0]);
  const py = clamp(Math.round(p.y), 0, size[1]);
  if (handle.includes("w")) x0 = Math.min(px, x1 - 1);
  if (handle.includes("e")) x1 = Math.max(px, x0 + 1);
  if (handle.includes("n")) y0 = Math.min(py, y1 - 1);
  if (handle.includes("s")) y1 = Math.max(py, y0 + 1);
  return [x0, y0, x1 - x0, y1 - y0];
}

export function containsRect(outer: Size, rect: Rect): boolean {
  const [x, y, w, h] = rect;
  return x >= 0 && y >= 0 && w >= 1 && h >= 1 && x + w <= outer[0] && y + h <= outer[1];
}

// ── 클릭 지점 ───────────────────────────────────────────────────

/** 상자 안 9분할 지점 (실수, Python click_point의 반올림 전) */
export function anchorPoint(rect: Rect, anchor: Anchor): Pt {
  const [fx, fy] = ANCHORS[anchor];
  const [x, y, w, h] = rect;
  return { x: x + fx * (w - 1), y: y + fy * (h - 1) };
}

/** 클릭 지점 = 9분할 지점 + offset (배율 1). Python click_point와 같은 반올림 */
export function clickPoint(rect: Rect, anchor: Anchor, offset: readonly [number, number]): Pt {
  const a = anchorPoint(rect, anchor);
  return { x: roundHalfUp(a.x + offset[0]), y: roundHalfUp(a.y + offset[1]) };
}

/**
 * 클릭한 픽셀을 고른 anchor 기준 오프셋으로 바꾼다 (템플릿 밖이어도 된다). clickPoint(rect, anchor, 결과)가
 * 그 픽셀이다
 */
export function offsetFromClick(click: Pt, rect: Rect, anchor: Anchor): [number, number] {
  const a = anchorPoint(rect, anchor);
  return [click.x - a.x, click.y - a.y];
}

// ── 정규화 검색 범위 ─────────────────────────────────────────────

/** kookabug_platform.dpi.normalized_to_pixels와 같은 식 (클라이언트 픽셀) */
export function normalizedToPixels(region: readonly number[], client: Size): Rect {
  const [x, y, w, h] = region;
  const [cw, ch] = client;
  const x0 = clamp(roundHalfUp(x * cw), 0, cw);
  const y0 = clamp(roundHalfUp(y * ch), 0, ch);
  const x1 = clamp(roundHalfUp((x + w) * cw), x0, cw);
  const y1 = clamp(roundHalfUp((y + h) * ch), y0, ch);
  return [x0, y0, x1 - x0, y1 - y0];
}

/**
 * 클라이언트 픽셀 사각형 → 정규화 값 (픽셀 / 크기). daemon이 저장할 때 같은 픽셀로 돌아오는 6자리 값으로
 * 다시 맞춘다 (T6 `_snap_region`)
 */
export function pixelsToRegion(rect: Rect, client: Size): [number, number, number, number] {
  return [rect[0] / client[0], rect[1] / client[1], rect[2] / client[0], rect[3] / client[1]];
}

/** 정지 화면 이미지 픽셀 ↔ 클라이언트 픽셀 (보통 같다. 다르면 비율로) */
export function imageToClientRect(rect: Rect, image: Size, client: Size): Rect {
  if (image[0] === client[0] && image[1] === client[1]) return rect;
  const sx = client[0] / image[0];
  const sy = client[1] / image[1];
  const x0 = Math.round(rect[0] * sx);
  const y0 = Math.round(rect[1] * sy);
  return [x0, y0, Math.max(1, Math.round((rect[0] + rect[2]) * sx) - x0), Math.max(1, Math.round((rect[1] + rect[3]) * sy) - y0)];
}

export function clientToImageRect(rect: Rect, image: Size, client: Size): Rect {
  return imageToClientRect(rect, client, image);
}
