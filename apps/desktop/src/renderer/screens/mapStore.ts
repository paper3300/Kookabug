// 화면 지도 상태 (M7 계획 3.14, B5). 지도 값은 daemon `screens.map`(카드·간선·세션·합치기 후보), 카드 자리는
// `screens.layout_get/set`(.kookabug/screen-map.json), 탐색 세션은 `explore.list`·`explore.changed`.
// - 순수 계산(출처 색·요약·사이드바 묶음·최단 경로·상태 바 글자)은 mapStore.test.ts로 본다
// - 승격·합치기·버리기는 사람(ui) 연결의 `screens.check/promote/discard`만 부른다 (렌더러 IPC — 에이전트 경로 없음)
// - 이미지는 `thumb`(daemon이 디스크 대표 스크린샷으로 만든 편집기 캐시 썸네일, kbimg://cache/)만 쓴다
import type { ResultOf } from "@kookabug/schema";
import { create } from "zustand";
import { client, toRpcError } from "../rpc/client";

export type ScreenMap = ResultOf<"screens.map">;
export type MapCard = ScreenMap["screens"][number];
export type MapEdge = ScreenMap["edges"][number];
export type MapMerge = NonNullable<ScreenMap["merges"]>[number];
export type ExploreSession = ResultOf<"explore.list">["sessions"][number];

export type Source = "explored" | "run" | "manual";

export const SOURCE_LABEL: Record<Source, string> = {
  explored: "Agent 탐색",
  run: "실행 기록",
  manual: "직접 작성",
};

export const MAP_TAB_PATH = "map:screens";

/** 카드 출처: 탐색 후보이거나 탐색에서 승격된 화면이면 Agent 탐색, 아니면 직접 작성 */
export function cardSource(card: Pick<MapCard, "state" | "origin">): Source {
  const origin = card.origin as { kind?: unknown } | null;
  return card.state === "explored" || origin?.kind === "explored" ? "explored" : "manual";
}

/** 간선 출처: 실행 기록이 하나라도 있으면 실행 기록, 탐색이면 Agent 탐색, 그 밖 직접 작성 */
export function edgeSource(edge: Pick<MapEdge, "sources">): Source {
  const kinds = edge.sources.map((s) => (s as { kind?: unknown }).kind);
  if (kinds.includes("run")) return "run";
  if (kinds.includes("explored")) return "explored";
  return "manual";
}

/** 범례: 지도에 실제로 있는 출처만 (시안의 녹화·문서·영상은 MVP 뒤 — U3·U4) */
export function legend(map: Pick<ScreenMap, "screens" | "edges"> | null): Source[] {
  if (map === null) return [];
  const found = new Set<Source>([...map.screens.map(cardSource), ...map.edges.map(edgeSource)]);
  return (["explored", "run", "manual"] as const).filter((s) => found.has(s));
}

/** 상태 바 "화면 N · 이동 M · 미탐색 K" */
export function mapSummary(map: Pick<ScreenMap, "screens" | "edges"> | null): { screens: number; moves: number; untried: number } {
  if (map === null) return { screens: 0, moves: 0, untried: 0 };
  return {
    screens: map.screens.length,
    moves: map.edges.filter((e) => e.status === "tried").length,
    untried: map.edges.filter((e) => e.status === "untried").length,
  };
}

/** 카드 아래 작은 글자 (시안: "시작 화면 · 이동 3", "이동 2 · 요소 6", "새로 발견 · …") */
export function cardMeta(card: MapCard, start: string | null): string {
  const parts: string[] = [];
  if (card.state === "explored") {
    parts.push(card.incomplete === true ? "판정 조건 없음" : "새로 발견");
  } else if (card.node === start) {
    parts.push("시작 화면");
  }
  parts.push(`이동 ${card.counts.moves}`);
  if (card.counts.elements > 0) parts.push(`요소 ${card.counts.elements}`);
  if ((card.explored_adds ?? 0) > 0) parts.push(`탐색 추가 ${card.explored_adds}`);
  return parts.join(" · ");
}

export function cardTitle(card: Pick<MapCard, "title" | "id" | "key" | "node">): string {
  return card.title ?? card.id ?? card.key ?? card.node;
}

export interface PendingGroup {
  session: string;
  title: string;
  status: string | null;
  cards: MapCard[];
  merges: MapMerge[];
}

/** 사이드바 "확인 전": 세션별 후보 카드 + 합치기 후보 (세션 최신 먼저) */
export function pendingGroups(map: ScreenMap | null): PendingGroup[] {
  if (map === null) return [];
  const groups = new Map<string, PendingGroup>();
  const group = (session: string): PendingGroup => {
    let g = groups.get(session);
    if (g === undefined) {
      const info = map.sessions.find((s) => s.id === session);
      g = { session, title: info?.title ?? session, status: info?.status ?? null, cards: [], merges: [] };
      groups.set(session, g);
    }
    return g;
  };
  for (const card of map.screens) if (card.state === "explored" && card.session !== undefined) group(card.session).cards.push(card);
  for (const merge of map.merges ?? []) group(merge.session).merges.push(merge);
  return [...groups.values()].sort((a, b) => b.session.localeCompare(a.session));
}

/** 사이드바 "화면 · N": 확정 화면 (제목 순) */
export function confirmedCards(map: ScreenMap | null): MapCard[] {
  if (map === null) return [];
  return map.screens.filter((s) => s.state === "confirmed").sort((a, b) => cardTitle(a).localeCompare(cardTitle(b), "ko"));
}

/** 이동 간선(가 본 것)만 따라가는 최단 경로 (노드 목록, 없으면 null) */
export function shortestPath(edges: readonly Pick<MapEdge, "from" | "to" | "status">[], from: string, to: string): string[] | null {
  if (from === to) return [from];
  const prev = new Map<string, string>([[from, from]]);
  const queue = [from];
  while (queue.length > 0) {
    const node = queue.shift()!;
    for (const e of edges) {
      if (e.from !== node || e.to === null || e.status !== "tried" || prev.has(e.to)) continue;
      prev.set(e.to, node);
      if (e.to === to) {
        const path = [to];
        let at = to;
        while (at !== from) {
          at = prev.get(at)!;
          path.unshift(at);
        }
        return path;
      }
      queue.push(e.to);
    }
  }
  return null;
}

/** "로비에서 여기까지 가는 플로 만들기"·"이 화면 테스트 작성 요청" 기본 문장 */
export function agentRequest(map: ScreenMap, node: string, kind: "flow" | "test"): { chip: string; text: string } {
  const card = map.screens.find((s) => s.node === node);
  const name = card === undefined ? node : cardTitle(card);
  const ref = card?.id ?? card?.key ?? node;
  const chip = `@screen ${ref}`;
  if (kind === "test") return { chip, text: `${name} 화면을 확인하는 테스트를 작성해 줘. 화면 판정 조건과 UI 요소를 써.` };
  const start = map.start;
  const startCard = start === null ? undefined : map.screens.find((s) => s.node === start);
  const path = start === null ? null : shortestPath(map.edges, start, node);
  const steps =
    path === null
      ? "지도에 이어진 경로가 없으니 탐색 결과를 보고 정해"
      : `경로: ${path.map((n) => cardTitle(map.screens.find((s) => s.node === n) ?? { node: n, title: null })).join(" → ")}`;
  return {
    chip,
    text: `${startCard === undefined ? "시작 화면" : cardTitle(startCard)}에서 ${name}까지 가는 서브그래프(플로)를 만들어 줘. ${steps}.`,
  };
}

/** 탐색기 경로 → 지도 노드 (확정 화면 파일·후보 카드 파일·합치기 후보 파일은 합칠 화면) */
export function nodeOfPath(map: ScreenMap | null, path: string): string | null {
  if (map === null) return null;
  const card = map.screens.find((s) => s.path === path);
  if (card !== undefined) return card.node;
  const merge = (map.merges ?? []).find((m) => m.path === path);
  return merge?.of ?? null;
}

export function activeSession(sessions: readonly ExploreSession[]): ExploreSession | null {
  return sessions.find((s) => s.status === "active") ?? null;
}

/** "m:ss" (시작 시각부터) */
export function elapsedText(startedAt: string, now: number): string {
  const started = Date.parse(startedAt);
  const total = Number.isFinite(started) ? Math.max(0, Math.floor((now - started) / 1000)) : 0;
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** 상태 바 오른쪽 "입력 도구: …" — 게임 조작 판정(사람이 지켜보는 에이전트 기준)과 이 탐색 동안 허용 */
export function inputToolText(clickVerdict: string | null, sessionAllowed: boolean): string | null {
  if (sessionAllowed) return "입력 도구: 이 탐색 동안 허용됨";
  if (clickVerdict === "allow") return "입력 도구: 바로 실행";
  if (clickVerdict === "ask") return "입력 도구: 확인 후 실행";
  if (clickVerdict === "deny") return "입력 도구: 사용 안 함";
  return null;
}

/** `recovery_pending`(남은 승격 정리 필요) 안내 */
export function recoveryText(message: string): string {
  return `남은 승격 정리가 필요해요 — ${message} 터미널에서 kookabug screen recover --show 로 볼 수 있어요.`;
}

// ---------------------------------------------------------------- 상태

export interface Layout {
  [k: string]: unknown;
  positions: Record<string, [number, number]>;
  zoom?: number;
}

export interface PromoteTarget {
  mode: "new" | "merge";
  node: string;
  session: string;
  key: string;
  title: string | null;
  of: string | null;
}

interface MapState {
  map: ScreenMap | null;
  loading: boolean;
  error: string | null;
  layout: Layout;
  layoutRevision: string | null;
  selected: string | null;
  sessions: ExploreSession[];
  /** "이 탐색 동안 허용"을 준 탐색 세션 (approval.resolved) */
  allowedSessions: string[];
  promote: PromoteTarget | null;
  notice: string | null;
}

const EMPTY: MapState = {
  map: null,
  loading: false,
  error: null,
  layout: { positions: {} },
  layoutRevision: null,
  selected: null,
  sessions: [],
  allowedSessions: [],
  promote: null,
  notice: null,
};

export const useMap = create<MapState>(() => ({ ...EMPTY }));

let loadSeq = 0;

export async function loadMap(): Promise<void> {
  const seq = ++loadSeq;
  useMap.setState({ loading: true });
  try {
    const map = await client().call("screens.map", {});
    if (seq !== loadSeq) return;
    const selected = useMap.getState().selected;
    const keep = selected !== null && map.screens.some((s) => s.node === selected) ? selected : null;
    useMap.setState({ map, loading: false, error: null, sessions: map.sessions, selected: keep });
  } catch (err) {
    if (seq !== loadSeq) return;
    useMap.setState({ loading: false, error: toRpcError(err).message });
  }
}

export async function loadLayout(): Promise<void> {
  try {
    const r = await client().call("screens.layout_get", {});
    const positions = (r.layout as { positions?: Record<string, [number, number]> }).positions ?? {};
    const zoom = (r.layout as { zoom?: number }).zoom;
    useMap.setState({ layout: { positions, ...(zoom !== undefined ? { zoom } : {}) }, layoutRevision: r.revision });
  } catch {
    // 배치가 없어도 지도는 자동 배치로 그린다
  }
}

export async function loadSessions(): Promise<void> {
  try {
    const r = await client().call("explore.list", {});
    useMap.setState({ sessions: r.sessions });
  } catch {
    // 연결 전
  }
}

export function select(node: string | null): void {
  useMap.setState({ selected: node });
}

let saveTimer: ReturnType<typeof setTimeout> | null = null;

/** 카드를 옮겼다: 자리를 기억하고 잠시 뒤 저장한다 */
export function moveCard(node: string, x: number, y: number): void {
  useMap.setState((s) => ({ layout: { ...s.layout, positions: { ...s.layout.positions, [node]: [Math.round(x), Math.round(y)] } } }));
  scheduleSave();
}

export function setZoom(zoom: number): void {
  useMap.setState((s) => ({ layout: { ...s.layout, zoom } }));
  scheduleSave();
}

function scheduleSave(): void {
  if (saveTimer !== null) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    saveTimer = null;
    void saveLayout();
  }, 400);
}

export async function saveLayout(): Promise<void> {
  const { layout, layoutRevision } = useMap.getState();
  try {
    const r = await client().call("screens.layout_set", { layout, base_revision: layoutRevision });
    useMap.setState({ layoutRevision: r.revision });
  } catch (err) {
    if (toRpcError(err).kind === "revision_conflict") {
      // 다른 창이 바꿨다: 그 배치 위에 지금 자리를 다시 얹는다
      const mine = useMap.getState().layout;
      await loadLayout();
      useMap.setState((s) => ({ layout: { ...s.layout, positions: { ...s.layout.positions, ...mine.positions }, zoom: mine.zoom ?? s.layout.zoom } }));
      const retry = useMap.getState();
      await client()
        .call("screens.layout_set", { layout: retry.layout, base_revision: retry.layoutRevision })
        .then((r) => useMap.setState({ layoutRevision: r.revision }))
        .catch(() => {});
    }
  }
}

export function openPromote(target: PromoteTarget): void {
  useMap.setState({ promote: target });
}

export function closePromote(): void {
  useMap.setState({ promote: null });
}

export function setNotice(notice: string | null): void {
  useMap.setState({ notice });
}

/** 후보 버리기 (사람만 — ui 연결) */
export async function discardCandidate(session: string, key: string): Promise<void> {
  try {
    await client().call("screens.discard", { session, key });
    useMap.setState({ notice: null });
  } catch (err) {
    const e = toRpcError(err);
    useMap.setState({ notice: e.kind === "recovery_pending" ? recoveryText(e.message) : `버리지 못했어요: ${e.message}` });
  }
  await loadMap();
}

export function noteAllowSession(session: string): void {
  useMap.setState((s) => (s.allowedSessions.includes(session) ? s : { allowedSessions: [...s.allowedSessions, session] }));
}

let refreshTimer: ReturnType<typeof setTimeout> | null = null;

function refreshSoon(): void {
  if (refreshTimer !== null) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshTimer = null;
    void loadMap();
  }, 150);
}

/** 앱 시작 때 한 번 (store/workspace.ts initWorkspace) */
export function initMap(): void {
  client().on("screens.changed", () => refreshSoon());
  client().on("explore.changed", (p) => {
    useMap.setState({ sessions: p.sessions });
    refreshSoon();
  });
  // 실행이 끝나면 실행 기록 사슬 간선이 바뀔 수 있다
  client().on("run.ended", () => refreshSoon());
}

/** daemon에 붙을 때마다 */
export async function mapConnected(): Promise<void> {
  await Promise.all([loadSessions(), loadLayout(), loadMap()]);
}

/** 프로젝트가 바뀜 */
export function resetMap(): void {
  loadSeq++;
  useMap.setState({ ...EMPTY });
}
