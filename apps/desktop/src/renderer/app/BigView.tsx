// 크게 보기 (UX6): 오른쪽 속성 탭의 스크린샷·영상은 패널 폭에 맞춰 그리고, "크게 보기"를 누르면 앱 안에서 창 대부분을
// 덮는 큰 보기로 연다. 바깥 누르기·Esc·닫기로 닫는다
import { useEffect } from "react";
import { createPortal } from "react-dom";
import css from "./shell.module.css";

export function BigView({ title, onClose, children }: { title: string; onClose(): void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  return createPortal(
    <div
      className={css.bigBackdrop}
      data-part="media-big"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onPointerDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className={css.bigBox}>
        <div className={css.bigHead}>
          <span className={css.bigTitle}>{title}</span>
          <button type="button" className={css.dialogButton} data-part="media-big-close" onClick={onClose}>
            닫기
          </button>
        </div>
        <div className={css.bigBody}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}
