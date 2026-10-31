// 액티비티 바와 사이드바 (시안 Main). 액티비티 바는 탐색기만 보인다: 화면 지도·실행 기록·녹화·
// 플러그인·설정은 그 단계에서 붙인다 (U3). 사이드바 아래 "노드" 섹션은 팔레트 자리다 (T9가 채움)
import { useState } from "react";
import { Explorer } from "../explorer/Explorer";
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
}: {
  title: string;
  top?: boolean;
  open: boolean;
  onToggle(): void;
}) {
  return (
    <button
      type="button"
      aria-expanded={open}
      className={`${css.sectionHeader} ${top ? css.sectionHeaderTop : ""}`}
      onClick={onToggle}
    >
      {open ? <ChevronDownIcon /> : <ChevronRightIcon />}
      <span className={css.sectionTitle}>{title}</span>
    </button>
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
        <Section title={name ?? ""} open={filesOpen} onToggle={() => setFilesOpen(!filesOpen)} />
        {filesOpen && (
          <div className={css.explorer}>
            <Explorer />
          </div>
        )}
        <section aria-label="노드" className={css.palette}>
          <Section title="노드" top open={paletteOpen} onToggle={() => setPaletteOpen(!paletteOpen)} />
          {paletteOpen && (
            <div className={css.paletteSearch}>
              <label className={css.inputBox}>
                <input type="search" placeholder="노드 검색" aria-label="노드 검색" />
              </label>
            </div>
          )}
        </section>
      </div>
    </aside>
  );
}
