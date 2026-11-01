// 실행 툴바 (시안 Main 탭 줄 오른쪽, M2 계획 2.11): 프로필 고르기(시안 "대상" 자리, U4)·실행 ▶·정지 ■.
// 녹화·에디터 분할·디버그 툴바(멈춤·Step)는 숨긴다 (U3). 검증 오류로 실행을 막으면 "검증 오류 N개"를 띄운다
import { useTabs } from "../store/tabs";
import { useUi } from "../store/ui";
import { useWorkspace } from "../store/workspace";
import { PlayIcon, StopIcon } from "../theme/icons";
import { runAvailability, type RunAvailability } from "./commands";
import css from "./run.module.css";
import { runModel, useRun } from "./runStore";

/** 실행·정지 활성 조건 (툴바·메뉴가 같이 쓴다) */
export function useRunAvailability(): RunAvailability {
  const tab = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  const connected = useWorkspace((s) => s.daemon.status === "connected");
  const running = useRun((s) => s.current?.phase === "running");
  const starting = useRun((s) => s.starting);
  return runAvailability({ tab, connected, running, starting });
}

function availabilityNow(): RunAvailability {
  const { active, tabs } = useTabs.getState();
  const run = useRun.getState();
  return runAvailability({
    tab: tabs.find((t) => t.path === active),
    connected: useWorkspace.getState().daemon.status === "connected",
    running: run.current?.phase === "running",
    starting: run.starting,
  });
}

/** 실행 명령 (툴바 ▶·메뉴 실행·F5): 활성 조건이 맞을 때만 지금 탭을 실행한다 */
export function runActive(): void {
  const now = availabilityNow();
  if (now.canRun && now.path !== null) void runModel.start(now.path);
}

/** 정지 명령 (툴바 ■·메뉴 정지·Shift+F5) */
export function stopActive(): void {
  if (availabilityNow().canStop) void runModel.cancel();
}

export function RunToolbar() {
  const tab = useTabs((s) => s.tabs.find((t) => t.path === s.active));
  const profiles = useWorkspace((s) => s.info?.profiles);
  const current = useRun((s) => s.current);
  const blocked = useRun((s) => s.blocked);
  const profile = useRun((s) => s.profile);
  const running = current?.phase === "running";
  const starting = useRun((s) => s.starting);
  const graph = tab?.kind === "graph" ? tab : undefined;
  const { canRun, canStop, runTitle } = useRunAvailability();
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
        onClick={runActive}
      >
        <PlayIcon />
      </button>
      <button
        type="button"
        aria-label="정지"
        title="실행 취소 (Shift+F5)"
        className={`${css.toolButton} ${css.stop}`}
        disabled={!canStop}
        onClick={stopActive}
      >
        <StopIcon />
      </button>
    </div>
  );
}
