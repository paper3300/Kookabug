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
  kb_source_list: "원본 목록 보기",
  kb_source_read: "원본 읽기",
  kb_setting_propose: "설정 바꾸기 제안",
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
  kb_screen_link: "화면 잇기",
  kb_explore_start: "탐색 시작",
  kb_explore_end: "탐색 끝",
  kb_input_click: "클릭",
  kb_input_key: "키 입력",
  kb_input_type: "글자 입력",
  kb_app_launch: "게임 실행",
  // UX7
  kb_explore_step: "탐색 한 걸음",
  kb_question_wait: "질문 답 기다리기",
  kb_job_progress: "단계 시작",
  kb_wiki_read: "위키 읽기",
};

/** 도구 이름 → 한국어 (모르는 도구는 이름 그대로) */
export function toolText(tool: string): string {
  return TOOL_TEXT[tool] ?? tool;
}

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

/** 목록 줄 시각 "MM-DD HH:MM" (UTC 표기를 이 PC 시각으로, UX9). 읽을 수 없으면 원문 */
export function shortTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
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
 * 화면 줄: 연달아 같은 도구·결과는 한 줄로 묶는다 ("화면 캡처 ×12", UX7). 대상이 모두 같으면 대상까지, 다르면 도구 이름만 보인다.
 * daemon은 MCP 도구 호출 하나를 한 줄로 남긴다(UX7 — 안쪽 요청·기다림 폴링은 세지 않는다)
 */
export function collapseActivity(entries: readonly ActivityEntry[]): ActivityRow[] {
  const out: (ActivityRow & { target: string })[] = [];
  for (const e of entries) {
    const last = out[out.length - 1];
    if (last !== undefined && last.tool === e.tool && last.result === e.result) {
      last.count += 1;
      last.seq = e.seq;
      if (last.target !== e.target) {
        last.target = "";
        last.text = activityText({ tool: e.tool, result: e.result, target: "" });
      }
      continue;
    }
    out.push({ seq: e.seq, at: e.at, tool: e.tool, result: e.result, text: activityText(e), count: 1, target: e.target });
  }
  return out.map(({ target: _target, ...row }) => row);
}

// ── 진행 중 머리 (UX7 E) ─────────────────────────────────────────

export interface JobProgress {
  step: number;
  total: number;
  title: string;
  doing: string | null;
  at: string;
}

export interface JobWaiting {
  kind: "credential" | "question" | "run";
  since: string;
}

export interface LastScreen {
  key: string;
  title: string | null;
  /** 편집기 캐시 썸네일 이름 (보호 화면이면 null — 이름만 보인다) */
  image: string | null;
}

/** "2/4 경로 걷기 — 타이틀 터치 → 로그인 팝업 기다리는 중" (없으면 빈 글) */
export function progressText(p: JobProgress | null | undefined): string {
  if (p == null) return "";
  const head = `${p.step}/${p.total} ${p.title}`;
  return p.doing != null && p.doing !== "" ? `${head} — ${p.doing}` : head;
}

/** 기다림 이유 한 줄 (실행은 n초째). 없으면 빈 글 */
export function waitingText(w: JobWaiting | null | undefined, nowMs: number = Date.now()): string {
  if (w == null) return "";
  if (w.kind === "credential") return "테스트 계정 등록을 기다리는 중";
  if (w.kind === "question") return "사람 답을 기다리는 중";
  const since = new Date(w.since).getTime();
  const secs = Number.isNaN(since) ? 0 : Math.max(0, Math.floor((nowMs - since) / 1000));
  return `실행 끝나기 기다림 ${secs}초째`;
}

/** 마지막 저장 화면 이름: 제목 (키), 제목이 없으면 키 */
export function lastScreenText(s: LastScreen | null | undefined): string {
  if (s == null) return "";
  return s.title != null && s.title !== "" ? `${s.title} (${s.key})` : s.key;
}

/** 진행 중 작업이면 폴링한다 */
export function activityLive(state: string): boolean {
  return state === "running" || state === "ending";
}

/** 폴링 간격 (ms) */
export const ACTIVITY_POLL_MS = 1_500;
