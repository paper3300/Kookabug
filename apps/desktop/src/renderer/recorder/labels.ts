// 녹화 화면 문구 (M4 계획 2.11, T9). 스토어·React를 모르는 순수 함수라 vitest로 문구를 고정한다
// (stepLabel.test.ts·statusText.test.ts). 글자 규칙(2.8): 원문 글자는 text_state가 ordinary인 스텝의 text만 쓴다.
// 비밀값·판정 중·확인 필요 스텝은 ● × 길이나 "판정 중"·"확인 필요"만 보인다
import type { daemonRpc } from "@kookabug/schema";

export type RecorderStep = daemonRpc.RecorderStep;
export type RecorderStateResult = daemonRpc.RecorderStateResult;
export type RecorderState = daemonRpc.RecorderState;
export type ReviewReason = daemonRpc.RecorderNeedsReviewReason;

/** 녹화 중 (단축키·임대권을 쥔) 상태 */
export const LIVE_STATES: ReadonlySet<string> = new Set(["starting", "recording", "paused"]);
/** 세션이 있고 다듬을 수 있는 상태 (스텝 목록이 보임) */
export const SESSION_STATES: ReadonlySet<string> = new Set(["starting", "recording", "paused", "stopped", "committing"]);

/** 스텝 줄 점 색 (시안: 번호 파랑, 비밀값 P·확인 V 주황, 대기 회색) */
export type DotTone = "step" | "special" | "wait";
/** 메모 색 (시안: 회색, 확인 필요 노랑, 비밀값 선택 필요 주황 글자) */
export type NoteTone = "muted" | "review" | "secret";

export interface StepLabel {
  /** 번호 칸 글자 (클릭 등 순번, 비밀값 P, 확인 V, 대기 빈칸) */
  mark: string;
  dot: DotTone;
  /** 노드 제목 (시안 '이미지 클릭 "강화"') */
  title: string;
  /** 원래 입력 (시안 'click (858, 562) · 00:09.4') */
  raw: string;
  note: string;
  tone: NoteTone;
}

/** 녹화 시각 "00:09.4" (분:초.십분의 일) */
export function formatStepTime(ms: number): string {
  const tenths = Math.max(0, Math.floor(ms / 100));
  const m = Math.floor(tenths / 600);
  const s = Math.floor((tenths % 600) / 10);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}.${tenths % 10}`;
}

/** 녹화 경과 "02:14" (상태 바·사이드바 REC) */
export function formatRecTime(ms: number): string {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(sec / 3600);
  const mm = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function seconds(ms: number | undefined): string {
  return `${((ms ?? 0) / 1000).toFixed(1)}s`;
}

/** 비밀값 스텝인가 (P) */
export function isSecretStep(step: RecorderStep): boolean {
  return step.kind === "text" && step.text_state === "secret";
}

/** 키를 아직 고르지 않은 비밀값 스텝 (커밋 secret_unresolved) */
export function secretUnresolved(step: RecorderStep): boolean {
  return isSecretStep(step) && (step.secret_key === null || step.secret_key === undefined);
}

/** 번호 칸: 클릭·키·글자·끌기·휠은 순번, 비밀값 P, 확인 V, 대기·지연은 빈칸 */
export function stepMarks(steps: readonly RecorderStep[]): Map<string, { mark: string; dot: DotTone }> {
  const out = new Map<string, { mark: string; dot: DotTone }>();
  let n = 0;
  for (const s of steps) {
    if (s.kind === "wait" || s.kind === "delay") out.set(s.step, { mark: "", dot: "wait" });
    else if (isSecretStep(s)) out.set(s.step, { mark: "P", dot: "special" });
    else if (s.kind === "check_text" || s.kind === "check_visible") out.set(s.step, { mark: "V", dot: "special" });
    else out.set(s.step, { mark: String(++n), dot: "step" });
  }
  return out;
}

function point(p: readonly [number, number] | undefined): string {
  return p === undefined ? "" : ` (${p[0]}, ${p[1]})`;
}

/** 글자 스텝의 보이는 글자: 일반 글자만 원문, 비밀값은 ●, 그 밖은 상태 */
export function typedText(step: RecorderStep): string {
  if (step.text_state === "ordinary" && typeof step.text === "string") return `"${step.text}"`;
  if (step.text_state === "secret") return "●".repeat(Math.max(1, step.text_len ?? 0));
  if (step.text_state === "pending") return "(판정 중)";
  return "(확인 필요)";
}

/** 원래 입력 줄 */
export function stepRaw(step: RecorderStep): string {
  const input = step.input ?? {};
  const at = ` · ${formatStepTime(step.t_ms)}`;
  switch (step.kind) {
    case "click": {
      const kind = input.button === "right" ? "right click" : input.button === "middle" ? "middle click" : input.count === 2 ? "double click" : "click";
      return `${kind}${point(input.point)}${at}`;
    }
    case "drag":
      return `drag${point(input.point)} →${point(input.end)}${at}`;
    case "scroll":
      return `scroll${point(input.point)} ${input.amount ?? 0}${at}`;
    case "key":
      return `key ${input.keys ?? ""}${at}`;
    case "text":
      return `type ${typedText(step)}${at}`;
    case "wait":
      return `wait ${seconds(input.gap_ms)}`;
    case "delay":
      return `delay ${seconds(input.gap_ms)}`;
    case "check_visible":
      return "assert visible";
    case "check_text":
      return "assert text";
  }
  return step.kind;
}

/** 확인 필요 이유 문구 (스텝 메모·띠) */
export const REVIEW_TEXT: Readonly<Record<ReviewReason, string>> = {
  geometry_unresolved: "화면이 바뀌던 중이에요 — REC 탭에서 영역을 고르세요",
  no_frame: "클릭 직전 화면이 없어요 — REC 탭에서 영역을 고르세요",
  window_undetermined: "어느 창에 들어간 입력인지 확실하지 않아요",
  ime_unknown: "입력기 상태를 확인하지 못했어요",
  cursor_moved_in_field: "칸 안에서 커서를 옮겼어요",
  field_box_unknown: "입력 칸을 정하지 못했어요",
  no_evidence: "비밀번호인지 확인하지 못했어요",
  cut_by_stop: "녹화가 끊긴 순간의 입력이에요",
  secret_overlap: "비밀번호 칸과 겹쳐 대상을 버렸어요 — 영역을 다시 고르거나 지우세요",
  wait_target_unknown: "기다릴 화면을 고르세요",
};

/**
 * 메모 줄. 비밀값 메모 뒤 절은 U16: 기본(D3, 기록 가림 꺼짐)은 "비밀값 선택 필요"만, 워크스페이스
 * record.redact_secrets가 켜졌을 때만 "· 재생 때 이 스텝은 스크린샷 생략"
 */
export function stepNote(step: RecorderStep, redactSecrets: boolean): { note: string; tone: NoteTone } {
  if (secretUnresolved(step)) {
    return { note: `비밀값 선택 필요${redactSecrets ? " · 재생 때 이 스텝은 스크린샷 생략" : ""}`, tone: "secret" };
  }
  if (isSecretStep(step)) {
    return { note: `비밀값 ${step.secret_key ?? ""}${redactSecrets ? " · 재생 때 이 스텝은 스크린샷 생략" : ""}`, tone: "muted" };
  }
  if (step.kind === "text" && step.text_state === "pending") return { note: "판정 중", tone: "muted" };
  // 사람이 "그대로 남기기"(keep)를 고르면 daemon이 needs_review를 비운다
  if (step.needs_review.length > 0) {
    return { note: step.needs_review.map((r) => REVIEW_TEXT[r] ?? r).join(" · "), tone: "review" };
  }
  const review = step.badges.filter((b) => b.severity !== "info");
  const shown = review.length > 0 ? review : step.badges;
  const note = shown.map((b) => b.message ?? b.code).join(" · ");
  return { note, tone: review.length > 0 ? "review" : "muted" };
}

export function stepLabel(step: RecorderStep, marks: ReadonlyMap<string, { mark: string; dot: DotTone }>, redactSecrets: boolean): StepLabel {
  const m = marks.get(step.step) ?? { mark: "", dot: "step" as const };
  const { note, tone } = stepNote(step, redactSecrets);
  return { mark: m.mark, dot: m.dot, title: step.node.title, raw: stepRaw(step), note, tone };
}

// ── 상태 문구 ────────────────────────────────────────────────────

/** 오류로 멈춘 까닭 (사이드바 맨 위 빨간 띠). 사람이 멈춘 것(user)은 null */
export function stopReasonText(reason: daemonRpc.RecorderStopReason | undefined): string | null {
  switch (reason) {
    case "hook_lost":
      return "녹화가 끊겼어요 — 그 뒤 입력은 녹화되지 않았어요";
    case "input_overflow":
      return "입력을 일부 놓쳐 녹화를 멈췄어요 — 그 뒤 입력은 녹화되지 않았어요";
    case "window_gone":
      return "게임 창이 닫혀 녹화를 멈췄어요 — 그 뒤 입력은 녹화되지 않았어요";
    case "storage_full":
      return "녹화 저장 공간이 가득 차 멈췄어요 — 그 뒤 입력은 녹화되지 않았어요";
    default:
      return null;
  }
}

/** 사이드바 머리 오른쪽·상태 줄 (시안 "REC 02:14"와 시안에 없는 상태 — 2.11 검수 M10) */
export function sidebarStateText(s: Pick<RecorderStateResult, "state" | "owned" | "counts">, elapsedMs: number): string | null {
  if (!s.owned) return SESSION_STATES.has(s.state) ? "다른 창에서 녹화 중이에요" : null;
  switch (s.state) {
    case "starting":
      return "녹화 준비 중…";
    case "recording":
      return `REC ${formatRecTime(elapsedMs)}`;
    case "paused":
      return "⏸ 일시정지 · 게임 입력을 녹화하지 않아요";
    case "stopped":
      return `녹화 끝 · 스텝 ${s.counts?.steps ?? 0}`;
    case "committing":
      return "저장 중…";
    default:
      return null;
  }
}

/** 상태 바가 빨강인가 (녹화 준비·녹화·일시정지, 소유 연결) */
export function statusBarRecording(s: Pick<RecorderStateResult, "state" | "owned"> | null): boolean {
  return s !== null && s.owned && LIVE_STATES.has(s.state);
}

/** 상태 바 항목 (시안 "녹화 중 02:14" · "SampleRPG 1280×720 · DPI 100%" · "스텝 6 · 템플릿 4" · 오른쪽 둘) */
export function statusBarItems(s: RecorderStateResult, elapsedMs: number): { left: string[]; right: string[] } | null {
  if (!s.owned) return SESSION_STATES.has(s.state) ? { left: ["다른 창에서 녹화 중"], right: [] } : null;
  const counts = `스텝 ${s.counts?.steps ?? 0} · 템플릿 ${s.counts?.targets ?? 0}`;
  const w = s.window;
  const win = w === undefined ? null : `${w.title} ${w.client_size[0]}×${w.client_size[1]} · DPI ${Math.round((w.dpi / 96) * 100)}%`;
  const head =
    s.state === "starting"
      ? "녹화 준비 중…"
      : s.state === "recording"
        ? `녹화 중 ${formatRecTime(elapsedMs)}`
        : s.state === "paused"
          ? `⏸ 일시정지 ${formatRecTime(elapsedMs)}`
          : s.state === "stopped" || s.state === "committing"
            ? `녹화 끝 · 스텝 ${s.counts?.steps ?? 0}`
            : null;
  if (head === null) return null;
  const live = LIVE_STATES.has(s.state);
  const left = [head, ...(win === null ? [] : [win]), ...(live || s.state === "stopped" ? [counts] : [])].filter((x, i) => !(i > 0 && x === head));
  return { left, right: live ? ["녹화 정지 Ctrl+Shift+R", "캡처 WGC · 훅 저수준"] : [] };
}

/** 녹화 알림 띠 문구 (경고 code → 문구). daemon이 message를 주면 그것 */
export function warningText(w: daemonRpc.RecorderWarning): string {
  if (w.message !== undefined && w.message !== "") return w.message;
  switch (w.code) {
    case "injected_ignored":
      return `다른 프로그램이 보낸 입력 ${w.count ?? 0}개는 녹화하지 않았어요`;
    case "popup_ignored":
      return "게임의 팝업 창 입력은 녹화하지 않아요";
    case "not_foreground":
      return "게임 창이 앞에 없어요 — 입력을 녹화하지 않는 중";
    default:
      return w.code;
  }
}

/** 오류 종류 → 문구 (시작·커밋 거부). 모르는 것은 daemon 문구 */
export function recorderErrorText(kind: string | null, message: string): string {
  switch (kind) {
    case "hotkey_unavailable":
      return "녹화 단축키를 등록하지 못해 녹화를 시작하지 않았어요";
    case "input_lease_busy":
      return "다른 실행이 입력을 쓰고 있어 녹화를 시작하지 못했어요";
    case "recording_active":
      return "실행 중에는 녹화를 시작할 수 없어요";
    case "window_gone":
      return "고른 창이 없어졌어요";
    case "capture_unsupported":
      return "이 창은 캡처할 수 없어요";
    case "hook_failed":
      return "입력 훅을 띄우지 못했어요";
    case "classification_pending":
      return "비밀번호 판정이 아직 끝나지 않았어요. 잠시 뒤 다시 저장하세요";
    case "text_review_required":
      return "비밀번호인지 확인이 필요한 입력이 있어요. 표시한 스텝에서 고르세요";
    case "secret_unresolved":
      return "비밀값을 고르지 않은 스텝이 있어요";
    case "target_missing":
      return "찾기 대상이 없는 스텝이 있어요. REC 탭에서 영역을 고르거나 스텝을 지우세요";
    case "secret_region_overlap":
      return "비밀번호 칸과 겹치는 영역은 쓸 수 없어요. 영역을 다시 고르세요";
    case "not_owner":
      return "다른 창에서 녹화 중이에요";
    default:
      return message;
  }
}

/** 저장(커밋) 단추를 막는 이유 — 띠를 다 처리해야 켜진다. 막지 않으면 null */
export function commitBlocker(steps: readonly RecorderStep[]): string | null {
  if (steps.some((s) => s.kind === "text" && s.text_state === "pending")) return "비밀번호 판정 중이에요";
  if (steps.some(secretUnresolved)) return "비밀값을 고르면 저장할 수 있어요";
  if (steps.some((s) => s.kind === "text" && s.text_state === "needs_review")) return "확인 필요한 입력을 먼저 고르세요";
  if (steps.length === 0) return "녹화된 스텝이 없어요";
  return null;
}
