// 시안 Main·Setup0Welcome의 인라인 SVG를 옮긴 아이콘 (M2 계획 2.10 "아이콘"). 색은 currentColor
import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

/** L3 마스코트 마크 (시안 타이틀 바·시작 화면 로고). 눈 띠는 배경색으로 칠한다 */
export function LogoMark({ cutout = "var(--kb-bg)", ...props }: IconProps & { cutout?: string }) {
  return (
    <svg viewBox="20 40 216 190" aria-hidden="true" {...props}>
      <path
        d="M160 88 L216 98 C225 100 226 107 218 109 L166 120 C168 134 168 148 162 162 C154 182 136 194 114 194 C100 194 88 190 78 182 L52 212 L34 208 L58 164 C64 150 66 134 64 118 C62 92 82 60 118 58 C138 57 154 68 160 88 Z"
        fill="currentColor"
      />
      <rect x="99" y="186" width="8" height="20" rx="3" fill="currentColor" />
      <rect x="118" y="186" width="8" height="20" rx="3" fill="currentColor" />
      <rect x="54" y="202" width="164" height="11" rx="5.5" fill="currentColor" />
      <path d="M150 92 C126 90 100 96 72 110 C100 106 126 104 151 104 Z" fill={cutout} />
      <circle cx="140" cy="97" r="5" fill="currentColor" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="M20 20l-4-4" />
    </svg>
  );
}

export function MinimizeIcon(props: IconProps) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" {...props}>
      <path d="M0 5h10" stroke="currentColor" />
    </svg>
  );
}

export function MaximizeIcon(props: IconProps) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" {...props}>
      <rect x=".5" y=".5" width="9" height="9" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function RestoreIcon(props: IconProps) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" {...props}>
      <rect x=".5" y="2.5" width="7" height="7" fill="none" stroke="currentColor" />
      <path d="M2.5 2.5v-2h7v7h-2" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" {...props}>
      <path d="M0 0l10 10M10 0L0 10" stroke="currentColor" />
    </svg>
  );
}

/** 액티비티 바 탐색기 (시안 Main) */
export function ExplorerIcon(props: IconProps) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" aria-hidden="true" {...props}>
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}

/** 섹션 머리 펼침 (시안 Main 사이드바) */
export function ChevronDownIcon(props: IconProps) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" {...props}>
      <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" {...props}>
      <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

/** 시작 화면 버튼의 Enter 표시 (시안 Setup0Welcome) */
export function EnterIcon(props: IconProps) {
  return (
    <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true" {...props}>
      <path d="M13 3v5a2 2 0 0 1-2 2H4" />
      <path d="M6.5 7.5L4 10l2.5 2.5" />
    </svg>
  );
}

/** 상태 바 입력 임대권 자물쇠 (시안 Main) */
export function LockIcon(props: IconProps) {
  return (
    <svg width="11" height="11" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true" {...props}>
      <rect x="3" y="7" width="10" height="7" rx="1" />
      <path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2" />
    </svg>
  );
}

/** 상태 바 연결 표시 (점) */
export function DotIcon(props: IconProps) {
  return (
    <svg width="8" height="8" viewBox="0 0 8 8" aria-hidden="true" {...props}>
      <circle cx="4" cy="4" r="3.5" fill="currentColor" />
    </svg>
  );
}
