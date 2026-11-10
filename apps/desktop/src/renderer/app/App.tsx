// 최상위: 워크스페이스가 없으면 시작 화면, 있으면 앱 틀
import { useEffect } from "react";
import { confirmLeaveDirty } from "../store/editing";
import { useTheme } from "../store/theme";
import { layoutOf, parseLayout, useUi } from "../store/ui";
import { initWorkspace, useWorkspace } from "../store/workspace";
import { Welcome } from "../welcome/Welcome";
import { Shell } from "./Shell";

let started = false;

/** 패널 배치: 앱 설정에서 읽어 적용하고, 바뀌면 (끄는 동안 몰아서) 다시 쓴다 */
function initLayout(): void {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let loaded = false;
  void window.kookabug.app
    .layoutGet()
    .then((saved) => {
      if (saved !== null) useUi.setState(parseLayout(saved));
    })
    .catch(() => {})
    .finally(() => {
      loaded = true;
    });
  useUi.subscribe((s, prev) => {
    if (!loaded) return;
    const next = layoutOf(s);
    const before = layoutOf(prev);
    if ((Object.keys(next) as (keyof typeof next)[]).every((k) => next[k] === before[k])) return;
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = null;
      void window.kookabug.app.layoutSet(layoutOf(useUi.getState())).catch(() => {});
    }, 250);
  });
}

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
    initLayout();
    // 창 닫기(X·끝내기·OS 닫기) 전에 저장 안 된 그래프를 묻는다 (주 프로세스 close-guard.ts)
    window.kookabug.on("app.closeRequested", () => {
      void confirmLeaveDirty().then((ok) => window.kookabug.app.closeAnswer(ok));
    });
    void window.kookabug.app.closeGuard(true);
  }, []);
  return root === null ? <Welcome /> : <Shell />;
}
