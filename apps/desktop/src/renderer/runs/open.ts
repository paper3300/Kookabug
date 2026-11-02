// 실행 하나를 기록 뷰어 RUN 탭으로 연다 (실행 목록 클릭, 상태 바·실행 로그의 "실패 보기"). 열면 실패 노드로
// 바로 이동한다 (runIndexStore.open → failureJump)
import { displayName } from "../explorer/tree";
import { openRunTab } from "../store/tabs";
import { runIndexModel } from "./runIndexStore";
import { shortIds, useRunList } from "./runListStore";

/** 목록에서 겹치지 않는 짧은 실행 ID (C24) */
export function shortIdOf(runId: string): string {
  return shortIds([...useRunList.getState().runs.map((r) => r.run_id), runId]).get(runId) ?? runId.slice(0, 4);
}

export function runTabTitle(runId: string, testTitle: string): string {
  return `#${shortIdOf(runId)} ${testTitle}`;
}

/** 목록·"실패 보기": 이미 열린 탭이어도 최신 실패 사슬로 다시 이동한다 */
export function openRun(runId: string, graph: string): void {
  openRunTab(runId, runTabTitle(runId, displayName(graph)));
  void runIndexModel.open(runId, true);
}
