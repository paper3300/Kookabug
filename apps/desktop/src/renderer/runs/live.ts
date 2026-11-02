// 기록 뷰어를 실행 화면·탭에 잇는다 (M3 T10)
// - 실행 화면(run/runStore)이 적용한 seq를 RUN 탭 색인에 알린다: 진행 중 실행의 타임라인이 늘어난다
// - 실행이 시작·끝나면 사이드바 실행 목록 첫 쪽을 다시 읽는다
// - RUN 탭을 닫으면 그 실행 상태를 버린다
import { useRun } from "../run/runStore";
import { useTabs } from "../store/tabs";
import { runIndexModel } from "./runIndexStore";
import { runListModel } from "./runListStore";

let connected = false;

export function connectRunViewer(): void {
  if (connected) return;
  connected = true;
  let lastRun: string | null = null;
  let lastPhase: string | null = null;
  useRun.subscribe((s) => {
    const c = s.current;
    if (c === null) {
      lastRun = null;
      lastPhase = null;
      return;
    }
    runIndexModel.noteSeq(c.runId, c.trace.lastSeq, c.phase === "ended");
    if (c.runId !== lastRun || c.phase !== lastPhase) {
      lastRun = c.runId;
      lastPhase = c.phase;
      void runListModel.reload();
    }
  });
  useTabs.subscribe((s) => {
    const open = new Set(s.tabs.flatMap((t) => (t.kind === "run" && t.runId !== undefined ? [t.runId] : [])));
    for (const runId of runIndexModel.store.getState().runs.keys()) if (!open.has(runId)) runIndexModel.close(runId);
  });
}
