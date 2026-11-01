// 에디터 영역 (시안 Main): 탭(TEST·SUB·TARGET 글자, 저장 안 됨 ●)·경로 표시줄·문서 띠(저장 충돌·저장 실패)·
// 내용. 그래프 탭은 캔버스(T8), target 편집기는 T12가 탭 내용으로 붙인다. 탭 줄 오른쪽은 실행 툴바(T11)
import type { ReactNode } from "react";
import { GraphCanvas } from "../graph/Canvas";
import { RunToolbar } from "../run/Toolbar";
import { useRun } from "../run/runStore";
import { editedSinceRun } from "../run/view";
import { requestCloseTab } from "../store/editing";
import {
  CONFLICT_DELETED,
  dismissConflict,
  dismissSaveError,
  reloadDoc,
  saveDoc,
  useDocuments,
} from "../store/documents";
import { ask } from "../store/dialog";
import { activateTab, tabBadge, useTabs } from "../store/tabs";
import { useWorkspace } from "../store/workspace";
import { LogoMark } from "../theme/icons";
import css from "./shell.module.css";

function Tabs() {
  const tabs = useTabs((s) => s.tabs);
  const active = useTabs((s) => s.active);
  const docs = useDocuments((s) => s.docs);
  return (
    <div role="tablist" aria-label="열린 파일" className={css.tabs} data-part="tabs">
      {tabs.map((tab) => {
        const badge = tabBadge(tab);
        const selected = tab.path === active;
        const dirty = docs.get(tab.path)?.dirty === true;
        return (
          <div
            key={tab.path}
            role="tab"
            aria-selected={selected}
            data-path={tab.path}
            data-dirty={dirty}
            className={css.tab}
            title={tab.path}
          >
            <button type="button" className={css.tabLabel} onClick={() => activateTab(tab.path)}>
              <span className={`${css.kind} ${badge.tone === "target" ? css.kindTarget : css.kindTest}`}>{badge.text}</span>
              {tab.title}
            </button>
            <button
              type="button"
              aria-label={dirty ? "탭 닫기 (저장 안 됨)" : "탭 닫기"}
              className={css.tabClose}
              data-dirty={dirty}
              onClick={() => void requestCloseTab(tab.path)}
            >
              {dirty ? "●" : "×"}
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
  const run = useRun((s) => s.current);
  const doc = useDocuments((s) => (active === null ? undefined : s.docs.get(active)));
  const parts = active === null || name === null ? [] : [name, ...active.split("/")];
  return (
    <div aria-label="경로" className={css.breadcrumb} data-part="breadcrumb">
      {parts.map((p, i) => (
        <span key={i} style={{ display: "contents" }}>
          {i > 0 && <span aria-hidden="true">›</span>}
          <span className={i === parts.length - 1 ? css.breadcrumbLast : undefined}>{p}</span>
        </span>
      ))}
      {editedSinceRun(run, doc) && (
        <span className={css.runSnapshot} data-part="run-snapshot" title="실행은 시작할 때 저장된 파일의 스냅샷으로 돈다">
          실행은 저장된 버전 기준
        </span>
      )}
    </div>
  );
}

async function reloadFromDisk(path: string, dirty: boolean): Promise<void> {
  if (dirty) {
    const r = await ask({
      title: "편집을 버리고 디스크 버전을 다시 열까요?",
      message: "저장하지 않은 변경과 실행 취소 기록이 사라져요.",
      buttons: [
        { label: "다시 열기", value: "reload", primary: true },
        { label: "취소", value: "cancel" },
      ],
      cancelValue: "cancel",
    });
    if (r.value !== "reload") return;
  }
  await reloadDoc(path);
}

/** 저장 충돌·저장 실패 띠 (M2 계획 2.6 "충돌") */
function DocBanner({ path }: { path: string }) {
  const doc = useDocuments((s) => s.docs.get(path));
  if (doc === undefined) return null;
  if (doc.conflict !== null) {
    const deleted = doc.conflict === CONFLICT_DELETED;
    return (
      <div
        role="alert"
        aria-label="저장 충돌"
        data-part="conflict-banner"
        className={`${css.banner} ${css.bannerWarn}`}
      >
        <span className={css.bannerText}>
          {deleted ? "디스크에서 이 파일이 지워졌어요." : "디스크의 이 파일이 밖에서 바뀌었어요."}
          {doc.dirty ? " 저장하지 않은 편집이 있어요." : ""}
        </span>
        {!deleted && (
          <button type="button" className={css.bannerButton} onClick={() => void reloadFromDisk(path, doc.dirty)}>
            디스크 버전 다시 열기
          </button>
        )}
        <button type="button" className={css.bannerButton} onClick={() => void saveDoc(path, { force: true })}>
          내 편집으로 덮어쓰기
        </button>
        <button type="button" className={css.bannerButton} onClick={() => dismissConflict(path)}>
          닫기
        </button>
      </div>
    );
  }
  if (doc.saveError !== null) {
    return (
      <div role="alert" aria-label="저장 실패" data-part="save-error" className={`${css.banner} ${css.bannerError}`}>
        <span className={css.bannerText}>{doc.saveError}</span>
        <button type="button" className={css.bannerButton} onClick={() => dismissSaveError(path)}>
          닫기
        </button>
      </div>
    );
  }
  return null;
}

export function Editor({ children }: { children?: ReactNode }) {
  const active = useTabs((s) => s.active);
  const activeTab = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  return (
    <main className={css.editorMain}>
      <div className={css.tabbar} data-part="tabbar">
        <Tabs />
        <RunToolbar />
      </div>
      <Breadcrumb />
      {active !== null && activeTab?.kind === "graph" && <DocBanner path={active} />}
      {active === null ? (
        <div className={css.editorEmpty}>
          <LogoMark className={css.editorEmptyLogo} cutout="var(--kb-editor-bg)" width={110} height={96} />
          <span>
            <span className={css.kbd}>Ctrl+P</span> 파일 빠른 열기
          </span>
        </div>
      ) : activeTab?.kind === "graph" ? (
        <GraphCanvas key={active} path={active} />
      ) : (
        <div className={css.canvas} data-part="canvas" data-path={active} />
      )}
      {children}
    </main>
  );
}
