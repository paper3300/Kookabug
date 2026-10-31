// 실행 취소 기록 (M2 계획 2.6·T9). 명령 하나 = 기록 하나다(이동은 끌기 하나가 한 명령). 값은 바꾸지 않는
// 구조 공유 값이라 앞 값을 그대로 든다. 기록은 렌더러 문서에 있어 daemon이 바뀌어도 남는다 (2.3 복구)
import type { GraphValue } from "./model";

export interface History {
  past: readonly GraphValue[];
  future: readonly GraphValue[];
}

export const HISTORY_LIMIT = 500;
export const EMPTY_HISTORY: History = { past: [], future: [] };

/** 편집 하나를 적는다 (before = 편집 전 값). 다시 실행 기록은 버린다 */
export function record(h: History, before: GraphValue): History {
  const past = [...h.past, before];
  return { past: past.length > HISTORY_LIMIT ? past.slice(past.length - HISTORY_LIMIT) : past, future: [] };
}

export function undo(h: History, current: GraphValue): { history: History; value: GraphValue } | null {
  if (h.past.length === 0) return null;
  return {
    value: h.past[h.past.length - 1],
    history: { past: h.past.slice(0, -1), future: [current, ...h.future] },
  };
}

export function redo(h: History, current: GraphValue): { history: History; value: GraphValue } | null {
  if (h.future.length === 0) return null;
  return {
    value: h.future[0],
    history: { past: [...h.past, current], future: h.future.slice(1) },
  };
}
