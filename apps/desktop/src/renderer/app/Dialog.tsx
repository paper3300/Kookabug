// 앱 안 대화 상자 (저장 확인·새 그래프 이름). 시안에 없는 화면이라 빠른 열기와 같은 메뉴 표면·입력 상자를 쓴다
import { useEffect, useRef, useState } from "react";
import { finish, setDialogError, useDialog, type DialogRequest } from "../store/dialog";
import css from "./shell.module.css";

type Current = DialogRequest & { id: number; error: string | null };

function focusables(box: HTMLElement): HTMLElement[] {
  return [...box.querySelectorAll<HTMLElement>("input, button")].filter((el) => !(el as HTMLButtonElement).disabled);
}

/** 대화 상자 하나 (요청마다 새로 만든다: 입력값은 처음 그리기에서 정해져 늦게 덮이지 않는다) */
function DialogBox({ current }: { current: Current }) {
  const [text, setText] = useState(current.input?.value ?? "");
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (inputRef.current !== null) {
      inputRef.current.focus();
      inputRef.current.select();
    } else {
      boxRef.current?.querySelector<HTMLButtonElement>("[data-primary=true]")?.focus();
    }
    // 포커스를 대화 상자 안에 가둔다: 밖으로 나가면 첫 칸으로 되돌린다 (뒤쪽 캔버스가 키를 받지 않게)
    const keepInside = (e: FocusEvent) => {
      const box = boxRef.current;
      if (box !== null && e.target instanceof Node && !box.contains(e.target)) focusables(box)[0]?.focus();
    };
    document.addEventListener("focusin", keepInside);
    return () => document.removeEventListener("focusin", keepInside);
  }, []);
  const choose = (value: string) => {
    const primary = current.buttons.find((b) => b.value === value)?.primary === true;
    if (current.check !== undefined && primary) {
      const error = current.check(text);
      if (error !== null) {
        setDialogError(error);
        return;
      }
    }
    finish({ value, text });
  };
  const primary = current.buttons.find((b) => b.primary)?.value ?? current.buttons[0]?.value ?? current.cancelValue;
  return (
    <div className={css.dialogBackdrop} onMouseDown={() => finish({ value: current.cancelValue, text: "" })}>
      <div
        ref={boxRef}
        role="dialog"
        aria-modal="true"
        aria-label={current.title}
        className={css.dialog}
        onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          // 대화 상자 안의 키는 뒤쪽(캔버스 지우기·전역 단축키)으로 보내지 않는다
          e.stopPropagation();
          if (e.key === "Tab") {
            const list = focusables(e.currentTarget);
            const at = list.indexOf(document.activeElement as HTMLElement);
            const next = list[(at + (e.shiftKey ? -1 : 1) + list.length) % list.length];
            if (next !== undefined) {
              e.preventDefault();
              next.focus();
            }
          } else if (e.key === "Escape") {
            e.preventDefault();
            finish({ value: current.cancelValue, text: "" });
          } else if (e.key === "Enter" && current.input !== undefined) {
            e.preventDefault();
            choose(primary);
          }
        }}
      >
        <div className={css.dialogTitle}>{current.title}</div>
        {current.message !== undefined && <div className={css.dialogMessage}>{current.message}</div>}
        {current.input !== undefined && (
          <label className={css.dialogField}>
            <span>{current.input.label}</span>
            <span className={css.inputBox}>
              <input
                ref={inputRef}
                aria-label={current.input.label}
                placeholder={current.input.placeholder}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  if (current.error !== null) setDialogError(null);
                }}
              />
            </span>
          </label>
        )}
        {current.error !== null && (
          <div role="alert" className={css.dialogError}>
            {current.error}
          </div>
        )}
        <div className={css.dialogButtons}>
          {current.buttons.map((b) => (
            <button
              key={b.value}
              type="button"
              data-primary={b.primary === true}
              className={b.primary ? css.dialogPrimary : css.dialogButton}
              onClick={() => choose(b.value)}
            >
              {b.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export function Dialog() {
  const current = useDialog((s) => s.current);
  return current === null ? null : <DialogBox key={current.id} current={current} />;
}
