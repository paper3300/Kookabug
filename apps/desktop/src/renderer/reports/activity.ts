// 진행 중 작업의 활동 목록 (UX1 U3): `jobs.activity`(사람 전용 읽기)의 한 줄 → 한국어 한 줄, 머리 요약, 이어 읽기 합치기.
// 대상은 daemon이 정한 짧은 글(경로·ID·창 제목)뿐이다 — 값·비밀값은 오지 않는다

export interface ActivityEntry {
  seq: number;
  at: string;
  tool: string;
  result: string;
  target: string;
}

export interface ActivityUsed {
  minutes: number;
  runs: number;
  tool_calls: number;
}

const TOOL_TEXT: Record<string, string> = {
  kb_project_info: "설정 확인",
  kb_toolset_enable: "도구 켜기",
  kb_knowledge_search: "지식 찾기",
  kb_knowledge_get: "지식 읽기",
  kb_knowledge_apply: "지식 쓰기 (주장·질문)",
  kb_wiki_write: "위키 쓰기",
  kb_report_note: "보고 요약 남김",
  kb_case_list: "사건 목록 보기",
  kb_case_get: "사건 읽기",
  kb_case_open: "사건 열기",
  kb_case_update: "사건 고치기",
  kb_triage_signals: "실패 신호 보기",
  kb_evidence_pin: "증거 고정",
  kb_adopt_request: "채택 요청",
  kb_graph_list: "테스트 목록 보기",
  kb_graph_get: "테스트 읽기",
  kb_graph_create: "테스트 만들기",
  kb_graph_patch: "테스트 고치기",
  kb_graph_validate: "테스트 검사",
  kb_node_search: "노드 찾기",
  kb_target_create: "찾기 대상 만들기",
  kb_run_start: "테스트 실행",
  kb_run_status: "실행 상태 보기",
  kb_run_events: "실행 기록 읽기",
  kb_run_cancel: "실행 취소",
  kb_run_compare: "실행 비교",
  kb_run_artifact_get: "실행 결과물 읽기",
  kb_log_search: "기록 찾기",
  kb_screen_capture: "화면 캡처",
  kb_ocr_read: "글자 읽기",
  kb_image_find: "그림 찾기",
  kb_screen_list: "화면 지도 보기",
  kb_screen_get: "화면 읽기",
  kb_screen_identify: "화면 알아보기",
  kb_screen_save: "화면 저장",
  kb_explore_start: "탐색 시작",
  kb_explore_end: "탐색 끝",
  kb_input_click: "클릭",
  kb_input_key: "키 입력",
  kb_input_type: "글자 입력",
  kb_app_launch: "게임 실행",
};

/** 도구 한 번 → "위키 쓰기: wiki/overview.md" (실패면 뒤에 "· 실패 (코드)") */
export function activityText(e: Pick<ActivityEntry, "tool" | "result" | "target">): string {
  const what = TOOL_TEXT[e.tool] ?? e.tool;
  const head = e.target !== "" ? `${what}: ${e.target}` : what;
  return e.result === "ok" ? head : `${head} · 실패 (${e.result})`;
}

/** 머리 요약: "12분 · 실행 3 · 도구 호출 41" */
export function activityHead(used: ActivityUsed | null): string {
  if (used === null) return "";
  return `${used.minutes}분 · 실행 ${used.runs} · 도구 호출 ${used.tool_calls}`;
}

/** 줄 시각 "HH:MM:SS" (UTC 표기를 이 PC 시각으로) */
export function activityTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/** 화면이 들고 있는 최대 줄 수 (오래된 것부터 버린다) */
export const ACTIVITY_KEEP = 500;

/** 이어 읽은 줄을 합친다 (같은 seq는 한 번, seq 순, 최대 ACTIVITY_KEEP) */
export function mergeActivity(prev: readonly ActivityEntry[], next: readonly ActivityEntry[]): ActivityEntry[] {
  const seen = new Set(prev.map((e) => e.seq));
  const out = [...prev, ...next.filter((e) => !seen.has(e.seq))].sort((a, b) => a.seq - b.seq);
  return out.length > ACTIVITY_KEEP ? out.slice(out.length - ACTIVITY_KEEP) : out;
}

export interface ActivityRow {
  /** 묶음의 마지막 seq (React 키) */
  seq: number;
  /** 묶음의 첫 시각 */
  at: string;
  tool: string;
  result: string;
  text: string;
  count: number;
}

/**
 * 화면 줄: 연달아 같은 도구·대상·결과는 한 줄로 묶는다. MCP 도구 하나가 daemon 메서드 여럿을 부른다
 * (예: kb_project_info → workspace.info·permissions.get·plugins.list·project.qa_info)
 */
export function collapseActivity(entries: readonly ActivityEntry[]): ActivityRow[] {
  const out: ActivityRow[] = [];
  for (const e of entries) {
    const last = out[out.length - 1];
    const text = activityText(e);
    if (last !== undefined && last.text === text && last.tool === e.tool) {
      last.count += 1;
      last.seq = e.seq;
      continue;
    }
    out.push({ seq: e.seq, at: e.at, tool: e.tool, result: e.result, text, count: 1 });
  }
  return out;
}

/** 진행 중 작업이면 폴링한다 */
export function activityLive(state: string): boolean {
  return state === "running" || state === "ending";
}

/** 폴링 간격 (ms) */
export const ACTIVITY_POLL_MS = 1_500;
