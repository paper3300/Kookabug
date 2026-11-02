// 액티비티 바와 사이드바 (시안 Main·RunViewer). 액티비티 바는 탐색기·실행 기록(M3 T10)만 보인다: 화면 지도·
// 녹화·플러그인·설정은 그 단계에서 붙인다 (U3). 실행 기록 배지는 지난 열람 이후 실패 수다.
// 사이드바 아래 "노드" 섹션은 팔레트다 (T9). 워크스페이스 머리 줄 오른쪽에 "새 테스트·새 서브그래프" 단추가
// 있다 (graph.create, T9)
import { useState } from "react";
import { Explorer } from "../explorer/Explorer";
import { Palette } from "../palette/Palette";
import { RunList } from "../runs/RunList";
import { failuresSince, runListModel, useRunList } from "../runs/runListStore";
import runsCss from "../runs/runs.module.css";
import { createGraphInteractive } from "../store/newGraph";
import { useUi, type SideView } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { ChevronDownIcon, ChevronRightIcon, ExplorerIcon, HistoryIcon } from "../theme/icons";
import css from "./shell.module.css";

function showSide(view: SideView): void {
  useUi.setState({ sideView: view });
  if (view === "runs") {
    runListModel.markSeen();
    void runListModel.reload();
  }
}

export function ActivityBar() {
  const view = useUi((s) => s.sideView);
  const failures = useRunList((s) => failuresSince(s.runs, s.seenAt));
  const badge = view === "runs" ? 0 : failures;
  return (
    <nav aria-label="작업 영역" className={css.activitybar}>
      <button
        type="button"
        aria-label="탐색기"
        aria-pressed={view === "explorer"}
        className={css.activityButton}
        onClick={() => showSide("explorer")}
      >
        <ExplorerIcon />
      </button>
      <button
        type="button"
        aria-label={badge > 0 ? `실행 기록, 실패 ${badge}건` : "실행 기록"}
        aria-pressed={view === "runs"}
        className={css.activityButton}
        data-part="activity-runs"
        onClick={() => showSide("runs")}
      >
        <HistoryIcon />
        {badge > 0 && (
          <span className={runsCss.activityBadge} data-part="activity-badge">
            {badge}
          </span>
        )}
      </button>
    </nav>
  );
}

function Section({
  title,
  top,
  open,
  onToggle,
  actions,
}: {
  title: string;
  top?: boolean;
  open: boolean;
  onToggle(): void;
  actions?: React.ReactNode;
}) {
  return (
    <div className={`${css.sectionRow} ${top ? css.sectionHeaderTop : ""}`}>
      <button type="button" aria-expanded={open} className={css.sectionHeader} onClick={onToggle}>
        {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
        <span className={css.sectionTitle}>{title}</span>
      </button>
      {actions}
    </div>
  );
}

function NewGraphButtons() {
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  return (
    <span className={css.sectionActions}>
      <button
        type="button"
        aria-label="새 테스트"
        title="새 테스트"
        className={css.sectionAction}
        disabled={!connected}
        onClick={() => void createGraphInteractive("test")}
      >
        +T
      </button>
      <button
        type="button"
        aria-label="새 서브그래프"
        title="새 서브그래프"
        className={css.sectionAction}
        disabled={!connected}
        onClick={() => void createGraphInteractive("subgraph")}
      >
        +S
      </button>
    </span>
  );
}

export function Sidebar() {
  const name = useWorkspace((s) => s.name);
  const view = useUi((s) => s.sideView);
  const [filesOpen, setFilesOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  if (view === "runs") {
    return (
      <aside aria-label="사이드바" className={css.sidebar}>
        <div className={css.sidebarInner} data-part="sidebar" data-view="runs">
          <div className={css.sidebarHeader} data-part="sidebar-header">
            <span>실행 기록</span>
          </div>
          <RunList />
        </div>
      </aside>
    );
  }
  return (
    <aside aria-label="사이드바" className={css.sidebar}>
      <div className={css.sidebarInner} data-part="sidebar">
        <div className={css.sidebarHeader} data-part="sidebar-header">
          <span>탐색기</span>
        </div>
        <Section
          title={name ?? ""}
          open={filesOpen}
          onToggle={() => setFilesOpen(!filesOpen)}
          actions={<NewGraphButtons />}
        />
        {filesOpen && (
          <div className={css.explorer}>
            <Explorer />
          </div>
        )}
        <section aria-label="노드" className={css.palette}>
          <Section title="노드" top open={paletteOpen} onToggle={() => setPaletteOpen(!paletteOpen)} />
          {paletteOpen && <Palette />}
        </section>
      </div>
    </aside>
  );
}
