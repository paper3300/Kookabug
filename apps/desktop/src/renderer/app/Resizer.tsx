// 패널 폭 손잡이: 사이드바 오른쪽 끝·오른쪽 패널 왼쪽 끝. 끌면 폭이 바뀌고, 최소 폭의 절반보다 좁게 끌어 놓으면
// 접는다. 두 번 누르면 기본 폭. 키보드(←·→)로도 16px씩 바꾼다. 폭은 부모(aside) 기준이다
import { useRef } from "react";
import css from "./shell.module.css";

/** 끈 폭을 최소·최대(그리고 창 폭 × 비율) 안으로 */
export function clampWidth(w: number, min: number, max: number, viewport: number, fraction: number): number {
  return Math.round(Math.min(Math.max(w, min), Math.max(min, Math.min(max, viewport * fraction))));
}

export function Resizer({
  edge,
  label,
  min,
  max,
  onWidth,
  onCollapse,
  maxFraction = 0.6,
}: {
  /** 창 폭에 대한 최대 비율 (오른쪽 패널은 0.5, UX6) */
  maxFraction?: number;
  /** 손잡이 자리: right = 부모 오른쪽 끝(왼쪽 사이드바), left = 부모 왼쪽 끝(오른쪽 패널) */
  edge: "left" | "right";
  label: string;
  min: number;
  max: number;
  /** null = 기본 폭으로 */
  onWidth(width: number | null): void;
  onCollapse(): void;
}) {
  const drag = useRef<{ x: number; width: number; raw: number } | null>(null);
  const limit = (w: number) => clampWidth(w, min, max, window.innerWidth, maxFraction);
  const current = (el: HTMLElement) => (el.parentElement?.getBoundingClientRect().width ?? min + 1) - 1;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      tabIndex={0}
      className={css.resizer}
      data-edge={edge}
      data-part="resizer"
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        const width = current(e.currentTarget);
        drag.current = { x: e.clientX, width, raw: width };
        document.body.dataset.resizing = "true";
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (d === null) return;
        const dx = e.clientX - d.x;
        d.raw = d.width + (edge === "right" ? dx : -dx);
        onWidth(limit(d.raw));
      }}
      onPointerUp={(e) => {
        const d = drag.current;
        drag.current = null;
        delete document.body.dataset.resizing;
        if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
        if (d !== null && d.raw < min / 2) {
          onWidth(limit(d.width));
          onCollapse();
        }
      }}
      onDoubleClick={() => onWidth(null)}
      onKeyDown={(e) => {
        if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
        e.preventDefault();
        const grow = (e.key === "ArrowRight") === (edge === "right");
        onWidth(limit(current(e.currentTarget) + (grow ? 16 : -16)));
      }}
    />
  );
}
