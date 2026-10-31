// 액티비티 바와 사이드바 (시안 Main). 액티비티 바는 탐색기만 보인다: 화면 지도·실행 기록·녹화·
// 플러그인·설정은 그 단계에서 붙인다 (U3). 사이드바 아래 "노드" 섹션은 팔레트다 (T9).
// 워크스페이스 머리 줄 오른쪽에 "새 테스트·새 서브그래프" 단추가 있다 (graph.create, T9)
import { useState } from "react";
import { Explorer } from "../explorer/Explorer";
import { Palette } from "../palette/Palette";
import { createGraphInteractive } from "../store/newGraph";
import { useWorkspace } from "../store/workspace";
import { ChevronDownIcon, ChevronRightIcon, ExplorerIcon } from "../theme/icons";
import css from "./shell.module.css";

export function ActivityBar() {
  return (
    <nav aria-label="작업 영역" className={css.activitybar}>
      <button type="button" aria-label="탐색기" aria-pressed="true" className={css.activityButton}>
        <ExplorerIcon />
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
  const [filesOpen, setFilesOpen] = useState(true);
  const [paletteOpen, setPaletteOpen] = useState(true);
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
