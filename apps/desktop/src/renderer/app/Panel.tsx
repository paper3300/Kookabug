// 하단 패널 (시안 Main): 문제·출력·실행 로그·노드 결과. 고정 데이터·터미널은 이후 (2.11).
// 출력(daemon·연결 메시지)은 T7, 문제(검증 진단)는 T8, 실행 로그·노드 결과는 T11
import { useEffect, useRef } from "react";
import { Problems, useProblems } from "../problems/Problems";
import { useUi, type PanelTab } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import css from "./shell.module.css";

const TABS: [PanelTab, string][] = [
  ["problems", "문제"],
  ["output", "출력"],
  ["runlog", "실행 로그"],
  ["result", "노드 결과"],
];

const LEVEL = { info: ["INFO", css.levelInfo], warn: ["WARN", css.levelWarn], error: ["ERROR", css.levelError] } as const;

function time(iso: string): string {
  const d = new Date(iso);
  const p = (n: number, w = 2) => String(n).padStart(w, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
}

function Output() {
  const lines = useWorkspace((s) => s.output);
  const end = useRef<HTMLDivElement>(null);
  // 본문 블록으로 쓴다: Chromium의 scrollIntoView는 Promise를 돌려주고, 효과가 그것을 돌려주면
  // React가 정리 함수로 부르다 실패한다
  useEffect(() => {
    void end.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);
  if (lines.length === 0) return <div className={css.panelEmpty}>출력이 없어요</div>;
  return (
    <>
      {lines.map((l, i) => (
        <div key={i} className={css.logLine}>
          <span className={css.logTime}>{time(l.time)}</span>
          <span className={`${css.logLevel} ${LEVEL[l.level][1]}`}>{LEVEL[l.level][0]}</span>
          <span className={css.logMessage}>{l.message}</span>
        </div>
      ))}
      <div ref={end} />
    </>
  );
}

export function Panel() {
  const tab = useUi((s) => s.panelTab);
  const problems = useProblems().length;
  return (
    <section aria-label="하단 패널" className={css.panel}>
      <div role="tablist" aria-label="하단 패널 탭" className={css.panelTabs} data-part="panel-tabs">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={css.panelTab}
            onClick={() => useUi.setState({ panelTab: id })}
          >
            {label}
            {id === "problems" && problems > 0 && (
              <span className={css.count} data-part="problem-count">
                {problems}
              </span>
            )}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={TABS.find(([id]) => id === tab)?.[1]} className={css.panelBody}>
        {tab === "output" ? (
          <Output />
        ) : tab === "problems" ? (
          <Problems />
        ) : (
          <div className={css.panelEmpty}>{tab === "runlog" ? "실행 기록이 없어요" : "고른 노드가 없어요"}</div>
        )}
      </div>
    </section>
  );
}
