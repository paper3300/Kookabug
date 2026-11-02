// 노드 오른쪽 클릭 메뉴 (M3 계획 2.9, U1): 브레이크포인트 토글. 순수 노드는 걸 수 없어 꺼진다
import { useEffect, useRef } from "react";
import { useDocuments } from "../store/documents";
import { useRegistry } from "../store/registry";
import { canBreak, hasBreakpoint, useBreakpoints } from "./breakpoints";
import { toggleNodeBreakpoint } from "./commands";
import css from "./debug.module.css";

export interface NodeMenuAt {
  x: number;
  y: number;
  node: string;
}

export function NodeMenu({ graph, at, onClose }: { graph: string; at: NodeMenuAt; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const on = useBreakpoints((s) => hasBreakpoint(s.list, graph, at.node));
  const value = useDocuments((s) => s.docs.get(graph)?.value ?? null);
  const types = useRegistry((s) => s.types);
  const allowed = on || canBreak(value, at.node, types);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("mousedown", close, true);
    window.addEventListener("keydown", key);
    window.addEventListener("blur", onClose);
    ref.current?.querySelector("button")?.focus();
    return () => {
      window.removeEventListener("mousedown", close, true);
      window.removeEventListener("keydown", key);
      window.removeEventListener("blur", onClose);
    };
  }, [onClose]);

  return (
    <div ref={ref} role="menu" aria-label="노드 메뉴" className={css.menu} data-part="node-menu" style={{ left: at.x, top: at.y }}>
      <button
        type="button"
        role="menuitem"
        className={css.menuItem}
        disabled={!allowed}
        title={allowed ? undefined : "순수 노드에는 브레이크포인트를 걸 수 없어요"}
        onClick={() => {
          toggleNodeBreakpoint(graph, at.node);
          onClose();
        }}
      >
        <span>{on ? "브레이크포인트 해제" : "브레이크포인트 설정"}</span>
        <span className={css.shortcut}>F9</span>
      </button>
    </div>
  );
}
