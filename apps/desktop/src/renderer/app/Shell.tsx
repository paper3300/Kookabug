// 앱 틀 (M2 계획 2.11): 타이틀 바 · 연결 띠 · 액티비티 바 · 사이드바 · 에디터 · 하단 패널 · 상태 바.
// 오른쪽 에이전트 패널 자리는 속성 편집기(T10)가 쓴다
import { useEffect } from "react";
import { Inspector } from "../inspector/Inspector";
import { runActive, stopActive } from "../run/Toolbar";
import { getTarget, saveBlocker, saveTarget, targetDirty } from "../target/targetStore";
import { useDialog } from "../store/dialog";
import { redoEdit, saveDoc, undoEdit } from "../store/documents";
import { confirmLeaveDirty, requestCloseTab } from "../store/editing";
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { addLeaveGuard, openFolder, useWorkspace } from "../store/workspace";
import { Banner, OpenErrorBanner } from "./Banner";
import { Dialog } from "./Dialog";
import { Editor } from "./Editor";
import { Panel } from "./Panel";
import { QuickOpen } from "./QuickOpen";
import css from "./shell.module.css";
import { ActivityBar, Sidebar } from "./Sidebar";
import { StatusBar } from "./StatusBar";
import { TitleBar } from "./TitleBar";

/** 글자 입력 칸 안이면 실행 취소·다시 실행은 그 칸의 것이다 */
function inTextField(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT";
}

/** 지금 탭이 그래프면 그 경로 */
export function activeGraph(): string | null {
  const { active, tabs } = useTabs.getState();
  return tabs.find((t) => t.path === active)?.kind === "graph" ? active : null;
}

/** 지금 탭이 TARGET이면 그 경로 */
function activeTarget(): string | null {
  const { active, tabs } = useTabs.getState();
  return tabs.find((t) => t.path === active)?.kind === "target" ? active : null;
}

function useShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // 대화 상자가 떠 있으면 뒤쪽 화면의 단축키(저장·실행 취소·탭 닫기 등)는 듣지 않는다
      if (useDialog.getState().current !== null) return;
      // F5 실행, Shift+F5 정지 (시안 툴바 "실행 F5")
      if (e.key === "F5" && !e.ctrlKey && !e.altKey && !e.metaKey) {
        e.preventDefault();
        if (e.shiftKey) stopActive();
        else runActive();
        return;
      }
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
        if (active !== null) void requestCloseTab(active);
      } else if (key === "s" && !e.shiftKey) {
        e.preventDefault();
        const path = activeGraph();
        if (path !== null) void saveDoc(path);
        const target = activeTarget();
        if (target !== null) {
          const doc = getTarget(target);
          if (doc !== undefined && saveBlocker(doc) === null && (targetDirty(doc) || doc.conflict !== null)) void saveTarget(target);
        }
      } else if ((key === "z" || key === "y") && !inTextField(e.target)) {
        const path = activeGraph();
        if (path === null) return;
        e.preventDefault();
        if (key === "z" && !e.shiftKey) undoEdit(path);
        else redoEdit(path);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

export function Shell() {
  useShortcuts();
  useEffect(() => addLeaveGuard(confirmLeaveDirty), []);
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
        <Inspector />
      </div>
      <StatusBar />
      <QuickOpen />
      <Dialog />
    </div>
  );
}
