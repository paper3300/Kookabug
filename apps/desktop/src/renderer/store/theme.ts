// 테마 (M2 계획 2.10). 고른 값(시스템·라이트·다크)은 주 프로세스가 userData/settings.json에 두고
// nativeTheme.themeSource로 정한다. 실제 테마는 주 프로세스의 nativeTheme.shouldUseDarkColors다:
// "시스템"이면 Windows 설정, 아니면 고른 테마. 바뀌면 theme.state 알림이 온다
import { create } from "zustand";
import type { ThemeMode, ThemeState as BridgeThemeState } from "../../preload/bridge";

export type Theme = "dark" | "light";
export type { ThemeMode };

interface ThemeState {
  theme: Theme;
  mode: ThemeMode;
  setMode(mode: ThemeMode): Promise<void>;
}

// 첫 칠하기 전 추정값: 주 프로세스 답이 오기 전에는 prefers-color-scheme
const query = window.matchMedia("(prefers-color-scheme: dark)");

function apply(state: BridgeThemeState): void {
  useTheme.setState({ mode: state.mode, theme: state.dark ? "dark" : "light" });
}

export const useTheme = create<ThemeState>(() => ({
  theme: query.matches ? "dark" : "light",
  mode: "system",
  async setMode(mode) {
    apply(await window.kookabug.app.themeSet(mode));
  },
}));

window.kookabug.on("theme.state", (data) => apply(data as BridgeThemeState));
void window.kookabug.app.themeGet().then(apply);
