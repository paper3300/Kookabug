// 진행 중 표시 (UX1 U1). CSS만 쓰고 테마 토큰을 따른다. 움직임 줄이기 설정이면 돌지 않는 점으로 바뀐다(css).
// 짧은 일(약 300ms 안)이 깜빡이지 않게 `delay`(기본 200ms) 뒤에야 보인다. 보이는 동안 role=status·aria-busy
import { useEffect, useState } from "react";
import css from "./spinner.module.css";

/** 표시 지연 기본값 (ms): 이보다 빨리 끝나는 일은 스피너가 보이지 않는다 */
export const SPINNER_DELAY_MS = 200;

/** `active`가 `delay`ms 넘게 이어지면 true. 꺼지면 바로 false */
export function useDelayed(active: boolean, delay: number = SPINNER_DELAY_MS): boolean {
  const [shown, setShown] = useState(active && delay <= 0);
  useEffect(() => {
    if (!active) {
      setShown(false);
      return;
    }
    if (delay <= 0) {
      setShown(true);
      return;
    }
    const t = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(t);
  }, [active, delay]);
  return active && shown;
}

export function Spinner({
  label,
  active = true,
  delay = SPINNER_DELAY_MS,
  size = "md",
  className,
}: {
  /** 스피너 옆 글 (예: "저장 중…"). 없으면 화면 읽기 프로그램에만 "진행 중" */
  label?: string;
  active?: boolean;
  delay?: number;
  size?: "sm" | "md";
  className?: string;
}) {
  const shown = useDelayed(active, delay);
  if (!shown) return null;
  return (
    <span
      className={[css.spinner, className].filter(Boolean).join(" ")}
      role="status"
      aria-busy="true"
      aria-live="polite"
      data-part="spinner"
      data-size={size}
    >
      <span className={css.ring} aria-hidden="true" />
      {label !== undefined ? <span className={css.label}>{label}</span> : <span className={css.hidden}>진행 중</span>}
    </span>
  );
}
