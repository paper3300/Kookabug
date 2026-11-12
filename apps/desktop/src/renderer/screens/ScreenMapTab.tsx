// 화면 지도 탭 (M7 계획 3.14, 시안 ScreenMap): 위 줄 범례(있는 출처만)·요약, 점 격자 위 카드와 이동 간선
// (가 본 이동 실선·안 가 본 이동 점선 "아직 안 가 봄"·합치기 후보 이동 보라 점선·실행 기록 주황), 선택 카드에
// 걸린 간선은 파랑. 카드를 끌면 자리를 기억한다(.kookabug/screen-map.json). 오른쪽 단추로 끌면 화면 이동(UX4). 오른쪽 아래 확대 단추
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { useRightDragPan } from "../app/rightDragPan";
import { autoLayout, bounds, edgePath, fitZoom, mergeLayout, nextZoom, type Point } from "./layout";
import { openFileTab } from "../store/tabs";
import {
  cardTitle,
  closePromote,
  edgeSource,
  legend,
  loadLayout,
  loadMap,
  mapSummary,
  moveCard,
  select,
  setNotice,
  setZoom,
  SOURCE_LABEL,
  useMap,
} from "./mapStore";
import { PromoteDialog } from "./PromoteDialog";
import { ScreenCard, SOURCE_CLASS } from "./ScreenCard";
import css from "./map.module.css";

const DEFAULT_ZOOM = 0.7;

export function useMapPositions(): { positions: Map<string, Point>; auto: Map<string, Point> } {
  const map = useMap((s) => s.map);
  const saved = useMap((s) => s.layout.positions);
  const auto = useMemo(
    () => (map === null ? new Map<string, Point>() : autoLayout(map.screens.map((s) => s.node), map.edges, map.start)),
    [map],
  );
  const positions = useMemo(() => mergeLayout(auto, saved), [auto, saved]);
  return { positions, auto };
}

export function ScreenMapTab() {
  const map = useMap((s) => s.map);
  const error = useMap((s) => s.error);
  const loading = useMap((s) => s.loading);
  const selected = useMap((s) => s.selected);
  const savedZoom = useMap((s) => s.layout.zoom);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [fitted, setFitted] = useState<number | null>(null);
  const zoom = savedZoom ?? fitted ?? DEFAULT_ZOOM;
  const notice = useMap((s) => s.notice);
  const promote = useMap((s) => s.promote);
  const { positions } = useMapPositions();
  const drag = useRef<{ node: string; startX: number; startY: number; origin: Point; moved: boolean } | null>(null);

  useEffect(() => {
    if (useMap.getState().map === null) {
      void loadMap();
      void loadLayout();
    }
  }, []);

  const selectedCard = map?.screens.find((s) => s.node === selected);
  const size = bounds(positions.values());

  // 처음 보기: 저장한 확대가 없으면 화면에 맞춘다 (지도를 처음 그릴 때 한 번 — 사람이 확대를 바꾸면 그 값을 저장)
  useLayoutEffect(() => {
    if (savedZoom !== undefined || fitted !== null || map === null || map.screens.length === 0) return;
    const el = canvasRef.current;
    if (el === null) return;
    setFitted(fitZoom(size, { width: el.clientWidth - 24, height: el.clientHeight - 24 }));
  }, [savedZoom, fitted, map, size]);
  const summary = mapSummary(map);
  const sources = legend(map);

  const onCardDown = (node: string) => (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const origin = positions.get(node);
    if (origin === undefined) return;
    drag.current = { node, startX: e.clientX, startY: e.clientY, origin, moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    select(node);
  };
  const onMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (d === null) return;
    const dx = (e.clientX - d.startX) / zoom;
    const dy = (e.clientY - d.startY) / zoom;
    if (!d.moved && Math.abs(dx) + Math.abs(dy) < 4) return;
    d.moved = true;
    moveCard(d.node, Math.max(0, d.origin.x + dx), Math.max(0, d.origin.y + dy));
  };
  const onUp = () => {
    drag.current = null;
  };
  // 오른쪽 단추 끌기 = 화면 이동 (UX4, 카드 위에서도). 캔버스는 스크롤 상자라 스크롤을 옮긴다
  const rightPan = useRightDragPan((dx, dy) => {
    const el = canvasRef.current;
    if (el === null) return;
    el.scrollLeft -= dx;
    el.scrollTop -= dy;
  });

  return (
    <div className={css.tab} data-part="screen-map" data-loading={loading}>
      <div className={css.toolbar} data-part="map-toolbar">
        <span data-part="map-summary">
          화면 {summary.screens} · 이동 {summary.moves} · 미탐색 {summary.untried}
        </span>
        {selectedCard !== undefined && (
          <>
            <span data-part="map-toolbar-selected">· 선택 {cardTitle(selectedCard)}</span>
            <button type="button" className={css.link} data-part="map-toolbar-raw" onClick={() => openFileTab(selectedCard.path)}>
              원문 보기
            </button>
          </>
        )}
        <span className={css.toolbarSpacer} />
        {sources.map((s) => (
          <span key={s} className={css.legendItem} data-part="map-legend" data-source={s}>
            <span className={`${css.legendDot} ${SOURCE_CLASS[s]}`} />
            {SOURCE_LABEL[s]}
          </span>
        ))}
      </div>
      {notice !== null && (
        <div className={css.notice} role="status" data-part="map-notice">
          <span>{notice}</span>
          <button type="button" className={css.noticeClose} aria-label="알림 닫기" onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      )}
      <div
        ref={canvasRef}
        className={css.canvas}
        data-part="map-canvas"
        onPointerDownCapture={rightPan.onPointerDownCapture}
        onContextMenuCapture={rightPan.onContextMenuCapture}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
      >
        {map === null ? (
          <div className={css.empty}>{error ?? "화면 지도를 읽는 중…"}</div>
        ) : map.screens.length === 0 ? (
          <div className={css.empty}>
            아직 화면이 없어요. 에이전트에게 게임 탐색을 맡기거나 screens/에 화면 판정 파일을 만들어요.
          </div>
        ) : (
          <div style={{ width: size.width * zoom, height: size.height * zoom }}>
            <div className={css.stage} style={{ width: size.width, height: size.height, transform: `scale(${zoom})` }}>
              <svg className={css.edges} width={size.width} height={size.height} aria-hidden="true">
                {map.edges.map((e, i) => {
                  if (e.to === null) return null;
                  const from = positions.get(e.from);
                  const to = positions.get(e.to);
                  if (from === undefined || to === undefined) return null;
                  const { d } = edgePath(from, to);
                  const active = selected !== null && (e.from === selected || e.to === selected);
                  return (
                    <path
                      key={i}
                      d={d}
                      className={css.edge}
                      data-part="map-edge"
                      data-from={e.from}
                      data-to={e.to}
                      data-status={e.status}
                      data-source={edgeSource(e)}
                      data-pending={e.pending === true}
                      data-active={active}
                    />
                  );
                })}
              </svg>
              {map.edges.map((e, i) => {
                if (e.to === null) return null;
                const from = positions.get(e.from);
                const to = positions.get(e.to);
                if (from === undefined || to === undefined) return null;
                const { label } = edgePath(from, to);
                return (
                  <div
                    key={i}
                    className={css.edgeLabel}
                    style={{ left: label.x, top: label.y }}
                    data-part="map-edge-label"
                    data-status={e.status}
                  >
                    {e.status === "untried" ? "아직 안 가 봄" : e.label}
                  </div>
                );
              })}
              {map.screens.map((card) => {
                const p = positions.get(card.node);
                if (p === undefined) return null;
                return (
                  <ScreenCard
                    key={card.node}
                    card={card}
                    x={p.x}
                    y={p.y}
                    selected={card.node === selected}
                    start={map.start}
                    onPointerDown={onCardDown(card.node)}
                  />
                );
              })}
            </div>
          </div>
        )}
      </div>
      <div className={css.zoom} data-part="map-zoom">
        <button type="button" aria-label="축소" onClick={() => setZoom(nextZoom(zoom, -1))}>
          −
        </button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" aria-label="확대" onClick={() => setZoom(nextZoom(zoom, 1))}>
          +
        </button>
      </div>
      {promote !== null && <PromoteDialog target={promote} onClose={closePromote} />}
    </div>
  );
}
