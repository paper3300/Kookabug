// 디버그 툴바·단축키·메뉴의 활성 조건 (M3 계획 2.9). 스토어를 모르는 순수 함수다 (availability.test.ts)
// - 툴바는 실행이 있을 때만 보인다 (진행 중 실행, 또는 다시 시작 중)
// - Step 단추는 멈춘 동안만 켜진다. "멈추는 중"(요청 뒤 확인 지점 전)에는 일시정지 단추가 눌린 채 회색이다
import type { RunState } from "../run/runStore";

export interface DebugAvailability {
  /** 툴바를 보인다 */
  visible: boolean;
  paused: boolean;
  pausing: boolean;
  canPause: boolean;
  canStep: boolean;
  canRestart: boolean;
  canStop: boolean;
}

export function debugAvailability(s: Pick<RunState, "current" | "starting">): DebugAvailability {
  const running = s.current?.phase === "running";
  const paused = running && s.current?.pause.paused != null;
  const pausing = running && !paused && s.current?.pausing === true;
  // 다시 시작 중: 옛 실행은 끝났고 새 실행 응답을 기다린다 (툴바가 깜빡이지 않게 남긴다)
  const restarting = s.starting !== null && s.current !== null;
  return {
    visible: running || restarting,
    paused,
    pausing,
    canPause: running && !paused && !pausing && s.starting === null,
    canStep: paused && s.starting === null,
    canRestart: running && s.starting === null,
    canStop: running,
  };
}
