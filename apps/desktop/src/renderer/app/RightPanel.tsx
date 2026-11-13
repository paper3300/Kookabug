// 오른쪽 패널 (M5 계획 3.10, 시안 Main): 속성 | 에이전트 탭. 기본 폭 320px(M2 U1), 왼쪽 끝을 끌어 폭 조절, 접기 가능.
// 프로젝트를 열면 처음부터 보인다(2026-11-09 사용자 요청). UX6: 모든 탭에서 보인다(TARGET·REC 포함).
// 고르는 자리(목록·타임라인·캔버스)는 그 탭에 두고, 고른 것의 정보·동작은 모두 속성 탭에 그린다 (UX4·UX6). 속성 탭은 지금
// 활성 탭이 고른 것만 그린다 — 탭을 바꾸면 그 탭에서 고른 것으로 바뀐다(선택은 탭마다 각 저장소가 기억한다)
// 폭은 창 폭의 50%까지, 탭 종류별로 마지막 폭을 기억한다 (store/ui.ts widthKey)
import { AgentPanel } from "../agent/AgentPanel";
import { pendingCount, useAgent } from "../agent/agentStore";
import { InspectorContent } from "../inspector/Inspector";
import { RecProps } from "../recorder/RecProps";
import { ReportProps } from "../reports/ReportsTab";
import { RunStepProps } from "../runs/RunTab";
import { ScreenProps } from "../screens/ScreenSidebar";
import { TargetProps } from "../target/TargetEditor";
import css from "../inspector/inspector.module.css";
import { useTabs, type EditorTab } from "../store/tabs";
import { inspectorWidthOf, setInspectorWidth, useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { Resizer } from "./Resizer";

/** 오른쪽 패널 폭 최대: 창 폭의 50% (UX6) */
export const RIGHT_MAX_FRACTION = 0.5;
/** 그리는 폭 상한 (왼쪽 손잡이 1px 포함) */
export const RIGHT_MAX_CSS = `calc(${RIGHT_MAX_FRACTION * 100}vw + 1px)`;

/** 속성 탭 내용: 지금 활성 탭의 종류대로 */
export function PropsContent({ tab }: { tab: Pick<EditorTab, "kind" | "path" | "runId"> | undefined }) {
  switch (tab?.kind) {
    case "map":
      return <ScreenProps />;
    case "run":
      return tab.runId !== undefined ? <RunStepProps runId={tab.runId} /> : <InspectorContent />;
    case "reports":
      return <ReportProps />;
    case "rec":
      return <RecProps />;
    case "target":
      return <TargetProps path={tab.path} />;
    default:
      return <InspectorContent />;
  }
}

export function RightPanel() {
  const root = useWorkspace((s) => s.root);
  const active = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  const kind = active?.kind;
  const open = useUi((s) => s.inspectorOpen);
  const tab = useUi((s) => s.rightTab);
  const waiting = useAgent(pendingCount);
  const width = useUi((s) => inspectorWidthOf(s, kind));
  if (root === null) return null;
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
    <aside
      aria-label={label}
      className={css.inspector}
      // 기억한 폭(선호)과 그리는 폭을 나눈다: 창을 줄이거나 큰 창에서 저장한 배치를 작은 창에서 열어도 창 폭의 50%를 넘지 않는다
      style={{ ...(width === null ? {} : { flexBasis: width + 1 }), maxWidth: RIGHT_MAX_CSS }}
      data-part="inspector"
      data-open="true"
      data-tab={tab}
      data-kind={kind ?? ""}
    >
      <Resizer
        edge="left"
        label="오른쪽 패널 폭"
        min={260}
        max={10_000}
        maxFraction={RIGHT_MAX_FRACTION}
        onWidth={(w) => setInspectorWidth(kind, w)}
        onCollapse={() => useUi.setState({ inspectorOpen: false })}
      />
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
      {tab === "agent" ? <AgentPanel /> : <PropsContent tab={active} />}
    </aside>
  );
}
