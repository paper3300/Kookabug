// 오른쪽 단추 끌기로 화면 이동 (UX4): 그래프 캔버스·화면 지도 공용. 배경이든 노드·카드 위든 오른쪽 단추를 누른 채
// 4px 넘게 움직이면 화면을 옮기고, 그 뒤에 오는 오른쪽 클릭 메뉴(contextmenu)는 띄우지 않는다. 덜 움직였으면
// 지금처럼 메뉴를 띄운다. 왼쪽 단추 동작(선택·이동)은 건드리지 않는다
import { useCallback, useEffect, useRef } from "react";

export const RIGHT_DRAG_THRESHOLD = 4;

interface PointLike {
  button?: number;
  clientX: number;
  clientY: number;
}

/** 순수 상태기: down → move(움직인 만큼 pan) → up. contextMenu()가 true면 그 메뉴를 막는다 */
export function createRightDragPan(pan: (dx: number, dy: number) => void, onEnd?: () => void) {
  let drag: { x: number; y: number; lastX: number; lastY: number; moved: boolean } | null = null;
  let suppress = false;
  return {
    down(e: PointLike): boolean {
      if (e.button !== 2) return false;
      drag = { x: e.clientX, y: e.clientY, lastX: e.clientX, lastY: e.clientY, moved: false };
      suppress = false;
      return true;
    },
    move(e: PointLike): void {
      const d = drag;
      if (d === null) return;
      if (!d.moved && Math.hypot(e.clientX - d.x, e.clientY - d.y) < RIGHT_DRAG_THRESHOLD) return;
      d.moved = true;
      pan(e.clientX - d.lastX, e.clientY - d.lastY);
      d.lastX = e.clientX;
      d.lastY = e.clientY;
    },
    up(): void {
      const d = drag;
      drag = null;
      if (d?.moved === true) {
        suppress = true;
        onEnd?.();
      }
    },
    /** 오른쪽 클릭 메뉴 직전: 끌었으면 true (한 번만) */
    contextMenu(): boolean {
      const moved = suppress || drag?.moved === true;
      suppress = false;
      return moved;
    },
    dragging(): boolean {
      return drag !== null;
    },
  };
}

/**
 * 요소에 붙이는 훅: 돌려준 두 처리기를 캡처 단계(onPointerDownCapture·onContextMenuCapture)로 단다. 움직임과 놓기는
 * window에서 받아 요소 밖으로 끌어도 이어진다
 */
export function useRightDragPan(pan: (dx: number, dy: number) => void, onEnd?: () => void) {
  const panRef = useRef(pan);
  const endRef = useRef(onEnd);
  panRef.current = pan;
  endRef.current = onEnd;
  const state = useRef(
    createRightDragPan(
      (dx, dy) => panRef.current(dx, dy),
      () => endRef.current?.(),
    ),
  );
  const cleanup = useRef<(() => void) | null>(null);
  useEffect(() => () => cleanup.current?.(), []);
  const onPointerDownCapture = useCallback((e: { button: number; clientX: number; clientY: number }) => {
    if (!state.current.down(e)) return;
    cleanup.current?.();
    const move = (ev: PointerEvent) => state.current.move(ev);
    const up = () => {
      state.current.up();
      done();
    };
    const done = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      window.removeEventListener("pointercancel", up, true);
      window.removeEventListener("blur", up);
      cleanup.current = null;
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
    window.addEventListener("pointercancel", up, true);
    window.addEventListener("blur", up);
    cleanup.current = done;
  }, []);
  const onContextMenuCapture = useCallback((e: { preventDefault(): void; stopPropagation(): void }) => {
    if (!state.current.contextMenu()) return;
    e.preventDefault();
    e.stopPropagation();
  }, []);
  return { onPointerDownCapture, onContextMenuCapture };
}
