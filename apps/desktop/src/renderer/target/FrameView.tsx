// 정지 화면 판 (M2 계획 2.9 "조작"): 드래그 = 템플릿 영역, Shift+드래그 = 검색 범위, 클릭 = 클릭 지점,
// 휠 = 확대·축소, 가운데 버튼 = 이동, 핸들 = 크기 고치기, 방향키 1px·Shift+방향키 10px.
// 좌표는 정지 화면의 물리 픽셀이다 (geometry.ts). 겹쳐 그리기는 화면 좌표 SVG라 확대해도 선 굵기가 그대로다.
// 매칭 결과(찾은 상자·점수·최고 후보·클릭 지점)는 daemon 응답 그대로 그린다
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import {
  clickPoint,
  clientToImageRect,
  fitView,
  gestureKind,
  HANDLES,
  handlePoint,
  imageToClientRect,
  imageToScreen,
  nudge,
  pan,
  pixelAt,
  pixelsToRegion,
  rectFromDrag,
  resizeRect,
  screenToImage,
  normalizedToPixels,
  offsetFromClick,
  zoomAt,
  type Handle,
  type Pt,
  type Rect,
  type Size,
  type View,
} from "./geometry";
import { setOffset, setRegion, specFields } from "./spec";
import css from "./target.module.css";
import { editSpec, setTemplate, useTargets, type TargetDoc } from "./targetStore";

type Focus = "template" | "search";

type Drag =
  | { kind: "select"; start: Pt; startImg: Pt; shift: boolean; now: Pt }
  | { kind: "resize"; which: Focus; handle: Handle; rect: Rect }
  | { kind: "pan"; last: Pt };

function imageUrl(doc: TargetDoc): { url: string; size: Size } | null {
  if (doc.frame !== null) {
    const ref = doc.frame.image;
    if ("cache" in ref) return { url: `kbimg://cache/${ref.cache}`, size: [doc.frame.width, doc.frame.height] };
    return { url: `kbimg://ws/${ref.workspace.split("/").map(encodeURIComponent).join("/")}`, size: [doc.frame.width, doc.frame.height] };
  }
  const img = doc.image;
  if (img !== null && "workspace" in img) {
    return { url: `kbimg://ws/${img.workspace.split("/").map(encodeURIComponent).join("/")}`, size: [img.width, img.height] };
  }
  return null;
}

/** 검색 범위 (정지 화면 픽셀). 사양에 없으면 null (화면 전체) */
export function searchRectOf(doc: TargetDoc): Rect | null {
  const region = specFields(doc.spec).region;
  if (region === null || doc.frame === null) return null;
  const client = doc.frame.client_size as Size;
  return clientToImageRect(normalizedToPixels(region, client), [doc.frame.width, doc.frame.height], client);
}

/** 클릭 지점을 정할 기준 상자와 배율: 새로 고른 영역, 아니면 찾은 상자 */
function clickBase(doc: TargetDoc): { rect: Rect; scale: number } | null {
  if (doc.template !== null) return { rect: doc.template, scale: 1 };
  const m = doc.preview?.match;
  if (doc.preview?.found === true && m !== null && m !== undefined) return { rect: m.rect as Rect, scale: m.scale };
  return null;
}

/** 보일 클릭 지점: 새 영역이면 바로 계산, 아니면 찾은 결과의 클릭 지점 */
function shownClick(doc: TargetDoc): Pt | null {
  const f = specFields(doc.spec);
  if (doc.template !== null) return clickPoint(doc.template, f.anchor, f.offset);
  const m = doc.preview?.match;
  if (doc.preview?.found === true && m !== null && m !== undefined) return { x: m.click[0], y: m.click[1] };
  return null;
}

function rectPath(rect: Rect, view: View): { x: number; y: number; width: number; height: number } {
  const a = imageToScreen({ x: rect[0], y: rect[1] }, view);
  return { x: a.x, y: a.y, width: rect[2] * view.zoom, height: rect[3] * view.zoom };
}

export function FrameView({ doc }: { doc: TargetDoc }) {
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<Size>([0, 0]);
  const [view, setView] = useState<View | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [focus, setFocus] = useState<Focus>("template");
  const shown = imageUrl(doc);
  const imageSize = shown?.size ?? null;
  const fitKey = doc.frame?.frame_id ?? (shown === null ? "" : shown.url);
  const interactive = doc.frame !== null && doc.status === "ready";

  useLayoutEffect(() => {
    const el = box.current;
    if (el === null) return;
    const measure = () => setSize([el.clientWidth, el.clientHeight]);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  // 정지 화면이 바뀌거나 판 크기가 처음 정해지면 전체가 보이게 맞춘다
  const fittedFor = useRef<string>("");
  useEffect(() => {
    if (imageSize === null || size[0] === 0 || size[1] === 0) return;
    const key = `${fitKey}|${size[0]}x${size[1]}`;
    if (fittedFor.current === key) return;
    fittedFor.current = key;
    setView(fitView(imageSize, size));
  }, [fitKey, imageSize, size]);

  // 판 안쪽(테두리 안) 기준 좌표: 이미지·겹쳐 그리기가 그 기준으로 놓인다
  const local = useCallback((e: { clientX: number; clientY: number }): Pt => {
    const el = box.current;
    const r = el?.getBoundingClientRect();
    return { x: e.clientX - (r?.left ?? 0) - (el?.clientLeft ?? 0), y: e.clientY - (r?.top ?? 0) - (el?.clientTop ?? 0) };
  }, []);

  // 휠: 확대·축소 (passive가 아니어야 기본 스크롤을 막는다)
  useEffect(() => {
    const el = box.current;
    if (el === null) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const p = local(e);
      setView((v) => (v === null ? v : zoomAt(v, Math.pow(1.0015, -e.deltaY), p)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [local]);

  const frameSize: Size | null = doc.frame === null ? null : [doc.frame.width, doc.frame.height];
  const search = searchRectOf(doc);

  const commitSearch = (rect: Rect | null) => {
    if (doc.frame === null) return;
    const client = doc.frame.client_size as Size;
    const region = rect === null ? null : pixelsToRegion(imageToClientRect(rect, [doc.frame.width, doc.frame.height], client), client);
    editSpec(doc.path, (s) => setRegion(s, region));
  };

  const commitClick = (p: Pt) => {
    const base = clickBase(doc);
    if (base === null) return;
    const f = specFields(doc.spec);
    const raw = offsetFromClick(p, base.rect, f.anchor);
    const offset: [number, number] = [raw[0] / base.scale, raw[1] / base.scale];
    editSpec(doc.path, (s) => setOffset(s, offset));
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (view === null || !interactive) return;
    box.current?.focus();
    const p = local(e);
    if (e.button === 1) {
      e.preventDefault();
      setDrag({ kind: "pan", last: p });
      e.currentTarget.setPointerCapture(e.pointerId);
      return;
    }
    if (e.button !== 0) return;
    const handle = (e.target as Element).closest?.("[data-handle]");
    if (handle !== null && handle !== undefined) {
      const which = handle.getAttribute("data-rect") as Focus;
      const rect = which === "template" ? doc.template : search;
      if (rect !== null) {
        setFocus(which);
        setDrag({ kind: "resize", which, handle: handle.getAttribute("data-handle") as Handle, rect });
        e.currentTarget.setPointerCapture(e.pointerId);
        return;
      }
    }
    setDrag({ kind: "select", start: p, startImg: screenToImage(p, view), shift: e.shiftKey, now: p });
    e.currentTarget.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (drag === null || view === null || frameSize === null) return;
    const p = local(e);
    if (drag.kind === "pan") {
      setView(pan(view, p.x - drag.last.x, p.y - drag.last.y));
      setDrag({ kind: "pan", last: p });
    } else if (drag.kind === "select") {
      setDrag({ ...drag, now: p });
    } else {
      setDrag({ ...drag, rect: resizeRect(drag.rect, drag.handle, screenToImage(p, view), frameSize) });
    }
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag;
    setDrag(null);
    if (d === null || view === null || frameSize === null) return;
    if (d.kind === "resize") {
      if (d.which === "template") setTemplate(doc.path, d.rect);
      else commitSearch(d.rect);
      return;
    }
    if (d.kind !== "select") return;
    const end = local(e);
    const kind = gestureKind(d.start, end, d.shift);
    if (kind === "click") {
      commitClick(pixelAt(screenToImage(end, view), frameSize));
      return;
    }
    const rect = rectFromDrag(d.startImg, screenToImage(end, view), frameSize);
    if (rect === null) return;
    setFocus(kind);
    if (kind === "template") setTemplate(doc.path, rect);
    else commitSearch(rect);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (frameSize === null || !interactive) return;
    const which: Focus = focus === "search" && search !== null ? "search" : "template";
    const rect = which === "template" ? doc.template : search;
    if (rect === null) return;
    const moved = nudge(rect, e.key, e.shiftKey, frameSize);
    if (moved === null) return;
    e.preventDefault();
    if (which === "template") setTemplate(doc.path, moved);
    else commitSearch(moved);
  };

  // 끄는 중에는 바뀔 사각형을 바로 보인다
  const liveTemplate = drag?.kind === "resize" && drag.which === "template" ? drag.rect : doc.template;
  const liveSearch = drag?.kind === "resize" && drag.which === "search" ? drag.rect : search;
  const rubber =
    drag?.kind === "select" && view !== null && frameSize !== null && gestureKind(drag.start, drag.now, drag.shift) !== "click"
      ? rectFromDrag(drag.startImg, screenToImage(drag.now, view), frameSize)
      : null;

  const preview = doc.preview;
  const match = preview?.found === true ? preview.match : null;
  const best = preview !== null && preview.found !== true ? (preview.best as { rect?: unknown; score?: unknown } | null) : null;
  const bestRect = Array.isArray(best?.rect) && best.rect.length === 4 ? (best.rect as Rect) : null;
  const click = shownClick(doc);
  const message = doc.frameExpired
    ? "정지 화면을 다시 고르세요"
    : doc.frame === null && shown !== null
      ? "정지 화면을 고르세요 (지금 보이는 것은 대상 이미지)"
      : null;

  return (
    <div
      ref={box}
      className={css.frame}
      data-part="target-frame"
      data-zoom={view?.zoom ?? ""}
      data-view={view === null ? "" : `${view.x},${view.y},${view.zoom}`}
      data-frame={doc.frame?.frame_id ?? ""}
      tabIndex={0}
      aria-label="정지 화면"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={() => setDrag(null)}
      onKeyDown={onKeyDown}
      onContextMenu={(e) => e.preventDefault()}
      style={{ cursor: drag?.kind === "pan" ? "grabbing" : interactive ? "crosshair" : "default" }}
    >
      {shown !== null && view !== null && (
        <img
          alt=""
          src={shown.url}
          draggable={false}
          className={`${css.frameImage} ${view.zoom >= 2 ? css.pixelated : ""}`}
          style={{ left: view.x, top: view.y, width: shown.size[0] * view.zoom, height: shown.size[1] * view.zoom }}
        />
      )}
      {shown === null && <div className={css.frameEmpty}>창에서 캡처하거나 이미지에서 정지 화면을 고르세요</div>}
      {view !== null && doc.frame !== null && (
        <svg className={css.overlay} aria-hidden="true">
          {liveSearch !== null && (
            <g data-part="search-rect" data-rect={liveSearch.join(",")}>
              <rect className={css.searchRect} {...rectPath(liveSearch, view)} />
              <text className={css.searchLabel} x={rectPath(liveSearch, view).x} y={rectPath(liveSearch, view).y - 4}>
                검색 범위
              </text>
            </g>
          )}
          {bestRect !== null && (
            <g data-part="best-rect" data-rect={bestRect.join(",")}>
              <rect className={css.bestRect} {...rectPath(bestRect, view)} />
              {typeof best?.score === "number" && (
                <text className={css.missText} x={rectPath(bestRect, view).x + rectPath(bestRect, view).width + 4} y={rectPath(bestRect, view).y + 11}>
                  {best.score.toFixed(2)}
                </text>
              )}
            </g>
          )}
          {match !== null && match !== undefined && (
            <g data-part="match-rect" data-rect={(match.rect as number[]).join(",")}>
              <rect className={css.matchRect} {...rectPath(match.rect as Rect, view)} />
              <rect
                className={css.scoreBadge}
                x={rectPath(match.rect as Rect, view).x + rectPath(match.rect as Rect, view).width + 2}
                y={rectPath(match.rect as Rect, view).y}
                width={38}
                height={16}
              />
              <text
                className={css.scoreText}
                data-part="score-badge"
                x={rectPath(match.rect as Rect, view).x + rectPath(match.rect as Rect, view).width + 8}
                y={rectPath(match.rect as Rect, view).y + 12}
              >
                {match.score.toFixed(2)}
              </text>
            </g>
          )}
          {liveTemplate !== null && (
            <rect className={css.templateRect} data-part="template-rect" data-rect={liveTemplate.join(",")} {...rectPath(liveTemplate, view)} />
          )}
          {rubber !== null && <rect className={css.selecting} data-part="rubber" {...rectPath(rubber, view)} />}
          {click !== null && (
            <g data-part="click-point" data-point={`${click.x},${click.y}`}>
              {(() => {
                const c = imageToScreen({ x: click.x + 0.5, y: click.y + 0.5 }, view);
                return <path className={css.cross} d={`M${c.x} ${c.y - 8}v16M${c.x - 8} ${c.y}h16`} />;
              })()}
            </g>
          )}
          {([["template", liveTemplate], ["search", liveSearch]] as const).map(([which, rect]) =>
            rect === null
              ? null
              : HANDLES.map((h) => {
                  const p = imageToScreen(handlePoint(rect, h), view);
                  return (
                    <rect
                      key={`${which}-${h}`}
                      data-handle={h}
                      data-rect={which}
                      className={`${css.handle} ${which === "search" ? css.handleSearch : ""}`}
                      x={p.x - 3.5}
                      y={p.y - 3.5}
                      width={7}
                      height={7}
                      style={{ pointerEvents: "all" }}
                    />
                  );
                }),
          )}
        </svg>
      )}
      {message !== null && (
        <div className={css.frameMessage} data-part="frame-message">
          {message}
        </div>
      )}
    </div>
  );
}

/** 지금 문서 (편집기 안 컴포넌트용) */
export function useTargetDoc(path: string): TargetDoc | undefined {
  return useTargets((s) => s.docs.get(path));
}
