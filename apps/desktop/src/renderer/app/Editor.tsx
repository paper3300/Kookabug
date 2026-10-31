// 에디터 영역 (시안 Main): 탭(TEST·SUB·TARGET 글자)·경로 표시줄·내용. 그래프 캔버스는 T8, target 편집기는
// T12가 탭 내용으로 붙인다. 툴바(프로필·실행)는 T11
import type { ReactNode } from "react";
import { activateTab, closeTab, tabBadge, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { LogoMark } from "../theme/icons";
import css from "./shell.module.css";

function Tabs() {
  const tabs = useTabs((s) => s.tabs);
  const active = useTabs((s) => s.active);
  return (
    <div role="tablist" aria-label="열린 파일" className={css.tabs} data-part="tabs">
      {tabs.map((tab) => {
        const badge = tabBadge(tab);
        const selected = tab.path === active;
        return (
          <div key={tab.path} role="tab" aria-selected={selected} data-path={tab.path} className={css.tab} title={tab.path}>
            <button type="button" className={css.tabLabel} onClick={() => activateTab(tab.path)}>
              <span className={`${css.kind} ${badge.tone === "target" ? css.kindTarget : css.kindTest}`}>{badge.text}</span>
              {tab.title}
            </button>
            <button type="button" aria-label="탭 닫기" className={css.tabClose} onClick={() => closeTab(tab.path)}>
              ×
            </button>
          </div>
        );
      })}
    </div>
  );
}

function Breadcrumb() {
  const name = useWorkspace((s) => s.name);
  const active = useTabs((s) => s.active);
  const parts = active === null || name === null ? [] : [name, ...active.split("/")];
  return (
    <div aria-label="경로" className={css.breadcrumb} data-part="breadcrumb">
      {parts.map((p, i) => (
        <span key={i} style={{ display: "contents" }}>
          {i > 0 && <span aria-hidden="true">›</span>}
          <span className={i === parts.length - 1 ? css.breadcrumbLast : undefined}>{p}</span>
        </span>
      ))}
    </div>
  );
}

export function Editor({ children }: { children?: ReactNode }) {
  const active = useTabs((s) => s.active);
  return (
    <main className={css.editorMain}>
      <Tabs />
      <Breadcrumb />
      {active === null ? (
        <div className={css.editorEmpty}>
          <LogoMark className={css.editorEmptyLogo} cutout="var(--kb-editor-bg)" width={110} height={96} />
          <span>
            <span className={css.kbd}>Ctrl+P</span> 파일 빠른 열기
          </span>
        </div>
      ) : (
        <div className={css.canvas} data-part="canvas" data-path={active} />
      )}
      {children}
    </main>
  );
}
