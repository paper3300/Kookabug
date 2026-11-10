// 액티비티 바와 사이드바 (시안 Main·RunViewer·Recorder). 액티비티 바는 탐색기·실행 기록(M3 T10)·녹화(M4 T9)·
// 플러그인(M6 B5)이 보인다: 화면 지도·설정은 그 단계에서 붙인다 (U3). 실행 기록 배지는 지난 열람 이후 실패 수,
// 플러그인 배지는 준비 필요·조건 다름 수다.
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
import { RecorderSidebar } from "../recorder/RecorderSidebar";
import { attentionCount } from "../plugins/model";
import { PluginsSidebar } from "../plugins/PluginsSidebar";
import { reloadPlugins, usePlugins } from "../plugins/pluginStore";
import { ChevronDownIcon, ChevronRightIcon, ExplorerIcon, HistoryIcon, MapIcon, PluginIcon, RecordIcon } from "../theme/icons";
import { activeSession, loadMap, useMap } from "../screens/mapStore";
import { ScreenSidebar } from "../screens/ScreenSidebar";
import { Resizer } from "./Resizer";
import css from "./shell.module.css";

export function showSide(view: SideView): void {
  useUi.setState({ sideView: view, sidebarOpen: true });
  if (view === "runs") {
    runListModel.markSeen();
    void runListModel.reload();
  }
  if (view === "plugins") void reloadPlugins();
  if (view === "screens") void loadMap();
}

/** 액티비티 아이콘 누르기: 펼친 채 같은 보기면 접고, 아니면 그 보기로 펼친다 (VS Code 관례) */
function onActivity(view: SideView): void {
  const { sideView, sidebarOpen } = useUi.getState();
  if (sidebarOpen && sideView === view) {
    useUi.setState({ sidebarOpen: false });
    return;
  }
  useUi.setState({ sidebarOpen: true });
  showSide(view);
}

export function ActivityBar() {
  const shown = useUi((s) => s.sideView);
  const open = useUi((s) => s.sidebarOpen);
  const view = open ? shown : null;
  const failures = useRunList((s) => failuresSince(s.runs, s.seenAt));
  const badge = view === "runs" ? 0 : failures;
  const pluginAttention = usePlugins((s) => attentionCount(s.list));
  const exploring = useMap((s) => activeSession(s.sessions) !== null);
  return (
    <nav aria-label="작업 영역" className={css.activitybar}>
      <button
        type="button"
        aria-label="탐색기"
        aria-pressed={view === "explorer"}
        className={css.activityButton}
        onClick={() => onActivity("explorer")}
      >
        <ExplorerIcon />
      </button>
      <button
        type="button"
        aria-label={exploring ? "화면 지도, 에이전트 탐색 중" : "화면 지도"}
        aria-pressed={view === "screens"}
        className={css.activityButton}
        data-part="activity-screens"
        onClick={() => onActivity("screens")}
      >
        <MapIcon />
        {exploring && <span className={css.activityExploreDot} data-part="activity-explore-dot" />}
      </button>
      <button
        type="button"
        aria-label={badge > 0 ? `실행 기록, 실패 ${badge}건` : "실행 기록"}
        aria-pressed={view === "runs"}
        className={css.activityButton}
        data-part="activity-runs"
        onClick={() => onActivity("runs")}
      >
        <HistoryIcon />
        {badge > 0 && (
          <span className={runsCss.activityBadge} data-part="activity-badge">
            {badge}
          </span>
        )}
      </button>
      <button
        type="button"
        aria-label="녹화"
        aria-pressed={view === "recorder"}
        className={css.activityButton}
        data-part="activity-recorder"
        onClick={() => onActivity("recorder")}
      >
        <RecordIcon />
      </button>
      <button
        type="button"
        aria-label={pluginAttention > 0 ? `플러그인, 준비 필요 ${pluginAttention}` : "플러그인"}
        aria-pressed={view === "plugins"}
        className={css.activityButton}
        data-part="activity-plugins"
        onClick={() => onActivity("plugins")}
      >
        <PluginIcon />
        {pluginAttention > 0 && (
          <span className={`${runsCss.activityBadge} ${css.activityBadgeWarn}`} data-part="activity-plugins-badge">
            {pluginAttention}
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

function SidebarContent() {
  const name = useWorkspace((s) => s.name);
  const view = useUi((s) => s.sideView);
  const [filesOpen, setFilesOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
  if (view === "recorder") {
    return (
      <>
        <div className={css.sidebarInner} data-part="sidebar" data-view="recorder">
          <RecorderSidebar />
        </div>
      </>
    );
  }
  if (view === "plugins") {
    return (
      <>
        <div className={css.sidebarInner} data-part="sidebar" data-view="plugins">
          <PluginsSidebar />
        </div>
      </>
    );
  }
  if (view === "screens") {
    return (
      <>
        <div className={css.sidebarInner} data-part="sidebar" data-view="screens">
          <div className={css.sidebarHeader} data-part="sidebar-header">
            <span>화면 지도</span>
          </div>
          <ScreenSidebar />
        </div>
      </>
    );
  }
  if (view === "runs") {
    return (
      <>
        <div className={css.sidebarInner} data-part="sidebar" data-view="runs">
          <div className={css.sidebarHeader} data-part="sidebar-header">
            <span>실행 기록</span>
          </div>
          <RunList />
        </div>
      </>
    );
  }
  return (
    <>
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
    </>
  );
}

/** 왼쪽 사이드바: 펼쳤을 때만, 오른쪽 끝을 끌어 폭을 바꾼다 (녹화 사이드바 폭은 따로 기억) */
export function Sidebar() {
  const view = useUi((s) => s.sideView);
  const open = useUi((s) => s.sidebarOpen);
  const recorder = view === "recorder";
  const width = useUi((s) => (recorder ? s.recorderSidebarWidth : s.sidebarWidth));
  if (!open) return null;
  return (
    <aside
      aria-label="사이드바"
      className={recorder ? `${css.sidebar} ${css.sidebarRecorder}` : css.sidebar}
      style={width === null ? undefined : { flexBasis: width + 1 }}
      data-part="sidebar-box"
    >
      <SidebarContent />
      <Resizer
        edge="right"
        label="사이드바 폭"
        min={recorder ? 260 : 170}
        max={recorder ? 720 : 640}
        onWidth={(w) => useUi.setState(recorder ? { recorderSidebarWidth: w } : { sidebarWidth: w })}
        onCollapse={() => useUi.setState({ sidebarOpen: false })}
      />
    </aside>
  );
}
