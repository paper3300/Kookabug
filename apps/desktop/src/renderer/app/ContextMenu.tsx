// 앱 공용 오른쪽 클릭 메뉴 (UX4). 모양은 그래프 노드 메뉴(debug/NodeMenu)와 같다: 바깥 누르기·Esc·창 흐림이면 닫힌다
import { useEffect, useRef } from "react";
import css from "../debug/debug.module.css";

export interface ContextMenuItem {
  label: string;
  onSelect: () => void;
  disabled?: boolean;
  part?: string;
}

export function ContextMenu({
  label,
  at,
  items,
  onClose,
  part,
}: {
  label: string;
  at: { x: number; y: number };
  items: readonly ContextMenuItem[];
  onClose: () => void;
  part?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
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
    <div ref={ref} role="menu" aria-label={label} className={css.menu} data-part={part} style={{ left: at.x, top: at.y }}>
      {items.map((item) => (
        <button
          key={item.label}
          type="button"
          role="menuitem"
          className={css.menuItem}
          disabled={item.disabled}
          data-part={item.part}
          onClick={() => {
            onClose();
            item.onSelect();
          }}
        >
          <span>{item.label}</span>
        </button>
      ))}
    </div>
  );
}
