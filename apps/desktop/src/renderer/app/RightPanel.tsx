// 오른쪽 패널 (M5 계획 3.10, 시안 Main): 속성 | 에이전트 탭. 폭 320px(M2 U1), 접기 가능.
// 그래프·RUN 탭이면 늘 보이고, 그 밖 탭은 에이전트 탭을 골랐을 때만 보인다 (TARGET·REC 편집 화면 폭을 그대로 둔다)
import { AgentPanel } from "../agent/AgentPanel";
import { pendingCount, useAgent } from "../agent/agentStore";
import { InspectorContent } from "../inspector/Inspector";
import css from "../inspector/inspector.module.css";
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";

export function RightPanel() {
  const root = useWorkspace((s) => s.root);
  const kind = useTabs((s) => s.tabs.find((t) => t.path === s.active)?.kind);
  const open = useUi((s) => s.inspectorOpen);
  const tab = useUi((s) => s.rightTab);
  const waiting = useAgent(pendingCount);
  const visible = root !== null && (kind === "graph" || kind === "run" || tab === "agent");
  if (!visible) return null;
  const label = tab === "agent" ? "에이전트" : "속성";
  if (!open) {
    return (
      <aside aria-label={label} className={`${css.inspector} ${css.collapsed}`} data-part="inspector" data-open="false" data-tab={tab}>
        <button
          type="button"
          aria-label={waiting > 0 ? `속성 패널 펼치기 (승인 대기 ${waiting})` : "속성 패널 펼치기"}
          className={css.collapsedButton}
          onClick={() => useUi.setState({ inspectorOpen: true })}
        >
          {/* 접혀도 세션·카드는 그대로다: 답을 기다리는 카드 수를 남긴다 (검수 B5 M1) */}
          {waiting > 0 && (
            <span className={css.rightTabBadge} data-part="collapsed-pending" title={`승인 대기 ${waiting}`}>
              {waiting}
            </span>
          )}
          <span className={css.vertical}>{waiting > 0 ? `${label} · 승인 대기` : label}</span>
        </button>
      </aside>
    );
  }
  return (
    <aside aria-label={label} className={css.inspector} data-part="inspector" data-open="true" data-tab={tab}>
      <div className={css.header} data-part="right-tabs">
        <div role="tablist" aria-label="오른쪽 패널" className={css.rightTabs}>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "props"}
            className={css.rightTab}
            onClick={() => useUi.setState({ rightTab: "props" })}
          >
            속성
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "agent"}
            className={css.rightTab}
            data-part="agent-tab"
            onClick={() => useUi.setState({ rightTab: "agent" })}
          >
            에이전트
            {waiting > 0 && tab !== "agent" && <span className={css.rightTabBadge}>{waiting}</span>}
          </button>
        </div>
        <button
          type="button"
          aria-label="속성 패널 접기"
          className={css.iconButton}
          onClick={() => useUi.setState({ inspectorOpen: false })}
        >
          »
        </button>
      </div>
      {tab === "agent" ? <AgentPanel /> : <InspectorContent />}
    </aside>
  );
}
