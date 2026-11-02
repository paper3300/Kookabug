// 디버거 명령 (M3 계획 2.9): 디버그 툴바 단추·단축키·메뉴가 같은 활성 조건(availability.ts)과 같은 명령을 쓴다.
// 정지는 탭 줄에서 디버그 툴바로 옮겼다 (M2 U3를 시안대로 되돌림)
import { useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { useTabs } from "../store/tabs";
import { runActive } from "../run/Toolbar";
import { runModel, useRun, type ResumeMode } from "../run/runStore";
import { debugAvailability, type DebugAvailability } from "./availability";
import { breakpointModel, toggleMany } from "./breakpoints";
import type { DebugKeyCommand } from "./keys";

export type { DebugAvailability };

export function useDebugAvailability(): DebugAvailability {
  const current = useRun((s) => s.current);
  const starting = useRun((s) => s.starting);
  return debugAvailability({ current, starting });
}

function now(): DebugAvailability {
  return debugAvailability(useRun.getState());
}

export function pauseRun(): void {
  if (now().canPause) void runModel.pause();
}

export function resumeRun(mode: ResumeMode): void {
  if (now().canStep) void runModel.resume(mode);
}

export function restartRun(): void {
  if (now().canRestart) void runModel.restart();
}

export function stopRun(): void {
  if (now().canStop) void runModel.cancel();
}

/** F5: 멈춘 동안은 계속, 아니면 실행 */
export function runOrContinue(): void {
  if (now().paused) resumeRun("continue");
  else runActive();
}

/** F9·메뉴: 지금 그래프 탭에서 고른 노드의 브레이크포인트 토글 */
export function toggleSelectedBreakpoints(): void {
  const { active, tabs } = useTabs.getState();
  if (active === null || tabs.find((t) => t.path === active)?.kind !== "graph") return;
  const doc = useDocuments.getState().docs.get(active);
  // 실행 스냅샷 그래프(읽기 전용)에는 걸지 않는다
  if (doc === undefined || doc.value === null || doc.readOnly || doc.view.selection.length === 0) return;
  const next = toggleMany(breakpointModel.list, active, doc.view.selection, doc.value, useRegistry.getState().types);
  if (next !== null) void breakpointModel.set(next);
}

/** 노드 하나 토글 (점 자리 클릭·오른쪽 클릭 메뉴) */
export function toggleNodeBreakpoint(graph: string, node: string): void {
  const doc = useDocuments.getState().docs.get(graph);
  const next = toggleMany(breakpointModel.list, graph, [node], doc?.value ?? null, useRegistry.getState().types);
  if (next !== null) void breakpointModel.set(next);
}

/** 단축키 명령 실행 (활성 조건이 맞지 않으면 아무것도 하지 않는다) */
export function runDebugKey(cmd: DebugKeyCommand): void {
  switch (cmd) {
    case "run_or_continue":
      runOrContinue();
      return;
    case "stop":
      stopRun();
      return;
    case "restart":
      restartRun();
      return;
    case "pause":
      pauseRun();
      return;
    case "toggle_breakpoint":
      toggleSelectedBreakpoints();
      return;
    case "step_over":
    case "step_into":
    case "step_out":
      resumeRun(cmd);
      return;
  }
}
