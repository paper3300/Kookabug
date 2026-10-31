// 최상위: 워크스페이스가 없으면 시작 화면, 있으면 앱 틀
import { useEffect } from "react";
import { confirmLeaveDirty } from "../store/editing";
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
    // 창 닫기(X·끝내기·OS 닫기) 전에 저장 안 된 그래프를 묻는다 (주 프로세스 close-guard.ts)
    window.kookabug.on("app.closeRequested", () => {
      void confirmLeaveDirty().then((ok) => window.kookabug.app.closeAnswer(ok));
    });
    void window.kookabug.app.closeGuard(true);
  }, []);
  return root === null ? <Welcome /> : <Shell />;
}
