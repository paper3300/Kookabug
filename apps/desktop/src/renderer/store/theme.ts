// 테마 상태. 첫 실행은 Windows 설정(nativeTheme → prefers-color-scheme)을 따른다.
// 보기 메뉴의 시스템·라이트·다크 고르기와 저장은 T7
import { create } from "zustand";

export type Theme = "dark" | "light";

interface ThemeState {
  theme: Theme;
}

const query = window.matchMedia("(prefers-color-scheme: dark)");

export const useTheme = create<ThemeState>(() => ({ theme: query.matches ? "dark" : "light" }));

query.addEventListener("change", (e) => useTheme.setState({ theme: e.matches ? "dark" : "light" }));
