// 화면 지도 사이드바 (M7 계획 3.14, 시안 ScreenMap 왼쪽): "화면 · N" 목록(출처 점·이동 수), 선택 섹션(대표
// 스크린샷 또는 "보호로 스크린샷 없음"·설명·출처·"이 화면인지 판정"·UI 요소·단추 2개·원문 보기), "확인 전" 묶음
// (세션별 후보: 옮기기·버리기, 합치기 후보: 합치기·버리기 — 판정 조건이 없는 후보는 옮기기 꺼짐)
import { useState } from "react";
import { addChip, setDraft } from "../agent/agentStore";
import { openFileTab } from "../store/tabs";
import { openAgentPanel } from "../store/ui";
import { ChevronDownIcon, ChevronRightIcon } from "../theme/icons";
import {
  agentRequest,
  cardSource,
  cardTitle,
  confirmedCards,
  discardCandidate,
  openPromote,
  pendingGroups,
  select,
  useMap,
  type MapCard,
  type ScreenMap,
} from "./mapStore";
import { noShotText, SOURCE_CLASS, thumbUrl } from "./ScreenCard";
import { openMapTab } from "./open";
import css from "./map.module.css";

export const ELEMENT_KIND: Record<string, string> = { button: "버튼", text: "글자", field: "입력", list: "목록" };

function Section({ title, open, onToggle }: { title: string; open: boolean; onToggle(): void }) {
  return (
    <button type="button" className={css.sideSection} aria-expanded={open} onClick={onToggle}>
      {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
      {title}
    </button>
  );
}

function originText(card: MapCard): string {
  const origin = card.origin as { session?: string } | null;
  if (cardSource(card) === "explored") return `Agent 탐색 #${(card.session ?? origin?.session ?? "").slice(-4)}`;
  return "직접 작성";
}

function Selected({ card, map }: { card: MapCard; map: ScreenMap | null }) {
  const ask = (kind: "flow" | "test") => {
    if (map === null) return;
    const r = agentRequest(map, card.node, kind);
    addChip({ kind: "screen", label: r.chip, text: `[첨부: 화면 ${r.chip.slice("@screen ".length)}]` });
    setDraft(r.text);
    openAgentPanel();
  };
  const startCard = map?.start === null || map === null ? undefined : map.screens.find((s) => s.node === map.start);
  return (
    <div className={css.detail} data-part="map-selected" data-node={card.node}>
      <div className={css.shot} data-part="map-selected-shot">
        {card.thumb !== null ? <img src={thumbUrl(card.thumb)} alt={`${cardTitle(card)} 대표 스크린샷`} /> : noShotText(card)}
      </div>
      <div className={css.describe}>
        {card.description ?? ""} <span className={css.muted}>· {originText(card)}</span>
      </div>
      <div className={css.field}>
        <span className={css.fieldLabel}>이 화면인지 판정</span>
        {card.detect_text !== "" ? (
          <span className={css.mono} data-part="map-detect">
            {card.detect_text}
          </span>
        ) : (
          <span className={css.warnText} data-part="map-detect-missing">
            판정 조건이 없어요 — 사람이 판정 조건을 채워야 확정 화면으로 옮길 수 있어요
          </span>
        )}
      </div>
      {card.elements.length > 0 && (
        <div className={css.field}>
          <span className={css.fieldLabel}>UI 요소</span>
          {card.elements.map((el) => (
            <div key={el.name} className={css.element} data-part="map-element">
              {/* 칩은 종류 글자 (이름 앞 글자는 영문이면 뜻이 없다, B5 검수 Low 3) */}
              <span className={css.chip} data-kind={el.kind}>
                {ELEMENT_KIND[el.kind] ?? el.kind}
              </span>
              <span>{el.name}</span>
            </div>
          ))}
        </div>
      )}
      {card.problem !== null && <span className={css.warnText}>{card.problem}</span>}
      <div className={css.buttons}>
        <button type="button" className={css.primary} data-part="map-ask-flow" onClick={() => ask("flow")}>
          {startCard === undefined ? "시작 화면" : cardTitle(startCard)}에서 여기까지 가는 플로 만들기
        </button>
        <button type="button" className={css.secondary} data-part="map-ask-test" onClick={() => ask("test")}>
          이 화면 테스트 작성 요청
        </button>
        <button type="button" className={css.link} data-part="map-raw" onClick={() => openFileTab(card.path)}>
          원문 보기
        </button>
      </div>
    </div>
  );
}

export function ScreenSidebar() {
  const map = useMap((s) => s.map);
  const selected = useMap((s) => s.selected);
  return <ScreenSidebarView map={map} selected={selected} />;
}

/** 값만 받아 그린다 (vitest 렌더) */
export function ScreenSidebarView({ map, selected }: { map: ScreenMap | null; selected: string | null }) {
  const [listOpen, setListOpen] = useState(true);
  const [detailOpen, setDetailOpen] = useState(true);
  const [pendingOpen, setPendingOpen] = useState(true);
  const confirmed = confirmedCards(map);
  const groups = pendingGroups(map);
  const card = map?.screens.find((s) => s.node === selected);
  const choose = (node: string) => {
    select(node);
    openMapTab();
  };
  return (
    <div className={css.side} data-part="screen-sidebar">
      <Section title={`화면 · ${confirmed.length}`} open={listOpen} onToggle={() => setListOpen(!listOpen)} />
      {listOpen &&
        confirmed.map((c) => (
          <button
            key={c.node}
            type="button"
            className={css.row}
            aria-selected={c.node === selected}
            data-part="map-row"
            data-node={c.node}
            onClick={() => choose(c.node)}
          >
            <span className={`${css.rowDot} ${SOURCE_CLASS[cardSource(c)]}`} />
            <span className={css.rowName}>{cardTitle(c)}</span>
            <span className={css.rowCount}>
              이동 {c.counts.moves}
              {(c.explored_adds ?? 0) > 0 ? ` · 탐색 +${c.explored_adds}` : ""}
            </span>
          </button>
        ))}
      {card !== undefined && (
        <>
          <Section title={`선택 · ${cardTitle(card)}`} open={detailOpen} onToggle={() => setDetailOpen(!detailOpen)} />
          {detailOpen && <Selected card={card} map={map} />}
        </>
      )}
      {groups.length > 0 && (
        <>
          <Section title="확인 전" open={pendingOpen} onToggle={() => setPendingOpen(!pendingOpen)} />
          {pendingOpen &&
            groups.map((g) => (
              <div key={g.session} data-part="map-pending" data-session={g.session}>
                <div className={css.groupHead}>
                  <span>{g.title}</span>
                  {g.status === "active" && <span>· 탐색 중</span>}
                </div>
                {g.cards.map((c) => (
                  <div key={c.node} className={css.pendingRow} data-part="map-candidate" data-node={c.node}>
                    <button type="button" className={css.pendingName} onClick={() => choose(c.node)} title={c.path}>
                      {cardTitle(c)}
                    </button>
                    <button
                      type="button"
                      className={css.mini}
                      data-part="map-promote"
                      disabled={c.incomplete === true || !(c.promotable ?? false)}
                      title={c.incomplete === true ? "판정 조건이 없어 옮길 수 없어요" : undefined}
                      onClick={() => {
                        openMapTab();
                        openPromote({ mode: "new", node: c.node, session: g.session, key: c.key ?? "", title: c.title, of: null });
                      }}
                    >
                      옮기기
                    </button>
                    <button
                      type="button"
                      className={css.mini}
                      data-part="map-discard"
                      onClick={() => void discardCandidate(g.session, c.key ?? "")}
                    >
                      버리기
                    </button>
                  </div>
                ))}
                {g.merges.map((m) => (
                  <div key={m.node} className={css.pendingRow} data-part="map-merge" data-node={m.node}>
                    <button type="button" className={css.pendingName} onClick={() => choose(m.of)} title={m.path}>
                      {m.title ?? m.key} → {m.of}
                    </button>
                    <button
                      type="button"
                      className={css.mini}
                      data-part="map-merge-open"
                      onClick={() => {
                        openMapTab();
                        openPromote({ mode: "merge", node: m.node, session: m.session, key: m.key, title: m.title, of: m.of });
                      }}
                    >
                      합치기
                    </button>
                    <button type="button" className={css.mini} onClick={() => void discardCandidate(m.session, m.key)}>
                      버리기
                    </button>
                  </div>
                ))}
              </div>
            ))}
        </>
      )}
    </div>
  );
}
