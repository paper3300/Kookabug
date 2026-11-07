// 화면 지도 카드 (시안 ScreenMap): 대표 스크린샷 썸네일(없으면 자리 그림 + 이유), 출처 점·제목, 작은 글자.
// 후보는 점선 테두리, 선택은 파란 테두리. 썸네일은 daemon이 디스크 대표 스크린샷으로 만든 편집기 캐시 PNG뿐이다
import type { PointerEvent as ReactPointerEvent } from "react";
import { cardMeta, cardSource, cardTitle, type MapCard, type Source } from "./mapStore";
import css from "./map.module.css";

export const SOURCE_CLASS: Record<Source, string> = {
  explored: css.srcExplored ?? "",
  run: css.srcRun ?? "",
  manual: css.srcManual ?? "",
};

export function thumbUrl(name: string): string {
  return `kbimg://cache/${encodeURIComponent(name)}`;
}

/** 썸네일이 없을 때의 글자: 후보는 보호 중 저장(스크린샷 생략), 확정 화면은 스크린샷 없음 */
export function noShotText(card: Pick<MapCard, "state">): string {
  return card.state === "explored" ? "보호로 스크린샷 없음" : "스크린샷 없음";
}

export function ScreenCard({
  card,
  x,
  y,
  selected,
  start,
  onPointerDown,
}: {
  card: MapCard;
  x: number;
  y: number;
  selected: boolean;
  start: string | null;
  onPointerDown(e: ReactPointerEvent<HTMLDivElement>): void;
}) {
  return (
    <div
      className={css.card}
      style={{ left: x, top: y }}
      data-part="map-card"
      data-node={card.node}
      data-state={card.state}
      data-source={cardSource(card)}
      data-selected={selected}
      data-incomplete={card.incomplete === true}
      onPointerDown={onPointerDown}
    >
      <div className={css.thumb} data-part="map-thumb" data-has-thumb={card.thumb !== null}>
        {card.thumb !== null ? (
          <img src={thumbUrl(card.thumb)} alt="" draggable={false} />
        ) : (
          <>
            <span className={css.thumbBlockA} />
            <span className={css.thumbBlockB} />
            <span className={css.thumbText}>{noShotText(card)}</span>
          </>
        )}
      </div>
      <div className={css.cardBody}>
        <div className={css.cardTitle}>
          <span className={`${css.cardDot} ${SOURCE_CLASS[cardSource(card)]}`} />
          {cardTitle(card)}
        </div>
        <div className={css.cardMeta} data-part="map-card-meta">
          {cardMeta(card, start)}
        </div>
      </div>
    </div>
  );
}
