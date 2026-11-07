// 화면 지도 검사용 지도 값 (vitest 공용, 검사 파일 아님)
import type { MapCard, ScreenMap } from "./mapStore";

export const S = "20261107-103000-a1b2";

export function card(over: Partial<MapCard> & { node: string }): MapCard {
  return {
    state: "confirmed",
    path: `screens/${over.node}.screen.json`,
    title: over.node,
    kind: "screen",
    origin: null,
    thumb: null,
    detect_text: 'image("title")',
    elements: [],
    counts: { moves: 0, elements: 0 },
    problem: null,
    ...over,
  } as MapCard;
}

export const MAP: ScreenMap = {
  revision: "r",
  start: "lobby",
  screens: [
    card({ node: "lobby", id: "lobby", title: "로비", counts: { moves: 2, elements: 0 } }),
    card({ node: "bag", id: "bag", title: "가방", origin: { kind: "explored", session: S }, explored_adds: 1 }),
    card({
      node: `x:${S}/upgrade`,
      key: "upgrade",
      session: S,
      state: "explored",
      title: "장비 강화",
      path: `screens/_explored/${S}/upgrade.screen.json`,
      promotable: true,
      incomplete: false,
      counts: { moves: 3, elements: 1 },
    }),
    card({
      node: `x:${S}/loading`,
      key: "loading",
      session: S,
      state: "explored",
      title: "로딩",
      path: `screens/_explored/${S}/loading.screen.json`,
      promotable: false,
      incomplete: true,
      detect_text: "",
    }),
  ],
  edges: [
    { from: "lobby", to: "bag", via: { key: "i" }, label: "키 i", status: "tried", sources: [{ kind: "manual" }] },
    { from: "bag", to: `x:${S}/upgrade`, via: { key: "u" }, label: "키 u", status: "tried", sources: [{ kind: "explored", session: S }] },
    {
      from: "lobby",
      to: "bag",
      via: { call: "subgraphs/open.graph.json", exit: "ok" },
      label: "open · ok",
      status: "tried",
      sources: [{ kind: "run", count: 2 }],
    },
    { from: `x:${S}/upgrade`, to: null, via: { key: "x" }, label: "키 x", status: "untried", sources: [{ kind: "explored", session: S }] },
  ],
  sessions: [
    {
      id: S,
      title: "상점 탐색",
      status: "active",
      agent: "a",
      steps: 41,
      max_steps: 200,
      started_at: "2026-11-07T10:30:00Z",
      counts: { screens: 2, moves: 3, untried: 1 },
    },
  ],
  merges: [
    {
      node: `x:${S}/bag2`,
      key: "bag2",
      session: S,
      of: "bag",
      path: `screens/_explored/${S}/bag2.screen.json`,
      title: "가방(탐색)",
      counts: { moves: 1, elements: 0 },
    },
  ],
};
