// 에이전트 패널 하단의 고르기 단추 (Agent·Model·Effort): 누르면 위로 펼쳐지는 목록. 바깥 누르기·Esc로 닫는다
import { useEffect, useRef, useState, type ReactNode } from "react";
import { ChevronDownIcon } from "../theme/icons";
import css from "./agent.module.css";

export interface PickerItem {
  value: string;
  name: string;
  description?: string;
}

export interface PickerAction {
  label: string;
  run(): void;
}

export function Picker({
  label,
  value,
  current,
  items,
  actions = [],
  disabled = false,
  title,
  part,
  icon,
  onPick,
}: {
  /** 단추와 목록 머리에 쓰는 이름 (Agent·Model·Effort) */
  label: string;
  /** 단추에 보일 지금 값 글자 */
  value: string;
  /** 목록에서 체크할 값 */
  current: string | null;
  items: readonly PickerItem[];
  /** 목록 아래 구분선 뒤 동작 (예: 에이전트 설정…) */
  actions?: readonly PickerAction[];
  disabled?: boolean;
  title?: string;
  part: string;
  icon?: ReactNode;
  onPick(value: string): void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current !== null && e.target instanceof Node && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    box.current?.querySelector<HTMLElement>('[aria-checked="true"], [role^="menuitem"]')?.focus();
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const move = (step: number) => {
    const list = [...(box.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
    const at = list.indexOf(document.activeElement as HTMLElement);
    list[(at + step + list.length) % list.length]?.focus();
  };
  return (
    <div
      className={css.picker}
      ref={box}
      data-part={part}
      onKeyDown={(e) => {
        if (!open) return;
        if (e.key === "Escape") {
          e.preventDefault();
          e.stopPropagation();
          setOpen(false);
          box.current?.querySelector<HTMLElement>("button")?.focus();
        } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
          e.preventDefault();
          move(e.key === "ArrowDown" ? 1 : -1);
        }
      }}
    >
      <button
        type="button"
        className={css.pickerButton}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`${label}: ${value}`}
        title={title ?? `${label}: ${value}`}
        disabled={disabled}
        onClick={() => setOpen(!open)}
      >
        {icon}
        <span className={css.pickerLabel}>{label}</span>
        <span className={css.pickerValue}>{value}</span>
        <ChevronDownIcon width={10} height={10} />
      </button>
      {open && (
        <div role="menu" aria-label={label} className={css.pickerMenu}>
          <div className={css.pickerHead}>{label}</div>
          {items.map((item) => (
            <button
              key={item.value}
              type="button"
              role="menuitemradio"
              aria-checked={item.value === current}
              className={css.pickerItem}
              title={item.description}
              onClick={() => {
                setOpen(false);
                if (item.value !== current) onPick(item.value);
              }}
            >
              <span className={css.pickerCheck}>{item.value === current ? "✓" : ""}</span>
              <span className={css.pickerItemText}>
                {item.name}
                {item.description !== undefined && item.description !== "" && <small>{item.description}</small>}
              </span>
            </button>
          ))}
          {actions.length > 0 && <div role="separator" className={css.pickerSeparator} />}
          {actions.map((a) => (
            <button
              key={a.label}
              type="button"
              role="menuitem"
              className={css.pickerItem}
              onClick={() => {
                setOpen(false);
                a.run();
              }}
            >
              <span className={css.pickerCheck} />
              <span className={css.pickerItemText}>{a.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
