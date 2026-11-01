// 실행 툴바 (시안 Main 탭 줄 오른쪽, M2 계획 2.11): 프로필 고르기(시안 "대상" 자리, U4)·실행 ▶·정지 ■.
// 녹화·에디터 분할·디버그 툴바(멈춤·Step)는 숨긴다 (U3). 검증 오류로 실행을 막으면 "검증 오류 N개"를 띄운다
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { PlayIcon, StopIcon } from "../theme/icons";
import css from "./run.module.css";
import { runModel, useRun } from "./runStore";

/** 지금 탭이 실행할 수 있는 그래프면 그 경로 (서브그래프는 테스트에서 불러 실행한다) */
export function runnablePath(): string | null {
  const { active, tabs } = useTabs.getState();
  const tab = tabs.find((t) => t.path === active);
  return tab?.kind === "graph" && tab.graphKind !== "subgraph" ? tab.path : null;
}

export function RunToolbar() {
  const tab = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const profiles = useWorkspace((s) => s.info?.profiles);
  const current = useRun((s) => s.current);
  const starting = useRun((s) => s.starting);
  const blocked = useRun((s) => s.blocked);
  const profile = useRun((s) => s.profile);
  const running = current?.phase === "running";
  const graph = tab?.kind === "graph" ? tab : undefined;
  const subgraph = graph?.graphKind === "subgraph";
  const canRun = graph !== undefined && !subgraph && connected && !running && starting === null;
  const runTitle =
    graph === undefined
      ? "그래프 탭에서 실행해요"
      : subgraph
        ? "서브그래프는 테스트에서 불러 실행해요"
        : running
          ? "실행이 끝나면 다시 실행할 수 있어요"
          : "실행 (F5)";
  return (
    <div
      role="toolbar"
      aria-label="실행"
      className={css.toolbar}
      data-part="run-toolbar"
      data-phase={starting !== null ? "starting" : running ? "running" : current !== null ? "ended" : "idle"}
      data-run-id={current?.runId ?? ""}
      data-verdict={current?.outcome?.verdict ?? ""}
    >
      {blocked !== null && graph !== undefined && blocked.path === graph.path && (
        <button
          type="button"
          className={css.blocked}
          data-part="run-blocked"
          data-kind={blocked.kind}
          title={blocked.kind === "validation" ? "문제 패널 열기" : blocked.message}
          onClick={() => {
            if (blocked.kind === "validation") useUi.setState({ panelTab: "problems" });
            else runModel.dismissBlocked();
          }}
        >
          {blocked.message}
        </button>
      )}
      <label className={css.profile}>
        프로필
        <select
          aria-label="실행 프로필"
          className={css.select}
          value={profile ?? ""}
          disabled={running}
          onChange={(e) => runModel.setProfile(e.target.value === "" ? null : e.target.value)}
        >
          <option value="">기본</option>
          {(profiles ?? []).map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </label>
      <button
        type="button"
        aria-label="실행 F5"
        title={runTitle}
        className={`${css.toolButton} ${css.play}`}
        disabled={!canRun}
        onClick={() => {
          if (graph !== undefined) void runModel.start(graph.path);
        }}
      >
        <PlayIcon />
      </button>
      <button
        type="button"
        aria-label="정지"
        title="실행 취소"
        className={`${css.toolButton} ${css.stop}`}
        disabled={!running}
        onClick={() => void runModel.cancel()}
      >
        <StopIcon />
      </button>
    </div>
  );
}
