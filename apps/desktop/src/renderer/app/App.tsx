// 최상위: 워크스페이스가 없으면 시작 화면, 있으면 앱 틀
import { useEffect } from "react";
import { useTheme } from "../store/theme";
import { initWorkspace, useWorkspace } from "../store/workspace";
import { Welcome } from "../welcome/Welcome";
import { Shell } from "./Shell";

let started = false;

export function App() {
  const theme = useTheme((s) => s.theme);
  const root = useWorkspace((s) => s.root);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);
  useEffect(() => {
    // StrictMode에서 두 번 불러도 구독은 한 번
    if (started) return;
    started = true;
    void initWorkspace();
  }, []);
  return root === null ? <Welcome /> : <Shell />;
}
