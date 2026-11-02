// 디버거 멈춤 상태 (M3 계획 2.1·2.9). UI는 멈춤을 이벤트(`debug.pause`·`debug.resume`)로만 안다: 따로 추측하지
// 않고, 다시 붙으면 구독 재전송으로 같은 상태가 된다. 순수 함수만 둔다 (pauseState.test.ts)
// - 멈춘 노드 표시: 경계 멈춤이면 다음에 실행할 노드, 폴링 멈춤이면 기다리던 노드. 서브그래프 안이면 루트 탭의
//   호출 노드에도, 그 서브그래프 탭이 열려 있으면 안쪽 노드에도 표시한다 (M2 강조 규칙과 같은 따라가기)
// - 멈춘 노드가 든 그래프는 이벤트의 `graph`(워크스페이스 기준)로 바로 안다. 중간 깊이(중첩 서브그래프)는 실행
//   스냅샷 호출 관계(run.status calls)로 따라간다
import { framesOf, type CallMap, type RunEvent } from "../run/highlight";

export type PauseReason = "breakpoint" | "step" | "request";
export type PauseWhere = "boundary" | "poll";

export interface PausePoint {
  seq: number;
  /** 경계 멈춤이면 다음에 시작할 스텝(아직 step.start 전), 폴링 멈춤이면 기다리던 스텝 */
  step: string | null;
  node: string | null;
  /** 멈춘 노드가 든 그래프 (워크스페이스 기준, 브레이크포인트 열쇠와 같은 경로). M0b 기록에는 없다 */
  graph: string | null;
  /** 그 노드까지의 호출 경로 */
  path: readonly string[];
  reason: PauseReason;
  where: PauseWhere;
}

export interface PauseState {
  /** 지금 멈춘 자리. 돌고 있으면 null */
  paused: PausePoint | null;
  /** 이 실행에서 멈춘 횟수 */
  count: number;
  /** 재개로 끝난 멈춤의 길이 합 (debug.resume paused_ms) */
  pausedMs: number;
  /** 마지막 재개 뒤 관측 세대 */
  epoch: number;
  /**
   * 마지막 멈춤·재개 이벤트의 seq (없으면 0). 일시정지 요청의 응답이 그 사이 멈춤·재개를 지나 늦게 오면 버리는
   * 기준이다 (검수 T9-1)
   */
  debugSeq: number;
}

export const NO_PAUSE: PauseState = { paused: null, count: 0, pausedMs: 0, epoch: 0, debugSeq: 0 };

function str(v: unknown): string | null {
  return typeof v === "string" ? v : null;
}

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const REASONS: readonly PauseReason[] = ["breakpoint", "step", "request"];

/** 이벤트 하나를 멈춤 상태에 더한다. 멈춤과 무관한 이벤트면 같은 객체를 돌려준다 */
export function applyPause(state: PauseState, e: RunEvent): PauseState {
  switch (e.event) {
    case "debug.pause": {
      const node = str(e.node);
      const path =
        Array.isArray(e.path) && e.path.length > 0 && e.path.every((p) => typeof p === "string")
          ? (e.path as string[])
          : node === null
            ? []
            : [node];
      const reason = REASONS.includes(e.reason as PauseReason) ? (e.reason as PauseReason) : "request";
      return {
        ...state,
        count: state.count + 1,
        debugSeq: e.seq,
        paused: {
          seq: e.seq,
          step: str(e.step),
          node,
          graph: str(e.graph),
          path,
          reason,
          where: e.where === "poll" ? "poll" : "boundary",
        },
      };
    }
    case "debug.resume":
      return {
        ...state,
        paused: null,
        pausedMs: state.pausedMs + (num(e.paused_ms) ?? 0),
        epoch: num(e.epoch) ?? state.epoch + 1,
        debugSeq: e.seq,
      };
    case "run.end":
      return state.paused === null ? state : { ...state, paused: null };
    default:
      return state;
  }
}

/** 멈춘 자리의 깊이마다 그 노드가 든 그래프 파일. 마지막 깊이는 이벤트의 graph가 정한다. 모르는 깊이는 null */
export function pauseFrames(root: string | null, point: PausePoint, calls: CallMap): (string | null)[] {
  const frames = framesOf(root, point.path, calls);
  if (point.graph !== null && frames.length > 0) frames[frames.length - 1] = point.graph;
  return frames;
}

/**
 * 이 탭(그래프 파일 하나)에서 멈춤으로 표시할 노드: 멈춘 노드가 이 파일에 있으면 그 노드, 이 파일이 멈춘 자리의
 * 조상(호출하는 쪽)이면 그 깊이의 호출 노드. 탭 버퍼에 그 노드 ID가 없으면 null
 */
export function pausedNodeIn(
  root: string | null,
  point: PausePoint,
  calls: CallMap,
  tabPath: string,
  hasNode: (id: string) => boolean,
): string | null {
  const frames = pauseFrames(root, point, calls);
  // 같은 파일이 여러 깊이에 있으면(재귀 호출) 가장 안쪽 깊이를 고른다
  for (let depth = frames.length - 1; depth >= 0; depth--) {
    if (frames[depth] !== tabPath) continue;
    const id = point.path[depth];
    return hasNode(id) ? id : null;
  }
  return null;
}

/** 멈춘 자리가 서브그래프 안쪽인데 중간 깊이의 그래프를 몰라 호출 관계가 더 필요한가 */
export function pauseNeedsCalls(root: string | null, point: PausePoint, calls: CallMap): boolean {
  const frames = pauseFrames(root, point, calls);
  return frames.slice(0, -1).some((f) => f === null);
}

export const REASON_TEXT: Record<PauseReason, string> = {
  breakpoint: "브레이크포인트",
  step: "한 단계",
  request: "일시정지",
};
