// 실행·정지 명령의 활성 조건 (M2 계획 2.8). 툴바 ▶·■, 메뉴 "실행"의 실행·정지, F5·Shift+F5가 이 함수 하나를 쓴다.
// 스토어를 모르는 순수 함수라 vitest로 본다

export interface RunTabLike {
  path: string;
  kind: "graph" | "target" | "run" | "file";
  graphKind?: string | null;
  /** 실행 스냅샷 그래프 (읽기 전용, M3 T10): 실행하지 않는다 */
  snapshot?: boolean;
}

export interface RunAvailabilityInput {
  /** 지금 탭 */
  tab: RunTabLike | undefined;
  /** daemon 연결됨 */
  connected: boolean;
  /** 따라가는 실행이 진행 중 */
  running: boolean;
  /** 시작 중인 그래프 경로 (저장·run.start 응답 대기) */
  starting: string | null;
}

export interface RunAvailability {
  /** 실행할 그래프 경로 (그래프 탭이 아니거나 서브그래프면 null) */
  path: string | null;
  canRun: boolean;
  canStop: boolean;
  /** 실행 단추·메뉴의 설명 */
  runTitle: string;
}

export function runAvailability({ tab, connected, running, starting }: RunAvailabilityInput): RunAvailability {
  const graph = tab?.kind === "graph" ? tab : undefined;
  const subgraph = graph?.graphKind === "subgraph";
  const snapshot = graph?.snapshot === true;
  const path = graph !== undefined && !subgraph && !snapshot ? graph.path : null;
  const canRun = path !== null && connected && !running && starting === null;
  const runTitle =
    graph === undefined
      ? "그래프 탭에서 실행해요"
      : snapshot
        ? "실행 기록의 스냅샷은 실행하지 않아요"
        : subgraph
        ? "서브그래프는 테스트에서 불러 실행해요"
        : running
          ? "실행이 끝나면 다시 실행할 수 있어요"
          : "실행 (F5)";
  return { path, canRun, canStop: running, runTitle };
}

// ── 실행 기한 (G11) ────────────────────────────────────────────

const MINUTE_MS = 60_000;

/** 툴바 기한 고르기의 고정 값 (분). 그 밖의 값은 kookabug.json run.deadline_ms로 정한다 */
export const DEADLINE_PRESETS_MIN: readonly number[] = [5, 10, 30, 60, 120, 240, 480];

/** 기한 글 ("90초", "5분", "1시간 30분") */
export function formatDeadline(ms: number): string {
  if (ms < MINUTE_MS) return `${Math.ceil(ms / 1000)}초`;
  const minutes = Math.round(ms / MINUTE_MS);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return `${minutes}분`;
  return rest === 0 ? `${hours}시간` : `${hours}시간 ${rest}분`;
}

export interface DeadlineOption {
  /** select 값: "" = 기본 */
  value: string;
  label: string;
  ms: number | null;
}

/**
 * 기한 고르기 항목. 첫 항목 "기본"은 run.start에 기한을 주지 않는 것이고 글에 워크스페이스 기본값
 * (`workspace.info` deadline_ms)을 붙인다. 지금 고른 값이 고정 값에 없으면 그 값도 넣는다
 */
export function deadlineOptions(workspaceDefaultMs: number | null | undefined, selectedMs: number | null): DeadlineOption[] {
  const base = workspaceDefaultMs === null || workspaceDefaultMs === undefined ? "기본" : `기본 (${formatDeadline(workspaceDefaultMs)})`;
  const values = DEADLINE_PRESETS_MIN.map((m) => m * MINUTE_MS);
  if (selectedMs !== null && !values.includes(selectedMs)) values.push(selectedMs);
  values.sort((a, b) => a - b);
  return [{ value: "", label: base, ms: null }, ...values.map((ms) => ({ value: String(ms), label: formatDeadline(ms), ms }))];
}
