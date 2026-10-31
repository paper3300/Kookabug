// 앱 안 대화 상자 하나 (저장 확인·이름 입력). 네이티브 confirm 대신 시안 토큰으로 그린다 (app/Dialog.tsx)
import { create } from "zustand";

export interface DialogButton {
  label: string;
  value: string;
  primary?: boolean;
}

export interface DialogRequest {
  title: string;
  message?: string;
  /** 이름 입력 칸 (있으면 결과에 입력값이 담긴다) */
  input?: { label: string; value: string; placeholder?: string };
  buttons: DialogButton[];
  /** Esc·바깥 누르기의 결과 */
  cancelValue: string;
  /** 입력값 검사 (오류 문구, 괜찮으면 null) */
  check?: (text: string) => string | null;
}

export interface DialogResult {
  value: string;
  text: string;
}

interface DialogState {
  current: (DialogRequest & { id: number; error: string | null }) | null;
}

export const useDialog = create<DialogState>(() => ({ current: null }));

let nextId = 0;
let resolveCurrent: ((r: DialogResult) => void) | null = null;

/** 대화 상자를 띄우고 고른 단추를 기다린다. 이미 떠 있으면 앞 것을 취소로 닫는다 */
export function ask(request: DialogRequest): Promise<DialogResult> {
  const prev = useDialog.getState().current;
  if (prev !== null) finish({ value: prev.cancelValue, text: "" });
  return new Promise((resolve) => {
    resolveCurrent = resolve;
    useDialog.setState({ current: { ...request, id: ++nextId, error: null } });
  });
}

export function finish(result: DialogResult): void {
  const resolve = resolveCurrent;
  resolveCurrent = null;
  useDialog.setState({ current: null });
  resolve?.(result);
}

// ── 편집 잠금 ────────────────────────────────────────────────────
// 대화 상자가 떠 있는 동안과 "저장하고 닫기"처럼 저장을 기다리는 동안은 그래프를 고칠 수 없다. 뒤쪽 캔버스의
// 키보드 지우기·실행 취소, 저장 요청 뒤에 생긴 편집이 닫기와 함께 사라지는 것을 막는다 (T9 검수 1차)

interface LockState {
  locks: number;
}

export const useEditLock = create<LockState>(() => ({ locks: 0 }));

/** 편집을 잠근다. 돌려준 함수로 푼다 (여러 번 불러도 한 번만 푼다) */
export function lockEdits(): () => void {
  useEditLock.setState((s) => ({ locks: s.locks + 1 }));
  let done = false;
  return () => {
    if (done) return;
    done = true;
    useEditLock.setState((s) => ({ locks: Math.max(0, s.locks - 1) }));
  };
}

/** 지금 그래프를 고칠 수 없는가 (대화 상자가 떠 있거나 잠금 중) */
export function editsLocked(): boolean {
  return useDialog.getState().current !== null || useEditLock.getState().locks > 0;
}

/** 컴포넌트용 */
export function useEditsLocked(): boolean {
  const dialog = useDialog((s) => s.current !== null);
  const locks = useEditLock((s) => s.locks);
  return dialog || locks > 0;
}

/** 입력 칸 아래 오류 문구 (대화 상자는 그대로 둔다) */
export function setDialogError(error: string | null): void {
  useDialog.setState((s) => (s.current === null ? s : { current: { ...s.current, error } }));
}
