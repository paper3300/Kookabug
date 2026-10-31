// 앱 틀 (M2 계획 2.11): 타이틀 바 · 연결 띠 · 액티비티 바 · 사이드바 · 에디터 · 하단 패널 · 상태 바.
// 오른쪽 에이전트 패널 자리는 속성 편집기(T10)가 쓴다
import { useEffect } from "react";
import { closeTab, useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { openFolder, useWorkspace } from "../store/workspace";
import { Banner, OpenErrorBanner } from "./Banner";
import { Editor } from "./Editor";
import { Panel } from "./Panel";
import { QuickOpen } from "./QuickOpen";
import css from "./shell.module.css";
import { ActivityBar, Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { TitleBar } from "./TitleBar";

function useShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.ctrlKey || e.altKey || e.metaKey) return;
      const key = e.key.toLowerCase();
      if (key === "p" && !e.shiftKey) {
        e.preventDefault();
        if (useWorkspace.getState().root !== null) useUi.setState({ quickOpen: true });
      } else if (key === "o" && !e.shiftKey) {
        e.preventDefault();
        void openFolder();
      } else if (key === "w" && !e.shiftKey) {
        e.preventDefault();
        const active = useTabs.getState().active;
        if (active !== null) closeTab(active);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function Shell() {
  useShortcuts();
  return (
    <div className={css.shell} data-screen="shell">
      <TitleBar />
      <Banner />
      <OpenErrorBanner />
      <div className={css.body}>
        <ActivityBar />
        <Sidebar />
        <div className={css.editor}>
          <Editor />
          <Panel />
        </div>
      </div>
      <StatusBar />
      <QuickOpen />
    </div>
  );
}
