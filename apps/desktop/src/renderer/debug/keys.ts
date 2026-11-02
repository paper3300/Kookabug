// 디버거 단축키 (M3 계획 2.9, VS Code 관례): F5 실행·계속, Shift+F5 정지, Ctrl+Shift+F5 다시 시작, F6 일시정지,
// F9 브레이크포인트, F10 다음 노드(step_over), F11 서브그래프로 들어가기(step_into), Shift+F11 나오기(step_out).
// 키 → 명령 이름만 정하는 순수 함수다. 명령의 활성 조건은 debug/commands.ts가 본다

export type DebugKeyCommand =
  | "run_or_continue"
  | "stop"
  | "restart"
  | "pause"
  | "toggle_breakpoint"
  | "step_over"
  | "step_into"
  | "step_out";

export interface KeyLike {
  key: string;
  shiftKey: boolean;
  ctrlKey: boolean;
  altKey: boolean;
  metaKey: boolean;
}

export function debugKey(e: KeyLike): DebugKeyCommand | null {
  if (e.altKey || e.metaKey) return null;
  const { key, shiftKey: shift, ctrlKey: ctrl } = e;
  switch (key) {
    case "F5":
      if (ctrl) return shift ? "restart" : null;
      return shift ? "stop" : "run_or_continue";
    case "F6":
      return ctrl || shift ? null : "pause";
    case "F9":
      return ctrl || shift ? null : "toggle_breakpoint";
    case "F10":
      return ctrl || shift ? null : "step_over";
    case "F11":
      if (ctrl) return null;
      return shift ? "step_out" : "step_into";
    default:
      return null;
  }
}
